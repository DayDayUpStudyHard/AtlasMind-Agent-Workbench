# 合同案件工作流视图 设计定稿（一期：让流程看得见）

> 版本：v1.4（定稿，2026-10-29 续实施：兼容性口径见 README §8 v1.4；阶段枚举不变）
> 日期：2026-10-29
> 状态：**已实现并完成本地分层验收**；逐项覆盖及外部 AI 链路限制见 [实施记录](./implementation-phase-1.md) 最新追加节
> 上游依据：[合同案件生命周期业务主线 PRD](../prd-contract-case-lifecycle.md)
> 阶段枚举：[阶段与状态枚举](./README.md)（唯一真源，冲突时以 README 为准）
> 范围：一期只做「展示与引导」，不改状态机、不做审批写入、不做履约台账归一

---

## 1. 已确认的决策

| # | 决策 | 结论 |
| --- | --- | --- |
| 1 | 工作流条位置 | **替换**现有「合同分析流程」面板，不新增第二条进度条 |
| 2 | 阶段由谁计算 | **后端计算**，前端只渲染（新增 workflow 接口） |
| 3 | 展示粒度 | 8 阶段主条 + 当前阶段展开子步骤 |
| 4 | 审批人 | 按金额阈值自动定角色，允许改派并留痕（二期实现，一期只显示"该谁审"） |
| 5 | 「运行 Agent」下拉 | **收起**为「高级操作」，默认折叠；主路径只走工作流条上的主按钮 |

## 2. 目标与非目标

**目标**

- 任何一个角色打开案件，3 秒内知道：现在在哪一步、谁该动、卡在哪、下一步点哪里。
- 阶段判断只有一份实现（后端），用户端 / 管理端 / 后续通知共用。

**非目标（一期明确不做）**

- 不做审批通过/退回按钮，不建审批记录表（二期）。
- 不改 `PENDING_APPROVAL` 的迁移条件、不修 `status` 任意写入（二期）。
- 不做金额阈值配置界面（二期）。
- 不做履约义务台账归一（第 1 层）。
- 不引入新表、不改现有表结构。

## 3. 页面结构

### 3.1 案件详情页（替换现有面板）

```text
┌──────────────────────────────────────────────────────────────────────┐
│ HT-2026-0042  [履约中]   技术服务合同                    [高级操作 ▾] │
│ 上传：张三   维护：李四   [负责人]                                    │
├──────────────────────────────────────────────────────────────────────┤
│ ①受理  ②解析  ③要素  ④日程  ⑤风险  ⑥签署  ⑦履约  ⑧归档           │
│  ✓     ✓     ✓     ●     ○     ○     ○     ○                      │
│ 已完成 已完成 已完成 待确认 等待中 未开始 未开始 未开始            │
│                     业务负责人                                     │
├───────────────────────────────────────────┬──────────────────────────┤
│ 当前阶段：日程确认                        │ 下一步                   │
│ 进入时间：10-29 14:02（已停留 2 小时）    │ 确认履约日程             │
│ 已识别 12 个时间节点，3 个待确认          │ 业务负责人 · 李四        │
│                                           │ [ 去确认 ]               │
└───────────────────────────────────────────┴──────────────────────────┘
├─ 卡住了？ [ 为什么不能提交审批 ]  ← 仅在有阻塞时出现
```

要点：

- 8 段横排，窄屏横向滚动；每段只显示「序号 + 名称 + 状态 + 责任人角色」。
- 当前阶段展开子步骤（例如"日程确认"下显示：候选 12 → 已复核 9 → 待确认 3）。
- 右侧「下一步」是唯一主按钮；点击后调用现有动作（确认要素 / 确认日程 / 处置风险 / 上传证据），不新增业务逻辑。
- 阻塞时显示原因码对应的人话（见 §6），并提供"找谁"提示。

### 3.2 合同列表页

卡片增加一行：`阶段标签` + `卡在谁那里`（无阻塞则不显示）。筛选器由"状态"改为"阶段"（状态筛选保留为二级）。

列表只显示 8 阶段，不显示子步骤（避免 N+1 查询与信息过载）。

### 3.3 「高级操作」

原「运行 Agent」下拉改为 `<details>`：「高级操作（一般不需要）」，默认折叠，保留原有 6 个菜单任务（风险审查、要素提取、日程提取、版本复核、审批意见草案、义务提取）及各自说明。系统另有受理建档、履约核验两个上下文入口；不为凑齐 8 个菜单按钮改变任务的准入条件。

一期不做角色限制（避免动权限模型），二期再按角色收口。保留原因：实施与排障需要手动重跑。

## 4. 阶段状态定义

每段五种状态：

| 状态 | 含义 | 视觉 |
| --- | --- | --- |
| `DONE` | 已完成 | 绿色 ✓ |
| `ACTIVE` | 进行中（系统在跑） | 蓝色，带进度 |
| `WAITING_HUMAN` | 等人处理（当前阶段） | 橙色高亮 + 主按钮 |
| `BLOCKED` | 卡住，需人介入才能继续 | 红色 + 原因 |
| `PENDING` | 未开始 | 灰色 |

> 说明：`WAITING_HUMAN` 与 `BLOCKED` 的区别是"正常等待"还是"异常中断"。卡住时同时给 `blockedReason` 与 `建议动作`。

## 5. 阶段推导规则（后端唯一实现）

按顺序判定，命中即停。字段来源均为现有表，不改结构。

| 阶段 | 判定顺序 |
| --- | --- |
| ① 受理建档 | 无主合同文档 → `WAITING_HUMAN`（发起人上传）；有主文档 → `DONE` |
| ② 解析就绪 | 文档 `parse_status` = PENDING/PARSING → `ACTIVE`；FAILED → `BLOCKED(PARSE_FAILED)`；READY 且诊断标记低质量 → `BLOCKED(QUALITY_LOW)`；READY → `DONE` |
| ③ 要素确认 | 无快照 → `PENDING`；有提取 run 运行中 → `ACTIVE`；run FAILED → `BLOCKED(EXTRACTION_FAILED)`；快照 `READY_FOR_CONFIRMATION` → `WAITING_HUMAN`（业务负责人）；`CONFIRMED` → `DONE` |
| ④ 日程确认 | 无日程 → `PENDING`；`timeline_status=RUNNING` → `ACTIVE`；FAILED → `BLOCKED(TIMELINE_FAILED)`；有节点且存在未复核 → `WAITING_HUMAN`（业务负责人）；全部复核 → `DONE` |
| ⑤ 风险处置 | 无审查 run → `PENDING`；RUNNING → `ACTIVE`；FAILED → `BLOCKED(REVIEW_FAILED)`；有限报告 → `WAITING_HUMAN` 且带 `LIMITED` 标记；有 OPEN 发现 → `WAITING_HUMAN`（法务）；无 OPEN 且案件状态为 `PENDING_APPROVAL` → `WAITING_HUMAN`，`nextAction.type=NONE`，文案"审批功能建设中，请线下处理"；已批准 → `DONE` |
| ⑥ 签署 | 案件状态未到 `APPROVED` → `PENDING`；`APPROVED` / `READY_TO_SIGN` → `WAITING_HUMAN`（发起人，`nextAction.type=NONE`，文案"待线下签署并归档签署件"）；`SIGNED` → `DONE` |
| ⑦ 履约跟踪 | 非 `IN_FULFILLMENT` → `PENDING`；`IN_FULFILLMENT` → `WAITING_HUMAN`（业务负责人，"履约中，按台账跟踪"）；`expiry_date` 已过 → 同状态加"已逾期"标记 |
| ⑧ 归档续签 | `EXPIRED` / `TERMINATED` → `DONE`；其余 → `PENDING`（一期不判断义务终态） |

补充规则：

- 只推导到"第一个非 DONE 阶段"，其后一律 `PENDING`，避免出现"后面已完成、前面没完成"的矛盾展示。
- 早期状态映射：`DRAFT/MATERIAL_PENDING/INTAKE_PARSING/INTAKE_CONFIRMING` 落在 ①②；`NEEDS_REVISION` 落在 ⑤（并在下一步提示"按驳回意见修改或补证"）。
- 签署映射：`APPROVED` / `READY_TO_SIGN` 落在 ⑥（待签），`SIGNED` 落在 ⑥（完成）；⑥ 不提供任何签署动作，只提示线下处理。
- 若多份文档，只看 `document_type=MAIN` 且 `deleted=0` 的最新版本。
- ③ 只采用当前主合同的 `READY_FOR_CONFIRMATION` / `CONFIRMED` 快照，已确认优先、同状态取最新。非空待确认快照的字段全部为 `CONFIRMED` / `NOT_APPLICABLE` 时，只读推导③为 `DONE`；不修改快照状态。空待确认快照不算完成。
- `APPROVED` / `READY_TO_SIGN` / `SIGNED` / `IN_FULFILLMENT` / `EXPIRED` / `TERMINATED` 是明确的后期业务信号；即使历史案件缺新版快照，①~⑤仍只读推断已完成，避免倒退，不补写数据。
- ⑤ OPEN 发现仅统计最近一次 `COMPLETED` / `LIMITED` 的 `CONTRACT_REVIEW` 运行，与案件详情的风险集合一致，不累计历史报告。
- **已知缺陷（不在本期修）**：`PENDING_APPROVAL` 在现状下不可达——唯一写入点要求先处于 `NEEDS_REVISION`，而后者只能从 `PENDING_APPROVAL` 经 `/request-revision` 退回，形成循环。因此一期只展示"审批功能建设中"文案，不提供任何审批操作；修复属二期（见 [phase-2 §3 流程模型](./phase-2-approval.md)）。

### 5.1 ⑥⑦⑧ 不读义务表（一期决定）

一期**既不读** `contract_timeline_node`，**也不读** `contract_obligation`：

- 前者是"时间节点"，不是"义务"，读它等于把日程当履约结论；
- 后者目前几乎没数据（仅一处手写 INSERT），读它等于永远"没有义务"。

因此 ⑦⑧ 只看 `contract_case.status` 与 `expiry_date`，**不显示义务条数、完成率、逾期义务数**。真实义务跟踪由三期在第 1 层账本归一后接入；一期不提前造数。

## 6. 阻塞原因码

| 码 | 人话文案 | 谁能解 |
| --- | --- | --- |
| `PARSE_FAILED` | 合同解析失败，需要重试或换解析方式 | 发起人 / 管理员 |
| `QUALITY_LOW` | 解析质量低，结论只能作为参考，请核对并重新上传清晰合同；一期无人工放行 API | 业务负责人（发起人协助上传） |
| `EXTRACTION_FAILED` | 要素提取失败，可重试 | 发起人 |
| `TIMELINE_FAILED` | 履约日程生成失败，可重试 | 发起人 |
| `REVIEW_FAILED` | 风险审查失败，可重试 | 发起人 |
| `CONFIG_MISSING` | 当前合同类型没有配置审查规则，请联系管理员 | 管理员 |
| `AWAITING_APPROVAL` | 等待 {角色} 审批（**二期启用**；一期不产生此码） | 对应审批人 |

## 7. 接口契约（一期）

### 7.1 详情：`GET /api/workspace/contracts/{caseId}/workflow`

权限：与案件详情一致（`checkAccess`）。不新增权限。

```json
{
  "caseId": 42,
  "stage": "TIMELINE_CONFIRM",
  "stageIndex": 4,
  "stages": [
    { "key": "INTAKE",           "label": "受理建档", "state": "DONE",           "ownerRole": null,     "enteredAt": "2026-10-20T09:12:00" },
    { "key": "PARSE",            "label": "解析就绪", "state": "DONE",           "ownerRole": null,     "enteredAt": "2026-10-20T09:15:00" },
    { "key": "ELEMENT_CONFIRM",  "label": "要素确认", "state": "DONE",           "ownerRole": "业务负责人", "enteredAt": null },
    { "key": "TIMELINE_CONFIRM", "label": "日程确认", "state": "WAITING_HUMAN",  "ownerRole": "业务负责人", "enteredAt": null },
    { "key": "RISK_DISPOSAL",    "label": "风险处置", "state": "PENDING",        "ownerRole": "法务",    "enteredAt": null },
    { "key": "SIGNING",          "label": "签署",     "state": "PENDING",        "ownerRole": "发起人",  "enteredAt": null },
    { "key": "FULFILLMENT",      "label": "履约跟踪", "state": "PENDING",        "ownerRole": "业务负责人", "enteredAt": null },
    { "key": "ARCHIVE",          "label": "归档续签", "state": "PENDING",        "ownerRole": "业务负责人", "enteredAt": null }
  ],
  "currentDetail": {
    "summary": "已识别 12 个时间节点，3 个待确认",
    "counters": { "total": 12, "confirmed": 9, "pending": 3 }
  },
  "nextAction": {
    "type": "CONFIRM_TIMELINE",
    "label": "确认履约日程",
    "actorRole": "业务负责人",
    "actorName": "李四",
    "enabled": true
  },
  "blockedReason": null,
  "limited": false
}
```

字段约定：

- `stage` 与 `stages[].key` 使用固定枚举，前端不解析中文。
- `ownerRole` 一期只给角色（业务负责人 / 法务 / 审批人 / 发起人 / 管理员），**不落到具体人**（二期再接）。
- `nextAction.type` 限定枚举，前端按类型调用已有接口：`UPLOAD_DOCUMENT` / `RETRY_PARSE` / `CONFIRM_ELEMENTS` / `CONFIRM_TIMELINE` / `HANDLE_FINDINGS` / `UPLOAD_EVIDENCE` / `NONE`。`APPROVE` 属二期，一期不返回。
- `enteredAt` **可空**。一期只填 ① 案件创建时间、② 主合同上传时间（来源确定）；③~⑧ 一律 `null`。`null` 时前端不渲染"已停留"。真实阶段进入时间由二期状态机写入阶段事件后填充，字段与前端均无需改动。
- `blockedReason` 为 §6 的码；无阻塞为 `null`。
- 接口只读，不产生副作用；同一请求 2 次结果一致（除非期间有 run 状态变化）。

### 7.2 列表：`GET /api/workspace/contracts` 增补字段

`items[]` 增加 `stage`（8 段枚举）与 `stageOwnerRole`。实现要求：**一次批量查询**（按 caseIds 取文档/快照/日程/审查状态），不允许逐条查库。

列表只推导到"当前阶段"，不计算子步骤与阻塞原因。

## 8. 前端改造清单

| 文件 | 改动 |
| --- | --- |
| `agent-front/src/components/WorkflowStrip.vue` | 新增：8 段横向条，props `stages` `currentKey`，窄屏横向滚动 |
| `agent-front/src/components/WorkflowNextAction.vue` | 新增：下一步卡片，展示标签/责任人/按钮，emit `action` |
| `agent-front/src/views/ContractCaseView.vue` | 删除 `analysis-workflow-panel` 面板与 `analysisStages` 计算；接入两个新组件；「运行 Agent」收进「高级操作」；新增 `loadWorkflow()` 与轮询（有运行中任务时 5s，其余 30s） |
| `agent-front/src/views/ContractPortfolioView.vue` | 卡片增加阶段标签与责任人；筛选增加阶段维度 |
| `agent-front/src/api/index.js` | 新增 `getContractWorkflow(caseId)` |

交互约束：

- 「下一步」按钮点击后必须先调既有接口，成功后再刷新 workflow；失败原样提示后端错误。
- 运行中任务沿用现有 SSE 进度；workflow 只在阶段变化时刷新，避免整页抖动。
- 8 段在 1280px 以下改为横向滚动，不换行。

## 9. 后端改造清单

| 位置 | 改动 |
| --- | --- |
| 新增 `ContractWorkflowService` | 唯一推导实现：入参 caseId，返回 §7.1 结构 |
| `ContractWorkspaceController` | 新增 `GET /{caseId}/workflow`，沿用 `checkAccess` |
| `listCases` | 增补 `stage`、`stageOwnerRole`（批量推导） |
| 不改表、不改图、不改状态机 | 一期硬约束 |

性能：workflow 接口内部 ≤ 7 条查询或 1 条多表 join；同一 case 结果缓存 2 秒（避免页面轮询打库）。

## 10. 兼容与回滚

- 后端 `analysisWorkflow` 字段保留不动（避免其它调用方受影）。
- 前端删除旧面板后如需回滚，直接 revert 该组件改动，后端无需回滚。
- 阶段推导为"推断"，不是权威状态；页面上以 tooltip 注明「阶段由系统根据当前进度推断」，为二期状态机落地留出解释空间。

## 11. 验收清单

1. 新建合同未上传文件：停在 ①，显示"待上传合同"，按钮可上传。
2. 上传后解析中：② 显示进行中与进度；解析失败显示 `PARSE_FAILED` 与重试入口。
3. 解析完成未提取：③ 为当前阶段，按钮"提取合同要素"。
4. 快照待确认：③ 显示"3 个字段待确认"，按钮跳到确认区。
5. 日程待确认：④ 显示节点计数（总数/已确认/待确认）。
6. 审查完成且有 OPEN 发现：⑤ 显示"待法务处置 N 项"，不再显示"运行 Agent"。
7. 审查完成无 OPEN 发现且状态为 `PENDING_APPROVAL`（用 `updateCase` 直接构造）：⑤ 显示"审批功能建设中，请线下处理"，且**不出现**审批按钮。正常流程到不了该状态，本项以构造验证为准。
8. 已批准/已签署/履约中/已到期：⑥⑦⑧ 状态正确推进，且不出现"后面完成、前面未完成"的矛盾。其中"已批准""已签署"需构造（`PENDING_APPROVAL` → `APPROVED` → `SIGNED`），正常流程不可达。
9. 列表页：一屏 20 条合同，阶段与责任人正确，接口总耗时 < 300ms。
10. 1280 / 768 / 375 三个宽度下 8 段条不换行、不重叠、主按钮可点。
11. 「高级操作」默认折叠；展开后原有 6 个菜单任务与受理建档、履约核验两个上下文入口保持既有准入与行为，不新增任务类型。
12. 回归：现有确认、上传、运行任务、审批意见草案展示均不受影响。
13. ③~⑧ 不显示"已停留"（`enteredAt` 为 `null`）；① ② 显示准确时间，且与案件创建/上传时间一致。

## 12. 开发前需核对的字段（实现时确认，不阻塞设计）

| 待核对 | 用途 | 缺失时的兜底 |
| --- | --- | --- |
| ~~`contract_document` 是否已有质量标记字段~~ | 判定 `QUALITY_LOW` | **已验证存在**：`parse_quality`（`AgentWorkbenchSchemaInitializer` 中 `addColumnIfMissing`），无需兜底 |
| `contract_extraction_snapshot.status` 取值全集 | ③ 的状态判定 | 按 `READY_FOR_CONFIRMATION` / `CONFIRMED` 两值先实现 |
| `contract_timeline_node.review_status` 取值 | ④ 的"待确认"计数 | 无值时退化为"日程已生成即 DONE"，并在 tooltip 标注 |
| 是否存在"待审批人"配置 | 二期的审批人计算 | 一期不需要；⑤ 只显示"审批功能建设中" |

## 13. 二期接口预留（不实现，仅说明方向）

- `stage` 枚举保持 8 段不变，二期在 ⑤ 内细分（待处置 / 待审批 / 已批准），⑥ 由"只读提示"变为"可上传签署件"。
- `nextAction.actorName` 一期为 `null`，二期由审批人计算填充。
- 二期新增 `approvals[]`，不影响现有字段。
