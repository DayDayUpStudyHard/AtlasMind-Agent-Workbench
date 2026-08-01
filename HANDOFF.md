# AtlasMind Agent Workbench Handoff

更新日期：2026-08-01

## 1. 项目定位

AtlasMind 当前不是单纯的聊天工具，也不是只会生成文档的 Prompt 应用。

当前产品方向是：**研发项目智能交付 Agent**

当前已经落地的主线场景有 3 个：

1. `HEALTH_ANALYSIS`：项目健康分析与交付计划
2. `PROJECT_ONBOARDING`：项目接手 / 入职助手
3. `ENGINEERING_DECISION`：研发决策助手

其中 MVP 主线仍然是 `HEALTH_ANALYSIS`，但底层执行框架已经升级为通用 Agent Harness，不再是简单的固定 Prompt 流程。

## 2. 当前已完成到什么程度

### 2.1 Agent 架构

后端已从“单次分析 + 文案生成”升级为：

`Planner -> Tool Calling -> Memory -> Reflection/Re-plan -> Artifact Executor`

关键实现位置：

- `agent-server/src/main/java/com/atlasmind/agent/runtime/DefaultAgentHarness.java`
- `agent-server/src/main/java/com/atlasmind/agent/runtime/AgentToolRegistry.java`
- `agent-server/src/main/java/com/atlasmind/agent/runtime/DeterministicHealthScoringEngine.java`
- `agent-server/src/main/java/com/atlasmind/agent/runtime/AgentTraceStore.java`

当前已具备的 Harness 能力：

- Planner 先制定有限计划
- 通过 DeepSeek 原生 Function Calling 选择工具
- 记录每次工具调用输入、输出、失败和耗时
- 支持 Reflection 检查证据覆盖与引用质量
- Reflection 不足时可触发 Re-plan
- 有执行预算，避免无限循环
- 工具失败时支持降级策略
- 运行结束后写入项目级 Episodic Memory

### 2.2 健康评分

健康分已经从 LLM 输出中剥离，改为后端确定性评分引擎。

当前原则是：

- `healthScore` 和各维度分数由后端规则计算
- LLM 只负责解释、风险总结、交付建议和结构化产物
- 报告中会记录 `scoringVersion`、`evidenceHash`、`analysisMode`

这一步已经解决了“同样仓库反复分析，分数随机漂移”的核心问题。

### 2.3 过程透明化

当前前后端都已经具备较强的运行可观测性。

已沉淀的运行观察包括：

- 计划内容
- 工具调用列表
- 观察结果
- Reflection 结论
- Re-plan 过程
- Agent 时间线
- 报告引用来源
- 运行记录删除联动清理

新增数据库表：

- `agent_tool_call`
- `agent_run_trace`

### 2.4 项目证据与知识

Agent Run 当前优先读取项目域内证据：

- GitHub 仓库元数据
- README
- 根目录关键配置文件
- Commit
- Issue
- PR
- 项目记忆
- 历史报告 / 运行结果

知识库不是单纯兜底，而是作为“公司规则 / 技术规范 / 技术栈文档”的补充输入源使用。

## 3. 代码结构

- `agent-server`
  Spring Boot 主后端，负责项目、运行、证据、报告、审批、Agent Harness。

- `agent-front`
  用户端工作台，面向技术负责人、项目负责人、研发管理者。

- `agent-admin`
  管理端控制台，面向管理员、AI 工程师、运维、知识管理员。

- `tools/chat-assistant/backend`
  Python FastAPI AI 服务，负责 Embedding、检索、LLM 相关能力。

- `prometheus`
  Prometheus 配置。

- `nginx`
  Nginx 反向代理构建文件。

## 4. 当前关键代码入口

如果接手人只看 6 个文件，建议先看这里：

1. `agent-server/src/main/java/com/atlasmind/service/impl/AgentProjectServiceImpl.java`
2. `agent-server/src/main/java/com/atlasmind/agent/runtime/DefaultAgentHarness.java`
3. `agent-server/src/main/java/com/atlasmind/agent/runtime/AgentToolRegistry.java`
4. `agent-server/src/main/java/com/atlasmind/agent/runtime/DeterministicHealthScoringEngine.java`
5. `agent-front/src/views/ProjectWorkbenchView.vue`
6. `agent-front/src/views/ProjectOverviewView.vue`

补充理解上下文时可看：

- `README.md`
- `CONTEXT.md`
- `Debug修复记录.md`

## 5. 运行方式

### 5.1 本地启动

根目录脚本：

- `start.bat`
- `start.sh`

`start.bat` 当前会拉起：

- Java backend：`http://localhost:18080`
- Admin app：`http://localhost:15173`
- Front app：`http://localhost:15174`
- Python AI service：`http://localhost:18088`

### 5.2 Docker 依赖

`docker-compose.yml` 里定义了这些依赖：

- MySQL
- Redis
- Elasticsearch
- Prometheus
- Grafana
- Nginx

当前最关键的基础依赖是：

- MySQL
- Redis
- Elasticsearch

本地开发常见模式是：

1. 用 Docker 起基础依赖
2. 用 `start.bat` 起 Java / 前端 / Python 服务

## 6. 当前验证状态

本次交接前重新验证过以下内容：

- `agent-server`：`.\mvnw.cmd test -q` 通过
- `agent-front`：`npm.cmd run build` 通过
- `tools/chat-assistant/backend`：`python -m py_compile app\services\llm_service.py app\api\routes.py` 通过

当前可直接访问确认的页面：

- 用户端首页：`http://localhost:15174` 返回 `200`

注意：

- `http://localhost:18080/` 根路径当前返回 `500`，这不一定代表主业务接口不可用，但说明后端没有提供友好的根路径健康页
- `http://localhost:18088/health` 当前返回 `404`，AI 服务暂未提供标准健康检查接口

## 7. 当前 MVP 的真实边界

这套系统已经能体现真正的 Agent 雏形，不再只是“问答工具”或“文档生成器”，因为它已经具备：

- 有界规划
- 工具调用
- 项目级记忆
- 反思与补充检索
- 结构化产物生成
- 审批闸门
- 运行轨迹可观测

但它还没有完全走到“研发智能交付 Agent”的终局，原因是下面几层还需要继续补：

- 更丰富的真实工具执行器
- 更严格的人审闸门
- 项目知识绑定配置
- 运行成本 / Token / 耗时统计
- 记忆确认与长期沉淀机制
- 更强的外部系统连接器

## 8. 当前最值得继续做的事

优先级建议如下。

### P0：把 Agent 能力继续做实

1. 增加更多真实工具，而不是只做分析
2. 为副作用工具加人工审批闸门
3. 区分只读工具和写入工具

建议优先补的工具：

- `createGithubIssue`
- `createGithubPullRequestDraft`
- `listCiFailures`
- `getBuildStatus`
- `inspectDependencyRisk`
- `generateTaskBreakdown`

### P1：把知识库做成项目可配置输入源

管理端应该支持：

- 上传知识文档
- 选择文档适用于哪些项目
- 选择文档属于哪类规则

建议知识类型至少拆为：

- 公司研发规范
- 技术栈最佳实践
- 项目私有文档
- 架构决策文档
- 运维 / 发布手册

### P1：补运行详情页

管理端建议增加 Run 详情页，完整展示：

- plan
- tool calls
- observations
- reflection
- re-plan
- artifact
- citations
- failure / fallback

这样管理员才能真正看懂 Agent 为什么得出这个结论。

### P1：验证评分稳定性闭环

建议对同一 GitHub 快照重复运行健康分析，确认：

- `evidenceHash` 不变
- `healthScore` 完全一致
- 只允许解释文本变化，不允许评分变化

### P2：把记忆体系做完整

现在已经有 Episodic Memory，但还建议继续补：

- unconfirmed / confirmed 区分
- 人工确认后提升为 durable memory
- 记忆来源可追溯
- 记忆过期与冲突策略

## 9. 已知问题 / 风险

1. 当前工作区是脏状态，存在未提交改动，接手前不要随意 reset。
2. 后端和 AI 服务缺少标准健康检查接口，不利于自动化巡检。
3. 部分根文档在终端输出里会出现编码观感问题，但文件本身并不一定损坏。
4. 真实副作用工具仍偏少，当前更强的是“分析 Agent”，还不是“执行 Agent”。
5. 项目知识库与项目绑定能力还需要继续加强，才能让知识真正进入具体项目决策链路。

## 10. 接手第一天建议

建议新接手人按这个顺序推进：

1. 读 `README.md`、`CONTEXT.md`、本文件
2. 起 MySQL / Redis / Elasticsearch
3. 运行 `start.bat`
4. 先打开用户端和管理端确认页面可用
5. 看一个真实项目的 Agent Run、Report、Action、Evidence
6. 从 `DefaultAgentHarness` 和 `AgentToolRegistry` 理解执行链路
7. 挑一个只读工具和一个副作用工具继续往下扩展

## 11. 一句话结论

项目已经从“能演示的 Agent UI”进入“有真实执行骨架的 Agent Workbench”阶段。

下一阶段不是继续堆 Prompt，而是把 **工具、审批、记忆、知识绑定、可观测性、执行器** 全部做实，逐步从“项目健康分析 Agent”走向“研发项目智能交付 Agent”。
