# 交接须知（给接手的人或 Agent）

> 目的：让一个**没有参与过讨论**的人或 Agent，能独立完成一期，而不需要猜。
> 读完本文再读 [phase-1-workflow-view.md](./phase-1-workflow-view.md)。
> **不要读 phase-2 / phase-3** —— 它们是草案，里面的"建议默认值"是留给人拍板的，不是给你的施工图。

---

## 1. 只读三份就够

1. 本文件（怎么跑、怎么验、红线在哪）
2. [README.md](./README.md) §4 —— 阶段与状态的**唯一枚举真源**
3. [phase-1-workflow-view.md](./phase-1-workflow-view.md) —— 一期施工图

业务背景看 [../prd-contract-case-lifecycle.md](../prd-contract-case-lifecycle.md)，但**不要**据此扩大范围。

## 2. 怎么跑起来

### 2.1 一键（Windows）

```bat
start.bat
```

它按顺序拉起四个进程：Java 18080 → 管理端 15173 → 用户端 15174 → Python 18088。

### 2.2 手动

| 服务 | 命令 | 端口 |
| --- | --- | --- |
| 依赖 | `docker compose up -d mysql redis elasticsearch` | 3306 / 6379 / 9200 |
| Java 后端 | `cd agent-server && mvnw.cmd spring-boot:run` | 18080 |
| Python AI | `cd tools/chat-assistant/backend && python run.py` | 18088 |
| 用户端 | `cd agent-front && npm install && npm run dev` | 15174 |
| 管理端 | `cd agent-admin && npm install && npm run dev` | 15173 |

健康检查：`http://localhost:18080/actuator/health`、`http://localhost:18088/docs`。

### 2.3 数据库

- 基础表：`agent-server/sql/init.sql`
- 增量迁移：`tools/chat-assistant/backend/migrations/V*.sql`（当前 V001–V040），**Python 服务启动时自动按 `schema_migrations` 应用未执行的迁移**。
- **不要手改已应用的迁移文件**；要加字段就新建下一个版本号。
- Java 启动期有兼容补列逻辑（`AgentWorkbenchSchemaInitializer`），用于滚动升级。

### 2.4 环境变量

Python 服务读 `tools/chat-assistant/backend/.env`（模板见 README §环境变量）。**密钥不要提交**。
没有真实 LLM Key 时，AI 能力会降级——见 §3.3。

## 3. 怎么验

### 3.1 自动化

| 对象 | 命令 |
| --- | --- |
| Java | `cd agent-server && mvn test -B` |
| 用户端构建 | `cd agent-front && npm ci && npm run build` |
| 管理端构建 | `cd agent-admin && npm ci && npm run build` |
| Python | `cd tools/chat-assistant/backend && python -m pip install -r requirements.txt pytest && python -m pytest` |
| 容器 | `docker compose config --quiet` |

CI 就是这几条（`.github/workflows/ci.yml`），本地跑通即等于过了 CI 的构建关。

### 3.2 手工验收

按 phase-1 §11 的 12 条，用真实浏览器点。三个宽度都要看：1280 / 768 / 375。

### 3.3 降级状态要分清

LLM、Embedding、Reranker 或 Elasticsearch 任一不可用时，系统会记录 fallback 并给结果打上"范围受限"（LIMITED）。

**验收时不要把降级结果当正常结果**：如果本地没有 Key，就不要用"AI 没出结论"来判定功能失败，先确认是基础设施降级还是逻辑错误。

## 4. 读代码的入口

| 想改什么 | 先看 |
| --- | --- |
| 工作流条 / 下一步卡片 | `agent-front/src/views/ContractCaseView.vue`（搜索 `analysis-workflow-panel`、`analysisStages`） |
| 列表页阶段标签 | `agent-front/src/views/ContractPortfolioView.vue` |
| 接口 | `agent-server/src/main/java/com/atlasmind/controller/ContractWorkspaceController.java` |
| 案件状态与数据 | `agent-server/src/main/java/com/atlasmind/service/impl/ContractCaseServiceImpl.java` |
| 四个任务图 | `tools/chat-assistant/backend/app/agent_runtime/graph/` |

## 5. 红线（违反即返工）

1. **不改表结构、不改迁移**。一期是只读展示，任何"顺手加个字段"都不行。
2. **不动四个任务图**（`contract_review` / `timeline_extraction` / `contract_extraction` / `fulfillment_check`）。
3. **不改状态机**：不要动 `PENDING_APPROVAL` 的迁移条件，不要动 `updateCase` 对 `status` 的写入。这些是二期的事。
4. **阶段判断只能有一处实现**：新建的 `ContractWorkflowService`。不许在 Controller、前端、SQL 里各写一遍。
5. **枚举只改 README §4**，不许在各期文件里另起一套 key。

## 6. 必须停下来问人的事（不要自行决定）

| 问题 | 为什么不能自己定 |
| --- | --- |
| ⑥ 履约 / ⑦ 归档 读哪张表（`contract_timeline_node` 还是 `contract_obligation`） | 两套数据现在互不相通，选错就等于给三期埋雷 |
| `READY_TO_SIGN` / `SIGNED` 归到哪个阶段 | 7 阶段里没有"签署"这一步，属于产品定义问题 |
| 二期三问：退回回到哪一步 / 审批记录粒度 / 谁能改派 | 业务决策，文档里只是"建议默认值" |

### 6.1 状态 → 阶段的参考映射（**待产品确认，不要当定论**）

| `contract_case.status` | 建议阶段 | 说明 |
| --- | --- | --- |
| `DRAFT` | ① 受理建档 | 未上传合同 |
| `MATERIAL_PENDING` | ① 受理建档 | 缺材料 |
| `INTAKE_PARSING` | ② 解析就绪 | 解析中 |
| `INTAKE_CONFIRMING` | ② 解析就绪 | 待确认首次识别结果 |
| `READY_FOR_REVIEW` | ⑤ 风险处置 | 前四步已就绪，等审查 |
| `REVIEWING` | ⑤ 风险处置 | 审查中 |
| `NEEDS_REVISION` | ⑤ 风险处置 | 被退回 |
| `PENDING_APPROVAL` | ⑤ 风险处置 | 等审批 |
| `APPROVED` | ⑤ 风险处置（DONE）→ ⑥ | 已批准 |
| `READY_TO_SIGN` | ⑤ 风险处置（收尾） | **归属待确认** |
| `SIGNED` | ⑤ 风险处置（收尾）→ ⑥ | **归属待确认** |
| `IN_FULFILLMENT` | ⑥ 履约跟踪 | 履约中 |
| `EXPIRED` / `TERMINATED` | ⑦ 归档续签 | 已到期 / 已终止 |

> `APPROVED` 之后 ⑤ 应为 `DONE`、⑥ 为 `WAITING_HUMAN`；`SIGNED` 同理。

## 7. 已知的坑

1. **中文文件用 `read` 工具读，不要用 `Get-Content`** —— PowerShell 控制台会乱码，看起来像文件坏了。
2. **文档里的行号会漂**。用锚点搜索（`analysis-workflow-panel`、`analysisStages`、`nextTaskType`、`canStart`），不要硬信行号。
3. **前端改完要重新构建**（`npm run dev` 热更新，`npm run build` 才进产物）；后端改完要重启 18080。
4. **`approvalMemo` 是 AI 生成的草案**，页面自己标了"不代表审批已完成"。不要把它当审批结果，也不要因为它存在就以为审批功能已实现。
5. **docs 下有两套"六层"**：技术架构六层 ≠ 改造层次 0~6，见 README §9。
6. **`contract_obligation` 目前几乎没数据**（只有一处手写 INSERT），看到履约 KPI 是 0 不是 bug，是已知缺口。

## 8. 交付前自检

- [ ] `mvn test` / `npm run build` ×2 / `pytest` 全绿
- [ ] 12 条验收逐条过，三个宽度都看过
- [ ] 没有新增表、没有改迁移、没有动任务图
- [ ] 阶段判断只有一处实现，前端没有第二套推导逻辑
- [ ] 枚举与 README §4 完全一致
- [ ] 删掉旧「合同分析流程」面板后，页面没有残留引用与死样式
- [ ] 文档里没写"已完成"却实际没做的项

## 9. 交付时说什么

交付说明只写三件事：

1. 做了什么（对应 phase-1 的哪几节）
2. 哪条验收没通过 / 哪条没环境验
3. 遇到 §6 里哪个问题，停下来问了还是绕过了（如果绕过了，说明绕法）

不要写"优化了用户体验"这类无法验收的话。
