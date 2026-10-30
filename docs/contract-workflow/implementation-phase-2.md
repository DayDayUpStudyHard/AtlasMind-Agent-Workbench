# 二期实施记录

> 分支：`feat/phase-2-flow`（第一步起所有步骤同分支）
> 上游设计：[phase-2-approval.md](./phase-2-approval.md) / [phase-2-design.md](./phase-2-design.md) / [phase-2-frontend.md](./phase-2-frontend.md)

---

## 第 1 步：表结构与种子（已完成）

| 交付 | 路径 |
| --- | --- |
| 迁移脚本（6 张流程表 + 2 张审批人表） | `tools/chat-assistant/backend/migrations/V041__contract_flow.sql` |
| Java 启动期镜像 DDL | `agent-server/.../config/AgentWorkbenchSchemaInitializer.java` |
| 种子脚本（开关 / 审批人 / 法务） | `agent-server/sql/contract_flow_seed.sql` |

验证：MySQL 8.0.42 实测唯一约束、事件去重、种子幂等；`mvn compile` 通过。

---

## 第 2.5 步：design v0.4 决策 13~17 落地（已完成）

| 决策 | 改动 |
| --- | --- |
| 13 节点状态 | 新增 `WAITING`；建链只有 `start_node` 是 `PENDING`；`advanceAfter` 把下一个 `WAITING`（或打回后的 `VOID`）翻成 `PENDING`；`currentActiveNode` 去掉最小 seq 兜底，出现多个活跃节点直接抛异常 |
| 14 候选组 | 删除 `deptCandidates` / `legalCandidates` 的 `adminIds()` 回落，为空即 `NO_APPROVER`；新增 `forceClaim`（`POST /nodes/{id}/claim?force=true`，仅 ADMIN），写 `ADMIN_OVERRIDE` |
| 15 事件挂载 | `contract_flow_event.node_id` 改 `NOT NULL`；`FLOW_START` 挂 `start_node`，`WITHDRAW_*` / `CANCEL` 挂当前活跃节点；`addEventRaw` 对空 `node_id` 直接抛异常 |
| 16 撤回起点 | 维持以 `target_node` 为准（原实现已如此，v0.4 确认） |
| 17 第 3 步范围 | 记录到 design §3.1，实现待第 3 步 |

`pending_rerun` 列（§1.2）第 1 步已建好，本次仅补文档。

**对已有库的收紧**：`AgentWorkbenchSchemaInitializer.tightenEventNodeIdToNotNull()`
在 `node_id` 仍可空时执行一次 `ALTER ... NOT NULL`；若存在 NULL 行则抛异常，
不静默删除审计数据。

测试：`ContractFlowServiceTest` 36 个用例通过；后端全量 107 个测试、0 失败。

> 沿用决策：`uploaderCandidates` 仍保留 ADMIN 兜底（历史案件 creator/maintainer 可能为空），
> 决策 14 只针对"部门审批 / 法务"两类节点。

### 2.5.1 design v0.5 追加（已完成）

| 决策 | 改动 |
| --- | --- |
| 14（收窄） | UPLOADER / SIGNING 允许 ADMIN 回落，但 `submit` 走回落时写 `ADMIN_OVERRIDE`，`payload.reason=CANDIDATE_FALLBACK`；审批节点仍禁止回落 |
| 18 新轮建链 | `createFlow` 只从 `start_node` 起建节点，前置节点不再在新轮伪造 `DONE`（否则 `done_at` 造假或为空）；`seq` 沿用 `NODE_CHAIN` 原始下标 |
| 19 游标 | `(created_at, id)` 联合游标，第 3 步实现 timeline 时落地 |

测试：`ContractFlowServiceTest` 38 个用例通过；后端全量 109 个测试、0 失败。

---

## 第 2 步：实体 / Mapper / 流程核心服务（已完成）

### 2.1 交付文件

| 文件 | 说明 |
| --- | --- |
| `entity/ContractFlow.java` 等 8 个实体 | `contract_flow*`、`contract_sign_check`、`dept_approver`、`flow_role_member` |
| `mapper/ContractFlowMapper.java` 等 8 个 Mapper | MyBatis-Plus `BaseMapper` |
| `service/ContractFlowConstants.java` | 节点/状态/事件/角色枚举真源 |
| `service/ContractFlowException.java` | 稳定原因码 + HTTP 状态 |
| `service/ContractFlowService.java` | 流程核心服务 |
| `test/.../FlowTestDatabase.java` | 真 MySQL 测试基座（Testcontainers 或本地库） |
| `test/.../ContractFlowServiceTest.java` | 32 个集成测试 |

### 2.2 已实现的流程动作

| 方法 | 设计依据 |
| --- | --- |
| `startFlow` | §1.1、§2.10 #7（撤回关闭的轮次不算"同版本不能重开"） |
| `submit` | §3.3 强制确认 + 候选组非空（决策 #6） |
| `claim` / `release` | §2.11 乐观锁；决策 #7 放回 |
| `approve` | §2.5 推进链 + §2.10 #1 |
| `returnTo` | §2.5 任意前序节点、中间节点 VOID、§2.10 #2 |
| `requestWithdraw` / `decideWithdraw` | §2.6 开新轮；§2.10 #4/#5/#8 |
| `cancel` / `cancelEligibility` | §2.4 6 小时 + agent 失败 |
| `onAgentFinished` / `requestAgentRerun` | §2.9 Java 轮询契约 + 合并重跑 |
| `current` / `candidates` | 派生查询 |

### 2.3 硬约束落地

| 约束 | 实现 |
| --- | --- |
| 动作与事件同事务 | 每个动作包在 `TransactionTemplate` 内，异常整体回滚 |
| 不吞异常 | 无 `catch (ignored)`；唯一 `catch` 是 `DuplicateKeyException` 的幂等分支 |
| 认领乐观锁 | 条件 `UPDATE ... WHERE state='PENDING' AND assignee_id IS NULL`，0 行→409 |
| 审批类动作行锁 | 先 `SELECT ... FOR UPDATE` 再校验 |
| 事件唯一性 | `ref_id` 非空事件幂等；空 `ref_id` 事件（EDIT/RETURN/CONFIRM）必须写入 |

### 2.4 测试说明

Testcontainers 在无 Docker 环境自动跳过；本仓库当前开发机无 Docker，故用本地 MySQL 真库执行：

```bash
# 准备空库
mysql -uroot -p -e "CREATE DATABASE flow_test DEFAULT CHARACTER SET utf8mb4"
# 指定本地库运行（Testcontainers 仍为 CI 默认路径）
FLOW_TEST_JDBC_URL="jdbc:mysql://localhost:3306/flow_test?useUnicode=true&characterEncoding=utf-8&serverTimezone=Asia/Shanghai" \
FLOW_TEST_JDBC_USER=root FLOW_TEST_JDBC_PASSWORD=123456 \
./mvnw test -Dtest=ContractFlowServiceTest
```

测试直接执行线上迁移 `V041__contract_flow.sql`，不使用 H2 替身。

### 2.5 结果

- `ContractFlowServiceTest`：32 / 32 通过
- 全量后端：103 个测试，0 失败、0 错误、0 跳过

### 2.6 已知边界

1. 签署节点完成 / `COMPLETE` 由第 4 步的签署件核对收口，本步不伪造完成。
2. 通知（`flow_notification`）与两个配置页 API 属第 5 步。
3. Java 轮询器本身（定时扫 `AGENT` 节点）在第 3 步接查询接口时一并接入；本步只提供 `onAgentFinished` 契约。

---

## 第 3 步：时间轴 / 内容类动作 / 查询接口（已完成）

### 3.1 交付文件

| 文件 | 内容 |
| --- | --- |
| `service/FlowTimelineService.java` | 里程碑派生 + 跨轮次事件游标查询 |
| `service/ContractFlowService.java` | 新增 `confirmElements` / `confirmTimeline` / `editContent` / `switchVersion` / `current` |
| `controller/ContractFlowController.java` | `/api/flows/cases/{caseId}/current\|timeline\|confirm-elements\|confirm-timeline\|edit\|version` |
| `common/GlobalExceptionHandler.java` | `ContractFlowException` → `Result.fail(status, reason)` |
| `test/.../FlowTimelineServiceTest.java` | 9 个用例 |
| `test/.../ContractFlowServiceTest.java` | 新增 11 个内容类动作用例 |

### 3.2 设计决策落地

| 点 | 实现 |
| --- | --- |
| 里程碑 ①~⑥ | 由事件流派生；无事件时全部 INACTIVE |
| ② 解析完成 | 流程开启即 DONE（上传动作隐含解析完成） |
| ⑤ 边界 | `AGENT_RUN`→ACTIVE；`ENTER(DEPT/LEGAL)`→WAITING_HUMAN；`APPROVE(LEGAL)`→DONE |
| ⑥ 签署 | `SIGN_UPLOAD`→ACTIVE；`COMPLETE`→DONE；⑦⑧ 恒 INACTIVE（第 4 步 / 第三期） |
| 分页 | `(created_at, id)` 联合游标，`limit` 上限 100，越界游标返回 400 |
| 跨轮次 | 查询案件全部轮次，事件带 `roundNo`，默认新轮在前 |
| 确认幂等 | 失效水位（`AGENT_RERUN` / `EDIT` 最大 id）之后只写一条 |
| 实质字段 | `SUBSTANTIVE_FIELDS` 变更才 `pending_rerun=1` + `AGENT_RERUN` |
| 审批期修改 | 返回 `NEED_WITHDRAW`，不直接改基线 |

### 3.3 测试结果

- `FlowTimelineServiceTest`：9 / 9 通过
- `ContractFlowServiceTest`：49 / 49 通过（新增 11 个）
- 全量后端：129 个测试，0 失败、0 错误、0 跳过

### 3.4 已知边界

1. 签署件核对（`contract_sign_check`、`SIGN_*` 事件）属第 4 步。
2. 剩余写接口（claim/release/approve/return/withdraw/cancel/agent-rerun）随第 5 步一起暴露。
3. `version` 只更新 `flow.version_id` 并记事件，文件落盘仍由既有 document 上传接口负责。
