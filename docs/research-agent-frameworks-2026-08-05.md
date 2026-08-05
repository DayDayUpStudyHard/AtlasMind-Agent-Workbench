# AtlasMind 合同 Agent 图运行时开源项目调研

> 调研日期：2026-08-05  
> 调研范围：Agent 图编排框架、合同审查/法律 RAG、文档工作流  
> 资料原则：只采用项目官方 GitHub 仓库、官方文档、官方源码和项目作者论文。功能事实均附一手来源 URL；“适配度”“建议”属于本文针对 AtlasMind 的工程判断。

## 1. 执行摘要

### 1.1 推荐结论

AtlasMind 应采用以下组合，而不是选择一个框架替换全部现有能力：

1. **LangGraph 作为图编排内核**：负责显式 DAG、条件分支、反思循环、检查点、暂停和恢复。它定位于长运行、有状态 Agent 的低层编排，并原生提供持久化检查点与 interrupt/resume 机制。[LangGraph README](https://github.com/langchain-ai/langgraph#readme) [Graph API](https://docs.langchain.com/oss/python/langgraph/graph-api) [Persistence](https://docs.langchain.com/oss/python/langgraph/persistence) [Interrupts](https://docs.langchain.com/oss/python/langgraph/interrupts)
2. **继续使用 Pydantic 做状态、工具参数、报告和引用校验**；可单独引入 `pydantic-evals` 建立合同评测集，但第一阶段不必将整个 LLM 调用层迁移到 PydanticAI。PydanticAI 的强项是类型安全工具、结构化输出、延迟工具审批、OpenTelemetry 与系统化评测；其耐久执行则通过 Temporal、DBOS、Prefect、Restate 等外部执行系统集成。[PydanticAI README](https://github.com/pydantic/pydantic-ai#readme) [Durable Execution](https://ai.pydantic.dev/durable_execution/overview/) [Deferred Tools](https://ai.pydantic.dev/deferred-tools/) [Evals](https://ai.pydantic.dev/evals/)
3. **保留 Redis Stream、MySQL、Elasticsearch、现有 Tool Registry 和业务报告表**。LangGraph 的 Graph State 只保存可恢复的运行状态；合同、证据、报告、人工确认仍由 AtlasMind 业务表保存。这样可以渐进迁移并随时切回旧 Harness。
4. **准确率提升不能只靠换框架**。应优先引入 LegalBench-RAG 的字符级检索评测思想、CUAD 的合同审查类别覆盖、OpenContracts 的“精确原文跨度 + 人工标注 + 引用关系”设计，以及 RAGFlow 的多路召回、融合重排和可视化切片思想。[LegalBench-RAG README](https://github.com/zeroentropy-ai/legalbenchrag#readme) [CUAD](https://github.com/The-Atticus-Project/cuad) [OpenContracts README](https://github.com/Open-Source-Legal/OpenContracts#readme) [RAGFlow README](https://github.com/infiniflow/ragflow#readme)
5. **不建议将 AutoGen、CrewAI 或 Semantic Kernel 作为 AtlasMind 主运行时**。AutoGen 已明确进入维护模式；Semantic Kernel 官方 README 已将 Microsoft Agent Framework 标为后继方向；CrewAI 更适合角色化多 Agent 与高层自动化，和 AtlasMind 当前强调可控判断、确定性门禁、证据链的目标不完全一致。[AutoGen README](https://github.com/microsoft/autogen#readme) [Semantic Kernel README](https://github.com/microsoft/semantic-kernel#readme) [CrewAI README](https://github.com/crewAIInc/crewAI#readme)

### 1.2 建议技术组合

| 层次 | 推荐选择 | 说明 |
|---|---|---|
| 异步任务分发 | 保留 Redis Stream | 继续承担 Consumer Group、ACK、PEL、重试和 Worker 扩缩容 |
| Agent 图编排 | LangGraph | 只替换 `AgentRunner.execute()` 内部编排，不改 Java API 和前端契约 |
| 业务状态与事实 | 保留 MySQL | 合同、证据、报告、人工确认、运行记录仍是事实源 |
| Graph Checkpoint | LangGraph Checkpointer 适配现有 MySQL，或独立 PostgreSQL | 不与业务表混写；通过 `run_id/thread_id` 建立关联 |
| 数据校验 | Pydantic BaseModel + 自定义业务 Validator | 校验引用存在性、证据覆盖、风险等级一致性和必填字段 |
| Agent 评测 | 自建 Golden Dataset + 可选 `pydantic-evals` | 离线评测结果、引用、工具轨迹和检索质量 |
| 检索 | Elasticsearch 关键词 + 向量并行召回 + 融合重排 | 不用“向量有结果就停止关键词检索”的降级式结构 |
| 可观测性 | 保留 AtlasMind Run/Trace/ToolCall UI，并补 OpenTelemetry | 不把生产可观测性强绑定到单一商业控制台 |

## 2. AtlasMind 的选型约束

AtlasMind 当前已经具备 Planner、原生 Function Calling、工具白名单、调用预算、Reflection、MySQL Trace/ToolCall/Report/Memory、Redis Stream Worker、合同规则与知识库检索。现有实现集中在 Python Runtime 的 [runner.py](https://github.com/DayDayUpStudyHard/AtlasMind-Agent-Workbench/blob/master/tools/chat-assistant/backend/app/agent_runtime/runner.py)、[worker.py](https://github.com/DayDayUpStudyHard/AtlasMind-Agent-Workbench/blob/master/tools/chat-assistant/backend/app/agent_runtime/worker.py) 和 [persistence.py](https://github.com/DayDayUpStudyHard/AtlasMind-Agent-Workbench/blob/master/tools/chat-assistant/backend/app/agent_runtime/persistence.py)。

因此新框架必须满足：

- 能渐进接入，不能要求重写现有工具、Redis Worker 和业务持久化；
- 能表达合同审查的并行维度 DAG、补检索/再反思循环；
- 能表达履约核验的待补证、待人工确认、上传新证据后重新核验；
- 支持节点级测试、运行恢复和详细轨迹；
- 允许确定性规则、业务 Validator 和人工确认拥有最终决策权；
- 不以多 Agent 自由对话代替合同证据核验。

## 3. Agent 框架逐项调研

## 3.1 LangGraph

### 定位与编排模型

LangGraph 官方将其定义为构建长运行、有状态 Agent 的低层编排框架，可以独立于 LangChain 使用。Graph API 以 State、Node、Edge 为核心，支持普通边、条件边、`Send`、`Command`、子图和 reducer，适合显式 DAG、循环和状态机。[README](https://github.com/langchain-ai/langgraph#readme) [Graph API](https://docs.langchain.com/oss/python/langgraph/graph-api)

### 状态与持久化

图编译时可注入 checkpointer；状态快照按 `thread_id` 保存。官方文档区分 checkpointer 的线程内短期状态与 store 的跨线程长期数据，并列出内存、SQLite、PostgreSQL 等持久化方式。检查点用于故障恢复、人机协作和 time travel。[Persistence](https://docs.langchain.com/oss/python/langgraph/persistence)

### 工具调用

官方 Quickstart 展示了“LLM 节点 -> 条件边 -> Tool 节点 -> LLM 节点”的工具循环；是否调用工具由模型返回的 tool calls 决定。AtlasMind 可保留现有工具注册表，只把工具执行包装为图节点，无需采用 LangChain 全套 Agent 抽象。[Quickstart](https://docs.langchain.com/oss/python/langgraph/quickstart)

### 人工中断

`interrupt()` 会暂停图、通过 checkpointer 保存状态，并等待 `Command(resume=...)` 恢复。官方文档明确要求中断前的副作用具备幂等性，并说明中断可用于审批、编辑状态和工具审批。[Interrupts](https://docs.langchain.com/oss/python/langgraph/interrupts)

### 可观测与评测

LangGraph 本身提供事件流、状态历史、节点级测试和部分执行；官方 README 将完整 tracing、轨迹评测和部署控制台指向 LangSmith。LangSmith 是相邻产品，不应成为 AtlasMind 核心业务数据唯一存储。[Testing](https://docs.langchain.com/oss/python/langgraph/test) [LangGraph README](https://github.com/langchain-ai/langgraph#readme) [LangSmith Observability](https://docs.langchain.com/langsmith/observability-concepts)

### 优点

- 与 AtlasMind 需要的 DAG、循环、分支、人工暂停和恢复高度匹配。
- 低层 API 允许复用现有 MySQL Store、Tool Registry、规则引擎和 Redis Worker。
- Checkpoint 和业务事实可以分层，适合渐进迁移和 Shadow Run。
- 节点可独立测试，有利于把“检索、判断、引用校验、反思”拆成可验证模块。[Testing](https://docs.langchain.com/oss/python/langgraph/test)

### 缺点

- 框架解决的是编排可靠性，不会自动提高合同判断准确率。
- State、reducer、幂等副作用、checkpoint 保留策略需要团队自行设计。
- 完整的可视化 tracing/eval 体验主要由 LangSmith 提供；若不采用 LangSmith，需要继续建设 AtlasMind 自有运行详情与 OTel 接入。[LangGraph README](https://github.com/langchain-ai/langgraph#readme)

### 对 AtlasMind 可复用设计

- `ContractReviewGraph`：上下文冻结 -> 风险维度并行检索 -> 规则检查 -> 初判 -> 引用校验 -> 补检索循环 -> 报告。
- `FulfillmentCheckGraph`：要求拆分 -> 证据匹配 -> 逐项判断 -> 缺口 -> 人工确认 interrupt -> resume。
- `run_id` 映射 `thread_id`，每个节点写入现有 Agent Trace。
- 对外保留 `AgentRuntime.run()/resume()` 接口，旧 Harness 与 LangGraph 并存。

### 不建议照搬

- 不把全部业务数据塞入 Graph State。
- 不直接用通用 ReAct Agent 替代合同专用节点和质量门禁。
- 不让 LangGraph Server 替代现有 Redis Stream 调度层。
- 不在第一阶段绑定 LangSmith 托管部署。

### 许可证与活跃度

代码采用 MIT License；GitHub API 在调研时显示仓库未归档、最近推送为 2026-08-02，GitHub latest release 为 `checkpointsqlite==3.1.1`，发布于 2026-07-30。[LICENSE](https://github.com/langchain-ai/langgraph/blob/main/LICENSE) [Repository metadata](https://api.github.com/repos/langchain-ai/langgraph) [Latest release](https://github.com/langchain-ai/langgraph/releases/tag/checkpointsqlite%3D%3D3.1.1)

## 3.2 PydanticAI / Pydantic Graph

### 定位与编排模型

PydanticAI 是类型安全的 Python Agent 框架，强调模型无关、依赖注入、结构化输出、工具、MCP、可观测和评测。`pydantic-graph` 是独立的异步图/有限状态机库，节点和边通过类型提示定义；当前官方文档还提供 Graph Builder、Decision、Join 和 Parallel Execution。[README](https://github.com/pydantic/pydantic-ai#readme) [Pydantic Graph](https://ai.pydantic.dev/graph/)

### 状态与持久化

Pydantic Graph 提供类型化运行上下文和状态；PydanticAI 的耐久执行官方支持 Temporal、DBOS、Prefect、Restate，并将长运行、人机协作和故障恢复交给这些执行后端。它不像 LangGraph 那样以自带 checkpointer 抽象为核心，因此接入 AtlasMind 当前 Redis/MySQL 恢复模型时需要额外适配。[Durable Execution](https://ai.pydantic.dev/durable_execution/overview/)

### 工具调用与人工中断

函数签名和 Pydantic 类型用于生成工具 schema，`RunContext` 提供依赖注入。Deferred Tools 支持“需要批准的工具”和“外部执行的工具”；调用可以进程内处理，也可以结束当前 run，在后续 run 中提供审批或执行结果。[Function Tools](https://ai.pydantic.dev/tools/) [Deferred Tools](https://ai.pydantic.dev/deferred-tools/)

### 可观测与评测

PydanticAI 可通过 Logfire 生成 Agent、模型请求和工具调用 span，也支持其他 OpenTelemetry 后端。`pydantic-evals` 提供 Dataset、Case、Evaluator、实验、多轮运行和基于 OTel span 的 Agent 轨迹评测。[Logfire](https://ai.pydantic.dev/logfire/) [Evals](https://ai.pydantic.dev/evals/)

### 优点

- 结构化输出、工具参数和依赖注入能力强，适合合同报告 schema 与业务 Validator。
- Evals 同时覆盖最终结果与工具轨迹，适合评测“答案是否正确”和“过程是否合规”。
- Deferred Tools 对高风险动作审批表达清晰。
- OpenTelemetry 不强制绑定 Logfire 后端。[Logfire](https://ai.pydantic.dev/logfire/)

### 缺点

- 图、Agent、durable execution、评测分布在多个包和外部执行后端中，整体接入面比单纯引入 LangGraph 大。
- 若为耐久执行再引入 Temporal/DBOS/Prefect/Restate，会与 AtlasMind 已有 Redis Worker 和恢复机制产生职责重叠。
- 类型安全只能阻止格式错误，不能替代“引用是否支持结论”的业务语义校验。

### 对 AtlasMind 可复用设计

- 使用 Pydantic BaseModel 定义 `ContractReviewState`、`Finding`、`Citation`、`FulfillmentItem`。
- 编写 Validator：引用 ID 必须存在；HIGH 风险必须有合同原文；知识库引用必须符合当前合同范围；必需履约项必须来源于合同原文。
- 试点 `pydantic-evals` 管理 Golden Dataset 和 span-based trajectory evaluator。
- 可参考 Deferred Tools 设计未来“发送通知/创建审批/生成外部任务”的审批协议。

### 不建议照搬

- 第一阶段不把全部 LLM Gateway、工具注册和运行持久化迁移到 PydanticAI。
- 不为了 durable execution 再引入一个工作流基础设施。
- 不用多 Agent 抽象替代合同维度节点。

### 许可证与活跃度

项目采用 MIT License；GitHub API 在调研时显示未归档、最近推送为 2026-08-04；最新 release `v2.23.0` 发布于 2026-08-04。[LICENSE](https://github.com/pydantic/pydantic-ai/blob/main/LICENSE) [Repository metadata](https://api.github.com/repos/pydantic/pydantic-ai) [v2.23.0](https://github.com/pydantic/pydantic-ai/releases/tag/v2.23.0)

## 3.3 Microsoft AutoGen

### 定位与编排模型

AutoGen 用于构建自主或人机协作的多 Agent 应用。Core API 提供消息传递、事件驱动 Agent、本地/分布式 runtime；AgentChat 提供 RoundRobin、Selector、Swarm 等高层团队模式；Extensions 提供模型、代码执行、MCP 和其他工具集成。[README](https://github.com/microsoft/autogen#readme)

### 状态与持久化

Agent 和 Team 暴露 `save_state/load_state`；官方状态教程说明状态可序列化到文件或数据库，但持久化介质和事务由应用实现。[Managing State](https://github.com/microsoft/autogen/blob/main/python/docs/src/user-guide/agentchat-user-guide/tutorial/state.ipynb)

### 工具调用与人工中断

`FunctionTool` 根据函数描述和类型注解生成 JSON Schema，Core 还提供 MCP、HTTP、GraphRAG 和代码执行工具。HITL 可以使用 `UserProxyAgent` 在运行中阻塞等待输入，或在 Team 停止后保存状态并在下一次运行提供反馈；官方教程明确指出运行中阻塞方式会使 Team 处于无法保存/恢复的不稳定状态，短交互之外更推荐“终止、持久化、下一次运行恢复”。[Tools](https://github.com/microsoft/autogen/blob/main/python/docs/src/user-guide/core-user-guide/components/tools.ipynb) [Human in the Loop](https://github.com/microsoft/autogen/blob/main/python/docs/src/user-guide/agentchat-user-guide/tutorial/human-in-the-loop.ipynb)

### 可观测与评测

AutoGen 对 runtime、tool 和 AgentChat Agent 提供 OpenTelemetry span；仓库包含 AutoGen Bench/AGBench 基准套件和 Studio 原型界面。[Telemetry](https://github.com/microsoft/autogen/blob/main/python/docs/src/user-guide/core-user-guide/framework/telemetry.md) [README](https://github.com/microsoft/autogen#readme)

### 优点

- 多 Agent 消息协议、分布式 runtime 和团队模式成熟。
- 工具生态广，OpenTelemetry 接入明确。
- `save_state/load_state` 允许应用选择持久化介质。

### 缺点

- 官方已明确进入 maintenance mode，不再获得新功能或增强，并推荐新项目使用 Microsoft Agent Framework。[README](https://github.com/microsoft/autogen#readme)
- 核心抽象偏多 Agent 消息协作，不是合同审查所需的显式证据 DAG 和质量门禁。
- 运行中 HITL 的可恢复性限制不适合可能等待数小时或数天的法务审批。[Human in the Loop](https://github.com/microsoft/autogen/blob/main/python/docs/src/user-guide/agentchat-user-guide/tutorial/human-in-the-loop.ipynb)

### 对 AtlasMind 可复用设计

- 参考 Agent/Team 状态序列化接口和 OTel span 命名。
- 参考“短交互阻塞、长等待先终止并持久化”的 HITL 边界。
- 参考工具 schema 和 MCP 适配，但无需采用 AutoGen Runtime。

### 不建议照搬

- 不采用 GroupChat/Swarm 作为合同审查主流程。
- 不让多个 Agent 自由辩论决定合同风险。
- 不在维护模式框架上建设新的核心运行时。

### 许可证与活跃度

仓库根 `LICENSE` 为 CC BY 4.0，代码由 `LICENSE-CODE` 明确采用 MIT；GitHub API 在调研时显示最近推送为 2026-04-15，最新 release `python-v0.7.5` 发布于 2025-09-30。活跃度必须结合官方“maintenance mode”声明理解。[LICENSE](https://github.com/microsoft/autogen/blob/main/LICENSE) [LICENSE-CODE](https://github.com/microsoft/autogen/blob/main/LICENSE-CODE) [Repository metadata](https://api.github.com/repos/microsoft/autogen) [python-v0.7.5](https://github.com/microsoft/autogen/releases/tag/python-v0.7.5)

## 3.4 CrewAI

### 定位与编排模型

CrewAI 提供两层抽象：Crews 用角色、目标和任务组织自主 Agent 团队；Flows 用 `@start`、`@listen`、`@router`、`and_`、`or_` 组织事件驱动工作流，支持分支、循环和多个启动节点。[README](https://github.com/crewAIInc/crewAI#readme) [Flows](https://docs.crewai.com/en/concepts/flows)

### 状态与持久化

Flows 支持字典式非结构化状态和 Pydantic 结构化状态，每个状态带 UUID。`@persist` 可应用到类或方法，默认使用 SQLiteFlowPersistence，并支持按状态 ID 恢复或 fork 历史状态。[Flows](https://docs.crewai.com/en/concepts/flows)

### 工具调用与人工中断

Agent 可使用自定义工具和 `crewai_tools`。Flows 的 `@human_feedback` 可暂停执行收集审批、质量复核或决策反馈，文档还指向异步/非阻塞自定义 provider 的实现方式。[README](https://github.com/crewAIInc/crewAI#readme) [Flows](https://docs.crewai.com/en/concepts/flows)

### 可观测与评测

官方 README 将托管部署、可观测、治理和安全控制台归于 CrewAI AMP Suite；开源仓库自身还包含可关闭的匿名产品遥测。本文审阅资料没有显示与 `pydantic-evals` 或 LegalBench-RAG 同等的开源、代码优先评测模型。[README](https://github.com/crewAIInc/crewAI#readme)

### 优点

- 高层 API 上手快，Flow 同时支持结构化状态、路由、持久化和 HITL。
- 角色化 Crew 适合研究、内容生成和职责明确的协作自动化。
- Python 原生，工具和模型接入丰富。

### 缺点

- Crew 的“角色、目标、backstory”容易把合同系统带向多 Agent 表演，而不是可验证判断。
- 默认 SQLite 持久化与 AtlasMind MySQL/Redis 体系不一致，需要自定义适配。
- 完整企业可观测与治理能力主要放在 AMP Suite，若不采用其平台仍需建设自有轨迹系统。[README](https://github.com/crewAIInc/crewAI#readme)

### 对 AtlasMind 可复用设计

- 参考 Flow 的结构化状态、router、fork/resume 和 human feedback UX。
- 参考将确定性 Python 代码与 Agent 节点混合，而不是每一步都调用 LLM。

### 不建议照搬

- 不建立“审查 Agent、法务 Agent、谈判 Agent”自由对话 Crew。
- 不迁移到 CrewAI 的内置 memory/knowledge/persistence，避免形成第二套事实源。
- 不把 AMP 作为运行所必需的控制平面。

### 许可证与活跃度

项目采用 MIT License；GitHub API 在调研时显示未归档、最近推送为 2026-08-04；最新 release `1.15.10` 发布于 2026-07-31。[LICENSE](https://github.com/crewAIInc/crewAI/blob/main/LICENSE) [Repository metadata](https://api.github.com/repos/crewAIInc/crewAI) [1.15.10](https://github.com/crewAIInc/crewAI/releases/tag/1.15.10)

## 3.5 Microsoft Semantic Kernel

### 定位与编排模型

Semantic Kernel 是模型无关 SDK，提供 Agent Framework、插件/函数、MCP、memory/planning 和 Process Framework。Process Framework 用事件驱动步骤表达业务流程，强调定义式控制和 OpenTelemetry 审计；官方页面同时标明该 Process Framework package 仍为 experimental。[README](https://github.com/microsoft/semantic-kernel#readme) [Process Framework](https://learn.microsoft.com/en-us/semantic-kernel/frameworks/process/process-framework)

### 状态、工具、人工中断

Kernel Plugin 可来自原生函数、Prompt、OpenAPI 或 MCP。Process Framework 以步骤输入/输出和事件连接流程，但本文审阅的官方页面没有给出类似 LangGraph checkpointer 的稳定、通用恢复契约；长等待的人机协作需要在应用或外部执行层补齐。[README](https://github.com/microsoft/semantic-kernel#readme) [Process Framework](https://learn.microsoft.com/en-us/semantic-kernel/frameworks/process/process-framework)

### 可观测与评测

Process Framework 官方说明支持通过 OpenTelemetry 进行审计。Semantic Kernel 的优势更偏 Microsoft 企业 SDK 集成；本文审阅范围内没有发现面向合同 Agent 的专用检索/引用评测方案。[Process Framework](https://learn.microsoft.com/en-us/semantic-kernel/frameworks/process/process-framework)

### 优点

- .NET、Python 和 Java 生态覆盖，插件模型适合企业系统集成。[README](https://github.com/microsoft/semantic-kernel#readme)
- 事件驱动 Process 与确定性业务步骤结合的思路适合审批类流程。
- MIT License，OpenTelemetry 方向明确。

### 缺点

- 官方 README 已将 Microsoft Agent Framework 标为后继方向并提供迁移指南，新项目存在技术路线切换成本。[README](https://github.com/microsoft/semantic-kernel#readme)
- Process Framework 仍标为 experimental，不适合作为 AtlasMind 关键履约状态机的首选基础。[Process Framework](https://learn.microsoft.com/en-us/semantic-kernel/frameworks/process/process-framework)
- AtlasMind Agent Runtime 已迁移到 Python，Semantic Kernel 的跨语言优势不能抵消迁移成本。

### 对 AtlasMind 可复用设计

- 参考 Plugin 边界、事件驱动 Process 和 OTel 审计。
- 保留 Java 为 Thin Proxy、Python 为 Agent Runtime 的当前分工，不因跨语言 SDK 再搬回 Java。

### 不建议照搬

- 不在 experimental Process Framework 上实现第一版合同状态机。
- 不同时引入 Semantic Kernel 和 LangGraph 两套编排。
- 不在官方后继框架已经明确的情况下增加核心依赖。

### 许可证与活跃度

项目采用 MIT License；GitHub API 在调研时显示未归档、最近推送为 2026-08-03；最新 release `dotnet-1.78.0` 发布于 2026-07-07。仓库仍有更新，但官方战略方向已转向 Microsoft Agent Framework。[LICENSE](https://github.com/microsoft/semantic-kernel/blob/main/LICENSE) [Repository metadata](https://api.github.com/repos/microsoft/semantic-kernel) [dotnet-1.78.0](https://github.com/microsoft/semantic-kernel/releases/tag/dotnet-1.78.0) [README](https://github.com/microsoft/semantic-kernel#readme)

## 4. 法律、合同与文档项目调研

## 4.1 OpenContracts

### 定位与核心模型

OpenContracts 是开源文档智能平台，以 Corpus、Document、Annotation、Relationship 和 Citation Graph 为核心。它支持精确 PDF 文本坐标标注、全文/向量检索、文档或语料库范围 Agent、结构化批量提取、GraphQL/REST 和 MCP。[README](https://github.com/Open-Source-Legal/OpenContracts#readme)

### 状态、工具、人工复核与可观测

Corpus 具有版本、历史和权限；结构化提取通过 Celery worker 并行运行，每个单元格支持人工 approve/reject。MCP 暴露 `search_corpus`、`get_document_text`、`list_annotations`、`list_relationships` 等工具。README 展示 Agent 的工具调用弹层和带原文引用的回答，但未把自己定位为通用耐久 Agent 图运行时。[README](https://github.com/Open-Source-Legal/OpenContracts#readme) [MCP docs](https://github.com/Open-Source-Legal/OpenContracts/tree/main/docs/mcp)

### 优点

- 把“精确原文跨度、人工标注、文档关系、Agent 引用”放在同一事实层。
- Parser、Embedder、Thumbnailer 可替换，后续搜索/标注/Agent 不受影响。[Pipeline](https://github.com/Open-Source-Legal/OpenContracts/blob/main/docs/pipelines/pipeline_overview.md)
- PDF、DOCX、TXT 以及可转换格式的文档处理面完整。[Supported formats](https://github.com/Open-Source-Legal/OpenContracts/blob/main/docs/upload_methods/supported_formats.md)

### 缺点

- 是完整文档平台，不是可嵌入的小型 Agent 编排库；整体采用会重复 AtlasMind 已有合同、知识库、前端和权限模型。
- Citation Graph 面向广义文献关系，合同“要求 -> 履约证据 -> 人工结论”仍需 AtlasMind 自己建模。

### AtlasMind 可复用与不建议照搬

可复用：精确 span citation、人工标注作为 ground truth、引用关系、批量提取逐项审批、解析器/嵌入器接口隔离。  
不照搬：整套 Django/React/GraphQL 平台、公开语料 fork/社区机制、用其 Agent 替换 AtlasMind Runtime。

### 许可证与活跃度

MIT License；GitHub API 在调研时显示未归档、最近推送为 2026-08-04；最新 release `v3.0.0.b4` 发布于 2026-02-08。[LICENSE](https://github.com/Open-Source-Legal/OpenContracts/blob/main/LICENSE) [Repository metadata](https://api.github.com/repos/Open-Source-Legal/OpenContracts) [v3.0.0.b4](https://github.com/Open-Source-Legal/OpenContracts/releases/tag/v3.0.0.b4)

## 4.2 CUAD

### 定位与核心模型

CUAD 是法律合同审查数据集和 benchmark，不是 Agent Runtime。论文说明其任务是从合同中高亮需要人工审查的关键片段，包含 510 份商业合同、超过 13,000 条专家标注；仓库的类别定义文件包含 41 类审查问题。[CUAD paper](https://arxiv.org/abs/2103.06268) [Repository](https://github.com/The-Atticus-Project/cuad) [Category definitions](https://github.com/The-Atticus-Project/cuad/blob/main/category_descriptions.csv)

### 状态、工具、人工中断与可观测

不适用。仓库提供数据、训练与评估脚本，没有 Agent 状态机、工具调用、持久化或 HITL Runtime。[Repository](https://github.com/The-Atticus-Project/cuad)

### 优点

- 提供专家标注的合同风险类别和原文跨度，可用于构建 AtlasMind 审查覆盖矩阵。
- “找出需要人工审查的片段”与 AtlasMind 的引用驱动审查目标一致。[CUAD paper](https://arxiv.org/abs/2103.06268)

### 缺点

- 是英文商业合同数据，不能直接证明中文采购、技术服务合同上的效果。
- 只评估片段识别，不能覆盖知识库适用性、风险解释、履约证据或工具轨迹。
- 仓库根目录未声明可识别的 LICENSE，GitHub metadata 的 license 为空；在将数据并入产品训练或分发前必须单独核实授权。[Repository metadata](https://api.github.com/repos/The-Atticus-Project/cuad) [Repository files](https://github.com/The-Atticus-Project/cuad)

### AtlasMind 可复用与不建议照搬

可复用：41 类覆盖表、原文 span 标注格式、按类别计算 recall/F1 的评测方式。  
不照搬：直接使用其英文模型、把 41 类固定为中国合同完整风险体系、在许可未核实前分发数据。

### 活跃度

GitHub API 在调研时显示仓库未归档，最近推送为 2023-07-13，GitHub Releases 页面没有 release。[Repository metadata](https://api.github.com/repos/The-Atticus-Project/cuad) [Releases](https://github.com/The-Atticus-Project/cuad/releases)

## 4.3 LegalBench-RAG

### 定位与核心模型

LegalBench-RAG 是专门评估法律 RAG 检索步骤的 benchmark。它以 query 和精确字符区间 ground truth 表示相关片段，可确定性计算字符级 precision 和 recall。作者论文报告 6,858 个 query-answer pair、超过 7,900 万字符的语料，并提供较小的 mini 版本。[README](https://github.com/zeroentropy-ai/legalbenchrag#readme) [Paper](https://arxiv.org/abs/2408.10343)

### 状态、工具、人工中断与可观测

不适用。项目是数据生成和检索 benchmark 工具，不提供 Agent 编排或业务持久化。数据生成涉及 LLM，因此 README 明确说明重新生成不会与发布数据逐位相同；已发布 benchmark 则可用于确定性检索评测。[README](https://github.com/zeroentropy-ai/legalbenchrag#readme)

### 优点

- 评测最小相关片段而非只看文档 ID，直接对应 AtlasMind 的“引用是否精确”。
- 字符级 precision/recall 可阻止大量无关上下文通过“命中文档”掩盖低质量检索。
- 数据来源覆盖 ContractNLI、CUAD、MAUD 和 PrivacyQA，仓库保留生成脚本。[README](https://github.com/zeroentropy-ai/legalbenchrag#readme)

### 缺点

- 只评检索，不评最终法律判断、风险级别、知识范围授权和人工确认。
- 公开数据为英文法律语料，AtlasMind 必须建立中文合同内部 benchmark。

### AtlasMind 可复用与不建议照搬

可复用：`query + file_path + char_start + char_end` ground truth、字符级 precision/recall、mini 快速回归集。  
不照搬：把其公开分数直接当作 AtlasMind 中文合同准确率，或只优化检索而忽略结论/引用一致性。

### 许可证与活跃度

MIT License；GitHub API 在调研时显示未归档、最近推送为 2025-05-30；仓库没有 GitHub release。[LICENSE](https://github.com/zeroentropy-ai/legalbenchrag/blob/master/LICENSE) [Repository metadata](https://api.github.com/repos/zeroentropy-ai/legalbenchrag) [Releases](https://github.com/zeroentropy-ai/legalbenchrag/releases)

## 4.4 RAGFlow

### 定位与核心模型

RAGFlow 是文档 RAG 引擎和 Agent 工作流平台，支持深度文档解析、模板化切片、可视化人工干预、可追溯引用、多数据源、多路召回与融合重排。其 Agent Canvas 支持 Switch、Iteration、Loop、Categorize、工具组件和 Await Response。[README](https://github.com/infiniflow/ragflow#readme) [Flow control components](https://github.com/infiniflow/ragflow/blob/main/docs/guides/agent/agent_workflow/flow_control_components.md)

### 状态、工具、人工中断与可观测

Await Response 会暂停工作流，等待用户补充文本、选项、文件、数字或布尔确认；源码 Canvas 对 resume、组件路径、组件输入输出和 thoughts 有显式处理。Canvas 调试界面可查看各组件结果。[Flow control components](https://github.com/infiniflow/ragflow/blob/main/docs/guides/agent/agent_workflow/flow_control_components.md) [Canvas source](https://github.com/infiniflow/ragflow/blob/main/agent/canvas.py) [Save and Run](https://github.com/infiniflow/ragflow/blob/main/docs/guides/agent/understand_the_canvas/save_and_run.md)

### 优点

- 文档解析、切片可视化、引用和混合检索设计完整。
- Agent Canvas 已覆盖条件、循环、迭代、检索工具和用户补充材料。
- 官方 README 记录 MinerU、Docling、MCP、Agent workflow 和 memory 等能力。[README](https://github.com/infiniflow/ragflow#readme)

### 缺点

- 是完整平台，自托管要求包括 MySQL、Redis、MinIO、Elasticsearch 等组件，会与 AtlasMind 技术栈和产品层大量重叠。[README](https://github.com/infiniflow/ragflow#readme)
- 通用可视化工作流不能替代合同专用 Validator、规则引擎和人工最终确认。
- 直接嵌入整个平台的改造量远高于复用检索与 UI 思想。

### AtlasMind 可复用与不建议照搬

可复用：多路召回 + 融合重排、切片可视化、Await Response 的文件补证交互、节点 thoughts/输入输出详情。  
不照搬：整套平台、通用 Canvas 作为合同用户主界面、第二套知识库和会话系统。

### 许可证与活跃度

Apache-2.0 License；GitHub API 在调研时显示未归档、最近推送为 2026-08-04；最新 release `v0.26.4` 发布于 2026-07-07。[LICENSE](https://github.com/infiniflow/ragflow/blob/main/LICENSE) [Repository metadata](https://api.github.com/repos/infiniflow/ragflow) [v0.26.4](https://github.com/infiniflow/ragflow/releases/tag/v0.26.4)

## 5. 框架选型矩阵

以下评分是针对 AtlasMind 当前架构的工程适配度判断，不是项目的通用质量排名。5 表示高度适合，1 表示明显不适合。

| 候选 | 显式 DAG/FSM | 持久化/恢复 | 长等待 HITL | 工具与类型约束 | 可观测/评测 | 渐进接入 | 路线稳定性 | AtlasMind 结论 |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| LangGraph | 5 | 5 | 5 | 4 | 4 | 5 | 5 | **主编排框架** |
| PydanticAI/Graph | 4 | 3 | 4 | 5 | 5 | 4 | 5 | **校验与评测能力补充** |
| AutoGen | 2 | 3 | 2 | 4 | 4 | 2 | 1 | 不选；维护模式 |
| CrewAI | 4 | 4 | 4 | 4 | 3 | 3 | 4 | 借鉴 Flow，不采用 Crew 主运行时 |
| Semantic Kernel | 3 | 2 | 2 | 4 | 3 | 2 | 2 | 不选；Process experimental 且后继已明确 |

### 评分依据摘要

- LangGraph 的优势来自原生 StateGraph、checkpointer、interrupt/resume 和节点级测试。[Graph API](https://docs.langchain.com/oss/python/langgraph/graph-api) [Persistence](https://docs.langchain.com/oss/python/langgraph/persistence) [Interrupts](https://docs.langchain.com/oss/python/langgraph/interrupts)
- PydanticAI 在类型、工具审批、OTel 和 eval 上最强，但 durable execution 需要外部执行后端。[Durable Execution](https://ai.pydantic.dev/durable_execution/overview/) [Evals](https://ai.pydantic.dev/evals/)
- AutoGen 的维护模式是排除核心选型的决定性因素。[README](https://github.com/microsoft/autogen#readme)
- CrewAI Flow 能力完整，但 Crew 的高层多 Agent 语义不符合 AtlasMind 的受控法律判断目标。[Flows](https://docs.crewai.com/en/concepts/flows)
- Semantic Kernel Process 仍为 experimental，且官方方向转向 Microsoft Agent Framework。[Process Framework](https://learn.microsoft.com/en-us/semantic-kernel/frameworks/process/process-framework) [README](https://github.com/microsoft/semantic-kernel#readme)

## 6. 法律/文档项目复用矩阵

| 项目 | 最值得复用 | 不能解决的问题 | 采用方式 |
|---|---|---|---|
| OpenContracts | 精确 span、人工标注、引用关系、可插拔解析 | Agent DAG、履约状态机 | 复用数据模型思想，不引入整个平台 |
| CUAD | 合同风险类别、专家标注片段 | 中文适配、知识库、履约和工具轨迹 | 用于设计 AtlasMind Golden Dataset 分类体系 |
| LegalBench-RAG | 字符级检索 precision/recall | 最终判断和人工确认 | 直接复用评测方法，构建中文内部集 |
| RAGFlow | 混合召回、融合重排、切片可视化、补充材料 HITL | 合同业务门禁和最终责任 | 复用算法与交互思想，不替换现有平台 |

## 7. 对 AtlasMind 的目标架构建议

```text
Java API / Redis Stream Worker
             |
             v
       RuntimeRouter
       |      |      |
    legacy  graph  shadow
             |
             v
     LangGraph Contract Runtime
       |-- ContractReviewGraph
       |-- FulfillmentCheckGraph
       |-- VersionReviewGraph（后续）
       `-- ApprovalGraph（后续）
             |
    +--------+----------+----------------+
    |                   |                |
Existing Tool      Pydantic        Evaluation
Registry/Stores    Validators      Golden Dataset
    |                   |                |
MySQL / ES / Files / Knowledge Base / OTel
```

### 7.1 合同审查图

```text
freeze_context
  -> inventory_contract_dimensions
  -> parallel_retrieval(payment, acceptance, liability,
                        termination, confidentiality, IP, compliance)
  -> deterministic_rules
  -> draft_findings
  -> validate_citations
       -> [缺失] targeted_retrieval -> draft_findings -> validate_citations
       -> [通过] reflect_consistency
  -> quality_gate
       -> [未通过且预算可用] targeted_retrieval
       -> [未通过且预算耗尽] insufficient_evidence_report
       -> [通过] persist_report
```

### 7.2 履约核验图

```text
freeze_contract_role_and_evidence
  -> split_requirements
  -> match_evidence
  -> evaluate_each_item
  -> validate_contract_basis
  -> build_missing_evidence_list
  -> interrupt(manual_confirmation)
  -> resume
       -> CONFIRMED / PENDING / REQUEST_MORE_EVIDENCE
```

履约图必须保持 AtlasMind 已确认的业务边界：AI 只分析，不自动认定完成、失败、验收通过或不通过；最终结论由人工确认。LangGraph interrupt 只负责保存和恢复流程，人工结论仍写入业务表。[LangGraph Interrupts](https://docs.langchain.com/oss/python/langgraph/interrupts)

## 8. 准确率增强方案

### 8.1 建立四层质量门禁

1. **格式门禁**：Pydantic schema、枚举、长度、必填字段。
2. **引用门禁**：引用 ID 存在、原文跨度有效、合同版本/hash 一致。
3. **业务门禁**：HIGH 风险有合同依据；必需履约项来自合同；知识引用在授权范围内。
4. **语义门禁**：结论与引用一致、风险等级与影响一致、合同约定与 AI 建议明确分离。

### 8.2 建立三类评测集

| 评测集 | 样本 | 指标 |
|---|---|---|
| Retrieval Set | query + 精确原文区间 | 字符级 precision、recall、MRR、无关上下文率 |
| Review Set | 合同 + 人工风险发现 | 重大风险 recall、误报率、引用正确率、类别覆盖率 |
| Fulfillment Set | 节点要求 + 证据包 + 人工结论 | 必需项覆盖、证据匹配正确率、待定克制率、补证清单有效率 |

Retrieval Set 采用 LegalBench-RAG 的字符区间方法；Review Set 参考 CUAD 的类别覆盖，但必须由中文合同与内部法务标注重新建立。[LegalBench-RAG](https://github.com/zeroentropy-ai/legalbenchrag#readme) [CUAD paper](https://arxiv.org/abs/2103.06268)

### 8.3 检索改造

- 关键词 BM25 与向量召回同时执行；
- 对结果做 RRF 或加权融合；
- 再使用 reranker；
- 去重后按风险维度组织上下文；
- 每条最终结论只能引用实际进入判断上下文的片段；
- 保存检索 query、rank、score、chunk hash 和 rerank score。

RAGFlow 官方 README 明确列出 multiple recall 与 fused re-ranking，LegalBench-RAG 则提供评估精确片段召回的方法。[RAGFlow README](https://github.com/infiniflow/ragflow#readme) [LegalBench-RAG README](https://github.com/zeroentropy-ai/legalbenchrag#readme)

## 9. 渐进实施顺序

### Phase 0：评测基线

- 建立 30-50 份中文合同 Golden Dataset；
- 记录旧 Harness 的风险 recall、误报、引用正确率和轨迹；
- 增加 Pydantic 报告 schema 和引用 Validator；
- 不引入 LangGraph 生产流量。

### Phase 1：Graph Runtime 外壳

- 新增 `AgentRuntime`、`LegacyAdapter`、`GraphAdapter`、`ShadowAdapter`；
- 接入 LangGraph checkpointer；
- 建立 Graph node -> AtlasMind trace 的映射；
- `CONTRACT_REVIEW` 默认仍走 legacy。

### Phase 2：合同审查 Shadow Run

- 实现领域并行检索、引用校验和再反思循环；
- 同一证据快照运行 legacy 与 graph；
- 确定性字段逐位比较，LLM 文本只做语义/人工抽检；
- 达到门槛后小流量切换。

### Phase 3：履约核验与 HITL

- 实现要求拆分、证据匹配、缺口清单；
- 使用 interrupt/resume 等待人工确认；
- 新证据上传只标记“待重新核验”，不自动消耗模型费用；
- 验证等待、恢复、重复提交和幂等性。

### Phase 4：检索与持续评测

- 上线 BM25 + 向量 + RRF/rerank；
- 引入字符级检索评测；
- 将离线评测、线上抽样和 Agent 轨迹评测纳入发布门禁；
- 按 graph version、prompt version、model、scoring version 对比回归。

## 10. 最终决策

1. **采用 LangGraph，但只承担 Python Runtime 内部图编排。**
2. **保留 Redis Stream、MySQL、Elasticsearch、现有工具和前后端 API。**
3. **使用 Pydantic 做强类型与业务校验，评估引入 `pydantic-evals`，暂不整体迁移到 PydanticAI Runtime。**
4. **AutoGen、CrewAI、Semantic Kernel 不作为主运行时。**
5. **准确率建设优先级高于框架迁移：先有 Golden Dataset、引用门禁和混合检索，再以 Shadow Run 证明 LangGraph 版本确实更好。**
6. **从开源法律项目复用“评测与证据设计”，不直接复制其产品平台。**

这套选择的核心不是“用了 LangGraph”，而是让 AtlasMind 获得可验证、可恢复、可人工接管、可对照评测的合同 Agent 执行系统。

