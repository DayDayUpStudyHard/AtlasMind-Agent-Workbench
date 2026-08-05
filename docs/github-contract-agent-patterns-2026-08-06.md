# GitHub 一手资料调研：合同时间节点 Agent 模式

> 文件标识：2026-08-06（按本次任务指定）
> 调研时点：2026-08-05
> 资料范围：只使用 GitHub 官方仓库的 README、源码、官方 issue 或设计文档。
> 目标：调研与 AtlasMind 当前“合同文档解析 -> 时间节点候选 -> 语义增强 -> 证据/检索 -> 人工复核 -> 履约判断”链路相似的问题，并给出可迁移建议。

## 1. 执行摘要

没有一个 GitHub 项目同时解决合同日期语义、PDF 质量、检索融合和业务审批。可迁移的共同模式是：

1. **先做高召回候选，再做语义归一化**：规则负责找日期、期限、触发词和责任方；LLM 负责判断事件类型、锚点关系、义务内容和歧义；日期计算、字段枚举和引用存在性由确定性代码完成。
2. **解析质量是业务前置条件**：文本层存在不等于文本可靠。应保存页级质量信号、解析器尝试链和最终选用结果；质量不足时按页或按文档 fallback，而不是直接把低质量文本送入时间抽取。
3. **引用必须是可验证证据**：至少保留文档版本、页码、文本偏移或稳定块 ID、原文 quote、解析器和内容哈希。只有文档 ID 或模型置信度不能证明一个日期或义务成立。
4. **混合检索要并行召回、再融合、最后按业务主键去重**：BM25/关键词解决数字、条款号和专有名词，向量解决同义表达；RRF 或加权融合解决排名合并；同一条款的多个 chunk 需要按合同版本、条款、页码和原文哈希聚合。
5. **人工复核是状态机，不是布尔字段**：缺少基准日期、多个候选锚点、低质量解析、证据不足和结论冲突都应进入明确的 `WAITING_*` / `NEEDS_REVIEW` 状态，并能从中断节点恢复。

对 AtlasMind 最重要的结论是：**时间节点的“基准日期不确定”不能被当成模型低置信度，而应成为一个需要用户选择的业务状态；规则和 LLM 可以生成候选，但不应替用户选择锚点或确认履约完成。**

## 2. AtlasMind 当前基线

| 当前链路 | 代码/文档位置 | 已有做法 | 调研暴露的主要缺口 |
|---|---|---|---|
| PDF 解析质量 | `tools/chat-assistant/backend/app/services/document_parser.py` | `assess_extracted_text_quality()` 检测乱码、替换字符、异常数字和可疑主体；AUTO 模式按 FAST -> MINERU -> OCR 尝试，并可按页合并 OCR 结果 | 质量评分主要是启发式；页级诊断和“为何选择某解析器”的证据还需要更稳定地持久化 |
| 合同时间节点抽取 | `tools/chat-assistant/backend/app/agent_runtime/contract_document_parser.py`、`app/services/llm_service.py` | 规则候选、`FALLBACK_RULE`、LLM enrichment、`PENDING_CONFIRMATION`、`NEEDS_REVIEW` 已存在 | 候选、锚点、期限单位、日历规则、原文跨度和最终人工选择需要统一成一个可审计字段模型 |
| 规则 + LLM + 校验 | `app/agent_runtime/graph/nodes/domain_tasks.py`、`retrieval.py`、`validation.py`、`app/agent_runtime/schemas/validators.py` | 固定风险域保召回，LLM 增加动态域；高风险发现要求合同/制度引用；报告有 Pydantic 和业务不变量校验 | 时间节点还需要字段级校验：日期可解析、quote 可回指、锚点唯一性、责任方/义务/后果关系一致 |
| 检索 | `tools/chat-assistant/backend/app/services/es_service.py`、`app/agent_runtime/graph/nodes/retrieval.py` | ES 已分别提供 kNN 和 `multi_match`；证据层按 `sourceId` 去重 | 目前不是显式的 RRF/加权融合；`sourceId` 去重不足以消除同一条款的不同 chunk 或不同解析版本 |
| 工作流与人工确认 | `app/agent_runtime/graph/contract_review.py`、`graph/nodes/human_confirm.py`、`migrations/V025__contract_analysis_workflow.sql` | LangGraph 图、人工中断节点、分析工作流表、证据快照哈希和 `WAITING_CONFIRMATION` 已有基础 | 需要区分解析复核、锚点选择、证据补充、履约判定和最终审批等不同等待原因，并保证恢复幂等 |

## 3. GitHub 一手资料与可迁移做法

### 3.1 合同/法律文档时间与义务抽取

#### A. The Atticus Project / CUAD

- 仓库：[`The-Atticus-Project/cuad`](https://github.com/The-Atticus-Project/cuad)
- 关键路径：[`README.md`](https://github.com/The-Atticus-Project/cuad/blob/master/README.md)、[`CUAD_v1.json`](https://github.com/The-Atticus-Project/cuad/blob/master/CUAD_v1.json)
- 做法：
  - 将商业合同拆成固定的条款类别和问题集合，答案保留合同原文中的 span，而不是只保存模型生成的摘要。
  - 类别覆盖合同期限、续期、终止、通知期、付款等与时间节点链路高度相关的条款类型。
  - 通过固定标签集合建立可重复的召回/精度评测基线。
- 优点：
  - 适合把“合同里是否存在某类条款”变成高召回的候选发现任务。
  - 原文 span 使字段抽取和证据展示可以共用一份标注。
  - 标签集合适合转化为 AtlasMind 的强制扫描域或 Golden Dataset。
- 局限：
  - 它是数据集/基准，不是生产级 PDF 解析、日期计算或履约工作流。
  - 条款类别存在不等于已经解析出事件锚点、责任方、期限单位和最终截止日期。
- 对 AtlasMind 的建议：
  - 以 CUAD 类似的固定域建立“时间条款召回集”：签署、生效、交付、验收、付款、续期、终止、通知和宽限期。
  - 每个候选必须保留 `quote + start/end offset + page + clauseId + documentVersion`。
  - 评测分三层：条款候选召回、事件/义务字段准确率、基准日期选择和截止日期计算准确率；不要只看最终报告是否生成。

#### B. Open-Source-Legal / OpenContracts

- 仓库：[`Open-Source-Legal/OpenContracts`](https://github.com/Open-Source-Legal/OpenContracts)
- 关键路径：[`README.md`](https://github.com/Open-Source-Legal/OpenContracts/blob/main/README.md)、[`docs/architecture/PDF-data-layer.md`](https://github.com/Open-Source-Legal/OpenContracts/blob/main/docs/architecture/PDF-data-layer.md)
- 官方设计讨论：[`Issue #1674：Human-in-the-loop support for extraction`](https://github.com/Open-Source-Legal/OpenContracts/issues/1674)
- 做法：
  - 把法律文档作为可定位、可标注、可重复处理的对象；结构化字段抽取与文档标注/原文位置关联。
  - PDF 数据层把解析、文本层、OCR 和后续标注分开，便于更换底层解析器而不丢失文档上下文。
  - 官方 issue 讨论了字段抽取后的人工批准/拒绝、`APPROVAL_NEEDED` 事件和持久化审批结果。
- 优点：
  - 与合同时间节点最接近的启发是：抽取结果不是最终事实，而是“带原文定位的待确认字段”。
  - 文档、标注、字段抽取和人工决定可以形成审计链。
  - 把人工批准建模成事件/状态，有利于批量处理和异步 worker。
- 局限：
  - Issue #1674 是设计讨论，不能当作已完整交付的生产实现。
  - 通用字段抽取不会自动解决中文合同中的相对期限、多个签署日期或条件终止逻辑。
- 对 AtlasMind 的建议：
  - 复用现有 `PENDING_CONFIRMATION`，但把等待原因细分为 `PARSE_QUALITY_REVIEW`、`TIME_ANCHOR_CONFIRMATION`、`FIELD_CONFIRMATION` 和 `EVIDENCE_SUPPLEMENT`。
  - 将人工选择保存为独立事实：选择的候选 ID、操作者、时间、备注、依据版本和前一状态；不要覆盖原始候选。
  - 对每个字段保存 `value`、`normalizedValue`、`explicitness`、`confidence`、`citations`、`validationErrors`，以支持单字段修订而不是整份合同重跑。

### 3.2 OCR/PDF 文字质量检测与多解析器 fallback

#### C. Unstructured

- 仓库：[`Unstructured-IO/unstructured`](https://github.com/Unstructured-IO/unstructured)
- 关键模块：[`unstructured/partition/pdf.py`](https://github.com/Unstructured-IO/unstructured/blob/main/unstructured/partition/pdf.py)
- 做法：
  - `partition_pdf` 暴露 `auto`、`fast`、`hi_res`、`ocr_only` 等策略入口。
  - 将“有文本层的 PDF”“需要布局分析的 PDF”“扫描件 OCR”视为不同处理路径，而不是一个固定解析器。
  - 解析结果带元素类型和元数据，方便后续按页、标题、表格和正文进行处理。
- 优点：
  - fallback 策略显式，适合封装成 AtlasMind 的解析能力矩阵。
  - 适合按文档特征选择成本不同的解析器。
- 局限：
  - `hi_res` 和 OCR 依赖较重，部署能力会影响实际可用路径。
  - `auto` 只解决解析路线选择，不保证日期、数字、表格和中文阅读顺序正确。
- 对 AtlasMind 的建议：
  - 保留现有 FAST/MINERU/OCR 链路，但把 provider 能力和失败原因结构化为 `attempts[]`。
  - 每页计算 `textLength`、非空字符密度、替换字符率、数字/日期可解析率、异常符号率；文档级分数只做汇总。
  - 解析器选择应允许“部分替换”：只替换低质量页，保留其余页的原始文本和引用坐标。

#### D. Docling

- 仓库：[`docling-project/docling`](https://github.com/docling-project/docling)
- 关键模块：[`docling/document_converter.py`](https://github.com/docling-project/docling/blob/main/docling/document_converter.py)、[`docling/datamodel/pipeline_options.py`](https://github.com/docling-project/docling/blob/main/docling/datamodel/pipeline_options.py)
- 官方失败案例：[`Issue #3887：PDF backend failure before OCR fallback`](https://github.com/docling-project/docling/issues/3887)
- 做法：
  - `DocumentConverter` 统一不同输入格式；PDF pipeline options 控制 OCR、布局、表格等能力。
  - 解析阶段暴露后端和 pipeline 选择，适合将“快速文本层”和“高质量结构化解析”分开部署。
  - 官方 issue 显示：底层 PDF backend 发生异常时，可能在后续 OCR 前就中断，需要调用方显式捕获并切换路径。
- 优点：
  - 结构化文档对象比纯字符串更适合保留页、段落、表格和阅读顺序。
  - 可作为高质量解析器或疑难页的升级路径。
- 局限：
  - 依赖和模型体量较大；不同 backend 的错误边界不能假设一致。
  - 解析结构正确不等于法律语义正确，仍需证据和字段校验。
- 对 AtlasMind 的建议：
  - 将 provider 调用包在统一的 `ParseAttempt` 记录中：`provider`、`version`、`pageScope`、`startedAt`、`errorType`、`qualityBefore/After`。
  - 对“backend exception”“无文本”“文本质量低”使用不同 fallback reason，便于统计哪个环节在漏节点。
  - 对时间节点引用优先使用最终选定页的坐标，禁止混用被替换页的旧 quote。

#### E. OCRmyPDF

- 仓库：[`ocrmypdf/OCRmyPDF`](https://github.com/ocrmypdf/OCRmyPDF)
- 关键路径：[`docs/introduction.md`](https://github.com/ocrmypdf/OCRmyPDF/blob/main/docs/introduction.md)、[`src/ocrmypdf/_api.py`](https://github.com/ocrmypdf/OCRmyPDF/blob/main/src/ocrmypdf/_api.py)
- 做法：
  - 提供 `skip-text`、`redo-ocr`、`force-ocr` 等明确模式，分别处理已有文本层、疑似错误文本层和强制重建 OCR 层的场景。
  - 在 OCR 前后保留 PDF 处理与验证步骤，目标是生成可搜索、可继续处理的 PDF。
- 优点：
  - 对“已有文本但不可信”的场景有比单纯 `text length == 0` 更清晰的处理语义。
  - 可以作为文本层修复器，放在高成本语义解析之前。
- 局限：
  - OCRmyPDF 解决的是可搜索文本和 OCR 层，不是合同条款切分、日期归一化或义务判断。
  - 强制 OCR 可能损失原生文本层的精确字符和坐标，必须保留原始 PDF 版本以便审计。
- 对 AtlasMind 的建议：
  - 将“原生文本层”“修复后文本层”“OCR 文本层”视为不同 `contentVersion`，引用绑定到具体版本。
  - 不要因为 OCR 质量分数更高就覆盖原生文本；比较日期、金额、主体名称和条款号等关键字段后再选择。
  - 将 OCR 失败和 OCR 结果低质量都落成可人工复核的解析状态，而不是静默回退到空文本。

### 3.3 规则高召回 + LLM 语义理解 + 字段校验/证据引用

#### F. PydanticAI

- 仓库：[`pydantic/pydantic-ai`](https://github.com/pydantic/pydantic-ai)
- 关键模块目录：[`pydantic_ai_slim/pydantic_ai/`](https://github.com/pydantic/pydantic-ai/tree/main/pydantic_ai_slim/pydantic_ai)，重点关注 agent graph、output/result validator 和 model retry 相关实现。
- 做法：
  - 用类型化输出模型约束 LLM 结果。
  - 输出验证失败时可以触发重试/修正，而不是把不合格结果直接交给业务层。
  - 将工具输入、输出和运行上下文作为显式类型边界。
- 优点：
  - 适合实现“字段格式正确、枚举合法、必填引用存在”的机器校验层。
  - 重试原因可以从普通模型文本中分离出来，便于观测和评估。
- 局限：
  - schema 通过不代表事实有证据；Pydantic 不能证明日期 quote 真的存在于合同原文。
  - 重试只适合格式/局部语义修复，不能用来无限补救召回不足或错误解析。
- 对 AtlasMind 的建议：
  - 保持现有 Pydantic schemas，但增加 `TimelineCandidate`、`AnchorCandidate`、`Obligation` 和 `EvidenceSpan` 的字段级模型。
  - validator 必须检查：`quote` 是 canonical text 的子串、offset 与 quote 一致、日期可解析、相对期限单位合法、选定 anchor 属于候选集合。
  - 任何无法通过证据校验的字段返回 `null/UNKNOWN`，并生成 `NEEDS_REVIEW`，不要让 LLM retry 把“没有证据”变成“看起来完整”。

#### G. CUAD + AtlasMind 现有规则基线的组合

- 外部基准仍是 [CUAD 的固定条款问题和原文 span](https://github.com/The-Atticus-Project/cuad/blob/master/README.md)。
- AtlasMind 的固定高召回入口在 [`domain_tasks.py`](https://github.com/DayDayUpStudyHard/AtlasMind-Agent-Workbench/blob/master/tools/chat-assistant/backend/app/agent_runtime/graph/nodes/domain_tasks.py)，规则/LLM 合流在 [`retrieval.py`](https://github.com/DayDayUpStudyHard/AtlasMind-Agent-Workbench/blob/master/tools/chat-assistant/backend/app/agent_runtime/graph/nodes/retrieval.py)。
- 适合采用三段式：
  1. **规则候选层**：扫描所有疑似日期、数字、期限、触发词、责任主体和条款类型，目标是高召回，允许噪声。
  2. **LLM 语义层**：只在候选窗口内判断 `eventType`、`anchorType`、`obligationAction`、`responsibleParty`、条件逻辑和是否为合同明确要求。
  3. **确定性验证层**：执行日期运算、引用回指、候选集合约束、字段枚举、前后逻辑和状态转换。
- 这种分层比“让一个 prompt 直接输出截止日期”更适合当前链路，因为可以分别评测漏召回、语义误判、日期计算和引用错误。

### 3.4 ES/关键词/向量检索融合与去重

#### H. Elasticsearch 原生 RRF

- 仓库：[`elastic/elasticsearch`](https://github.com/elastic/elasticsearch)
- 关键路径：[`docs/reference/query-languages/query-dsl/compound/rrf.asciidoc`](https://github.com/elastic/elasticsearch/blob/main/docs/reference/query-languages/query-dsl/compound/rrf.asciidoc)、[`RRFQueryBuilder.java`](https://github.com/elastic/elasticsearch/blob/main/server/src/main/java/org/elasticsearch/search/retriever/RRFQueryBuilder.java)
- 做法：
  - 将关键词/BM25、kNN 或其他 retriever 的排序结果合并为一个 RRF 排名。
  - 融合排名而不是直接相加不同量纲的原始分数，减少手工校准 BM25 与 cosine 分数的成本。
- 优点：
  - 与 AtlasMind 当前 ES kNN + `multi_match` 结构直接兼容。
  - 可以让精确条款号、金额、日期和语义近似同时参与召回。
- 局限：
  - RRF 只解决“哪些结果排在前面”，不解决证据是否支持结论。
  - chunk ID 不一致时，ES 只能按文档身份合并；同一条款被切成多个 chunk 仍需业务层聚合。
- 对 AtlasMind 的建议：
  - 在 [`es_service.py`](https://github.com/DayDayUpStudyHard/AtlasMind-Agent-Workbench/blob/master/tools/chat-assistant/backend/app/services/es_service.py) 增加显式混合检索入口，保留 `retrieverType`、排名、原始分数和融合分数。
  - 召回后按 `(caseId, documentVersion, clauseId)` 聚合，再按页码、文本范围和 quote hash 去重；保留每个条款的最佳关键词命中和最佳向量命中。
  - 对时间节点查询提高关键词召回权重或增加日期/条款号过滤，不要只依赖 embedding。

#### I. Haystack DocumentJoiner

- 仓库：[`deepset-ai/haystack`](https://github.com/deepset-ai/haystack)
- 关键模块：[`haystack/components/joiners/document_joiner.py`](https://github.com/deepset-ai/haystack/blob/main/haystack/components/joiners/document_joiner.py)
- 做法：
  - 提供 concatenate、线性分数融合、倒数排名融合等 join 模式，将多个 retriever 的 `Document` 列表合并。
  - 以文档 ID/元数据作为合并基础，并在 join 阶段处理重复结果。
- 优点：
  - 把“多路召回”和“融合排序”分成独立组件，便于离线比较不同融合策略。
  - 可借鉴其显式传递分数、排名和元数据的接口，而不是只返回一串文本。
- 局限：
  - 按 ID 去重只能处理 ID 一致的重复；同一条款的不同 chunk、不同 parser 版本和稍有差异的 quote 仍需领域主键。
  - 通用 joiner 不知道合同版本、生效范围和证据优先级。
- 对 AtlasMind 的建议：
  - 将当前 `_deduplicate_evidence()` 从单一 `sourceId` 去重升级为“证据身份 + 语义近邻”两级去重。
  - 证据身份建议使用 `caseId/documentVersion/clauseId/page/startOffset/endOffset/contentHash`；聚合结果保留 `retrievalSources: ["KEYWORD", "VECTOR"]`。
  - 同一条款多个命中不应简单截断，应该把命中来源、排名和分数合并到一个证据对象中，供 LLM 和前端解释。

### 3.5 工作流与人工复核状态

#### J. LangGraph

- 仓库：[`langchain-ai/langgraph`](https://github.com/langchain-ai/langgraph)
- 关键路径：[`README.md`](https://github.com/langchain-ai/langgraph/blob/main/README.md)、[`libs/langgraph/langgraph/types.py`](https://github.com/langchain-ai/langgraph/blob/main/libs/langgraph/langgraph/types.py)、官方概念文档 [`human_in_the_loop.md`](https://github.com/langchain-ai/langgraph/blob/main/docs/docs/concepts/human_in_the_loop.md)
- 做法：
  - 图节点显式推进状态；`interrupt` 将执行停在需要人处理的位置。
  - checkpointer 保存可恢复状态；人工输入通过 resume 命令回到原图，而不是重新从头跑一遍。
  - 人工确认、工具审批和补充信息都可以建模为不同的中断点。
- 优点：
  - 与 AtlasMind 已有 `ContractReviewGraph`、`human_confirm.py` 和分析工作流表高度匹配。
  - 可以把“等待补证”“选择基准日期”“确认履约结果”拆成可观测、可恢复的节点。
- 局限：
  - LangGraph 只提供编排和恢复，不定义合同事实、权限、审批有效期或幂等规则。
  - 如果把所有业务事实都塞进 graph state，会造成状态与 MySQL 业务表分叉。
- 对 AtlasMind 的建议：
  - 继续让 MySQL 保存合同、候选、证据、人工决定和报告；Graph checkpoint 只保存运行恢复所需的状态。
  - 将 `runId` 映射到稳定的 `threadId`，每个 interrupt 写入等待原因、待处理对象 ID 和证据快照哈希。
  - resume 前检查文档版本和证据快照未变化；变化时转成新的 revision，而不是覆盖旧决定。

#### K. OpenContracts 的人工批准设计

- 设计来源：[`Issue #1674`](https://github.com/Open-Source-Legal/OpenContracts/issues/1674)
- 做法：围绕抽取结果引入显式批准/拒绝事件，将待批准对象、操作者决定和后续流程分开。
- 优点：适合借鉴“抽取成功不等于业务确认”的边界；能把字段级人工修订纳入审计。
- 局限：这是 issue 级设计讨论，不能直接替代 AtlasMind 的状态持久化、权限和 API 设计。
- 对 AtlasMind 的建议：
  - 人工动作至少区分 `CONFIRM`、`SELECT_ANCHOR`、`EDIT_FIELD`、`REQUEST_SUPPLEMENT`、`KEEP_PENDING`、`REJECT`。
  - 结论状态与人工动作分离：人工可以确认“候选有效”，但不能只靠日期自动把履约节点改成“已完成”。

## 4. 面向 AtlasMind 的迁移建议

### P0：把时间节点改成“候选 + 锚点 + 证据 + 状态”

建议最小对象：

```text
TimelineCandidate
  candidateId
  documentId / documentVersion / clauseId
  eventType                  # SIGNED, EFFECTIVE, DELIVERY, ACCEPTANCE, PAYMENT, RENEWAL...
  obligationAction           # 交付、提交、付款、验收、通知等
  responsibleParty
  duration                   # amount + unit + calendarType
  anchorCandidates[]         # 每个候选都有 sourceQuote、sourceSpan、reason
  resolvedDate               # 仅在 anchor 被确定后生成
  sourceQuote / page / offsets
  explicitness               # EXPLICIT_CONTRACT | INFERRED | USER_CONFIRMED
  status                     # EXTRACTED | NEEDS_REVIEW | PENDING_CONFIRMATION | CONFIRMED
  validationErrors[]
```

规则层只负责高召回地产生 `candidateId`；LLM 只能在候选和原文窗口内补充语义；日期运算由确定性函数执行。多个签署日、生效日或“收到通知后 N 日”存在时，`resolvedDate` 保持为空并进入 `TIME_ANCHOR_CONFIRMATION`。

### P0：把解析质量变成可追溯的输入门禁

在现有 `DocumentParser.last_diagnostics` 基础上持久化：

- 每页 `qualityScore`、质量信号、字符密度、日期/数字可解析率；
- `attempts[]`：provider、版本、页范围、错误、输入/输出质量；
- `selectedProvider`、`selectedPageProviders`、`contentHash`、`qualityRuleVersion`；
- 原始文本层、fallback 文本层和最终 canonical text 的关系。

只有达到门禁的页才进入时间候选抽取；低质量页可以产生候选，但候选必须自动标记 `NEEDS_REVIEW`，不能被当成确定事实。

### P1：把规则、LLM、校验拆成可独立评测的三层

1. 规则层：日期、中文大写数字、期限单位、触发事件、责任方、条款编号、通知/付款/验收关键词。
2. LLM 层：事件类型、义务动作、基准事件、条件逻辑、明确合同要求与 AI 建议的区分。
3. 校验层：日期计算、日历规则、quote 回指、候选引用存在、字段枚举、责任方一致性、显式后果与推断后果分离。

报告中应同时保存三类来源：`RULE`、`LLM`、`HUMAN`。`HUMAN` 不是把 LLM 覆盖掉，而是记录最终采用哪个候选以及为什么。

### P1：在 ES 中实现显式混合检索和领域去重

- 关键词与向量并行召回，使用 RRF 或经评测的加权融合。
- 对合同时间节点优先保留包含条款号、日期、金额、单位和通知对象的关键词命中。
- 召回结果先按合同版本和条款聚合，再送给 LLM；不要把多个相邻 chunk 当成多个独立事实。
- 证据对象保留 `keywordRank`、`vectorRank`、`fusionScore`、`retrievalSources` 和 `dedupKey`，方便解释和调参。

### P1：细化人工复核状态

建议将目前的等待状态细化为：

```text
PARSE_QUALITY_REVIEW
INTAKE_CONFIRMATION
TIME_ANCHOR_CONFIRMATION
EVIDENCE_SUPPLEMENT
FULFILLMENT_JUDGEMENT_REVIEW
REPORT_APPROVAL
```

每个等待状态都应持久化：

- `workflowId`、`runId`、`nodeName`；
- 待处理对象 ID，例如 `candidateId`、`requirementId` 或 `findingId`；
- `evidenceSnapshotHash` 和 `documentVersion`；
- 可执行动作集合；
- 操作者、备注、决定时间；
- resume 后的下一个节点和幂等键。

### P2：补一套针对时间链路的评测指标

建议至少建立以下指标：

| 指标 | 含义 |
|---|---|
| Candidate recall | 时间/义务候选是否被规则层找出 |
| Anchor accuracy | 选择签署、生效、通知、验收等基准事件是否正确 |
| Deadline arithmetic accuracy | 自然日、工作日、月末截断和闰年计算是否正确 |
| Citation support rate | 日期、义务和后果是否都能回指原文 |
| Parse escalation success | 低质量页升级解析后，关键字段质量是否提高 |
| Hybrid retrieval recall | 关键词/向量/融合后是否找回金标准证据 |
| Duplicate evidence rate | 同一条款被重复送入语义层的比例 |
| Human override rate | 人工修改候选、锚点或结论的比例 |
| Resume success rate | 人工处理后是否能从正确节点幂等恢复 |

## 5. 不建议直接迁移的部分

- 不建议引入任何一个外部项目的完整工作流或存储模型；AtlasMind 已有 MySQL、Redis、ES、Run/Trace/Report 和前端状态。
- 不建议把 OCR、Docling 或 Unstructured 的输出直接视为法律事实；它们只提供更好的文本/结构候选。
- 不建议让 LLM 直接计算最终截止日期，或用当前日期、上传日期替代缺失锚点。
- 不建议只用一个文档级置信度决定整个合同是否可用；页级质量和字段级证据更重要。
- 不建议用“日期已到”自动把节点改为完成/失败；最终履约状态仍需证据判断和人工确认。

## 6. 来源清单

| Repo | GitHub 路径/模块 | 本次借鉴点 | 主要局限 |
|---|---|---|---|
| [`The-Atticus-Project/cuad`](https://github.com/The-Atticus-Project/cuad) | `README.md`, `CUAD_v1.json` | 固定合同条款标签、原文 answer span、可评测召回 | 基准数据，不是生产解析/工作流 |
| [`Open-Source-Legal/OpenContracts`](https://github.com/Open-Source-Legal/OpenContracts) | `docs/architecture/PDF-data-layer.md`, Issue #1674 | 法律文档定位、解析层与标注分离、抽取后人工批准 | issue 设计不等于完整实现 |
| [`Unstructured-IO/unstructured`](https://github.com/Unstructured-IO/unstructured) | `unstructured/partition/pdf.py` | `auto/fast/hi_res/ocr_only` 解析策略 | 需要额外依赖，不能保证法律语义 |
| [`docling-project/docling`](https://github.com/docling-project/docling) | `docling/document_converter.py`, `docling/datamodel/pipeline_options.py` | 统一转换器、PDF pipeline、OCR/布局选项 | backend 异常和部署成本需要调用方处理 |
| [`ocrmypdf/OCRmyPDF`](https://github.com/ocrmypdf/OCRmyPDF) | `docs/introduction.md`, `src/ocrmypdf/_api.py` | 已有文本层、重做 OCR、强制 OCR 的明确模式 | 解决 OCR 层，不解决合同语义 |
| [`pydantic/pydantic-ai`](https://github.com/pydantic/pydantic-ai) | `pydantic_ai_slim/pydantic_ai/` | 类型化输出、validator、失败重试 | schema 通过不代表有证据 |
| [`elastic/elasticsearch`](https://github.com/elastic/elasticsearch) | `rrf.asciidoc`, `RRFQueryBuilder.java` | 关键词和向量排名融合 | 仍需业务层条款聚合和证据校验 |
| [`deepset-ai/haystack`](https://github.com/deepset-ai/haystack) | `haystack/components/joiners/document_joiner.py` | 多路 Document join、RRF/加权融合、按 ID 处理重复 | ID 不一致时无法做领域语义去重 |
| [`langchain-ai/langgraph`](https://github.com/langchain-ai/langgraph) | `README.md`, `libs/langgraph/langgraph/types.py`, HITL concept doc | interrupt、checkpoint、resume、可恢复人工节点 | 不提供合同业务事实和审批语义 |

## 7. 最终结论

AtlasMind 当前方向是可行的，且已经具备几项关键基础：解析质量检测、规则 fallback、LLM enrichment、Pydantic 报告校验、合同/知识库引用、LangGraph 人工中断和分析工作流表。下一步不应换掉整套架构，而应优先补齐四个可审计边界：

1. **解析器输出 -> canonical text 的质量证据**；
2. **时间候选 -> 基准日期选择的显式状态**；
3. **混合检索 -> 条款级证据聚合和去重**；
4. **人工决定 -> 可恢复、可追溯、不可覆盖历史的工作流事件**。

做到这四点后，规则高召回、LLM 语义理解、字段校验、引用展示和履约人工复核才能连成一条可信的合同时间节点链路。
