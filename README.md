# AtlasMind Agent Workbench - ContractOps

企业合同全生命周期智能运营平台。AtlasMind 将合同文件处理、合同事实、风险审查、履约核验和人工复核组织为可追溯的合同作业系统，而不是只生成一份审查报告。

> 当前状态：生产路径使用 LangGraph v1 任务图和公共 Agent Graph Harness；历史 `legacy` 与风险审查 v2 试验路径保留用于回归对比，不作为新功能的默认实现。

## 核心能力

- 合同创建、PDF/DOCX/DOC/TXT/Markdown 解析、条款切分和页码/段落证据定位。
- 解析质量检测；低质量 PDF 可按配置使用 OCR 或 MinerU 重解析。
- 合同要素提取：少量基础身份字段确定性规范化，合同专属要素由 LLM 按原文动态规划，并保留候选、引用和快照谱系。
- 正式履约日程：规则候选、LLM 语义复核和确定性校验分层执行；不将未复核的候选作为正式日程。
- 风险审查：规则、关键词、向量检索、RRF 融合与重排序协作；补证后会重新分析受影响领域，再生成完整或范围受限报告。
- 履约核验：将合同要求与独立上传的证明材料逐项比对。AI 只能给出证据判断和缺口，最终履约结论必须由人工确认。
- 前台合同工作台、合同范围 Chat、风险处置、修改后合同上传；管理端规则库、知识库、Agent 可观测性和评测中心。

## 六层架构

```text
L1 合同入口与文档解析
   文件 / 正文 -> 解析质量 -> OCR/MinerU（可选）-> 条款与页码定位
                     |
L2 证据快照与混合检索
   合同条款 + 制度库 + 规则库 + 履约证明
   ES 向量/关键词 + MySQL 关键词 + RRF + 分池重排序
                     |
L3 Planner + Harness + LangGraph
   TaskSpec -> 公共 Graph Builder -> Checkpoint / Resume / 节点观测
                     |
L4 业务 Agent
   合同画像 | 履约日程 | 风险审查 | 履约核验
                     |
L5 确定性校验与质量门禁
   Schema、原文引用、证据快照、字段规范化、范围受限披露
                     |
L6 合同作业与人工复核
   确认事实、处理风险、上传证明、人工终审、审计与评测
```

详细设计见 [合同作业系统六层架构](docs/contract-operations-six-layer-architecture-2026-08-08.md) 与 [Agent Harness 迁移 PRD](docs/prd-contract-agent-harness-v1-migration-2026-08-14.md)。

## 任务图与业务边界

| 任务类型 | 图名称 | 主要产物 | 人工边界 |
| --- | --- | --- | --- |
| `CONTRACT_ELEMENT_EXTRACTION` | `contract_extraction` | 合同事实快照、动态合同画像、字段引用 | 可确认或修正事实；已确认字段不会被后续重跑静默覆盖 |
| `TIMELINE_EXTRACTION` | `timeline_extraction` | 正式时间节点、条件、责任方、日期基准与引用 | 可复核节点；低质量/OCR 风险会被显式标记 |
| `CONTRACT_REVIEW` | `contract_review` | 风险发现、合同/制度依据、处理建议、覆盖诊断 | 人工决定处理、接受例外或关闭风险 |
| `FULFILLMENT_CHECK` | `fulfillment_check` | 要求分解、证据比对、AI 建议、缺口 | 图在 `WAITING_HUMAN` 中断，只有人工结论能生成最终履约状态 |

所有任务复用已解析的合同证据和证据快照，不重复 OCR 或全文切分。每次运行冻结图、Prompt、模型、检索、重排序和评分器版本，并记录节点耗时、工具调用、fallback 与预算诊断。

## 产品界面

### 用户端 - `15174`

- 合同工作台：案件、待办、履约和风险概览。
- 合同录入与文件处理：处理进度进入消息中心，用户可离开页面等待后台任务完成。
- 合同详情：合同画像、履约日程、风险研判、合同原文/页码证据、Agent 基础运行状态。
- 事实确认：对要素与时间节点确认、修正或标注待复核。
- 履约处理：向节点上传独立证明材料，查看 AI 的证据判断后人工确认。
- 合同对话：只在当前合同证据范围内回答，并展示来源。

### 管理端 - `15173`

- 合同、文档处理任务、规则库、标准条款库与知识库管理。
- Agent 运行详情：图节点、Trace、工具调用、模型/Prompt/检索版本、错误与范围受限诊断。
- 评测中心：要素提取、履约日程、风险审查、履约核验和综合评测；支持版本比较与 case/artifact/引用追溯。

## 技术架构

| 层 | 实现 |
| --- | --- |
| 业务后端 | Spring Boot 3.2, Java 17, Sa-Token, JdbcTemplate / MyBatis-Plus |
| AI 服务 | FastAPI, LangGraph, Pydantic, OpenAI-compatible LLM / Embedding API |
| 图编排 | `TaskSpec` + 公共 Graph Builder + MySQL Checkpoint + Runtime Router |
| 数据与队列 | MySQL 8, Redis Stream, Elasticsearch 8 |
| 检索 | ES 向量/关键词、MySQL 关键词、规则候选、RRF 融合、合同/制度分池重排序 |
| 前端 | Vue 3, Naive UI（用户端）, Element Plus（管理端） |

### 服务边界

```text
agent-server/                     Java API、鉴权、业务工作流、审批和管理端接口
tools/chat-assistant/backend/     Python 文档处理、Agent Runtime、图、检索与评测执行器
agent-front/                      用户合同工作台
agent-admin/                      管理端：规则、知识库、运行可观测性、评测中心
tools/chat-assistant/backend/
  migrations/                     MySQL 增量迁移（当前 V001-V039）
docs/                             PRD、设计记录、调研与评测报告
```

## 本地启动

### 前置条件

- Java 17+
- Node.js 与 npm
- Python 3.11+
- MySQL 8、Redis、Elasticsearch 8
- 可用的 LLM 服务；Embedding 与 Reranker 可分别配置

启动依赖后，Windows 可运行：

```bat
start.bat
```

或分别启动：

```bash
# Java 后端: 18080
cd agent-server && mvnw.cmd spring-boot:run

# Python AI 服务: 18088（启动时自动执行未应用的 SQL 迁移）
cd tools/chat-assistant/backend && python run.py

# 管理端: 15173
cd agent-admin && npm install && npm run dev

# 用户端: 15174
cd agent-front && npm install && npm run dev
```

| 服务 | 地址 |
| --- | --- |
| Java 后端 | `http://localhost:18080` |
| 管理端 | `http://localhost:15173` |
| 用户端 | `http://localhost:15174` |
| Python AI 服务 | `http://localhost:18088` |
| Java 健康检查 | `http://localhost:18080/actuator/health` |
| Python API 文档 | `http://localhost:18088/docs` |
| Knife4j | `http://localhost:18080/doc.html` |

开发服务器为避免本机端口被短生命周期工具复用导致陈旧页面，用户端响应会带 `Cache-Control: no-store`。如本机浏览器仍有旧的 `localhost` 站点数据，可使用 `http://127.0.0.1:15174` 临时访问。

## AI、检索与文档配置

Python 服务读取 `tools/chat-assistant/backend/.env`。以下是最小示例，所有密钥均应替换为实际值，不能提交到仓库：

```env
# LLM
LLM_API_KEY=replace-me
LLM_BASE_URL=https://api.deepseek.com
LLM_MODEL=deepseek-chat

# Embedding：独立的 OpenAI-compatible 端点；不配置时语义检索降级
EMBEDDING_API_KEY=replace-me
EMBEDDING_BASE_URL=https://api.siliconflow.cn/v1
EMBEDDING_MODEL=Qwen/Qwen3-Embedding-8B
EMBEDDING_DIM=2560
EMBEDDING_TIMEOUT_SECONDS=10

# Reranker：独立配置；不完整或不可用时保留检索结果并记录关键词 fallback
RERANKER_API_KEY=replace-me
RERANKER_BASE_URL=https://api.siliconflow.cn/v1
RERANKER_MODEL=your-reranker-model
RERANKER_TIMEOUT_SECONDS=15

# Data services
MYSQL_HOST=localhost
MYSQL_PORT=3306
MYSQL_USER=root
MYSQL_PASSWORD=replace-me
MYSQL_DB=atlasmind_agent
REDIS_URL=redis://localhost:6379/0
ES_HOST=http://localhost:9200
CONTRACT_INDEX=contract_chunks
KB_INDEX=kb_chunks

# Internal Java <-> Python calls
CHAT_ASSISTANT_TOKEN=replace-with-a-random-token
JAVA_BACKEND_URL=http://localhost:18080

# Optional scan-PDF remediation
PDF_AUTO_REPARSE=true
OCR_ENABLED=false
OCR_PROVIDER=paddle
MINERU_ENABLED=false
```

注意：Embedding 模型与 `EMBEDDING_DIM` 必须匹配。更换模型或维度后必须重建相关 ES 向量索引；没有知识库文档时，风险审查不能被解释为“已覆盖全部制度依据”。

根目录 `.env.example` 是 Docker Compose 的生产部署密钥模板，与 Python 服务的本地 `.env` 用途不同。

## 数据与迁移

核心业务对象包括：

- `contract_case` / `contract_document` / `contract_clause` / `contract_clause_chunk`
- `contract_extraction_snapshot` / `contract_extracted_element` / `contract_timeline_node`
- `contract_review_finding` / `contract_fulfillment_check` / `contract_timeline_evidence_link`
- `agent_run` / `agent_node_execution` / `agent_run_trace` / `agent_report`
- `agent_eval_dataset` / `agent_eval_case` / `agent_eval_run` / `agent_eval_result`

Python 服务启动时会按 `schema_migrations` 执行 `tools/chat-assistant/backend/migrations/V*.sql` 中尚未应用的迁移。不要手工修改已应用迁移；新增结构使用新的版本文件，并保留 Java 启动期的兼容补列逻辑以支持滚动升级。

## 测试与验证

```bash
# Python 后端
cd tools/chat-assistant/backend && python -m pytest -q

# Java 编译
cd agent-server && mvnw.cmd -q compile

# 两个 Vue 项目构建
cd agent-front && npm run build
cd agent-admin && npm run build
```

评测中心只将有效 `COMPLETED` 或有证据支撑的 `LIMITED` 产物交给评分器；环境不可用、无效 Artifact、未注册评分任务会显式标记，不以占位分数充当准确率。履约核验评测还必须提供独立证明材料、唯一目标节点选择器与受控人工结论，不能把实际履约情况混入合同正文。

## 当前质量边界

- LLM 不可用、Embedding/Reranker 失败或 Elasticsearch 不可用时，系统会记录 fallback 与范围限制；不应将降级结果与完整证据结果混为同一质量口径。
- 风险结论需要合同原文和适用制度依据。制度库为空时，双引用覆盖与完整风险覆盖不能视为已通过。
- OCR 低质量、日期基准缺失、乱码或不完整引用的内容会被标记为待复核，不作为自动履约依据。
- 评测结果用于衡量特定数据集与版本组合，不代表所有合同类型的通用准确率。

## 当前评测基线

`contract-review-v1` 数据集已使用 LangGraph v1 和 Elasticsearch 强制检索完成真实重复评测。Run #71、#72、#73 连续三次均通过发布门禁：风险召回 `100%`、双引用率 `100%`、误报率 `0%`、Schema 有效率 `100%`、`LIMITED=0/3`，且没有基础设施失败。

当前生产基线为 **Run #73**。只有状态为 `COMPLETED` 且 `releaseGate.status=PASSED` 的评测运行才能被设置为生产基线；切换基线不会删除历史运行，便于回溯和版本对比。

风险发现分为两层：正式 `findings` 必须同时具备合同引用和政策/标准引用；证据不完整的发现会保留在 `candidateFindings` 候选区，等待补证后再发布，不会被静默删除。

## 相关文档

- [合同作业系统六层架构](docs/contract-operations-six-layer-architecture-2026-08-08.md)
- [Agent Harness 迁移 PRD](docs/prd-contract-agent-harness-v1-migration-2026-08-14.md)
- [高召回证据 DAG PRD](docs/prd-evidence-agent-harness-high-recall-dag-2026-08-14.md)
- [履约核验 Agent 设计](docs/fulfillment-verification-agent-design-2026-08-04.md)
- [Phase 3 v2 试点评测报告](docs/phase3-v2-pilot-report-2026-08-14.md)
- [可复现 Benchmark P0](docs/benchmark-p0.md)
- [可复现 Benchmark P1](docs/benchmark-p1.md)
- [可复现 Benchmark P2](docs/benchmark-p2.md)
- [真实 Benchmark 基线（2026-08-19）](docs/benchmark-real-baseline-2026-08-19.md)
- [调试与修复记录](Debug修复记录.md)
