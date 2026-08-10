# AtlasMind 合同文件权限、额度结算与协作流程 PRD

> 文档版本：v1.0  
> 日期：2026-08-09  
> 产品：AtlasMind Agent Workbench / ContractOps  
> 文档状态：待评审  
> 优先级：P0（上线前）

## 1. 背景与目标

当前系统已经具备合同案件、文档上传、Agent Run、合同审查和基础访问策略。本阶段解决三个会直接影响真实业务上线的问题：

1. 合同文件必须和合同权限保持一致，不能通过静态 URL 绕过鉴权。
2. Agent Run 消耗的额度必须可预占、确认、释放、对账，不能因为异常运行永久占用。
3. 合同必须支持负责人、协作者、审阅人和可追踪的人工协作，而不是只能由单个用户操作。

### 1.1 成功标准

- 任意文件下载都能追溯到用户、合同、文件版本和授权判断。
- 额度账面满足：`allocated = used + available + reserved`。
- Agent Run 无论成功、失败、取消、超时、重放，最终都只有一个确定的额度结果。
- 合同可由多人按明确角色协作，任何修改都有版本和审计记录。
- 跨部门用户无法通过 ID、文件 URL、下载接口、SSE 或导出接口越权读取数据。

### 1.2 非目标

- 本阶段不做复杂 RBAC 权限编辑器。
- 不做多人实时光标/实时协同编辑。
- 不做在线 Word/PDF 编辑器。
- 不改变现有 Python Agent Runtime 的核心推理逻辑。
- 不批量改变历史合同归属；历史数据由管理员确认。

## 2. 现有对象与新增概念

沿用现有对象：

- `t_user`：系统用户、系统角色 `ADMIN | USER`
- `department`：部门
- `contract_case`：合同案件，创建时快照 `department_id`
- `contract_document`：合同原始文档及版本
- `agent_run`：一次 Agent 执行
- `contract_review_finding`：审查发现
- `contract_obligation`：合同义务
- `contract_timeline_node`：时间节点
- `quota_transaction`：额度流水
- `ContractAccessPolicy`：合同统一访问入口

新增概念：

- **文件对象**：实际存储对象，不能直接暴露物理路径。
- **文件版本**：沿用 `contract_document.version`，同一合同的业务文档版本不可变。
- **合同成员**：合同级协作关系，不等同于系统角色。
- **额度预占**：Agent Run 创建时临时锁定额度。
- **额度结算**：Run 进入终态后确认扣除或释放预占。
- **幂等键**：防止重复创建 Run、重复回调、重复结算。

### 2.1 兼容性原则

本 PRD 是对现有 ContractOps 的增量增强，不重建三套核心模型：

1. `contract_case.status` 沿用当前状态枚举，新增状态必须先做 DDL 和前后端映射。
2. `contract_document` 继续作为合同文件、版本和解析状态的业务主表；私有文件对象只补存储安全元数据。
3. `user_quota` 和 `quota_transaction` 继续作为额度账本；只有在需要表达更复杂结算状态时，才引入 `quota_reservation`。
4. Python Agent Runtime 的 `WAITING_HUMAN` 是合法非终态，不能被对账任务当作失败或超时自动退款。

## 3. 权限模型

### 3.1 合同级协作角色

| 角色 | 查看合同 | 下载文件 | 上传文件 | 修改业务字段 | 发起 Run | 审阅/确认 | 管理成员 |
|---|---:|---:|---:|---:|---:|---:|---:|
| `OWNER` | 是 | 是 | 是 | 是 | 是 | 是 | 是 |
| `EDITOR` | 是 | 是 | 是 | 是 | 是 | 是 | 否 |
| `REVIEWER` | 是 | 是 | 否 | 否 | 否 | 是 | 否 |
| `VIEWER` | 是 | 是 | 否 | 否 | 否 | 否 | 否 |
| `ADMIN` | 全局 | 全局 | 全局 | 全局 | 代操作需记录真实发起人 | 全局 | 全局 |

系统角色 `ADMIN | USER` 仍然保留。`ADMIN` 是全局越权能力，合同成员角色是普通用户在单个合同内的业务授权。

合同成员上线前后需要兼容现有 `visibility` 规则：

- 新合同：创建人自动成为 `OWNER`，`contract_case.owner_id` 和 `creator_id` 同步写入。
- 历史合同：没有 `contract_member` 记录时，继续按 `visibility`、`department_id`、`contract_department_visibility` 判断。
- 成员表上线后，`ContractAccessPolicy` 的判断顺序为 `ADMIN -> contract_member -> visibility fallback`。
- `LEGACY_REVIEW` 仍是过渡态，不能因为成员表上线而批量失效历史可见性。

### 3.2 授权原则

1. 所有合同子资源先定位 `case_id`，再调用 `ContractAccessPolicy`。
2. 只要合同不存在、已删除或用户无权访问，统一返回 `404`，避免泄露资源存在性。
3. `ADMIN` 的代操作必须同时记录 `operator_id` 和 `acting_for_user_id`。
4. 权限变更只影响后续请求，不自动篡改历史审计和已生成报告。
5. 文件权限不能高于合同权限；成员被移除后，旧下载链接立即失效。

## 4. 模块一：文件权限闭环

### 4.1 业务流程

```text
创建上传会话
  -> 上传分片/文件
  -> 校验大小、类型、checksum
  -> 病毒扫描/解析
  -> 生成不可变文件版本
  -> 绑定 contract_case
  -> 按 ContractAccessPolicy 下载/预览
  -> 新版本替换（旧版本只读）
  -> 归档或删除（软删 + 延迟清理）
```

### 4.2 文件状态

`INITIATED -> UPLOADING -> UPLOADED -> SCANNING -> AVAILABLE`

异常状态：

- `FAILED`：上传失败、checksum 不匹配或解析失败
- `QUARANTINED`：病毒/恶意内容
- `DELETED`：业务软删，不允许新下载

只有 `AVAILABLE` 文件允许预览、下载和作为 Agent 输入。

### 4.3 数据表

#### `contract_document` 增量字段

| 字段 | 类型 | 说明 |
|---|---|---|
| `storage_key` | VARCHAR(512) | 私有存储 key，不返回物理路径 |
| `content_type` | VARCHAR(120) | MIME |
| `storage_status` | VARCHAR(24) | `INITIATED/UPLOADING/UPLOADED/AVAILABLE/FAILED/QUARANTINED/DELETED` |
| `scan_status` | VARCHAR(24) | `PENDING/PASSED/BLOCKED/SKIPPED` |
| `download_count` | BIGINT | 下载次数 |
| `last_download_at` | DATETIME | 最近下载时间 |

说明：

- `contract_document.file_path` 暂时保留，用于兼容现有解析链路和历史数据。
- 新上传不再把 `file_path` 当作公开 URL，只保存内部兼容路径或空值。
- Python 解析服务读取文件时应使用内部挂载路径或服务端授权的文件解析接口，不依赖公网 `/upload/**`。
- `contract_document.version` 继续作为业务版本号，避免再新增一套 `version_no`。

约束：

- 保留现有 `UNIQUE(case_id, version)`，如后续支持多条主文档线，再升级为 `UNIQUE(case_id, document_type, version)`。
- `storage_key` 唯一。
- 禁止客户端传入 `storage_key`、`upload_by`、`case_id` 覆盖服务端值。

#### `private_upload`

现有兼容表继续保留，用于非合同文件和历史 `/upload/**` 路径的鉴权兜底。合同文件一旦能通过 `contract_document` 定位 `case_id`，必须走 `ContractAccessPolicy`，不能只按上传人判断。

#### `file_access_log`

记录 `file_id、case_id、user_id、action、decision、ip、user_agent、request_id、create_time`。

### 4.4 接口

| 方法 | 接口 | 权限 | 说明 |
|---|---|---|---|
| `POST` | `/api/workspace/contracts/{caseId}/files/upload-init` | `OWNER/EDITOR` | 创建上传会话 |
| `PUT` | `/api/files/upload-sessions/{sessionId}/parts/{partNo}` | 上传会话持有人 | 上传分片 |
| `POST` | `/api/files/upload-sessions/{sessionId}/complete` | 上传会话持有人 | 合并并校验 checksum |
| `GET` | `/api/workspace/contracts/{caseId}/files` | 合同可见 | 文件版本列表 |
| `GET` | `/api/files/{fileId}/download` | 合同可见 | 服务端鉴权后流式下载 |
| `GET` | `/api/files/{fileId}/preview` | 合同可见 | 预览，返回短时 token 或流 |
| `POST` | `/api/workspace/contracts/{caseId}/files/{fileId}/new-version` | `OWNER/EDITOR` | 创建新版本 |
| `DELETE` | `/api/workspace/contracts/{caseId}/files/{fileId}` | `OWNER/EDITOR/ADMIN` | 软删 |

下载接口要求：

- 不允许 `redirect` 到公开 URL。
- 默认 `Content-Disposition: attachment`，文件名使用服务端安全编码。
- 限制单用户并发下载数和单文件最大传输速率。
- 每次下载记录允许/拒绝结果。
- 若使用对象存储，使用短时、单对象、不可复用签名 URL，签名生成前必须完成权限校验。

### 4.5 文件安全规则

- 白名单扩展名和真实 MIME 双重校验。
- 单文件大小、单合同总容量、单用户日上传量均可配置。
- 压缩包禁止目录穿越；解压文件必须放在隔离目录。
- 文件名过滤控制字符、路径分隔符和双扩展名。
- 原始文件和解析产物分离存储。
- `QUARANTINED` 文件不可下载、不可进入 Agent Run。
- 文件删除采用软删；物理清理由延迟任务执行，并保留恢复窗口。

### 4.6 验收标准

- 无权限用户通过文件 ID、旧 URL、预览接口、下载接口均得到 `404`。
- 移除合同成员后，原 access token 不能下载新文件。
- 同一文件重复上传可按 checksum 去重，不产生错误重复版本。
- 断点续传、重复 complete、网络重试均不产生重复文件对象。
- 文件下载日志能关联到合同和用户。

## 5. 模块二：额度完整结算

### 5.1 额度定义

每个用户拥有：

- `total_quota`：管理员分配总额度
- `used_count`：已确认消耗
- `reserved_count`：运行中预占
- `available = total_quota - used_count - reserved_count`

严禁出现负数或 `used_count + reserved_count > total_quota`。

### 5.2 Run 与额度状态

额度预占状态：

`RESERVED -> CONFIRMED`

异常终态：

- `REFUNDED`：失败、取消、超时且未产生可计费结果
- `PARTIAL_SETTLED`：已产生部分结果，按明确计费规则结算
- `EXPIRED`：预占超时，由对账任务释放

Agent Run 终态必须是：

`COMPLETED | FAILED | CANCELLED`

`WAITING_HUMAN` 和 `WAITING_APPROVAL` 是合法非终态，不允许自动结算。`TIMEOUT` 当前代码未定义，若要上线超时终态，必须同步补齐 Python Runtime、Java 后台、前端状态映射和额度退款规则。

每个 Run 只能有一条有效结算记录。

### 5.3 数据表

#### 沿用 `user_quota`

当前已有字段：`user_id、total_quota、used_count、reserved_count`。本阶段不重命名，前端可显示为“总额度、已用、预占、可用”。

#### 沿用 `quota_transaction`

当前已有字段：`user_id、amount、type、balance_after、run_id、operator_id、remark、idempotency_key`。

必须保证：

- `RESERVE`：`reserved_count + units`
- `CONFIRM`：`reserved_count - units`，`used_count + units`
- `REFUND`：`reserved_count - units`
- 同一 `run_id` 只能出现一条 `RESERVE`
- 同一 `run_id` 只能出现一条结算流水：`CONFIRM` 或 `REFUND`
- `idempotency_key` 全局唯一

#### `quota_reservation`（P1 可选）

只有当一期整数额度不能满足“部分结算、阶梯计费、复杂超时 SLA”时才新增独立表：

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | BIGINT | 主键 |
| `user_id` | BIGINT | 额度所属用户 |
| `run_id` | BIGINT | Agent Run |
| `idempotency_key` | VARCHAR(128) | 幂等键 |
| `units_reserved` | INT | 预占单位 |
| `units_final` | INT | 最终扣除单位 |
| `status` | VARCHAR(24) | 预占/结算状态 |
| `reserved_at` | DATETIME | 预占时间 |
| `settled_at` | DATETIME | 结算时间 |
| `reason` | VARCHAR(255) | 结算原因 |

约束：

- `UNIQUE(user_id, idempotency_key)`
- `UNIQUE(run_id)`
- `INDEX(status, reserved_at)`

### 5.4 结算规则

默认规则：

| Run 结果 | 额度处理 |
|---|---|
| 创建失败，未进入队列 | 立即 `REFUNDED` |
| 排队期间取消 | `REFUNDED` |
| Agent 启动后失败 | 默认 `REFUNDED`，保留系统日志 |
| 正常完成 | `CONFIRMED`，扣除实际单位 |
| `WAITING_HUMAN` | 不结算，等待人工恢复或取消 |
| 超时但已生成报告 | 当前不实现；若引入 `TIMEOUT`，由产品配置决定 `PARTIAL_SETTLED` 或 `REFUNDED` |
| 重复请求 | 返回原 Run 和原结算结果，不重复扣费 |

一期只支持整数单位。计费策略通过 `run_type -> unit_cost` 配置，禁止前端传入扣费数量。

### 5.5 接口

| 方法 | 接口 | 说明 |
|---|---|---|
| `GET` | `/api/quota/me` | 当前额度汇总 |
| `GET` | `/api/quota/transactions` | 当前用户流水 |
| `POST` | `/api/workspace/contracts/{caseId}/runs` | 创建 Run 并预占额度 |
| `POST` | `/api/runs/{runId}/cancel` | 取消运行 |
| `GET` | `/api/runs/{runId}/quota` | 查看该 Run 额度状态 |
| `GET` | `/api/admin/quota/reconciliation` | 管理端对账 |
| `POST` | `/api/admin/quota/{userId}/adjust` | 管理员调整额度 |

创建 Run 必须在同一事务内完成：

1. 校验合同访问权限。
2. 校验请求幂等键。
3. `SELECT ... FOR UPDATE` 锁定用户额度。
4. 校验可用额度。
5. 插入 `agent_run`。
6. 插入 `RESERVE` 流水；如启用 `quota_reservation`，同步插入预占记录。
7. 提交后再投递异步任务。

### 5.6 对账任务

每 5 分钟执行：

- 找出 `RESERVED` 且超过 TTL 的预占。
- 查询对应 Run 状态。
- 终态 Run 执行确认/退款。
- 无对应 Run 的预占标记异常并退款。
- 对 `used/reserved` 与流水聚合结果进行核对。
- 异常记录告警，不静默修正。

对账必须幂等、可重复执行、支持管理员手动重试。

### 5.7 验收标准

- 并发创建 Run 时不会超卖额度。
- 同一 `idempotency_key` 重试不会多创建 Run 或多扣额度。
- 成功、失败、取消、超时四条路径均有自动化测试。
- 对账后不存在长期 `RESERVED`。
- 管理员不能把 `used_count + reserved_count` 调整到超过 `total_quota`。

## 6. 模块三：合同协作流程

### 6.1 合同生命周期

一期状态：

沿用当前前后端已有状态：

`DRAFT -> INTAKE_PARSING -> INTAKE_CONFIRMING -> READY_FOR_REVIEW -> REVIEWING -> NEEDS_REVISION -> PENDING_APPROVAL -> APPROVED -> READY_TO_SIGN -> SIGNED -> IN_FULFILLMENT -> EXPIRED/TERMINATED`

辅助状态：

- `MATERIAL_PENDING`：缺材料，仍可补充文件和重新解析。
- `ARCHIVED`：本 PRD 作为 P1 新增状态，需要 DDL、列表筛选、详情标签和恢复流程全部补齐后才能启用。

异常/终止状态：

- 解析失败记录在 `contract_document.parse_status='FAILED'`、`contract_document_job.status='FAILED'` 或工作流状态中。
- Run 失败记录在 `agent_run.status='FAILED'`。
- 合同取消或废弃一期不新增 `CANCELLED` 状态，使用软删除或 `TERMINATED`，避免和 Run 状态混用。

状态变更必须由服务端校验前置状态，不接受前端直接写任意状态。

### 6.2 协作流程

```text
OWNER 创建合同
  -> 上传文件并完成解析
  -> 指派 EDITOR / REVIEWER
  -> Agent Run 生成审查结果
  -> REVIEWER 处理发现和字段
  -> OWNER 提交审批
  -> 指定审批人确认
  -> APPROVED / NEEDS_REVISION
  -> 签署后进入履约跟踪
```

### 6.3 数据表

#### `contract_member`

字段：`id、case_id、user_id、role、status、invited_by、joined_at、removed_at、create_time、update_time`。

约束：

- `UNIQUE(case_id, user_id)`
- 一个合同只能有一个 `OWNER`
- `OWNER` 移交必须显式指定新 Owner，不能直接删除最后 Owner
- 被移除成员保留历史记录，不物理删除

#### `contract_invitation`

字段：`id、case_id、invitee_user_id、role、token_hash、expires_at、status、invited_by、accepted_at`。

状态：`PENDING | ACCEPTED | DECLINED | EXPIRED | REVOKED`。

邀请 token 只存 hash，默认 48 小时过期，接受后立即失效。

#### `contract_comment`

字段：`id、case_id、file_id、finding_id、parent_id、author_id、body、status、edited_at、deleted_at、create_time`。

评论支持回复、@用户、引用文件页码/文本片段；删除采用软删并保留审计。

#### `contract_state_transition`

记录 `case_id、from_status、to_status、actor_id、reason、metadata、create_time`，用于时间线和审计。

### 6.4 接口

| 方法 | 接口 | 权限 | 说明 |
|---|---|---|---|
| `GET` | `/api/workspace/contracts/{caseId}/members` | 合同可见 | 成员列表 |
| `POST` | `/api/workspace/contracts/{caseId}/members/invite` | `OWNER/ADMIN` | 邀请成员 |
| `POST` | `/api/invitations/{token}/accept` | 被邀请人 | 接受邀请 |
| `PATCH` | `/api/workspace/contracts/{caseId}/members/{userId}` | `OWNER/ADMIN` | 改成员角色 |
| `DELETE` | `/api/workspace/contracts/{caseId}/members/{userId}` | `OWNER/ADMIN` | 移除成员 |
| `POST` | `/api/workspace/contracts/{caseId}/owner/transfer` | `OWNER/ADMIN` | 转移负责人 |
| `GET` | `/api/workspace/contracts/{caseId}/comments` | 合同可见 | 评论列表 |
| `POST` | `/api/workspace/contracts/{caseId}/comments` | 合同可见 | 新增评论 |
| `PATCH` | `/api/comments/{commentId}` | 作者/ADMIN | 编辑评论 |
| `DELETE` | `/api/comments/{commentId}` | 作者/OWNER/ADMIN | 删除评论 |
| `POST` | `/api/workspace/contracts/{caseId}/submit-review` | `OWNER/EDITOR` | 提交审核 |
| `POST` | `/api/workspace/contracts/{caseId}/approve` | 被指派审批人/ADMIN | 审批通过 |
| `POST` | `/api/workspace/contracts/{caseId}/request-revision` | 审批人/REVIEWER/ADMIN | 退回修改 |
| `GET` | `/api/workspace/contracts/{caseId}/timeline` | 合同可见 | 协作时间线 |

### 6.5 协作通知

一期支持站内通知，邮件为 P1：

- 被邀请加入合同
- 角色变更或被移除
- 被 @
- 新评论/回复
- 审批通过或退回
- Agent Run 完成或失败
- 文件解析完成或失败

通知必须包含 `event_id`，消费幂等，不能因通知失败回滚业务事务。

### 6.6 前端页面

合同详情页新增四个区域：

1. 文件版本：上传、版本切换、预览、下载、删除。
2. 成员与权限：成员列表、角色、邀请、移交 Owner。
3. 审查工作区：发现项、字段复核、评论、@用户。
4. 活动时间线：状态、文件、Run、评论、审批、额度事件。

交互要求：

- 操作按钮按当前角色动态显示，后端仍是最终权限判断。
- 所有异步动作显示处理中、成功、失败和重试状态。
- 文件下载失败不能被误显示为“无文件”。
- 审批、移除成员、删除文件必须二次确认。

## 7. 跨模块一致性规则

1. 文件上传、合同成员变更、状态变更、额度结算都必须写审计。
2. 删除合同时不能直接删除文件和流水；先软删合同，异步清理对象。
3. 合同不可见时，文件、Run、报告、评论、额度详情全部返回 `404`。
4. 合同成员变更不影响已有历史评论和审计，但影响新请求权限。
5. Agent Run 的输入文件必须保存 `document_id + version + content_hash/storage_key` 快照，避免文件替换导致结果不可复现。
6. 所有写接口支持 `request_id`；创建 Run、邀请、结算额外支持 `idempotency_key`。

## 8. 监控与告警

必须有以下指标：

- 文件上传成功率、扫描失败率、下载拒绝率
- 合同越权访问次数
- `RESERVED` 额度数量及最长等待时间
- 额度对账不一致数量
- Agent Run 成功率、失败率、超时率
- 邀请接受率、审批平均耗时
- 评论通知失败数

告警阈值建议：

- 任一额度预占超过 30 分钟：告警
- 对账不一致大于 0：告警
- 5 分钟内同一用户下载拒绝超过 20 次：风控告警
- Agent Run 失败率连续 10 分钟超过 20%：告警

## 9. 测试要求

### 9.1 权限测试

- 跨部门合同列表、详情、文件、报告、SSE、导出全部拒绝。
- `VIEWER` 不能上传、修改、发起 Run。
- `REVIEWER` 能确认发现项但不能改合同基础字段。
- 成员移除后旧 token 不能继续读取文件。

### 9.2 并发与幂等测试

- 50 个并发 Run 请求不超卖额度。
- 同一幂等键重复 20 次只创建一个 Run。
- complete upload、接受邀请、confirm/refund 重试均只生效一次。

### 9.3 故障测试

- Python 服务宕机后 Run 最终退款。
- Redis Stream 消费失败可重试，不能重复结算。
- 文件上传中途断网可恢复。
- 对账任务重复运行不会改变已结算结果。

## 10. 发布计划

### Phase 1：文件权限闭环

- 私有下载接口
- 文件状态和版本表
- ContractAccessPolicy 覆盖全部文件端点
- 文件审计
- 权限回归测试

### Phase 2：额度结算

- 沿用 `quota_transaction` 做结算账本，必要时再启用 P1 `quota_reservation`
- Run 创建事务
- confirm/refund
- stale reconciliation
- 并发和幂等测试

### Phase 3：协作流程

- 合同成员和邀请
- Owner/Editor/Reviewer/Viewer
- 评论和时间线
- 提交审核、退回、审批
- 站内通知

### 灰度门槛

- P0 自动化测试全部通过
- 无未解释的额度对账差异
- 无公开文件 URL
- 至少完成一次“创建合同 -> 邀请 -> 审阅 -> Agent Run -> 审批 -> 归档”端到端演练
- 完成数据备份和恢复演练

## 11. 待产品确认的规则

1. Agent Run 失败是否一律退款，还是按已产生的计算量部分扣费？
2. 合同 Owner 离职或被禁用后，是否自动转交部门管理员？
3. 文件默认保留期限和删除恢复窗口是多少？
4. 审批是单人审批还是多人会签？
5. 普通用户是否允许邀请同部门用户，还是必须由 Owner 操作？
6. 是否允许已签署合同继续上传新版本，还是只能创建补充协议版本？
