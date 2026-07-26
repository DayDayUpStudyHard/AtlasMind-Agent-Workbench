# AtlasMind Agent Workbench

面向企业内部知识资产管理、RAG 检索和 Agent 问答的智能工作台。

AtlasMind Agent Workbench 不是个人站点系统，而是一个用于后端 + Agent 实习展示的工程项目：Java 后端负责业务 API、权限、任务、通知和 AI Gateway；Python AI 服务负责文档解析、切片、Embedding、检索和回答生成；Vue 管理端负责知识治理、导入进度和 RAG 调试；Vue 用户端提供类 ChatGPT 的问答入口。

## 应用场景

企业团队可以把接口文档、部署手册、项目复盘、制度 SOP、FAQ、会议纪要等资料导入系统。员工通过 AtlasMind AI 提问，系统从授权知识源中召回内容，生成带引用来源的回答。管理员可以查看文档导入进度、失败原因、检索 TopK、召回来源、问答日志和权限边界。

典型问题：

- 这个项目本地怎么启动？
- 某个接口的鉴权规则是什么？
- 超期退款需要走什么流程？
- 最近一次线上故障的根因和修复动作是什么？

## 技术栈

| 层级 | 技术 |
| --- | --- |
| Java 后端 | Spring Boot 3.2.5, Java 17, MyBatis-Plus, Sa-Token |
| 数据层 | MySQL 8.x, Redis, Elasticsearch |
| AI 服务 | Python FastAPI, OpenAI-compatible LLM API, Embedding API |
| 文档解析 | pypdf, PaddleOCR 可选, MinerU provider 预留 |
| 管理端 | Vue 3, Element Plus, md-editor-v3 |
| 用户端 | Vue 3, Naive UI, marked |
| 工程化 | Docker Compose, Nginx, Prometheus, Knife4j |

## 项目结构

```text
AtlasMind-Agent-Workbench/
├── agent-server/                 # Java 业务后端与 AI Gateway
├── agent-admin/                  # 管理端：知识治理、内容管理、RAG 调试
├── agent-front/                  # 用户端：知识门户与 AtlasMind AI
├── tools/chat-assistant/backend/ # Python AI 微服务
├── agent-server/sql/             # 初始化 SQL 与增量脚本
├── nginx/                        # 部署反向代理配置
├── prometheus/                   # 监控配置
└── Debug修复记录.md              # 工程排查与迭代记录
```

## 本地端口

为避免和原个人站点同时启动时冲突，新项目使用独立端口：

| 服务 | 地址 |
| --- | --- |
| Java 后端 | http://localhost:18080 |
| 管理端 | http://localhost:15173 |
| 用户端 | http://localhost:15174 |
| Python AI 服务 | http://localhost:18088 |
| Knife4j API 文档 | http://localhost:18080/doc.html |

## 数据库

新项目数据库名为 `atlasmind_agent`，与原项目数据库隔离。

初始化：

```bash
mysql -u root -p < agent-server/sql/init.sql
```

`init.sql` 只包含企业知识工作台需要的表结构和少量示例数据，不包含原个人站点文章、说说或上传文档切片。

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

## 核心能力

- 知识内容管理：结构化维护技术方案、制度 SOP、项目复盘等内容源。
- 文档知识库：支持 Markdown、TXT、PDF 文档导入，记录解析、切片、Embedding、索引状态。
- 分层 PDF 解析：`FAST` 读取文字层，`OCR` 对扫描页调用 PaddleOCR，`MINERU` 预留高质量解析 provider。
- RAG 检索：以向量检索为主，关键词 fallback 兜底，支持 TopK 配置。
- 权限隔离：`PUBLIC` 可进入普通搜索和 RAG；`PRIVATE`、`DISABLED` 永远不可被 RAG 检索。
- Java AI Gateway：统一鉴权、参数校验、超时、异常包装和 Python AI 服务调用。
- 任务与通知：上传后异步导入，前端轮询任务状态，消息中心展示成功或失败。
- 可观测性：问答链路记录检索方式、召回来源、相似度、耗时、失败原因。

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

## 简历表达

可以把项目描述为：

> 设计并实现 AtlasMind Agent Workbench，基于 Spring Boot + Vue + Python FastAPI 的企业知识资产管理与 Agent 问答平台，支持文档异步导入、三档 PDF 解析、向量检索 + 关键词 fallback、权限隔离 RAG、Java AI Gateway、任务通知和问答可观测性。

重点不是“套了一个 AI 聊天框”，而是展示后端系统如何接入 Agent：数据建模、权限边界、异步任务、检索链路、异常处理和可观测性都在项目里落地。
