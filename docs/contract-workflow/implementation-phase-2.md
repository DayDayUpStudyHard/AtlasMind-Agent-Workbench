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
