# Phase 0 冻结基线与接口审计报告

> 日期：2026-08-14
> 对应 PRD：[通用 Evidence Agent Harness 与高召回 DAG 改造](./prd-evidence-agent-harness-high-recall-dag-2026-08-14.md) §23 Phase 0
> 冻结基线代码版本：`ae894cc`（master）
> 状态：✅ runs 25-29 全部完成，基线已冻结（见 §2.1）

---

## 1. 交付物清单

| PRD Phase 0 交付物 | 状态 | 位置 |
|---|---|---|
| 基线报告 | ✅ 本文件 | docs/phase0-baseline-report-2026-08-14.md |
| Graph 接口清单 | ✅ §4 | 本文件 §4 |
| Golden Dataset v1 | ✅ 已入库 | agent_eval_dataset id=20/21/22；seed 脚本 scripts/seed_golden_datasets.py |
| 不兼容变更清单 | ✅ §6 | 本文件 §6 |

Phase 0 任务逐项核对（PRD §23）：

| # | 任务 | 状态 |
|---|---|---|
| 1 | 冻结当前 Graph v1 的评测运行 | ✅ 后台执行中（runs 25-29，见 §2） |
| 2 | 记录风险、要素、日程和履约核验现有指标 | ✅ §2（含历史运行参照） |
| 3 | 确认四张图当前输入、输出、数据库写入和前端消费 | ✅ §4 |
| 4 | 清点现有检索、rerank、引用验证和缓存实现 | ✅ §5 |
| 5 | 为关键回归问题建立 Golden Cases | ✅ §3（6 例 + 4 项人工检查） |
| 6 | 为现有未提交的证据快照改动补测试并单独提交 | ✅ tests/test_evidence_snapshot.py（7 测试），commit `19561a4` |

**验收标准**（同一评测配置可重复运行并得到可解释结果）：评测运行由 `agent_eval_run` 行 + `_run_evaluation_background` 工作器驱动，同一数据集可重复发起；计分入口已统一为 `_EVAL_SCORERS` 注册表（commit `8a672b3`），可解释性以每个 case 的 `summary_json` 明细为准。✅

---

## 2. 评测基线（Graph v1）

### 2.1 本轮冻结运行

| Run | 数据集 | 任务类型 | 引擎 | 状态 | 高风险召回 | 双引用率 | 误报率 | Schema | 备注 |
|---|---|---|---|---|---|---|---|---|---|
| 25 | 9 风险审查回归集(30例) | CONTRACT_REVIEW | langgraph | ✅ DEGRADED | **61.67%** | 36.94% | 0.0% | 100% | 30/30 通过；29/30 LIMITED；infra 失败 0；rerank fallback 2 |
| 26 | 9 风险审查回归集(30例) | CONTRACT_REVIEW | legacy | ✅ DEGRADED | 35.0% | 100.0% | 0.0% | 100% | 30/30 通过；6/30 LIMITED；infra 失败 0 |
| 27 | 10 要素提取基准集(20例) | INTAKE | langgraph | ✅ COMPLETED | 21.58% | 67.45% | 0.0% | 100% | 20/20 通过；真计分（要素匹配+缺失检测）；infra 失败 0 |
| 28 | 11 履约日程提取集(20例) | FULFILLMENT_TIMELINE | langgraph | ✅ COMPLETED | 100% | 100% | 0.0% | 100% | 20/20 通过；⚠️ 占位计分（恒 1.0） |
| 29 | 12 履约核验检查集(20例) | FULFILLMENT_CHECK | langgraph | ✅ COMPLETED | 100% | 100% | 0.0% | 100% | 20/20 通过；⚠️ 占位计分（恒 1.0） |

> 状态语义：任一 case 产出 LIMITED 报告（或 rerank 发生 keyword fallback）即整轮标记 DEGRADED（`resultValid=false`），历史 runs 18/19/22 同为 DEGRADED——**DEGRADED 不代表失败**，仅表示"存在受限结果"。
> run 25 与历史最佳 run 22（64.4%）同配置可比：召回 61.67%（-2.7pp），双引用率 36.94%（+3.9pp），LIMITED 率 96.7%——LIMITED 率过高正是 Phase 3 v2 试点要解决的检索失败退避问题。
> run 26 legacy 召回 35.0% 与历史 run 20（31.7%）同量级；legacy 双引用率 100% 为口径差异（§2.3），跨引擎不可比。
> run 27 要素召回 21.58% 是首个"真计分"要素基线（run 23 的 100% 为空计分产物，不可比）——要素提取质量差是既有事实，Phase 2 起由 Harness 检索与缺失检测改善。

> 状态语义：任一 case 产出 LIMITED 报告（或 rerank 发生 keyword fallback）即整轮标记 DEGRADED（`resultValid=false`），历史 runs 18/19/22 同为 DEGRADED——**DEGRADED 不代表失败**，仅表示"存在受限结果"。
> run 25 与历史最佳 run 22（64.4%）同配置可比：召回 61.67%（-2.7pp），双引用率 36.94%（+3.9pp），LIMITED 率 96.7%——LIMITED 率过高正是 Phase 3 v2 试点要解决的检索失败退避问题。

### 2.2 历史运行参照（基线上下文）

| Run | 数据集 | 引擎 | 状态 | 高风险召回 | 双引用率 | 说明 |
|---|---|---|---|---|---|---|
| 18 | 9 | langgraph | DEGRADED | 58.3% | 32.6% | |
| 19 | 9 | langgraph | DEGRADED | 58.3% | 31.5% | |
| 20 | 9 | legacy | DEGRADED | 31.7% | 100.0% | |
| 22 | 9 | langgraph | DEGRADED | **64.4%** | 33.0% | 当前 v1 风险最佳 |
| 23 | 10 | langgraph | COMPLETED | 100.0% | 100.0% | ⚠️ 空计分时期，数字不可比 |
| 24 | 10 | legacy | FAILED | 0.0% | 0.0% | legacy 不支持要素提取（已加守卫） |

### 2.3 计分语义说明（影响数字可比性）

- **风险审查**：真计分。highRecall=期望风险命中率；dualCitationRate=合同+知识双引用率（legacy 天然双引用，langgraph 政策引用率低，故 legacy 双引用率虚高——两引擎此指标口径不同）。
- **要素提取**（8a672b3 起）：highRecall=要素期望命中率（严格包含匹配 + 缺失标记检测）；dualCitationRate 复用为要素引用覆盖率；findingCount=提取要素数。run 23 的 100% 是空计分产物，**不可与新 run 比较**。
- **履约日程 / 履约核验**：占位计分（恒 1.0），本轮仅冻结"能跑通"状态与耗时，指标无判别力。PRD §22.9 的日程/核验门槛当前无法验证。

---

## 3. Golden Dataset v1

依据 PRD §25.4 回归清单建立，已入库（append-only，不动现有数据集）：

| 数据集 | ID | 用例 | 覆盖回归 |
|---|---|---|---|
| Golden-风险审查回归集 | 20 | GD-RV-001 付款条款引用附件隐藏验收风险（CROSS_REF） | 补充检索未修正结论 |
| | | GD-RV-002 缺验收条款，规则发现须带解释（MISSING_CLAUSE） | 规则发现缺少解释 |
| Golden-要素提取回归集 | 21 | GD-IN-001 金额"10"陷阱（10台/10万单价/10%质保金 vs 总价100万） | 合同总价被识别成 10 CNY |
| | | GD-IN-002 项目业主/联系人/开户行≠合同当事人 | 标题、甲乙方识别错误 |
| Golden-履约日程回归集 | 22 | GD-TL-001 结束条件（履行完毕之日/双条件提前终止）不得转固定日期 | 结束条件被错误转为固定日期 |
| | | GD-TL-002 长条款尾部付款期限 | 时间节点截断 |

人工检查项（无法由评测用例覆盖，列为每轮回归前的手工清单）：

1. 风险审查已完成但合同详情页无结果（前端消费链路）。
2. 履约证明核验存在人工确认入口且 Resume 可回到原图。
3. 旧 FAILED Run 不阻止同数据集重新发起。
4. 评测重复运行不重复创建 Embedding 与 ES 索引（fixture 按文本/配置 Hash 复用）。

Golden 运行时机：按 PRD §22.8/Phase 3 在 v1/v2 对照实验中执行，Phase 0 仅建立与冻结。

---

## 4. Graph 接口清单

### 4.0 公共设施

| 组件 | 位置 | 说明 |
|---|---|---|
| 运行时路由 | app/agent_runtime/runtime.py `dispatch_with_mode(ctx, mode)` | 两引擎统一入口；langgraph 按 task_type 查图适配器注册表；legacy 走 AgentRunner |
| 证据快照加载 | app/agent_runtime/graph/evidence_snapshot.py `load_contract_evidence_snapshot()` | 新增共享加载器（98f3353）：主文档选择、条款目录、已确认录入、要素快照、文档质量、Snapshot Hash |
| 公共 State | app/agent_runtime/graph/state.py `BaseGraphState` | 含新增 `contract_evidence_snapshot` 字段（可选） |
| 报告持久化 | app/agent_runtime/persistence.py `MySqlReportStore` | 四张图 + legacy 统一写 `agent_report`（content_json=完整产物） |
| Checkpoint/观测 | app/agent_runtime/graph/checkpoint.py | agent_graph_checkpoint / agent_node_execution / agent_tool_call / agent_run 状态 |

### 4.1 contract_review（风险审查，langgraph v1）

- **节点**：load_run_context → freeze_case_snapshot → inventory_clauses → create_domain_tasks → retrieve_domain_evidence → run_deterministic_rules → draft_domain_findings → validate_claims → coverage_reflection → targeted_retrieval → compose_report / compose_limited_report → validate_schema → repair_artifact → prepare_human_review → persist_report
- **输入**：subject_id、run_id、task_input（documentId、evalExpectedDimensions 等）；case_snapshot、document_snapshot、knowledge_snapshot、domain_tasks、retry_state
- **输出产物**：`{title, summary, findings[], risks, analysisMode: FULL|LIMITED, scoringVersion, evidenceHash, reportMarkdown, retrievalValidation}`，写入 agent_report.content_json
- **DB 写入**：agent_report、contract_review_finding（按 run 先删后插）、checkpoint 三表、agent_run
- **前端消费**：Java `/api/workspace/contracts/{id}`、`/api/workspace/contracts/runs/{runId}`、`/api/admin/contracts/reports`、`/api/admin/contracts/actions`（风险处置）→ ContractDetail 风险 Tab

### 4.2 contract_extraction（要素提取）

- **节点**：load_extraction_context → select_element_packs → retrieve_element_evidence → extract_element_batches → validate_extracted_elements → build_contract_profile → persist_extraction_snapshot
- **输入**：subject_id、task_input.documentId；共享快照（include_content_text=True）
- **输出产物**：`evaluationStages.CONTRACT_ELEMENT_EXTRACTION.{elements[], contractProfile{baseFields,groups}, elementSummary, summary, requiresHumanConfirmation}`
- **DB 写入**：contract_extraction_snapshot（upsert）、contract_extracted_element（按 snapshot 先删后插）、contract_element_evidence_link、contract_element_candidate、contract_analysis_workflow、agent_report
- **前端消费**：Java 合同详情 → 合同画像/要素 Tab（读取 extraction snapshot 表）；人工确认走 intake 确认链路

### 4.3 timeline_extraction（履约日程）

- **节点**：load_run_context → freeze_case_snapshot → publish_final_timeline（**3 节点薄图**，黑盒在 `contract_document_parser.extract_final_contract_timeline()`）
- **输入**：subject_id、run_id、analysis_workflow.documentId（98f3353 起支持指定文档）
- **输出产物**：`{timelineNodeCount, documentId}`；正式日程节点行
- **DB 写入**：contract_timeline_node、contract_analysis_workflow、agent_report
- **前端消费**：Java 合同详情 → 时间节点 Tab

### 4.4 fulfillment_check（履约核验）

- **节点**：load_run_context → freeze_case_snapshot → decompose_requirements → retrieve_fulfillment_evidence → judge_each_requirement → validate_fulfillment_judgement → prepare_human_confirmation → wait_human_confirmation → apply_human_result → persist_report
- **输入**：subject_id、run_id、履约节点与上传证明（task_input）
- **输出产物**：逐 Requirement 的匹配/缺口/AI 建议结论，reportType=FULFILLMENT_REPORT；人工确认经 LangGraph Interrupt/Resume
- **DB 写入**：agent_report（含确认状态）、checkpoint 三表、agent_run
- **前端消费**：Java 合同详情 → 履约核验 Tab；`/internal/agent/run/{id}/resume` 人工确认

### 4.5 legacy 引擎（AgentRunner）

- **流程**：Phase 1 上下文构建 → 2 规划 → 3 工具轮询（≤2 轮×3 调用）→ 4 证据保证 → 5 反思（可重规划）→ 6 产物生成
- **支持任务**：HEALTH_ANALYSIS、PROJECT_ONBOARDING、ENGINEERING_DECISION、CONTRACT_REVIEW、CONTRACT_INTAKE、APPROVAL_DECISION、FULFILLMENT_CHECK（`LEGACY_SUPPORTED_TASK_TYPES`）
- **不支持**：CONTRACT_ELEMENT_EXTRACTION、TIMELINE_EXTRACTION（三层守卫：runtime ValueError / worker fail-fast / Java+Vue 拒绝）
- **产物**：analyze_project / run_project_task 产物 → MySqlReportStore 统一落库
- **前端消费**：同上（agent_report 驱动）

---

## 5. 检索 / rerank / 验证 / 缓存实现清点

### 5.1 检索通道

| 通道 | 实现位置 | 备注 |
|---|---|---|
| MySQL 条款类型过滤 | graph/nodes/retrieval.py `_load_type_clauses` | 按 requiredClauseTypes 直接取 |
| 合同条款混合检索 | contract_store.py `search_contract_clause` | 多源 RRF 融合（retrievalType=HYBRID_RRF），rerank 见下 |
| 政策/知识库检索 | contract_store.py `search_policy` | 内置标准条款 + 知识库 |
| 历史决策检索 | contract_store.py `search_historical` | 历史审核发现 |
| 三类结果合并 | retrieval.py `_retrieve_one_domain` | 合同+政策+历史并发，去重（limit 18） |

⚠️ **PRD §4.1 问题在代码层已确认**：`retrieval.py:107` 把 WorkUnit 全部查询拼成一个字符串（`" ".join(queries)[:600]`）——多意图单查询，正是 PRD 要拆的。

### 5.2 Rerank

| 能力 | 位置 | 行为 |
|---|---|---|
| 合同命中重排 | contract_store.py `_rerank_contract_hits` + reranker.py `Reranker.rerank_contract_clauses` | 模型 rerank；失败/不可用时关键词 fallback |
| 政策命中重排 | reranker.py `rerank_policy_items` | 同上 |
| 实际方法记录 | nodes/retrieval.py:172 `rerankMethods`（langgraph）、runner.py:752 `legacyPipeline.rerankMethods`（legacy） | 评测中心据此记录 actualMethod（MIXED / MODEL_RERANK / KEYWORD_FALLBACK） |

### 5.3 引用与验证

| 能力 | 位置 | 说明 |
|---|---|---|
| 引用支持验证 | graph/nodes/validation.py `validate_claims`；contract_extraction.py `_citation_supported` | 引用 ID 必须存在于证据池、原文支持主张；要素逐引用核验 |
| 确定性规则 | graph/nodes/retrieval.py `run_deterministic_rules` + `_fallback_rule_findings` | 规则命中→发现；检索失败→规则兜底发现 |
| Schema 验证 | contract_review graph `validate_schema` + `repair_artifact` | 产物 Schema 门禁与修复 |
| 覆盖反思 | graph/nodes/reflection.py `coverage_reflection` | 领域级覆盖门禁（非 PRD 的子项级矩阵）；评测模式下按 evalExpectedDimensions 裁剪 |

### 5.4 缓存

| 缓存 | 位置 | TTL/失效 |
|---|---|---|
| Prompt 注册表 | prompts.py PromptRegistry | 30s 内存缓存，DB 变更后 clear |
| 运行时设置 | runtime.py | 30s |
| 知识库 Embedding 索引 | memory_index.py | 进程内索引，显式 invalidate |
| 编译后图注册表 | graph/registry.py | 编译图缓存 |
| DB 连接池 | persistence.py | mincached=2/maxcached=6 |

❌ **无检索结果缓存**（PRD §20.3 的 snapshot_hash+query 缓存键体系不存在）——同一合同重复评测会重复 ES/Embedding 检索。

### 5.5 评测计分（当前实现）

- 注册表：`_EVAL_SCORERS`（routes.py）统一两引擎计分入口。
- 已实现：CONTRACT_REVIEW/RISK_REVIEW（风险真计分）、CONTRACT_ELEMENT_EXTRACTION/INTAKE/ELEMENT_EXTRACTION（要素真计分）。
- 占位（恒 1.0）：FULFILLMENT_CHECK、TIMELINE_EXTRACTION。

---

## 6. 不兼容变更清单

| # | 变更/差异 | 影响 | 处理建议 |
|---|---|---|---|
| 1 | Runtime 实际只有 `legacy`/`langgraph` 两个值；PRD 规划的 `langgraph_v1`/`langgraph_v2`/`shadow_v2` 未注册 | 无法按 graph_version 对照与回退 | Phase 3 前增加 v1/v2 注册与 Shadow Run |
| 2 | agent_eval_run 的 graph_name/graph_version/prompt_version/llm_model 列存在但始终为空 | 评测基线缺少模型/提示词维度，跨期不可比 | Phase 0.5：worker 落库这些维度 |
| 3 | legacy 对 INTAKE/TIMELINE 由"全败"改为"三层守卫拒绝"（8a672b3） | 行为变化：前端禁用、Java 拒绝、worker fail-fast | 已生效，文档已同步 |
| 4 | 要素提取计分从恒 1.0 改为真计分（8a672b3） | 历史 run 23（100%）与新 run 不可直接比较 | 引用新 run 27 作为要素基线 |
| 5 | 履约日程/履约核验评测仍为占位计分 | PRD §22.9 日程/核验门槛无法验证 | Phase 2/3 前补齐这两个计分器 |
| 6 | 证据快照改造（98f3353）新增 state 字段 `contract_evidence_snapshot` 与 observation 字段 `evidenceSnapshotHash` | 旧 Checkpoint 恢复时不含新字段（可选字段，向后兼容） | 旧 RUNNING Run 继续由旧图恢复；新 Run 自然带新字段 |
| 7 | 要素提取图错误信息由中文改为英文（98f3353 重构副作用："没有可用于要素提取的主合同文档"→"Contract document is not ready..."） | 前端若直接展示该 message 会出现英文 | 后续统一错误码/文案 |
| 8 | COMPREHENSIVE 评测 task plan 只跑要素+日程+风险，不含履约核验 | 综合集不覆盖核验任务（评测文本无履约证明，by design） | 保持现状，在文档中标注 |
| 9 | 风险双引用率口径两引擎不同（legacy 强制双引用 vs langgraph 按需） | 该指标跨引擎不可比 | 对比实验统一口径或分引擎解读 |
| 10 | 遗留问题（Debug修复记录）：IN-164 类"差异型期望"（期望与合同文本故意不符）计分无法表达 | 部分要素 case 期望判分失真 | Phase 2 计分器演进时处理 |

---

## 7. 结论与下一步

1. **基线已冻结**：runs 25-29 全部完成（§2.1）——风险基线 run 25（langgraph 61.67% / legacy 35.0%）、要素基线 run 27（真计分 21.58%）；日程/核验仅有"可运行性"基线（计分占位）。
2. **接口审计结论**：四张图 + legacy 已共享 RuntimeRouter、MySqlReportStore、checkpoint/观测设施；证据快照共享已落地第一张图（要素+日程）并接进 review 的 context 节点。与 PRD 的差距集中在：多查询拆分（§4.1）、遗漏审计、子项覆盖矩阵、WorkUnit 模型、负向门禁、检索缓存。
3. **Phase 1 就绪**：EvidenceContextBuilder 的核心逻辑已存在于 evidence_snapshot.py；下一步把 contract_review 的检索路径完全切到共享快照，并验证四张图同案同 Hash（PRD Phase 1 验收）。
4. **Golden 运行**：按 PRD Phase 3 在 v2 试点时执行 v1/v2 对照；Phase 0 已建立数据集与手工检查清单。
