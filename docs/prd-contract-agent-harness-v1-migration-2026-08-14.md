# AtlasMind 合同 Agent Harness v1 公共化与任务迁移 PRD

> 文档版本：v1.0
> 日期：2026-08-14
> 状态：规划中
> 前置进度：原《Evidence Agent Harness High Recall DAG》已推进至 Phase 3 试点
> 关联文档：
> - [Evidence Agent Harness High Recall DAG](./prd-evidence-agent-harness-high-recall-dag-2026-08-14.md)
> - [Phase 0 基线报告](./phase0-baseline-report-2026-08-14.md)
> - [Phase 3 v2 试点报告](./phase3-v2-pilot-report-2026-08-14.md)
> - [合同作业系统六层架构](./contract-operations-six-layer-architecture-2026-08-08.md)

---

## 1. 变更摘要

原 PRD 设计为：风险审查 Graph v2 达到指标后，再以 v2 经验固化通用 Harness，并迁移其他任务。

Phase 3 评测结果表明：

- 评分器修复后，当前风险审查 v1 基线重算召回率约为 93.3%；
- v2 目前只有部分样本结果，未证明召回率提升；
- v2 在已完成的 6 个对照样本上与 v1 持平，但耗时约为 v1 的 4.8～5.1 倍；
- 标称 v2 的部分历史 Run 实际静默回退为 Legacy，不能作为 v2 证据；
- v2 的复杂遗漏审计、反证和多轮定向回补尚未证明有足够的边际收益。

因此本 PRD 作出以下架构调整：

1. `langgraph_v2` 停止继续推进，不进入生产默认路由；
2. 保留 v2 代码、Git Tag、评测产物和实验记录，不删除、不作为新模块的复用基础；
3. 以当前稳定的风险审查 `langgraph_v1` 作为生产基线和公共编排参考；
4. 从 v1 和已验证 Harness 中抽取公共模块，不复制完整业务 Graph；
5. 按“公共 Harness → 要素提取 → 履约日程 → 履约核验”的顺序迁移；
6. 每个任务继续拥有自己的 Graph 和业务 Schema，但共享同一套证据、检索、校验、预算、观测和恢复机制。

本 PRD 取代原 PRD Phase 4～9 的执行路线。原 PRD 保留为历史设计与 v2 实验记录。

---

## 2. 背景与问题

### 2.1 当前实现状态

当前系统已经具备：

- Runtime Router 和独立 Graph Adapter；
- 统一 `EvidenceSnapshot` 加载入口；
- `WorkUnit`、`EvidenceNeed`、`RetrievalRequest`、`EvidenceBundle` 类型；
- 公共 `RetrievalOrchestrator`；
- 混合检索、RRF、rerank、父条款扩展和证据合并；
- 公共 Grounding Validator、Schema 校验和 Observation；
- 风险审查 v1 Graph；
- 风险审查 v2 实验 Graph。

### 2.2 当前主要问题

1. 公共能力已经出现，但接口边界还不稳定；
2. 风险 v2 的复杂 DAG 尚未证明比 v1 更准确；
3. 要素提取仍有“首次基础信息识别错误、后续画像再次修正”的重复处理；
4. 履约日程内部仍有黑盒逻辑，过程不可充分观测；
5. 履约核验需要逐要求判断、证据不足克制和人工最终确认；
6. 评测器、模型版本、Prompt 版本、Runtime 版本必须能形成可比较的闭环；
7. 不能为了复用而建立四套几乎相同的业务 Graph。

---

## 3. 产品目标

### 3.1 总目标

建设一套以稳定风险审查 v1 为基线的通用 Agent Graph Harness，使新增合同任务只需声明任务差异，不再重复实现：

- 合同证据快照加载；
- WorkUnit 编排；
- 混合检索和证据合并；
- LLM 调用和结构化输出；
- 引用、事实和 Schema 校验；
- 有限重试和局部重跑；
- 预算、超时、错误、心跳和 Trace；
- 人工中断、Resume 和历史版本保护。

### 3.2 业务目标

1. 风险审查继续以风险 v1 为稳定生产基线；
2. 要素提取首次就正确识别金额、主体、标题、日期等基础字段；
3. 动态合同画像由 LLM 根据合同内容决定要素，不使用一套固定模板强行套用所有合同；
4. 履约日程输出最终结果，不向前端展示未经语义复核的初步候选；
5. 履约核验输出 AI 建议，但不自动确认履约完成；
6. 管理端能够看到每个任务的 Agent、WorkUnit、查询、证据、验证、回补和耗时；
7. 前台只展示业务重点，证据和详细过程可展开查看。

### 3.3 非目标

本阶段不做：

- 继续扩大 v2 的反证 Agent 和多轮回补逻辑；
- 默认引入第二个 LLM；
- 自由协作式多 Agent；
- 重写全部数据库；
- 一次性迁移四张 Graph；
- 删除 Legacy 或 v2 历史代码；
- 为了速度直接减少证据召回范围；
- 让 AI 自动确认履约或自动确认验收通过。

---

## 4. 架构决策

### 4.1 基准版本

生产基准：风险审查 `langgraph_v1`。

兼容别名：现有 `langgraph` 在迁移期只允许指向 v1，不得根据进程状态或未知字符串静默回退到其他实现。

实验版本：`langgraph_v2`。

历史版本：`legacy`。

建议的规范 Runtime 标识：

```text
legacy
langgraph_v1
langgraph_v2_experimental
```

旧值 `langgraph` 仅作为兼容输入，落库时统一记录为 `langgraph_v1`。

### 4.2 统一 Graph 不是统一业务逻辑

四个任务不要求内部节点完全相同。统一的是生命周期和基础契约：

```text
load_snapshot
    -> build_task_context
    -> plan_work_units
    -> retrieve_evidence
    -> analyze_units
    -> validate_candidates
    -> audit_coverage
    -> compose_artifact
    -> persist_or_human_gate
```

任务差异由 `TaskSpec` 声明：

- WorkUnit 规划器；
- 检索策略；
- 分析器；
- 校验器；
- 产物组装器；
- 持久化策略；
- 是否需要人工 Gate。

### 4.3 v2 的处理原则

- v2 代码保留在独立模块和历史 Tag 中；
- 不继续增加 v2 业务能力；
- 不允许 v2 作为其他模块的模板；
- 不允许 v2 进入默认生产路由；
- 只有当未来有明确问题、独立 Golden 集和预算证明时，才重新启动 v2 实验；
- v2 后续如重启，必须以 Harness 接口为基础，不得复制整套 v1/v2 Graph。

---

## 5. 目标架构

### 5.1 六层合同作业系统映射

本 PRD 遵循现有六层架构：

```text
L1 文档与证据层
    PDF/OCR/MinerU、条款、页码、段落、质量诊断、EvidenceSnapshot

L2 合同事实层
    基础身份、动态画像、确认事实、版本和引用

L3 履约作业层
    时间节点、责任方、动作、触发条件、证明材料和核验状态

L4 风险与控制层
    风险发现、规则、政策依据、影响、建议和处理状态

L5 Agent 编排层
    Graph、Harness、WorkUnit、检索、校验、人工 Gate、预算和恢复

L6 管理与评测层
    运行中心、Trace、指标、Golden、版本对照、成本和回滚
```

### 5.2 Harness 模块边界

建议公共代码集中在：

```text
app/agent_runtime/harness/
    models.py          # TaskSpec / WorkUnit / EvidenceNeed / Bundle
    graph_builder.py   # 公共 Graph 生命周期
    retrieval.py       # RetrievalOrchestrator
    validation.py      # 引用、事实、Schema 校验
    coverage.py        # WorkUnit 和 Checklist 覆盖审计
    budget.py          # 超时、Token、查询、回补预算
    observation.py     # Observation、Trace、指标
    cache.py           # Snapshot / query / embedding / fixture cache
    recovery.py        # heartbeat、timeout、resume
```

业务 Graph 保留在：

```text
app/agent_runtime/graph/
    contract_review.py
    contract_extraction.py
    timeline_extraction.py
    fulfillment_check.py
```

业务 Graph 不得重复实现公共检索、引用校验、预算和心跳。

---

## 6. 核心接口

### 6.1 TaskSpec

```python
class TaskSpec:
    task_type: str
    graph_name: str
    graph_version: str
    prompt_version: str
    planner: WorkUnitPlanner
    retriever: RetrievalPolicy
    analyzer: UnitAnalyzer
    validator: ArtifactValidator
    coverage_auditor: CoverageAuditor
    composer: ArtifactComposer
    persistence: PersistencePolicy
    human_gate: HumanGate | None
```

TaskSpec 只描述差异，不持有合同全文，不直接管理数据库连接，不直接创建外部客户端。

### 6.2 WorkUnit

一个 WorkUnit 是一次受预算约束的业务分析单元，不等同于固定合同领域。

```json
{
  "workUnitId": "payment-terms",
  "label": "付款与价款",
  "purpose": "识别金额、付款条件、开票条件和付款风险",
  "checkItems": [
    {
      "key": "TOTAL_AMOUNT",
      "required": true,
      "status": "NOT_CHECKED"
    }
  ],
  "queryIntents": ["合同总价", "付款条件 开票期限"],
  "requiredClauseTypes": ["PAYMENT"],
  "budget": {
    "maxQueries": 2,
    "maxRetryRounds": 1
  }
}
```

领域级 WorkUnit 可以用于复用证据，但必须保留 `checkItems` 逐项状态。任何任务都不得只用“领域有证据”代替子项覆盖。

### 6.3 EvidenceBundle

每个 Bundle 必须记录：

- Snapshot Hash；
- WorkUnit ID；
- 查询请求和查询版本；
- keyword/vector/rerank 各通道结果；
- 合同证据和政策证据；
- 父条款、相邻条款和证据并集来源；
- 超时、降级、错误和耗时；
- 是否可支持确定性结论。

### 6.4 统一结果状态

```text
COMPLETED
LIMITED
WAITING_HUMAN
FAILED
```

`LIMITED` 必须说明缺失的 WorkUnit、Checklist Item、证据来源和是否执行过回补。不得把基础设施失败伪装成业务无证据。

---

## 7. 公共 Graph 生命周期

### 7.1 标准 DAG

```text
load_snapshot
       |
       v
freeze_run_context
       |
       v
plan_work_units
       |
       v
fan_out retrieve_evidence
       |
       v
fan_out analyze_work_units
       |
       v
merge_candidates
       |
       v
validate_grounding_and_schema
       |
       v
audit_checklist_coverage
       |
       +---- coverage sufficient ----> compose_artifact
       |
       +---- limited missing evidence -> one bounded targeted retry
                                      |
                                      v
                                  revalidate
                                      |
                                      v
                                compose_artifact
       |
       +---- human task ----------------> interrupt/resume
       |
       v
persist_artifact
```

### 7.2 默认预算

生产默认采用保守预算：

- 首轮检索：每 WorkUnit 1～2 个查询意图；
- 默认最多 1 轮定向回补；
- 回补只重跑受影响 WorkUnit；
- 单 Run 全局超时；
- 单 WorkUnit 查询、LLM、Token 和重试预算；
- 外部 Embedding/Rerank 有独立短超时；
- 超预算后输出 LIMITED，并保存完整诊断；
- 评测的快速模式和准确率模式必须显式区分。

### 7.3 失败策略

- Snapshot 加载异常：FAILED，不生成业务结论；
- 外部检索部分失败：保留成功通道，标记证据不完整；
- LLM 单 WorkUnit 失败：该单元 LIMITED，其他单元继续；
- Schema 失败：进入有限修复，修复失败不得持久化为完整结果；
- 人工等待：WAITING_HUMAN，不写 COMPLETED；
- Shadow 运行：不得阻塞主结果，单独超时、取消和记录。

---

## 8. 迁移计划

### Phase 3 收尾：冻结 v2，修正基线

目标：把当前实验状态固化为可追溯的历史基线。

任务：

1. 给 `langgraph_v1`、`langgraph_v2`、Legacy 打 Git Tag；
2. 将 run 30 标记为部分评测，不作为完整 v2 基线；
3. 将 run 33、35 标记为 Runtime mismatch，不作为 v2 结果；
4. 固化评分器版本和重算说明；
5. 补录 Run 的 graph、prompt、model、retrieval、rerank 和 scorer 元数据；
6. 保存代表性合同、Artifact、引用和 Trace；
7. v2 从默认路由和新任务模板中移除；
8. 增加 v2 frozen 文档，停止功能开发。

验收：任何人可以根据 Git Tag、评测 Run 和产物快照复现“v1 基线 / v2 实验 / 评分器重算”的关系。

### Phase 4：稳定 Harness 公共化

目标：从风险 v1 提取公共生命周期，不改变风险 v1 业务行为。

任务：

1. 定义 TaskSpec 和 Graph Harness 接口；
2. 将风险 v1 的公共节点迁移到 Harness；
3. 风险 v1 改为声明 TaskSpec；
4. 保留 v1 Artifact、字段和 API 兼容；
5. 增加四类任务的统一 Snapshot Hash、版本和观察字段；
6. 增加 Fake Retrieval、Fake LLM 和 Fake Persistence；
7. 测试成功、超时、降级、FAILED、WAITING_HUMAN、Resume 和旧 Checkpoint；
8. 禁止 Harness 引入 v2 的多轮回补默认行为。

验收：风险 v1 结果与迁移前在冻结 Golden 集上等价，且调用方不再实现公共检索、校验和恢复逻辑。

### Phase 5：迁移合同要素提取

目标：首次识别正确，支持动态要素和字段级复核。

任务：

1. 基础身份字段单独建立固定 WorkUnit；
2. 合同类型、标的和画像要素由 LLM 动态规划；
3. 金额、币种、主体、标题、日期使用确定性规范化和专用校验；
4. 每个要素必须绑定原文引用、页码、条款和 Snapshot Hash；
5. 发现冲突时保留候选，不静默覆盖人工确认值；
6. 只重跑失败或低置信度字段；
7. 保存候选、确认、修正和版本历史；
8. 不允许后续风险画像覆盖基础确认事实。

验收：

- 关键基础字段准确率 ≥95%；
- 金额单位和币种准确率 ≥99%；
- 人工确认值在所有后续 Graph 中可见；
- 字段级引用支持率 ≥97%；
- 重跑单字段不会重复 OCR、Embedding 或整份合同分析。

### Phase 6：迁移履约日程

目标：把日程黑盒变成可观测、可验证、可人工确认的 DAG。

任务：

1. 规则层生成时间候选；
2. LLM 基于完整原文判断责任方、动作、触发事件、期限和后果；
3. 规则候选与 LLM 候选去重并保留来源；
4. 代码负责日期计算，不让 LLM 直接计算最终日期；
5. 支持“合同结束条件”这类非固定日期条件事件；
6. 不截断父条款、上下文和完整引用；
7. 对乱码、低质量 OCR 和不确定基准日期标记风险，不篡改原文；
8. 只向前端展示最终确认后的正式日程；
9. 为每个节点保留状态和失败阶段。

验收：

- 时间节点召回率 ≥92%；
- 日期计算准确率 ≥99%；
- 责任方、动作和触发条件准确率 ≥95%；
- 所有正式节点可追溯到完整合同引用；
- 规则层、LLM 层和校验层耗时可分别观测。

### Phase 7：迁移履约核验

目标：让“上传材料 → AI 判断 → 人工确认”成为真实作业流程。

任务：

1. 将时间节点拆成履约 Requirements；
2. 为每个 Requirement 定义要求、证据类型、截止条件和合同后果；
3. 检索上传证明材料、合同要求和关联业务资料；
4. 执行文件类型、日期、金额、签章和内容规则；
5. LLM 输出已履约、未履约、证据不足、存在冲突四种建议；
6. AI 不得写入最终人工状态；
7. 人工确认使用 Interrupt / Resume；
8. 新材料只重跑受影响 Requirement；
9. 人工结论追加保存，不允许新 Run 覆盖历史结论。

验收：

- 履约证据不足克制率 ≥98%；
- AI 建议 Schema 通过率 ≥99%；
- AI 自动确认路径为零；
- 新材料局部重跑成功率 ≥99%；
- 人工 Resume 成功率 ≥99%；
- 前端和管理端状态一致。

### Phase 8：统一评测与可观测性

目标：每个任务能独立评测，同时支持跨模块复用指标。

任务：

1. 评测集按任务用途区分：要素、日程、风险、履约核验、综合；
2. 评测用例不再重复创建合同分条和 Embedding，按文本 Hash 缓存；
3. 每个 Run 冻结 Runtime、Graph、Prompt、Model、Retrieval、Rerank、Scorer 版本；
4. 分别统计检索召回、引用支持、字段准确、时间计算、风险召回、履约判断和人工采纳；
5. 所有部分 Run 明确标注分母、可评分例数和跳过原因；
6. 管理端显示 WorkUnit、Checklist、查询、证据、验证、预算和耗时；
7. 建立 v1 基线、迁移版本和未来版本的对照看板。

验收：所有指标可以追溯到具体 Case、Artifact、引用和版本，不允许使用恒定 `1.0` 占位计分作为发布依据。

---

## 9. 评测规则

### 9.1 风险审查

- 重大风险召回率；
- 风险 Precision；
- 误报率；
- 合同引用支持率；
- 政策引用支持率；
- 负向结论正确率；
- LIMITED 比例；
- 每个 Checklist Item 覆盖率；
- 每个 WorkUnit 漏检率。

### 9.2 要素提取

- 关键字段准确率；
- 数值和币种准确率；
- 主体和角色准确率；
- 动态要素召回率；
- 要素引用支持率；
- 冲突识别率；
- 人工确认后事实传播正确率。

### 9.3 履约日程

- 节点召回率；
- 责任方准确率；
- 动作准确率；
- 条件触发准确率；
- 日期计算准确率；
- 非固定结束条件识别率；
- 乱码和不确定日期的正确标记率。

### 9.4 履约核验

- Requirement 召回率；
- 证明材料匹配准确率；
- 已履约/未履约判断准确率；
- 证据不足克制率；
- 冲突证据识别率；
- 人工采纳率；
- AI 自动确认违规数，必须为 0。

---

## 10. 数据库与版本策略

优先复用现有表，不立即进行大规模表拆分。必须补齐或统一以下元数据：

```text
agent_run.runtime_engine
agent_run.graph_name
agent_run.graph_version
agent_run.prompt_version
agent_run.llm_model
agent_run.retrieval_version
agent_run.rerank_version
agent_run.scorer_version
agent_run.snapshot_hash
```

核心 JSON 产物必须包含：

- `artifactSchemaVersion`；
- `snapshotHash`；
- `graphName`；
- `graphVersion`；
- `promptVersion`；
- `scorerVersion`；
- `coverage`；
- `observations`；
- `humanDecisionVersion`。

旧产物只读兼容，不用新代码强行重解释为新版本产物。

---

## 11. 发布、回滚与退场

### 11.1 Runtime 生命周期

```text
legacy                 历史回退和旧 Run Resume
langgraph_v1           当前生产基线
langgraph_v2_frozen    冻结实验版本，只读对比
```

新任务默认使用 `langgraph_v1` 公共化后的实现，不得默认使用 v2。

### 11.2 发布门槛

每迁移一个任务必须同时满足：

1. 冻结 Golden 集上 Schema 和关键行为不回归；
2. 关键业务指标达到对应任务门槛；
3. 新旧结果可逐条对比；
4. 管理端可看到完整 Trace；
5. 能够切回旧 Graph；
6. 已有 WAITING_HUMAN Run 可以按原版本 Resume；
7. 新旧数据库产物均可被前端读取。

### 11.3 退场条件

- v2 仅保留 Git Tag、历史评测和产物快照；
- 不再保留 v2 的日常生产配置；
- Legacy 代码在无未完成 Run、无 Resume 依赖并完成回滚演练后再归档；
- 历史运行查看不能依赖重新执行旧代码。

---

## 12. 执行顺序与提交拆分

建议每个阶段独立提交，避免一次性重构：

1. `docs: freeze graph v2 as experimental baseline`
2. `feat(harness): define stable task and artifact contracts`
3. `refactor(harness): extract v1 snapshot retrieval validation observation`
4. `test(harness): add graph contract and failure-path tests`
5. `refactor(extraction): migrate contract element graph to harness`
6. `test(extraction): add amount party title date golden cases`
7. `refactor(timeline): migrate timeline graph to harness`
8. `test(timeline): add condition event and date calculation cases`
9. `refactor(fulfillment): migrate fulfillment check to harness`
10. `test(fulfillment): add proof matching and human confirmation cases`
11. `feat(eval): add task-specific scorers and versioned run metadata`
12. `feat(observability): expose work unit evidence and latency details`

每个提交都应能独立编译、运行单测和回滚。

---

## 13. 完成定义

本 PRD 完成时必须满足：

1. 风险审查 v1 是生产基线，v2 不在默认路由；
2. 四类任务共享 EvidenceSnapshot、RetrievalOrchestrator、Validator、Budget 和 Observation；
3. 业务 Graph 只声明 TaskSpec 差异；
4. 要素、日程、风险具备逐 WorkUnit 和逐 Checklist Item 覆盖状态；
5. 要素首次基础字段识别不依赖后续画像修正；
6. 日程内部过程可观测，正式结果不包含未复核初步候选；
7. 履约核验按 Requirement 输出证据和 AI 建议，人工最终确认；
8. 所有回补有预算，所有失败有明确状态和原因；
9. 管理端可以查看 Agent、Graph、Snapshot、查询、证据、校验、耗时和版本；
10. 评测中心可以分别评估四类任务，且没有恒定占位指标；
11. 历史 v1、v2、Legacy 结果可追溯，不依赖旧代码重跑；
12. 所有新模块均能动态切回上一稳定版本；
13. 不存在 AI 自动确认履约或验收通过的路径；
14. 第二模型和自由多 Agent 未成为主流程硬依赖。

---

## 14. 第一轮立即执行清单

当前先执行以下内容：

1. 冻结并标记 v2，不再继续扩展；
2. 补齐 v1 的 Graph、Prompt、Model、Retrieval、Rerank、Scorer 元数据；
3. 修正并测试人工确认值进入 EvidenceSnapshot 的契约；
4. 从风险 v1 提取 Harness，不改变风险输出字段；
5. 把公共失败、预算、心跳、Resume 和 Observation 做成契约测试；
6. 迁移合同要素提取；
7. 用真实要素 Golden 集完成首次验收后，再迁移履约日程；
8. 暂不迁移履约核验，等日程的稳定节点 ID 和状态模型确认后再做；
9. 删除或隔离评测临时脚本，避免误提交和误操作；
10. 更新 Debug 修复记录，记录 v2 冻结和新迁移路线。
