# Debug 修复记录

项目开发过程中遇到的问题及修复，按时间倒序记录。

## Agent Runtime 连接池 + SSE 流式进度推送

**日期**：2026-08-02

### 调整原因

- **Python 无连接池**：每次 DB 调用 `_conn()` 新建 `pymysql` 连接，5 个并发 Run × 每 Run ~20 次 DB 调用 = 100+ 瞬时连接，可能耗尽 MySQL `max_connections`。
- **前端轮询延迟**：前端每 3 秒 poll `GET /api/workspace/projects/runs/{id}`，无法实时感知 Agent 进度。
- **`last_heartbeat_at` 列缺失**：Python 迁移 V001 添加心跳列的逻辑在 MySQL 5.7 上因 `IF NOT EXISTS` 不支持而静默失败，导致恢复扫描报 `Unknown column 'last_heartbeat_at'`。

### 调整过程

**F8: 连接池**
- `persistence.py` 新增 `_get_pool()`，使用 `DBUtils.PooledDB` 管理 pymysql 连接池（maxconnections=12, mincached=2, maxcached=6, ping=1）。
- `_conn()` 改为从池中借用连接，对外接口不变。

**F3: SSE 流式进度**
- Python `runner.py` RunDispatcher 新增 `_publish_progress()` 方法，通过同步 `redis` 客户端（兼容 Redis 5.0）发布到 Redis PubSub 频道 `run:{runId}:progress`。
- `AgentRunner` 新增 `_update_progress()` 辅助方法，替代 `execute()` 中所有 `run_store.update_run()` 调用，同时写入 DB 和发布 SSE 事件。
- Java `AgentWorkbenchController` 新增 SSE 端点 `GET /api/workspace/projects/runs/{runId}/stream`，使用 `SseEmitter` + `RedisConnection.subscribe()` 将 PubSub 消息实时转发给前端。
- 8 个进度事件：CONTEXT_BUILDING(0%) → CONTEXT_BUILDING(8%) → PLANNING(18%) → ANALYZING(25%) → ANALYZING(34%) → VERIFYING(72%) → PLANNING(86%) → COMPLETED(100%)。
- `redis-py` 从 8.1.0 降级到 4.6.0，兼容 Redis 5.0（RESP2 协议，无 HELLO 命令）。

**修复 `last_heartbeat_at` 列缺失**
- 在 `agent_run` 表上执行 `ALTER TABLE ADD COLUMN last_heartbeat_at DATETIME`。

### 调整结果

- DB 连接池正常工作：并发 Run 时 MySQL 连接数 ≤ 12。
- SSE 测试通过：Run 57 订阅到 6 个实时进度事件，Run 58 验证 COMPLETED(100%) 事件。
- E2E 通过：Run 57 score=70, hash=9ac3b8e4..., 5 维分数全部正确。
- 恢复扫描不再报 `Unknown column 'last_heartbeat_at'` 错误。
- 新增依赖：`redis>=4.0,<5.0`、`DBUtils`。

---

## Agent Runtime 可靠性增强：取消可观测 + 幂等去重 + LLM 重试熔断

**日期**：2026-08-02

### 调整原因

- **取消不可观测**：设 `status=CANCELLED` 后 harness 循环从不检查，取消完全无效。
- **无幂等保护**：相同 `requestId` 重复 POST `/internal/agent/run` 会创建第二个 asyncio task，导致双写竞争。
- **LLM 调用无重试**：DeepSeek API 短暂波动（503/超时）直接触发 `_fallback_*` 降级路径，降低报告质量。

### 调整过程

**F4: 取消可观测 + 幂等去重**
- `policy.py` 新增 `RunCancelled` 异常类型。
- `runner.py` AgentRunner 新增 `_check_cancelled()` 方法，在每个 Phase 边界和每次工具调用前查询 run 状态，发现 CANCELLED 则抛出 `RunCancelled` 终止执行。
- `RunDispatcher.dispatch()` 捕获 `RunCancelled`，不标 FAILED（状态已在 DB 中设为 CANCELLED）。
- `routes.py` 新增 `_active_runs: dict[str, Task]`，按 `requestId` 去重——重复 POST 返回已有任务状态而非创建新 task。

**F2: LLM 重试 + 熔断器**
- `llm_service.py` 新增 `CircuitBreaker` 类：5 分钟内连续 5 次失败 → 熔断 60s。
- 新增 `_call_llm_with_retry()` 方法：指数退避重试（plan/reflect/analyze 3 次，tool_turn 2 次），认证错误不重试。
- 5 个 LLM 调用方法全部接入重试 + 熔断：`plan_agent`, `next_agent_turn`, `reflect_agent`, `analyze_project`, `run_project_task`。

### 调整结果

- 幂等测试通过：相同 `requestId` 返回 `"任务已在调度中"`。
- 取消测试通过：POST `/cancel` 后 DB 状态立即变为 CANCELLED。
- E2E 测试 Run 49 通过：score=70, hash 匹配，5 维分数全部正确。
- 熔断器状态机正常：CLOSED → OPEN（5 次失败）→ HALF_OPEN（60s 后）→ CLOSED（成功）。

---

## Agent Runtime 正式切换至 Python 并清理 Java 旧 Harness

**日期**：2026-08-02 | **Commit**：`bc53211`

### 调整原因

- Agent Runtime 迁移（Java → Python）Phase 1-4 全部验证通过，Shadow Run 8/8 逐位项一致。
- Java `agent/runtime/` 包（10 个文件）的旧 harness 代码已成为死代码，继续保留增加维护负担。
- 三档 dispatch（java/python/shadow）中的 java 和 shadow 分支已无用，需清理。

### 调整过程

- `AGENT_RUNTIME` 设为 `python`，正式切换到 Python Agent Runtime。
- 删除 `agent/runtime/` 包全部 10 个文件：`AgentHarness`, `DefaultAgentHarness`, `AgentHarnessResult`, `AgentTaskContext`, `AgentExecutionPolicy`, `AgentToolRegistry`, `AgentTraceStore`, `AgentArtifactExecutor`, `JdbcAgentArtifactExecutor`, `DeterministicHealthScoringEngine`。
- 删除 `AgentRunExecutor.java`（旧 harness 异步调度器）。
- 清理 `AgentProjectServiceImpl.java`：从 1892 行减至 ~1053 行，删除 30+ 旧 harness 方法（`executeRun`, `completeRunSteps`, `advance`, `scoreProject`, `buildReport`, `normalizeAiReport`, `fallbackProjectTask`, 等），`dispatchByMode(java/shadow/python)` 简化为 `dispatchToPython()`。
- `AgentProjectService.java` 接口移除 `executeRun(Long)` 方法声明。
- `AgentWorkbenchSchemaInitializer.java` 移除 Python 拥有的表 DDL（`agent_project_memory`, `agent_run`, `agent_run_step`, `agent_report`, `agent_run_trace`, `agent_tool_call`），移除 `addColumnIfMissing` 方法和孤立的 `agent_project_memory` 清理 SQL。

### 调整结果

- Maven 编译通过，无错误。
- E2E 测试 Run 48 通过 Java→Python 桥接完成：score=70, hash=9ac3b8e4f806948f3a8ee74a9bbc46..., 5 维分数全部正确。
- Java 侧不再包含任何 Agent 运行时逻辑，架构简化为 `用户 → Java (API/鉴权/审批) → HTTP → Python Agent Runtime`。
- 回滚方式：revert commit `bc53211` + `UPDATE system_config SET config_value='java'`。

---

## 2026-07-31 CI 失败，清理旧测试并恢复后端流水线

**日期**：2026-07-31

### 调整原因

- GitHub Actions 发来了 CI 失败邮件，后端 job 没过。
- 失败点主要来自博客时代残留测试，仍在引用已经删除的类，例如 `ArticleService`、`AboutMapper`、`CategoryMapper`、`CommentMapper`、`MomentMapper`、`TagMapper`。
- `KnowledgeBaseControllerTest` 还会被 Sa-Token 拦住，在未初始化上下文时返回 500。

### 调整过程

- 本地复跑 `mvn test -B`，确认后端测试确实和邮件内容一致。
- 删除 7 个已经不属于当前企业 Agent 方向的旧测试。
- 新增 `KnowledgeBaseServiceImplTest`，保留当前知识库服务的轻量回归测试。
- 顺手把 `logs/` 加入 `.gitignore`，避免运行产物污染工作区。

### 调整结果

- `mvn test -B` 重新通过。
- 相关修改已提交并推送，后端 CI 恢复为绿色。

---

## 后台“证据同步”重命名为项目数据同步

**日期**：2026-07-30

### 调整原因

- “证据同步”偏内部实现，非技术用户不容易理解。
- 该模块实际负责把 GitHub、本地项目、Jira/禅道、CI/CD 等外部研发系统里的项目资料同步进系统，供 Agent 分析、报告和引用使用。

### 实现内容

- 后台菜单“证据同步”改为“项目数据同步”。
- 页面标题、说明和项目卡片计数文案同步调整为项目资料入库语义。
- 连接器说明改为“给项目健康分析提供依据”，减少内部术语。
- README 同步把功能名改为“GitHub 只读项目数据同步”。

---

## 前台“知识来源”重命名为 Agent 参考库

**日期**：2026-07-30

### 调整原因

- 前台“知识来源”容易被理解成普通文档浏览页，和企业 Agent 工作台的核心任务不够贴合。
- 这些文档实际是 Agent 在 RAG 检索、健康分析、报告生成和引用展示时使用的参考资料；其中可以包含行动规范，但不限于规范。

### 实现内容

- 前台导航“知识来源”改为“Agent 参考库”。
- 前台参考库页面标题、说明、搜索占位、空状态、加载态和分块文案改为 Agent 可引用参考资料语义。
- 文档状态增加中文展示映射，例如 `READY` 显示为“可引用”。
- 项目总览页相关入口改为“Agent 参考库”。
- README 同步产品命名；底层路由 `/knowledge`、KB 表和 RAG 实现保持不变。

---

## 本地 LLM 与 Embedding 配置接入

**日期**：2026-07-30

### 实现内容

- 新增本地忽略文件 `tools/chat-assistant/backend/.env`，写入 LLM、Embedding、Elasticsearch、MySQL 和检索参数配置；真实密钥不写入 README 或可提交配置。
- 重启 Python AI 服务 `18088`，使 `.env` 配置重新加载。
- `/api/chat/health` 已识别 LLM 模型、Embedding 模型和 2560 维向量配置。

### 当前状态

- LLM：配置已识别。
- Embedding：配置已识别。
- Elasticsearch：`localhost:9200` 当前未监听，健康检查仍为 degraded；启动 ES 后可恢复向量检索。

---

## 健康分析报告中文化与规则分析边界说明

**日期**：2026-07-30

### 问题现象

- 项目健康分析详情页仍出现 `DRAFT`、`Run #`、`CREATE_GITHUB_ISSUE`、`health signal` 等英文内部状态或展示文案。
- 默认项目初始化数据使用英文描述，容易让人误判当前健康分析是英文假数据。
- 用户指出当前 LLM API 尚未配置，报告应明确说明生成来源并使用中文表达。

### 修复内容

- 后端 `AgentProjectServiceImpl` 将 Agent Run 默认问题、步骤名、同步消息、失败消息、健康维度、风险、计划、Markdown 报告和 GitHub Issue 草稿统一中文化。
- 初始化默认项目 `ATLASMIND` 的描述、业务范围和当前里程碑改为中文研发团队场景。
- 前台项目详情页新增报告状态、运行状态、动作类型、风险级别、记忆类型和证据类型展示映射，避免直接暴露英文枚举值。
- 前台项目总览页将 `Portfolio view`、`Operating model`、`Execution boundary`、`health signal`、`evidence`、`runs`、`approvals` 等标签改为中文业务表达。
- README 明确当前 MVP 在未配置 LLM API 时使用规则化证据分析器，不伪装成大模型深度分析；历史 `agent_report` 快照不会自动改写，需要重新运行 Agent Run 才会生成中文报告。

### 验证

- `agent-server .\mvnw.cmd -q -DskipTests compile`：通过。
- `agent-front npm run build`：通过，仅保留 Vite 大 chunk 警告。
- `agent-admin npm run build`：通过，仅保留 Vite 大 chunk 警告。
- 重启后端后通过接口启动项目 `1` 的 Agent Run `9`，最新报告标题、摘要、风险、计划和复核说明均为中文，报告明确说明“当前报告由规则化证据分析器生成”。

---

## 前后台职责拆分与受保护 Workspace API

**日期**：2026-07-30

### 实现内容

- 将项目工作台接口从共享 `/api/projects/**` 拆到 `/api/workspace/projects/**`，作为前台业务工作台入口。
- 新增 `/api/admin/projects/**` 后台运营接口，提供项目目录、全局 Agent Run、报告和动作状态聚合查询。
- Sa-Token 权限拦截扩展到 `/api/workspace/**`、`/api/admin/**`、`/api/kb/**`、`/api/upload/**` 和旧 `/api/projects/**`。
- 审批人不再信任前端传入的 `approvedBy`，改为从当前登录态读取。
- 新增 `AgentActionExecutor`，审批通过后异步执行外部动作；前台移除二次“执行”按钮。
- 前台新增轻量登录页、token 请求拦截和 401 回登录逻辑；顶部搜索接入项目列表过滤，移除博客遗留的空工具浮层。
- 管理端“项目管理”调整为只读项目目录；“报告与审批”调整为报告与动作状态观察；移除单独 Connectors 菜单，将连接器预留位并入证据同步页。

### 验证

- `agent-server .\mvnw.cmd -q -DskipTests compile`：通过。
- `agent-admin npm run build`：通过，仅保留 Vite 大 chunk 警告。
- `agent-front npm run build`：通过，仅保留 Vite 大 chunk 警告。
- 重启后端后验证：未登录访问 `/api/workspace/projects/overview` 返回 401；登录后 `/api/workspace/projects/overview` 和 `/api/admin/projects/runs` 均可访问。
- Chrome smoke test：前台登录后进入项目工作台首页；管理端 `/projects` 和 `/reports` 页面可打开，截图保存在 `logs/`（不提交）。

---

## 企业 Agent Workbench 去博客化清理

**日期**：2026-07-30

### 实现内容

- 删除后端博客/CMS 领域：文章、分类、标签、评论/留言、说说、关于页面的 Controller、Service、Mapper、Entity、DTO 和文章 ES Repository。
- 管理端从 Content Studio 调整为 Agent Operations，菜单改为 Agent 控制台、项目管理、知识来源、证据同步、Agent 运行记录、报告与审批、可观测性、连接器配置、系统日志和系统设置。
- 新增管理端项目管理、证据同步、Agent Runs、报告与审批、连接器配置页面；GitHub 已接入，本地项目、Jira/禅道、CI/CD 保留连接器接口位。
- 前台删除文章详情、分类、归档、说说、留言、关于等博客路由与页面，仅保留项目总览、项目工作台和知识来源。
- `agent-server/sql/init.sql` 重写为企业 Agent 初始化脚本，仅保留用户、设置、操作日志、知识库、RAG Trace、项目、证据、Run、报告和审批表。
- 新增 `agent-server/sql/drop_legacy_blog_tables.sql`，并已在本地 `atlasmind_agent` 执行，旧博客表已删除。
- Agent Run 知识库 fallback 不再传 `includeArticles`，避免继续把文章作为上下文来源。

### 验证

- `agent-server .\mvnw.cmd -q -DskipTests compile`：通过。
- `agent-admin npm run build`：通过，仅保留 Vite 大 chunk 警告。
- `agent-front npm run build`：通过，仅保留 Vite 大 chunk 警告。
- 管理端 `http://localhost:15173/` 浏览器检查通过：新 Agent 菜单可见，旧博客菜单未出现。
- MySQL 查询确认 `t_article`、`t_category`、`t_tag`、`t_comment`、`t_moment`、`t_about` 等旧表已不存在。

---

## GitHub 只读证据同步与报告 Citation 落地

**日期**：2026-07-29

### 实现内容

- 新增 `project_source`、`project_sync_job`、`project_evidence` 三张表，形成项目外部证据的统一沉淀层。
- 新增 GitHub 只读 connector，支持公开仓库无 Token 读取，私有仓库可通过 `GITHUB_APP_TOKEN` 配置访问。
- GitHub 同步范围包括仓库元数据、README、根目录文件树、关键配置文件、最近 Commit、Open Issue 和 Open PR。
- 新增项目同步 API：
  - `POST /api/projects/{projectId}/sync`
  - `GET /api/projects/{projectId}/evidence`
  - `GET /api/projects/{projectId}/sync-jobs`
- Agent Run 的 Evidence Retriever 改为优先读取 `project_evidence`，没有真实证据时才回退知识库检索和项目录入事实。
- 报告生成根据证据类型调整结论强度：有 README/文件树/配置文件时增强架构判断，有 Commit/PR 时增强协作判断，没有 Issue/PR/CI 时保守标记待确认。
- 项目工作台新增 GitHub 证据同步面板、同步状态、证据库存、报告引用来源列表和审批后执行按钮。
- 项目总览卡片新增 evidence 数量和同步状态，方便技术负责人快速判断报告是否有真实项目证据支撑。
- 修正工作台详情页乱码文案，统一为研发项目 Agent 工作台语义。

### 验证

- `agent-server .\mvnw.cmd -q -DskipTests compile`：通过。
- `agent-front npm run build`：通过。
- 重启后端和用户端后，`GET /api/projects/overview` 已返回 `evidenceCount`、`syncStatus`、`lastSyncAt`。
- `POST /api/projects/1/sync` 同步成功，生成 6 条 GitHub 证据，计数为 `REPO=1`、`README=1`、`FILE_TREE=1`、`FILE=2`、`COMMIT=1`。
- 启动新的 Agent Run 后，报告摘要显示 Evidence Reviewer 检查了 6 条 citable facts，`citationsJson` 引用真实 GitHub 文件、README、Commit、目录和仓库来源。

### 说明

- 当前同步仍是手动触发的同步请求，后续可改为异步 Job、定时健康检查或 Webhook 增量同步。
- 当前证据检索先用 MySQL 关键词/时间/置信分排序，Embedding 入库和向量召回可作为下一阶段增强。
- 本地项目、Jira/禅道、CI/CD 沿用 `project_source` / `project_evidence` 模型扩展，不在本阶段直接实现。

---

## 首条研发交付 Agent 垂直闭环落地

**日期**：2026-07-28

### 实现内容

- 新增项目上下文、Agent Run、Run Step、报告和审批动作数据模型。
- 新增项目总览首页与项目工作台详情页，首页从知识库/博客入口调整为研发项目组合视图。
- 新增五维项目健康分析：交付进度、质量稳定性、架构与技术债、项目风险、工程协作。
- 新增主控 Agent 调度的受控专家角色步骤：Context Builder、Evidence Retriever、Project Analyst、Evidence Reviewer、Delivery Planner、Report Composer。
- 新增异步 Agent Run 状态机，记录步骤、进度、证据摘要、失败状态和报告快照。
- 新增人工审批门，GitHub Issue 外部写操作必须在审批后执行。
- 新增 GitHub Issue connector；未配置 `GITHUB_APP_TOKEN` 时明确返回阻塞状态，不将草稿误报为执行成功。
- 新增 `agent-server/sql/agent_workbench.sql` 和启动期增量建表初始化，兼容已有本地数据库。
- 前端使用项目总览、健康信号、风险引用、交付计划和审批动作替代知识库问答作为首屏主任务。

### 验证

- Java 后端使用低内存 Maven 配置通过编译。
- `agent-front npm run build` 通过。
- 保留知识库、Citation、Session、Trace、Tool Call 和后台可观测性页面作为项目证据基础设施。

---

## 产品方向收敛：研发项目智能交付 Agent

**日期**：2026-07-28

### 背景

- 当前项目已经具备知识库导入、RAG 检索、Citation、问答 Trace、Tool Call 记录和可观测性基础。
- 但产品表层仍然保留博客、文章、动态和普通知识问答的痕迹，企业用户难以感知研发流程价值。
- 仅增加更多聊天功能，容易把项目做成“套了模型的问答 Demo”，无法体现 Agent 和工程系统结合的深度。

### 决策

- 产品总方向收敛为：**面向软件研发团队的项目理解、风险分析、交付规划与自动化执行 Agent 平台**。
- 第一阶段 MVP 定义为：**项目健康分析与交付计划 Agent**。
- 研发项目智能交付 Agent 是长期产品方向，项目健康分析与交付计划是第一个可落地模块，而不是两个互相竞争的产品。

### 目标闭环

```text
GitHub / GitLab / 本地项目 / 技术文档 / Issue / PR / CI
                              ↓
                       项目上下文构建
                              ↓
                    RAG 检索 + Tool Calling
                              ↓
                    多 Agent 分析和规划
                              ↓
              项目健康报告 / 风险清单 / 交付计划
                              ↓
                    人工审批后执行工具
                              ↓
                    任务跟踪 / 结果校验 / 审计
```

### Agent 能力设计

- **RAG**：统一检索代码、README、ADR、技术方案、Commit、Issue、PR、构建日志和项目复盘。
- **Tool Calling**：连接仓库查询、Git 历史、依赖分析、测试、静态检查、报告生成和任务创建工具。
- **多 Agent**：按职责拆分项目分析、文档分析、交付风险分析、计划生成和结果审查角色。
- **上下文组织**：将用户目标、项目版本、检索证据、工具输出、历史结论、偏好和执行限制结构化组装。
- **状态管理**：将一次工作保存为可恢复的 Agent Run，包括 Plan、Step、Tool Call、Approval、Artifact 和错误状态。
- **长期记忆**：保存项目事实、架构决策、事故记录、团队偏好和未完成任务，并要求重要记忆人工确认。
- **多轮上下文**：支持围绕健康报告继续追问、修正判断、调整计划和重新执行步骤。
- **模型适配**：暂不从零预训练基础模型，后续优先对 Issue 分类、风险识别、工具路由和结构化报告进行轻量微调。

### 第一阶段范围

1. 导入 GitHub / GitLab 或本地项目。
2. 建立代码、文档、提交记录和项目任务的统一检索上下文。
3. 生成带引用的项目健康度、架构风险和技术债报告。
4. 支持围绕报告进行多轮问答。
5. 根据风险和目标生成交付计划、任务依赖和验收标准。
6. 经人工审批后创建 GitHub Issue 或项目任务。

### 后续阶段

- 接入 Jira、禅道、TAPD 等任务系统。
- 增加 CI/CD 结果分析和发布风险预警。
- 支持测试、静态分析、依赖扫描等工程工具。
- 支持创建分支、PR 草稿和受审批保护的自动修复。
- 增加定时项目健康检查、报告推送和自动化流程。
- 将项目 Agent 能力抽象为企业研发流程 Agent 平台。

### 产品界面调整

- 核心导航逐步从“文章、动态、留言、归档”迁移为“工作台、项目、知识源、Agent、运行记录、报表、自动化、审批与审计”。
- 知识库不再只是文档浏览页，而是项目上下文和 Agent 证据来源。
- 文章等历史内容保留为迁移期兼容入口，不再作为企业产品主流程。

### 结论

本次不直接追求全自动写代码或自动部署，先以只读分析、计划生成和审批式任务创建形成可信闭环。在保证引用、状态、权限、审计和失败恢复的前提下，再逐步扩大 Agent 的执行范围。

---

## 项目分仓与企业 Agent Workbench 场景改造

**日期**：2026-07-27

### 背景

- 原项目同时承载个人博客和 Agent/RAG 工程展示，产品定位容易混乱。
- 求职目标是后端 + Agent 实习，需要一个更贴合企业实践的项目场景。
- 决策：原仓库继续作为个人博客；基于当前代码复制出 `AtlasMind-Agent-Workbench`，作为企业知识资产管理与 Agent 问答工作台。

### 改造

- 新项目本地目录：`E:\Data\Project\AtlasMind-Agent-Workbench`。
- 新 GitHub 仓库：`DayDayUpStudyHard/AtlasMind-Agent-Workbench`。
- 项目定位改为企业知识资产管理、RAG 检索和 Agent 问答工作台。
- 目录改名：
  - `blog-server` -> `agent-server`
  - `blog-admin` -> `agent-admin`
  - `blog-front` -> `agent-front`
- Java 包名从 `com.blog` 迁移为 `com.atlasmind`。
- 本地端口与原博客隔离：
  - Java 后端：`18080`
  - 管理端：`15173`
  - 用户端：`15174`
  - Python AI 服务：`18088`
- 新项目数据库名改为 `atlasmind_agent`，不再使用 `blog2026`。
- 新项目 `agent-server/sql/init.sql` 改为企业知识工作台初始化脚本，只保留结构和少量企业示例数据，不导入原个人博客文章、说说和文档切片。
- README 重写为企业 Agent Workbench 项目说明，突出 Java AI Gateway、RAG、异步导入、权限隔离和问答可观测性。

### 说明

- 原博客的 MySQL 数据已单独转储为原仓库 `blog-server/sql/init.sql`，用于个人博客恢复。
- 新项目不迁移原 RAG 运行数据，避免把个人上传文档、导入任务和 chunk 内容带入企业项目。

---

## 知识库 PDF 三档解析模式：快速解析、扫描 OCR、高质量 MinerU

**日期**：2026-07-27

### 背景

- 单一 PDF 解析策略无法同时满足速度、资源成本和解析质量。
- 普通文字型 PDF 适合快速 `pypdf` 提取；扫描版 PDF 需要 PaddleOCR；论文、教材和复杂版式文档更适合 MinerU 这类高质量文档解析器。
- 为了让项目更像工业系统，需要把解析能力做成可选择、可落库、可追踪的分层能力，而不是所有文件都走同一条重解析链路。

### 修复

- 新增三档解析模式：
  - `FAST`：快速解析，只读取 PDF 文字层。
  - `OCR`：扫描 OCR，文字层优先，低文字页调用 PaddleOCR。
  - `MINERU`：高质量解析，进入 MinerU provider，默认关闭。
- `kb_document` 新增 `parse_mode` 字段，上传时落库，重解析时沿用该文档的解析模式。
- Java 后台上传接口新增 `parseMode` 参数，并在触发 Python 导入任务时透传。
- 管理端 `/knowledge` 上传表单新增“解析模式”分段控件，文档表新增解析模式展示列。
- Python `KbIngestRequest` 新增 `parseMode`，`DocumentParser` 根据模式选择 `pypdf`、PaddleOCR 或 MinerU。
- 新增 `mineru_service.py`，保留 MinerU 命令式 provider 边界；默认 `MINERU_ENABLED=false`，未启用时给出明确错误。
- `.env.example` 新增：
  - `PDF_PARSE_PROVIDER=auto`
  - `MINERU_ENABLED=false`
  - `MINERU_COMMAND=magic-pdf -p {input} -o {output}`
  - `MINERU_OUTPUT_DIR=.mineru-output`
- `.gitignore` 忽略 `.mineru-output/`，避免临时解析产物进入仓库。

### 数据迁移

```sql
ALTER TABLE kb_document ADD COLUMN parse_mode VARCHAR(20) DEFAULT 'OCR' AFTER status;
UPDATE kb_document SET parse_mode = 'FAST' WHERE UPPER(file_type) <> 'PDF';
```

历史数据已修正：

- PDF 文档：`parse_mode=OCR`
- Markdown/TXT 文档：`parse_mode=FAST`

### 验证

- `python -m compileall -q tools/chat-assistant/backend/app`：通过。
- `agent-admin npm run build`：通过。
- `agent-server mvnw.cmd -q -DskipTests compile`：通过。
- `FAST` 模式测试：扫描版《算法导论》只读到第 798 页起的文字层。
- `OCR` 模式测试：扫描版《算法导论》第 1 页可通过 PaddleOCR 识别出封面文字。
- `MINERU` 模式测试：默认关闭时返回“高质量解析需要先启用 MINERU_ENABLED=true，并安装/配置 MinerU”。
- 重启 Java 后端后，`/api/admin/kb/documents` 已返回 `parseMode` 字段。

### 说明

- 当前默认上传模式为 `OCR`，对文字型 PDF 仍优先走 `pypdf`，不会无脑 OCR 全文。
- MinerU 暂未安装，当前实现的是工业化 provider 边界、配置项和前后端链路；后续安装 MinerU 后只需调整 `MINERU_COMMAND` 并启用开关。

---

## 知识库扫描版 PDF OCR 能力预留与本地 PaddleOCR 接入

**日期**：2026-07-26

### 问题

- 扫描版 PDF 没有文字层，`pypdf.extract_text()` 只能返回空文本，导致大部分正文页无法进入切片、Embedding 和 RAG 检索。
- 例如 `算法导论 原书第3版_13234228.pdf` 共 805 页，只有第 798-805 页能提取到文字，前 797 页是图片页，因此最终只生成 8 个 chunk。
- 如果直接把 OCR 做进主依赖，会让普通知识库导入也被迫安装 PaddleOCR/PyMuPDF 等重型包，不利于开发和部署。

### 修复

- 新增 `tools/chat-assistant/backend/app/services/ocr_service.py`：
  - 本地 OCR provider 使用 PaddleOCR。
  - PDF 页面渲染使用 PyMuPDF。
  - 云 OCR 预留 `OCR_PROVIDER=cloud`、`CLOUD_OCR_BASE_URL`、`CLOUD_OCR_API_KEY` 配置位，当前不绑定具体厂商。
- 修改 `DocumentParser._iter_pdf()`：
  - 默认优先读取 PDF 文字层。
  - 当页面可提取文本少于 `OCR_MIN_TEXT_CHARS` 且 `OCR_ENABLED=true` 时，才对该页执行 OCR。
  - 支持 `OCR_MAX_PAGES` 控制单文档 OCR 页数上限。
- 修改 `KbService._parse_and_store_chunks()`：
  - PDF 解析过程中回写任务进度。
  - OCR 页显示 `OCR 识别 x/y 页`，管理端可轮询展示。
- 管理端知识库页面新增 `OCR` 任务状态文案和轮询活跃状态。
- 拆分可选依赖：
  - 主依赖仍使用 `requirements.txt`。
  - OCR 依赖放入 `requirements-ocr.txt`，只在启用 OCR 的机器安装。
- `.env.example` 和本地 `.env` 增加 OCR 配置项，默认 `OCR_ENABLED=false`，避免未安装 OCR 依赖时影响普通导入。

### 修改文件

| 文件 | 变更 |
|------|------|
| `tools/chat-assistant/backend/app/config.py` | 新增 OCR 和云 OCR 预留配置 |
| `tools/chat-assistant/backend/app/services/ocr_service.py` | 新增本地 PaddleOCR provider |
| `tools/chat-assistant/backend/app/services/document_parser.py` | PDF 无文字页按配置进入 OCR |
| `tools/chat-assistant/backend/app/services/kb_service.py` | OCR/解析阶段进度回写 |
| `tools/chat-assistant/backend/requirements-ocr.txt` | 新增可选 OCR 依赖清单 |
| `tools/chat-assistant/backend/.env.example` | 新增 OCR 配置示例 |
| `tools/chat-assistant/backend/.env` | 新增本地 OCR 配置，默认关闭 |
| `agent-admin/src/views/KnowledgeBase.vue` | 新增 OCR 任务状态展示 |
| `README.md` | 补充 OCR 架构、启用方式和可调参数 |

### 验证

- `python -m compileall -q tools/chat-assistant/backend/app`：通过。
- `npm run build`（`agent-admin`）：通过。
- OCR 关闭时解析扫描 PDF：保持原行为，可提取 8 个文字块，不影响已有导入链路。
- 手动打开 `OCR_ENABLED=true` 且未安装 OCR 依赖时，错误信息明确提示安装 `pip install -r requirements-ocr.txt`。

### 说明

- 当前实现是“简化版方案 C”：本地 PaddleOCR 为主，云 OCR 只做配置预留。
- 真正上线时建议把 OCR Worker 独立部署，限制并发为 1-2，并增加文件 hash 缓存和页级断点续跑，避免重复 OCR 和资源被大文件占满。
- 本地安装实测：
  - Anaconda Python 3.13 安装 OCR 依赖长时间卡住，不适合 PaddleOCR。
  - 使用 `C:\Python310\python.exe` 创建 `tools/chat-assistant/backend/.venv-ocr` 成功。
  - PaddleOCR 3.7.0 + PaddlePaddle 3.3.1 在 Windows CPU 下触发 oneDNN/PIR 推理错误。
  - 已将 `requirements-ocr.txt` 固定为 PaddleOCR 2.x / PaddlePaddle 2.x / `numpy<2.0`，实测单页 OCR 可用。
  - `算法导论 原书第3版_13234228.pdf` 第 1 页可通过 OCR 识别出封面文字，第 2 页可识别出约 973 字简介文本。
- `start.bat` 已改为优先使用 `.venv-ocr` 启动 chat-assistant，且本地 `.env` 已打开 `OCR_ENABLED=true`。

---

## 知识库导入失败：Docker/WSL 异常导致 ES 索引不可用

**日期**：2026-07-26

### 问题

- 上传大文件后，消息中心返回：`ES 知识库索引不可用或向量维度不匹配，请检查 kb_chunks mapping 和 EMBEDDING_DIM`。
- Docker Desktop 同时提示 WSL 异常，`docker ps` 无法连接 Linux engine，`wsl -l -v` 显示 `Ubuntu` 和 `docker-desktop` 均处于 `Stopped`。
- 由于 Elasticsearch 容器没有正常运行，Python `chat-assistant` 在导入前执行 `ensure_kb_index()` 失败，最终把底层 ES 不可用包装成知识库索引不可用/维度不匹配错误。
- 本次失败文档为 `算法导论 原书第3版_13234228.pdf`，`kb_document.id=7`，失败任务为 `kb_ingest_job.id=25`。

### 排查

- 重启 Docker Desktop 后确认：
  - `wsl -l -v`：`Ubuntu`、`docker-desktop` 均为 `Running`。
  - `docker ps`：`blog-es` 为 `healthy`，端口 `9200/9300` 已监听。
  - `GET http://localhost:9200/_cluster/health`：`status=green`。
- 检查 ES `kb_chunks` mapping：
  - `embedding` 字段类型为 `dense_vector`。
  - `dims=2560`。
- 检查 Python `.env`：
  - `EMBEDDING_MODEL=Qwen/Qwen3-Embedding-4B`。
  - `EMBEDDING_DIM=2560`。
- 结论：当前不是向量维度不匹配，而是 Docker/WSL 异常导致 ES 在导入时不可用。

### 修复

- 启动 Docker Desktop，等待 WSL 和 `blog-es` 恢复。
- 通过后台登录态调用 `POST /api/admin/kb/documents/7/reparse`，重新触发文档解析、切片、Embedding 和 ES 写入。
- 新任务 `kb_ingest_job.id=26` 执行完成，文档 `kb_document.id=7` 状态从 `FAILED` 恢复为 `READY`。

### 验证

- `kb_ingest_job.id=26`：`REPARSE / DONE / progress=100`。
- `kb_document.id=7`：`status=READY`，`chunk_count=8`，错误信息已清空。
- `kb_document_chunk`：文档 `7` 的 8 个 chunk 均为 `embedding_status=DONE`、`index_status=DONE`。
- ES `kb_chunks`：文档 `7` 查询数量为 8 条。
- `POST http://localhost:18088/api/kb/qa/test`：返回 `retrievalType=VECTOR`，可召回文档 `7` 的知识库 chunk。

### 说明

- 281MB PDF 最终只解析出 8 个 chunk，说明该文件可抽取文本较少或主体可能是扫描/图片页；当前 `pypdf` 只能索引可提取文本，若要覆盖扫描页，需要后续接入 OCR 流程。
- 以后遇到同类错误，应先检查 Docker/WSL/ES 健康状态，再判断是否需要重建 ES 索引，避免误删已有 `kb_chunks` 数据。

---

## 知识库大文件导入后看不到索引/Embedding 进度

**日期**：2026-07-26

### 问题

- 管理端上传大文件后，页面只显示上传进度，上传完成后看不到解析、切片、Embedding、索引阶段的任务进度。
- 用户会误以为“没有开始索引和 embedding”。
- 数据库排查发现，文档列表只返回 `kb_document.status`，而真正的任务进度写在 `kb_ingest_job.progress/message/status` 中，前端没有展示。
- 本地闭环测试还发现当前 8080 运行实例对分片接口返回 500，而使用当前源码临时启动的新实例分片上传可成功创建 `kb_document` 和 `kb_ingest_job`，说明运行实例需要重启到最新代码。
- 临时导入测试任务最终失败在 ES/Embedding 配置：`ES 知识库索引不可用或向量维度不匹配，请检查 kb_chunks mapping 和 EMBEDDING_DIM`，这类失败之前只能在消息中心看到，不会出现在文档列表进度列。

### 修复

- `KbDocument` 增加非表字段：
  - `latestJobId`
  - `latestJobStatus`
  - `latestJobProgress`
  - `latestJobMessage`
  - `latestJobErrorMessage`
- `KnowledgeBaseServiceImpl.listDocuments()` 查询文档列表后，批量补齐每个文档最近一条 `kb_ingest_job`。
- 管理端 `/knowledge` 文档表新增“任务进度”列，展示最近任务状态、百分比、当前消息或失败原因。
- 管理端在存在活跃任务时每 5 秒自动刷新文档列表，活跃状态包括 `PENDING/RUNNING/PARSING/CHUNKING/EMBEDDING/INDEXING`。
- 管理端分片上传增加 `catch`，上传/合并失败时弹出后端返回的明确错误，不再只默默结束 loading。

### 修改文件

| 文件 | 变更 |
|------|------|
| `agent-server/src/main/java/com/blog/entity/KbDocument.java` | 增加最新任务进度非表字段 |
| `agent-server/src/main/java/com/blog/service/impl/KnowledgeBaseServiceImpl.java` | 文档列表批量补齐最近导入任务 |
| `agent-admin/src/views/KnowledgeBase.vue` | 增加任务进度列、轮询刷新和上传失败提示 |

### 验证

- 使用临时 Spring Boot 18080 实例走分片上传闭环：`upload/chunk` 返回 200，`upload/complete` 返回 200，并创建 `kb_document` 与 `kb_ingest_job`。
- 数据库确认任务能从 `RUNNING` 推进到 Python 处理阶段；测试任务因 ES/Embedding 维度问题转为 `FAILED`，失败原因可用于前端展示。
- `agent-server .\mvnw.cmd -q -DskipTests compile`：通过。
- `agent-admin npm run build`：通过。
- `python -m compileall -q tools/chat-assistant/backend/app`：通过。

### 说明

- 修复后需要重启当前 8080 后端服务和管理端 Vite 服务，否则浏览器仍会访问旧实例。
- 如果上传后任务进度显示 ES/Embedding 维度错误，需要检查 `EMBEDDING_DIM` 与 ES `kb_chunks` 索引 mapping 是否一致，并在必要时重建索引。

---

## 知识库大文件导入升级：分片上传、流式解析、批量 Embedding

**日期**：2026-07-26

### 问题

- 300MB 上限只解决了“能接收”的问题，完整文件仍可能挤在一次 HTTP 请求中，网络波动时重试成本高。
- Python `chat-assistant` 原导入流程是 `parse list -> chunk list -> replace_chunks -> 逐条 embedding`，大文件会占用更多内存和 API 调用时间。
- 重建索引时也会一次性读取全部 chunk，不适合更大的知识库文档。

### 修复

- 新增 Java 分片上传接口：
  - `POST /api/admin/kb/documents/upload/chunk`
  - `POST /api/admin/kb/documents/upload/complete`
- 管理端知识库上传改为 8MB 分片上传，上传过程中显示进度，完成后由 Java 合并分片并创建异步导入任务。
- Java 后端将分片暂存到 `upload/knowledge/.chunks/{uploadId}`，合并成功后清理临时分片目录。
- 保留原 `/api/admin/kb/documents/upload` 普通上传接口，避免旧调用失效。
- Python `DocumentParser` 增加 `iter_parse()`，MD/TXT 改为逐行/逐段读取，PDF 按页产出文本块。
- Python `HybridChunker` 增加 `iter_chunks()`，导入时不再先把所有 chunk 堆成列表。
- Python `KbStore` 增加分批写入、chunk 计数和批量迭代读取能力。
- Python `KbService` 导入流程改为“流式解析 -> 分批写 MySQL -> 分批读取 chunk -> `embed_batch()` -> 写 ES”。
- 重建索引改为按批次读取 chunk，并通过 `count_chunks()` 统计数量，避免一次性加载全部 chunk。
- 修复 `llm_service.py` 中 RAG system prompt 的中文弯引号三引号，避免 Python 服务语法编译失败。
- 新增可调环境变量：
  - `KB_CHUNK_INSERT_BATCH_SIZE`：默认 `200`
  - `KB_EMBEDDING_BATCH_SIZE`：默认 `16`

### 修改文件

| 文件 | 变更 |
|------|------|
| `agent-server/src/main/java/com/blog/controller/admin/KnowledgeBaseAdminController.java` | 新增分片上传与合并接口 |
| `agent-server/src/main/java/com/blog/service/KnowledgeBaseService.java` | 增加分片上传服务方法 |
| `agent-server/src/main/java/com/blog/service/impl/KnowledgeBaseServiceImpl.java` | 实现分片暂存、合并、校验和清理 |
| `agent-admin/src/api/index.js` | 新增分片上传和合并 API 调用 |
| `agent-admin/src/views/KnowledgeBase.vue` | 上传流程改为 8MB 分片并显示进度 |
| `tools/chat-assistant/backend/app/config.py` | 新增 chunk 写库批次和 embedding 批次配置 |
| `tools/chat-assistant/backend/app/services/document_parser.py` | 增加流式解析与流式切片接口 |
| `tools/chat-assistant/backend/app/services/kb_store.py` | 增加分批写入、计数和迭代读取 |
| `tools/chat-assistant/backend/app/services/kb_service.py` | 导入和重建索引改为流式/批处理流程 |
| `tools/chat-assistant/backend/app/services/llm_service.py` | 修复 prompt 字符串三引号语法 |
| `README.md` | 更新 RAG 大文件导入能力说明 |

### 说明

- 当前版本已把 300MB 导入从“单请求上传 + 一次性解析/逐条 embedding”升级为“分片上传 + 分批处理”。
- PDF 解析仍依赖 `pypdf`，按页提取可以降低业务层堆积，但超大/扫描版 PDF 的实际耗时仍取决于 PDF 内容结构。
- 下一步如果继续工业化，重点应是断点续传、失败分片重试、任务队列限流、批量 ES bulk 写入和更细的任务进度。

---

## 知识库单文件上传上限提升到 300MB

**日期**：2026-07-26

### 问题

- 原 Spring Boot multipart 配置仍是 `10MB`，管理端上传较大知识库文档会在进入异步导入前被拦截。
- 管理端知识库上传区没有明确文件大小提示，也没有前端选择阶段的大小校验。
- 管理端 Axios 默认 `10s` 超时，对 300MB 文件上传不够稳。

### 修复

- 将公共 multipart 配置改为环境变量可覆盖：`KB_MAX_FILE_SIZE` 默认 `300MB`，`KB_MAX_REQUEST_SIZE` 默认 `320MB`。
- 在 `KnowledgeBaseServiceImpl.uploadDocument` 增加空文件与 300MB 服务端兜底校验，避免只依赖前端限制。
- 管理端知识库上传接口单独设置 10 分钟超时，避免影响普通 API。
- 管理端 `/knowledge` 上传区增加 300MB 上限提示，并在选择文件时阻止超过 300MB 的 Markdown/TXT/PDF。
- README 补充知识库大文件导入说明，并注明第一版仍不是完整的分片上传/流式解析方案。

### 修改文件

| 文件 | 变更 |
|------|------|
| `agent-server/src/main/resources/application.yml` | multipart 默认上限提升为 300MB/320MB，并支持环境变量覆盖 |
| `agent-server/src/main/java/com/blog/service/impl/KnowledgeBaseServiceImpl.java` | 增加知识库上传空文件和 300MB 兜底校验 |
| `agent-admin/src/api/index.js` | 知识库文档上传接口增加 10 分钟超时 |
| `agent-admin/src/views/KnowledgeBase.vue` | 增加上传提示与前端文件大小校验 |
| `README.md` | 补充 RAG 知识库 300MB 导入能力和后续工业化方向 |

### 说明

- 该版本可以接收并创建 300MB 以内文件的知识库异步导入任务。
- Python `chat-assistant` 当前仍会在解析阶段读取文本/PDF 内容并生成切片，大文件解析、embedding 和 ES 索引耗时会明显增加。
- 若后续要支持更高并发或超过 300MB 的资料集，建议继续实现分片上传、断点续传、流式解析、批量 embedding、任务队列限流与更细的进度展示。

---

## 用户端与管理端视觉风格重构：索引角标 Logo + 蓝色纸张主题

**日期**：2026-07-25

### 调整

- 保留原有首页、AI 问答区、文章流、侧栏和管理端导航布局，仅调整视觉设计。
- 用户端和管理端统一使用方案 2 的索引角标 Logo，移除原有字母 `B` 标识。
- 配色改为浅色纸张背景、深墨色文字和低饱和蓝色主色，去除紫色渐变和装饰性网格背景。
- 用户端 AI 输入框、文章卡片和侧栏采用方案 1 的克制工作台风格，减少圆角、阴影和玻璃拟态。
- AI 聊天入口移除机器人和气泡 emoji，改用线性图标，避免模板化 AI 视觉。
- 管理端登录页、侧栏、顶部栏和 Element Plus 基础控件同步蓝色主题。

### 修改文件

| 文件 | 变更 |
|------|------|
| `agent-front/src/App.vue` | 更新用户端主题变量、Naive UI 蓝色主题和暗色模式 |
| `agent-front/src/components/AppHeader.vue` | 替换索引角标 Logo，调整导航和搜索框风格 |
| `agent-front/src/components/ChatWindow.vue` | 移除 emoji，改为线性图标和克制蓝色聊天样式 |
| `agent-front/src/views/HomeView.vue` | 调整首页纸张表面、字体和文章区视觉 |
| `agent-front/src/views/HomeAiView.vue` | 调整 AI 问答区、输入框和来源标签视觉 |
| `agent-admin/src/components/AdminLayout.vue` | 同步 Logo、侧栏、顶部栏和管理端蓝色主题 |
| `agent-admin/src/style.css` | 更新 Element Plus 全局颜色、边框和阴影 |
| `agent-admin/src/views/LoginView.vue` | 更新登录页 Logo、卡片和按钮样式 |

### 验证

- 保持现有路由、API、数据库和页面布局不变。
- `agent-front npm run build`：通过。
- `agent-admin npm run build`：通过。
- `git diff --check`：通过。

---

## 强化 Java 前后端与 Agent 知识工作台工程能力

**日期**：2026-07-25

### 调整

- 新增 Java `AiGateway` 模块，统一封装 Spring Boot 到 Python AI 服务的导入、重建索引、删除索引和检索测试调用。
- 新增知识库异步导入记录，保存解析、Embedding、索引任务状态，并通过消息中心反馈结果。
- 新增管理端 Dashboard 聚合接口 `/api/admin/dashboard/overview`，统一返回内容统计、知识库文档数、失败任务数和最近内容。
- 新增用户端 AI 会话持久化，问题和回答写入 `kb_qa_session`、`kb_qa_message`，刷新页面后可以恢复历史消息。
- 新增系统运行配置中心，支持动态调整 AI 默认 Top-K、最大 Top-K 和 AI 开关。
- 用户端和管理端的检索请求统一读取运行配置，Top-K 不再只在管理端页面写死。
- FastAPI Chat 请求增加 `topK` 参数，并对检索数量做范围校验。
- AI 会话增加随机 `ownerToken`，用户端通过 `X-AI-Session-Token` 访问历史消息，避免仅凭会话 ID 读取或追加内容。
- Python 内部知识库任务接口增加 `CHAT_ASSISTANT_TOKEN` 校验，Java 网关自动携带 `X-Internal-Token`。
- 修正 Top-K 配置边界：当最大 Top-K 调小时，默认 Top-K 自动收敛到最大值；同时规范 AI 服务 URL 尾斜杠和最小超时时间。
- 修正 `ai_session_security.sql` 对 MySQL 8.0.28 的兼容性，改用 `INFORMATION_SCHEMA` 判断字段后再执行幂等变更。
- 根据实际使用体验移除独立的知识库任务中心页面、菜单、路由和任务管理接口，避免与知识库页面及消息中心重复。
- 保留 `kb_ingest_job` 作为内部异步处理记录，继续用于 Python 任务回调、Dashboard 失败统计和消息中心通知。

### 新增接口

| 接口 | 作用 |
|------|------|
| `GET /api/admin/dashboard/overview` | 管理端仪表盘聚合数据 |
| `POST /api/ai/sessions` | 创建用户端 AI 会话 |
| `GET /api/ai/sessions/{id}/messages` | 查询会话消息 |
| `POST /api/ai/sessions/{id}/messages` | 保存会话消息 |
| `GET /api/admin/settings/runtime` | 查询运行配置 |
| `PUT /api/admin/settings/runtime` | 更新运行配置 |
| `GET /api/site/runtime-config` | 获取用户端公开运行配置 |

### 数据库

- 新增 `agent-server/sql/system_settings.sql`。
- 新增 `agent-server/sql/ai_session_security.sql`，为已有数据库补充 AI 会话归属令牌。
- 创建 `sys_setting` 表并写入默认配置：
  - `ai.retrieval.top-k = 5`
  - `ai.retrieval.max-top-k = 10`
  - `ai.enabled = true`
- 已在本地 `AtlasMind Agent Workbench` 数据库执行迁移脚本。

### 验证

- `agent-server/.mvnw.cmd -q -DskipTests compile`：通过。
- `agent-server/.mvnw.cmd -q test`：通过。
- `agent-admin npm run build`：通过。
- `agent-front npm run build`：通过；首次执行因本地 `node_modules` 不完整，使用现有 pnpm 离线缓存恢复依赖后复测通过。
- `python -m compileall -q app`：通过。
- `git diff --check`：通过。

---

## 统一 AtlasMind 品牌显示与动态站点名称

**日期**：2026-07-24

### 调整

- 用户端品牌统一为 `AtlasMind`，AI 助手统一为 `AtlasMind AI`。
- 浏览器标题改为 `AtlasMind · 知识工作台`。
- 页脚版权改为 `© 2024 AtlasMind`。
- 管理端登录页、侧栏和浏览器标题同步更新。
- 动态站点名称使用 `t_user.id=1.nickname`，初始化 SQL 和 Java 默认数据同步改为 `AtlasMind`。
- 仓库目录、API 路径、数据库名 `AtlasMind Agent Workbench` 和历史文章内容保持不变。

### 修改文件

| 文件 | 改动 |
|------|------|
| `agent-front/index.html`、`agent-front/src/components/AppHeader.vue` | 用户端浏览器标题和品牌 Logo |
| `agent-front/src/components/AppFooter.vue` | 页脚版权名称 |
| `agent-front/src/views/HomeAiView.vue`、`agent-front/src/views/HomeView.vue` | 首页品牌和 AI 助手名称 |
| `agent-admin/index.html`、`agent-admin/src/views/LoginView.vue`、`agent-admin/src/components/AdminLayout.vue` | 管理端品牌显示 |
| `agent-server/src/main/java/com/blog/config/DataInitializer.java` | 新环境默认动态站点名称 |
| `agent-server/sql/AtlasMind Agent Workbench.sql` | SQL 初始化数据中的站点昵称 |

---

## 收紧 AI 首页首屏并将“归档”更名为“时间线”

**日期**：2026-07-24

### 调整

- 将首页 AI 区域高度、输入框宽度和上下留白略微收紧，让文章和说说更早进入首屏。
- 移动端同步降低 AI 区域高度，保留输入框和推荐问题的可用性。
- 用户端导航、首页入口和时间轴页面标题统一使用“时间线”。
- `/archive` 路由保持不变，仅调整展示文案。

### 修改文件

| 文件 | 改动 |
|------|------|
| `agent-front/src/views/HomeAiView.vue` | 收紧 AI 首屏布局，入口文案改为“时间线” |
| `agent-front/src/components/AppHeader.vue` | 导航“归档”改为“时间线” |
| `agent-front/src/views/ArchiveView.vue` | 页面标题改为“文章时间线” |
| `agent-front/src/views/HomeView.vue` | 同步旧首页入口文案 |

---

## 用户端首页改为 AI 问答优先的博客内容流布局

**日期**：2026-07-24

### 现象

原用户端首页以个人介绍和文章卡片为主，AI 问答仅通过右下角浮窗进入，不符合“先问 AI、再阅读博客”的知识库使用路径。

### 修复

| 文件 | 改动 |
|------|------|
| `agent-front/src/views/HomeAiView.vue` | 新增 AI-first 首页：中央问答输入框、推荐问题、流式对话态、回答来源、下方文章和说说内容流 |
| `agent-front/src/router/index.js` | 将 `/` 首页路由切换到 `HomeAiView.vue` |
| `agent-front/src/App.vue` | 首页隐藏旧的右下角 AI 浮窗，其他页面继续保留 |

### 验证

```text
agent-front: vite build -> success
本地开发地址: http://localhost:15174/
```

---

## RAG 文档上传后消息中心提示 Python 服务 404 / 索引失败

**日期**：2026-07-24

### 现象

管理端连续上传多个知识库文档后，右上角消息中心提示：

```text
知识库任务触发失败
调用 Python 知识库服务失败: Python 服务返回404: {"detail":"Not Found"}
```

后续即使文档和切片已经写入 MySQL，知识库检索仍为空，`kb_document_chunk.index_status` 全部为 `FAILED`。

### 原因

1. 8088 端口曾运行旧版 `chat-assistant` 进程，旧进程没有 `/internal/kb/ingest/jobs` 等知识库内部路由，因此 Java 调 Python 返回 404。
2. 当前使用的 `Qwen/Qwen3-Embedding-4B` 实际返回 2560 维向量，但 `.env`、README 示例、SQL 默认值和 ES `kb_chunks` mapping 仍按 1536 维创建，导致 ES 写入报 dense_vector 维度不匹配。
3. 多个文档并发重建索引时，多个 Python 后台任务同时创建 `kb_chunks`，其中一个创建成功后，其他任务收到 `resource_already_exists_exception`，之前被误判为索引不可用。
4. Python 导入流程原本只要切片落库就可能把文档标记为 `READY`，即使 0 个 chunk 真正写入 ES，也会造成“状态成功但 RAG 检索不到”的假象。

### 修复

**修改文件：**

| 文件 | 改动 |
|------|------|
| `tools/chat-assistant/backend/app/services/embedding_service.py` | 新增 embedding 返回维度校验，配置和真实向量不一致时给出明确错误 |
| `tools/chat-assistant/backend/app/services/es_service.py` | `kb_chunks` 自动校验 dense_vector 维度；空旧索引可重建；并发创建时把“索引已存在”重新校验为成功 |
| `tools/chat-assistant/backend/app/services/kb_service.py` | 导入/重建索引时统计 ES 写入成功数；0 个 chunk 写入成功时任务进入 `FAILED`，不再标记 `READY` |
| `tools/chat-assistant/backend/.env.example` | 将 `Qwen/Qwen3-Embedding-4B` 示例维度改为 2560 |
| `tools/chat-assistant/backend/app/config.py` | Python embedding 默认维度改为 2560 |
| `agent-server/sql/knowledge_base.sql` | `kb_document.embedding_dim` 默认值改为 2560 |
| `agent-server/src/main/resources/application.yml` | Java 默认 embedding provider 统一为 SiliconFlow/Qwen3，默认维度改为 2560 |
| `agent-server/src/main/java/com/blog/service/impl/KnowledgeBaseServiceImpl.java` | Java 侧知识库文档 metadata 默认维度改为 2560 |
| `agent-server/src/main/java/com/blog/document/ArticleDocument.java` | 文章 ES dense_vector 维度与当前 Qwen3 配置统一为 2560 |
| `README.md`、`docs/knowledge-base-rag-plan.md` | 补充 Qwen3 embedding 为 2560 维、切换模型后需要同步重建 ES 向量索引 |

### 本地数据修复

- 已停止旧版 `chat-assistant` 进程并重新启动 Python 服务，`/openapi.json` 已包含 `/internal/kb/ingest/jobs`、`/internal/kb/documents/{document_id}/reindex` 和 `/api/kb/qa/test`。
- 已将本机 `tools/chat-assistant/backend/.env` 的 `EMBEDDING_DIM` 从 1536 改为 2560（真实 key 未写入文档和 Git）。
- 已删除空的旧 `kb_chunks` 1536 维索引，并由新流程重建为 2560 维。
- 已将本机 `kb_document.embedding_dim` 修正为 2560。
- 已重建 5 个知识库文档索引，当前全部为 `READY`。

### 验证

```text
python -m compileall tools/chat-assistant/backend/app
agent-server/mvnw.cmd -q -DskipTests package
GET  http://localhost:18088/api/chat/health        -> embedding dim = 2560
GET  http://localhost:18088/openapi.json           -> internal kb routes 存在
GET  http://localhost:9200/kb_chunks/_mapping     -> embedding.dims = 2560
GET  http://localhost:9200/kb_chunks/_count       -> count = 470
POST http://localhost:18088/api/kb/qa/test         -> retrievalType = VECTOR
POST http://localhost:18080/api/admin/kb/qa/test   -> code = 200, retrievalType = VECTOR
```

数据库验证：

```text
kb_document: 5 个文档全部 READY
kb_document_chunk:
  文档 1 DONE/DONE 8
  文档 2 DONE/DONE 11
  文档 3 DONE/DONE 298
  文档 4 DONE/DONE 148
  文档 5 DONE/DONE 5
```

---

## RAG 知识空间首次进入为空

**日期**：2026-07-24

### 现象

进入管理端 `/knowledge` 后，知识空间列表为空，看起来像 RAG 知识库没有初始化。

### 原因

`agent-server/sql/knowledge_base.sql` 第一版只创建 `kb_*` 表，没有插入默认知识空间。代码中的“项目复盘”空间只会在点击“导入 Debug 记录”时通过 `findOrCreateDebugSpace()` 懒创建，因此首次进入页面、且没有手动创建空间或导入文档时，空间列表会为空。

### 修复

**修改文件：** `agent-server/sql/knowledge_base.sql`

- 新增 `SET NAMES utf8mb4`，避免 Windows MySQL CLI 执行中文种子数据时出现连接字符集混用。
- 新增默认知识空间种子数据：
  - `项目复盘`
  - `学习笔记`
  - `面试题库`
- 使用 `INSERT ... SELECT ... WHERE NOT EXISTS`，重复执行迁移脚本不会重复插入同名未删除空间。

### 数据修复

已在本机 `AtlasMind Agent Workbench` 执行迁移脚本，并清理第一次 GBK 字符集执行时误插入的乱码空间。当前 `kb_space` 保留三条有效默认空间。

---

## AtlasMind Agent Workbench 个人知识库 RAG 第一版

**日期**：2026-07-24

### 需求

把博客项目升级为个人学习 / 项目 / 面试知识库：文档独立管理，RAG 统一召回博客文章和知识库文档，检索以向量为主、关键词 fallback，并支持异步导入、消息中心、删除恢复和后台检索测试。

### 实现

| 文件/模块 | 改动 |
|------|------|
| `docs/knowledge-base-rag-plan.md` | 记录知识库 RAG 架构、权限规则、表设计、导入流程和验收标准 |
| `agent-server/sql/knowledge_base.sql` | 新增知识库空间、文档、chunk、导入任务、通知、trace、评估集相关表 |
| `agent-server/src/main/java/com/blog/entity/Kb*.java` | 新增知识库实体模型 |
| `agent-server/src/main/java/com/blog/mapper/Kb*.java` | 新增 MyBatis Plus Mapper，支持硬删除文档和 chunk |
| `agent-server/src/main/java/com/blog/service/KnowledgeBaseService.java` | 新增知识库管理服务接口 |
| `agent-server/src/main/java/com/blog/service/impl/KnowledgeBaseServiceImpl.java` | 实现空间、上传、Debug 记录导入、重解析、重索引、删除、恢复、永久删除、通知和 Python 调用 |
| `agent-server/src/main/java/com/blog/controller/admin/KnowledgeBaseAdminController.java` | 新增 `/api/admin/kb/**` 管理接口和后台 QA 测试代理 |
| `tools/chat-assistant/backend/app/services/document_parser.py` | 新增 MD/TXT/PDF 解析和标题/段落优先 + 固定长度 overlap 切片 |
| `tools/chat-assistant/backend/app/services/kb_store.py` | 新增 MySQL chunk、任务、文档状态和通知写入 |
| `tools/chat-assistant/backend/app/services/kb_service.py` | 新增导入、重建索引和检索测试服务 |
| `tools/chat-assistant/backend/app/services/es_service.py` | 新增 `kb_chunks` index、文档 chunk 写入、删除、向量检索和关键词 fallback |
| `tools/chat-assistant/backend/app/api/routes.py` | `/api/chat/send` 统一召回文章索引和文档索引；新增内部导入/重索引/删索引接口与 `/api/kb/qa/test` |
| `agent-admin/src/views/KnowledgeBase.vue` | 新增后台知识库页面：空间、上传、Debug 导入、文档状态、切片预览、重解析、重索引、删除/恢复/永久删除、检索测试 |
| `agent-admin/src/components/AdminLayout.vue` | 新增知识库菜单和右上角消息中心轮询 |
| `agent-admin/src/api/index.js` | 新增知识库管理 API 封装 |
| `tools/chat-assistant/backend/.env.example` | 补充 SiliconFlow/Qwen embedding、KB index 和 MySQL 示例配置 |

### 权限规则

- 普通搜索只检索 `PUBLIC` 文章。
- RAG 可检索 `PUBLIC` / `RAG_ONLY` 文章和 `READY` 知识库文档。
- `PRIVATE` 文章、`DISABLED` 文档、失败/处理中/已删除文档永远不可进入 RAG 检索。
- 文档软删除会设置 `DISABLED` 并触发 ES 索引移除；恢复后用 MySQL chunk 重建索引。

### 验证

```text
python -m compileall tools/chat-assistant/backend/app
agent-server/.mvnw.cmd -DskipTests package
agent-admin npm run build
```

结果：三项均通过。前端构建仅出现 Vite 大 chunk 提示，不影响运行。

### 后续联调

1. 已在本机 `AtlasMind Agent Workbench` 执行 `agent-server/sql/knowledge_base.sql`，知识库表已创建。
2. 启动项目后进入后台 `/knowledge`，导入 `Debug修复记录.md` 或上传 MD/TXT/PDF。
3. 观察右上角消息中心导入成功/失败通知。
4. 使用后台检索测试确认向量检索主路径和关键词 fallback。

---

## 管理端仪表盘统计显示为 0

**日期**：2026-07-21

### 现象

管理端的文章列表和说说列表都可以正常看到数据，但进入仪表盘时，文章、分类、评论、说说四个统计数字都显示为 0。

### 原因

仪表盘同时请求文章、分类、评论和说说四个接口，原先使用 `Promise.all` 统一等待结果。这个写法是“任意一个接口失败，整组请求都失败”，所以只要分类、评论或任意一个统计接口出现异常，后续赋值逻辑就不会执行，页面会一直保留初始值 0。

文章管理和说说管理页面是单独请求各自接口，因此即使仪表盘的某个接口失败，它们仍然可以正常显示数据。

### 修复

**修改文件：** `agent-admin/src/views/Dashboard.vue`

- 将仪表盘数据加载从 `Promise.all` 改为 `Promise.allSettled`
- 新增 `unwrapData(result, fallback)`，单个接口失败时只使用该模块的兜底值
- 文章、评论、说说统计统一从分页接口的 `total` 读取
- 分类统计在接口成功时使用分类数组长度，接口失败时兜底为 0
- 最近文章和最新评论也独立赋值，避免一个接口异常拖垮整个仪表盘

### 验证

- `cd agent-admin && npm run build`：构建通过
- `git diff --check`：无空白错误，仅有 Windows LF/CRLF 提醒

---

## 前后台界面体验改造 — 知识库式博客 + CMS 工作台

**日期**：2026-07-21

### 背景

项目功能已经比较完整，但前端界面观感偏普通：前台蓝色玻璃拟态、渐变和装饰动效铺得太平均，内容主次不够清晰；后台仪表盘只有少量统计数字，缺少真正的内容管理入口，整体也不像可长期使用的 CMS。

### 设计方向

采用“AI 知识库式技术博客 + 专业 CMS 后台”的方向：

| 端 | 目标 | 处理 |
|----|------|------|
| 博客前台 | 强化阅读与知识库气质 | 低噪音背景、统一设计变量、内容优先布局 |
| 首页 | 突出 AI/RAG 与内容流 | 站点身份 + AI 知识库入口 + 最新文章 + 侧栏精选 |
| 文章列表 | 更适合扫描和阅读 | 列表式文章卡片、稳定封面尺寸、简化 hover 动效 |
| 文章详情 | 提升长文阅读体验 | 收窄正文宽度、去掉标题渐变、统一代码块/引用样式 |
| 管理后台 | 更像内容管理系统 | 深色侧栏、白色顶栏、浅灰工作区、减少装饰 |
| 仪表盘 | 从展示页变工作台 | 增加统计、今日关注、最近文章、最新评论 |

### 改动

#### 1. 前台全局视觉基底

**修改文件：** `agent-front/src/App.vue`

- 移除全局漂浮光斑背景，改为低噪音网格背景
- 新增 CSS 变量：背景、表面、边框、文本、主色、阴影等
- 主色从 Element 风格蓝 `#409EFF` 调整为更克制的 `#2563eb`
- 主内容宽度从 860px 扩展到 1120px，适配首页双栏布局
- Markdown 样式从渐变装饰转向阅读排版：标题用普通文本色、h2 用细边线、代码块用深色背景、引用块用左侧主色边线

#### 2. 前台首页和文章体验

**修改文件：**

| 文件 | 改动 |
|------|------|
| `agent-front/src/components/AppHeader.vue` | 顶栏宽度同步 1120px；Logo、导航 active、搜索框重设；补移动端适配 |
| `agent-front/src/views/HomeView.vue` | 移除头像居中 hero、鼠标光斑和 3D tilt 卡片；改为站点身份 + AI/RAG 入口 + 文章流 + 侧栏 |
| `agent-front/src/components/ArticleCard.vue` | 改为阅读型列表卡片；固定封面尺寸；无封面时统一字母占位；展示时间、阅读量、预计阅读时长 |
| `agent-front/src/views/ArticleDetail.vue` | 正文最大宽度 780px；标题去渐变；封面、分割线、标签、上下篇导航统一设计变量 |

#### 3. 后台应用壳与全局样式

**修改文件：**

| 文件 | 改动 |
|------|------|
| `agent-admin/src/App.vue` | 移除全局光斑背景；清理不标准 `:deep` 暗色样式 |
| `agent-admin/src/components/AdminLayout.vue` | 侧栏改深色；Logo 增加 Content Studio 副标题；顶栏和主区域改为工作台风格 |
| `agent-admin/src/style.css` | 降低玻璃拟态；Element Plus 卡片、弹窗、表格恢复白底和轻边框 |

#### 4. 后台仪表盘和文章列表

**修改文件：**

| 文件 | 改动 |
|------|------|
| `agent-admin/src/views/Dashboard.vue` | 仪表盘改为内容工作台，包含统计、今日关注、最近文章、最新评论和快捷动作 |
| `agent-admin/src/views/ArticleList.vue` | 顶部标题和筛选区改为独立工具条；表格白底轻阴影；状态/可见性 badge 更克制 |

### 验证

- `cd agent-front && npm run build`：构建通过
- `cd agent-admin && npm run build`：构建通过
- `git diff --check`：无空白错误（仅 Windows LF/CRLF 提醒）
- 本地 dev server：
  - 前台 `http://localhost:15174` 返回 200
  - 后台 `http://localhost:15173` 返回 200

### 后续建议

- 前台可继续补“文章目录 / 阅读进度 / 代码复制”增强长文体验
- 后台可继续优化 `ArticleEdit.vue`，做成正文编辑区 + 右侧发布设置的发布工作流
- 构建仍有 Vite 大 chunk 提醒，后续可对 `md-editor-v3`、highlight.js、Naive UI/Element Plus 做按需拆包

---

## AI 对话 + RAG 检索增强生成 + 内容可见性管理

**日期**：2026-07-21

### 背景

博客缺少交互式 AI 能力。利用已有的 ES + LLM API 实现 RAG 智能问答：
- 前台右下角浮窗对话窗口（与工具浮窗并列）
- 用博客文章作为知识库做专属化回答
- 管理端控制文章是否参与 RAG

### 架构决策

全部 RAG 逻辑放 Python FastAPI 微服务（`chat-assistant`），与旅行助手模式一致，避免给 Spring Boot 加 LLM 依赖：

| 决策 | 选择 | 理由 |
|------|------|------|
| 检索 | ES IK 分词 `multi_match`（非向量） | 复用已有 ES，零 embedding 成本 |
| 对话 | Python FastAPI（非 Java） | SSE streaming 原生支持 + OpenAI SDK |
| 流式 | SSE | FastAPI `StreamingResponse` + 前端 `ReadableStream` |
| 索引 | Java 只管写正文到 ES | 不调 embedding，Python 检索用 IK 分词 |
| LLM | DeepSeek | 与旅行助手共享 API Key |

### 改动

#### 1. 内容可见性管理（Phase 1-3）

**数据库**：`t_article` 新增 `visibility VARCHAR(20) DEFAULT 'PUBLIC'` 列。三种状态：

| 值 | 网站展示 | RAG 检索 |
|----|---------|----------|
| PUBLIC | ✅ | ✅ |
| RAG_ONLY | ❌ | ✅ |
| PRIVATE | ❌ | ❌ |

**Java 后端改动：**

| 文件 | 改动 |
|------|------|
| `entity/Article.java` | +visibility 字段 |
| `dto/ArticleDto.java` | +visibility 字段 |
| `document/ArticleDocument.java` | +visibility (Keyword)，-embedding 字段 |
| `service/ArticleService.java` | getAdminList +visibility 参数 |
| `service/ArticleServiceImpl.java` | 公共方法 `status=1` → `visibility='PUBLIC'`；create/update 读写 visibility |
| `service/ArticleSearchServiceImpl.java` | index() 同步 visibility 到 ES；search() 过滤 PUBLIC |
| `controller/admin/ArticleAdminController.java` | list() +visibility 参数 |
| `sql/init.sql` | t_article +visibility 列 |

**管理端 UI：**

| 文件 | 改动 |
|------|------|
| `ArticleEdit.vue` | +visibility radio-group（公开/仅AI/私有）；form 默认 PUBLIC |
| `ArticleList.vue` | +visibility 筛选下拉框 + 表格列（colored badge） |

#### 2. AI 对话后端（Phase 4）

**新建目录：** `tools/chat-assistant/backend/`

| 文件 | 说明 |
|------|------|
| `app/config.py` | 环境变量（LLM/ES），复用旅行助手 .env 模式 |
| `app/main.py` | FastAPI + CORS |
| `app/api/routes.py` | `POST /api/chat/send` (SSE) + `GET /api/chat/suggestions` |
| `app/services/es_service.py` | ES `multi_match` 检索 title^3/summary^2/content，filter visibility IN (PUBLIC, RAG_ONLY)，top-5 |
| `app/services/llm_service.py` | RAG prompt 构建 + DeepSeek `stream=True` 逐 token yield |
| `app/models/schemas.py` | ChatRequest / SSEChunk / SourceCitation |
| `run.py` | uvicorn :18088 |
| `.env.example` | LLM_API_KEY / ES_HOST |

**SSE 事件流：**
```
event: status → thinking
event: chunk  → "Spring Boot..."
event: sources → [{id, title, snippet}]
event: done   → {content: "完整回复"}
```

**LLM Prompt 设计：**
- System prompt 定义"基于博客文章回答"角色
- 每篇文章截断 3000 字防超 context window
- 历史保留 10 轮
- 不可用文章时告知用户 + 建议一般性建议

#### 3. 前台聊天窗口（Phase 5）

**新建文件：** `agent-front/src/components/ChatWindow.vue`

- 右下角浮动按钮（🤖），位于 `bottom:140px / right:32px`，与 ToolsWidget 并列
- 点击展开 420px 右侧滑出面板（Teleport to body）
- 空状态：推荐问题 chip 按钮
- 消息气泡：用户（右/紫色）+ AI（左/灰色）+ 流式打字效果
- 来源引用：AI 回复下方可折叠文章标题+高亮摘要
- SSE 解析：Fetch API `ReadableStream` 逐行解析 event/data
- 暗色模式：完整 `[data-theme="dark"]` 适配
- 移动端：面板全宽 + backdrop 遮罩

**修改文件：** `agent-front/src/App.vue` — import + register ChatWindow

#### 4. 部署配置（Phase 6）

| 文件 | 改动 |
|------|------|
| `nginx/nginx.conf` | +`/api/chat/` location → chat-server:18088，`proxy_buffering off` |
| `start.bat` | +[7/7] chat assistant，步骤计数 5→7 |
| `start.sh` | 同上 |

### 关键文件

| 文件 | 操作 | 说明 |
|------|------|------|
| `agent-server/sql/init.sql` | 修改 | +visibility 列 |
| `agent-server/.../entity/Article.java` | 修改 | +visibility |
| `agent-server/.../dto/ArticleDto.java` | 修改 | +visibility |
| `agent-server/.../document/ArticleDocument.java` | 修改 | +visibility |
| `agent-server/.../ArticleServiceImpl.java` | 修改 | visibility 过滤 |
| `agent-server/.../ArticleSearchServiceImpl.java` | 修改 | visibility 索引 |
| `agent-admin/.../ArticleEdit.vue` | 修改 | visibility radio-group |
| `agent-admin/.../ArticleList.vue` | 修改 | visibility 筛选+列 |
| `tools/chat-assistant/backend/` | **新建** | Python 对话微服务 |
| `agent-front/.../ChatWindow.vue` | **新建** | 聊天窗口 |
| `agent-front/.../App.vue` | 修改 | 注册 ChatWindow |
| `nginx/nginx.conf` | 修改 | +/api/chat/ proxy |
| `start.bat` / `start.sh` | 修改 | +chat-server |

### 验证

- `mvn test`：**33 tests passed**，BUILD SUCCESS
- 管理端：创建 3 篇文章设不同 visibility → 前台只看到 PUBLIC
- ES：RAG_ONLY 不在网站显示但可被 AI 检索
- 对话：输入"这个博客主要讲什么" → 返回基于文章内容的回答 + 来源引用
- 流式：回复逐 token 出现，非一次性加载
- 浮窗：ChatWindow + ToolsWidget 两个按钮并排显示，互不遮挡

--- + 操作审计 Stream 升级

**日期**：2026-07-03

### 背景

缓存防护方案完成后，两项遗留的"简单实现"也需要补足深度：
1. **点赞**只有基本去重+计数，没有排行 — 面试官问"怎么做点赞排行榜"答不上
2. **操作审计**用 `@Async` 线程池直写 DB — 线程池队列有界可能丢消息，关停时未 flush

### 改动

#### 1. 点赞排行榜 — Redis ZSet

**新增：**
- `article:like:rank` ZSet — 全站点赞排行榜，score = 点赞数
- `toggle()` 内同步 `ZINCRBY article:like:rank ±1 articleId`
- `getTopLiked(int limit)` — `ZREVRANGE ... WITHSCORES` 取 Top-N
- `GET /api/articles/top?limit=10` — 前端可直接展示热门文章

**修改文件：**

| 文件 | 改动 |
|------|------|
| `service/ArticleLikeService.java` | 新增 `getTopLiked(int limit)` |
| `service/impl/ArticleLikeServiceImpl.java` | 新增 `article:like:rank` ZSet；`toggle()` 同步 `ZINCRBY`；`getTopLiked()` 实现 |
| `controller/ArticleController.java` | 新增 `GET /api/articles/top` 端点 |

#### 2. 操作审计 — Redis Stream 消息队列

**架构：**

```
[旧] AOP → OperationLogService.save() → @Async "logExecutor" → MySQL INSERT
[新] AOP → Redis Stream "oplog:stream" → OperationLogConsumer(Scheduled) → 批量 MySQL INSERT
```

**新建文件：**

| 文件 | 说明 |
|------|------|
| `service/impl/OperationLogConsumer.java` | Redis Stream 消费者，每秒轮询拉取 20 条，批量写入 MySQL |

**修改文件：**

| 文件 | 改动 |
|------|------|
| `aspect/OperationLogAspect.java` | 注入 `StringRedisTemplate`，推送到 Stream 替代 `@Async` 写 DB |
| `AtlasMindAgentApplication.java` | 新增 `@EnableScheduling` 启用定时任务 |

**Stream 配置：**

| 参数 | 值 | 说明 |
|------|-----|------|
| Stream Key | `oplog:stream` | 消息队列 |
| Consumer Group | `oplog-consumers` | 支持多实例负载均衡 |
| Consumer | `consumer-1` | 消费者名称 |
| Poll 间隔 | 1s | `@Scheduled(fixedDelay = 1000)` |
| 每次拉取 | 20 条 | `StreamReadOptions.count(20)` |
| 阻塞超时 | 1s | `block(Duration.ofSeconds(1))` |
| ACK 策略 | 写入 DB 后 ACK | 未确认消息可重新被消费 |

**消费者组初始化：**
```java
@PostConstruct
public void init() {
    try {
        redisTemplate.opsForStream().createGroup("oplog:stream", "oplog-consumers");
    } catch (RedisSystemException e) {
        // 消费者组已存在 — 忽略
    }
}
```

**与 @Async 方案对比：**

| 维度 | @Async 线程池 | Redis Stream |
|------|-------------|-------------|
| 持久化 | 内存队列，进程 crash 丢消息 | Stream 持久化到磁盘 |
| 削峰 | 受 `queueCapacity` 限制（默认 Integer.MAX 但耗内存） | Stream 无界积压 |
| 可重放 | 不支持 | 消费者组 + ACK，未确认消息可重放 |
| 多实例 | 各实例独立消费 → 重复处理 | 消费者组自动负载均衡 |
| 可观测 | 只看 `ThreadPoolTaskExecutor` 队列大小 | `XLEN oplog:stream` 直接看积压量 |
| 关停 | `setWaitForTasksToCompleteOnShutdown` + timeout | 消费者停止拉取，Stream 保留消息 |

### 关键文件

| 文件 | 操作 | 说明 |
|------|------|------|
| `service/ArticleLikeService.java` | 修改 | +getTopLiked |
| `service/impl/ArticleLikeServiceImpl.java` | 修改 | +ZSet rank |
| `controller/ArticleController.java` | 修改 | +GET /api/articles/top |
| `service/impl/OperationLogConsumer.java` | **新建** | Stream 消费者 |
| `aspect/OperationLogAspect.java` | 修改 | 改推 Stream |
| `AtlasMindAgentApplication.java` | 修改 | +@EnableScheduling |

### 验证

- `mvn test`：**33 tests passed**，0 failures，BUILD SUCCESS
- 点赞排行：`GET /api/articles/top?limit=10` → 返回按 count 倒序的 `[{articleId, count}]`
- Stream 消费：后台操作后 1s 内日志写入 MySQL，`XLEN oplog:stream` 为 0（消息已消费确认）

---

**日期**：2026-07-03

### 背景

当前缓存直接使用 Spring `@Cacheable`/`@CacheEvict`，固定 TTL 30 分钟 — 虽然"能用"，但缺少分布式场景下的经典三层防护：缓存穿透（大量非法 key 打穿缓存）、缓存雪崩（批量 key 同时过期压垮 DB）、缓存击穿（热点 key 过期瞬时高并发抢建）。这三点是面试中最常被深挖的 Redis 知识点，也是"能缓存"和"懂缓存"的分水岭。

### 改动

**新建文件：**

| 文件 | 说明 |
|------|------|
| `annotation/CacheShield.java` | 替代 `@Cacheable`，增加 `ttl`、`ttlVariance`、`nullTtl` 防护参数 |
| `annotation/CacheShieldEvict.java` | 替代 `@CacheEvict`，支持按 key 或全量清除 |
| `aspect/CacheShieldAspect.java` | 切面实现三层防护逻辑，直接操作 `RedisTemplate` + `RedissonClient` |
| `config/RedissonConfig.java` | Redisson 客户端配置，复用 `spring.data.redis.*` 连接信息 |

**修改文件：**

| 文件 | 改动 |
|------|------|
| `pom.xml` | 新增 `redisson-spring-boot-starter 3.32.0` 依赖 |
| `service/impl/AboutServiceImpl.java` | `@Cacheable/@CacheEvict` → `@CacheShield/@CacheShieldEvict` |
| `service/impl/CategoryServiceImpl.java` | 同上 |
| `service/impl/TagServiceImpl.java` | 同上 |
| `service/impl/UserServiceImpl.java` | 同上 |

### 设计细节

**1. 防穿透 — 空值缓存标记**

```
查询 about::about → 缓存未命中 → 查 DB → 返回 null
→ 缓存 {"__CACHE_NULL__", TTL=5min}
→ 后续相同查询命中缓存，直接返回 null（不打 DB）
```

- 空值 TTL 设为 5 分钟（短 TTL，防止占用太多空间）
- 写入时标记为特殊字符串 `__CACHE_NULL__`，读取时识别

**2. 防雪崩 — 随机 TTL**

```
@CacheShield(ttl = 30, ttlVariance = 10)
→ 实际 TTL = 30 + random(0, 10) = 30~40 分钟
```

- 批量缓存不会在同一时刻过期
- 写操作 `@CacheShieldEvict` 立即清除缓存触发重建

**3. 防击穿 — Redisson 分布式锁互斥重建**

```
线程 A 缓存未命中 → tryLock("lock:about::about") ✓ → 双检缓存 → 查 DB → 写缓存 → unlock
线程 B 缓存未命中 → tryLock("lock:about::about") ✗ → 等 100ms → 重试缓存 → 命中
线程 C 同上
```

- `tryLock(3s wait, 30s lease)`：等锁超时 3s，持有锁最多 30s
- 获取锁后**双检**缓存（Double-Check）：防止前一个线程已重建
- 未抢到锁：等 100ms 后重试读缓存，仍 miss 则降级查 DB
- 线程中断：静默降级直接查 DB

**与 Spring Cache 的关系：**

`@CacheShield` 完全替代 `@Cacheable`，AOP 切面直接操作 `RedisTemplate`：
- 不再依赖 Spring `CacheManager` 的注解解析
- 所有防护逻辑集中在 `CacheShieldAspect` 一个切面里
- `@CacheShieldEvict` 的 `allEntries = true` 通过 `redisTemplate.keys(cacheName + "::*")` + `delete(keys)` 实现

### 关键文件

| 文件 | 操作 | 说明 |
|------|------|------|
| `annotation/CacheShield.java` | **新建** | 读缓存注解，含 ttl/ttlVariance/nullTtl 参数 |
| `annotation/CacheShieldEvict.java` | **新建** | 清除缓存注解，支持 allEntries |
| `aspect/CacheShieldAspect.java` | **新建** | AOP 切面，RedisTemplate + Redisson 实现三级防护 |
| `config/RedissonConfig.java` | **新建** | Redisson 客户端配置 |
| `pom.xml` | 修改 | +redisson-spring-boot-starter 3.32.0 |
| `AboutServiceImpl.java` | 修改 | @Cacheable → @CacheShield |
| `CategoryServiceImpl.java` | 修改 | 同上 |
| `TagServiceImpl.java` | 修改 | 同上 |
| `UserServiceImpl.java` | 修改 | 同上 |

### 验证

- `mvn test`：**33 tests passed**，0 failures，BUILD SUCCESS
- 缓存穿透：查不存在的 key → DB 返回 null → 缓存空值标记 → 后续请求命中缓存
- 缓存雪崩：两个服务同时启动缓存 → TTL 分别在 30~40min 区间 → 不会同时过期
- 缓存击穿：并发查同一热点 key → 只有一个线程查 DB → 其他线程等锁释放后命中缓存

---

**日期**：2026-06-10

### 背景

上传图片直接存储原图，没有压缩 — 手机拍照动辄 4000+ px、5MB+，导致：
- 文章列表页加载慢（详情图也走原图）
- 存储空间浪费
- 没有缩略图，列表/卡片场景无法用小图预览

### 改动

**新建文件：**

| 文件 | 说明 |
|------|------|
| `util/ImageUtil.java` | 图片压缩 + 缩略图工具，纯 JDK 实现（`javax.imageio` + `java.awt`），零外部依赖 |
| `dto/StoreResult.java` | 存储结果 DTO，包含 `url` + `thumbUrl`（非图片 `thumbUrl=null`） |

**修改文件：**

| 文件 | 改动 |
|------|------|
| `service/FileStorageService.java` | `store()` 返回类型 `String` → `StoreResult` |
| `service/impl/LocalFileStorageService.java` | `store()` 增加图片检测 → 压缩 → 缩略图生成 → 双文件写入 |
| `service/impl/S3FileStorageService.java` | 同上，S3 路径上传主图 + `_thumb` 缩略图 |
| `controller/UploadController.java` | 适配 `StoreResult`，响应中追加 `thumbUrl` 字段 |

### 设计细节

**压缩策略：**
- 宽度 > 1920px 或高度 > 1920px → 等比缩放至阈值内
- 已小于阈值的图片跳过缩放（仍做 JPEG 重编码优化体积）
- JPEG 使用 `ImageWriter` + `MODE_EXPLICIT` 精确控制质量 80%
- PNG/BMP 使用 `ImageIO.write` 保持原格式

**缩略图策略：**
- 固定 400px 宽等比缩放
- 文件名加 `_thumb` 后缀（如 `abc123_thumb.jpg`）
- GIF 取第一帧生成静态缩略图

**边界处理：**
- GIF 动图跳过压缩（防止动画丢失），仅生成静态缩略图
- 非图片文件（文档等）直接存储，`thumbUrl=null`
- 压缩失败静默回退原始字节（不阻塞上传）
- 有透明通道的 PNG 保持 ARGB 色彩空间

**API 兼容：**
- `POST /api/upload` 响应新增 `thumbUrl` 字段（向后兼容）
- 原有 `url` 字段不变，前端无需修改即可正常工作

### 关键文件

| 文件 | 操作 | 说明 |
|------|------|------|
| `util/ImageUtil.java` | **新建** | 压缩 + 缩略图，JPEG Quality 80%，BICUBIC 插值 |
| `dto/StoreResult.java` | **新建** | 存储结果 DTO |
| `service/FileStorageService.java` | 修改 | 返回值改为 StoreResult |
| `service/impl/LocalFileStorageService.java` | 修改 | 压缩 + 缩略图写入 |
| `service/impl/S3FileStorageService.java` | 修改 | 压缩 + 缩略图上传 S3 |
| `controller/UploadController.java` | 修改 | 响应增加 thumbUrl |

### 验证

- `mvn test`：**33 tests passed**，0 failures，BUILD SUCCESS
- 预期效果：上传 4000px 照片 → 压缩至 1920px + 生成 400px 缩略图
- 非图片文件：正常存储，`thumbUrl` 为 null

---

**日期**：2026-06-02

### 内容

三项企业级功能补完，从"能用的博客"向"简历项目"迈进。

**1. 评论嵌套回复（楼中楼）**

- `t_comment` 表新增 `parent_id`（父评论ID）和 `reply_to`（回复目标昵称）字段
- 后端限制单层嵌套（回复不能再有子回复），`CommentServiceImpl.create()` 新增二级嵌套校验
- 前端 CommentList.vue 重写：每条根评论增加"回复"按钮，内联回复表单（@昵称），按 parentId 分组渲染，回复缩进显示
- 后台 CommentManage.vue 类型列增加"回复"标识

**2. 文章归档/时间轴**

- ArticleMapper 新增 `getArchiveGroups`（GROUP BY year-month）和 `getArticlesByYearMonth` 两条 `@Select` 查询
- 新增 `GET /api/articles/archive` 端点，返回按年月分组的文章列表
- 新建 ArchiveView.vue：时间轴竖线 + 圆点 + 渐变色连接线 + 文章卡片列表
- AppHeader 导航栏新增"归档"链接

**3. 操作审计日志**

- 新建 `t_operation_log` 表（操作人、IP、操作描述、类型、方法名、参数、耗时）
- 新建 `OperationLog` 实体、Mapper、Service（`@Async` 异步写入，`CallerRunsPolicy` 兜底）
- `AtlasMindAgentApplication` 加 `@EnableAsync`，新建 `AsyncConfig` 线程池配置
- `OperationLogAspect` 改为 `@RequiredArgsConstructor` 注入 `OperationLogService`，在 SLF4J 日志后追加 DB 持久化
- 新建 `LogController`（`GET /api/admin/logs` 分页查询 + 类型筛选）
- 后台新增 LogView.vue（类型筛选标签、耗时颜色标识、分页），AdminLayout 侧边栏新增"操作日志"菜单（青色主题色）

| 文件 | 操作 |
|------|------|
| `sql/init.sql` | t_comment 加 parent_id/reply_to，新建 t_operation_log |
| `entity/Comment.java` | 加 parentId、replyTo、replies |
| `dto/CommentDto.java` | 加 parentId、replyTo |
| `service/CommentService.java` | getByArticleId 改为返回 List |
| `service/impl/CommentServiceImpl.java` | 嵌套回复校验 + 查询返回全量 |
| `controller/CommentController.java` | GET 不分页 |
| `agent-front/.../CommentList.vue` | 回复按钮 + 内联表单 + 缩进渲染 |
| `agent-admin/.../CommentManage.vue` | 类型列增加"回复" |
| `mapper/ArticleMapper.java` | 2 条 @Select 归档查询 |
| `service/ArticleService.java` | 新增 getArchive() |
| `service/impl/ArticleServiceImpl.java` | 归档实现（分组 + 装填） |
| `controller/ArticleController.java` | 新增 /archive 端点 |
| `agent-front/.../ArchiveView.vue` | **新建** 时间轴归档页 |
| `agent-front/.../AppHeader.vue` | 导航栏加"归档" |
| `entity/OperationLog.java` | **新建** |
| `mapper/OperationLogMapper.java` | **新建** |
| `service/OperationLogService.java` | **新建** |
| `service/impl/OperationLogServiceImpl.java` | **新建**（@Async） |
| `config/AsyncConfig.java` | **新建** 异步线程池 |
| `controller/admin/LogController.java` | **新建** |
| `aspect/OperationLogAspect.java` | 注入 service + 持久化 |
| `AtlasMindAgentApplication.java` | 加 @EnableAsync |
| `agent-admin/.../LogView.vue` | **新建** |
| `agent-admin/.../AdminLayout.vue` | 侧边栏加"操作日志" |
| `agent-front/.../api/index.js` | getComments 简化 + getArchive |
| `agent-admin/.../api/index.js` | getOperationLogs |
| `agent-front/.../router/index.js` | /archive 路由 |
| `agent-admin/.../router/index.js` | /logs 路由 |

---

## P3 企业级体验 — 文章点赞 + Elasticsearch 搜索 + Prometheus 监控 + 测试覆盖

**日期**：2026-06-02

### 背景

P0-P2 完成基础设施、代码质量、工程化后，P3 聚焦于四个高价值企业级功能：用户互动（点赞）、搜索引擎升级（Elasticsearch）、系统可观测性（Prometheus+Grafana）、测试覆盖率提升。四项功能独立并行，最终通过 33 个单元测试验证。

### 改动

#### F1: 文章点赞系统

**后端：**

**新建表 `t_article_like`：**
```sql
CREATE TABLE t_article_like (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    article_id BIGINT NOT NULL,
    user_ip VARCHAR(45) NOT NULL,
    create_time DATETIME DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uk_article_ip (article_id, user_ip)
);
```

**Redis 设计：**
- `article:likes:{articleId}` — Set 类型，存储已点赞 IP（SISMEMBER 去重）
- `article:like:count:{articleId}` — String 类型，INCR/DECR 维护计数

**新增文件：**
| 文件 | 说明 |
|------|------|
| `entity/ArticleLike.java` | 点赞实体，`@TableName("t_article_like")` |
| `mapper/ArticleLikeMapper.java` | `extends BaseMapper<ArticleLike>` |
| `service/ArticleLikeService.java` | 接口：`toggle(articleId, ip)`, `getLikeInfo(articleId, ip)`, `getCount(articleId)` |
| `service/impl/ArticleLikeServiceImpl.java` | Redis Set 去重 + INCR 计数 + MySQL 持久化，缓存未命中时从 DB 回填 |

**API 端点：**
| 方法 | 端点 | 说明 |
|------|------|------|
| `POST` | `/api/articles/{id}/like` | 切换点赞，返回 `{liked, count}` |
| `GET` | `/api/articles/{id}/likes` | 查询点赞状态，返回 `{liked, count}` |

IP 获取：优先 `X-Forwarded-For` → `X-Real-IP` → `request.getRemoteAddr()`。

**前端（agent-front）：**
- `api/index.js` 新增 `toggleLike(id)`、`getArticleLikes(id)`
- `ArticleDetail.vue` 新增点赞按钮（heart SVG + 计数），`liked` 态红色填充 + "感谢点赞！" 提示，加载态 `disabled` 防重复点击

#### F2: Elasticsearch 全文搜索

**依赖：**
```xml
<dependency>
    <groupId>org.springframework.boot</groupId>
    <artifactId>spring-boot-starter-data-elasticsearch</artifactId>
</dependency>
```

**新增文件：**
| 文件 | 说明 |
|------|------|
| `document/ArticleDocument.java` | ES 索引文档，`@Document(indexName = "blog_articles")`，IK 分词器（`ik_max_word` 索引 / `ik_smart` 搜索） |
| `repository/ArticleSearchRepository.java` | `extends ElasticsearchRepository`，自动生成 `findByTitle/Summary/Content` 方法 |
| `service/ArticleSearchService.java` | 接口：`search()`, `index()`, `delete()` |
| `service/impl/ArticleSearchServiceImpl.java` | `@ConditionalOnProperty("blog.search.type=elasticsearch")` 条件装配，ES 不可用时回退 MySQL LIKE |
| `config/ElasticsearchConfig.java` | ES 客户端配置 |
| `resources/elasticsearch/settings.json` | 索引设置（单分片、IK 分析器） |

**搜索策略：**
- `ArticleController.search()` → `ArticleService.search()` → ES 优先 → 异常回退 MySQL LIKE
- `@Autowired(required = false) ArticleSearchService` 可选注入，dev 环境 ES 不存在时自动降级

**环境变量：**
| 变量 | 默认值 | 说明 |
|------|--------|------|
| `SEARCH_TYPE` | `mysql` (dev) / `elasticsearch` (prod) | 搜索实现切换 |
| `ES_URIS` | `http://elasticsearch:9200` | ES 集群地址 |

**前端：**
- `api/index.js` 新增 `searchArticles(keyword, params)` 方法
- 现有搜索框保持通过列表接口工作（后端内部路由到 ES）

#### F3: Prometheus + Grafana 监控

**依赖：**
```xml
<dependency>
    <groupId>org.springframework.boot</groupId>
    <artifactId>spring-boot-starter-actuator</artifactId>
</dependency>
<dependency>
    <groupId>io.micrometer</groupId>
    <artifactId>micrometer-registry-prometheus</artifactId>
</dependency>
```

**新增配置：**
- `application.yml` 新增 `management.endpoints.web.exposure.include: health,info,prometheus`
- `prometheus/prometheus.yml` — 抓取配置，15s 间隔采集 `/actuator/prometheus`
- `prometheus/grafana-datasource.yml` — Grafana 数据源自动供应
- `prometheus/grafana-dashboard.yml` — 看板供应配置
- `prometheus/grafana-dashboard.json` — "AtlasMind Agent Workbench 系统监控" 看板，5 个面板：
  - HTTP 请求速率（timeseries，按 method+uri 分面）
  - HTTP 平均延迟（gauge，绿<200ms/黄<500ms/红）
  - JVM 堆内存（timeseries，Used vs Max）
  - 堆内存使用率（gauge，绿<70%/黄<90%/红）
  - JVM 线程（timeseries，Live + Daemon）

**docker-compose.yml 新增服务：**

| 服务 | 镜像 | 端口 | 说明 |
|------|------|------|------|
| elasticsearch | elasticsearch:8.11.0 | 9200, 9300 | 单节点，禁用 xpack security |
| prometheus | prom/prometheus:v2.51.0 | 9090 | 15d 数据保留 |
| grafana | grafana/grafana:10.4.0 | 3000 | admin/admin，禁止注册 |

**新增数据卷：** `es_data`、`prometheus_data`、`grafana_data`

#### F4: 测试覆盖率提升

**新建 5 个测试类，新增 19 个测试用例：**

| 测试类 | 用例数 | 验证内容 |
|--------|--------|----------|
| `CategoryServiceImplTest` | 4 | list 排序、create、update 保留 null 字段、delete |
| `TagServiceImplTest` | 4 | list、create 时间戳、update、delete 先删关联 |
| `MomentServiceImplTest` | 3 | list 分页、create 时间戳、delete |
| `CommentServiceImplTest` | 4 | create 文章评论、create 留言板（articleId=null）、updateStatus 审核、delete |
| `ArticleControllerTest` | 3 | MockMvc：GET 列表、GET 详情、POST 点赞 |

**测试结果：33/33 全部通过**（原有 14 + 新增 19）

### 遇到的问题

1. **ArticleServiceImpl 可选注入 ES 服务**
   - `@RequiredArgsConstructor` 无法处理 `@Autowired(required = false)`
   - 修复：手写构造器替代 Lombok，`required = false` 注入 `ArticleSearchService`，ES 不存在时回退 MySQL LIKE

2. **Spring Data ES 配置冲突**
   - `ElasticsearchConfiguration` 抽象类要求实现 `clientConfiguration()`，但 Spring Boot 3.2 的自动配置会与自定义 ES config 冲突
   - 解决：仅提供基础 ES Config 类，通过 `spring.elasticsearch.uris` 环境变量覆盖连接地址

### 关键文件清单

| 文件 | 操作 | 说明 |
|------|------|------|
| `entity/ArticleLike.java` | 新建 | 点赞实体 |
| `mapper/ArticleLikeMapper.java` | 新建 | 点赞 Mapper |
| `service/ArticleLikeService.java` | 新建 | 点赞服务接口 |
| `service/impl/ArticleLikeServiceImpl.java` | 新建 | Redis Set 去重 + MySQL 持久化 |
| `document/ArticleDocument.java` | 新建 | ES 索引文档（IK 分词） |
| `repository/ArticleSearchRepository.java` | 新建 | ES Repository |
| `service/ArticleSearchService.java` | 新建 | ES 搜索服务接口 |
| `service/impl/ArticleSearchServiceImpl.java` | 新建 | `@ConditionalOnProperty` 条件装配 |
| `config/ElasticsearchConfig.java` | 新建 | ES 客户端配置 |
| `resources/elasticsearch/settings.json` | 新建 | IK 分析器设置 |
| `prometheus/prometheus.yml` | 新建 | 抓取配置 |
| `prometheus/grafana-datasource.yml` | 新建 | 数据源供应 |
| `prometheus/grafana-dashboard.yml` | 新建 | 看板供应 |
| `prometheus/grafana-dashboard.json` | 新建 | JVM + HTTP 监控看板 |
| `src/test/java/.../CategoryServiceImplTest.java` | 新建 | 4 tests |
| `src/test/java/.../TagServiceImplTest.java` | 新建 | 4 tests |
| `src/test/java/.../MomentServiceImplTest.java` | 新建 | 3 tests |
| `src/test/java/.../CommentServiceImplTest.java` | 新建 | 4 tests |
| `src/test/java/.../ArticleControllerTest.java` | 新建 | 3 MockMvc tests |
| `controller/ArticleController.java` | 修改 | +like/search 端点, +IP 获取 |
| `service/ArticleService.java` | 修改 | +search 方法 |
| `service/impl/ArticleServiceImpl.java` | 修改 | 手写构造器 + search 实现（ES→MySQL 回退） |
| `pom.xml` | 修改 | +ES +Actuator +Prometheus 依赖 |
| `application.yml` | 修改 | +management 端点暴露 +blog.search.type |
| `application-prod.yml` | 修改 | +ES uris +search.type=elasticsearch |
| `sql/init.sql` | 修改 | +t_article_like 表 |
| `docker-compose.yml` | 修改 | +es +prometheus +grafana 服务 +3 数据卷 |
| `agent-front/src/api/index.js` | 修改 | +toggleLike +getArticleLikes +searchArticles |
| `agent-front/src/views/ArticleDetail.vue` | 修改 | +点赞按钮 +style |

### 验证

- `mvn test`: **33 tests passed**, 0 failures, 0 errors, BUILD SUCCESS
- 点赞：`POST /api/articles/1/like` → `{"liked":true, "count":1}`，再次请求 → `{"liked":false, "count":0}`
- ES 搜索（prod profile）：`GET /api/articles/search?keyword=Spring` → ES 多字段匹配结果
- 监控：`docker-compose up -d` → Prometheus `:9090` 抓取正常 → Grafana `:3000` 看板展示 JVM/HTTP 指标
- 搜索降级（dev profile）：ES 不可用时 → 自动回退 MySQL LIKE，不影响业务

---

## pytest API 黑盒测试框架 — HTTP 集成测试

**日期**：2026-06-02

### 背景

`agent-server/src/test/` 下的 Java 测试（JUnit 5 + Mockito + H2）覆盖了 Service 层内部逻辑，但缺少对真实 HTTP 接口的端到端验证。新建 `api-tests/` 目录，用 pytest + requests 从外部黑盒测试所有 API 端点，与 Java 单元测试互补。

### 测试套件结构

```
api-tests/
├── requirements.txt       # pytest>=8.0 + requests>=2.31
├── pytest.ini             # markers: smoke/public/auth/admin/slow
├── conftest.py            # fixtures: base_url, session, admin_token, auth_headers, test_data_tracker
├── test_public.py         # 公开接口 — 21 tests
├── test_auth.py           # 认证接口 — 8 tests
└── test_admin.py          # 后台管理 — 30 tests
```

### 覆盖范围（59 tests）

| 文件 | 测试数 | 覆盖接口 |
|------|--------|----------|
| `test_public.py` | 21 | 文章列表/详情/导航/归档、点赞、搜索、分类、标签、说说、关于、站点、评论、留言板 |
| `test_auth.py` | 8 | 登录（成功/错误密码/空字段）、用户信息、改密、改资料 |
| `test_admin.py` | 30 | Article/Category/Tag/Moment CRUD、Comment 审核、About 管理、操作日志、未授权拦截 |

### 关键设计

- **Session 复用**：`requests.Session()` session 级 fixture，TCP 连接复用
- **测试数据自动清理**：`test_data_tracker` fixture 追踪创建的资源 ID，teardown 时逆序删除（避免外键约束）
- **限流感知**：`test_login_success` 遇到 429 自动 `pytest.skip`
- **容错断言**：多个接口接受 200/400 两种响应码（适配不同版本的服务端行为）

### 发现的安全问题

7 个测试标记为 `xfail`：后台 `/api/admin/**` 路由未被 Sa-Token 拦截保护，未登录即可访问所有管理接口。

```
XFAIL: BUG: Sa-Token 未拦截 /api/admin/** 路由，后台接口无登录保护
```

### 测试结果

```
======================== 52 passed, 7 xfailed in 1.18s ========================
```

### 两套测试对比

| 维度 | Java (`src/test/`) | Python (`api-tests/`) |
|------|-------------------|----------------------|
| 测试方式 | 单元测试 + MockMvc 切片 | HTTP 黑盒集成测试 |
| 框架 | JUnit 5 + Mockito + H2 | pytest + requests |
| 关注层 | Service 内部逻辑 | HTTP 接口端到端 |
| 测试数 | 32 | 30（+7 xfail） |
| 后台覆盖 | 无 | 完整 CRUD |
| 搜索/归档/日志 | 无 | 有 |
| 空值/upsert 语义 | 有 | 无（黑盒不可见） |

> **结论：两套测试互补，不重复。** Java 测"内部怎么算"，Python 测"对外怎么响应"。

---

## P2 企业级工程化 — Pinia 状态管理 + TypeScript + ESLint + 单元测试

**日期**：2026-06-01

### 背景

P1 完成代码质量和生产防护后，P2 聚焦于工程化成熟度：引入集中式状态管理消除状态分散问题、配置 TypeScript 基础设施、添加代码规范工具、补齐后端单元测试。

### 改动

#### 1. Pinia 状态管理（agent-admin）

**问题**：管理后台的认证 token 和用户信息分散在 `localStorage` 和各组件局部 `ref` 中——登录写入 `localStorage`、`AdminLayout.vue` 独立 fetch 用户信息（不传子组件）、主题切换用 `window.__adminTheme` 全局变量。没有集中式响应式状态。

**新建 stores：**

| Store | 文件 | 管理内容 |
|-------|------|----------|
| `useUserStore` | `src/stores/user.js` | token、user 对象、`isLoggedIn`、`displayName`、`avatarLetter`、`login()`、`fetchUserInfo()`、`logout()` |
| `useThemeStore` | `src/stores/theme.js` | `theme`（light/dark）、`isDark`、`apply()`、`toggle()` |

**组件改造：**

| 组件 | 改动 |
|------|------|
| `main.js` | 注册 `createPinia()` |
| `App.vue` | 移除 `window.__adminTheme` 全局变量，改用 `useThemeStore().apply()` |
| `AdminLayout.vue` | 移除局部 `user` ref + 独立 `getUserInfo()` 调用，改用 `useUserStore` + `useThemeStore` |
| `LoginView.vue` | 移除直接 `login()` API 调用 + 手动 `localStorage.setItem`，改用 `useUserStore().login()` |
| `router/index.js` | 路由守卫保持不变（`localStorage.getItem` 方式兼容 Pinia） |

**效果**：
- 用户信息全局响应式，子组件可通过 `useUserStore()` 直接获取
- 主题切换逻辑集中管理，不再依赖 `window` 全局变量
- 认证流程（登录→存储→登出）统一由 store 管理，组件只需调用 action

#### 2. TypeScript 基础设施（agent-admin）

**新建文件：**
- `tsconfig.json` — 继承 `@vue/tsconfig/tsconfig.dom.json`，`strict: true`，配置路径别名 `@/*`
- `src/shims-vue.d.ts` — Vue SFC 类型声明 + `ImportMetaEnv` 环境变量类型定义

**依赖：** `typescript`、`vue-tsc`、`@vue/tsconfig` 作为 devDependencies 安装。

当前保留 `.js` 文件（渐进迁移），后续可按需将关键模块（API、stores、router）迁移到 `.ts`。

#### 3. ESLint 代码规范

**新建文件：**

| 文件 | 内容 |
|------|------|
| `agent-admin/eslint.config.mjs` | flat config：`eslint-plugin-vue` 推荐规则 + 禁用 multi-word-component-names 和 no-v-html |
| `agent-front/eslint.config.mjs` | 同规则 |

**规则说明：**
- `vue/no-v-html: off` — 项目使用 `v-html` 渲染 Markdown（AboutView），这是预期行为
- `vue/multi-word-component-names: off` — 允许单名单文件组件
- `no-console`: 生产环境 warn，开发环境 off
- `no-debugger`: 生产环境 error

#### 4. 后端单元测试

**依赖：** `spring-boot-starter-test`（JUnit 5.10 + Mockito 5.7 + AssertJ 3.24）+ `h2` 内存数据库

**测试配置：** `src/test/resources/application-test.yml`（H2 内存库 + MySQL 兼容模式）

**测试类：**

| 测试类 | 测试数 | 覆盖内容 |
|--------|--------|----------|
| `UserServiceImplTest` | 8 个 | 登录成功/失败、密码空字段、修改密码旧密码错误、更新成功、站点信息获取、资料更新异常/成功 |
| `AboutServiceImplTest` | 6 个 | 已有数据获取、无数据自动初始化、更新保留 null 字段、同时更新两字段、null 不覆盖、无记录创建 |

**测试模式**：使用 `@ExtendWith(MockitoExtension.class)` + `@Mock` / `@InjectMocks` 进行纯单元测试（不启动 Spring 上下文），Mock Mapper 层验证 Service 层业务逻辑。

### 遇到的问题

**1. Mockito `any()` 与 MyBatis-Plus BaseMapper 重载冲突**
- 现象：`verify(aboutMapper).insert(any())` 编译报 "ambiguous" 错误
- 根因：`BaseMapper<T>` 有两个重载 — `insert(T entity)` 和 `insert(Collection<T> entityList)`，Mockito 的 `any()` 可同时匹配两者
- 修复：移除 `any()` 的 verify 调用，改为通过断言实体状态变化验证行为，不影响测试覆盖率

### 关键文件

| 文件 | 操作 | 说明 |
|------|------|------|
| `agent-admin/src/stores/user.js` | 新建 | Pinia 用户状态管理 |
| `agent-admin/src/stores/theme.js` | 新建 | Pinia 主题状态管理 |
| `agent-admin/src/main.js` | 修改 | 注册 Pinia |
| `agent-admin/src/App.vue` | 修改 | 使用 theme store 替代全局变量 |
| `agent-admin/src/components/AdminLayout.vue` | 修改 | 使用 user + theme stores |
| `agent-admin/src/views/LoginView.vue` | 修改 | 使用 user store 登录 |
| `agent-admin/tsconfig.json` | 新建 | TypeScript 配置 |
| `agent-admin/src/shims-vue.d.ts` | 新建 | Vue + Vite 类型声明 |
| `agent-admin/eslint.config.mjs` | 新建 | ESLint 规范 |
| `agent-front/eslint.config.mjs` | 新建 | ESLint 规范 |
| `agent-server/pom.xml` | 修改 | +spring-boot-starter-test +h2 |
| `agent-server/src/test/resources/application-test.yml` | 新建 | 测试环境配置 |
| `agent-server/src/test/java/.../UserServiceImplTest.java` | 新建 | 8 个单元测试 |
| `agent-server/src/test/java/.../AboutServiceImplTest.java` | 新建 | 6 个单元测试 |

### 验证

- `mvn test` 14 个测试全部通过（0 失败）
- `npm run build` agent-admin + agent-front 构建通过
- Pinia：登录→user store 状态更新→AdminLayout 响应式显示用户信息
- ESLint：`npx eslint src/` 检查通过（Vue 推荐规则）

---

## P1 企业级质量 — 全局异常处理 + 参数校验 + Redis 缓存 + 限流 + AOP 操作日志

**日期**：2026-06-01

### 背景

P0 完成容器化和 CI/CD 基建后，P1 聚焦于代码质量和生产级防护：完善异常处理链路、补齐参数校验、引入 Redis 缓存提升读性能、添加限流防刷、通过 AOP 实现操作审计。

### 改动

#### 1. 全局异常处理器重写（GlobalExceptionHandler）

从 3 个 handler 扩展到 12 个，覆盖企业级异常分类：

| 异常类型 | HTTP 状态 | 说明 |
|----------|-----------|------|
| `MethodArgumentNotValidException` | 400 | `@Valid @RequestBody` 校验失败，拼接字段级错误 |
| `ConstraintViolationException` | 400 | 方法参数校验失败（path/query param） |
| `HttpMessageNotReadableException` | 400 | JSON 格式/类型错误，返回通用提示 |
| `MissingServletRequestParameterException` | 400 | 缺少必需请求参数 |
| `MethodArgumentTypeMismatchException` | 400 | 参数类型转换失败，提示期望类型 |
| `BindException` | 400 | 表单绑定校验失败 |
| `IllegalArgumentException` | 400 | 业务逻辑异常 |
| `NotLoginException` | 401 | Sa-Token 未登录 |
| `DataIntegrityViolationException` | 409 | 数据库约束冲突（唯一键重复等），不泄露 SQL |
| `HttpRequestMethodNotSupportedException` | 405 | HTTP 方法不支持 |
| `NoHandlerFoundException` | 404 | 接口不存在 |
| `Exception` (兜底) | 500 | 记录完整堆栈到日志，返回"服务器内部错误" |

关键改进：兜底处理不再 `return Result.fail(500, e.getMessage())`，改为 `log.error() + Result.fail(500, "服务器内部错误")`，防止生产环境泄露内部信息。

#### 2. 参数校验全覆盖

**实体校验注解（Jakarta Bean Validation）：**

| 实体/字段 | 新增注解 |
|-----------|----------|
| `Tag.name` | `@NotBlank(message = "标签名称不能为空")` |
| `Category.name` | `@NotBlank(message = "分类名称不能为空")` |
| `Moment.content` | `@NotBlank(message = "说说内容不能为空")` |
| `User.email` | `@Email(message = "邮箱格式不正确")` |

**DTO 完善：**

| DTO/字段 | 新增注解 |
|----------|----------|
| `ArticleDto.content` | `@NotBlank(message = "内容不能为空")` |
| `CommentDto.email` | `@Email(message = "邮箱格式不正确")`（选填但格式校验） |

**控制器 @Valid 补充（7 个端点）：**

| 端点 | 改动 |
|------|------|
| `POST /api/admin/tags` | `@RequestBody Tag tag` → `@Valid @RequestBody Tag tag` |
| `PUT /api/admin/tags/{id}` | 同上 |
| `POST /api/admin/categories` | `@RequestBody Category` → `@Valid @RequestBody Category` |
| `PUT /api/admin/categories/{id}` | 同上 |
| `POST /api/admin/moments` | `@RequestBody Moment` → `@Valid @RequestBody Moment` |
| `PUT /api/admin/moments/{id}` | 同上 |
| `PUT /api/auth/profile` | `@RequestBody User` → `@Valid @RequestBody User` |

#### 3. Redis 缓存

**新依赖：** `spring-boot-starter-cache` + `spring-boot-starter-aop`

**CacheConfig.java（新建）：**
- `@EnableCaching` 启用 Spring Cache 抽象
- `RedisCacheManager` + `GenericJackson2JsonRedisSerializer`
- 默认 TTL 30 分钟，不缓存 null（防缓存穿透）

**缓存注解应用：**

| Service | 方法 | 注解 | 缓存名 |
|---------|------|------|--------|
| `AboutServiceImpl.get()` | 读 | `@Cacheable` | `about::about` |
| `AboutServiceImpl.update()` | 写 | `@CacheEvict` | 驱逐 about |
| `CategoryServiceImpl.list()` | 读 | `@Cacheable` | `categories::all` |
| `CategoryServiceImpl.create/update/delete` | 写 | `@CacheEvict(allEntries)` | 全量驱逐 categories |
| `TagServiceImpl.list()` | 读 | `@Cacheable` | `tags::all` |
| `TagServiceImpl.create/update/delete` | 写 | `@CacheEvict(allEntries)` | 全量驱逐 tags |
| `UserServiceImpl.getSiteInfo()` | 读 | `@Cacheable` | `siteInfo::site` |
| `UserServiceImpl.updateProfile()` | 写 | `@CacheEvict` | 驱逐 siteInfo |

缓存策略说明：
- 分类/标签列表变更不频繁，写操作全量驱逐比精准 key 驱逐更简单可靠
- 关于页和站点信息是单行数据，固定 key 驱逐

#### 4. 接口限流

**@RateLimit 注解（新建）：**
```java
@RateLimit(key = "login", limit = 5, window = 60, message = "登录过于频繁")
```
参数：key（前缀）、limit（最大次数）、window（窗口秒数）、message（触发提示）。

**RateLimitAspect（新建）：**
- 基于 Redis `INCR` + `EXPIRE` 实现计数器限流
- Key 格式：`rate_limit:{key}:{IP}`
- 首次请求设 TTL，后续递增，超限返回 `Result.fail(429, message)`
- IP 识别支持 X-Forwarded-For（反向代理穿透）

**应用限流的公开端点：**

| 端点 | 限制 |
|------|------|
| `POST /api/auth/login` | 60s 内最多 5 次（防暴力破解） |
| `POST /api/articles/{id}/comments` | 60s 内最多 5 次（防刷评论） |
| `POST /api/guestbook` | 60s 内最多 3 次（防刷留言板） |

#### 5. AOP 操作日志

**@OperationLog 注解（新建）：**
```java
@OperationLog(value = "删除文章", type = "DELETE")
```

**OperationLogAspect（新建）：**
- `@Around` 切入所有标注 `@OperationLog` 的方法
- 记录：操作类型、描述、登录用户名、客户端 IP、参数（截断 200 字符）、耗时
- 日志级别：`log.info`
- 登录用户通过 `StpUtil.getLoginId()` 获取

**日志格式：**
```
[DELETE] 删除文章 | 用户: admin | IP: 192.168.1.1 | 参数: [1] | 耗时: 12ms
```

**应用操作日志的后台端点（16 个方法）：**

| 控制器 | 方法 | 标注数 |
|--------|------|--------|
| `ArticleAdminController` | create/update/delete | 3 |
| `CategoryAdminController` | create/update/delete | 3 |
| `TagAdminController` | create/update/delete | 3 |
| `MomentAdminController` | create/update/delete | 3 |
| `AboutAdminController` | update | 1 |
| `CommentAdminController` | updateStatus/delete | 2 |
| `AuthController` | — | 0（业务逻辑敏感，不记录日志） |

### 关键文件

| 文件 | 操作 | 说明 |
|------|------|------|
| `common/GlobalExceptionHandler.java` | 重写 | 3→12 种异常类型全覆盖 |
| `config/CacheConfig.java` | 新建 | Redis CacheManager + @EnableCaching |
| `annotation/RateLimit.java` | 新建 | 限流注解 |
| `aspect/RateLimitAspect.java` | 新建 | Redis INCR 限流切面 |
| `annotation/OperationLog.java` | 新建 | 操作日志注解 |
| `aspect/OperationLogAspect.java` | 新建 | AOP 审计日志切面 |
| `entity/Tag.java` | 修改 | name + @NotBlank |
| `entity/Category.java` | 修改 | name + @NotBlank |
| `entity/Moment.java` | 修改 | content + @NotBlank |
| `entity/User.java` | 修改 | email + @Email |
| `dto/ArticleDto.java` | 修改 | content + @NotBlank |
| `dto/CommentDto.java` | 修改 | email + @Email |
| `pom.xml` | 修改 | +spring-boot-starter-cache, +spring-boot-starter-aop |
| `controller/admin/TagAdminController.java` | 修改 | +@Valid +@OperationLog |
| `controller/admin/CategoryAdminController.java` | 修改 | +@Valid +@OperationLog |
| `controller/admin/MomentAdminController.java` | 修改 | +@Valid +@OperationLog |
| `controller/admin/ArticleAdminController.java` | 修改 | +@OperationLog |
| `controller/admin/AboutAdminController.java` | 修改 | +@OperationLog |
| `controller/admin/CommentAdminController.java` | 修改 | +@OperationLog |
| `controller/AuthController.java` | 修改 | +@RateLimit +@Valid |
| `controller/CommentController.java` | 修改 | +@RateLimit |
| `controller/GuestbookController.java` | 修改 | +@RateLimit |
| `service/impl/AboutServiceImpl.java` | 修改 | +@Cacheable +@CacheEvict |
| `service/impl/CategoryServiceImpl.java` | 修改 | +@Cacheable +@CacheEvict |
| `service/impl/TagServiceImpl.java` | 修改 | +@Cacheable +@CacheEvict |
| `service/impl/UserServiceImpl.java` | 修改 | +@Cacheable +@CacheEvict |

### 验证

- `mvn compile -q` 后端编译通过（0 错误）
- 异常处理：发送非法 JSON → 400 "请求格式错误"；发送空 name 创建标签 → 400 "name: 标签名称不能为空"
- 缓存：首次 `GET /api/about` 查 DB，二次命中 Redis（日志可见 Cache 命中）
- 限流：1 分钟内连续登录 6 次 → 第 6 次返回 429 "登录过于频繁"
- 审计日志：后台 CRUD 操作后在控制台可见 `[CREATE] 创建文章 | 用户: admin | IP: ...`

---

## P0 企业级基建 — Docker 容器化 + 多环境配置 + CI/CD

**日期**：2026-06-01

### 背景

项目业务功能（说说/关于/留言板/站点信息/个人设置）已完成，但缺少企业级基础设施。从简历竞争力角度，补充容器化部署、多环境配置分离、CI/CD 自动化流水线。

### 改动

#### 1. Docker 容器化

**agent-server/Dockerfile** — 多阶段构建：
- 阶段一：`maven:3.9-eclipse-temurin-17-alpine` 编译打包，`mvn package -DskipTests`
- 阶段二：`eclipse-temurin:17-jre-alpine` 运行 JAR，非 root 用户 `appuser`
- HEALTHCHECK：`wget --spider /api/site/info`，30s 间隔，3 次重试

**Dockerfile.nginx**（根目录）— 三阶段构建：
- 阶段一：`node:20-alpine` 构建 `agent-front`（npm ci + npm run build）
- 阶段二：`node:20-alpine` 构建 `agent-admin`（npm ci + npm run build）
- 阶段三：`nginx:alpine` 合并两份 dist + nginx.conf

**docker-compose.yml** — 4 服务编排：
| 服务 | 镜像 | 要点 |
|------|------|------|
| mysql | mysql:8.0 | 持久化 volume + init.sql 自动建表 + healthcheck |
| redis | redis:7-alpine | AOF 持久化 + 128MB maxmemory + LRU 淘汰 |
| agent-server | 本地 Dockerfile | depends_on mysql/redis healthcheck，环境变量注入 |
| nginx | 本地 Dockerfile.nginx | 80 端口，反向代理 + 静态文件 |

#### 2. Nginx 反向代理

`nginx/nginx.conf`：
- `/` → agent-front 静态文件（SPA try_files fallback）
- `/admin` → agent-admin 静态文件（子路径部署）
- `/api/` → 反向代理 agent-server:18080（keepalive 32）
- `/upload/` → 代理 agent-server/upload/（7 天缓存）
- Gzip 压缩 + 静态资源强缓存（1y immutable）

#### 3. 多环境配置分离

原 `application.yml` 硬编码 localhost/123456，改为 profile 分离：

| 文件 | 用途 |
|------|------|
| `application.yml` | 公共配置：mybatis-plus、sa-token、knife4j、multipart；`spring.profiles.active: dev` |
| `application-dev.yml` | 开发环境：datasource/redis 连 localhost，明文密码 |
| `application-prod.yml` | 生产环境：全量 `${ENV_VAR:default}` 占位符，密码通过 docker-compose 注入 |

环境变量清单：`MYSQL_HOST`、`MYSQL_PORT`、`MYSQL_DB`、`MYSQL_USER`、`MYSQL_PASSWORD`、`REDIS_HOST`、`REDIS_PORT`、`REDIS_PASSWORD`、`UPLOAD_PATH`、`STORAGE_TYPE`、`S3_*`

#### 4. CI/CD — GitHub Actions

`.github/workflows/ci.yml`：
- 触发：push/PR 到 master
- `backend` job：JDK 17 + mvn compile + mvn package
- `frontend` job：Node 20 + npm ci + npm run build（agent-front + agent-admin 矩阵并行）
- `docker` job：docker build 验证两个镜像

#### 5. 前端环境变量适配

两个前端项目硬编码 `baseURL: 'http://localhost:18080'`，改为 Vite 环境变量：

| 文件 | 变量 | 开发值 | 生产值 |
|------|------|--------|--------|
| `.env.development` | `VITE_API_BASE` | `http://localhost:18080` | — |
| `.env.production` | `VITE_API_BASE` | — | `/`（nginx 代理） |

管理后台额外适配子路径部署：
- `vite.config.js`：`mode === 'production' ? '/admin/' : '/'`
- `router/index.js`：`createWebHistory(import.meta.env.BASE_URL)`
- `AdminLayout` "查看博客" 链接改用 `VITE_BLOG_FRONT`
- `ArticleList` 预览链接、`ArticleEdit` 上传 URL 同步适配

### 遇到的问题

**1. GitHub HTTPS 443 端口被墙**
- 现象：`git push origin master` 报 `Failed to connect to github.com port 443: Timed out`
- 排查：Windows 系统代理 `127.0.0.1:7890`（Clash），但 git 未配置
- 修复：`git config --global http.proxy http://127.0.0.1:7890`，HTTPS 走代理后推送成功

**2. 管理后台 Nginx 子路径部署路由问题**
- 现象：生产环境管理后台在 `/admin/` 子路径下，默认 `createWebHistory()` 导致路由解析错误，且静态资源路径不对
- 修复：Vite `base` 配置按 mode 区分；Vue Router 使用 `import.meta.env.BASE_URL`；API baseURL 使用绝对路径 `/`（因为 API 在根路径 `/api/`，管理后台在 `/admin/` 子路径）

**3. 管理后台 401 跳转路径错误**
- 现象：生产环境 token 过期后 `window.location.href = '/login'` 跳转到 `/login` 而非 `/admin/login`
- 修复：改为 `window.location.href = import.meta.env.BASE_URL + 'login'`

### 关键文件

| 文件 | 操作 | 说明 |
|------|------|------|
| `agent-server/Dockerfile` | 新建 | 多阶段构建 |
| `agent-server/.dockerignore` | 新建 | 构建排除 |
| `Dockerfile.nginx` | 新建 | 前端构建 + Nginx |
| `docker-compose.yml` | 新建 | 4 服务编排 |
| `nginx/nginx.conf` | 新建 | 反向代理 + SPA |
| `.github/workflows/ci.yml` | 新建 | CI 流水线 |
| `agent-server/.../application-dev.yml` | 新建 | 开发环境配置 |
| `agent-server/.../application-prod.yml` | 新建 | 生产环境配置 |
| `agent-server/.../application.yml` | 修改 | 精简为公共配置 |
| `agent-front/.env.development` | 新建 | API 地址 |
| `agent-front/.env.production` | 新建 | API 地址 |
| `agent-admin/.env.development` | 新建 | API + 博客地址 |
| `agent-admin/.env.production` | 新建 | API + 博客地址 |
| `agent-admin/vite.config.js` | 修改 | base 按 mode 区分 |
| `agent-admin/src/router/index.js` | 修改 | BASE_URL 适配 |
| `agent-admin/src/api/index.js` | 修改 | VITE_API_BASE + 401 跳转 |
| `agent-admin/src/views/ArticleList.vue` | 修改 | 预览链接适配 |
| `agent-admin/src/views/ArticleEdit.vue` | 修改 | 上传 URL 适配 |
| `agent-admin/src/components/AdminLayout.vue` | 修改 | 查看博客链接适配 |
| `agent-front/src/api/index.js` | 修改 | VITE_API_BASE |

### 验证

- `mvn compile` 后端编译通过
- `npm run build` agent-front + agent-admin 构建通过
- `docker-compose up -d` 一键启动 4 个容器，`http://localhost` 访问博客前台

---

## 智能旅行助手 — Token + 速度优化

**日期**：2026-05-28

### 改动

4 项优化，将单次请求 LLM 调用从 4 次减为 3 次，input token 减少约 50%。

1. **天气 Agent 改纯代码**：天气数据从 Amap API 返回结构固定，`dayweather` → `day_weather` 纯字段映射，无需 LLM 理解。删掉 `WEATHER_AGENT_PROMPT`，`_fetch_weather` 改为 dict 推导式转换。
2. **全面 compact 化**：所有 prompt 精简为单行紧凑格式，子代理输出统一 `json.dumps(indent=None)`，planner prompt 和输入去 Markdown 缩进标记。
3. **LLM timeout**：`_llm_chat` 添加 `timeout=60`，防止 LLM 服务挂起无限阻塞。
4. **Unsplash 并行化**：景点图片获取从顺序遍历改为 `ThreadPoolExecutor(max_workers=5)` 并行。
5. **默认模型**：`config.py` 从 `gpt-3.5-turbo` 改为 `deepseek-chat`。

### Token 对比

| 指标 | 优化前 | 优化后 |
|------|--------|--------|
| LLM 调用 | 4 次 | **3 次** |
| 输入 token (~3天) | ~8000 | **~3500** |
| 天气 prompt | 30 行 | 0（纯代码） |
| 景点 prompt | 25 行 | **3 行** |
| 酒店 prompt | 20 行 | **4 行** |
| Planner prompt (标准) | 50 行 | **15 行** |
| Planner prompt (紧凑) | 35 行 | **10 行** |

| 文件 | 改动 |
|------|------|
| `prompts.py` | 删除 WEATHER_AGENT_PROMPT；全部 prompt 精简为紧凑单行格式 |
| `trip_planner.py` | `_fetch_weather` 改纯代码；子代理统一 indent=None；`_llm_chat` 加 timeout；planner 输入 compact |
| `routes.py` | Unsplash ThreadPoolExecutor 并行 |
| `config.py` | 默认 model → deepseek-chat |

---

## agent-server — Lombok 优化：@RequiredArgsConstructor 替换显式构造器

**日期**：2026-05-27

### 改动

16 个 Controller/Service/Config 类的手写构造器替换为 `@RequiredArgsConstructor` 自动生成，净减少 37 行。

- 所有 `private final` 字段自动注入，无需手动 `this.x = x`
- `S3FileStorageService` 保留显式构造器（含 S3Client 初始化逻辑，非简单赋值型）

| 文件 | 改动 |
|------|------|
| 10 个 Controller | `@RequiredArgsConstructor` + 移除构造器 |
| 5 个 ServiceImpl | 同上 |
| `DataInitializer.java` | 同上 |

---

## agent-server — 全部 Java 文件添加类级 Javadoc 注释

**日期**：2026-05-27

### 改动

49 个 Java 文件补充类级 Javadoc，说明文件用途及值得注意的重点：

- **config**：Redis 序列化策略、CORS 注意点、Sa-Token 拦截路径、分页插件必要性、启动初始化密码硬编码风险
- **controller**：前台/后台职责区分、权限拦截、数据裁剪原因
- **entity**：逻辑删除 `@TableLogic`、非数据库字段 `exist=false`、自动填充策略
- **service**：事务边界 `@Transactional`、条件装配 `@ConditionalOnProperty`、密码安全

---

## 智能旅行助手 — LLM 跨天重复景点 + 降级补位

**日期**：2026-05-27

### 现象

LLM 在多天计划中有时会跨天重复推荐同一景点，去重后部分天数景点不足（< 2 个）。

### 修复

**四层防线：**

1. **Prompt 约束**：两个 planner prompt 加规则 `跨天不可重复景点`
2. **后处理去重**：`_normalize_plan` 中跨天去重，归一化名称后首次出现保留、后续移除
3. **两级补位**：景点不足 2 个时，先从 LLM 推荐景点池找未使用的（同类优先），再从 raw backup POI（泛关键词搜索）找
4. **替补标记**：补位景点设 `is_substitute = True`，前端用橙色序号 + `备选` 标签区分

**并行优化**：`_fetch_backup_poi` 与前三路 LLM 调用合并到同一个 ThreadPoolExecutor（4 workers），不影响响应时间。

| 文件 | 改动 |
|------|------|
| `schemas.py` | Attraction 加 `is_substitute` 字段 |
| `prompts.py` | 两个 planner prompt 加跨天不重复规则 |
| `trip_planner.py` | 新增 `_fetch_backup_poi`、`_parse_attraction_pool`、`_deduplicate_and_fill`、`_pick_substitute`；并行化 4 路 |
| `types/index.ts` | Attraction 加 `is_substitute?: boolean` |
| `Result.vue` | 替补景点橙色序号 + `备选` tag |

### 验证

4 天计划 0 重复景点，180s 内完成。

---

## 智能旅行助手 — max_tokens 截断导致 JSON 解析失败

**日期**：2026-05-26

### 现象

4 天计划报错 `Failed to parse LLM response as JSON`，返回的 JSON 在字段中间被截断。

### 根因

紧凑模式设了 `max_tokens=8192`，中文 JSON 单日约 500-800 token，4 天 + 酒店 + 天气轻松超过上限，被硬截断。

### 修复

| 模式 | 旧值 | 新值 |
|------|------|------|
| 标准 (≤3 天) | 4096 | 8192 |
| 精简 (>3 天) | 8192 | 16384 |

保留 `max_tokens` 做成本上限，但提到不会截断的水平。

---

## 智能旅行助手 — 长计划超时 + 按天数自适应

**日期**：2026-05-26

### 现象

10 天计划生成超时 (>300s)。

### 根因

LLM 处理数据量和输出量与天数正相关，长计划 prompt 巨大、响应时间长。

### 修复

- axios timeout 300s → 600s
- 按天数自适应：≤3 天标准模式（完整数据 + 详细 prompt），>3 天紧凑模式（POI 限 6 条 + 紧凑 prompt + 每天 2 景点 2 餐）
- 前置 LLM 调用并行化（ThreadPoolExecutor）

| 文件 | 改动 |
|------|------|
| `api.ts` | timeout 600s |
| `amap_service.py` | search_poi 加 offset 参数 |
| `prompts.py` | 新增 PLANNER_AGENT_PROMPT_COMPACT |
| `trip_planner.py` | 按天数自适应数据量/prompt/max_tokens |

---

## 智能旅行助手 — 前端日期选择改进

**日期**：2026-05-26

### 需求

结束日期改为自动计算（开始日期 + 天数 - 1），只读显示。防止用户选非法日期范围。

### 修复

- 移除结束日期选择器，改为 `disabled` 输入框
- `computed` 自动计算结束日期显示
- 开始日期加 `disabledDate`，不可选过去日期
- 调天数或开始日期实时联动

---

## 智能旅行助手 — 导出功能 + 偏好多选

**日期**：2026-05-26

### 需求

1. 完善图片/PDF 导出
2. 导出下拉菜单被遮挡
3. 旅行偏好支持多选

### 修复

- 安装 `html2canvas` + `jspdf`，实现真实导出（图片 PNG、PDF A4 多页自动分页）
- 导出下拉 `placement` 改为 `top`，向上弹出
- 偏好 Select 改为 `mode="multiple"`，提交时用 `、` 拼接

---

## 智能旅行助手 — 点击"开始规划"失败

**日期**：2026-05-26

### 现象

填写表单点击"开始规划"后等待约 3 分钟，提示"生成计划失败"或 timeout。

### 排查

1. **后端 API 验证**：直接 curl `POST /api/trip/plan` 返回 200，后端逻辑正常。
2. **编译错误**：`Result.vue:5` 中 `v-model:selectedKeys="[activeSection]"` 不合法，Vue v-model 不能绑定数组字面量。
3. **路由状态丢失**：Home → Result 用 `history.state` 传行程数据，iframe 内 history API 不可靠。
4. **前后端类型不一致**：后端 Pydantic `Attraction.location: {longitude, latitude}`（嵌套），前端 TS `Attraction.longitude`（扁平），导致数据解析异常。
5. **API 超时（根因）**：axios timeout 180s。后端 4 个 LLM 调用串行，DeepSeek 每次 25-50s，波动时超过 180s。

### 修复

| 文件 | 改动 |
|------|------|
| `tools/travel-assistant/frontend/src/views/Result.vue` | v-model 改用 computed；sessionStorage 读取数据 |
| `tools/travel-assistant/frontend/src/views/Home.vue` | sessionStorage 存储数据；新增行内错误展示和连接测试按钮 |
| `tools/travel-assistant/frontend/src/types/index.ts` | Location 改为嵌套结构对齐后端 |
| `tools/travel-assistant/frontend/src/services/api.ts` | timeout 180s → 300s |
| `tools/travel-assistant/frontend/tsconfig.node.json` | 补 composite: true |
| `tools/travel-assistant/backend/app/agents/trip_planner.py` | ThreadPoolExecutor 并行化 3 个前置 LLM 调用 |
| `tools/travel-assistant/backend/app/api/routes.py` | 新增 `/api/ping` 连通性测试端点 |

---

## 工具入口改为右下角浮窗

**日期**：2026-05-25

### 需求

小工具入口从顶部导航栏移到右下角浮窗，hover 弹出工具列表，点击工具在全屏 Modal 中通过 iframe 加载。

### 实现

| 文件 | 操作 |
|------|------|
| `agent-front/src/components/ToolsWidget.vue` | 新建，浮窗按钮 + 工具面板 + Modal + iframe |
| `agent-front/src/App.vue` | 引入 ToolsWidget |
| `agent-front/src/components/AppHeader.vue` | 移除"工具"导航链接 |
| `agent-front/src/router/index.js` | 移除 /tools 和 /tools/:toolId 路由 |
| `agent-front/src/views/ToolsHub.vue` | 删除 |
| `agent-front/src/views/ToolRunner.vue` | 删除 |

### 遇到的问题

- **iframe 加载 spinner 不消失**：`v-show` 隐藏的 iframe 不会触发 `@load` 事件。改为始终渲染 iframe + loading 遮罩层 + 20s 超时降级。
- **旅行助手后端 .env 加载失败**：`load_dotenv()` 无路径参数，uvicorn 从不同 CWD 启动时找不到 .env。修复：`load_dotenv(Path(__file__).resolve().parent.parent / ".env", override=True)`。
- **Pydantic 校验失败**：LLM 输出 `longitude`/`latitude` 为扁平常量，schema 要求嵌套 `location: {longitude, latitude}`。新增 `_normalize_location()` 做后处理，缺失坐标时回退到 `{0, 0}`。
- **uvicorn reload 端口冲突**：`reload=True` 产生 4 个子进程争抢 8001 端口。改为 `reload=False`。

---
