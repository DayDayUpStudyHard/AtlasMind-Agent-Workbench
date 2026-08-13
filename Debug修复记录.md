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
