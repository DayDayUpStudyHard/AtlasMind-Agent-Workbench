# Python Agent Runtime Migration Plan

更新日期：2026-08-01

## 1. 背景

当前 AtlasMind 的 Agent 运行时分散在两处：

- Java 负责 Agent Run 生命周期、Harness 主循环、工具调用记录、Trace、报告持久化、审批衔接
- Python 负责 LLM 规划、Function Calling 选工具、Reflection、知识库与检索能力

这让 `agent-server` 同时承担了业务 CRUD、GitHub 同步、Agent Runtime 编排三类职责，导致：

- `AgentProjectServiceImpl` 过大，变更局部功能也需要理解整条运行链
- Java 与 Python 在 Agent 语义上“双脑协作”，接口复杂
- 新增工具、调整 Prompt、修改 Reflection/Fallback 时，改动跨语言扩散

本次迁移的目标，是把 Agent Runtime 收敛到 Python，形成单一 owner。

## 2. 目标与非目标

### 2.1 目标

1. Python 成为 Agent Runtime 的唯一执行 owner
2. Java 保留公共接口、鉴权、项目 CRUD、GitHub 同步、审批与外部副作用执行
3. 前后端现有公共接口保持不变
4. 运行可观测性不下降，反而更清晰
5. 支持无重启切换 `java / python / shadow`

### 2.2 非目标

1. 本阶段不引入 Redis Stream / Celery / 独立消息队列
2. 本阶段不改前端交互模型
3. 本阶段不重做知识库架构
4. 本阶段不新增大量外部副作用工具

## 3. 目标架构

```text
Front / Admin
  -> Java public API
      -> 权限、会话、审批、GitHub sync、公共查询
      -> Python internal runtime API
          -> Planner
          -> Tool Calling
          -> Memory
          -> Reflection / Re-plan
          -> Deterministic Scoring
          -> Trace / Tool Call / Report Persistence
          -> MySQL / Elasticsearch / LLM
```

核心决策：

- Java 不再参与 Harness 主循环
- Python 直接读写 Agent Runtime 相关表
- Java 只代理“启动 run”和“查询 run”
- 删除 `agent/runtime/` 不是第一步，而是最终 cutover 之后的清理动作

## 4. 职责边界

### 4.1 Java 保留职责

- `agent_project` 相关 CRUD
- `project_source` / `project_sync_job` / `project_evidence`
- GitHub 只读同步
- 管理端与用户端公共 API
- Sa-Token 鉴权与权限控制
- `agent_action` 的审批与最终执行
- 系统配置读取与运行时模式切换

### 4.2 Python 接管职责

- Agent Run 主循环
- Planner / Tool Calling / Reflection / Re-plan
- 确定性健康评分
- Tool 调用轨迹记录
- 运行时 Trace
- 报告草稿持久化
- Episodic Memory 写入
- 运行超时与僵尸 Run 恢复

### 4.3 表所有权

Java owner：

- `agent_project`
- `project_source`
- `project_sync_job`
- `project_evidence`
- `kb_*`
- `sys_setting`
- `agent_action` 的审批与执行更新

Python owner：

- `agent_run`
- `agent_run_step`
- `agent_run_trace`
- `agent_tool_call`
- `agent_report`
- `agent_project_memory`

共享规则：

- Python 可以创建 `agent_action` 草稿，状态必须是 `PENDING_APPROVAL`
- Java 是 `agent_action` 审批与执行状态的唯一 owner

## 5. 迁移范围

计划从 Java 迁出到 Python 的内容：

- `agent-server/src/main/java/com/atlasmind/agent/runtime/`
- `AgentProjectServiceImpl` 中与 Harness 主循环直接相关的逻辑
- `AgentRunExecutor` 的异步运行入口
- `AgentArtifactExecutor` 的产物持久化职责
- `AgentTraceStore` 的运行 Trace 和 Tool Call 写入逻辑

计划保留在 Java 的内容：

- `startRun()` 公共入口
- `getRun()`、`listRuns()`、`listReports()` 等公共查询
- `approveAction()` / `executeAction()`
- 项目、证据、GitHub 同步、管理端删除操作

## 6. Python Runtime 模块设计

建议新增目录：

```text
tools/chat-assistant/backend/app/agent_runtime/
  api_models.py
  runner.py
  policy.py
  stores/
    run_store.py
    trace_store.py
    evidence_store.py
    report_store.py
    memory_store.py
  scoring.py
  tools.py
  persistence.py
  recovery.py
  migrations.py
```

### 6.1 模块职责

- `api_models.py`
  Internal API 请求响应模型、Run 状态模型、Shadow 对比模型。

- `runner.py`
  Harness 主循环，编排 Planner、工具调用、Reflection、Re-plan、Artifact 持久化。

- `policy.py`
  执行预算、超时、最大回合数、最大工具调用数、重复调用拦截、失败兜底。

- `tools.py`
  运行时工具注册表与 7 个工具实现。

- `scoring.py`
  健康评分确定性引擎。

- `persistence.py`
  产物持久化与 `agent_action` 草稿创建。

- `recovery.py`
  心跳、超时扫描、僵尸 Run 处理、进程启动后恢复。

- `migrations.py`
  Python owner 表的 schema version 校验与升级。

### 6.2 Store 接口拆分

不要引入一个巨大的 `MySqlRuntimeRepository`。

建议拆为：

```python
class RunStore(ABC):
    create_run(...)
    update_run(...)
    get_run(...)
    heartbeat(...)
    find_timed_out_runs(...)
    find_stale_created_runs(...)

class TraceStore(ABC):
    append_trace(...)
    start_tool_call(...)
    complete_tool_call(...)
    fail_tool_call(...)

class EvidenceStore(ABC):
    search_evidence(...)
    search_knowledge(...)
    get_project_memory(...)
    get_recent_runs(...)
    get_latest_report(...)
    get_project_profile(...)

class ReportStore(ABC):
    save_report(...)
    get_report(...)
    get_latest_report(...)

class MemoryStore(ABC):
    save_memory(...)
```

这样每个接口都小、可单测、可替换。

## 7. 异步执行模型

### 7.1 本阶段选择

本阶段只做协程模式，不引入 Redis Stream。

启动模型：

1. Java 创建 Run 记录
2. Java 调用 Python `POST /internal/agent/run`
3. Python 收到后使用 `asyncio.create_task()` 启动后台执行
4. Python 负责心跳、超时、恢复、结束状态写回

### 7.2 为什么本阶段不上 Redis Stream

Redis Stream 不是简单配置项，它会引入完整的队列语义：

- Consumer Group 创建与治理
- PEL 积压清理
- ACK 时机定义
- worker 扩缩容与 rebalance
- 告警与死信策略

这应当作为后续独立迭代，而不是与 Runtime 迁移绑在同一阶段。

### 7.3 协程模式补足项

为了避免 `create_task()` 变成脆弱实现，`recovery.py` 必须负责：

- 定期写 `heartbeat_at`
- 标记运行开始时间
- 超时扫描
- 启动时扫描 `CREATED` / `RUNNING` / 中间态僵尸 Run
- 根据最后心跳与状态决定恢复、重试或失败终结

建议新增或复用字段：

- `heartbeat_at`
- `runtime_owner`
- `error_message`

如果不扩字段，至少要在 `agent_run_trace` 中保留恢复事件。

## 8. 运行时模式与回滚

### 8.1 配置来源

运行模式不使用环境变量切换，而使用数据库配置动态切换。

仓库已有：

- `sys_setting` 表
- `/api/admin/settings/runtime`

建议新增配置：

- `agent.runtime.mode = java | python | shadow`

### 8.2 模式定义

- `java`
  继续走当前 Java Runtime。

- `python`
  Java 只做代理，实际运行由 Python owner。

- `shadow`
  Java 继续产出正式结果，同时异步触发 Python Shadow Run 做对比，不影响前端主流程。

### 8.3 切换位置

Java 在 `startRun()` 每次执行时读取 `sys_setting`，而不是启动时缓存。

这样可以无重启回滚。

## 9. Internal API 契约

### 9.1 启动 Run

`POST /internal/agent/run`

请求建议：

```json
{
  "requestId": "uuid",
  "runId": 31,
  "projectId": 2,
  "taskType": "HEALTH_ANALYSIS",
  "question": "分析当前项目健康度与交付风险",
  "actor": {
    "userId": "u-1",
    "name": "admin"
  },
  "taskInput": {},
  "mode": "primary"
}
```

响应建议：

```json
{
  "ok": true,
  "runId": 31,
  "status": "CREATED",
  "accepted": true
}
```

说明：

- `requestId` 用于幂等
- `runId` 由 Java 先创建，Python 不再自行分配
- `mode` 允许 `primary` 或 `shadow`

### 9.2 查询 Run

`GET /internal/agent/run/{id}`

响应建议包含：

```json
{
  "run": {},
  "steps": [],
  "toolCalls": [],
  "traces": [],
  "report": {},
  "actions": [],
  "memories": []
}
```

### 9.3 鉴权

沿用现有内部调用方式：

- `X-Internal-Token`

并补充：

- 所有 internal agent 接口都必须校验 token
- 日志中带 `runId`、`requestId`

## 10. Java 容错语义

Java 调 Python 不是 fire-and-forget 成功即默认成立，必须定义失败语义。

推荐策略：

1. Java 先创建 `agent_run`
2. 初始状态为 `CREATED`
3. 调 Python `POST /internal/agent/run`
4. 如果 Python 返回成功，Java 正常返回 Run 概要
5. 如果 Python 调用失败，Java 立即将该 Run 标记为：
   - `status = FAILED`
   - `progress = 100`
   - `current_step = Python Agent Runtime 不可用`
   - `error_message = 具体异常`

明确不采用的策略：

- 不把失败请求保留为 `QUEUED`
- 不假设后续某个恢复器能捡起一次根本没成功投递的请求

## 11. Python Runtime 状态机

建议状态语义保持兼容当前前端认知：

```text
CREATED
-> CONTEXT_BUILDING
-> PLANNING
-> ANALYZING
-> VERIFYING
-> WAITING_APPROVAL
-> COMPLETED

失败分支：
任意中间态 -> FAILED
```

Shadow 模式可以额外通过 trace 标识，而不必新增前端状态。

恢复策略建议：

- `CREATED` 且超过短阈值未进入心跳：判定投递失败或 worker 异常，可终结为 `FAILED`
- 中间态超过执行超时：终结为 `FAILED`
- `WAITING_APPROVAL` 不参与恢复

## 12. Shadow Run 对比矩阵

没有明确矩阵，Shadow Run 会变成噪音源。

建议如下：

| 字段 | 对比方式 | 通过标准 |
| --- | --- | --- |
| `healthScore` | 逐位 | 必须完全一致 |
| `evidenceHash` | 逐位 | 必须完全一致 |
| `healthStatus` | 逐位 | 必须一致 |
| `dimensions[].score` | 逐位 | 必须一致 |
| `citations` | 集合 | 相同 `sourceType:sourceId` |
| `toolCalls` | 集合 | 相同工具名称集合，顺序允许不同 |
| `reflection.adequate` | 逐位 | 必须一致 |
| `risks[].title` | 语义 | 允许表述差异 |
| `plan[].title` | 语义 | 允许表述差异 |
| `reportMarkdown` | 不对比 | 不作为验收项 |

Shadow 失败判定建议：

- 任一确定性字段不一致：记为失败
- 仅 LLM 文案差异：记为通过

## 13. Migration Ownership

Python 既然拥有 runtime 表，就应拥有其 migration 执行权。

建议：

1. Python 启动时检查 schema version
2. 通过 `schema_migrations` 或等价版本表执行增量 migration
3. Java 只读这些表，不负责初始化或升级

要求：

- migration 必须可重复执行
- migration 有明确版本号
- migration 失败时 Python 启动应失败并报清楚错误

不建议：

- Java 和 Python 双方都可能执行同一批 runtime DDL
- 在生产环境中靠隐式 schema drift“碰巧能跑”

## 14. 删除与审批语义

删除 Run、Report、Action 的公共入口仍由 Java 暴露。

原因：

- 前端当前已经绑定 Java 公共 API
- 管理端权限、审计、操作日志都在 Java

但底层删除逻辑需要按 ownership 区分：

- Java 删除 `agent_action` 审批对象
- Java 可调用 Python 删除 runtime 产物，或直接按共享 schema 规则清理

建议本阶段保持现状：

- 删除入口仍在 Java
- Java 继续负责 Run/Report/Action 删除联动

这样可以减少迁移面。

## 15. 分阶段迁移步骤

### Phase 0：准备

1. 定义 Internal API 请求响应模型
2. 在 `sys_setting` 中新增 `agent.runtime.mode`
3. 设计 Python runtime migration 版本表
4. 固化 Shadow Run 对比矩阵

### Phase 1：Python Runtime 骨架

1. 新建 `agent_runtime/`
2. 实现 5 个 store 接口
3. 实现 `runner.py`
4. 实现 `policy.py`
5. 实现 `recovery.py`
6. 实现 `/internal/agent/run` 和 `/internal/agent/run/{id}`

### Phase 2：功能搬迁

1. 搬迁 Harness 主循环
2. 搬迁确定性评分
3. 搬迁 Trace / Tool Call 记录
4. 搬迁报告持久化
5. 搬迁 Episodic Memory 写入

### Phase 3：Java 接入

1. `startRun()` 读取 `agent.runtime.mode`
2. `python` 模式下调用 `/internal/agent/run`
3. 补齐 Python 不可用时的 `FAILED` 语义
4. `getRun()` 继续走现有表查询

### Phase 4：Shadow 验证

1. 以 `shadow` 模式运行对照实验
2. 验证确定性字段完全一致
3. 记录 diff 报告
4. 修复不一致项

### Phase 5：切主

1. 将 `agent.runtime.mode` 切到 `python`
2. 观察一段时间运行质量
3. 确认审批、删除、报告、运行轨迹全部正常

### Phase 6：清理 Java Runtime

1. 删除 `agent/runtime/`
2. 删除 Java Harness 执行逻辑
3. 保留 Java 公共 API 与审批执行逻辑
4. 清理不再使用的 Gateway 方法与注入项

## 16. 验收标准

迁移完成至少满足：

1. 前端无需改接口即可正常启动 Run、查看 Run、查看报告、审批动作
2. `python` 模式下：
   - 能成功跑 3 类任务
   - Tool Call、Trace、Reflection、Report 均完整可见
3. `shadow` 模式下：
   - 确定性字段完全一致
4. Python 进程重启后：
   - 僵尸 Run 可被识别并正确终结或恢复
5. Java 调 Python 失败时：
   - 不残留大量 `CREATED` / 假 `QUEUED`
6. 管理端删除 Run/Report/Action 不回归
7. 运行模式可在数据库中切换，无需重启

## 17. 主要风险

1. Python 直接持久化后，如果没有接口拆分，可能复制出新的“大型 God object”
2. `asyncio.create_task()` 若无恢复机制，会造成隐性任务丢失
3. Shadow Run 如果没有固定对比矩阵，会制造大量无效 diff
4. Python 与 Java 若同时持有 runtime DDL 控制权，会出现 schema ownership 混乱
5. Java 若不定义明确失败语义，会堆积伪待处理 Run

## 18. 结论

这次迁移不是“把 Java 代码搬去 Python”，而是把 Agent Runtime 变成一个真正单 owner 的深模块。

推荐最终方案是：

- 本阶段只做协程模式
- Python 拥有 runtime 表与 migration
- Java 保留公共接口、权限、审批、GitHub sync
- 运行模式通过 `sys_setting` 动态切换
- Shadow Run 用固定矩阵验收
- 删除 Java Runtime 放在最终 cutover 之后

按这个方案推进，迁移收益会是清晰的：

- Agent 逻辑集中
- Java 职责收敛
- Prompt / Tools / Reflection 演进更快
- 运行轨迹和失败语义更容易收敛
