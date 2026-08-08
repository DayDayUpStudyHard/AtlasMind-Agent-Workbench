# GitHub 一手资料调研：合同首次录入与基础字段识别

> 日期：2026-08-08  
> 范围：标题、甲乙方、合同金额、日期等首次录入字段；不讨论后续风险审查与履约判断。  
> 当前故障样本：规则从“总价 10%”截出 `10 CNY`，覆盖 LLM 已正确提取的 `1860 万元`；标题规则也曾把“合同编号：”当成合同标题。

## 1. 结论先行

GitHub 上没有一个项目可以直接替换 AtlasMind 的合同首次识别模块。成熟项目把问题拆成三类：

1. **文档解析**：Docling、Unstructured、MinerU 负责 OCR、版面、阅读顺序、表格和坐标，不负责判定哪个数字是合同总价。
2. **字段抽取与审阅**：OpenContracts 把字段定义、结构化抽取、来源标注、运行记录和人工批准分开，不把模型结果直接视为已确认事实。
3. **法律抽取评测**：CUAD 用专家标注的合同条款和原文答案跨度评测“是否找对原文”，但它不是生产录入系统。

对 AtlasMind 最重要的共同经验是：

- 解析结果是证据层，不是业务事实。
- 规则适合召回候选和做确定性校验，不适合凭一个置信度直接覆盖 LLM。
- 每个字段必须保存原文、页码/位置、归一化值、候选来源和校验结果。
- `partyA/partyB` 是合同法律角色；`ourEntity/counterparty` 是用户立场，必须在用户选择我方角色后映射。
- 候选只能写入 intake/抽取快照；用户确认后才写入 `contract_case` 的正式字段。
- 后续要素、风险和履约 Agent 应复用已确认事实，不重新识别标题、主体和总金额。

## 2. 项目对比

| 项目 | 它真正解决的问题 | 对首次字段识别的可借鉴点 | 不能直接解决的部分 |
|---|---|---|---|
| Docling | 多格式解析、PDF OCR、版面、阅读顺序、表格和统一文档模型 | 输出结构化 `DoclingDocument`；内容项带层级、版面和来源信息，适合作为字段证据底座 | 不判断“10%”与“合同总价”的业务语义 |
| Unstructured | 根据文档情况选择 `fast`、`hi_res`、`ocr_only` 等解析策略，并输出元素及元数据 | 解析策略显式化；保留元素类型和坐标元数据；失败时可切换策略 | 元素切分不是合同事实抽取，也没有法律字段裁决 |
| MinerU | 扫描件/乱码 PDF、复杂版式、表格、跨页内容和阅读顺序恢复 | 自动检测扫描/乱码并启用 OCR；输出 Markdown/JSON 和 span 可视化；适合中文复杂 PDF | 高质量文字仍可能含 OCR 错字；不会决定甲乙方或总金额 |
| OpenContracts | 文档解析、字段集、结构化抽取、引用图、运行记录、人工批准 | 每个字段作为独立 Datacell；可关联来源 annotation；记录 LLM 调用和错误；支持 approve/reject | 通用字段查询需要 AtlasMind 自己定义中文合同业务校验 |
| CUAD | 专家标注的法律合同审查数据与评测代码 | 用条款类别和原文答案跨度评测召回，而不是只比较模型生成文本 | 是英文法律审查基准，不是 OCR、工作流或中文字段录入系统 |

## 3. 各项目源码中的关键做法

### 3.1 Docling：先建立统一、可定位的文档表示

Docling 支持 PDF、DOCX 等格式，包含 OCR、页面布局、阅读顺序和表格结构，并可导出 lossless JSON。其 `DoclingDocument` 将正文、标题、表格、图片和层级关系组织成统一模型。

可迁移到 AtlasMind：

- 将解析器输出统一为 `DocumentBlock`，至少包含 `text`、`page`、`bbox`、`blockType`、`readingOrder`、`parserVersion`。
- 标题候选优先来自 `TITLE/SECTION_HEADER` 类型的首页块，而不是“前 30 行中最长的含合同二字文本”。
- 金额候选保留整段和相邻表格单元格，避免只截取正则命中的几个字符。
- 解析器可以替换，但字段证据坐标和业务事实接口保持稳定。

来源：

- [docling-project/docling](https://github.com/docling-project/docling)
- [Docling document model](https://github.com/docling-project/docling/blob/main/docs/concepts/docling_document.md)
- [DocumentConverter](https://github.com/docling-project/docling/blob/main/docling/document_converter.py)

### 3.2 Unstructured：解析策略是显式决策，不是静默 fallback

`partition_pdf()` 明确区分 `fast`、`hi_res`、`ocr_only` 和自动策略。`hi_res` 使用布局检测，`ocr_only` 走 OCR，`fast` 使用 PDF 文本层；输出元素可携带坐标等 metadata。

可迁移到 AtlasMind：

- 保存本次文档为何选择原生文本、MinerU 或 OCR，而不是只保存最终纯文本。
- 对主体、金额等关键字段保存它来自哪个解析版本。
- OCR 质量低时重新解析的是证据层；不得让后续每个 Agent 各自重新 OCR。

来源：

- [Unstructured](https://github.com/Unstructured-IO/unstructured)
- [`partition_pdf` implementation](https://github.com/Unstructured-IO/unstructured/blob/main/unstructured/partition/pdf.py)

### 3.3 MinerU：高质量解析是抽取前提，但不是最终判断

MinerU 提供 pipeline、VLM 和 hybrid 等解析方式，支持扫描件、复杂布局、表格、跨页内容、页眉页脚清理和阅读顺序恢复，并输出 Markdown、JSON 和可视化 span。

可迁移到 AtlasMind：

- 对中文复杂 PDF，优先复用 MinerU 的块级 JSON，而不是只使用扁平 Markdown。
- 保留 span 可视化结果，让用户核对金额和主体时能跳到对应页面。
- 在首次识别前做页级质量门禁；解析质量不够时先升级解析方式，再进入字段抽取。
- 不应把 MinerU 的 OCR 文本直接写成正式字段，仍需业务语义裁决和人工确认。

来源：

- [opendatalab/MinerU](https://github.com/opendatalab/MinerU)
- [MinerU documentation](https://opendatalab.github.io/MinerU/)

### 3.4 OpenContracts：字段结果、证据和人工批准分开

OpenContracts 使用 Fieldset 定义一组字段，每个 Column 定义查询和输出类型；每个文档与字段形成独立 Datacell。抽取结果可以关联来源 annotation，保存处理状态、错误和 LLM 调用历史，并具有人工 approve/reject 流程。解析器、向量化器和缩略图组件可以替换，下游接口不变。

这是最接近 AtlasMind 首次录入的参考：

- 一次识别可以覆盖多个基础字段，但每个字段独立保存候选、证据、状态和人工决定。
- Pydantic/类型校验保证 JSON 结构，不代表业务事实正确；仍需要字段级校验器。
- LLM 或 Agent 可以提出字段值，但不能绕过标准审批门禁。
- 人工确认后的 annotation/Datacell 才能成为后续流程复用的事实。

来源：

- [Open-Source-Legal/OpenContracts](https://github.com/Open-Source-Legal/OpenContracts)
- [Structured data extraction](https://github.com/Open-Source-Legal/OpenContracts/blob/main/docs/extract_and_retrieval/data_extraction.md)
- [Custom extractors](https://github.com/Open-Source-Legal/OpenContracts/blob/main/docs/walkthrough/advanced/write-your-own-extractors.md)
- [PDF data layer](https://github.com/Open-Source-Legal/OpenContracts/blob/main/docs/architecture/PDF-data-layer.md)

### 3.5 CUAD：评测必须看原文跨度和漏检

CUAD 将合同审查描述为从长合同中寻找关键条款，并提供专家标注的数据与评测代码。它的价值不是生产架构，而是强调：抽取质量必须基于类别覆盖、原文答案和漏检情况评测。

可迁移到 AtlasMind：

- 为标题、主体、总金额、签署日期等字段建立带原文跨度的金标样本。
- 金额评测不能只判断“输出是数字”，还应判断金额类型和引用位置。
- 单独统计误把比例、保证金、违约金、单价和分期款当作合同总价的错误率。

来源：

- [The-Atticus-Project/cuad](https://github.com/The-Atticus-Project/cuad)
- [CUAD paper](https://arxiv.org/abs/2103.06268)

## 4. AtlasMind 当前实现与成熟做法的差异

当前首次识别大致为：

```text
解析后的纯文本
  -> 正则生成 deterministic_hints
  -> LLM 同时读取合同片段和 hints
  -> validate_extraction 校验引用
  -> 规则置信度 >= 0.78 时可覆盖 LLM
  -> 人工确认前回填 contract_case
```

主要问题：

1. **规则同时承担召回和裁决**：`总价10%` 的局部匹配可以覆盖 LLM 对完整价款条款的理解。
2. **引用存在性代替语义正确性**：原文确实含“合同编号：”，不代表它是标题；原文确实含“总价10”，不代表它是总金额。
3. **角色模型混用**：`partyA/partyB` 与 `OUR_ENTITY/COUNTERPARTY` 在确认我方立场前互相覆盖。
4. **候选过早成为正式数据**：`NEEDS_CONFIRMATION` 阶段已经回填 `contract_case`，错误候选会污染首页、详情和后续 Agent。
5. **字段证据过于扁平**：只保存 quote/offset，未稳定保存页面、坐标、解析版本和候选间关系。
6. **后续重复提取**：合同画像再次识别基础字段，造成顶部案件字段与下方画像字段冲突。

## 5. 推荐目标架构

```text
原始合同文件
  -> 文档解析层（原生文本 / MinerU / OCR，统一块级结构）
  -> 质量门禁（页级质量、关键页完整性、解析版本）
  -> 候选召回层（规则 + 版面 + 表格 + 文件名，只产候选）
  -> LLM 字段裁决（读取候选及完整相邻上下文）
  -> 确定性字段校验（金额类型、大小写一致性、主体合法性、日期完整性）
  -> Intake 候选快照（不写正式案件字段）
  -> 人工逐字段确认
  -> Canonical Contract Facts（唯一事实源）
  -> 要素 / 风险 / 履约 Agent 只读复用
```

### 5.1 候选模型

每个候选至少保存：

```json
{
  "fieldKey": "amount",
  "rawValue": "1860万元",
  "normalizedValue": 18600000,
  "semanticType": "CONTRACT_TOTAL",
  "source": "LLM|RULE|TABLE|LAYOUT|FILENAME",
  "quote": "本合同总价为人民币……（¥1860万元）",
  "page": 12,
  "bbox": [0, 0, 0, 0],
  "parserVersion": "mineru:...",
  "validationErrors": [],
  "status": "PROPOSED|NEEDS_REVIEW|CONFIRMED|REJECTED"
}
```

### 5.2 字段专用裁决规则

**合同标题**

- 候选来源：首页标题块、封面中心大字、文件名、LLM。
- 排除“合同编号、签订地点、填写说明、目录、附件”等标签。
- 标题值允许对 OCR 空格进行归一化，但引用必须保留原始文字。

**合同主体**

- 首次只提取 `partyA`、`partyB` 及合同中的角色别名。
- 不读取或写入 `ourEntity/counterparty` 作为甲乙方候选。
- 用户选择 `ourSide=A|B` 后，再确定我方主体和相对方。
- 同时检查封面和签章页；冲突时进入人工确认，不按出现顺序猜测。

**合同总金额**

- 规则召回所有金额并分类为：`CONTRACT_TOTAL`、`PAYMENT_INSTALLMENT`、`PERCENTAGE`、`GUARANTEE`、`PENALTY`、`UNIT_PRICE`、`OTHER`。
- `%`、`合同总价的 X%`、`X 日内`不得进入总金额候选。
- 优先比较“合同总价/合同价款”完整条款中的阿拉伯数字和中文大写。
- 大小写一致且引用完整时可自动提出高可信候选；冲突或 OCR 损坏时必须人工确认。
- 规则不能仅凭置信度覆盖一个有完整引用且通过校验的 LLM 结果。

## 6. 分阶段落地顺序

### P0：修复当前错误

1. 取消 `fallback_confidence >= 0.78` 即覆盖 LLM 的通用逻辑。
2. 排除比例金额，并从“第一个命中”改为“多候选分类”。
3. 标题规则排除字段标签和通用页眉。
4. 删除 intake 阶段 `OUR_ENTITY/COUNTERPARTY -> partyA/partyB` 的反向映射。
5. `NEEDS_CONFIRMATION` 只保存候选，不回填正式业务字段；确认接口一次性写入。

### P1：建立唯一事实源

1. 增加 Canonical Contract Fact 或复用已确认的 extraction snapshot。
2. 后续合同画像只补合同类型专属要素，不再重新提取基础字段。
3. 顶部摘要、风险审查和履约核验统一读取确认后的基础事实。

### P2：完善证据和评测

1. 保存页码、bbox、parser/content 版本和字段决策历史。
2. 建立中文合同首次识别评测集。
3. 单独统计金额类型混淆、标题标签误识别、甲乙方互换和 OCR 引用失真。

## 7. 最终建议

AtlasMind 不需要更换成某一个 GitHub 项目，也不应再增加一次独立的“基础字段 Agent”。更合理的组合是：

- 继续使用现有原生解析 + MinerU/OCR 作为文档证据层，并逐步输出 Docling/OpenContracts 风格的统一块和位置数据。
- 借鉴 OpenContracts，将每个字段作为可批准、可拒绝、可追溯的候选单元。
- 借鉴 CUAD，用原文跨度和字段类别建立可重复评测。
- 规则只负责候选召回和业务校验，LLM负责上下文语义裁决，人工确认负责把候选提升为正式事实。

这套结构能够同时解决当前的 `10 CNY`、错误标题、甲乙方混淆和后续重复提取问题，并保持现有 MySQL、Python Runtime 与前端确认页的总体技术栈不变。
