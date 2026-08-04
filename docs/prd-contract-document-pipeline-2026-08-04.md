# PRD：合同文档智能处理流水线

日期：2026-08-04  
项目：AtlasMind Agent Workbench — ContractOps  
方向：企业合同生命周期运营 Agent  
阶段：合同文件解析、条款切片、时间节点提取、Embedding 检索、可观测性

---

## 1. 背景

当前系统已经具备合同案件、合同审查 Agent、知识库上传、PDF/MinerU 解析、切片、Embedding 和 ES 检索能力。但合同文件处理链路仍偏轻：

- 前台合同录入主要依赖粘贴文本或简单文件登记。
- 合同原文没有完整复用知识库已有的 PDF/MinerU、切片、Embedding 和 ES 能力。
- DOCX 尚未作为一等合同文件格式处理。
- 合同时间节点目前只能从案件字段、已有义务和简单规则中提取，尚未形成可审计流水线。
- 管理端 AI Observability 已能看 Agent Run，但文档解析、切片、Embedding、索引过程还没有作为独立 Pipeline 展示。

本 PRD 目标是把合同文件处理升级为可审计、可复核、可检索的文档智能处理流水线，为后续合同审查、履约日历、续签评估和证据链引用打基础。

---

## 2. 产品目标

建设一条合同专属文档流水线：

```text
上传合同
  ↓
Java 薄入口保存文件和案件关系
  ↓
Python Document Worker
  ↓
DOCX 原生解析
  ↓
LibreOffice 转 PDF
  ↓
MinerU 页码 / 版面 / OCR 校验
  ↓
条款父节点 + 条款子切片
  ↓
规则提取时间节点候选
  ↓
LLM 复核归类
  ↓
Verifier 防幻觉校验
  ↓
Executor 入库
  ↓
Embedding + contract_chunks 独立 ES 索引
  ↓
READY_FOR_REVIEW
  ↓
用户手动发起合同审查 Agent
```

核心目标：

- 支持 DOCX/PDF/TXT/Markdown 合同上传。
- DOCX 原生解析为主，LibreOffice + MinerU 做版面和页码校验。
- 合同切片独立存储和索引，不混入通用知识库。
- 时间节点先规则提取，再 LLM 复核归类，最后 Verifier 校验入库。
- 人工确认优先，重新解析只生成差异，不自动覆盖。
- 用户端展示业务状态，管理端展示完整技术流水线。
- 文档流水线纳入 AI Observability。

---

## 3. 非目标

本阶段不做以下内容：

- 不做自由多 Agent 群聊式合同解析。
- 不让 LLM 直接写数据库。
- 不把合同原文直接混入通用 `kb_chunks`。
- 不把 PDF/MinerU 结果作为 DOCX 原文的唯一事实源。
- 不自动覆盖用户已确认字段。
- 不默认上传后自动审查合同。

---

## 4. 核心决策

### 4.1 合同原件不进入通用知识库

合同使用独立的合同切片和独立 ES 索引：

```text
kb_chunks          公司制度、标准条款、通用知识库文档
contract_chunks    合同案件私有证据
```

原因：

- 合同有案件权限、商业机密和法律证据链要求。
- Agent 审查必须区分“合同原文证据”和“公司规则知识”。
- 避免普通知识库问答误召回其他合同原文。

### 4.2 DOCX 混合解析

采用：

```text
python-docx 原生解析为主
LibreOffice headless 转 PDF
MinerU 做页码、版面、OCR 校验
```

规则：

- 合同原文、条款编号、表格结构以 DOCX 原生解析为主。
- 页码、版面位置、OCR 内容以 MinerU 为辅助证据。
- 金额、日期、主体、付款条件、违约责任等关键字段冲突时，进入人工复核。
- Agent 不允许静默选择其中一个版本。

### 4.3 条款父节点 + 子切片 Embedding

合同文档结构：

```text
contract_document
  └── contract_clause
        └── contract_clause_chunk
```

检索命中子切片后，Agent 自动带回完整父条款，避免只引用半句话。

### 4.4 时间节点提取 Harness

本阶段不做多 Agent。采用单 Harness：

```text
Rule Extractor
  ↓
LLM Reviewer
  ↓
Verifier
  ↓
Executor
```

职责：

- Rule Extractor：提取日期、相对期限、金额、起算条件、条款号、原文位置。
- LLM Reviewer：归类节点类型，补充业务含义、责任方、复核建议。
- Verifier：检查引用是否真实存在，检查冲突和低置信度。
- Executor：写入 `contract_timeline_node` / `contract_obligation`。

### 4.5 默认手动发起审查

合同解析完成后进入：

```text
READY_FOR_REVIEW
```

用户点击“开始审查”后才启动 `CONTRACT_REVIEW` Agent。

可选：

- 上传时允许勾选“上传完成后自动发起审查”。
- 如果解析冲突、低置信度、缺页或 OCR 不完整，必须阻断自动审查。

---

## 5. 用户故事

### 5.1 业务用户上传 DOCX 合同

作为业务用户，我希望上传 DOCX 合同后，系统自动解析合同结构、提取关键时间节点，并提示我何时可以发起审查。

验收：

- 上传后立即创建合同文件记录。
- 页面显示解析状态。
- 解析完成后展示“可审查”。
- 如果存在冲突，展示“需要复核”，并能看到冲突字段。

### 5.2 法务查看合同时间节点

作为法务，我希望看到合同中的所有重要时间节点，包括生效、到期、付款、验收、通知、续签、解除、逾期宽限等。

验收：

- 时间节点有类型、日期或相对条件、来源条款、原文片段、置信度。
- 低置信度节点不能直接进入履约提醒。
- 人工确认后的节点不被重新解析覆盖。

### 5.3 管理员排查解析失败

作为管理员，我希望在 AI Observability 中看到文档处理流水线的每一步，知道失败发生在 DOCX 解析、PDF 转换、MinerU、Embedding 还是 ES 索引。

验收：

- 管理端新增 Contract Document Pipeline tab。
- 每个 Job 展示阶段、进度、错误、输入/输出摘要。
- 支持关联合同案件、文档、后续 Agent Run。

### 5.4 Agent 审查引用合同证据

作为审查 Agent，我需要同时检索合同原文、标准条款、企业制度和历史案例，并在审查发现中引用具体合同条款。

验收：

- `searchContractClause` 只检索当前案件合同切片。
- `searchKnowledge` 检索通用知识库。
- 审查发现必须包含合同引用和规则引用。

---

## 6. 功能需求

### 6.1 文件上传

支持格式：

- DOCX
- PDF
- TXT
- Markdown

MVP 可先支持 DOCX 和 PDF。

上传入口：

- 用户端合同案件详情。
- 用户端合同发起页。
- 管理端文档管理页。

上传后：

- Java 保存文件和合同文档记录。
- Java 调用 Python Worker 启动解析任务。
- API 不阻塞完整解析过程。

### 6.2 文档处理 Job

新增文档处理任务：

```text
UPLOADED
DOCX_PARSING
PDF_CONVERTING
MINERU_CHECKING
CLAUSE_SPLITTING
TIMELINE_EXTRACTING
LLM_REVIEWING
VERIFYING
EMBEDDING
INDEXING
READY
CONFLICT_REVIEW_REQUIRED
FAILED
```

每个阶段写入 trace：

- stage
- progress
- summary
- input_json
- output_json
- error_message
- started_at
- finished_at

### 6.3 DOCX 原生解析

解析内容：

- 段落
- 表格
- 标题
- 条款编号
- 页眉页脚
- 批注和修订状态，若可行

输出统一结构：

```json
{
  "documentId": 1,
  "parser": "python-docx",
  "blocks": [
    {
      "blockType": "PARAGRAPH",
      "text": "string",
      "style": "string",
      "sequenceNo": 1
    }
  ]
}
```

### 6.4 LibreOffice + MinerU 校验

DOCX 处理时：

- 使用 LibreOffice headless 转 PDF。
- PDF 交给 MinerU。
- MinerU 输出 Markdown/页码/版面证据。
- 与 DOCX 原生解析结果做对齐。

失败策略：

- LibreOffice 失败：保留原生解析结果，标记缺少页码证据。
- MinerU 失败：保留原生解析结果，标记版面校验失败。
- 关键字段冲突：进入 `CONFLICT_REVIEW_REQUIRED`。

### 6.5 条款切分

生成 `contract_clause`：

- clause_number
- title
- content
- clause_type
- page_number
- source_document_id
- content_hash

生成 `contract_clause_chunk`：

- case_id
- document_id
- clause_id
- clause_number
- chunk_index
- chunk_text
- source_page
- content_hash
- embedding_status
- index_status

### 6.6 时间节点提取

规则提取候选：

- 绝对日期：`2026-08-01`、`2026年8月1日`
- 相对期限：`提前7日`、`收到发票后15日内`
- 持续期间：`服务期一年`、`自动续签两年`
- 周期义务：`每季度`、`每月`、`每逾期一日`

LLM 复核输出：

```json
{
  "nodes": [
    {
      "nodeType": "PAYMENT|DELIVERY|ACCEPTANCE|NOTICE|RENEWAL|TERMINATION|PENALTY|OTHER",
      "label": "付款节点",
      "date": "YYYY-MM-DD|null",
      "condition": "收到发票后15日内",
      "responsibleParty": "OUR_ENTITY|COUNTERPARTY|BOTH|UNKNOWN",
      "businessMeaning": "string",
      "confidence": 0.92,
      "contractCitation": {
        "clauseId": 1,
        "clauseNumber": "5.1",
        "quote": "string",
        "page": 3
      }
    }
  ]
}
```

Verifier 检查：

- quote 是否出现在对应条款原文中。
- date/condition 是否来自规则候选或明确原文。
- 是否与案件字段冲突。
- confidence 是否低于阈值。

入库：

- 验证通过：`CONFIRMED_BY_SYSTEM` 或 `EXTRACTED`
- 低置信度：`NEEDS_REVIEW`
- 冲突：`CONFLICT`

### 6.7 Embedding 与检索

合同独立索引：

```text
contract_chunks
```

ES mapping 需要包含：

- chunk_id
- case_id
- document_id
- clause_id
- clause_number
- title
- content
- clause_type
- source_page
- status
- embedding_model
- embedding

检索工具：

- `searchContractClause(caseId, query, topK)`
- `getContractClauseDetail(clauseId)`
- `searchContractTimeline(caseId, query)`
- `searchKnowledge(spaceId, query)`

---

## 7. 数据模型建议

### 7.1 contract_document_job

```sql
CREATE TABLE contract_document_job (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    case_id BIGINT NOT NULL,
    document_id BIGINT NOT NULL,
    job_type VARCHAR(64) NOT NULL DEFAULT 'CONTRACT_DOCUMENT_PIPELINE',
    status VARCHAR(64) NOT NULL DEFAULT 'UPLOADED',
    stage VARCHAR(64) NULL,
    progress INT NOT NULL DEFAULT 0,
    error_message TEXT NULL,
    started_at DATETIME NULL,
    finished_at DATETIME NULL,
    create_time DATETIME DEFAULT CURRENT_TIMESTAMP,
    update_time DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_case_job (case_id, create_time),
    INDEX idx_document_job (document_id, create_time),
    INDEX idx_status (status, create_time)
);
```

### 7.2 contract_document_job_trace

```sql
CREATE TABLE contract_document_job_trace (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    job_id BIGINT NOT NULL,
    stage VARCHAR(64) NOT NULL,
    sequence_no INT NOT NULL,
    summary VARCHAR(500) NOT NULL,
    input_json LONGTEXT NULL,
    output_json LONGTEXT NULL,
    error_message TEXT NULL,
    create_time DATETIME DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uk_job_seq (job_id, sequence_no),
    INDEX idx_job_stage (job_id, stage, sequence_no)
);
```

### 7.3 contract_clause_chunk

```sql
CREATE TABLE contract_clause_chunk (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    case_id BIGINT NOT NULL,
    document_id BIGINT NOT NULL,
    clause_id BIGINT NULL,
    clause_number VARCHAR(64) NULL,
    chunk_index INT NOT NULL,
    chunk_text LONGTEXT NOT NULL,
    source_page INT NULL,
    content_hash CHAR(64) NOT NULL,
    embedding_status VARCHAR(32) NOT NULL DEFAULT 'PENDING',
    index_status VARCHAR(32) NOT NULL DEFAULT 'PENDING',
    create_time DATETIME DEFAULT CURRENT_TIMESTAMP,
    update_time DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_case_chunk (case_id, document_id, chunk_index),
    INDEX idx_clause_chunk (clause_id, chunk_index),
    INDEX idx_embedding_status (embedding_status, index_status)
);
```

### 7.4 contract_timeline_node

```sql
CREATE TABLE contract_timeline_node (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    case_id BIGINT NOT NULL,
    document_id BIGINT NULL,
    clause_id BIGINT NULL,
    node_type VARCHAR(64) NOT NULL,
    label VARCHAR(256) NOT NULL,
    node_date DATE NULL,
    condition_text VARCHAR(512) NULL,
    responsible_party VARCHAR(64) NULL,
    business_meaning TEXT NULL,
    citation_json LONGTEXT NULL,
    confidence DECIMAL(5,4) NULL,
    source VARCHAR(64) NOT NULL DEFAULT 'EXTRACTED',
    status VARCHAR(64) NOT NULL DEFAULT 'EXTRACTED',
    manual_override TINYINT NOT NULL DEFAULT 0,
    create_time DATETIME DEFAULT CURRENT_TIMESTAMP,
    update_time DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_case_timeline (case_id, node_date),
    INDEX idx_status (status)
);
```

---

## 8. API 建议

### 8.1 Java 用户端 API

```http
POST /api/workspace/contracts/{caseId}/documents/upload
GET  /api/workspace/contracts/{caseId}/documents/{documentId}/pipeline
POST /api/workspace/contracts/{caseId}/documents/{documentId}/pipeline/retry
GET  /api/workspace/contracts/{caseId}/timeline
PATCH /api/workspace/contracts/timeline/{nodeId}
```

### 8.2 Java 管理端 API

```http
GET /api/admin/ai-observability/document-pipelines
GET /api/admin/ai-observability/document-pipelines/{jobId}
POST /api/admin/ai-observability/document-pipelines/{jobId}/retry
```

### 8.3 Python Internal API

```http
POST /internal/contracts/documents/{documentId}/pipeline/start
GET  /internal/contracts/documents/pipeline/{jobId}
```

---

## 9. 前端设计

### 9.1 用户端

合同案件详情：

- 文件列表显示业务状态：
  - 上传完成
  - 解析中
  - 待复核
  - 可审查
  - 处理失败
- 文件详情展示：
  - 条款数量
  - 时间节点数量
  - 是否有冲突
  - 是否已建立索引

首页合同卡片：

- 展示前 5 个时间节点。
- 节点显示日期或相对条件。
- 鼠标悬浮显示来源条款和提取方式。

### 9.2 管理端

AI Observability 新增：

```text
Contract Document Pipeline
```

展示：

- Job 列表
- 合同案件
- 文件名
- 当前阶段
- 进度
- 错误信息
- trace 数量
- chunk 数量
- timeline node 数量
- embedding/index 成功数量
- 关联 Agent Run

详情：

- 阶段 timeline
- 每阶段 input/output JSON
- MinerU 转换结果摘要
- DOCX/MinerU 冲突摘要
- ES indexing 明细
- 后续 Agent Run 链接

---

## 10. Agent 工具变更

新增或调整工具：

```text
searchContractClause
getContractClauseDetail
searchContractTimeline
listContractTimeline
searchKnowledge
findStandardClause
```

审查 Agent 检索策略：

```text
1. searchContractClause(caseId, query)
2. getContractClauseDetail(clauseId)
3. searchKnowledge(spaceId/projectId, query)
4. findStandardClause(clauseType)
5. 生成双引用发现
```

---

## 11. 分阶段实施计划

### Phase 1：数据结构与状态模型

目标：

- 新增文档流水线表。
- 新增合同 chunk 和 timeline node 表。
- 扩展 contract_document 状态字段。

交付：

- Migration SQL。
- Java 查询 API。
- 管理端空页面/列表接口。

验收：

- 上传合同后能创建 pipeline job。
- 管理端能看到 job 和 trace。

### Phase 2：Python DOCX 解析 Worker

目标：

- 支持 DOCX 原生解析。
- 输出统一 `ParsedContractDocument`。
- 生成 `contract_clause`。

交付：

- `contract_docx_parser.py`
- `contract_document_pipeline.py`
- trace 写入。

验收：

- DOCX 合同能解析出条款。
- 表格文本能进入条款或附件块。
- 失败能写入 job trace。

### Phase 3：LibreOffice + MinerU 校验

目标：

- DOCX 转 PDF。
- PDF 交给 MinerU。
- 对齐 DOCX 与 MinerU 结果。

交付：

- LibreOffice converter。
- MinerU adapter 复用。
- conflict detection。

验收：

- PDF 页码能回填到条款或 chunk。
- 关键字段冲突进入 `CONFLICT_REVIEW_REQUIRED`。
- LibreOffice/MinerU 失败可降级。

### Phase 4：合同 chunk + Embedding + ES

目标：

- 建立 `contract_chunks` 独立索引。
- 复用 EmbeddingService。
- 支持合同私有语义检索。

交付：

- `ContractChunkStore`
- `ContractSearchService`
- `searchContractClause` 工具。

验收：

- 只检索当前 caseId 的合同切片。
- 命中子切片后能返回父条款。
- ES/Embedding 失败可降级关键词检索。

### Phase 5：时间节点提取 Harness

目标：

- 规则提取候选节点。
- LLM 复核归类。
- Verifier 校验引用。
- Executor 写入 `contract_timeline_node`。

交付：

- `contract_timeline_extractor.py`
- `contract_timeline_reviewer.py`
- `contract_timeline_verifier.py`
- 时间节点用户端展示。

验收：

- 能提取日期、相对期限、周期义务。
- 每个节点有原文引用。
- 低置信度和冲突节点进入人工复核。

### Phase 6：AI Observability 集成

目标：

- 管理端展示完整文档 Pipeline。
- Pipeline 与 Agent Run 互相关联。

交付：

- `/api/admin/ai-observability/document-pipelines`
- 管理端 tab。
- 详情 trace drawer。

验收：

- 管理员能定位失败阶段。
- 能看到 chunk、timeline、embedding、indexing 统计。
- 能跳转关联 Agent Run。

---

## 12. 验收指标

功能指标：

- DOCX/PDF 合同上传后可异步解析。
- 解析完成后能发起合同审查。
- 合同时间节点可展示并可追溯。
- Agent 审查能引用合同条款和知识库规则。

质量指标：

- 解析失败不影响案件存在。
- 关键字段冲突不自动覆盖人工确认。
- 合同检索必须按 caseId 隔离。
- 每个 Agent 结论必须能追溯到 source clause。

可观测性指标：

- 每个文档 job 至少记录 5 个关键阶段 trace。
- 每个失败 job 必须有 error_message。
- 管理端能看到每阶段耗时。

---

## 13. 风险与对策

### 13.1 LibreOffice 转换差异

风险：Word 与 LibreOffice 渲染存在分页或字体差异。  
对策：DOCX 原生解析为主，PDF/MinerU 只做页码和版面辅助。

### 13.2 MinerU 部署复杂

风险：MinerU 依赖较重，可能无法在所有环境启用。  
对策：配置开关，失败降级，不阻断原生解析。

### 13.3 LLM 幻觉时间节点

风险：LLM 生成不存在的节点。  
对策：LLM 只能复核候选或必须提供 quote；Verifier 校验 quote 是否存在。

### 13.4 合同隐私泄露

风险：合同内容进入通用知识库，被其他问答召回。  
对策：合同独立索引，caseId 过滤，工具层强制权限边界。

### 13.5 重复解析覆盖人工确认

风险：重新解析覆盖用户已确认字段。  
对策：manual_override 字段，重解析只生成 diff。

---

## 14. 推荐下一步

先做 Phase 1 + Phase 2：

1. 新增 `contract_document_job`、`contract_document_job_trace`、`contract_clause_chunk`、`contract_timeline_node`。
2. Python 增加 DOCX 原生解析。
3. Java 上传合同后创建 job 并调用 Python Worker。
4. 管理端 AI Observability 先展示 Document Pipeline 的 job 和 trace。

这样能最快证明：

- 合同文档处理不再只是 TXT。
- DOCX 可以进入标准解析链路。
- 管理端能看到处理过程。
- 后续 MinerU、Embedding、时间节点可以继续挂上去。
