# 二期技术设计（v0.6）

> 日期：2026-10-30
> 状态：**可开工**（24 项决策；第 1~2 步已实现并自检通过，v0.6 补第 3 步的 5 个待定点）
> 上游：业务模型见 [phase-2-approval.md](./phase-2-approval.md) §3；本文只解决"怎么落地"
> 前提：金额阈值已废弃——**所有合同都必须经法务**；老案件不迁移；节点链线性无分支

---

## 1. 表结构

### 1.1 `contract_flow`（流程轮次）

```sql
CREATE TABLE contract_flow (
  id              BIGINT AUTO_INCREMENT PRIMARY KEY,
  case_id         BIGINT      NOT NULL,
  round_no        INT         NOT NULL,
  state           VARCHAR(16) NOT NULL DEFAULT 'RUNNING',  -- RUNNING / COMPLETED / CANCELLED
  version_id      BIGINT      NOT NULL,                    -- 本轮版本；提交审批时写入，审批结论绑定 (flow_id, version_id)
  start_node      VARCHAR(32) NOT NULL DEFAULT 'UPLOADER',  -- 本轮从哪个节点开始（撤回重走时非首节点）
  parent_flow_id  BIGINT      NULL,                        -- 撤回重走时指向上一轮
  baseline_json   JSON        NOT NULL,                    -- 提交时的要素快照（实质字段判定基准）
  baseline_hash   CHAR(64)    NOT NULL,                    -- baseline_json 的 SHA-256
  agent_run_id    BIGINT      NULL,                        -- 本轮当前 agent 运行
  started_by      BIGINT      NULL,
  started_at      DATETIME    NOT NULL DEFAULT CURRENT_TIMESTAMP,
  ended_at        DATETIME    NULL,
  end_reason      VARCHAR(64) NULL,
  UNIQUE KEY uk_case_round (case_id, round_no),
  KEY idx_case (case_id)
);
```

**同一版本不能重开**：新建 flow 前校验 `(case_id, version_id, state='CANCELLED')` 是否存在，存在则要求换版本。

### 1.2 `contract_flow_node`（节点实例）

```sql
CREATE TABLE contract_flow_node (
  id                BIGINT AUTO_INCREMENT PRIMARY KEY,
  flow_id           BIGINT      NOT NULL,
  node_key          VARCHAR(32) NOT NULL,  -- UPLOADER/AGENT/DEPT_APPROVAL/LEGAL_APPROVAL/SIGNING
  seq               INT         NOT NULL,
  state             VARCHAR(16) NOT NULL,  -- WAITING/PENDING/CLAIMED/DONE/BLOCKED/VOID
  assignee_id       BIGINT      NULL,
  claimed_at        DATETIME    NULL,
  claim_expires_at  DATETIME    NULL,
  candidate_group   VARCHAR(64) NULL,      -- OWNER / DEPT:<deptId> / LEGAL
  pending_rerun     TINYINT     NOT NULL DEFAULT 0,  -- agent 运行中再次触发，标 1 待补跑
  entered_at        DATETIME    NOT NULL,
  done_at           DATETIME    NULL,
  UNIQUE KEY uk_flow_node (flow_id, node_key, seq),
  KEY idx_flow_state (flow_id, state)
);
```

节点状态语义（**不变量：`PENDING` 的节点在任何时刻最多一个**）：

| 状态 | 含义 |
| --- | --- |
| `WAITING` | 还没轮到（建链时除 `start_node` 外全部是这个） |
| `PENDING` | 当前待认领 |
| `CLAIMED` | 有人认领，处理中 |
| `DONE` | 已完成 |
| `BLOCKED` | agent 失败等，需人介入 |
| `VOID` | 被打回作废，事件保留 |

推进规则：前一节点变 `DONE` 时，把下一个 `WAITING` 翻成 `PENDING`。

### 1.3 `contract_flow_event`（事件流，只增不改）

```sql
CREATE TABLE contract_flow_event (
  id           BIGINT AUTO_INCREMENT PRIMARY KEY,
  flow_id      BIGINT      NOT NULL,
  node_id      BIGINT      NOT NULL,   -- 所有事件必须挂节点，否则 uk_event 对 NULL 不生效
  event_type   VARCHAR(32) NOT NULL,
  actor_id     BIGINT      NULL,
  actor_type   VARCHAR(8)  NOT NULL,  -- USER / AGENT / SYSTEM
  from_node    VARCHAR(32) NULL,
  to_node      VARCHAR(32) NULL,
  ref_id       BIGINT      NULL,      -- agent_run_id / withdraw_id / sign_check_id
  payload_json JSON        NULL,
  created_at   DATETIME    NOT NULL DEFAULT CURRENT_TIMESTAMP,
  UNIQUE KEY uk_event (flow_id, node_id, event_type, ref_id),
  KEY idx_flow_time (flow_id, created_at),
  KEY idx_flow_type (flow_id, event_type, id)
);
```

`node_id` 挂载规则：`FLOW_START` → `start_node`；`WITHDRAW_*` → 当前活跃节点；`SIGN_*` → `SIGNING` 节点。**MySQL 唯一索引忽略 NULL，所以这一列必须非空，否则重试会重复写入。**

`event_type` 取值：

| 类别 | 取值 |
| --- | --- |
| 流程 | `FLOW_START`、`CANCEL`、`COMPLETE`、`ABANDON` |
| 节点 | `CLAIM`、`RELEASE`、`ENTER` |
| 内容 | `EDIT`、`UPLOAD`、`CONFIRM_ELEMENTS`、`CONFIRM_TIMELINE`、`VERSION_SWITCH` |
| agent | `AGENT_RUN`、`AGENT_FAIL`、`AGENT_RERUN` |
| 审批 | `APPROVE`、`RETURN` |
| 撤回 | `WITHDRAW_REQUEST`、`WITHDRAW_APPROVE`、`WITHDRAW_REJECT`、`WITHDRAW_EXPIRE` |
| 签署 | `SIGN_UPLOAD`、`SIGN_CHECK`、`SIGN_DECISION` |

### 1.4 `contract_flow_claim`（认领记录）

```sql
CREATE TABLE contract_flow_claim (
  id             BIGINT AUTO_INCREMENT PRIMARY KEY,
  node_id        BIGINT      NOT NULL,
  user_id        BIGINT      NOT NULL,
  claimed_at     DATETIME    NOT NULL,
  released_at    DATETIME    NULL,
  release_reason VARCHAR(32) NULL,  -- MANUAL / TIMEOUT / FORCED / RETURNED / DONE
  KEY idx_node (node_id)
);
```

### 1.5 `contract_flow_withdraw`（撤回申请）

```sql
CREATE TABLE contract_flow_withdraw (
  id            BIGINT AUTO_INCREMENT PRIMARY KEY,
  flow_id       BIGINT      NOT NULL,
  requester_id  BIGINT      NOT NULL,
  target_node   VARCHAR(32) NOT NULL,   -- 撤回后从哪个节点重走
  reason        VARCHAR(512) NOT NULL,
  state         VARCHAR(16) NOT NULL DEFAULT 'PENDING',  -- PENDING/APPROVED/REJECTED/EXPIRED
  pending_flag  TINYINT GENERATED ALWAYS AS (IF(state='PENDING', 1, NULL)) STORED,
  decided_by    BIGINT      NULL,
  decided_at    DATETIME    NULL,
  created_at    DATETIME    NOT NULL DEFAULT CURRENT_TIMESTAMP,
  UNIQUE KEY uk_flow_pending (flow_id, pending_flag),  -- 同一流程只能有一个未决撤回
  KEY idx_flow (flow_id)
);
```

`pending_flag` 是关键：MySQL 唯一索引对 `NULL` 不生效，所以用生成列把"未决"映射成 1、其余映射成 `NULL`，从数据库层面挡住"同时两个未决撤回"。

### 1.6 `contract_sign_check`（签署件核对）

```sql
CREATE TABLE contract_sign_check (
  id                BIGINT AUTO_INCREMENT PRIMARY KEY,
  flow_id           BIGINT      NOT NULL,
  version_id        BIGINT      NOT NULL,
  signed_doc_id     BIGINT      NOT NULL,
  rule_result_json  JSON        NULL,
  agent_result_json JSON        NULL,
  verdict           VARCHAR(16) NOT NULL,  -- MATCH / MISMATCH / UNKNOWN
  decided_by        BIGINT      NULL,
  decision          VARCHAR(16) NULL,      -- APPROVE / RERUN / ABANDON
  decided_at        DATETIME    NULL
);
```

## 2. 状态派生（不存"当前阶段"，算出来）

### 2.1 当前节点

```
当前节点 = flow 内 state ∈ {PENDING, CLAIMED, BLOCKED} 的节点（不变量：最多一个）
若全部 DONE → 流程待 COMPLETE
若无 RUNNING 的 flow → 案件无进行中流程
```

**不需要"取最小 seq 兜底"**——`WAITING` 只表示未到达，`PENDING` 只表示当前待办，两者的语义不重叠。若查询出现多个 `PENDING`，那是数据坏了，应当报警而不是容错。

### 2.2 当前持有者

```
holder = 当前节点.assignee_id
holder 为空 → 待认领，展示候选组
```

### 2.3 时间轴（替换一期阶段条）

**节点链是线性的，没有并行分支**：任何时刻只有一个活跃节点（`PENDING`/`CLAIMED`/`BLOCKED`），其余是 `DONE`、`WAITING` 或 `VOID`。打回是回退，不是分支——它把当前节点及中间节点标 `VOID`，把目标节点重新置为 `PENDING`。

时间轴由两类数据合成，**统一按时间排序**：

| 来源 | 内容 | 数据量 |
| --- | --- | --- |
| 8 阶段里程碑 | 由少数几类事件推导"进入某阶段" | 每单 ≤ 8 条 |
| 事件流 | 全部动作，逐条挂轴 | 每单几十~几百条 |

**必须进时间轴的动作**（不是可选项）：

| 事件 | 展示 |
| --- | --- |
| `EDIT` | 谁改了哪些字段，前后值 |
| `UPLOAD` / `VERSION_SWITCH` | 上传/换版，版本号 |
| `CONFIRM_ELEMENTS` / `CONFIRM_TIMELINE` | 谁在什么时候确认了要素/日程 |
| `AGENT_RUN` / `AGENT_RERUN` / `AGENT_FAIL` | 跑了什么任务、耗时、结论、失败原因 |
| `CLAIM` / `RELEASE` | 谁认领、谁放回、为什么 |
| `APPROVE` / `RETURN` | 通过 / 打回，打回含目标节点与理由 |
| `WITHDRAW_REQUEST` / `WITHDRAW_APPROVE` / `WITHDRAW_REJECT` | 撤回全程 |
| `CANCEL` / `ABANDON` / `COMPLETE` | 流程终止的三种方式 |

**查询实现**（不缓存）：

- 里程碑：`WHERE flow_id=? AND event_type IN ('CONFIRM_ELEMENTS','CONFIRM_TIMELINE','ENTER','AGENT_RUN','APPROVE','SIGN_UPLOAD','COMPLETE')`，配合 `(flow_id, event_type)` 索引，结果 ≤ 20 行
- 事件列表：游标分页 `WHERE flow_id=? AND (created_at, id) < (?, ?) ORDER BY created_at DESC, id DESC LIMIT 50`
- 索引：`KEY idx_flow_type (flow_id, event_type, id)`

里程碑推导（**①② 不走事件**，沿用 [phase-1-workflow-view.md](./phase-1-workflow-view.md) §② 的口径）：

| 阶段 | 数据源 | 规则 |
| --- | --- | --- |
| ① 受理建档 | `contract_case` + 是否有主文档 | 一期口径：无主文档 → `WAITING_HUMAN`；有 → `DONE` |
| ② 解析就绪 | `contract_document.parse_status` | PENDING/PARSING → `ACTIVE`；FAILED → `BLOCKED(PARSE_FAILED)`；READY 且低质量 → `BLOCKED(QUALITY_LOW)`；READY → `DONE` |
| ③ 要素确认 | 事件 `CONFIRM_ELEMENTS` | 出现即 `DONE` |
| ④ 日程确认 | 事件 `CONFIRM_TIMELINE` | 出现即 `DONE` |
| ⑤ 风险处置 | 事件 `AGENT_RUN` / `ENTER(DEPT_APPROVAL)` / `ENTER(LEGAL_APPROVAL)` / `APPROVE(LEGAL_APPROVAL)` | 见下表 |
| ⑥ 签署 | 事件 `SIGN_UPLOAD` / `COMPLETE` | SIGN_UPLOAD → `ACTIVE`；COMPLETE → `DONE` |
| ⑦ 履约 / ⑧ 归档 | `contract_case.status` + `expiry_date` | 一期口径，标记 `inactive` |

**为什么不把 ①② 也从事件推**：`parse_status=FAILED` 和解析低质量都是**需要人介入的异常**，如果按"能走到 agent 就等于解析完了"处理，前端就看不到 `PARSE_FAILED`，重试入口会消失。

代价：timeline 接口多一次 `contract_document` 查询（按 case_id 取主文档）。可接受。

**⑤ 的边界（2026-10-30 定）**：

| 时机 | ⑤ 状态 | 理由 |
| --- | --- | --- |
| `AGENT_RUN`（ConsTRACT_REVIEW 完成） | `ACTIVE` | 风险清单已产出，进度不能还显示"未开始" |
| `ENTER(DEPT_APPROVAL)` | `WAITING_HUMAN` | 等部门审批人处理 |
| `ENTER(LEGAL_APPROVAL)` | `WAITING_HUMAN` | 等法务 |
| `APPROVE(LEGAL_APPROVAL)` | `DONE` | 风险处置结束，进入签署 |

不采用"agent 一开始跑就亮 ⑤"——agent 跑在 ③④ 确认之前，会让进度条倒流。

**⑦⑧ 的数据源（2026-10-30 定）**：flow 只产出 **③~⑥** 的里程碑；**①② 读案件/文档状态**（见上表），⑦ 履约、⑧ 归档继续读 `contract_case.status` + `expiry_date`（一期口径），二期不补 `FULFILLMENT_START` / `ARCHIVE` 事件——那属于三期。前端把 ⑦⑧ 显示为灰色未激活刻度，悬浮提示"由案件状态跟踪，暂未纳入流程"。

### 2.4 取消判定

```
可取消 = (当前节点.state='PENDING' AND now - 当前节点.entered_at >= 6h)
       OR (存在 node_key='AGENT' AND state='BLOCKED')
```

不满足时接口返回 `CANCEL_NOT_ALLOWED` + 具体原因码，前端置灰并展示原因。

### 2.5 打回

```
RETURN(to_node):
  1. 校验 to_node 是当前节点之前的节点
  2. 当前节点 → VOID；to_node 之后、当前节点之前的所有节点 → VOID
  3. to_node.state = PENDING，assignee 清空，entered_at = now
  4. 写事件 RETURN（from/to/reason/actor）
```

### 2.6 撤回（批准后开新轮，不是同一轮回退）

**为什么开新轮**：撤回必然伴随内容变更 → 产生新版本。若在同一 `flow` 内回退，`flow.version_id` 会被改写，导致"法务批的是 v1、flow 上记的是 v2"，审计查不清谁批了哪一版。**每一轮的版本与审批结论必须落在同一行。**

```
WITHDRAW_REQUEST(by=user, target_node):
  1. 校验 flow.state='RUNNING'
  2. INSERT contract_flow_withdraw(flow_id, requester_id, target_node, reason, state='PENDING')
     → 唯一索引挡并发：同一流程已有未决申请时直接失败
  3. 写事件 WITHDRAW_REQUEST

当前持有者 APPROVE(withdraw_id):
  1. withdraw.state='APPROVED', decided_by, decided_at
  2. 当前 flow.state='CANCELLED', end_reason='WITHDRAWN'
  3. 新建 flow: round_no+1、parent_flow_id=旧 flow.id、**start_node = 撤回申请中指定的 target_node**、
     version_id=当前最新版本、baseline_json=当前要素快照
  4. 从 start_node 起建节点链，start_node 之前的节点直接置 DONE（不重复劳动）
  5. 写事件 WITHDRAW_APPROVE（记在旧 flow）与 FLOW_START（记在新 flow）

**新轮的节点链只从 `start_node` 建起，不建前置节点**（2026-10-30 定）：

- 前置节点的"完成"发生在上一轮，若在新轮里再建一遍并标 `DONE`，`done_at` 要么是假的（填当前时间），要么是空的（违反约束）
- 不建即无假数据；前端把缺的前几段显示为「上一轮已完成」，而不是"本轮已完成"
- `seq` 沿用 `NODE_CHAIN` 的原始序号，保证顺序不变

当前持有者 REJECT(withdraw_id):
  withdraw.state='REJECTED'；写事件 WITHDRAW_REJECT；流程状态不变

申请人 == 当前持有者：不允许自批，转 ADMIN 队列

自动失效（见 §2.10）：
  当前节点变 DONE 时，未决 withdraw 置 EXPIRED + 事件 WITHDRAW_EXPIRE
```

撤回期间流程**不冻结**：当前节点仍可正常审批，只是申请人不能再改内容。

### 2.7 内容修改（关键联动）

```
EDIT(实质字段):
  1. 写事件 EDIT（diff 摘要）
  2. 生成新版本（`contract_document.version` + 1），`flow.version_id` 更新为新版本
     （此时尚无审批结论，改版本不产生歧义；若已有审批通过，见步骤 5，走撤回而不是直接改）
  3. 当前 AGENT 节点 state=PENDING，写 AGENT_RERUN
  4. UPLOADER 节点的 CONFIRM_ELEMENTS / CONFIRM_TIMELINE 作废，需重新确认
  5. 若修改发生在审批之后 → 走撤回流程，不直接改
```

### 2.8 合同变更 → agent 自动运行

**触发判定（二选一，命中即触发）**：

| 触发 | 判定方法 |
| --- | --- |
| 新版本 | `contract_document` 新增 `version`，且 `storage_status='AVAILABLE'` |
| 内容变更 | **`baseline_json` 与当前要素比对**：命中 §2.8 的 7 个实质字段才算变更 |

**执行规则**：

```
onContractChanged(flowId):
  1. 若 AGENT 节点 state='RUNNING' → 合并：标记 pending_rerun=1，本次结束立即再跑一次
  2. AGENT 节点 state=PENDING，entered_at=now
  3. 写事件 AGENT_RERUN（含触发原因：新版本 / 字段变更 / 撤回）
  4. 调用现有任务入口（CONTRACT_ELEMENT_EXTRACTION + TIMELINE_EXTRACTION + CONTRACT_REVIEW）
  5. 跑完写 AGENT_RUN（耗时、结论、run_id）；失败写 AGENT_FAIL 并把节点置 BLOCKED
  6. UPLOADER 节点回到"待确认"，CONFIRM_* 事件作废（不删除，追加作废标记事件）
```

**"实质字段"清单**（变了才触发）：金额、币种、甲乙方、起止日期、付款条款、违约责任、责任上限。标点、排版、错别字不触发。

**幂等**：同一 `(flow_id, version_hash)` 只跑一次；重复触发由 `pending_rerun` 合并。

### 2.9 agent 节点的推进契约（补齐，2026-10-30）

**现状核实**：

- `agent_run` 由 Python 侧**直接写 MySQL**（共享库），Java 只读
- `HttpAiGateway.getAgentRun()` **全仓库零调用**（死代码）
- **没有任何回调端点**
- Python 服务**不在本仓库**

结论：二期不能让"流程语义"继续靠隐式共享库。必须显式定契约。

| 方案 | 做法 | 优点 | 缺点 |
| --- | --- | --- | --- |
| **A. Java 轮询（采用）** | 定时任务扫 `AGENT` 节点，按 `agent_run_id` 读状态 | 不改另一个仓库；流程语义单点写入 | 最多 5s 延迟；任务必须幂等 |
| B. Python 回调 | 完成后 POST 内部接口 | 实时 | 要改另一个仓库；失败需重试；两侧都写流程 |
| C. Python 直写 flow 表 | — | 最快 | 语义散落两个服务，禁止 |

**轮询器规则**：

```
扫描：node_key='AGENT' AND state IN ('PENDING','CLAIMED') AND flow.state='RUNNING'
状态映射：
  Python SUCCEEDED → node DONE  + 事件 AGENT_RUN
  Python FAILED    → node BLOCKED + 事件 AGENT_FAIL(reason)
  RUNNING 且 30 分钟无进度 → node BLOCKED + 事件 AGENT_FAIL(reason=TIMEOUT)
幂等：以 (agent_run_id, 状态迁移) 为准，事件唯一键见 §2.11
```

### 2.10 撤回 × 节点完成 竞态真值表

| # | 场景 | 期望结果 |
| --- | --- | --- |
| 1 | 撤回待批，当前节点被**通过** | `withdraw.state=EXPIRED` + 事件 `WITHDRAW_EXPIRE`（改都没改就批了，撤回失去意义） |
| 2 | 撤回待批，当前节点被**打回** | 当前节点 VOID；`withdraw.state=EXPIRED`（reason=`SUPERSEDED`） |
| 3 | 撤回待批，流程被**取消** | `withdraw.state=EXPIRED` |
| 4 | 撤回待批，申请人 = 当前持有者 | 不禁止提交，但**不允许自批**，转 ADMIN 队列 |
| 5 | 撤回待批，申请人被移出候选组 | 仍可批准——决策看 `requester_id`，不看候选组 |
| 6 | 撤回已批，目标节点已 VOID | 新轮从 `start_node` 重建节点链，不修改旧轮，无冲突 |
| 7 | 撤回已批，同版本再次提交 | 允许——新轮是不同 `flow_id`，"同版本不能重开"只约束被**取消**的轮次 |
| 8 | 两个撤回请求并发 | 唯一索引挡第二个，返回 `409 WITHDRAW_PENDING_EXISTS` |

### 2.11 事务与并发（硬约束）

| 约束 | 做法 |
| --- | --- |
| **动作与事件同事务** | 状态变更 + 事件写入在一个事务内，失败一起回滚。**禁止** `catch (ignored)`——现状 `transitionStatus` 的审计写入就是吞异常的，二期不能照抄 |
| **认领乐观锁** | `UPDATE contract_flow_node SET assignee_id=?, state='CLAIMED' WHERE id=? AND state='PENDING' AND assignee_id IS NULL`；影响行数 0 → `409 ALREADY_CLAIMED` |
| **审批类动作加行锁** | `SELECT ... FROM contract_flow_node WHERE id=? FOR UPDATE`，再做状态校验 |
| **事件唯一性** | `UNIQUE KEY uk_event (flow_id, node_id, event_type, ref_id)`，`ref_id` 存 `agent_run_id` / `withdraw_id` 等，防重试重复写 |
| **确认幂等** | `CONFIRM_*` 的 `ref_id` 为 NULL，唯一键对它不生效 → 幂等必须由代码保证，见 §3.2 |

因此 `contract_flow_event` 增加一列：

```sql
ref_id BIGINT NULL,   -- 关联的 agent_run_id / withdraw_id / sign_check_id
UNIQUE KEY uk_event (flow_id, node_id, event_type, ref_id)
```

## 3. 接口清单

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| POST | `/api/flows/cases/{caseId}/start` | 开启一轮流程（校验同版本未取消） |
| GET | `/api/flows/cases/{caseId}/current` | 当前轮 + 当前节点 + 持有者 |
| GET | `/api/flows/cases/{caseId}/timeline` | 时间轴，`?cursor=&limit=50`；游标为 `(created_at, id)`，见决策 19 |
| POST | `/api/flows/nodes/{nodeId}/claim` | 认领（`?force=true` 仅 ADMIN，写 `ADMIN_OVERRIDE`） |
| POST | `/api/flows/nodes/{nodeId}/release` | 放回（含超时放回） |
| POST | `/api/flows/nodes/{nodeId}/approve` | 通过 |
| POST | `/api/flows/nodes/{nodeId}/return` | 打回，body: `{toNodeKey, reason}` |
| POST | `/api/flows/{flowId}/withdraw` | 申请撤回，body: `{targetNode, reason}` |
| POST | `/api/flows/withdraws/{withdrawId}/decide` | 批准/驳回，body: `{approved, comment}` |
| POST | `/api/flows/{flowId}/cancel` | 取消，body: `{reason}` |
| POST | `/api/flows/{flowId}/agent-rerun` | 手动触发重跑（自动触发见 §2.8） |
| POST | `/api/flows/cases/{caseId}/sign-doc` | 上传签署件 |
| POST | `/api/flows/sign-checks/{id}/decide` | 签署核对结论，body: `{decision}` |
| POST | `/api/flows/cases/{caseId}/confirm-elements` | 上传人确认要素，写 `CONFIRM_ELEMENTS` |
| POST | `/api/flows/cases/{caseId}/confirm-timeline` | 上传人确认日程，写 `CONFIRM_TIMELINE` |
| POST | `/api/flows/cases/{caseId}/edit` | 修改实质字段，body `{changes, reason}`，见 §3.2 |
| POST | `/api/flows/cases/{caseId}/version` | 登记版本切换，body `{documentId}`，见 §3.2 |

**兼容**：一期 `GET /contracts/{caseId}/workflow` 保留，内部改为读 flow 派生，字段不变。

### 3.1 接口 → 实施步骤（防止漏做）

| 步骤 | 接口 |
| --- | --- |
| 第 1~2 步 | `start`（服务层已有，控制器待建） |
| **第 3 步** | `current`、`timeline`、`confirm-elements`、`confirm-timeline`、`edit`、`version` |
| **第 4 步** | `sign-doc`、`sign-checks/{id}/decide` |
| **第 5 步** | `claim`（含 force）、`release`、`approve`、`return`、`withdraw`、`withdraws/{id}/decide`、`cancel`、`agent-rerun` |

第 3 步之所以要带 `confirm-*` / `edit` / `version`：**没有它们，时间轴里 `CONFIRM_*`、`EDIT`、`UPLOAD` 三类事件在真实环境永远是空的**，页面做出来是个空壳。

### 3.2 接口语义约定（2026-10-30 定）

**`version` 只管登记切换，不建文档版本**

- 文件上传继续走一期已有的文档接口，`contract_document.version` 只由 Python 解析流水线写
- 本接口收 `{documentId}`：校验文档属于该案件 → 写 `UPLOAD`（首次）或 `VERSION_SWITCH`（换版）→ 更新 `flow.version_id`
- **不在此接口里新建 `contract_document` 记录**，避免两处同时管版本号

**`edit` 由后端比对，前端不提交 diff**

```json
{ "changes": { "amount": "450000", "endDate": "2027-01-01" }, "reason": "客户砍价" }
```

```
1. 读 flow.baseline_json，逐字段比对 changes
2. 命中 7 个实质字段（金额/币种/甲乙方/起止日期/付款条款/违约责任/责任上限）
   → 写 EDIT（含 diff 摘要）+ 生成新版本 + AGENT_RERUN + 作废 CONFIRM_*
3. 未命中 → 只写 EDIT，不重跑、不作废确认
```

判定放后端的原因：前端算 diff 等于把"什么算实质变更"这条业务规则下放到浏览器，且与 §2.8 的幂等冲突。

**`confirm-*` 幂等**

- 判据：该轮该节点已有 `CONFIRM_ELEMENTS`/`CONFIRM_TIMELINE`，且其后**没有** `AGENT_RERUN` / `EDIT` → 直接返回 200 + 当前状态，**不写新事件**
- agent 重跑后需要重新确认，那是**新的**确认，照常写
- 理由：同一人连点两次按钮不该产生两条同样的审计记录；重复项本身就是噪音
- 注意：`CONFIRM_*` 的 `ref_id` 为 NULL，`uk_event` 对此不生效，所以这条幂等**必须由代码保证**，不能指望数据库

**`timeline` 默认返回全部轮次**

- 默认跨轮返回，按 `round_no` 分组；`?round=N` 只取某轮
- 游标 `(created_at, id)`：跨轮天然有序，时间单调递增，不必为跨轮改游标
- **里程碑只算当前轮**，历史轮只返回事件
- 边界：`limit` 可能截在某一轮中间 → 前端渲染"已加载的轮完整、最后一轮不完整"，尾部显示「加载更多」

## 4. 签署件比对规则

| # | 规则 | 判定 | 失败后果 |
| --- | --- | --- | --- |
| 1 | 文件哈希 | 完全相同 → `MATCH`（最理想） | 不同继续比 |
| 2 | 页数 | 页数差 > 0 | `MISMATCH` |
| 3 | 条款编号集合 | 审批版有的编号，签署件缺失 | `MISMATCH` |
| 4 | 关键字段 | 金额、甲乙方、起止日期、付款条款编号 | 任一不等 → `MISMATCH` |
| 5 | 文本相似度 | 归一化后 < **98%** | 标记差异段落 |

- 规则 1 命中：直接 `MATCH`，不再跑 agent
- 规则 2~4 命中：`MISMATCH`，仍跑 agent 补充语义差异
- 全部通过但相似度 < 98%：`UNKNOWN`，agent 提示"疑似语义改动"，**只标记不阻断**，交法务终裁
- **agent 永远不判定 `MATCH`**，只输出"疑似不一致 + 位置 + 证据"

`rule_result_json` 结构：

```json
{"hash":"same|diff","pages":{"approved":12,"signed":12},
 "clauses":{"missing":[],"added":["第 8.2 条"]},
 "fields":{"amount":{"approved":"500000","signed":"450000","equal":false}},
 "similarity":0.973}
```

## 5. 权限与角色映射

| 节点 | 谁可以进候选组 | 来源 | 候选组为空时 |
| --- | --- | --- | --- |
| UPLOADER / SIGNING | 案件 `creator_id`、`maintainer_id` | `contract_case` | **回落 ADMIN**，见下 |
| DEPT_APPROVAL | 该部门审批人（`dept_approver` 白名单：`dept_id + user_id`） | 新表 | **阻断** `NO_APPROVER` |
| LEGAL_APPROVAL | 法务组成员（`flow_role_member`：`role_code='LEGAL'`） | 新表 | **阻断** `NO_APPROVER` |

- 成员角色 `OWNER/EDITOR/REVIEWER/VIEWER` 与流程角色是**两套**，不互相推导
- **`DEPT_APPROVAL` / `LEGAL_APPROVAL` 候选组为空 → 提交被阻断**，返回 `NO_APPROVER`，页面提示"请管理员配置该部门审批人"
- **`ADMIN` 不是审批节点的候选人**，不参与这两个节点的回落。它只有"**强制认领**"能力：`POST /nodes/{id}/claim?force=true`，仅 ADMIN 可调，必须写 `ADMIN_OVERRIDE` 事件，时间轴上可见

> 早期版本写的是"ADMIN 永远是兜底候选人"，与"候选组为空即阻断"互相矛盾，已废弃。原因是：一旦回落，管理员会变成所有部门的默认审批人，等于取消部门审批。宁可卡住，也不要静默降级。

**UPLOADER 为什么例外**：

- 它**不是审批**，是录入。管理员代提交不等于替人做决策
- 历史案件可能有 `creator_id` / `maintainer_id` 都为空的孤儿数据，不回落就**完全没有入口**，只能靠 SQL 修数据
- 但**必须留痕**：管理员以非 owner 身份在 `UPLOADER` / `SIGNING` 节点操作（含通过回落路径获得候选资格）时，一律写 `ADMIN_OVERRIDE` 事件，`payload.reason = CANDIDATE_FALLBACK`

两类回落的差别：**审批节点回落 = 业务规则失效；录入节点回落 = 修数据缺陷。** 前者禁止，后者允许但必须可追溯。

## 6. 迁移

- **老案件不迁移**：`contract_flow` 无记录即视为历史案件
- 一期页面遇到无 flow 的案件：时间轴显示"历史案件，无流程记录"，不报错
- 不删除任何老数据；如需物理清理，单独立项
- 新流程只对"开启流程"之后的案件生效

## 7. 与缺陷的对应

| 现状缺陷 | 本设计如何消除 |
| --- | --- |
| `PENDING_APPROVAL` 死循环 | 流程由 `contract_flow` 驱动，不再依赖 `status` 迁移 |
| `updateCase` 任意改 status | 审批相关 status 不再写入；`status` 只做汇总展示字段 |
| 通过后无出口 | `SIGNING` 节点 + `COMPLETE` 事件 |
| 没有"该谁审" | 候选组 + 认领 |
| 没有留痕 | `contract_flow_event` 只增不改 |
| `enteredAt` 为空 | 由 `contract_flow_node.entered_at` 填充 |

### 7.1 与 `contract_analysis_workflow` 的分工（2026-10-30 定）

仓库里原本已有一张"流程表" `contract_analysis_workflow`（`current_stage=DOCUMENT_PARSE…`），驱动文档解析流水线。二期**不合并、不退役**，两者分工如下：

| 表 | 只管 | 谁写 | 谁看 |
| --- | --- | --- | --- |
| `contract_analysis_workflow` | 文档解析流水线（段切分、页码、质量） | Python | 不直接展示给用户，② 阶段的数据来源 |
| `contract_flow`（新） | 人的审批链（认领、通过、打回、撤回、取消、签署） | Java | 详情页节点条与时间轴 |

**边界规则**：flow 的 `AGENT` 节点只表达"流程内的一次 agent 动作"（触发、完成、失败、重跑），**不展示解析进度**；解析进度仍由 `analysis_workflow` 表达，只在 ② 阶段以"解析中/解析完成"呈现。

三年内如果要做归一，是**三期**的事；二期只加这一行说明，防止接手的人以为有两套审批流。README §9 同步加防混淆说明。

## 8. 评审与决策结论（2026-10-30）

| # | 议题 | 结论 | 理由 |
| --- | --- | --- | --- |
| 1 | 撤回中状态 | **独立表 `contract_flow_withdraw`** | "同一流程只能有一个未决撤回"需要落成唯一约束 |
| 2 | 权限表 | **两张表** `dept_approver` / `flow_role_member` | 只有两种节点，多态是提前优化 |
| 3 | 时间轴 | **事件类型过滤 + 索引，不缓存** | 里程碑只依赖少数几类事件 |
| 4 | 撤回后重走 | **开新轮**（`round_no+1`、`start_node`、`parent_flow_id`） | 同轮回退会让 `version_id` 被改写，审批结论与版本脱钩 |
| 5 | 撤回 × 节点完成 | **节点 DONE → withdraw EXPIRED** | 见 §2.10 真值表 |
| 6 | agent 节点推进 | **Java 轮询 Python 状态**（5s） | 不改另一个仓库；流程语义单点写入 |
| 7 | ⑦⑧ 数据源 | **混合**：①~⑥ 读 flow 事件，⑦⑧ 读 `contract_case.status` | ⑦⑧ 是三期范围 |
| 8 | ⑤ 边界 | agent 审查完成 → `ACTIVE`；法务通过 → `DONE` | 避免进度条倒流 |
| 9 | 与 `analysis_workflow` | **并存，分工写死**（§7.1） | 二期不碰 Python 流水线 |
| 10 | 通知 | **新建 `flow_notification`**（带 `user_id`、`event_id`） | `kb_notification` 无收件人；`kb_` 是知识库语义 |
| 11 | 相似度阈值 | **98%，只标记不阻断** | 跑 20 单后按真实分布回调 |
| 12 | 测试 | **flow 相关用 Testcontainers 真 MySQL** | `pending_flag` 生成列 + JSON 在 H2 下不保证兼容，而它正是并发保障的核心 |
| 13 | 节点状态 | **新增 `WAITING`**，`PENDING` 任何时刻最多一个 | 否则建链时多个 `PENDING` 并存，靠"取最小 seq"兜底，时间轴推导会错 |
| 14 | 候选组为空 | **审批节点（DEPT/LEGAL）阻断、不回落 ADMIN；UPLOADER 允许回落但必须写 `ADMIN_OVERRIDE`** | 审批回落等于让管理员成为所有部门默认审批人；录入回落只是给孤儿数据一个入口，留痕即可 |
| 15 | `event.node_id` | **`NOT NULL`** + `uk_event` 真生效 | MySQL 唯一索引忽略 NULL，否则 `SIGN_CHECK` 等重试会重复写入 |
| 16 | 撤回新轮起点 | **以撤回申请的 `target_node` 为准** | 与代码一致，比"申请人所在节点"更直接 |
| 17 | 第 3 步范围 | **追加 `confirm-*` / `edit` / `version` 四个接口** | 否则时间轴里三类事件永远无数据 |
| 18 | 撤回新轮的节点链 | **只从 `start_node` 建起，不建前置节点** | 前置节点在新轮标 `DONE` 会导致 `done_at` 造假或为空 |
| 19 | 事件分页游标 | **`(created_at, id)` 联合游标**，不用单列 `id` | 同一秒多事件（批量写入）按 `id` 翻页会漏页或重页 |
| 20 | ①② 里程碑数据源 | **沿用一期口径**（案件主文档 + `parse_status`），不从 flow 事件推 | 从事件推会吞掉 `PARSE_FAILED` / 低质量，前端重试入口消失 |
| 21 | `version` 接口职责 | **只登记切换，不建文档版本** | 两处同时管 `contract_document.version` 必然打架；版本号只由 Python 写 |
| 22 | `edit` 的 diff 判定 | **后端比对 `baseline_json`**；§2.8 的"文档内容哈希"废弃 | 前端算 diff 等于把业务规则下放浏览器；PDF 重生成会改文件哈希，错别字也触发重跑 |
| 23 | `confirm-*` 幂等 | **做幂等**：同轮同节点已确认且其后无 `AGENT_RERUN`/`EDIT` → 直接返回成功 | 连点两次不该产生两条一样的审计记录；`ref_id` 为 NULL 时唯一键管不住 |
| 24 | `timeline` 跨轮 | **默认返回全部轮次并按轮分组**，`?round=N` 过滤；里程碑只算当前轮 | 前端按轮分组，分两次请求反而要自己拼；游标天然有序 |

### 遗留待定

1. 里程碑查询 P95 超过 300ms，或单案事件超过 500 条时 → 加 2 秒缓存（照抄一期 `ContractWorkflowService`）
2. `pending_rerun` 放 `contract_flow_node` 字段（已定：字段，多实例安全）
3. 时间轴可见性：默认对**有案件访问权的成员**可见；参与人可操作。若后续要求"仅参与者可见时间轴"，改 `ContractAccessPolicy` 一处即可
