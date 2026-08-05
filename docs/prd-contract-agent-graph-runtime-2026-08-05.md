# AtlasMind 合同 Agent 图运行时与判断准确率增强 PRD

> 文档版本：v1.0  
> 日期：2026-08-05  
> 产品：AtlasMind Agent Workbench - ContractOps  
> 文档状态：待实施  
> 目标版本：Graph Runtime v1  
> 主要范围：合同审查 Agent、履约核验 Agent、Agent 可观测性与评测体系
> 开源调研附件：[Agent 框架与法律项目调研](./research-agent-frameworks-2026-08-05.md)

---

## 1. 文档目的

本文档定义 AtlasMind 在现有 Python Agent Runtime 基础上，引入 LangGraph、显式 DAG、状态机、质量门禁和评测体系的完整产品与技术方案。

本次建设不是为了把现有 `AgentRunner` 换成另一个框架，也不是为了展示“使用了 LangGraph”。核心目标是解决以下业务问题：

1. 长合同审查可能因条款读取、引用数量和工具预算限制而漏掉关键风险。
2. Reflection 发现证据不足后，补充检索没有形成再次复核的闭环。
3. 只验证 LLM 输出是 JSON，尚未验证结论、引用、规则和证据之间是否一致。
4. 合同审查、履约核验、版本复核共用一条通用六阶段流程，任务差异没有被明确表达。
5. 履约核验包含补证、待定、人工确认、上传新证据后重新核验等状态，继续使用线性流程会越来越难维护。
6. 当前缺少可以证明“准确率确实提高”的合同 Agent 专项评测集和发布门槛。

LangGraph 在本项目中承担“图编排与状态推进”职责；MySQL 继续保存业务事实，Redis Stream 继续负责异步任务分发，现有工具、规则引擎、报告和前后端接口尽量复用。

---

## 2. 产品结论

### 2.1 核心决策

- 引入 LangGraph，但采用渐进式迁移，不一次性重写整个 Agent Runtime。
- 保留现有 `AgentRunner` 作为旧实现、回滚通道和 Shadow Run 对照组。
- 第一批只迁移 `CONTRACT_REVIEW`，达到评测门槛后再迁移 `FULFILLMENT_CHECK`。
- 合同审查使用“确定性骨架 + 并行领域分析 DAG + 证据复核循环”。
- 履约核验使用“要求拆解 + 证据匹配 + 判断复核 + 人工确认状态机”。
- 本阶段不建设多个 Agent 自由对话或互相辩论；采用职责明确的节点和独立验证器。
- LLM 不拥有风险分数、最终履约结果和外部动作执行权。
- 合同审查和履约核验都必须主动查询适用知识库，知识库不是最后兜底。

### 2.2 一句话价值

让合同 Agent 从“按顺序调用工具并生成报告”，升级为“能够分解任务、并行取证、发现缺口、循环补证、验证结论并在关键节点等待人工确认的可恢复工作流”。

### 2.3 为什么不能只改 Prompt

Prompt 可以提醒模型谨慎，但不能可靠保证：

- 每个风险维度都被检查；
- 每条结论都有合同原文和制度依据；
- 补检索后一定再次复核；
- 证据不足时一定停止给出确定结论；
- 人工确认后可以从原状态继续；
- 同一输入在规则层得到一致结果；
- 发布前可以量化比较新旧 Runtime。

这些约束必须由图结构、状态模型、验证器和评测体系共同保证。

---

## 3. 当前基线

### 3.1 已实现并保留的能力

当前 Python Runtime 已经具备真实 Agent Harness，而不是单次问答：

- Planner；
- 原生 Function Calling；
- 工具注册表和白名单；
- 最大工具调用数、最大轮次和超时预算；
- 重复工具调用拦截；
- 合同证据与知识库强制检索；
- Reflection 和有限 Re-plan；
- 确定性合同风险评分；
- Agent Run、Trace、Tool Call、Report、Memory 持久化；
- Redis Stream Consumer Group 异步执行；
- 取消、心跳、超时恢复和 LLM 熔断；
- SSE 进度和管理端运行详情；
- 履约证据快照、证据多对多绑定和人工确认记录。

### 3.2 当前执行链路

```text
用户端 / 管理端
      ↓
Java API：鉴权、业务 CRUD、创建 Agent Run
      ↓
Redis Stream：agent:run:stream
      ↓
Python Worker
      ↓
AgentRunner.execute()
      ↓
Context → Planner → Tool Loop → Evidence Guarantee
      → Reflection → Artifact → Report / Trace / Memory
      ↓
MySQL + Elasticsearch
```

### 3.3 当前主要约束

| 编号 | 当前约束 | 业务影响 |
|---|---|---|
| C-01 | 通用 Runner 最多 2 轮、8 次工具调用 | 长合同或复杂任务容易在证据完整前耗尽预算 |
| C-02 | `readContractClause` 单次最多读取 20 条 | 条款较多时存在覆盖盲区 |
| C-03 | 最终合同审查只传入有限 findings 和 citations | 已检索证据可能未进入最终判断上下文 |
| C-04 | 补检索后不再次执行完整 Reflection | 不能证明证据缺口已经关闭 |
| C-05 | Reflection 失败仍可能继续生成正式报告 | “未通过质量门禁”和“报告完成”语义冲突 |
| C-06 | 本地 Reflection 只要存在引用即可判 adequate | 一个弱引用可能错误通过复杂任务 |
| C-07 | JSON 解析没有严格业务 Schema | 引用 ID、枚举、必需字段和结论可能不一致 |
| C-08 | 知识库向量检索与关键词检索主要是降级关系 | 精确术语和语义相似内容不能稳定融合 |
| C-09 | 不同合同任务共享通用 Planner | 工具可选范围过大，任务完成信号不够具体 |
| C-10 | 缺少合同 Agent Golden Dataset | 无法量化新旧版本准确率差异 |

---

## 4. 建设目标

### 4.1 业务目标

1. 提高重大合同风险的召回率，减少因上下文截断和检索遗漏造成的漏审。
2. 降低无依据风险、错误引用和把通用建议说成合同约定的误报。
3. 让每项履约判断都能展示“合同要求 → 证据 → 判断 → 缺口”。
4. 证据不足时输出待定和补证清单，不强行给出完成或验收通过结论。
5. 新证据上传后可从明确状态重新核验，并保留历史判断和证据快照。
6. 让法务、采购和业务人员能看懂 Agent 为什么做出判断。

### 4.2 技术目标

1. 将 Agent 编排从隐藏在顺序代码中的状态，升级为显式图与状态转换。
2. 支持并行分析、条件分支、有限循环、节点重试、暂停和恢复。
3. 建立强类型 Graph State、结构化产物和业务验证器。
4. 保持现有 Java API、Redis Stream、MySQL Store 和前端主接口兼容。
5. 支持旧 Harness、LangGraph 和 Shadow 三种运行模式动态切换。
6. 图中每个节点都可观测、可重放、可归因和可评测。

### 4.3 成功定义

本次建设成功不以“LangGraph 能运行”为标准，而以以下结果为标准：

- 新 Graph Runtime 在固定评测集上的重大风险召回率高于旧 Harness；
- 引用正确率、结构化输出成功率和证据不足时的克制率达到发布门槛；
- 同一证据快照下，确定性规则结果完全一致；
- Graph Run 可被中断、恢复和审计；
- 新 Runtime 出现问题时，无需重启即可切回旧 Harness。

---

## 5. 非目标

本 PRD 不包含：

- 训练或微调基础大模型；
- 建设多个自治 Agent 自由讨论的多 Agent 社会；
- AI 自动签署合同、自动确认履约完成或自动批准高风险动作；
- 在当前无多用户权限基础上伪造复杂组织权限；
- 把所有 Java 业务逻辑迁移到 Python；
- 用 LangGraph 替换 Redis Stream、MySQL 或 Elasticsearch；
- 对历史合同报告进行无条件批量重跑；
- 在没有评测集的情况下仅凭主观观感宣布准确率提升；
- 第一阶段接入图片、视频的完整多模态真实性鉴定。

---

## 6. 用户与关键场景

### 6.1 当前 MVP 用户

当前尚未完成多用户和权限控制，因此 MVP 中当前登录用户同时承担：

- 合同负责人；
- 材料上传者；
- 结果编辑者；
- 人工复核者。

系统仍记录 `created_by`、`confirmed_by` 等字段，为后续权限建设保留接口，但本阶段不据此做复杂授权决策。

### 6.2 业务角色

| 角色 | 核心诉求 |
|---|---|
| 业务经办人 | 快速知道合同有什么风险、需要补什么材料、下一步做什么 |
| 法务复核人 | 查看完整原文、制度依据、规则命中和 Agent 判断链路 |
| 采购/财务 | 关注金额、付款、发票、验收前提和违约后果 |
| 履约负责人 | 按时间节点上传证明材料并发起核验 |
| 系统管理员 | 管理规则、标准条款、知识范围、Prompt、Runtime 和运行记录 |

### 6.3 核心用户故事

#### US-01 合同审查

作为业务经办人，我上传合同并发起审查后，希望 Agent 自动覆盖主要风险维度，展示每条风险的合同原文、制度依据、影响、修改建议和复核点。

#### US-02 证据不足

作为法务复核人，当合同缺少某类条款或知识库没有足够制度依据时，我希望系统明确标记缺失内容，而不是生成看起来确定的法律结论。

#### US-03 履约核验

作为履约负责人，我为某个时间节点上传报告、回单、验收单等材料后，希望 Agent 按合同要求逐项核验并列出缺口，最终由我人工确认。

#### US-04 新证据重检

作为履约负责人，当我上传新证据时，希望节点显示“待重新核验”，但系统不要自动产生模型费用；由我主动点击后重新运行。

#### US-05 Agent 可观测性

作为管理员，我希望查看本次 Agent 为何启动、走过哪些节点、每轮为什么选择工具、取回哪些证据、在哪个质量门禁失败以及如何恢复。

#### US-06 安全回滚

作为管理员，当 Graph Runtime 报告质量下降时，希望动态切换回旧 Harness，不重启服务、不丢失运行记录。

---

## 7. 设计原则

### 7.1 事实、判断和动作分离

- 事实：合同原文、文件、制度、人工输入和工具输出。
- 判断：规则结果和 LLM 解释。
- 动作：补材料、法务复核、提醒、协商任务等建议。

LLM 不能把判断写成事实，也不能未经审批直接执行高风险动作。

### 7.2 确定性骨架，LLM 处理语义

代码负责：

- 任务路由；
- 风险维度清单；
- 工具权限和预算；
- 规则引擎；
- 引用存在性校验；
- 状态转换；
- 最终风险分数覆盖；
- 人工确认边界。

LLM 负责：

- 查询扩展；
- 条款语义理解；
- 风险解释；
- 证据与要求匹配；
- 缺口描述；
- 可执行建议；
- 报告语言组织。

### 7.3 知识库是一等证据来源

合同审查和履约核验都必须查询适用知识库。知识范围沿用：

- `GLOBAL`：全部合同可用；
- `SPECIFIC_CASES`：只对绑定合同可用；
- `DISABLED`：不参与合同 Agent；
- 默认 `DISABLED`。

历史报告保留当时引用快照，新运行按最新知识范围检索。

### 7.4 不确定时克制

- 缺少证据：`INSUFFICIENT_EVIDENCE`；
- 条款模糊：`UNCLEAR_TERMS`；
- 结论冲突：`NEEDS_REVIEW`；
- 禁止把“不知道”改写成“低风险”；
- 禁止仅凭文件名判断证据内容；
- 图片或视频未经过识别时不能作为充分证据。

### 7.5 人工最终负责

- 合同风险报告可以由 Agent 生成，但高风险动作必须审批。
- 履约完成、完成失败、验收通过和验收不通过必须人工确认。
- AI 给出的后果推断必须标注“AI 推断，仅供参考，不代表合同约定”。

---

## 8. 目标架构

### 8.1 总体架构

```text
Java API / Redis Stream
          ↓
RuntimeRouter
    ├── LegacyHarnessAdapter
    ├── ContractGraphRuntime
    └── ShadowRuntime
          ↓
ContractGraphRuntime
    ├── ContractReviewGraph
    ├── FulfillmentCheckGraph
    ├── VersionReviewGraph        后续
    └── ApprovalDecisionGraph     后续
          ↓
Tool Registry / Rule Engine / Retrieval / Validators
          ↓
MySQL / Elasticsearch / LLM
```

### 8.2 模块接口

外部只需要理解一个稳定接口：

```python
class AgentRuntime(Protocol):
    async def run(self, context: AgentTaskContext) -> AgentResult: ...
    async def resume(self, run_id: int, command: ResumeCommand) -> AgentResult: ...
```

实现：

- `LegacyHarnessAdapter`：调用现有 `AgentRunner.execute()`；
- `ContractGraphRuntime`：调用 LangGraph；
- `ShadowRuntime`：同一快照分别执行两套 Runtime，保存对比结果，只把主版本结果展示给用户。

### 8.3 Runtime 路由

配置优先从数据库读取：

| 配置键 | 示例 | 说明 |
|---|---|---|
| `agent.runtime.default` | `legacy` | 默认运行时 |
| `agent.runtime.CONTRACT_REVIEW` | `langgraph` | 按任务覆盖 |
| `agent.runtime.FULFILLMENT_CHECK` | `legacy` | 履约暂不迁移 |
| `agent.runtime.shadow.enabled` | `true` | 是否执行对照 |
| `agent.graph.contract_review.version` | `v1` | 图版本 |

读取失败时使用进程内安全默认值 `legacy`。

### 8.4 包结构建议

```text
app/agent_runtime/
├── runtime.py                    # AgentRuntime 接口与路由
├── runner.py                     # 旧 Harness，迁移期保留
├── graph/
│   ├── state.py                  # 强类型 Graph State
│   ├── registry.py               # graph_name + version 注册
│   ├── checkpoint.py             # 检查点适配
│   ├── contract_review.py        # 审查主图
│   ├── fulfillment_check.py      # 履约主图
│   ├── routing.py                # 条件边
│   └── nodes/
│       ├── context.py
│       ├── retrieval.py
│       ├── rules.py
│       ├── judgement.py
│       ├── reflection.py
│       ├── validation.py
│       ├── artifact.py
│       └── persistence.py
├── schemas/
│   ├── graph_state.py
│   ├── review.py
│   ├── fulfillment.py
│   └── citations.py
└── evaluation/
    ├── dataset.py
    ├── metrics.py
    ├── runner.py
    └── comparators.py
```

### 8.5 开源框架选型矩阵

以下评分只表示其对 AtlasMind 当前架构和合同业务的适配度，不是框架的通用质量排名。详细事实、许可证和一手来源见调研附件。

| 候选 | DAG/状态机 | 持久化恢复 | 长等待人工介入 | 类型与工具约束 | 渐进接入 | AtlasMind 结论 |
|---|---:|---:|---:|---:|---:|---|
| LangGraph | 5 | 5 | 5 | 4 | 5 | 主编排框架 |
| PydanticAI / Pydantic Graph | 4 | 3 | 4 | 5 | 4 | 采用 Pydantic 校验和评测思想，不整体迁移 Runtime |
| AutoGen | 2 | 3 | 2 | 4 | 2 | 不采用；偏多 Agent 且官方进入维护模式 |
| CrewAI | 4 | 4 | 4 | 4 | 3 | 借鉴 Flow、router 和 human feedback，不采用 Crew 主运行时 |
| Semantic Kernel | 3 | 2 | 2 | 4 | 2 | 不采用；Process Framework 仍为实验能力且官方后继方向已明确 |

选型依据：

- LangGraph 的 StateGraph、条件边、checkpointer 和 interrupt/resume 与合同审查循环、履约人工确认直接匹配；
- Pydantic 在强类型状态、工具参数、结构化报告和自定义 Validator 上更有价值；
- AutoGen 和 CrewAI 的角色化多 Agent 不是当前准确率问题的主要解法；
- Semantic Kernel 的跨语言优势不足以抵消 Python Runtime 已经落地后的二次迁移成本；
- 所有候选框架都不能替代合同证据、规则、知识范围和人工最终责任。

参考：[LangGraph Graph API](https://docs.langchain.com/oss/python/langgraph/graph-api)、[LangGraph Persistence](https://docs.langchain.com/oss/python/langgraph/persistence)、[PydanticAI Evals](https://ai.pydantic.dev/evals/)、[CrewAI Flows](https://docs.crewai.com/en/concepts/flows)。

### 8.6 最终技术选型

| 技术层 | MVP 选择 | 采用方式 | 不采用的替代项 |
|---|---|---|---|
| Agent 图编排 | LangGraph | 仅用于 Python Runtime 内部 StateGraph、条件边、子图、interrupt/resume | 不采用 CrewAI、AutoGen、Semantic Kernel 作为主 Runtime |
| 强类型模型 | Pydantic BaseModel | Graph State、工具参数、引用、报告和 Resume Command | 不仅依赖 JSON parser |
| 业务验证 | Python 自定义 Validator | 引用存在性、合同版本、知识范围、双引用和结论一致性 | 不把校验完全交给第二次 LLM 调用 |
| LLM Gateway | 保留现有 OpenAI-compatible Client | 继续连接 DeepSeek，保留重试、熔断和 Prompt Registry | 第一阶段不迁移到 PydanticAI Agent Client |
| 异步分发 | 保留 Redis Stream | XADD、Consumer Group、ACK、PEL 和 Worker 恢复 | 不引入 Temporal、DBOS、Prefect、Restate 或 LangGraph Server |
| 业务数据 | 保留 MySQL | 合同、文件、规则、报告、动作、人工确认继续作为事实源 | 不把业务事实放入 Graph State 或 LangSmith |
| Graph Checkpoint | MySQL 自有 Checkpoint Adapter | 新建专用表，实现 LangGraph checkpointer 协议并关联 run_id | MVP 不新增 PostgreSQL；SQLite 仅用于单元测试 |
| 检索 | Elasticsearch BM25 + kNN 并行召回 | 应用层 RRF 融合，后续可加 reranker | 不再使用“向量有结果就不跑关键词”的单路优先模式 |
| Embedding | 保留现有 Qwen Embedding 配置 | 保持维度与历史索引兼容，模型变更必须重建索引 | 不因 Graph 迁移同时更换 Embedding |
| 文档解析 | 保留 DOCX 原生解析、PDF/MinerU、LibreOffice 转换 | 延续现有 Worker 和条款/时间节点流水线 | 不引入第二套完整文档平台 |
| 可观测性 | 现有 Run/Trace/ToolCall + OpenTelemetry | MySQL 保存业务审计，OTel 记录跨节点性能与模型 span | 不强制绑定 LangSmith、Logfire 或 CrewAI AMP |
| 离线评测 | 自建 Golden Dataset + pytest 指标 | 后续试点 `pydantic-evals` 管理实验和轨迹评测 | 不直接使用英文公开集分数作为中文准确率 |
| 前端 | 保留 Vue 3 用户端和管理端 | 增加 Graph JSON 可视化、引用 span 和人工确认界面 | 不嵌入 RAGFlow Canvas 或 OpenContracts 前端 |

### 8.7 Checkpoint 单一决策

MVP 采用 MySQL 自有 Checkpoint Adapter，不新增 PostgreSQL。

原因：

1. AtlasMind 已经使用 MySQL 保存 Agent Run、Trace、Tool Call 和业务事实；
2. 当前规模不值得为 checkpoint 单独增加一套数据库、备份和监控；
3. Redis Stream 已承担分发，不需要再引入 Temporal 等第二套耐久执行平台；
4. 自有 Adapter 可以让 checkpoint 与 `run_id`、人工确认和现有删除策略保持一致。

约束：

- Adapter 必须实现并发写、状态修订、幂等恢复和序列化兼容测试；
- checkpoint 表与业务表分开，不在同一个 JSON 中保存合同全文；
- 单元测试可使用 LangGraph 内存或 SQLite checkpointer；
- 当并发规模、checkpoint 写入量或维护成本超过既定阈值时，再单独评估官方 PostgreSQL checkpointer；
- 未通过恢复测试前，不允许把履约人工中断切到生产 Graph。

### 8.8 依赖管理

- `langgraph`、checkpoint 相关包必须锁定精确版本，不能使用无上限的 `>=`；
- Pydantic 继续使用项目已有主版本，新增 Schema 必须兼容当前 FastAPI；
- `pydantic-evals` 首先作为开发/评测依赖，不进入在线请求关键路径；
- OpenTelemetry SDK 允许关闭，不得因遥测后端不可用阻塞 Agent；
- 每次依赖升级必须运行 Golden Dataset 和 checkpoint 恢复测试。

---

## 9. Graph State 设计

### 9.1 状态原则

- Graph State 是一次运行的可恢复工作状态，不是业务事实主表。
- 合同、文件、知识和人工确认仍以业务表为事实来源。
- State 中保存的是 ID、版本、哈希、快照和中间判断。
- 节点不得通过隐藏的全局变量交换业务状态。
- 每个节点输入和输出必须可序列化。
- 每次状态修改产生 `stateRevision`。

### 9.2 通用状态字段

| 字段 | 类型 | 说明 |
|---|---|---|
| `runId` | long | Agent Run ID |
| `subjectType` | string | 当前为 `CONTRACT_CASE` |
| `subjectId` | long | 合同案件 ID |
| `taskType` | enum | `CONTRACT_REVIEW` 等 |
| `graphName` | string | 图名称 |
| `graphVersion` | string | 图版本 |
| `stateRevision` | int | 状态修订号 |
| `triggerType` | enum | MANUAL、RESUME、SHADOW、SCHEDULED |
| `taskInput` | object | 用户输入和节点 ID 等 |
| `caseSnapshot` | object | 合同元数据快照 |
| `documentSnapshot` | list | 文件版本和哈希 |
| `knowledgeSnapshot` | list | 本次可用知识范围 |
| `plan` | object | 有界计划 |
| `domainTasks` | list | 风险维度或履约子项 |
| `observations` | list | 工具结果摘要 |
| `citations` | list | 规范化引用 |
| `ruleFindings` | list | 确定性规则命中 |
| `draftFindings` | list | LLM 初步发现 |
| `validatedFindings` | list | 通过验证的发现 |
| `coverage` | object | 各维度覆盖情况 |
| `reflection` | object | 当前质量门禁结果 |
| `retryState` | object | 各节点重试和补检索次数 |
| `budget` | object | 工具、Token、时间预算 |
| `errors` | list | 结构化错误 |
| `artifact` | object | 最终产物 |
| `waitState` | object/null | 人工等待状态 |

### 9.3 引用统一结构

```json
{
  "citationId": "CONTRACT_CLAUSE:182",
  "sourceType": "CONTRACT_CLAUSE",
  "sourceId": "182",
  "documentId": 41,
  "documentVersion": 2,
  "contentHash": "sha256...",
  "page": 6,
  "clauseNumber": "第七条",
  "snippet": "原文片段",
  "retrievalScore": 0.86,
  "retrievalType": "HYBRID_RRF",
  "scope": "CURRENT_CASE"
}
```

引用 ID 必须包含来源类型，禁止仅使用数据库数字 ID，避免合同条款 `12` 与知识文档 `12` 冲突。

### 9.4 状态不可变事实

一次运行启动后，下列信息在当前 Run 中冻结：

- 合同案件 ID；
- 当前合同文件版本和哈希；
- 规则集版本；
- 评分版本；
- Prompt 版本；
- 模型名称；
- 知识库范围快照；
- 我方角色 `ourSide`。

运行中业务数据发生变化时，本 Run 继续使用原快照，完成后提示“发现数据变更，建议重新运行”。

---

## 10. 节点设计规范

每个 Graph Node 必须声明：

1. 节点名称和业务目的；
2. 必需输入字段；
3. 输出字段；
4. 可调用工具；
5. 是否允许调用 LLM；
6. 超时和重试策略；
7. 幂等键；
8. 失败后的路由；
9. Trace 摘要；
10. 是否会产生业务写入。

### 10.1 节点类型

| 类型 | 说明 | 示例 |
|---|---|---|
| `LOAD` | 读取事实快照 | 加载合同、文件、角色 |
| `PLAN` | 生成有界任务计划 | 查询扩展、风险维度任务 |
| `RETRIEVE` | 调用读取/搜索工具 | 条款、知识库、历史决策 |
| `COMPUTE` | 确定性计算 | 规则引擎、风险评分 |
| `JUDGE` | LLM 语义判断 | 风险解释、证据匹配 |
| `VALIDATE` | 代码或独立模型复核 | 引用、覆盖、矛盾检查 |
| `ARTIFACT` | 生成结构化产物 | 审查报告、履约报告 |
| `PERSIST` | 保存业务数据 | 报告、发现、核验记录 |
| `INTERRUPT` | 等待人工输入 | 履约最终确认 |

### 10.2 幂等规则

节点幂等键建议：

```text
runId + graphVersion + nodeName + stateRevision + inputHash
```

同一幂等键已经成功时，恢复执行直接复用输出，不再次调用 LLM 或外部工具。

### 10.3 重试规则

| 错误 | 默认处理 |
|---|---|
| LLM 连接超时 | 指数退避重试 2 次，再走降级或失败分支 |
| LLM JSON 不合法 | 本地修复一次，结构化修复节点一次 |
| Pydantic 校验失败 | 进入 `repair_output`，最多 1 次 |
| ES 不可用 | 降级 MySQL 关键词检索并标记 retrieval degradation |
| Embedding 不可用 | 使用关键词检索，不把低召回伪装成正常 |
| MySQL 短暂错误 | 节点级重试，保持幂等 |
| 工具参数非法 | 不重试，返回 Planner/Graph 路由错误 |
| 证据不足 | 不是系统错误，进入补检索或待定产物 |

---

## 11. 合同审查 Graph

### 11.1 目标

合同审查图必须覆盖：

- 主体与授权；
- 商务与付款；
- 责任与违约；
- 合规与保密；
- 履约可执行性；
- 终止与续签；
- 知识产权和数据保护（合同适用时）。

最终报告中的每个实质风险必须完成双引用：合同原文或明确缺失证据 + 制度/标准条款依据。

### 11.2 图结构

```text
START
  ↓
load_run_context
  ↓
freeze_case_snapshot
  ↓
build_clause_inventory
  ↓
run_deterministic_rules
  ↓
create_domain_tasks
  ↓
并行 Map：review_domain_task × N
  ├── build_queries
  ├── retrieve_contract_evidence
  ├── retrieve_policy_evidence
  ├── align_rule_and_evidence
  └── draft_domain_findings
  ↓
merge_findings
  ↓
validate_claims_and_citations
  ↓
coverage_reflection
  ├── PASS → calculate_contract_risk
  ├── NEED_MORE_EVIDENCE → targeted_retrieval → validate again
  └── CANNOT_RESOLVE → generate_limited_report
  ↓
compose_review_report
  ↓
validate_report_schema
  ├── INVALID → repair_report → validate once
  └── VALID
  ↓
persist_report_and_findings
  ↓
END
```

### 11.3 `build_clause_inventory`

目的：避免只读取前 20 条合同条款。

输出：

- 总条款数；
- 各条款类型数量；
- 未分类条款；
- 缺失的关键条款类型；
- 每条条款的 ID、编号、标题、页码、哈希和内容长度；
- 当前合同文本是否完整。

要求：

- 条款清单分页读取，不依赖数据库自然顺序；
- 未分类条款不能静默忽略；
- 超长条款保留父条款，并使用子切片检索；
- 文档解析失败时停止正式审查，提示先修复解析。

### 11.4 `create_domain_tasks`

领域任务由代码生成固定基础集合，LLM 只能补充，不能删除必查项。

每个任务包含：

```json
{
  "domain": "PAYMENT",
  "objective": "检查金额、付款节点、发票、验收前提和逾期后果",
  "requiredClauseTypes": ["PAYMENT", "ACCEPTANCE", "LIABILITY"],
  "mandatoryRuleKeys": ["..."],
  "queryTemplates": ["付款条件 发票 验收后付款 逾期"],
  "completionSignals": ["合同证据已检查", "政策证据已检查", "结论已验证"]
}
```

### 11.5 领域任务并行

可并行的领域任务使用 DAG fan-out/fan-in。并行上限由配置控制，默认 3，避免同时触发过多 LLM 和 Embedding 请求。

并行节点不能直接写 `contract_review_finding`，先写 Graph State，汇总去重并通过验证后统一持久化。

### 11.6 风险发现结构

```json
{
  "findingKey": "PAYMENT:ADVANCE_PAYMENT_NO_GUARANTEE",
  "clauseType": "PAYMENT",
  "severity": "HIGH",
  "title": "预付款缺少保障条件",
  "claim": "合同约定较高比例预付款，但未发现履约担保或分阶段支付约束",
  "contractCitationIds": ["CONTRACT_CLAUSE:182"],
  "policyCitationIds": ["KB_CHUNK:903"],
  "impact": "...",
  "remediationAdvice": "...",
  "negotiationAdvice": "...",
  "verificationPoints": ["..."],
  "evidenceStatus": "DUAL_CITED",
  "confidenceLevel": "HIGH"
}
```

### 11.7 Claim Validator

验证器至少检查：

- 引用 ID 是否存在于当前 State；
- 引用是否属于当前合同版本或当前可用知识范围；
- 引用片段是否真实存在于源内容；
- “合同未约定”是否基于完整条款清单，而不是只看检索 TopK；
- 制度要求是否来自有效版本；
- HIGH 风险是否具备足够证据；
- 同一发现的合同依据与制度依据是否语义相关；
- 发现之间是否重复或互相矛盾；
- LLM 是否修改了确定性评分字段；
- 建议是否被错误写成合同事实。

验证输出：`PASS`、`NEED_MORE_EVIDENCE`、`DOWNGRADE_CONFIDENCE`、`REJECT_FINDING`。

### 11.8 Reflection 闭环

Reflection 不再返回一个笼统 `adequate`，而是返回领域覆盖矩阵：

```json
{
  "status": "NEED_MORE_EVIDENCE",
  "domains": {
    "PAYMENT": {"covered": true, "issues": []},
    "ACCEPTANCE": {"covered": false, "issues": ["未找到验收标准制度依据"]}
  },
  "missingEvidence": ["验收标准制度依据"],
  "nextQueries": ["技术服务 验收标准 成果物 验收单"],
  "retryable": true
}
```

补检索后必须重新执行 Claim Validator 和 Reflection。最大补检索轮数默认 2，超过后生成“范围受限报告”，不得显示为完整审查通过。

### 11.9 风险评分

- `ContractRiskScoringEngine` 继续拥有风险分数和维度分。
- 输入必须是验证后的规则发现与有效 findings 快照。
- `riskScore`、`riskStatus`、`dimensions`、`scoringVersion`、`evidenceHash`、`analysisMode` 由后端覆盖模型输出。
- 相同案件快照、规则版本和 findings 集合必须得到完全一致的评分。

---

## 12. 履约核验 Graph

### 12.1 目标

履约核验不是简单判断“有文件/没文件”，而是：

```text
合同要求 → 必需履约子项 → 证据文件与片段 → 逐项判断 → 缺口 → 人工确认
```

系统不输出数字评分，只输出高/中/低风险与高/中/低可信度。

### 12.2 图结构

```text
START
  ↓
load_timeline_node
  ↓
freeze_fulfillment_snapshot
  ↓
decompose_requirements
  ↓
validate_required_items
  ↓
retrieve_linked_and_candidate_evidence
  ↓
parse_and_match_evidence
  ↓
search_policy_knowledge
  ↓
judge_each_requirement
  ↓
validate_fulfillment_judgement
  ├── 缺少可补证据 → build_missing_evidence_list
  ├── 条款模糊 → mark_unclear_terms
  └── 判断可供复核 → compose_fulfillment_report
  ↓
save_check_snapshot
  ↓
WAITING_HUMAN_CONFIRMATION
  ├── 人工确认 → CONFIRMED
  ├── 人工退回 → PENDING_SUPPLEMENT
  └── 新证据上传 → STALE / WAITING_RECHECK
```

### 12.3 要求拆解

一个时间节点可拆成多个履约子项。例如“提交研究报告并通过验收后付款”至少拆为：

1. 提交研究报告；
2. 报告内容符合合同约定；
3. 完成验收；
4. 取得验收确认；
5. 满足付款前提。

每个子项字段：

| 字段 | 说明 |
|---|---|
| `requirementId` | 当前核验内稳定 ID |
| `requirement` | 具体要求 |
| `required` | 是否必需 |
| `sourceCitationIds` | 合同原文依据 |
| `acceptanceCriteria` | 可判断标准 |
| `responsibleParty` | 甲方、乙方、双方或待确认 |
| `evidenceExpected` | 预期证明材料 |
| `ambiguity` | 条款是否模糊 |

必需项必须有合同原文依据。AI 建议只能作为 `required=false` 的辅助项，不能擅自升级为合同义务。

### 12.4 我方角色

- 角色使用合同创建时确定的 `ourSide`；
- 核验时不能临时切换甲乙方；
- `ourSide=A`：从甲方验收、付款和追责角度分析；
- `ourSide=B`：从乙方交付、举证和通过验收角度分析；
- 角色缺失时进入 `NEEDS_REVIEW`，不猜测。

### 12.5 证据匹配

证据来源：

- 人工绑定到节点的证据；
- Agent 自动匹配的本合同证据；
- 付款回单、发票、报告、成果物、验收单、会议纪要、通知记录等；
- 当前合同可用知识文档只能用于判断标准，不能冒充实际履约证据。

证据与节点多对多关联，保留：

- 文件 ID；
- 文件版本；
- 内容哈希；
- 引用片段；
- 匹配原因；
- 人工绑定或 Agent 匹配来源；
- 本次 check ID。

### 12.6 逐项判断结构

```json
{
  "requirement": "乙方应提交最终研究报告",
  "required": true,
  "contractCitationIds": ["CONTRACT_CLAUSE:211"],
  "evidenceCitationIds": ["FULFILLMENT_DOCUMENT:81#p12"],
  "judgement": "EVIDENCE_INSUFFICIENT",
  "reason": "文件中存在研究报告，但未找到最终版标识和提交确认记录",
  "gap": "补充最终版报告及甲方接收记录",
  "riskLevel": "MEDIUM",
  "confidenceLevel": "MEDIUM"
}
```

### 12.7 允许的 Agent 结论

- `BASICALLY_SATISFIED`：证据基本支持，仍需人工确认；
- `HAS_ISSUES`：发现明确缺口或冲突；
- `INSUFFICIENT_EVIDENCE`：证据不足；
- `UNCLEAR_TERMS`：合同标准本身不明确；
- `NEEDS_REVIEW`：存在冲突或机器无法可靠判断。

禁止 Agent 自动写入 `COMPLETED`、`FAILED`、`ACCEPTED`、`REJECTED` 作为最终业务结果。

### 12.8 人工确认状态

`contract_fulfillment_check.status` 建议统一为：

| 状态 | 含义 |
|---|---|
| `RUNNING` | Agent 正在核验 |
| `PENDING_CONFIRMATION` | AI 分析完成，等待人工确认 |
| `PENDING_SUPPLEMENT` | 人工要求补证 |
| `STALE` | 新证据或合同版本使历史判断过期 |
| `CONFIRMED` | 人工已确认 |
| `CANCELLED` | 已取消 |
| `FAILED` | 系统执行失败 |

无法补充证据时允许长期保持 `PENDING_CONFIRMATION` 或人工确认“继续待定”。

### 12.9 新证据规则

- 上传证据后不自动调用 Agent；
- 受影响节点显示“待重新核验”；
- 原核验历史不可覆盖；
- 用户主动点击重新核验时创建新 Run 和新 Check；
- 新 Check 读取最新证据，旧 Check 保留旧快照。

---

## 13. 后续 Graph

### 13.1 VersionReviewGraph

目标：比较合同版本后，只重新审查受影响领域。

```text
版本差异 → 变更条款分类 → 受影响规则 → 受影响时间节点
→ 并行局部复核 → 风险变化摘要 → 人工确认新基线
```

### 13.2 ApprovalDecisionGraph

目标：基于已验证审查发现、已接受例外和金额阈值给出审批路径建议。

要求：

- HIGH 未关闭时不能建议无条件通过；
- 例外必须有有效期和补偿控制；
- 最终审批仍由人完成；
- 审批意见不反向修改原始审查证据。

### 13.3 RenewalAssessmentGraph

目标：结合履约历史、争议、付款和时间节点判断续签、重谈或终止。

该图依赖履约历史数据质量，放在合同审查和履约核验稳定之后实施。

---

## 14. 工具体系

### 14.1 复用现有工具

现有合同工具继续复用，包括：

- `getContractCase`；
- `getContractParties`；
- `listContractDocuments`；
- `readContractClause`；
- `searchContractClause`；
- `getContractClauseDetail`；
- `listContractTimeline`；
- `searchContractTimeline`；
- `searchPolicyKnowledge`；
- `findStandardClause`；
- `searchHistoricalDecisions`；
- `evaluateReviewRules`；
- `calculateContractRisk`；
- `extractObligations`；
- `verifyFulfillmentEvidence`；
- `compareContractVersions`。

### 14.2 建议新增或深化工具

| 工具 | 目的 |
|---|---|
| `listClauseInventory` | 分页返回完整条款目录和哈希，不传完整正文 |
| `retrieveEvidenceHybrid` | 同时执行向量、关键词和字段检索并融合 |
| `getCitationSource` | 按规范化 citation ID 读取并校验原文 |
| `listApplicableKnowledge` | 返回本合同可用知识范围和版本快照 |
| `validateEvidenceSnapshot` | 检查文件版本、哈希和软删除状态 |
| `getFulfillmentEvidenceDetail` | 获取指定证据的解析片段和识别状态 |

### 14.3 工具权限

每个 Graph Node 只获得所需工具子集。例如 `calculate_contract_risk` 不能调用文件删除工具，`retrieve_policy` 不能写报告。

### 14.4 工具结果规范

所有工具结果统一返回：

```json
{
  "ok": true,
  "data": {},
  "citations": [],
  "warnings": [],
  "degraded": false,
  "error": null,
  "metadata": {
    "latencyMs": 120,
    "source": "MYSQL",
    "resultCount": 8
  }
}
```

迁移期可由 Adapter 包装旧工具结果，不要求一次性修改所有 Store。

---

## 15. 检索与知识库准确率

### 15.1 检索流程

```text
领域任务
  ↓
确定性查询模板 + LLM 查询扩展
  ↓
关键词召回 + 向量召回 + 元数据过滤
  ↓
RRF 融合
  ↓
业务重排
  ↓
去重、范围校验、引用快照
```

### 15.2 合同条款检索

- 精确词：条款编号、金额、百分比、日期、期限、否定词优先关键词检索；
- 语义词：责任限制、验收标准、数据合规等使用向量召回；
- 按 `case_id`、文档版本、条款类型过滤；
- 对“缺失条款”判断必须基于条款清单和规则，不只基于 TopK 搜索为空；
- 每个风险领域至少保留一个完整父条款引用。

### 15.3 知识库检索

- 同时检索标准条款和企业上传知识；
- 先应用 `GLOBAL/SPECIFIC_CASES/DISABLED` 范围；
- 检索结果携带文档版本、chunk、页码和范围；
- 标准条款的查询不能要求整个 query 字符串完整包含；
- 对政策冲突显示来源和版本，不由模型静默选择；
- 过期或禁用知识不能进入新运行。

### 15.4 重排特征

- 查询与片段语义相关度；
- 风险领域匹配；
- 合同类型匹配；
- 标准条款强制性；
- 文档生效状态和版本；
- 精确关键词覆盖；
- 否定词和例外条件；
- 人工确认过的历史使用记录。

### 15.5 检索降级提示

Embedding 或 ES 不可用时：

- 继续关键词检索；
- Trace 标记 `RETRIEVAL_DEGRADED`；
- 报告显示“本次语义检索不可用，结果覆盖可能受限”；
- 不允许把降级运行计入正常准确率评测。

---

## 16. 结构化输出与判断校验

### 16.1 Pydantic Schema

至少建立：

- `ContractReviewArtifact`；
- `ContractFinding`；
- `DualCitation`；
- `ReflectionResult`；
- `FulfillmentArtifact`；
- `FulfillmentRequirementJudgement`；
- `EvidenceSnapshotItem`；
- `ResumeCommand`；
- `GraphError`。

### 16.2 校验层次

1. JSON 语法校验；
2. Pydantic 字段和枚举校验；
3. 引用存在性校验；
4. 引用原文一致性校验；
5. 业务不变量校验；
6. 结论一致性校验；
7. 独立 Reflection/Judge 校验。

### 16.3 关键业务不变量

- `required=true` 必须有合同引用；
- HIGH 风险必须有有效合同依据和政策依据，或明确标记“关键条款缺失”；
- `INSUFFICIENT_EVIDENCE` 不能同时写“已确认履约完成”；
- `UNCLEAR_TERMS` 不能输出高可信度确定判断；
- AI 后果推断不能放入 `explicitConsequence`；
- 规则评分字段不能由 LLM 修改；
- 当前合同角色不能由核验 Prompt 重选；
- 不可用知识文档不能出现在 citations；
- 软删除证据不能进入新 evidence snapshot。

### 16.4 修复策略

Schema 校验失败后允许一次定向修复，修复 Prompt 只接收：

- 原输出；
- 校验错误；
- 允许引用 ID；
- 输出 Schema。

修复失败时生成受限兜底产物并标记失败原因，不能无限重试。

---

## 17. 记忆与反馈

### 17.1 记忆类型

| 类型 | 是否自动使用 | 说明 |
|---|---|---|
| 合同事实 | 是 | 当前合同、文件和主体事实 |
| 审查确认 | 是 | 人工确认或驳回的风险发现 |
| 已批准例外 | 有条件 | 必须匹配适用范围和有效期 |
| 履约历史 | 是 | 历史核验及人工结果 |
| Agent 情节记忆 | 默认否 | 未经确认不能作为正式判断依据 |
| 用户偏好 | 后续 | 待多用户权限完成后启用 |

### 17.2 反馈闭环

人工操作形成评测标签：

- 确认风险；
- 驳回误报；
- 补充遗漏风险；
- 修改严重度；
- 调整证据绑定；
- 确认履约结果；
- 标记 Agent 建议无效。

反馈不能直接修改 Prompt 或规则，先进入评测数据和管理员审核流程。

---

## 18. 人工中断与恢复

### 18.1 中断点

第一阶段只在履约核验最终确认使用人工中断。合同审查报告生成不阻塞，但动作审批仍沿用现有业务审批。

### 18.2 中断语义

Graph 到达中断点后：

1. 保存 checkpoint；
2. 更新 Agent Run 为 `WAITING_HUMAN`；
3. Redis Stream 当前消息完成 ACK；
4. 前台展示待确认项；
5. 人工操作后发布新的 resume 消息；
6. Worker 从 checkpoint 恢复，而不是从头执行。

### 18.3 Resume Command

```json
{
  "command": "CONFIRM | REQUEST_SUPPLEMENT | KEEP_PENDING | CANCEL",
  "expectedStateRevision": 8,
  "manualResult": "SATISFIED | NOT_SATISFIED | PENDING",
  "note": "人工说明",
  "operatorId": "current-user"
}
```

使用 `expectedStateRevision` 防止重复提交和旧页面覆盖新状态。

---

## 19. 可观测性

### 19.1 管理端 Run 详情

必须展示：

- 为什么启动 Agent：任务类型、合同案件、时间节点、触发人、触发入口；
- Graph 名称和版本；
- 当前节点和状态；
- DAG/状态机执行路径；
- 每个节点输入摘要、输出摘要、耗时和状态；
- Planner 计划；
- Function Calling 参数和结果；
- 检索 query、召回方式、结果数量和降级状态；
- Reflection 覆盖矩阵；
- 补检索轮次和原因；
- 引用校验失败项；
- LLM 模型、Prompt 版本、Token 和延迟；
- checkpoint、暂停、恢复、取消和错误；
- 最终报告、动作和人工结果。

### 19.2 事件类型

新增或规范：

- `GRAPH_STARTED`；
- `NODE_STARTED`；
- `NODE_COMPLETED`；
- `NODE_FAILED`；
- `BRANCH_SELECTED`；
- `FAN_OUT_STARTED`；
- `FAN_IN_COMPLETED`；
- `QUALITY_GATE_FAILED`；
- `RETRIEVAL_REPLAN_REQUESTED`；
- `CHECKPOINT_SAVED`；
- `HUMAN_INTERRUPT_CREATED`；
- `GRAPH_RESUMED`；
- `OUTPUT_REPAIRED`；
- `GRAPH_COMPLETED`。

### 19.3 前台展示

前台不展示完整系统日志，只展示：

- 当前阶段；
- 已完成的业务步骤；
- 使用了哪些证据类型；
- 是否发生检索降级；
- 是否需要补材料或人工确认；
- 报告的证据覆盖摘要。

技术堆栈、Prompt 全文和内部错误只放管理端。

---

## 20. 数据模型

### 20.1 `agent_run` 增量字段

| 字段 | 类型 | 说明 |
|---|---|---|
| `runtime_engine` | varchar(32) | legacy/langgraph/shadow |
| `graph_name` | varchar(64) | 图名称 |
| `graph_version` | varchar(32) | 图版本 |
| `state_revision` | int | 最新状态修订 |
| `checkpoint_status` | varchar(32) | NONE/SAVED/WAITING/RESUMED |
| `parent_run_id` | bigint null | 重跑或 Shadow 关联 |
| `evidence_snapshot_hash` | varchar(128) | 本次证据快照 |

### 20.2 `agent_graph_checkpoint`

该表由 `MySqlGraphCheckpointSaver` 使用。MVP 不增加 PostgreSQL；业务事实仍不得写入 checkpoint。

| 字段 | 说明 |
|---|---|
| `id` | 主键 |
| `run_id` | Run ID |
| `graph_name` / `graph_version` | 图身份 |
| `thread_id` | LangGraph thread 标识 |
| `checkpoint_id` | 检查点标识 |
| `state_revision` | 状态版本 |
| `node_name` | 保存时节点 |
| `state_json` | 可恢复状态 |
| `state_hash` | 状态哈希 |
| `status` | ACTIVE/SUPERSEDED/CONSUMED |
| `create_time` | 创建时间 |

### 20.3 `agent_node_execution`

用于图节点级统计，避免只依赖自由格式 Trace：

- run_id；
- node_name；
- node_type；
- attempt；
- status；
- input_hash；
- output_hash；
- started_at / finished_at / latency_ms；
- llm_model / prompt_version；
- token_input / token_output；
- error_code / error_message。

### 20.4 `agent_claim_verification`

保存报告结论校验结果：

- run_id；
- finding_key；
- claim；
- contract_citation_ids；
- policy_citation_ids；
- validation_status；
- validation_reasons；
- verifier_type；
- create_time。

### 20.5 评测表

新增：

- `agent_eval_dataset`：数据集版本和用途；
- `agent_eval_case`：脱敏输入、期望发现、期望引用和标签；
- `agent_eval_run`：Runtime、模型、Prompt、图版本；
- `agent_eval_result`：逐项指标、差异和人工复核。

现有 `kb_eval_case` 继续用于知识库 RAG 测试，不混用合同 Agent 端到端评测。

### 20.6 已有履约表

复用：

- `contract_fulfillment_check`；
- `contract_timeline_evidence_link`；
- `contract_document` 版本、哈希和软删除字段。

迁移时补充状态枚举约束和必要索引，不覆盖历史记录。

---

## 21. 接口需求

### 21.1 保持兼容

现有启动和查询接口保持兼容：

- `POST /internal/agent/run`；
- `GET /internal/agent/run/{id}`；
- Java 用户端和管理端现有 Run、Report、Trace 查询接口。

响应可增量增加 `runtimeEngine`、`graphName`、`graphVersion`、`currentNode` 和 `waitState`。

### 21.2 新增内部接口

#### 恢复 Graph

```http
POST /internal/agent/run/{runId}/resume
```

请求为 `ResumeCommand`，要求幂等和状态版本校验。

#### 查询 Graph 状态

```http
GET /internal/agent/run/{runId}/graph
```

返回节点、边、实际路径、当前状态和 checkpoint 摘要。

#### 执行评测

```http
POST /internal/agent/evaluations
GET  /internal/agent/evaluations/{evalRunId}
```

仅管理端或内部环境使用。

### 21.3 用户端接口

建议增加：

- `POST /api/contracts/{caseId}/timeline/{nodeId}/checks/{checkId}/confirm`；
- `POST /api/contracts/{caseId}/timeline/{nodeId}/checks/{checkId}/request-supplement`；
- `POST /api/contracts/{caseId}/timeline/{nodeId}/recheck`；
- `GET /api/contracts/{caseId}/timeline/{nodeId}/checks`。

确认接口必须校验案件、节点、Check 和当前用户上下文一致。

---

## 22. 前台产品需求

### 22.1 合同审查报告

报告页增加：

- “规则引擎评分，DeepSeek 负责解释”；
- 图版本、模型和证据快照摘要；
- 风险维度覆盖情况；
- 每条发现的合同原文、制度依据、影响、修改建议和复核点；
- 引用失效或知识范围变化提示；
- “范围受限报告”醒目标识；
- 检索降级提示；
- 人工确认/驳回发现入口作为后续反馈标签。

### 22.2 履约核验

时间节点详情内展示：

- 具体业务动作；
- 完整合同原文；
- 具体年月日和基准日期；
- 基准日期不确定提示与人工修改；
- 合同明确后果；
- AI 推断后果及免责声明；
- 需要完成的履约子项；
- 每个子项的合同依据、证据、判断和缺口；
- 证明文件上传入口；
- 发起核验、待补证、待确认、待重新核验状态；
- 人工确认入口；
- 可展开的历史核验和证据快照。

### 22.3 Agent 运行状态

用户端使用业务语言：

- 正在读取合同；
- 正在检查付款和验收条款；
- 正在查询企业制度；
- 正在核验证据；
- 发现证据缺口，正在补充检索；
- 分析完成，等待人工确认。

不展示 `DURATION_TERM`、`TEXT_DATE`、节点函数名等技术标签。

---

## 23. 管理端产品需求

### 23.1 Graph Runtime 配置

管理员可按任务类型设置：

- legacy；
- langgraph；
- shadow；
- 图版本；
- 最大补检索次数；
- 并发领域任务数；
- 工具预算；
- LLM Token 预算。

配置变更写入现有系统日志。

### 23.2 Run 详情可视化

提供两种视图：

- 时间线视图：按发生顺序查看；
- Graph 视图：查看节点、分支、循环和当前状态。

点击节点后显示输入摘要、输出摘要、工具调用、引用、质量门禁、错误和重试。

### 23.3 评测中心

管理员可以：

- 管理脱敏评测样本；
- 选择旧 Harness 或图版本运行；
- 查看逐案件差异；
- 查看风险召回、误报、引用正确率和成本；
- 标记差异属于回归、改进或允许变化；
- 阻止未达标版本发布。

---

## 24. 可靠性和性能

### 24.1 执行预算

预算按任务配置，不再全局固定：

| 任务 | 工具调用 | 补检索轮次 | 默认超时 |
|---|---:|---:|---:|
| 合同审查 | 20 | 2 | 10 分钟 |
| 履约核验 | 12 | 1 | 6 分钟 |
| 版本复核 | 16 | 2 | 8 分钟 |
| 合同录入提取 | 不进入 Graph v1 | - | 保持现状 |

预算是上限，不要求每次用满。

### 24.2 Redis ACK

- 正常 Graph：持久化报告和最终状态后 ACK；
- 人工中断：checkpoint 和 `WAITING_HUMAN` 状态落库后 ACK；
- resume 使用新消息；
- malformed 消息进入死信记录后 ACK；
- 重复消息依赖 run 状态与节点幂等键避免重复执行。

### 24.3 恢复

- Worker 崩溃后通过 Redis PEL 重新领取；
- 已有 checkpoint 时从最近成功节点恢复；
- 没有 checkpoint 时按现有 Run Recovery 处理；
- 恢复前验证合同、文件和知识快照是否仍可访问；
- 快照变化不偷偷替换，提示重跑。

### 24.4 性能目标

- P95 节点状态写入延迟小于 500ms；
- 管理端打开 Run 详情不加载完整大文本，原文按需读取；
- 并行领域任务默认不超过 3；
- 相同查询和同一快照允许短期检索缓存；
- 单个 Run State 必须控制体积，完整文件不写入 checkpoint。

---

## 25. 安全与权限

### 25.1 当前阶段

- 继续使用当前登录用户作为负责人、编辑者和复核者；
- 不在 UI 中虚构未实现的法务/采购角色权限；
- 所有人工确认记录操作者标识；
- Python Internal API 只允许内部网络和服务鉴权访问；
- Prompt、Trace 和报告中不得记录 API Key。

### 25.2 后续权限准备

状态和接口预留：

- `operatorId`；
- `requiredRole`；
- `allowedActions`；
- `dataScope`；
- `approvalPolicyVersion`。

多用户权限上线后，再启用职责分离和合同级访问控制。

### 25.3 数据隐私

- 评测样本必须脱敏；
- 合同原件不进入通用知识库；
- 日志只保存必要片段；
- 大段原文不写入普通 Trace；
- 模型调用需记录发送的文档版本和片段 ID；
- 软删除证据不能被新运行检索。

---

## 26. 准确率评测体系

### 26.1 评测集

第一版至少 30 份合同，逐步扩展到 100 份。覆盖：

- 技术服务；
- 货物采购；
- NDA/保密；
- 高预付款；
- 模糊验收；
- 责任上限缺失；
- 单方解除；
- 数据与知识产权；
- 日期和相对期限；
- 缺失条款；
- 无风险或低风险合同；
- 履约证据充分、部分充分、冲突和完全缺失。

每个样本包含：

- 脱敏合同；
- 适用制度；
- 标准答案 findings；
- 严重度；
- 合同引用；
- 政策引用；
- 必须发现项；
- 不应发现项；
- 可接受表达差异；
- 履约要求与证据标签。

### 26.2 核心指标

| 指标 | 定义 |
|---|---|
| 重大风险召回率 | 标注 HIGH 风险中被正确发现的比例 |
| 风险精确率 | Agent findings 中真实成立的比例 |
| 双引用正确率 | 合同和政策引用都正确支持发现的比例 |
| 引用可定位率 | citation 可回到真实文档、版本和片段的比例 |
| Unsupported Claim Rate | 缺乏证据的实质结论比例 |
| 缺失条款识别率 | 必须条款缺失被正确发现的比例 |
| 履约要求召回率 | 合同必需履约项被拆出的比例 |
| 证据匹配准确率 | 证据与履约子项正确关联比例 |
| Abstention Accuracy | 证据不足时正确保持待定的比例 |
| Schema Valid Rate | 最终产物一次或修复后通过 Schema 的比例 |
| Deterministic Consistency | 相同快照规则字段逐位一致比例 |

### 26.3 发布门槛

Graph Runtime v1 上线条件：

- 重大风险召回率不低于 90%，且不低于旧 Harness；
- 风险精确率不低于 80%；
- 双引用正确率不低于 95%；
- 引用可定位率 100%；
- Unsupported Claim Rate 不高于 3%；
- Schema Valid Rate 100%；
- Deterministic Consistency 100%；
- 高风险漏审数量不得高于旧 Harness；
- 无 P0 数据泄露、越权或错误自动确认问题。

样本量不足时指标只作为试运行结果，不宣称生产准确率。

### 26.4 Shadow Run 对比

逐位比较：

- riskScore；
- riskStatus；
- dimensions；
- scoringVersion；
- evidenceHash（输入快照一致时）；
- graph/runtime 元数据除外。

集合比较：

- findings 规则键；
- 合同引用 ID；
- 政策引用 ID；
- 使用工具集合。

语义或人工比较：

- 风险标题；
- 影响说明；
- 修改建议；
- 谈判建议；
- 报告摘要。

不得要求 LLM 文本逐字一致。

---

## 27. 测试策略

### 27.1 单元测试

- Graph 路由条件；
- State Schema；
- 节点幂等；
- 引用 ID 规范化；
- Claim Validator；
- 领域覆盖矩阵；
- 确定性评分；
- Resume 状态版本；
- 工具预算和循环上限；
- 知识范围过滤。

### 27.2 图级测试

使用 Fake LLM、Fake Tools 和内存 Checkpoint 测试：

- 一次通过；
- 缺证据后补检索通过；
- 两次补检索仍不足；
- 工具失败降级；
- Schema 修复成功和失败；
- 人工中断与恢复；
- 重复 resume；
- 运行中取消；
- 恢复时快照变化。

### 27.3 集成测试

- MySQL checkpoint；
- Redis Stream ACK/PEL；
- ES 正常和不可用；
- DeepSeek 正常、超时、限流和非法 JSON；
- 报告、发现、动作和核验历史持久化；
- Java 查询接口兼容。

### 27.4 E2E

1. 上传合同；
2. 完成解析；
3. 发起 Graph 审查；
4. 管理端查看完整路径；
5. 前台查看双引用报告；
6. 上传履约证明；
7. 发起核验；
8. 人工保持待定或确认；
9. 上传新证据；
10. 查看待重新核验与历史快照。

---

## 28. 迁移与发布方案

### 28.1 迁移原则

- 不同时重写编排、工具、存储和前端；
- 新旧 Runtime 共用稳定接口；
- 先修当前正确性问题，再引入图；
- 每一阶段可独立回滚；
- 旧 Harness 在 Graph 稳定前不删除；
- 数据迁移由 Python migration runner 执行。

### 28.2 Phase G0：评测基线与当前 Harness 修正

范围：

- 建立第一批合同评测样本；
- 补检索后重新执行 Reflection；
- Reflection 不通过时生成受限报告；
- 增加 Pydantic 产物 Schema；
- 修正 Prompt 中过时的 Runtime 所有权描述；
- 记录现有 Harness 指标。

验收：

- 旧 Harness 有可重复评测结果；
- 证据不足不会伪装成完整通过；
- 不改变现有 API。

### 28.3 Phase G1：Runtime 接口和 LangGraph 基础设施

范围：

- 新增 `AgentRuntime` 接口；
- 包装 Legacy Harness；
- 引入 LangGraph 并锁定版本；
- 建立 State、Graph Registry、Node Trace 和 `MySqlGraphCheckpointSaver`；
- 数据库动态路由和回滚配置；
- 最小测试图跑通。

验收：

- legacy/langgraph 可按任务动态切换；
- Graph 节点可观测；
- 失败可切回 legacy。

### 28.4 Phase G2：ContractReviewGraph

范围：

- 完整条款清单；
- 领域任务 fan-out/fan-in；
- 混合检索；
- 规则和证据对齐；
- Claim Validator；
- Reflection 补检索循环；
- 报告 Schema 和修复节点；
- Shadow Run。

验收：

- 达到合同审查发布门槛；
- 管理端可查看 Graph 路径；
- 至少连续 20 次 Shadow Run 无 P0 回归。

### 28.5 Phase G3：FulfillmentCheckGraph

范围：

- 履约子项拆解；
- 证据自动匹配和人工绑定；
- 逐项判断；
- 知识库检索；
- 人工确认中断与恢复；
- 新证据触发 stale；
- 历史查看。

验收：

- 不自动确认完成或验收通过；
- 证据不足能生成补证清单；
- 恢复后不重复调用已完成节点；
- 历史证据快照可追溯。

### 28.6 Phase G4：评测中心和发布门禁

范围：

- 管理端评测数据集；
- 批量运行；
- 新旧版本对比；
- 指标趋势；
- 发布门禁和回归记录。

### 28.7 Phase G5：后续业务图

按优先级建设：

1. VersionReviewGraph；
2. ApprovalDecisionGraph；
3. RenewalAssessmentGraph；
4. 规则影响巡检 Graph。

---

## 29. 工作量评估

### 29.1 最小准确率修正

预计修改 3 至 5 个文件，约 200 至 400 行：

- Reflection 闭环；
- 产物 Schema；
- 引用校验；
- 回归测试。

### 29.2 ContractReviewGraph 试点

预计新增或修改 8 至 15 个文件，约 800 至 1600 行代码和测试：

- Runtime 接口；
- Graph State；
- 审查图与节点；
- Checkpoint；
- Trace；
- Shadow 比较；
- Migration；
- 单元和集成测试。

### 29.3 完整范围

加入履约图、管理端 Graph 可视化和评测中心后属于中大型迭代，应按 G0-G4 分阶段交付，不建议作为一次提交完成。

---

## 30. 验收清单

### 30.1 架构

- [ ] `AgentRuntime` 外部接口稳定；
- [ ] Legacy 和 LangGraph 两个 Adapter 可用；
- [ ] Runtime 可数据库动态切换；
- [ ] Graph State 强类型且可序列化；
- [ ] 每个节点有明确输入、输出、预算和错误路由；
- [ ] checkpoint 可恢复；
- [ ] 旧 Harness 未提前删除。

### 30.2 合同审查

- [ ] 完整条款清单不受 20 条限制；
- [ ] 必查领域不能被 Planner 删除；
- [ ] 合同和知识库检索都执行；
- [ ] 补检索后重新验证；
- [ ] 未通过质量门禁不生成完整通过报告；
- [ ] 每个实质风险完成双引用或明确缺失依据；
- [ ] 风险分由规则引擎覆盖；
- [ ] 报告通过 Schema 和业务不变量校验。

### 30.3 履约核验

- [ ] 一个节点支持多个履约子项；
- [ ] 必需项都有合同原文依据；
- [ ] 证据和节点多对多；
- [ ] 证据快照包含版本、哈希和片段；
- [ ] 证据不足允许核验并保持待定；
- [ ] 最终结果必须人工确认；
- [ ] 新证据只提示重检，不自动调用 Agent；
- [ ] 历史核验可展开查看；
- [ ] 我方角色来自合同创建时配置。

### 30.4 可观测性

- [ ] 能看到调用 Agent 的业务目的；
- [ ] 能看到实际 Graph 路径；
- [ ] 能看到工具、参数、结果摘要和耗时；
- [ ] 能看到循环次数和补检索原因；
- [ ] 能看到质量门禁失败项；
- [ ] 能看到模型、Prompt、图版本和快照哈希；
- [ ] 前台不暴露内部技术标签。

### 30.5 评测

- [ ] 至少 30 个脱敏样本；
- [ ] 新旧 Runtime 可在同一快照对比；
- [ ] 指标计算可重复；
- [ ] 达到发布门槛；
- [ ] 每次图或 Prompt 发布记录评测结果。

---

## 31. 风险与应对

| 风险 | 影响 | 应对 |
|---|---|---|
| LangGraph 引入后重复一套持久化 | 数据不一致 | Graph State 只存工作状态，业务事实仍归 MySQL Store |
| 图节点过细 | 接口复杂、成本增加 | 保持深模块，按可独立重试或质量门禁划分节点 |
| 并行调用过多 | API 限流和成本上涨 | 并发上限、缓存、领域任务合并 |
| Reflection 仍由同一模型自证 | 可能放过错误 | 代码不变量优先，独立 Prompt/上下文，关键样本人工评测 |
| 长合同状态过大 | checkpoint 缓慢 | State 保存 ID 和摘要，正文按需读取 |
| Shadow Run 成本翻倍 | 测试成本上涨 | 只对抽样案件或管理端开启 |
| 评测集偏差 | 指标虚高 | 合同类型覆盖、困难负样本、定期人工复核 |
| 人工中断长期积压 | 状态和消息混乱 | 中断后 ACK，checkpoint 持久化，独立待办提醒 |
| 知识库规则冲突 | 结论不稳定 | 展示冲突来源和版本，转人工复核 |
| LLM 供应商波动 | 输出回归 | 模型版本记录、回归评测、动态回滚 |

---

## 32. 已确定决策

1. 使用 LangGraph，但渐进迁移。
2. 首个业务图为合同审查，第二个为履约核验。
3. 不在本阶段建设多 Agent 自由协作。
4. 使用 DAG 做领域并行，使用状态机处理循环、失败、人工确认和重检。
5. 规则和确定性评分继续保留，LLM 不直接决定风险分。
6. 合同审查和履约核验都必须查询知识库。
7. 履约最终结果必须人工确认。
8. 当前无多用户权限，MVP 不虚构复杂角色权限。
9. 我方甲乙方角色按合同创建时选择，不在核验时切换。
10. 履约不做数字评分，只使用风险和可信度高/中/低。
11. 新证据上传后只标记待重检，不自动调用 Agent。
12. 系统日志放管理端，前台只展示业务状态和必要摘要。
13. MySQL 继续保存业务数据，Graph checkpoint 只保存运行状态。
14. 旧 Harness 在 Graph 达标前保留作回滚和 Shadow 对照。

---

## 33. 待后续确认事项

以下事项不阻塞 G0-G2：

- 多用户和合同级权限模型；
- 图片、施工照片和视频的多模态真实性核验；
- 是否引入独立小模型作为 Claim Verifier；
- 企业环境的模型私有化部署；
- 主动定时巡检的触发策略；
- 历史人工反馈何时可以升级为正式规则；
- VersionReviewGraph 的自动重审范围；
- 评测样本的法务标注流程和责任人。

---

## 34. 术语表

| 术语 | 定义 |
|---|---|
| DAG | 无循环的有向图，适合并行领域分析后汇总 |
| State Graph | 允许条件边、循环和暂停恢复的执行图 |
| Graph State | 一次 Agent Run 的可恢复工作状态 |
| Node | 图中具有明确输入、输出和失败语义的执行节点 |
| Checkpoint | 可用于恢复运行的状态快照 |
| Reflection | 检查证据覆盖、引用和任务完成度的质量门禁 |
| Claim Validator | 验证结论是否被真实证据支持的模块 |
| Shadow Run | 同一输入运行新旧 Runtime，但只展示主版本结果 |
| Dual Citation | 一项合同风险同时引用合同依据和制度依据 |
| Evidence Snapshot | 本次判断使用的证据版本、哈希和片段快照 |
| Abstention | 证据不足时主动保持待定而不是猜测 |
| Runtime Adapter | 在稳定接口后接入 Legacy 或 LangGraph 的实现 |

---

## 35. 推荐立即执行顺序

1. 完成 G0：评测基线、Reflection 闭环和严格 Schema。
2. 建立 `AgentRuntime` 接口和 Legacy Adapter，不改变现有行为。
3. 实现 ContractReviewGraph 最小闭环。
4. 用固定案件执行 Shadow Run，先比较漏审和引用，不比较文案。
5. 达到发布门槛后将合同审查切到 LangGraph。
6. 再实施履约核验状态机和人工恢复。

本顺序能够先获得准确率收益，再承担框架迁移成本，并保证任何阶段都可以回到当前可用系统。

---

## 36. 开源法律项目业务参考与产品取舍

### 36.1 对比范围

开源法律项目与 Agent 框架承担的职责不同，不能把它们混在同一张“谁最好”的表中：

- Agent 框架回答“流程如何编排、暂停、恢复和观测”；
- 法律/合同项目回答“合同原文、标注、引用、审查类别和人工复核如何组织”；
- AtlasMind 还要补齐合同案件、企业知识、履约证据和全生命周期闭环。

本次业务参考项目：

- [OpenContracts](https://github.com/Open-Source-Legal/OpenContracts)；
- [CUAD](https://github.com/The-Atticus-Project/cuad)；
- [LegalBench-RAG](https://github.com/zeroentropy-ai/legalbenchrag)；
- [RAGFlow](https://github.com/infiniflow/ragflow)。

### 36.2 业务能力矩阵

| 业务能力 | OpenContracts | CUAD | LegalBench-RAG | RAGFlow | AtlasMind 目标 |
|---|---|---|---|---|---|
| 文档上传与解析 | 强 | 仅数据集 | 仅评测语料 | 强 | 保留现有解析流水线并增强可视化 |
| 精确原文 span | 强 | 强 | 强 | 有引用 | 必须建设统一 citation span |
| 人工标注/复核 | 强 | 专家标注数据 | 不提供业务 UI | 支持流程人工输入 | 风险发现和履约子项都可人工确认 |
| 合同风险类别 | 通用标注 | 41 类英文合同问题 | 非目标 | 非目标 | 中国采购/服务合同风险目录 |
| 企业制度知识 | 可做语料库 | 无 | 无 | 强 RAG | GLOBAL/SPECIFIC_CASES/DISABLED 权限范围 |
| Agent DAG/状态机 | 非主能力 | 无 | 无 | 通用 Canvas | 合同专用 LangGraph |
| 审查规则和确定性评分 | 无内置合同规则 | 无 | 无 | 无 | 现有规则引擎和固定评分 |
| 合同案件与版本 | Corpus/Document 版本 | 无 | 无 | 知识文档版本 | 合同案件、版本复核和历史报告 |
| 履约时间节点 | 无完整业务闭环 | 无 | 无 | 可自定义流程 | 时间节点、证据、核验和人工确认 |
| 付款/验收证明 | 无专用模型 | 无 | 无 | 文件问答 | 履约证据多对多与证据快照 |
| 协商/审批动作 | 非核心 | 无 | 无 | 通用工作流 | 审查发现到审批动作闭环 |
| 到期/续签运营 | 非核心 | 无 | 无 | 非核心 | 合同生命周期后续能力 |
| 检索准确率评测 | 非核心 | 片段任务 | 强 | 检索能力强 | 中文字符级检索评测 + 结论评测 |

这张表说明：没有一个参考项目可以直接替代 AtlasMind。AtlasMind 的差异化不应是“也能上传合同并聊天”，而应是“把精确引用、企业制度、规则审查、履约证据、人工确认和后续动作放在同一案件生命周期里”。

### 36.3 OpenContracts：参考证据事实层

#### 值得采用

OpenContracts 以 Corpus、Document、Annotation、Relationship 和 Citation Graph 组织文档智能，并支持精确文本坐标标注、结构化批量提取和逐项人工 approve/reject。

AtlasMind 应采用以下业务设计：

1. **原文跨度是一等数据**：风险、时间节点、履约要求和证据判断都保存可定位的原文 span，而不只保存截断字符串。
2. **标注与结论分离**：用户可以确认“这段原文是什么”，也可以单独确认“Agent 对它的判断是否正确”。
3. **关系是一等数据**：合同条款、制度条款、风险发现、履约子项和证明文件之间建立可查询关系。
4. **逐项人工复核**：报告不仅有整体“确认”，每条 finding 和 requirement 都应允许确认、驳回或修改。
5. **解析器可替换**：DOCX、PDF、MinerU、OCR 只负责产生统一 Document Block/Span，后续审查不绑定具体解析器。

#### 不采用

- 不引入其完整 Django、React、GraphQL 和 Corpus 产品体系；
- 不复制公开语料 fork 和社区协作模型；
- 不用 Citation Graph 替代 AtlasMind 的合同业务关系；
- 不让通用文档 Agent 替代合同审查和履约状态机。

#### 转化为 AtlasMind 需求

| 需求 ID | 产品需求 |
|---|---|
| BUS-OC-01 | `Citation` 增加 blockId、charStart、charEnd、page、documentVersion、contentHash |
| BUS-OC-02 | 合同详情提供原文定位，点击引用跳到对应页/段 |
| BUS-OC-03 | 审查发现支持确认、驳回、修改严重度和补充引用 |
| BUS-OC-04 | 履约要求支持确认“来自合同”或降级为“AI 建议” |
| BUS-OC-05 | 人工反馈保留原 Agent 输出和修改后值，形成评测标签 |

参考：[OpenContracts README](https://github.com/Open-Source-Legal/OpenContracts#readme)、[Pipeline Overview](https://github.com/Open-Source-Legal/OpenContracts/blob/main/docs/pipelines/pipeline_overview.md)。

### 36.4 CUAD：参考风险覆盖目录和标注方法

CUAD 提供商业合同审查数据和专家标注片段，其价值是风险类别覆盖和原文 span 标注，不是 Agent Runtime。

#### 值得采用

1. 建立“风险类别 → 问题定义 → 正反例 → 原文 span → 严重度规则”的审查目录；
2. 评测时按类别统计 recall，而不是只看整体报告是否像样；
3. 对每个类别同时准备“应命中”和“不应命中”的负样本；
4. 将遗漏的高风险类别作为发布阻断项。

#### 必须本地化

- CUAD 主要是英文商业合同，不能直接代表中国采购和技术服务合同；
- 41 类不能直接变成 AtlasMind 的唯一分类法；
- 必须补充中国业务常见的发票、验收、付款前提、质保、印章授权、数据出境、成果归属、不可抗力通知等类别；
- 公开数据授权未完全确认前，不进入产品训练数据分发。

#### AtlasMind 风险目录结构

```text
一级维度
  └── 二级风险类别
       ├── 适用合同类型
       ├── 必查条款类型
       ├── 规则键
       ├── 正例与反例
       ├── 必需证据
       ├── 默认严重度
       └── 人工升级条件
```

#### 转化为 AtlasMind 需求

| 需求 ID | 产品需求 |
|---|---|
| BUS-CUAD-01 | 管理端新增风险覆盖目录，关联现有审查规则和标准条款 |
| BUS-CUAD-02 | Run 详情显示本次已覆盖、无适用证据和未完成的类别 |
| BUS-CUAD-03 | Golden Dataset 按类别统计 HIGH 风险召回率 |
| BUS-CUAD-04 | Planner 不能删除合同类型规定的必查类别 |
| BUS-CUAD-05 | 人工新增遗漏风险时必须选择或新建风险类别 |

参考：[CUAD Repository](https://github.com/The-Atticus-Project/cuad)、[CUAD Paper](https://arxiv.org/abs/2103.06268)。

### 36.5 LegalBench-RAG：参考引用与检索评测

LegalBench-RAG 用 query 和精确字符区间 ground truth 评测法律检索，可计算字符级 precision 和 recall。它解决的是“检索是否找到准确片段”，不解决最终法律判断。

#### 值得采用

1. 评测最小相关片段，而不是仅判断命中了哪个文档；
2. 同时衡量召回和无关上下文，防止把整页合同塞给模型也算命中；
3. 建立 mini 集用于每次提交快速回归，完整集用于发布前评测；
4. 对关键词、向量、融合和 rerank 分别记录指标。

#### 转化为 AtlasMind 需求

| 需求 ID | 产品需求 |
|---|---|
| BUS-LBR-01 | Retrieval Dataset 保存 query、documentId、charStart、charEnd |
| BUS-LBR-02 | 评测中心展示字符级 precision、recall、MRR 和无关上下文率 |
| BUS-LBR-03 | 每条 finding 只能引用实际进入判断上下文的片段 |
| BUS-LBR-04 | 检索 Trace 保存原始 rank、融合 rank、score、rerank score 和 chunk hash |
| BUS-LBR-05 | ES 或 Embedding 降级运行不纳入正常模型准确率指标 |

参考：[LegalBench-RAG README](https://github.com/zeroentropy-ai/legalbenchrag#readme)、[Paper](https://arxiv.org/abs/2408.10343)。

### 36.6 RAGFlow：参考文档检索、调试和补证交互

RAGFlow 的价值在于深度文档解析、切片可视化、多路召回、融合重排，以及 Canvas 中的条件、循环和 Await Response。AtlasMind 不需要引入整套平台，但应复用这些产品思想。

#### 值得采用

1. **切片可见**：管理员可以查看一个引用来自哪份文件、哪一页、哪个切片和父条款；
2. **多路召回**：BM25 与向量并行，融合后再重排；
3. **调试可见**：节点显示输入、输出、thought 摘要、工具和命中结果；
4. **Await Response**：缺材料时明确向用户索要文件、文本、选项或确认；
5. **可恢复循环**：补材料后从等待点继续，而不是重新执行全部节点。

#### 不采用

- 不引入第二套 MySQL、Redis、MinIO、Elasticsearch 和知识库；
- 不把通用 Canvas 暴露给普通合同用户；
- 不允许管理员随意拖拽绕过合同质量门禁；
- 不用通用 RAG 回答替代规则审查和履约逐项判断。

#### 转化为 AtlasMind 需求

| 需求 ID | 产品需求 |
|---|---|
| BUS-RF-01 | 管理端提供切片和父条款双层查看 |
| BUS-RF-02 | 检索实现 BM25 + Vector + RRF，后续接可配置 reranker |
| BUS-RF-03 | Graph 节点详情展示 query、候选、融合与最终上下文 |
| BUS-RF-04 | 履约缺口可以生成结构化补证请求，直接打开上传入口 |
| BUS-RF-05 | 人工补证后使用 resume/recheck，不重复已完成的无关节点 |

参考：[RAGFlow README](https://github.com/infiniflow/ragflow#readme)、[Flow Control Components](https://github.com/infiniflow/ragflow/blob/main/docs/guides/agent/agent_workflow/flow_control_components.md)。

### 36.7 AtlasMind 的业务差异化

参考项目普遍聚焦文档智能、风险片段数据或通用 RAG。AtlasMind 应把以下完整业务链作为产品主线：

```text
合同录入
  → AI 提取与人工确认
  → 签署前风险审查
  → 修改/谈判/法务复核动作
  → 审批与版本复核
  → 合同时间节点和履约要求
  → 证明材料上传与 Agent 核验
  → 人工确认
  → 到期、续签和终止评估
```

核心产品对象不是聊天消息，也不是单份文档，而是“合同案件”。所有 Agent Run、引用、发现、动作、时间节点、证据和人工确认都归属于案件及明确版本。

### 36.8 业务模块建设优先级

| 优先级 | 模块 | 用户价值 | 开源参考 |
|---|---|---|---|
| P0 | 精确引用与原文定位 | 用户可以验证结论，不再面对截断片段 | OpenContracts、LegalBench-RAG |
| P0 | 风险覆盖矩阵 | 防止长合同漏审关键类别 | CUAD |
| P0 | 合同审查 Graph | 证据不足可补检索并复核 | LangGraph |
| P0 | 履约证据工作台 | 上传、绑定、核验、补证和历史闭环 | OpenContracts、RAGFlow |
| P1 | 检索与评测中心 | 能证明准确率变化 | LegalBench-RAG、Pydantic Evals |
| P1 | 版本影响审查 | 只复核变更影响范围 | LangGraph DAG |
| P1 | 风险发现人工反馈 | 形成企业自己的高质量评测标签 | OpenContracts |
| P2 | 续签和终止评估 | 从审查工具扩展为生命周期运营 | AtlasMind 自有业务 |

### 36.9 不应走的产品方向

- 不做只有一个大输入框的“合同 ChatGPT”；
- 不把报告字数增加等同于判断准确；
- 不用多个角色 Agent 的讨论过程代替证据校验；
- 不复制通用知识库产品，忽略合同案件、版本和履约状态；
- 不只展示风险列表而没有后续动作、补证和人工确认；
- 不把英文 benchmark 的公开成绩宣传成中文合同效果；
- 不让可视化 Canvas 变成绕过规则和审批的后门。

### 36.10 业务验收标准

- [ ] 用户从任一风险可跳转到准确合同原文和制度原文；
- [ ] 报告显示风险类别覆盖矩阵，不因 TopK 截断漏掉必查领域；
- [ ] 用户可以逐条确认、驳回或修改 Agent 发现；
- [ ] 人工修改保留前后值并进入评测数据；
- [ ] 履约缺口可以直接转成补证清单和上传动作；
- [ ] 新证据上传后历史判断不被覆盖；
- [ ] 管理员可以查看检索候选、融合排序和最终引用；
- [ ] 合同审查、履约核验和知识库都归属于明确案件与版本；
- [ ] 产品能够完成“发现问题 → 给出动作 → 补充证据 → 人工确认”的闭环；
- [ ] 前台使用合同业务语言，不显示框架和内部抽取技术标签。
