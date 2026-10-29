# 一期实施情况（合同工作流视图）

## 历史实施记录（2026-10-29，原记录未记具体时分）

> 以下 §1~§9 保留原始记录及当时结论；本次续实施结果见文末带时间的追加节，不以最新环境倒改历史记录。

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

---

## 本次续实施与验收（2026-10-29 19:23，Asia/Shanghai）

### 当前完成情况

一期只读工作流的未完成实现、编译、构建、数据联调和主要浏览器交互已补齐。结论为**一期实现完成，本地分层验收通过；完整外部 AI 链路与全部任务端到端回归尚未全覆盖**。下面逐项区分真实操作、构造数据和自动化验证，不把构造状态或 LIMITED 结果当作正常 AI 全流程完成。

本次以当前 `master` 的 `1438742` 为基线继续实施，未创建提交。历史段落中的环境限制、439/16 测试结论、5/6 条 SQL 数量及未验清单均为当时记录，当前结果以本追加节为准。

### 本次补齐与修复

1. **编译阻断**：修正工作流 `Stage` 构造参数遗漏；修正评测控制器 `featuresJson` 二次赋值后被 lambda 捕获的非 final 编译错误，保持原有业务含义。
2. **详情与列表同一口径**：统一使用批量信号装载，固定 7 条 SQL（案件、主文档、快照与字段计数、运行、分析工作流、日程计数、当前风险计数），无逐案件查库；列表补齐 `timeline_status`，不存在或已删除案件不建立信号。
3. **当前版本与字段确认**：只取最新未删除 MAIN 文档及其有效快照，快照选择与案件详情一致（已确认优先、同状态取最新）。真实统计字段总数、已确认、待确认；非空 `READY_FOR_CONFIRMATION` 快照全部字段复核后只读推导③完成，不要求既有接口额外更新快照状态；空未确认快照不误判完成。
4. **风险与历史数据**：只计最近有效 `CONTRACT_REVIEW` 运行的 OPEN 发现，避免旧报告风险残留污染当前阶段；对于已批准、待签、已签、履约、到期、终止案件，承认后期业务状态，避免历史缺新版快照使阶段倒退。
5. **恢复入口接通**：无结果或失败时，要素、日程、审查主按钮调用既有任务；已有结果时跳到对应复核区。低质量提供“上传清晰合同”，不宣称存在一期人工放行 API。任务运行时禁止重复发起任务，上传入口仍可打开，提交时防重复。
6. **上传表单补全**：原 `showUpload` / `doUpload` 存在但缺弹窗模板，现补齐主合同、附件、报价、资质、履约证据，以及文件/文字两种方式；复用既有接口。使用 Naive UI 弹窗并适配焦点管理，文字上传已实际成功。
7. **确认后即时更新**：字段、事实、日程复核后失效工作流缓存；前端字段、日程、风险处理、基准日保存后刷新工作流。最后一个待确认项处理后直接推进。
8. **页面反馈**：无按钮场景展示后端说明（含审批建设中），不误显示“暂无待办”；主按钮具备主题色、44px 高度、焦点与禁用状态；列表空结果保留筛选器、可清空，补充加载/错误/重试反馈，并防止旧请求覆盖新结果。

### 自动化、接口与运行环境

| 验证 | 本次结果与范围 |
| --- | --- |
| Java `mvnw.cmd test -B` | **71 tests，0 failures，0 errors，0 skipped**；含原有 17 条推导测试、新增 10 条 H2 真实 SQL 集成测试 |
| 用户端 `npm run build` | **通过**（最后一次上传入口修正后已重构建）；仅有大于 500KB 的 chunk 提示 |
| 管理端 `npm run build` | **通过**；有 chunk 体积提示 |
| Python `python -m pytest -q` | **455 passed，1 warning**；本次未修改 Python 业务/任务图代码，历史 16 条失败未在当前环境复现 |
| `docker compose config --quiet` | **通过**；仅说明配置有效，不代表所有依赖均已运行 |
| 四服务启动 | Java 18080、Python 18088、用户端 15174、管理端 15173 均启动成功；MySQL/Redis 可用，Elasticsearch 9200 未启动 |
| 真实 MySQL/API | 20 个定向合成案件，详情/列表阶段一致；复核缓存失效、当前风险口径、审批无动作、时间字段与访问控制通过 |
| 权限 | 其他临时用户访问案件工作流 **404**；匿名访问 **401** |
| 列表性能 | 实际可见 25 条（含 20 条验收案件），30 次串行请求，**P95 53.74ms，最大 81.04ms**；本机局部样本，非负载测试 |

新增 H2 用例覆盖：详情/列表的日程失败一致、替换主文档不复用旧快照、字段确认计数及推进、空快照、解析时间与无文档 limited、历史后期状态、失败动作恢复、低质量重传、风险审查开始/重试、历史 OPEN 不污染当前报告。最后一项先验证旧查询失败，再修正并跑全量通过。

### 13 条验收的当前证据

| # | 当前结果 | 证据与边界 |
| --- | --- | --- |
| 1 | 通过 | API 新建无主合同停①；浏览器打开上传弹窗，文字提交成功，真实解析后进入③ |
| 2 | 分层通过 | API 构造解析中/失败，自动化覆盖 `PARSE_FAILED` 与上传时间；真实 PDF 经上传、解析得到 `READY/LOW`，页面停②并显示重传入口。没有用真实损坏 PDF 制造解析异常 |
| 3 | 通过 | API 覆盖未提取停③与提取动作；浏览器提取失败样本点“重新提取”后创建既有任务、转为进行中 |
| 4 | 通过 | 3 个合成字段真实复核：浏览器 3→2→1，最后确认后立即推进⑤；API 与 H2 覆盖全部复核后 DONE，无需改快照状态 |
| 5 | 通过 | 3 个合成日程节点在浏览器逐个确认，3→2→1→⑤；API 核对计数及缓存失效 |
| 6 | 通过 | 当前有效审查绑定 2 个合成 OPEN 风险，页面显示“待法务处置 2 项”，主按钮定位风险区；H2 确认旧报告 OPEN 不污染计数 |
| 7 | 构造通过 | 用既有更新接口构造 `PENDING_APPROVAL`，workflow 为⑤、NONE、建设中文案，无审批动作；不改变不可达的状态机问题 |
| 8 | 构造通过 | APPROVED、READY_TO_SIGN、SIGNED、IN_FULFILLMENT、EXPIRED、TERMINATED 的 API 与 H2 阶段验证；历史缺快照也不倒退；⑥⑦⑧不造履约指标 |
| 9 | 通过 | 20 个构造案件详情/列表阶段一致；25 条实际列表 30 次 P95 53.74ms；浏览器阶段/状态交叉筛选无结果仍可清空恢复 |
| 10 | 通过 | 1280/768/375 三档实测，8 段同一行，窄屏局部横滚，主按钮可见可点；截图见下方 |
| 11 | 部分回归，范围已澄清 | 默认折叠已见，展开原有 6 个菜单及说明，版本复核在不满足条件时禁用。另 2 个任务位于受理/履约上下文，未逐个真实 AI 端到端执行；不是缺少两个菜单按钮 |
| 12 | 部分回归 | 浏览器完成文字上传、字段/日程确认、风险跳转、失败任务重试创建、审批草案展示与“非审批结果”提示；未逐个完成所有任务及所有文件类型的真实 AI 链路 |
| 13 | 通过 | 20 个 API 结果③~⑧ enteredAt 均 null；浏览器③无进入时间，②显示真实 PDF 上传时间；①创建、②上传与数据库/API来源核对一致 |

### 三档宽度截图

- [1280px 案件工作流](./evidence/phase1-1280.jpg)
- [768px 案件工作流](./evidence/phase1-768.jpg)
- [375px 案件工作流与主按钮](./evidence/phase1-375.jpg)
- [真实 LOW 解析后的重传弹窗（375px）](./evidence/phase1-low-quality-upload-375.jpg)

实测阶段条可视/内容宽度：1280 下 963/963，768 下 625/874，375 下 268/874；8 段不换行，溢出发生在阶段条内部。截图使用本轮合成案件，不含业务合同。

### 保留边界与后续复验

- 不新增表/迁移，不改四个任务图，不改 `updateCase` 的 status 写入或 `PENDING_APPROVAL` 迁移条件；审批/签署继续仅线下提示，审批意见仍为草案。
- ⑥⑦⑧只依赖案件状态与到期日，不读取义务表或输出义务完成率；阶段判断仅后端一处实现。
- 本地 Elasticsearch 未启动，AI 结果可能因检索依赖而 LIMITED；未声称正常模式 AI 全链路验收完成。需在完整依赖环境补跑所有任务端到端，尤其受理与履约上下文、真实版本复核、所有上传文件类型；不将此扩展为二三期实施。
- 验收仅使用本轮专属 20 个案件、2 个临时账号及合成 PDF；交付前定向清理这些临时数据和测试上传文件，保留测试源码与截图，不清空共享表或已有业务数据。本轮启动的四服务在验收后停止。

### 收尾完成（2026-10-29 19:29，Asia/Shanghai）

已定向清理本轮 20 个验收案件、2 个临时账号及其关联记录、2 份合成 PDF 和临时验收脚本；回查验收案件、账号、任务均为 0。临时账号已退出登录，本轮四服务已停止，四个验收端口均无监听。保留回归测试与四张截图，未清空共享表或删除已有业务文件。
