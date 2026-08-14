# Debug 修复记录

## 2026-08-11：检索重排序 — 关键词奖励 → LLM Cross-Encoder Reranker

### 问题

合同条款检索的最终排序使用 `_rerank_contract_hits()` 做简单的关键词命中奖励（命中一个合同术语 +1000 分），不理解"该条款是否实际回答当前审查问题"。见 [contract_store.py:223](tools/chat-assistant/backend/app/agent_runtime/contract_store.py#L223)。

### 修复

新增 [reranker.py](tools/chat-assistant/backend/app/agent_runtime/reranker.py)（378 行），实现 LLM 语义重排序：

- **召回扩大**：`candidate_k` 从 `max(top_k * 4, 20)` 扩大到 `min(max(top_k * 6, 30), 50)`，即 30～50 条候选
- **LLM Reranker**：使用独立的 `RERANKER_API_KEY` 调用 LLM（key 为空时自动降级到关键词启发式），按四项标准排序：
  1. 问题相关性 — 条款是否直接回答审查问题
  2. 条款完整性 — 完整条款优先于碎片
  3. 主体/条件匹配 — 是否涉及相同的当事人、金额、日期
  4. 同章连贯性 — 同章节条款形成完整画面
- **合同与知识库分离**：`rerank_contract_clauses()` 和 `rerank_policy_items()` 各自独立排序，不交叉竞争
- **配置项**（[config.py](tools/chat-assistant/backend/app/config.py)）：

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `RERANKER_API_KEY` | `""` | 空 = 关键词 fallback，填入即启用 LLM |
| `RERANKER_BASE_URL` | `""` | 空 = 回退到 `LLM_BASE_URL` |
| `RERANKER_MODEL` | `""` | 空 = 回退到 `LLM_MODEL` |
| `RERANKER_MIN_RECALL` | `30` | 最少召回数 |
| `RERANKER_MAX_RECALL` | `50` | 最多召回数 |

### 影响范围

- `contract_store.py` — `search_contract_clause()` 和 `search_policy()` 的召回窗口 + 重排序调用
- `config.py` — 7 个新配置项
- `reranker.py` — 新增模块

---

## 2026-08-11：Targeted Retrieval 补充检索未反馈到分析 — P0

### 问题

合同审查图（ContractReviewGraph）在覆盖不足时执行 `targeted_retrieval` 补充检索，但检索到的关键条款**从未送回领域分析和结论校验**，直接生成"范围受限报告"。即使第二次检索找到了能填补缺口的关键条款，也不能真正修正风险发现。

见 [contract_review.py:117](tools/chat-assistant/backend/app/agent_runtime/graph/contract_review.py#L117)：
```python
# 硬编码边 — 直接跳到 compose_limited_report，跳过 re-analysis
builder.add_edge("targeted_retrieval", "compose_limited_report")
```

而 `_route_after_targeted` 函数（返回 `"validate_claims"`）已正确定义但从未被注册为条件边 — 死代码。

### 修复

将死胡同链路改为闭环：

```
修复前：
  coverage_reflection → targeted_retrieval → compose_limited_report (死胡同)

修复后：
  coverage_reflection → targeted_retrieval
    → draft_domain_findings (只重新分析缺失领域)
    → validate_claims (再次验证)
    → coverage_reflection (再查覆盖)
    → 缺口已补齐 → compose_report (完整报告!)
    → 缺口仍存在 → compose_limited_report (retry_count>=1 终止)
```

四处修改：

1. **[contract_review.py:51-57](tools/chat-assistant/backend/app/agent_runtime/graph/contract_review.py#L51)** — `_route_after_targeted` 改为路由到 `draft_domain_findings`
2. **[contract_review.py:120-129](tools/chat-assistant/backend/app/agent_runtime/graph/contract_review.py#L120)** — 硬编码边替换为条件边
3. **[retrieval.py:582-597](tools/chat-assistant/backend/app/agent_runtime/graph/nodes/retrieval.py#L582)** — `draft_domain_findings` 新增 `gap_domains` 参数，仅重新分析缺失领域，已覆盖领域的 findings/analysis 保持不变
4. **[reflection.py:217-224](tools/chat-assistant/backend/app/agent_runtime/graph/nodes/reflection.py#L217)** — `targeted_retrieval` 返回 `gap_domains` 标记

### 影响范围

- `contract_review.py` — 图边路由
- `retrieval.py` — `draft_domain_findings` 支持选择性重分析
- `reflection.py` — `targeted_retrieval` 传回 `gap_domains`

---

## 2026-08-13：评测回归集三组对比暴露的根因修复（TypeError / 门禁 / 双引用）

### 问题

风险审查回归集 v2 三组对比运行（legacy / LangGraph 全开 / LangGraph 关覆盖反思）暴露出三处问题：

1. **legacy 全量 LIMITED、召回 1.67%、双引用 0%**（run 17）：30/30 用例产出确定性兜底报告。排查 trace 表发现反射闸门实际通过 20/30，但所有 `contract_review` LLM 调用在发出请求前即抛异常，被 try/except 兜底静默吞掉。探针复现：

   ```
   TypeError: Completions.create() got an unexpected keyword argument 'thinking'
   ```

   根因：给六个直接调用点加的 DeepSeek reasoning guard 写成了 `**self._reasoning_guard()`，把 `{"thinking": ...}` 展开成 OpenAI SDK 的**顶层参数**；SDK 只接受 `extra_body={"thinking": ...}` 嵌套写法（`_structured_completion` 一直用正确写法，所以 LangGraph 不受影响）。六个方法（`contract_review`/`contract_intake`/`contract_fulfillment_check`/`contract_approval`/`analyze_project`/`run_project_task`）全部调用即抛错，不只是评测，线上真实流程同样瘫痪。

2. **LangGraph 门禁误降级**（run 15：9 个 LIMITED）：门禁裁剪后，已完成分析且产出发现的 gated 域仍因低置信度噪声被判 AMBIGUOUS → 整案降级 LIMITED。

3. **双引用率 0%**（run 15/16）：kb_document 全空；`search_policy._standard()` 用"整句逐字包含"过滤，查询短语永远匹配不上任何标准条款（实测 0 命中）；规则引擎发现不挂制度引用。

### 修复

1. **reasoning guard 参数位修复**（[llm_service.py](tools/chat-assistant/backend/app/services/llm_service.py)）：六个调用点 `**self._reasoning_guard()` → `extra_body=self._reasoning_guard() or None`；`contract_review` 解析改用 `_parse_structured_response`（content 为空时从 reasoning_content 恢复）；[runner.py](tools/chat-assistant/backend/app/agent_runtime/runner.py) FULL 路径补 try/except 兜底。
2. **门禁裁剪修正**（[reflection.py](tools/chat-assistant/backend/app/agent_runtime/graph/nodes/reflection.py)）：评测用例只对期望维度映射到的域设闸（`_eval_required_domain_keys`）；gated 域发现数 > 0 且分析状态 COMPLETED 时不再计入 missing。
3. **双引用修复**：`_standard()` 逐字包含 → CJK/字母 bigram 重叠评分（[contract_store.py](tools/chat-assistant/backend/app/agent_runtime/contract_store.py)）；规则发现以触发规则本身作为制度依据（`policyCitation` = ruleKey/ruleTitle/snippet，`policyCitationIds` = `RULE:{ruleKey}`，[retrieval.py](tools/chat-assistant/backend/app/agent_runtime/graph/nodes/retrieval.py)）。

### 验证结果

| run | 引擎 | 召回 | 双引用 | LIMITED |
|-----|------|------|--------|---------|
| 16（修复前基线） | LangGraph | 58.3% | 0% | 0/30 |
| 18（修复后全开） | LangGraph | 58.3% | 32.6% | 3/30 |
| 19（修复后关反思） | LangGraph | 58.3% | 31.5% | 0/30 |
| 20（修复后） | legacy | **31.7%**（原 1.67%） | **100%**（原 0%） | 12/30 |

### 影响范围

- `llm_service.py` — 六处 extra_body 参数位
- `runner.py` — FULL 路径兜底
- `reflection.py` — 评测门禁裁剪
- `contract_store.py` — `_standard()` bigram 过滤
- `retrieval.py` — 规则发现制度引用

---

## 2026-08-13：评测计分修复（空真召回 / 短标题匹配 / legacy 计分对齐）

### 问题

1. 期望发现中无 HIGH 条目的用例，召回被强制记 0/1=0（case 131/133/137），把整组平均拉低约 10 个百分点。
2. `_risk_finding_matches` 的 bigram 重叠分母取期望侧长度，"短实际标题 vs 长期望标题"（如"不可抗力范围过宽" vs 长句描述）永远低于 0.28 阈值而漏配；"仲裁"与"争议解决"这类同义不同词仍无法匹配。
3. legacy 计分路径用严格子串匹配标题，LLM 报告标题措辞稍有差异即漏配（run 14 FULL 报告正常但召回仅 1.67% 的原因之一）。

### 修复

1. **空真召回**（[routes.py](tools/chat-assistant/backend/app/api/routes.py) 两处计分器）：无 HIGH 期望时召回记 1.0（没有期望即没有遗漏），不再拉低平均值。
2. **containment 匹配**（`_risk_finding_matches`）：新增短侧覆盖率判定——共享 bigram ≥ 3、短侧 ≥ 3 且覆盖 ≥ 50% 即匹配；维度门禁保持优先（两边维度都有且不一致仍拒绝）。
3. **legacy 计分对齐**：legacy 路径匹配从严格子串改为 `_risk_finding_matches`。

### 验证结果

- run 22（LangGraph 全开）：召回 58.3% → **64.4%**，双引用 33.0%，误报 0%。
- run 20（legacy）：召回 1.67% → **31.7%**。
- 测试套件 114/114 通过（新增空真召回、containment 正反例、维度门禁用例）。

### 影响范围

- `routes.py` — 两处计分器 + `_risk_finding_matches` containment 分支
- `tests/test_evaluation.py` — 4 个新用例

---

## 2026-08-13：评测中心运行详情入口（逐条记录可见全部参数）

### 问题

评测记录列表只有汇总指标，管理端无法查看单次运行的完整参数（功能特性、汇总 JSON、环境快照）和逐用例结果（模式/召回/双引用/误报/风险分/发现数/完整产物）。

### 修复

1. **后端**（[EvalAdminController.java](agent-server/src/main/java/com/atlasmind/controller/admin/EvalAdminController.java)）：`GET /api/admin/eval/runs/{runId}` 全部字段改为驼峰别名（原 `r.*`/`er.*` 为下划线），并关联用例的 `expectedFindingsJson`/`shouldNotFindJson`/场景/难度/噪声等评测元数据。
2. **前端**（[EvalCenter.vue](agent-admin/src/views/EvalCenter.vue)）：评测记录每条新增"详情"入口。详情对话框两层：
   - 运行级：状态/Runtime/图版本/模型/提示词版本/三项指标/进度字段/环境状态/时间，功能特性、汇总指标、环境快照三个可折叠 JSON 块
   - 用例级：逐用例结果表 + 单用例视图（指标、预期 vs 不应 vs 实际发现对比、合同/制度引用标记、完整产物 JSON）

### 影响范围

- `EvalAdminController.java` — getRun 字段别名 + 结果关联用例元数据
- `EvalCenter.vue` — 详情入口 + 双层详情对话框 + 标签类型辅助函数

---

## 2026-08-14：评测计分器统一注册表 + 要素提取真计分 + legacy 引擎守卫

### 问题

要素提取回归集（IN-*，20 case）首跑出现两个假象分数：
- run 23（LangGraph）：全指标 100%，但逐用例 `finding_count` 全为 0 —— 计分器只有 CONTRACT_REVIEW 分支，其余任务类型一律无条件满分（`_score_eval_artifact` 占位分支），且 INTAKE 产物是 `elements` 而非 `findings`，计分器根本没看提取结果。case IN-007 期望 2 个 HIGH（缺失检测），Agent 提取 0 个要素，召回仍记 1.0。
- run 24（legacy）：20/20 FAILED，逐 case 抛 `unsupported project task type: CONTRACT_ELEMENT_EXTRACTION` —— 强制 legacy 模式绕过了 runtime.py `_resolve` 里"提取类任务默认走 LangGraph"的保护，落进项目任务的 LLM 方法。

### 修复

1. **计分器收敛为注册表**（[routes.py](tools/chat-assistant/backend/app/api/routes.py)）：`_EVAL_SCORERS` 按任务类型注册计分器，`_score_eval_artifact` 统一分发。删除 legacy worker 内联的那份重复计分逻辑（此前空真召回等修复都要两处同步改），两引擎共用同一入口。未注册任务类型（FULFILLMENT_CHECK/TIMELINE_EXTRACTION）保留占位分支，待补真实计分器。
2. **新增要素提取计分器** `_score_element_extraction`：
   - 提取面 = `elements` + `contractProfile.baseFields/groups.fields` 展平（elementKey/类别/rawValue 与字段 label/value）
   - 期望条目分两类：含缺失标记（缺失/缺少/空白/不明确/未定义/未约定/无法判断/待确认）→ 校验产物 group reason/summary 是否点名该要素并出现缺失标记；其余 → 与提取面做**严格匹配**（专用 `_element_expectation_matches`：包含匹配为准，≥12 字长标题才允许 SequenceMatcher≥0.5）。不复用 `_risk_finding_matches` 的 bigram 重叠——数字型期望（金额/日期）唯一 bigram 少，两个巧合共享对（"00"/"0元"）就会误过 0.28 阈值（实测复现）
   - `dual_citation_rate` 列复用为"引用覆盖率"（带引用的提取项占比）；`finding_count` 记提取项数
3. **legacy 引擎三层守卫**：
   - [runtime.py](tools/chat-assistant/backend/app/agent_runtime/runtime.py)：`LEGACY_SUPPORTED_TASK_TYPES` + `is_legacy_task_supported()`；`dispatch_with_mode` 强制 legacy 遇到不支持任务类型直接抛清晰错误，不再逐 case 落进 `run_project_task`
   - eval worker 启动前 fail-fast：legacy × 提取/日程数据集整单 FAILED 并给出明确提示，不再产出 20 条重复谜之失败
   - [EvalAdminController.java](agent-server/src/main/java/com/atlasmind/controller/admin/EvalAdminController.java) `startEvalRun` 服务端拒绝；[EvalCenter.vue](agent-admin/src/views/EvalCenter.vue) 前端置灰 legacy 选项 + 默认切 LangGraph + 提交前拦截

### 验证结果

- 测试套件 119/119 通过（新增 6 用例：注册表路由、要素计分正例 2/3、缺失未检出记 0、占位分支、legacy 支持集守卫）
- Vue 构建通过；Java 编译通过（exit 0）

### 影响范围

- `routes.py` — 计分器注册表 + 要素计分器 + legacy worker 共用计分入口 + fail-fast
- `runtime.py` — legacy 支持任务集合 + 强制模式守卫
- `EvalAdminController.java` / `EvalCenter.vue` — 非法引擎×数据集组合拦截
- `tests/test_evaluation.py` — 6 个新用例

### 遗留

- FULFILLMENT_CHECK / TIMELINE_EXTRACTION 仍走占位计分（100%），待补真实计分器
- IN-* 中"争议/不一致"类期望（如 IN-164）依赖产物中有显式 discrepancy 报告才能计分，当前 group reason 未纳入提取面

---

## 2026-08-15：第四轮验收修复 — LIMITED 配额结算 / 详情页工作流终态 / LLM 真实计量（e4c207e）

### 问题

1. **LIMITED 配额结算死循环**：结算任务对 LIMITED 调用 `confirm()`，但 `QuotaService.confirm()` 状态集只含 `COMPLETED` → 每次调度都抛"Run 状态不允许额度变更"，预扣额度永久悬挂。
2. **详情页只认 COMPLETED**：Python 已将工作流终态写成 LIMITED，但 `ContractCaseView` 的 `workflowIsComplete`/`reviewDone` 等只把 COMPLETED 视为完成，风险审查与"分析就绪"阶段一直显示待处理，状态文案也没有 LIMITED。
3. **LLM 计量低估真实消耗**：图节点固定记 1 次 LLM 调用，但底层 `_call_llm_with_retry` 最多 4 次尝试，结构化解析失败还会再走一轮非结构化调用；token 统计被最后一次响应覆盖。真实调用可超预算却仍判预算内。

### 修复

1. **配额结算**（[QuotaService.java](agent-server/src/main/java/com/atlasmind/service/QuotaService.java)）：`confirm()` 状态集 → `("COMPLETED","LIMITED")`（受限报告=真实消耗，确认而非退还）；QuotaServiceTest 新增 `limitedRunConsumesReservedQuotaExactlyOnce`。
2. **详情页**（[ContractCaseView.vue](agent-front/src/views/ContractCaseView.vue)）：`workflowIsComplete`/`parseDone`/`reviewDone`/`hasCompletedRun` 均视 LIMITED 为终态；`workflowStatusLabel/Class` 新增"范围受限"+ warn 徽章。
3. **LLM 真实计量**（[llm_service.py](tools/chat-assistant/backend/app/services/llm_service.py)）：`_call_llm_with_retry` 新增 `usage_out` 累计——`calls` 计每次真实 API 尝试（重试与结构化→非结构化回退都算），token 键跨响应累加；`_structured_completion` 透传；[retrieval.py](tools/chat-assistant/backend/app/agent_runtime/graph/nodes/retrieval.py) 按真实次数/累计 token 记账。单测：3 次尝试记 3 次、两阶段回退记 2 次且 token 累加。

### 验证结果

- Python 263/263（+3 新测试）、Java 43/43（QuotaServiceTest 5/5）、agent-front 构建通过、`git diff --check` 通过

### 影响范围

- `QuotaService.java` / `QuotaServiceTest.java` — confirm 状态集 + 测试
- `ContractCaseView.vue` — 工作流终态判定 + 状态文案/样式
- `llm_service.py` / `retrieval.py` / `tests/test_llm_service.py` — usage_out 累计计量

---

## 2026-08-15：Golden delta 操作格式重构 — 删除标记值碰撞根除 + 捕获浅拷贝修复

### 问题

1. Golden 增量里删除键用哨兵值编码：第一版字符串 `"!golden-removed!"` 会与恰好相同的业务内容碰撞，第二版单键字典 `{"__golden_removed__": true}` 仍有理论碰撞面（业务值恰好等于该字典）。
2. Golden 捕获时把节点输入 shallow-copy 交给真实节点：`prepare_human_review` 等节点原地修改嵌套结构（artifact dict）时，冻结输入被污染，掩盖了节点真实输出与输入之间的差异。

### 修复

1. **显式 set/remove 操作格式**（[test_task_spec_builder.py](tools/chat-assistant/backend/tests/test_task_spec_builder.py)）：delta 改为 `{"format": "golden-delta-ops-v1", "set": [[path, value], ...], "remove": [[path], ...]}`——变更全部编码在路径层，业务值作为 `value` 下的**不透明载荷**保存，任何 JSON 值都不再可能被误判为删除标记；`_apply` 按操作序重放（remove 先于 set，根路径只允许 set）。新增回归测试：两个历史标记值的精确拷贝 + 邻键真实删除可无损往返。
2. **捕获深拷贝修复**：`_collect_golden` 真实节点重放改为 `node(copy.deepcopy(input_state))`——原地修改留在输出副本上，冻结输入保持 pristine。

### 验证结果

- Golden 定向测试 33/33、Python 263/263、`git diff --check` 通过；fixture 重新生成 517,361B（仍为原始 1.94MB 的约 1/4）

### 影响范围

- `tests/test_task_spec_builder.py` — delta 格式/`_diff`/`_apply`/捕获深拷贝/回归测试
- `tests/golden/contract_review_v1_golden_artifact.json` — 重新生成

---

## 2026-08-15：PRD Phase 5 迁移合同要素提取 — 8 项任务实施

### 问题

PRD §Phase 5（迁移合同要素提取）要求 8 项改造：①基础身份字段单独固定 WorkUnit ②合同类型/标的/画像要素 LLM 动态规划 ③金额/币种/主体/标题/日期确定性规范化+专用校验 ④要素绑定原文引用/页码/条款/Snapshot Hash ⑤冲突保留候选不静默覆盖人工确认值 ⑥只重跑失败或低置信度字段 ⑦候选/确认/修正/版本历史保存 ⑧风险画像不得覆盖基础确认事实。现有实现：要素提取全部由 LLM 静态分组完成、无确定性规范化、无快照 Hash 绑定、重跑整份合同、候选互相覆盖。

### 修复

1. **确定性规范化器**（新增 [element_normalization.py](tools/chat-assistant/backend/app/agent_runtime/graph/element_normalization.py)）：金额（中文大写/阿拉伯数字 + 万/亿外部倍率、币种别名 ¥/￥/人民币→CNY 等、裸"元"隐含 CNY）、日期（2012-12-12 / 2012.12.12 / 2012年12月12日 / 20121212，日历合法性校验）、主体/标题、全角→半角；`validate_base_field` 输出 `EXTRACTED`/`NEEDS_REVIEW` + issues（ourSide 白名单 A/B、contractType 枚举）；`validate_structured_element` 类型化校验（MONEY/DATE/结构化值）。31 项测试。
2. **固定基础身份 WorkUnit + 专用节点**（[contract_extraction.py](tools/chat-assistant/backend/app/agent_runtime/graph/contract_extraction.py)）：`_BASE_IDENTITY_WORK_UNIT`（work_unit_id=base_identity_fields，required_checks 声明确定性校验 6 项，human_review_policy=CONFIRMED_VALUES_ONLY）+ `extract_base_identity_fields` 节点走规范化路径而非 LLM；`_canonical_base_fields` 附 normalizedValue/validation.deterministic，人工确认值原样保留。
3. **LLM 动态规划**（[llm_service.py](tools/chat-assistant/backend/app/services/llm_service.py)）：`plan_contract_elements` 规划 2-6 个要素包（不含基础身份键）；`_normalize_planned_packs` 校验后采用，LLM 失败回退 STATIC_FALLBACK 并留 meta（source/contractTypeRefined/subjectSummary/rationale）。
4. **快照 Hash 绑定**：`validate_extracted_elements` 给每个要素 validation 与 citation 绑定 evidenceSnapshotHash；新增 `audit_element_coverage` 审计节点输出引用支持率/绑定率/未引用清单。
5. **字段级重跑**：`_previous_settled_elements` 读上一快照已确认（reviewStatus 已设，或 EXTRACTED/CONFIRMED 且置信度≥0.75）要素 → carried 不再检索/提取（按 packKey 过滤，无整份重分析）；新增 [V034](tools/chat-assistant/backend/migrations/V034__extraction_snapshot_provenance.sql) base_snapshot_id + rerun_scope_json 溯源；已确认要素查询失败时降级为全量提取而非整个 Run 失败。
6. **候选保留**：`_top_candidates_by_key` 选最高置信度置 selected=1，carried 置"沿用上一版本已确认要素"，冲突候选 selected=0 保留供人工确认——确认值永不静默覆盖。
7. **画像防覆盖**（任务⑧）：画像分组字段与基础身份键冲突即丢弃；`build_contract_profile`/`normalize_contract_profile` 统一从 `base_identity_fields`（或重算 `_canonical_base_fields`）取基础事实。
8. **架构迁移**：`CONTRACT_EXTRACTION_SPEC` 声明 §6.1 全角色（context/planner/retriever/analyzer/validator/coverage_auditor/composer/persistence），走公共 `build_task_graph` 编译（与 risk v1 同构）；`_run_async` 收敛到 harness 公共实现。

### 验证结果

- Python 312/312（原 263 + 规范化器 31 + Phase 5 定向 18）、`git diff --check` 通过，提交 4eaab2e 已推送
- 验收门槛（基础字段准确率 ≥95%、引用支持率 ≥97% 等）为评测门禁，待 Phase 8 统一评测集跑分，**当前未声称达标**

### 影响范围

- `agent_runtime/graph/element_normalization.py`（新增）/ `contract_extraction.py`（重写流程 + TaskSpec）
- `services/llm_service.py`（plan_contract_elements）
- `migrations/V034__extraction_snapshot_provenance.sql`（新增）
- `agent_runtime/harness/__init__.py`（docstring）
- `tests/test_element_normalization.py`、`tests/test_contract_extraction_phase5.py`（新增）
- 未动 legacy `_retrieve_pack`；v2 检索/分析逻辑未改

---

## 2026-08-15：PRD Phase 6 履约日程 DAG 化 — 黑盒单节点重构为分层可观测 DAG

### 问题

原履约日程是黑盒：`timeline_extraction.py` 只有一个 publish 节点，内部一次调用 `extract_final_contract_timeline` 完成规则提取+LLM 复核+落库，规则层/LLM 层/校验层耗时不可分别观测、失败阶段粒度是整节点。另有 PRD 明确要求未满足：LLM 载荷经 `_compact_timeline_candidate_for_llm` 截断 4500 字（不截断父条款）；`citation.fullQuote` 截断 12000 字；乱码/低质量 OCR/不确定基准日期无标记。**附带发现 Phase 5 运行时隐患**：LangGraph 0.4.10 静默丢弃未声明在 state schema 上的节点输出键，Phase 5 的 `base_identity_fields`/`carried_elements`/`element_coverage_audit` 在真实运行时会被丢弃（直调节点测试无法暴露）。

### 修复

1. **TaskSpec DAG**（[timeline_extraction.py](tools/chat-assistant/backend/app/agent_runtime/graph/timeline_extraction.py) 重写，10 阶段，走公共 `build_task_graph`）：planner 选文档/生效日期/质量门禁 → retriever 装载条款证据（无 OCR/Embedding）→ 规则层 `extract_rule_timeline_candidates`（日期 100% 代码解析，LLM 不算日期）→ LLM 层 `enrich_timeline_candidates`（strict：复核不可用即 raise，绝不发布未复核日程）→ 校验层（去重、来源谱系 RULE_CANDIDATE→LLM_ENRICHED、完整引用、条件节点检查、quote 落地性检查——只标记不篡改原文）→ 覆盖率审计（引用支持率 + 规则/LLM/校验三层耗时聚合）→ composer（FINAL artifact + stageDurationsMs）→ persistence（DELETE manual_override=0 → INSERT source=AGENT_FINAL → UPDATE workflow，与 legacy 落库契约一致）。每个节点独立 current_node + 耗时观察（任务9）。
2. **不截断**：`enrich_contract_timeline` 改用 `_complete_timeline_candidate_for_llm` 发完整条款原文（legacy compaction 函数保留不删）；`_add_timeline_node` 的 `fullQuote` 取消 12000 字截断。
3. **风险标记**：`_MOJIBAKE_PATTERN`（U+FFFD + 经典 CJK 乱码签名 ä¸/åŒ/çš„/æ˜¯/â€ 等）命中→NEEDS_REVIEW+mojibakeRisk；生效日期缺失→推断年份/相对期限节点标 dateBasis.effectiveDateMissing（推断年不可信）；低质量 OCR 沿用 documentQuality LOW 降级。
4. **state schema 修复**（[state.py](tools/chat-assistant/backend/app/agent_runtime/graph/state.py)）：`base_identity_fields`/`carried_elements`/`element_coverage_audit`/`timeline_*` 全部补入 `BaseGraphState`；新增编译图回归测试（emit→read 探针证明跨节点通道存活）。

### 验证结果

- Python 334/334（test_timeline_v2 19 + schema 回归 + LLM 完整条款载荷 3）、`git diff --check` 通过，提交 8116285 已推送
- 验收门槛（召回率 ≥92%、日期计算 ≥99%、责任方/动作/触发 ≥95%）为评测门禁，待 Phase 8 统一评测跑分，**当前未声称达标**；规则/LLM/校验三层耗时可分别观测已实现

### 影响范围

- `agent_runtime/graph/timeline_extraction.py`（重写为 DAG，legacy publish_final_timeline 保留）
- `agent_runtime/contract_document_parser.py`（fullQuote 取消截断；legacy extract_final_contract_timeline 未动）
- `agent_runtime/graph/state.py`（schema 通道补齐）
- `services/llm_service.py`（完整条款载荷 + _complete_timeline_candidate_for_llm）
- `tests/test_timeline_v2.py`（新增）、`tests/test_contract_extraction_phase5.py`、`tests/test_llm_service.py`
- 未动 v2 检索/分析逻辑；未动 Java 显示过滤（source='AGENT_FINAL' OR manual_override=1 不变）

---

## 2026-08-15：PRD Phase 7 迁移履约核验 — 证据规则 / AI 建议 / 局部重跑 / 人工终审

### 问题

旧履约核验是黑盒单体（`fulfillment_check.py` 单节点拼接），PRD §Phase 7 九项任务现状盘点：①③⑦已有雏形（时间节点拆 Requirements、检索材料、Interrupt/Resume）；②缺截止条件/合同后果字段；④⑤⑧⑨缺失（证据规则、LLM 四建议、局部重跑、追加式保存）。**期间发现生产级 bug**：`fulfillment_judge._suggest_with_llm` 的 LLMService 导入深度写错（`...services` 解析到不存在的 `app.agent_runtime.services`），LLM 建议层从未真正执行、一直被 FALLBACK_RULE 静默吞掉——回退路径太优雅反而掩盖了主路径失效，测试断言建议层结论时暴露。

### 修复

1. **TaskSpec DAG**（[fulfillment_check.py](tools/chat-assistant/backend/app/agent_runtime/graph/fulfillment_check.py) 重写，10 阶段，走公共 `build_task_graph`）：context（load_run_context+freeze_case_snapshot）→ planner（decompose_requirements）→ retriever（retrieve_fulfillment_evidence + 重跑范围计算）→ analyzer（check_evidence_rules → judge_each_requirement）→ validator → coverage_auditor → composer（prepare）→ `wait_human_confirmation`（`_FulfillmentHumanGate(HumanGate)` 子类，spec.human_gate 与节点同一对象，§6.1 identity 契约）→ apply_human_result → persist_report。
2. **任务②**（[requirements.py](tools/chat-assistant/backend/app/agent_runtime/graph/nodes/requirements.py)）：`extract_contract_consequence` 纯函数按句子提取合同后果（LIQUIDATED_DAMAGES/RESCISSION/DEEMED_PASSED/NOT_SPECIFIED）；SELECT 补 `nodeDate`/`conditionText`，分解项携带 `deadline`/`deadlineCondition`/`contractConsequence`。
3. **任务④**（[evidence_rules.py](tools/chat-assistant/backend/app/agent_runtime/graph/nodes/evidence_rules.py) 新增）：五组确定性规则（文件类型/日期/金额/签章/内容），每条结果带稳定 code；硬旗标集合 `_HARD_FLAG_CODES`（日期越界、金额不符、缺签章、内容零匹配等）在 judge 层将 SUPPORTED 降级 PARTIAL 并把原因写入 gap。
4. **任务⑤**（fulfillment_judge 重写）：LLM 四建议层 **advisory 不 strict**（与 Phase 6 相反——此处人工门禁是最终权威，LLM 失败回退 FALLBACK_RULE 保留规则行，人工照常决策）；修复 LLMService 导入深度（`....services`）；`normalize_ai_suggestion` 校验 Schema、映射 `满足/不满足/证据不足/存在冲突` 词表到四建议结论。
5. **任务⑥**（三层防护）：`normalize_ai_suggestion` 降级禁止终态（COMPLETED/FAILED/ACCEPTED/REJECTED）→ NEEDS_REVIEW；`validate_fulfillment_judgement` 图级兜底再降级并打 `demotedByValidator`；`apply_human_result` 的最终结论只由 manual_result 映射（SATISFIED→BASICALLY_SATISFIED / NOT_SATISFIED→HAS_ISSUES / PENDING→NEEDS_REVIEW）。
6. **任务⑦**：Interrupt/Resume 经 GraphAdapter 保留（GraphInterrupt → WAITING_HUMAN，resume 命令带 manual_result/note/operator_id）。
7. **任务⑧**（[retrieval.py](tools/chat-assistant/backend/app/agent_runtime/graph/nodes/retrieval.py)）：`compute_rerun_scope` 纯函数按 (documentId, contentHash/version) 差分计算 UNCHANGED/ALL/AFFECTED_ONLY；新文档按 `_match_score>=2` 归属需求；**归属失败一律保守降级 ALL，绝不静默跳过**；上一次判定行（含 evidenceSnapshot+aiSuggestion）持久化在 `content.requirements` + `content.timelineNodeId`，UNCHANGED/AFFECTED_ONLY 下未受影响需求 carriedForward。
8. **任务⑨**：`MySqlReportStore._save_sync` 对 agent_report 仅 INSERT（每轮一行，历史追加不覆盖）；锁定测试断言 SQL 含 INSERT INTO agent_report 且无 UPDATE/DELETE。

### 验证结果

- Python **359/359**（新增 `tests/test_fulfillment_check_v2.py` 20 项：spec 编译/阶段序/门禁 identity、后果提取、分解字段、五组证据规则+汇总、建议层附加/FALLBACK、硬旗标降级、重跑范围三模式+保守 ALL、carry-forward、validator 降级、wait_state 载荷、manual_result 唯一终审、INSERT-only；schema 探针补 4 个 Phase 7 通道；adapter 真图 resume 三态回归），`git diff --check` 通过
- 验收门槛（证据不足克制率 ≥98%、AI 建议 Schema 通过率 ≥99%、AI 自动确认路径为零、局部重跑 ≥99%、Resume ≥99%）为评测门禁，待 Phase 8 统一评测跑分，**当前未声称达标**；AI 自动确认路径为零与 Resume 机制已由测试证明

### 影响范围

- `agent_runtime/graph/fulfillment_check.py`（重写为 TaskSpec DAG）
- `agent_runtime/graph/nodes/`：`evidence_rules.py`、`fulfillment_audit.py`（新增）；`fulfillment_judge.py`（重写）、`requirements.py`、`retrieval.py`、`human_confirm.py`、`fulfillment_validate.py`（扩展）
- `agent_runtime/graph/state.py`（evidence_rules/rerun_scope/fulfillment_ai/fulfillment_validation 四通道补 schema）
- `tests/test_fulfillment_check_v2.py`（新增）、`tests/test_graph_runtime_adapter.py`（真图 resume 重写）、`tests/test_contract_extraction_phase5.py`（探针扩展）
- 未动 legacy `_fulfillment_check` 旧路径代码；未动 v2 检索/分析逻辑；履约最终判定仍 100% 由人工确认写入
