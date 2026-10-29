# 一期实施情况（合同工作流视图）

> 日期：2026-10-29
> 对应设计：[phase-1-workflow-view.md](./phase-1-workflow-view.md) v1.2
> 对应分支：`fix/review-2026-10-29-batch1`
> 状态：**代码已写完，未编译、未做浏览器验收**

---

## 1. 一句话结论

8 阶段工作流视图的代码已完成，静态检查通过；但**本轮环境没有 JDK / Node / Docker，Java 未编译、前端未构建、13 条验收一条都未在浏览器里跑过**。下一步的第一件事是补齐环境后复跑验证，不要直接当成"已验收"。

## 2. 本轮环境限制（务必先看）

| 工具 | 状态 | 后果 |
| --- | --- | --- |
| JDK / Maven | **不存在**（`JAVA_HOME` 未设置，全盘未找到 `java.exe` / `javac.exe`） | `mvnw test`、`mvn compile` 未执行 |
| Node / npm | **不存在** | `npm run build`（agent-front / agent-admin）未执行 |
| Docker | **不存在** | MySQL / Redis / Elasticsearch 起不来，接口无法黑盒验证 |
| Python | 可用（3.12.10），已安装 requirements | `pytest` 已跑，结果见 §5 |

## 3. 已完成的工作

### 3.1 后端

| 文件 | 操作 | 内容 |
| --- | --- | --- |
| `agent-server/src/main/java/com/atlasmind/service/ContractWorkflowService.java` | **新增**（631 行） | 阶段推导唯一实现 |
| `agent-server/src/main/java/com/atlasmind/controller/ContractWorkspaceController.java` | 修改 | 新增 `GET /api/workspace/contracts/{caseId}/workflow`，沿用 `accessPolicy.checkAccess` |
| `agent-server/src/main/java/com/atlasmind/service/impl/ContractCaseServiceImpl.java` | 修改 | `listCases` 增补 `stage`/`stageLabel`/`stageOwnerRole`；5 处写操作后调用 `evict()` 失效缓存 |
| `agent-server/src/test/java/com/atlasmind/service/ContractWorkflowServiceTest.java` | **新增** | 17 个推导规则单测（纯函数，不打库） |

`ContractWorkflowService` 的关键实现点：

1. **8 阶段固定枚举**（`INTAKE / PARSE / ELEMENT_CONFIRM / TIMELINE_CONFIRM / RISK_DISPOSAL / SIGNING / FULFILLMENT / ARCHIVE`），与 README §4 一致。
2. **只推导到第一个非 `DONE` 阶段**，其后一律 `PENDING`，避免"后面完成、前面未完成"。
3. **`enteredAt` 只填 ①②**：① 案件创建时间、② 主合同上传时间；③~⑧ 返回 `null`（按 v1.2 定稿）。
4. **⑤ 审批降级为文案**：`PENDING_APPROVAL` → `WAITING_HUMAN` + `nextAction.type=NONE` + "审批功能建设中，请线下处理"，**不提供任何审批动作**。
5. **⑥⑦⑧ 不读义务表**：只看 `contract_case.status` 与 `expiry_date`，不显示义务条数/完成率/逾期数。
6. **已进入审批/签署/履约后的案件，⑤ 强制 `DONE`**：避免历史遗留 OPEN 发现把阶段条拉回⑤，破坏"首个非 DONE"的单调性。
7. **性能**：详情接口 2 秒进程内缓存（`ConcurrentHashMap`，上限 2000 条防内存泄漏）；列表 `attachStages` 用固定 5 条批量查询（案件 / 主文档 / 快照 / agent_run / 时间节点 / OPEN 发现），无 N+1。
8. **降级策略**：`contract_extraction_snapshot`、`contract_analysis_workflow` 等表缺失时（滚动升级期）按"无"处理，不阻断案件详情与列表。

### 3.2 前端

| 文件 | 操作 | 内容 |
| --- | --- | --- |
| `agent-front/src/components/WorkflowStrip.vue` | **新增**（98 行） | 8 段横向条，5 种状态视觉（DONE/ACTIVE/WAITING_HUMAN/BLOCKED/PENDING），窄屏横向滚动不换行 |
| `agent-front/src/components/WorkflowNextAction.vue` | **新增**（62 行） | 下一步卡片：标签 / 责任人 / 主按钮 / 阻塞原因 |
| `agent-front/src/views/ContractCaseView.vue` | 修改 | 删除旧「合同分析流程」面板；接入两个新组件；「运行 Agent」收进默认折叠的「高级操作（一般不需要）」；新增 `loadWorkflow()` 与 5s（运行中）/30s（空闲）轮询 |
| `agent-front/src/views/ContractPortfolioView.vue` | 修改 | 卡片增加阶段标签 + 责任人；筛选器增加「阶段」维度（状态筛选保留为二级） |
| `agent-front/src/api/index.js` | 修改 | 新增 `getContractWorkflow(caseId)` |

前端清理（死代码，避免"第二套推导"）：

- 删除 `analysisStages` computed（前端自算的 5 步分析进度）
- 删除 `workflowIsComplete`、`workflowStatusLabel`、`workflowStatusClass`
- 删除 `latestRiskReviewRun`、`extractionRunFailed`（旧面板专用）
- 删除 `.analysis-workflow-panel` / `-head` / `-stages` / `-foot` / `.workflow-complete-*` / `.workflow-stage-progress` 等死样式
- 「Agent 运行」Tab 内重复的 5 阶段条一并移除

### 3.3 「下一步」按钮的接线（一期不改业务逻辑）

| `nextAction.type` | 前端行为 |
| --- | --- |
| `UPLOAD_DOCUMENT` / `RETRY_PARSE` | 打开现有上传弹窗 |
| `CONFIRM_ELEMENTS` | 切到「合同要素」Tab |
| `CONFIRM_TIMELINE` | 切到「履约日程」Tab |
| `HANDLE_FINDINGS` | 切到「风险研判」Tab |
| `UPLOAD_EVIDENCE` | 切到「合同原文」Tab |
| `NONE` | 不渲染按钮 |

## 4. 硬约束自检

| 红线 | 结果 |
| --- | --- |
| 不改表结构、不改迁移 | ✅ 无 SQL / 迁移改动 |
| 不动四个任务图 | ✅ `tools/chat-assistant/backend/app/agent_runtime/graph/` 零改动 |
| 不改状态机（`PENDING_APPROVAL` 迁移条件、`updateCase` 的 status 写入） | ✅ 未改（只加了 `evict` 调用） |
| 阶段判断只有一处实现 | ✅ 仅 `ContractWorkflowService`；前端已删除自算逻辑 |
| 枚举只改 README §4 | ✅ 8 个 key 与 README §4.1 完全一致 |

## 5. 已验证的部分

### 5.1 Python 测试（与本期无关，用于确认没有踩坏其它模块）

```
python -m pytest -q
439 passed, 16 failed
```

失败的 16 条全部是既有问题，与本期无关：

- `tests/test_llm_service.py`（11 条）：`ValueError: LLM_API_KEY 未设置，请在 .env 中配置`
- `tests/test_task_spec_builder.py` 等（5 条）：golden 样本与当前实现漂移（`create_domain_tasks output drifted from the frozen sample`）

本期未修改任何 Python 文件（`git status` 可证），这些失败在改动前后一致。

### 5.2 静态检查

| 对象 | 检查项 | 结果 |
| --- | --- | --- |
| `ContractWorkflowService.java` | 括号平衡（`{}` 117/117、`()` 480/480）、公开方法存在性、依赖注入引用 | 通过 |
| `ContractCaseView.vue` | template 标签配对（0 处不匹配）、script 括号平衡、模板标识符均可解析 | 通过 |
| `ContractPortfolioView.vue` / 两个新组件 / `api/index.js` | 括号平衡、导入导出一致性 | 通过 |
| 全仓库 | 删除后无残留引用（`analysisStages`、`workflowIsComplete`、`analysis-workflow-*` 等 grep 为 0） | 通过 |

## 6. 未验证的部分（下次开工从这里继续）

### 6.1 必须先跑的三条命令

```bash
# 1) Java 编译 + 单测（需 JDK 17）
cd agent-server && ./mvnw test -B

# 2) 前端构建（需 Node 18+）
cd agent-front && npm ci && npm run build
cd agent-admin && npm ci && npm run build

# 3) Python 全量（需 .env 提供 LLM_API_KEY 才能全绿）
cd tools/chat-assistant/backend && python -m pytest
```

### 6.2 13 条验收清单的当前状态

| # | 验收项 | 状态 |
| --- | --- | --- |
| 1 | 新建合同未上传文件 → 停在①，可上传 | ⬜ 未验 |
| 2 | 解析中②显示进行中；失败显示 `PARSE_FAILED` + 重试 | ⬜ 未验 |
| 3 | 解析完成未提取 → ③ 为当前阶段，按钮"提取合同要素" | ⬜ 未验 |
| 4 | 快照待确认 → ③ 显示待确认字段数 | ⬜ 未验 |
| 5 | 日程待确认 → ④ 显示节点计数 | ⬜ 未验 |
| 6 | 有 OPEN 发现 → ⑤ 显示"待法务处置 N 项" | ⬜ 未验 |
| 7 | `PENDING_APPROVAL`（需用 `updateCase` 构造）→ ⑤ 显示"审批功能建设中"，无审批按钮 | ⬜ 未验 |
| 8 | 已批准/已签署/履约中/已到期（需构造）→ ⑥⑦⑧ 正确推进 | ⬜ 未验 |
| 9 | 列表页 20 条阶段与责任人正确，接口 < 300ms | ⬜ 未验 |
| 10 | 1280 / 768 / 375 三档宽度，8 段条不换行不重叠 | ⬜ 未验 |
| 11 | 「高级操作」默认折叠；展开后 8 个任务行为不变 | ⬜ 未验 |
| 12 | 回归：确认、上传、运行任务、审批意见草案展示不受影响 | ⬜ 未验 |
| 13 | ③~⑧ 不显示"已停留"；①② 显示准确时间 | ⬜ 未验 |

> 验收 7、8 按 v1.2 定稿要求"以构造验证为准"：`PENDING_APPROVAL` 正常流程不可达，需用 `PUT /api/workspace/contracts/{id}` 直接写 status 构造。

### 6.3 编译阶段最可能先暴露的三个点

1. `ContractWorkflowService` 用了 `record Cached(...)`，需 Java 17（项目已是 17，正常）。
2. `ContractCaseServiceImpl` 构造器由 Lombok `@RequiredArgsConstructor` 生成，新增 `final` 字段后需确认没有手写构造器冲突（当前文件无手写构造器）。
3. 前端 `WorkflowStrip.vue` 用 `stage.state.toLowerCase()`，若后端返回 `null` 会报错——当前后端始终返回 5 种状态字符串之一，但建议联调时确认。

## 7. 与设计文档的差异

| 设计 | 实现 | 原因 |
| --- | --- | --- |
| §7.1 `stageIndex` 为 1~8 | 一致 | — |
| §7.1 `ownerRole` 只有 5 种角色 | 一致（发起人/业务负责人/法务/审批人/管理员） | — |
| §9 "workflow 接口内部 ≤ 7 条查询" | 6 条 | 批量列表另有 6 条；详情 6 条 |
| §9 "同一 case 结果缓存 2 秒" | 进程内 2 秒 | 未用 Redis，避免新增缓存 key 与序列化依赖 |
| §8 "运行中任务 5s，其余 30s" | 一致 | 用 `workflowPollTicks % 6` 实现 |

## 8. 交付时要说的话

1. **做了什么**：phase-1 §3~§9 的后端推导 + 两个前端组件 + 详情页替换 + 列表页增补。
2. **哪条验收没通过**：13 条全部未执行（不是失败，是环境不具备）。
3. **遇到 §6 的问题**：无。`SIGNED` 归属与⑥⑦⑧ 读表两个问题已在 v1.3 定案，本轮未做任何越权决策。

## 9. 下次开工检查项

- [ ] 补齐 JDK 17 + Node 18 + Docker 后，跑 §6.1 三条命令
- [ ] 修掉编译错误（如有），确保 `ContractWorkflowServiceTest` 17 条全绿
- [ ] 起四个服务，逐条过 §6.2 的 13 条
- [ ] 三档宽度截图（1280 / 768 / 375）
- [ ] 确认列表接口 P95 < 300ms
- [ ] 补记本轮未覆盖的分支（如 `QUALITY_LOW` 在真实低质量 PDF 上的表现）
