# AtlasMind Agent Workbench

## 2026-07-30 update: blog domain removed

AtlasMind has been cleaned up as an enterprise R&D Agent Workbench. The legacy blog/CMS domain is no longer part of the active product surface:

- Removed article/category/tag/comment/moment/about backend APIs and their service/mapper/entity code.
- Removed blog routes and pages from both `agent-admin` and `agent-front`.
- Reframed the admin app as an Agent operations console: projects, knowledge sources, evidence sync, Agent runs, reports/approvals, observability, connectors, logs, and settings.
- Rewrote `agent-server/sql/init.sql` so a fresh database initializes Agent, RAG, trace, project, evidence, report, approval, user, setting, and operation-log tables only.
- Added `agent-server/sql/drop_legacy_blog_tables.sql` for existing local databases; it drops `t_article`, `t_category`, `t_tag`, `t_comment`, `t_moment`, `t_about`, and article relation tables.
- Existing local legacy blog tables were dropped after confirmation that local data can be discarded.

The product boundary is now: **single enterprise/R&D team internal deployment, first user = tech lead or engineering manager, first scenario = project health analysis and delivery planning Agent**.

面向软件研发团队的项目理解、风险分析、交付规划与自动化执行 Agent 平台。

> 当前产品方向：**研发项目智能交付 Agent**
>
> 当前 MVP：**项目健康分析与交付计划 Agent**

AtlasMind 不再以博客文章或普通聊天问答作为核心，而是把一个真实的软件项目作为 Agent 的工作对象。Agent 可以读取 GitHub / GitLab / 本地项目代码、技术文档、Issue、PR、Commit 和构建测试结果，基于可引用证据分析项目状态，生成报告和交付计划，并在人工审批后推动研发流程执行。

## 产品目标

AtlasMind 的目标不是“接入一个大模型做问答”，而是构建一个可追踪、可恢复、可审批的研发 Agent 工作流：

```text
项目代码 / 技术文档 / Git / Issue / PR / CI
                    ↓
              项目上下文构建
                    ↓
         RAG 检索 + Tool Calling
                    ↓
       多 Agent 分析 / 规划 / 校验
                    ↓
       健康报告 / 风险清单 / 交付计划
                    ↓
        人工审批后执行研发工具
                    ↓
        任务跟踪 / 结果验证 / 审计
```

核心原则：

- RAG 提供项目事实，避免模型凭空编造。
- Tool Calling 连接真实研发系统，而不是只生成文本。
- Agent Run 保存计划、步骤、工具调用、结果和错误，支持恢复与重试。
- 所有重要结论保留引用、证据和来源版本。
- 创建 Issue、修改代码、创建 PR、部署等动作必须经过权限和审批。

## 首个落地场景

用户导入一个 GitHub 仓库或本地项目，并上传相关技术文档后，AtlasMind 完成：

1. 分析项目目录、技术栈、模块和依赖关系。
2. 检索 README、ADR、接口文档、Commit、Issue 和 PR。
3. 生成项目健康度、架构风险和技术债报告。
4. 支持围绕报告继续多轮追问。
5. 将风险和改进建议拆解为交付计划。
6. 经审批后创建 GitHub Issue 或项目任务。

后续可以扩展到：

- 版本发布风险分析
- Sprint / 周报自动生成
- 依赖和安全风险扫描
- 技术债持续跟踪
- CI 测试失败分析
- 事故根因分析和复盘
- 定时项目健康检查
- 受审批保护的 PR 和任务自动化

## 企业价值

AtlasMind 重点解决研发团队中的重复分析和交付协同问题：

- 减少技术负责人编写项目报告和周报的时间。
- 缩短新人理解大型项目的时间。
- 提前发现架构、依赖、测试和交付风险。
- 把需求、代码、文档、Issue 和 PR 放到同一个分析上下文中。
- 让 Agent 的结论、计划和执行过程可追踪、可审计。

## Agent 能力模型

### RAG

知识源不只包括普通文档，还包括：

- 源代码和代码注释
- README、ADR、技术方案、接口文档
- Git Commit、Issue、Pull Request
- 测试报告、构建日志和部署记录
- 项目复盘、事故记录和历史决策

回答和报告应尽量返回文件路径、代码位置、文档章节、Commit / PR 链接和命中片段。

### Tool Calling

规划中的工程工具包括：

- `searchProjectDocs`
- `inspectRepository`
- `getGitHistory`
- `getPullRequests`
- `analyzeDependencies`
- `runTests`
- `runStaticAnalysis`
- `generateProjectReport`
- `createIssue`
- `createPullRequest`
- `scheduleHealthCheck`

工具需要具备权限、超时、重试、幂等和审批边界。读取和分析工具可以自动执行，写入外部系统的工具需要人工确认。

### 多 Agent

首期只拆分职责清晰的角色，不追求无意义的 Agent 数量：

```text
Orchestrator Agent
├── Repository Analyst：分析代码结构、依赖和变更
├── Documentation Analyst：分析技术文档和项目知识
├── Delivery Analyst：分析进度、Issue、PR 和交付风险
├── Planner Agent：生成任务计划和依赖顺序
└── Reviewer Agent：检查结论、引用和计划质量
```

### 上下文与长期记忆

每次运行由结构化上下文组成：

```text
用户目标
+ 项目基本信息
+ 当前代码版本
+ 检索证据
+ 工具输出
+ 历史结论
+ 用户和团队偏好
+ 当前计划状态
+ 预算、权限和执行限制
```

长期记忆分为：

- 项目事实：技术栈、模块、负责人和部署方式。
- 架构决策：采用某个方案的原因和约束。
- 事故记忆：历史故障、根因和修复动作。
- 团队偏好：报告格式、代码规范和审批要求。
- 任务记忆：上次运行进度、未解决问题和后续动作。

重要记忆需要人工确认后才能写入，不能让模型无条件修改项目事实。

### 微调与模型适配

当前不建议从零预训练基础模型。更适合在评估集成熟后，对轻量任务进行 LoRA 或分类模型微调：

- Issue 分类
- 风险等级判断
- 技术债类型识别
- Agent 工具路由
- 报告结构化输出
- 代码变更影响等级判断

合理分工是：

```text
基础模型：通用推理和规划
RAG：提供最新项目事实
微调模型：稳定分类、路由和结构化输出
Tool Calling：连接真实工程系统
```

## 当前已经落地的基础能力

| 能力 | 当前状态 |
| --- | --- |
| 文档知识库 | 已支持 Markdown、TXT、PDF 导入 |
| PDF 解析 | 已支持 FAST、OCR，MinerU provider 已预留 |
| RAG 检索 | 已支持向量检索和关键词 fallback |
| Citation | 已返回来源、命中片段、相似度和排名 |
| Session | 已保存问答会话和消息 |
| Trace | 已记录检索方式、召回命中和耗时 |
| Tool Call 记录 | 已记录 Embedding、检索和 LLM 调用步骤 |
| 可观测性 | 管理端已具备问答链路查看基础 |
| 评估集 | 已有评估用例和运行结果数据模型 |
| Agent Run | 已落地异步运行、步骤状态、报告快照和审批动作 |
| GitHub 只读证据同步 | 已支持仓库元数据、README、根目录关键文件、Commit、Issue、PR 同步到 `project_evidence` |
| 本地项目 / Jira / 禅道 / CI/CD | 已预留 connector 边界，后续建设 |
| 报告 Artifact | 已支持 Web 报告、Citation 展示和 Markdown 导出 |
| 审批式执行 | 已支持 GitHub Issue 草稿审批与受控执行 |

## 目标导航

博客式内容不是企业研发产品的核心，目标导航调整为：

1. 工作台
2. 项目
3. 知识源
4. Agent
5. 运行记录
6. 报表
7. 自动化
8. 审批与审计
9. 系统设置

当前前台仍保留知识浏览和历史内容页面，作为迁移期兼容入口；后续将逐步移除文章、动态、留言等博客式主流程。

## 技术架构

| 层级 | 技术 |
| --- | --- |
| Java 业务后端 | Spring Boot 3.2.5, Java 17, MyBatis-Plus, Sa-Token |
| Agent Gateway | Java 统一鉴权、会话、任务、通知、工具调用和异常边界 |
| AI 服务 | Python FastAPI, OpenAI-compatible LLM API, Embedding API |
| 数据层 | MySQL 8.x, Redis, Elasticsearch |
| 文档解析 | pypdf, PaddleOCR 可选, MinerU provider 预留 |
| 管理端 | Vue 3, Element Plus, md-editor-v3 |
| 用户端 | Vue 3, Naive UI, marked |
| 工程化 | Docker Compose, Nginx, Prometheus, Knife4j |

### 服务边界

```text
agent-server/
  业务 API、权限、会话、任务、审批、Agent Gateway、审计

tools/chat-assistant/backend/
  文档解析、切片、Embedding、向量检索、RAG 回答、评估

agent-admin/
  项目、知识源、Agent Run、报表、评估和可观测性管理

agent-front/
  研发工作台、项目问答、报告查看和审批入口
```

## 项目结构

```text
AtlasMind-Agent-Workbench/
├── agent-server/                 # Java 业务后端与 Agent Gateway
├── agent-admin/                  # 管理端：知识治理、运行记录、评估与观测
├── agent-front/                  # 用户端：研发工作台与项目 Agent
├── tools/chat-assistant/backend/ # Python AI 微服务
├── agent-server/sql/             # 初始化 SQL 与增量脚本
├── api-tests/                    # HTTP 集成测试
├── nginx/                        # 部署反向代理配置
├── prometheus/                   # 监控配置
├── docs/                         # 架构和实施方案
└── Debug修复记录.md              # 工程排查、设计决策与迭代记录
```

## 本地端口

| 服务 | 地址 |
| --- | --- |
| Java 后端 | http://localhost:18080 |
| 管理端 | http://localhost:15173 |
| 用户端 | http://localhost:15174 |
| Python AI 服务 | http://localhost:18088 |
| Knife4j API 文档 | http://localhost:18080/doc.html |

## 数据库

数据库名为 `atlasmind_agent`，与原项目数据库隔离。

初始化：

```bash
mysql -u root -p < agent-server/sql/init.sql
```

知识库目前使用 `kb_space`、`kb_document`、`kb_document_chunk`、`kb_ingest_job`、`kb_qa_session`、`kb_retrieval_trace`、`kb_retrieval_hit` 和 `kb_tool_call` 等表。

后续将增加项目、代码源、Agent Run、计划步骤、报表 Artifact、审批和自动化任务等领域模型。

## 快速启动

1. 启动 MySQL、Redis、Elasticsearch。
2. 启动 Java 后端：

```bash
cd agent-server
mvnw.cmd spring-boot:run
```

3. 启动 Python AI 服务：

```bash
cd tools/chat-assistant/backend
python run.py
```

4. 启动管理端：

```bash
cd agent-admin
npm install
npm run dev
```

5. 启动用户端：

```bash
cd agent-front
npm install
npm run dev
```

也可以使用根目录 `start.bat` 一键启动本地开发服务。

## AI 服务配置

`tools/chat-assistant/backend/.env.example` 提供配置模板：

```env
LLM_API_KEY=your-llm-api-key
LLM_BASE_URL=https://api.deepseek.com
LLM_MODEL=deepseek-chat

EMBEDDING_API_KEY=your-embedding-api-key
EMBEDDING_BASE_URL=https://api.siliconflow.cn/v1
EMBEDDING_MODEL=Qwen/Qwen3-Embedding-4B
EMBEDDING_DIM=2560

MYSQL_DB=atlasmind_agent
ES_INDEX=agent_contents
KB_INDEX=kb_chunks

PDF_PARSE_PROVIDER=auto
OCR_ENABLED=false
OCR_PROVIDER=paddle
MINERU_ENABLED=false
```

## 分阶段路线

## 首条垂直闭环（已落地）

当前版本已经把第一条研发交付闭环接入前后端，并补上真实 GitHub 证据同步：

```text
项目接入
  → GitHub 只读同步
  → project_evidence 证据沉淀
  → 异步 Agent Run
  → 项目上下文构建
  → project_evidence / RAG 证据检索
  → 项目分析 Agent
  → Evidence Reviewer 核验
  → Delivery Planner 生成计划
  → Web 报告与 Markdown 导出
  → 人工审批
  → GitHub Issue connector
```

已落地模块：

- `agent_project`、`agent_run`、`agent_run_step`、`agent_report`、`agent_action` 数据模型。
- `project_source`、`project_sync_job`、`project_evidence` 数据模型。
- 项目总览首页与项目工作台详情页。
- GitHub 只读同步：仓库元数据、README、根目录文件树、关键配置文件、最近 Commit、Open Issue 和 Open PR。
- Agent Run 优先使用真实 `project_evidence` 作为 Citation，没有同步证据时再回退知识库检索和项目事实。
- 五维健康视图：交付、质量、架构、风险、工程协作。
- 风险证据、交付任务、Agent Run 进度和审批动作展示。
- 异步执行、失败状态、报告快照和 Markdown 导出。
- GitHub Issue 最小权限 connector 边界；未配置 GitHub App Token 时只保留审批草稿，不伪造执行成功。

本阶段仍然只接入 GitHub 方向的最小闭环。本地项目、Jira/禅道、CI/CD 已预留 connector 边界，后续按真实用户验证结果扩展。

### GitHub 证据同步接口

当前 GitHub connector 是只读能力，公开仓库无需 Token，私有仓库可通过 `GITHUB_APP_TOKEN` 配置访问：

| API | 作用 |
| --- | --- |
| `POST /api/projects/{projectId}/sync` | 手动同步 GitHub 证据 |
| `GET /api/projects/{projectId}/evidence` | 查看项目证据列表，可按 `objectType` 过滤 |
| `GET /api/projects/{projectId}/sync-jobs` | 查看同步任务状态、失败原因和计数 |

证据类型包括 `REPO`、`README`、`FILE_TREE`、`FILE`、`COMMIT`、`ISSUE` 和 `PR`。报告中的 citation 会保留类型、标题、来源路径或链接、命中片段和置信分。

### Phase 1：项目健康分析与交付计划

- 导入 GitHub / GitLab / 本地项目。
- 建立代码、文档、Commit、Issue、PR 的统一检索上下文。
- 生成项目健康度、架构、技术债和风险报告。
- 支持报告多轮追问。
- 根据风险生成交付计划。

### Phase 2：研发任务协同

- 连接 GitHub Issues、Jira、禅道或 TAPD。
- 生成任务、验收标准和依赖关系。
- 跟踪任务状态和项目风险。
- 自动生成 Sprint / 周报。

### Phase 3：审批式工程执行

- 执行测试、静态分析和依赖检查。
- 创建 Issue、分支和 PR 草稿。
- 支持人工审批、失败重试和结果校验。
- 保存完整 Agent Run 和审计记录。

### Phase 4：持续交付自动化

- 定时项目健康检查。
- CI/CD 结果分析。
- 发布风险预警。
- 受控的回滚和修复流程。

## 简历表达

> 设计并实现 AtlasMind Agent Workbench，面向软件研发团队提供项目理解、风险分析、交付规划与审批式自动化执行能力。系统基于 Spring Boot + Vue + Python FastAPI 构建，支持文档与代码知识源接入、RAG 检索、Citation、Tool Calling、Agent Run 状态管理、长期项目记忆、报告生成和研发流程审计。

项目重点不是“套了一个 AI 聊天框”，而是把模型接入真实工程流程：项目数据建模、上下文组织、权限边界、异步任务、检索链路、工具调用、失败恢复、人工审批和可观测性都在系统中落地。
