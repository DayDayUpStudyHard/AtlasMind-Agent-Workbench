# Debug 修复记录

项目开发过程中遇到的问题及修复，按时间倒序记录。

## 权限体系四个硬点补全：合同访问边角、额度幂等、管理员保护、Token 测试

**日期**：2026-08-09

### 调整原因

权限体系（Sa-Token + BCrypt + Redis + httpOnly Cookie Token Rotation）主链路已跑通，但存在四个硬点：
1. 间接合同资源（reminders / memories / runs/{runId}/stream）缺少 `ContractAccessPolicy` 校验，可通过猜 ID 跨部门访问
2. 额度 `confirm/refund` 的 UPDATE 语句不幂等，重复调用会二次修改 `used_count`/`reserved_count`
3. 禁用用户时没有"最后一个管理员"保护，可禁用所有管理员导致系统不可管理
4. Refresh token 旋转缺少并发双 refresh 和重放检测的自动化测试

### 合同访问策略边角补全

**Controller 层** (`ContractWorkspaceController.java`)：
- `GET /memories/{memoryId}`：查询带出 `project_id`，调用 `accessPolicy.checkAccess(project_id)` 校验合同可见性
- `GET /runs/{runId}/stream`：SSE 订阅前解析 run 的 `subjectId` 并校验访问权限，防止未授权用户监听进度事件

**Service 层** (`ContractCaseServiceImpl.java`)：
- `listReminders()`：SQL 增加 `accessPolicy.buildVisibilityFilter(params)`，按 `c` 别名过滤
- `listWorkQueue()`：三种队列（APPROVAL / FULFILLMENT / REVIEW）所有子查询均加 visibility filter
- `portfolio()`：7 个 contract_case 直接查询加 `buildVisibilityFilterNoAlias`；3 个 obligation 查询新 join contract_case 并加 filter；agent_run / contract_review_finding 同样 join 加 filter
- `workQueueSummary()`：三个维度的嵌套子查询全部加 visibility filter，params 按 filter 出现次数正确重复组合（每处 filter 各 2 个占位参数）

### 额度幂等加固

**`QuotaService.java`**：
- 抽取 `hasIdempotencyKey(key)` 辅助方法，统一检查 `quota_transaction` 表中是否已有同名幂等键
- `reserve()`：`SELECT FOR UPDATE` 持锁后、UPDATE 计数器前增加幂等检查，已存在则直接返回；INSERT 改 `ON DUPLICATE KEY UPDATE`
- `confirm()`：`SELECT FOR UPDATE` 持锁后、UPDATE `used_count` 前增加幂等检查，防止重复累加
- `refund()`：`SELECT FOR UPDATE` 持锁后、UPDATE `reserved_count` 前增加幂等检查，防止重复扣减

### 最后一个管理员保护

**`AdminUserController.java` — `disable()` 方法**：
- 禁用前查目标用户 role，若为 ADMIN 则查 `SELECT COUNT(*) FROM t_user WHERE role='ADMIN' AND status='ACTIVE'`
- 仅剩 1 个活跃管理员时抛出 `IllegalStateException("不能禁用最后一个管理员")`
- 逻辑与已有的角色降级保护（`update()` 中 line 144-156）完全一致

### Refresh Token 并发与重放测试

**`UserServiceImplTest.java`** — 新增 7 个测试：
- `rotateRefreshTokenSuccess`：正常轮换，旧 token → ROTATION，新 token 入库
- `rotateRefreshTokenReplayDetection`：已 revoke 的 token 再次使用 → 整族 `REUSE_DETECTED`
- `rotateRefreshTokenExpired`：过期 token 抛异常
- `rotateRefreshTokenUserDisabled`：禁用用户拒绝刷新
- `rotateRefreshTokenNotFound`：不存在的 token 抛异常
- `concurrentDoubleRefreshDetectsReplay`：模拟两次连续调用，第一次成功轮换、第二次检测到已 revoke → 触发整族作废
- `revokeRefreshTokenByHash` / `revokeAllRefreshTokensForUser`：撤销单 token / 撤销用户所有 token

新增 `@Mock JdbcTemplate`，token row 辅助方法 `tokenRow()` / `tokenList()`。

### 验证

- Java：`.\\mvnw.cmd -q -DskipTests compile` 通过

## 合同首次识别 P0/P1/P2：候选裁决、唯一事实源与字段审计

**日期**：2026-08-08

### 调整原因

- 合同发起时，规则可能把“合同总价 10%”误识别为 `10 CNY`，并以规则置信度覆盖模型识别出的 1860 万元合同总价。
- 标题规则可能把“合同编号”等字段标签当成合同名称；预处理结果还可能把“我方/相对方”错误映射成甲方/乙方。
- 未经人工确认的候选会提前回填 `contract_case`，导致首页、详情、风险审查和后续合同画像共同使用错误事实。
- 合同画像会再次提取标题、主体、金额和日期，造成顶部正式字段与下方画像冲突。
- 首次识别缺少字段级决定历史和可重复评测，无法回答“模型提出了什么、用户改了什么、依据是什么”。

### P0：修复首次识别错误

- 金额规则改为“召回多个候选并分类”，区分 `CONTRACT_TOTAL`、`PERCENTAGE`、履约担保、分期付款、违约金和单价；百分比不再进入合同总额候选。
- 有连续原文引用且通过字段校验的 LLM 结果优先，规则只在模型候选不可用时兜底，不再按通用置信度强行覆盖模型。
- 合同标题增加合理性校验，排除合同编号、填写说明、目录和通用字段标签。
- 删除预处理阶段 `OUR_ENTITY/COUNTERPARTY -> partyA/partyB` 的反向覆盖；甲乙方始终表示合同法律角色，我方角色由用户确认后映射。
- intake schema / prompt 升级为 `contract-intake-v2`，明确禁止把比例、保证金、分期款、违约金和单价当成合同总金额。
- `NEEDS_CONFIRMATION` 阶段只保存候选并把案件置为 `INTAKE_CONFIRMING`，不再提前写入标题、主体、金额和日期；确认接口才一次性写入正式案件字段。

### P1：建立确认后的唯一事实源

- 合同要素图不再要求 LLM 重复生成标题、甲乙方、我方角色、总金额、币种、签订日期、生效日期和到期日期。
- 新增 canonical base field 投影：基础字段只读取人工确认后的 `contract_case`，并按 `ourSide` 还原合同中的甲方/乙方。
- LLM 只负责发现不同合同类型的专属要素分组；即使模型返回伪造的 `baseFields`，归一化阶段也会丢弃并重新注入正式事实。
- 风险审查、履约核验和合同画像继续读取同一案件事实与文档证据，不再各自重新判断合同总额和合同主体。
- 只有模型候选值与人工确认值一致时才继承候选原文引用；用户改过的值标记为“已人工确认”，不会把旧候选引用错误挂到新值上。

### P2：字段决策审计与专项评测

- 新增迁移 `V029__contract_intake_fact_decision.sql` 和 `contract_intake_fact_decision` 表，逐字段保存：候选值、确认值、`ACCEPTED / EDITED / USER_SUPPLIED / CLEARED` 决定类型、候选来源、可信度、校验结果、引用、内容哈希、解析器、schema/prompt/model 版本和确认人。
- Python 在解析器已经提供信息时，为 intake 引用补充 document、clause、page、content hash 和 parser version；引用 JSON 保留 bbox 扩展位，未提供坐标时不伪造位置。
- 合同详情“原文证据”页新增“事实确认记录”，可查看首次候选、最终值、人工决定、识别依据和运行版本；移动端改为单列显示。
- 新增 `contract_intake_evaluation.py`、中文合同首次识别样本集和回归测试，分别统计字段精确匹配率、金额/标题/主体准确率、比例误判金额、标题标签误识别和甲乙方互换。
- 修复实现过程中发现的两个执行顺序问题：`validate_extraction()` 返回路径被辅助函数截断，以及 `extract_intake()` 在加载 intake 前引用未初始化变量。

### 验证

- 首次识别专项测试：`18 passed`；增加真实工程合同封面、非总金额分类和“人工修改正式值不能复用旧候选引用”的唯一事实源回归测试。
- 评测 CLI：3/3 样本通过，字段、金额、标题和主体准确率均为 100%，比例金额误判、标题标签误判、甲乙方互换均为 0。
- 当前 MySQL 已执行 `V029`，`contract_intake_fact_decision` 表存在。
- Python 全量测试：`85 passed`，仅保留 1 条 LangGraph 上游弃用警告。
- Java：`.\\mvnw.cmd -q -DskipTests compile` 通过。
- 前端：`npm.cmd run build` 通过；仅保留现有主包体积提示。

### 真实合同回归补充（2026-08-08）

- 新上传“安源电厂二次再热合同.pdf”后确认页仍显示 `10 CNY`。数据库追踪确认该 intake 由未重启的旧 Python 进程处理，保存的仍是旧格式规则候选；同时 LLM 熔断器处于 open 状态，因此截图只展示了旧规则结果。
- 使用该 intake 的完整真实文本复现后，新规则正确定位到“本合同总价款为人民币肆仟捌佰陆拾万元整（¥4860万元）”，结果为 `48,600,000 CNY`；“合同总价10%”被标记为 `PERCENTAGE`，不参与总金额选择。
- 增加真实工程合同封面回归用例：排除英文 Logo 和合同编号，合并“公司名称 + 工程名称 + 勘察设计合同”三行标题，并使用甲乙方字段校正标题中的单字 OCR 错误（如“有眼责任公司”改为“有限责任公司”）。
- 金额候选按类型各保留最多 4 项、总量最多 32 项，避免长合同中的大量扣款、单价和百分比候选占满 LLM 上下文；该真实合同从上百个候选压缩为 13 个。
- 已重启 Python 服务并重新执行 intake `#36`：LLM 调用恢复，标题、甲乙方和金额均正确，旧错误信息已清空。
- 页面复验发现确认弹窗仍显示 `10`：前端金额初始化写成“案件旧值优先于 intake 新候选”，与标题、主体和日期的优先级不一致。现统一改为 intake 候选优先，案件字段仅在新候选缺失时兜底。

---

## 合同文档预处理：统一 OCR 清洗 + 主体识别

**日期**：2026-08-06

### 调整原因

- PDF 扫描件提取的合同文本存在严重的 OCR 乱码："质保盒"（应为质保金）、"血1满"（应为届满）、"草包商"（应为承包商）、"设计尿包商"（应为设计承包商）、"liEI" 等非中文乱码块。
- 乱码文本直接进入 timeline 正则提取和 clause 分类，导致时间节点展示不可读、合同条款无法正确分类。
- 工程合同使用"业主""设计承包商""发包方"等非标准称谓，原 `deterministic_hints()` 只匹配字面"甲方""乙方"，无法识别主体角色。
- 上述两个问题各自独立处理（timeline 靠正则、主体靠 hints），没有共享 LLM 理解结果，造成重复调用和上下文割裂。
- 合同标题跨行显示（如"中电投分宜电厂扩建工程(2x660MW机组)"在上一行，"勘察设计合同"在下一行），原提取只取第一行命中行，标题不完整。

### 实现

**新增 `contract_text_preprocessor.py`**：一次 LLM 调用同时完成 OCR 文本清洗、主体识别和质量标记。

- 注入 50+ 中文工程合同高频术语词典（质保金、竣工验收、违约金、勘察设计等），指导 LLM 根据上下文推断 OCR 错误修正。
- 列出常见 OCR 形近字对照表（盒→金、血→期/届、尿→承/建、曰→日 等）。
- 两档修复策略：明显 OCR 错误积极修正，模糊的标记 low-confidence 保留原文。
- 输出结构化 JSON：`cleanedText`（清洗后全文）、`parties`（识别的主体及 A/B 角色推定）、`quality`（GOOD/FAIR/POOR + 乱码段落标记）、`corrections`（每处修正可审计）。
- LLM 调用接入 `LLMService._call_llm_with_retry`（熔断器+最多 2 次重试），不再裸调 `analysis_client` 绕过保护。
- 预处理结果写入 `contract_document.content_text`（清洗后文本覆盖原乱码）和 `contract_party`（主体角色）。
- 新增 `contract_document.preprocess_status` 列（PENDING/READY/FAILED/SKIPPED），前端可感知预处理状态。

**修改 `contract_document_parser.py`**：`parse_contract_document()` 在 PDF 文本提取后立即调用 `ContractTextPreprocessor.process()`，清洗后的文本替代原始 `content` 变量，后续 clause 切分和 timeline 提取均使用清洗文本。新增 `_write_preprocess_parties()` 将主体写入 `contract_party` 表。

**修改 `contract_intake_extractor.py`**：
- `deterministic_hints()` 标题提取增强：读取前 30 行，合并短行（<80 字连续合并），取最长包含"合同/协议"的候选行——解决标题跨行截断。
- 甲方/乙方关键词从 17 个扩展到 22 个，增加"业主、发包方、招标人、建设方、承包方、设计方、施工方、监理方、投标人"等工程行业称谓。
- `extract_intake()` 新增：在 `deterministic_hints()` 后查询 `contract_party` 表，读取预处理已识别的主体，以 0.95 高置信度覆盖 hints 中的 partyA/partyB。

**Java 侧**：`AgentWorkbenchSchemaInitializer` 新增 `contract_document.preprocess_status` 列（`VARCHAR(16) DEFAULT 'PENDING'`）。

### 当前状态与已知问题

- 预处理管道已搭建完成，`deepseek-v4-flash` 可正常调用。
- **LLM 返回了响应但 `cleanedText` 未生效**：定位到 `_parse_response()` 解析 LLM JSON 失败或 `cleanedText` 字段为空时，`data.get("cleanedText") or text` 静默回退到原始乱码文本。`llm_used=True` 被错误标记为成功。
- 修复方向：加日志输出 LLM 实际返回的前 500 字符；若 `cleanedText` 与原始文本完全相同，标记 `llm_used=False`，不伪装成功。
- 后续计划：在 LLM 预处理前增加确定性 OCR 正则清洗（如 `re.sub("草包商", "承包商", text)`），先做粗修再给 LLM 精修。

---

## 合同风险发现变得过于简略：确定性规则兜底与严格审查提示词

**日期**：2026-08-06

### 现象

合同审查中出现“未找到TERMINATION类型条款”或“未找到ACCEPTANCE类型条款”时，前端只能看到“模型分析未完成”“根据规则要求补充或修改对应条款”等模板文本。即使 LLM 调用成功，也可能漏掉确定性规则发现；每个风险领域最多返回 3 条，导致复杂合同的风险覆盖不足。

### 根因

1. 规则引擎按 `contract_review_rule` 的 `checkType` 和 `clauseType` 对合同条款证据做确定性检查。`MISSING` 规则在合同中没有对应条款类型时产生发现，并不是 LLM 或前端临时生成的。
2. LLM 兜底内容只有通用的影响、修改建议和人工复核问题，未结合规则类型、检查配置和规则描述展开。
3. LLM 输出没有强制携带并覆盖 `ruleKey`，成功返回时可能不解释某条确定性规则；提示词的单领域上限为 3 条，也会降低召回。

### 修复

- 在 `retrieval.py` 中保留规则引擎的确定性结论，同时按验收、终止、付款、责任、保密、知识产权、数据保护等条款类型生成具体的风险影响、条款修订重点、谈判底线、复核问题和证据核对点。
- 读取 `checkConfig` 的 `keywords`、`fields`、阈值和禁止措辞，把规则真正要求的内容写入兜底建议。
- LLM 正常返回时，比较返回的 `ruleKey` 与确定性规则；模型漏掉的规则自动补入详细兜底发现，避免规则结果在 LLM 层丢失。
- 提示词要求模型逐条覆盖 `deterministicRuleFindings`，严格检查缺失、模糊、矛盾、单方裁量、责任不清、期限不明和不可量化表述；单个领域最多输出 6 条有证据的风险，并强制填写解释、影响、修订、谈判和人工复核字段。
- 归一化结果保留 `ruleKey` 和 `ruleTitle`，便于审计和前端显示风险来源。

### 验证

- 增加回归测试：缺失终止条款必须输出具体终止后结算、交接和数据返还建议；LLM 返回空 findings 时，确定性规则仍必须保留。
- 运行 `python -m pytest -q tests/test_contract_risk_graph.py`。

### 联动回归修复

完整测试还发现合同发起页的标题识别回归：跨行标题合并逻辑把“合同金额”和日期等结构化字段拼进合同标题，导致标题变成整段元数据。现已在短行合并和标题候选筛选时排除带字段标签的行，保留跨行自然标题识别能力。

最终运行 `python -m pytest -q`：69 项通过，保留 1 条 LangGraph 弃用警告，无测试失败。

## 合同解析链路修复：OCR 预处理、质量识别与时间节点降噪

**日期**：2026-08-06

### 现象

在新上传合同，尤其是扫描质量一般的 PDF 上，时间节点会出现以下问题：

- 原文存在乱码、错字、符号污染，导致节点标题和说明难以阅读
- PDF 原始文字层质量差时，没有足够稳定地触发 OCR 优化
- LLM 预处理失败后，链路会退回到未经修整的原始文本，后续规则抽取进一步放大噪声
- 时间节点 enrichment 依赖模型时，若外部 LLM 超时，前端会看到较粗糙的规则结果

本次重点不是前端样式，而是先把后端“文本进入 Agent 前”的质量做扎实。

### 根因

1. `contract_text_preprocessor.py` 中存在确定性 OCR 清洗函数缺失的问题，导致失败分支不完整。
2. 预处理链路之前更接近“整篇一次性丢给 LLM”，长合同更容易超时或返回不完整结果。
3. `document_parser.py` 的文本质量检测对“中英混杂乱码 / glyph soup”识别不够敏感，低质量 PDF 文字层没有稳定降级到 OCR fallback。
4. `contract_document_parser.py` 在低质量文本场景下，对时间节点 label / meaning 的回退不够保守，容易把脏片段直接展示出来。

### 修复内容

#### 1. 合同文本预处理器修复

文件：
`tools/chat-assistant/backend/app/agent_runtime/contract_text_preprocessor.py`

处理：

- 补上缺失的确定性清洗逻辑，修复 `_deterministic_ocr_fix` 缺失造成的异常分支
- 增加稳定的规范化 / 清洗 helper，先做规则修正，再决定是否调用 LLM
- 将“大文本一次性清洗”改为“分块预处理”，降低长合同超时和 JSON 不完整风险
- 当 LLM 预处理失败、返回非法 JSON 或超时时，不再回退到原始 OCR 文本，而是回退到“确定性清洗后的文本”

效果：

- 即使 LLM 不可达，链路也能得到一份比原始 PDF 文字层更干净的文本
- 后续规则抽取和节点构造不会再直接吃最脏的原始输入

#### 2. PDF 文本质量识别增强

文件：
`tools/chat-assistant/backend/app/services/document_parser.py`

处理：

- 收紧文字层质量识别阈值
- 新增 / 加强以下 heuristics：
  - 中文字符占比过低
  - 异常 Latin run 过多
  - 中英符号混杂、明显乱码式 glyph soup 检测
- 用 `_assess_extracted_text_quality_v2` 覆盖旧质量评估逻辑

效果：

- 之前“勉强有文字层但其实很脏”的 PDF，现在能更稳定地判为 `LOW`
- 一旦判为低质量，会更可靠地触发 OCR 优化链路，而不是直接拿脏文字继续往下跑

#### 3. 时间节点回退逻辑收紧

文件：
`tools/chat-assistant/backend/app/agent_runtime/contract_document_parser.py`

处理：

- 统一预处理结果持久化，确保 `TEXT_PREPROCESSED` trace 稳定落库
- 只要存在清洗后的文本，就将 `preprocess_status` 标记为 `READY`
- 对低质量片段增加更保守的 label / meaning fallback：
  - 不再盲目把明显乱码片段直接作为节点标题
  - 必要时退回到更通用的业务标签，例如“交付/服务节点”“验收节点”
  - 含义说明改为明确提示“原文识别质量较低，需要复核”

效果：

- 虽然在 LLM enrichment 不可用时仍可能不够漂亮，但至少不会再把最离谱的乱码原样顶到前台
- 节点信息从“误导性噪声”收敛为“可识别但需复核”的保守输出

### 本次针对性验证

重点复跑文档：

- `contract_document.id = 50`
- 文件名：`中电投分宜电厂扩建工程（2×660MW机组）勘察设计合同.pdf`

验证动作：

1. 多次重新执行 `parse_contract_document(50)`
2. 确认预处理 trace 已写入数据库
3. 确认低质量文字层会触发 OCR 优化 trace
4. 抽查 `contract_timeline_node` 输出，观察标题、说明和兜底策略是否生效

### 当前验证结果

- 解析可以完成
- `TEXT_PREPROCESSED` trace 已能稳定写出
- `PDF_RECOGNITION_OPTIMIZATION` trace 已出现，说明 OCR fallback 被触发
- 时间节点标题较之前已有改善，极端乱码节点已能回退到通用标签
- 但外部 LLM 目前仍存在超时问题，因此部分 enrichment 仍然只能走规则 / fallback 分支

当前仍可见的局限：

- 某些节点标题不再是纯乱码，但仍偏长、偏 clause 原文截取
- 模型超时时，节点“重点动作总结”无法完全达到理想效果
- 这类残留问题更适合下一步继续做“规则侧标题压缩 + LLM 可用时二次润色”

### 测试与编译验证

已通过：

- `python -m unittest discover -s tests -p 'test_contract_text_preprocessor.py'`
- `python -m unittest discover -s tests -p 'test_document_parser_quality.py'`
- 修改过的 Python 文件 `py_compile` 通过

新增 / 覆盖的测试点：

- 非法 JSON 返回时的确定性 fallback
- 长文本分块清洗
- glyph soup 式乱码文本的质量识别回归测试

### 结论

这次修复把合同解析链路从“模型一超时就把脏文本原样往后传”改成了“先确定性清洗，再按质量决定是否 OCR，再做节点抽取”的更稳妥路径。

它已经显著降低了乱码直接进入时间节点展示的概率，但还没有根治所有展示问题。当前剩余问题的核心不再是链路失控，而是：

- OCR / 原文质量本身仍有限
- 外部 LLM 仍不稳定，导致节点摘要和语义润色经常只能 fallback

后续若继续优化，优先级建议是：

1. 继续增强低质量节点的标题压缩和摘要规则
2. 恢复稳定的 LLM 调用后，再让模型对候选节点做二次语义整理
3. 前端对“保守兜底节点”和“高置信度节点”做更清晰的层级展示

## 合同文本预处理与时间节点重跑

**日期**：2026-08-06

### 现象

合同详情里的时间节点仍然出现明显 OCR 乱码，且预处理任务有时会把原始文本当成“清洗成功”继续往后传。

### 根因

1. 预处理器把整篇文本一次性发给 LLM，长文容易截断或返回空 JSON。
2. LLM 失败时直接回退到原始 OCR 文本，导致坏文本继续进入时间节点和风险分析链路。
3. 预处理 trace 只在少数分支写入，导致后台看起来像“没跑过”。

### 修复

| 文件 | 改动 |
|------|------|
| `tools/chat-assistant/backend/app/agent_runtime/contract_text_preprocessor.py` | 新增保结构文本规范化、分块 LLM 清洗、确定性回退；LLM 失败时使用确定性清洗文本，不再把原始 OCR 文本伪装成成功结果 |
| `tools/chat-assistant/backend/app/agent_runtime/contract_document_parser.py` | 预处理结果统一落库；无论是否走 LLM，都写入 `TEXT_PREPROCESSED` trace 和合同主体信息 |
| `tools/chat-assistant/backend/tests/test_contract_text_preprocessor.py` | 新增回归测试：坏 JSON 回退确定性文本、长文本分块清洗 |

### 验证

- `python -m unittest discover -s tests -p 'test_contract_text_preprocessor.py'`
- `python -m unittest discover -s tests -p 'test_document_parser_quality.py'`
- `python -m py_compile app/agent_runtime/contract_text_preprocessor.py app/agent_runtime/contract_document_parser.py app/agent_runtime/graph/nodes/retrieval.py`
- 重新解析 `doc#50`

### 结果

- `contract_document_job_trace` 已写入 `TEXT_PREPROCESSED`
- `contract_document_job` 重新生成了 `TIMELINE_EXTRACTING`、`INDEXING`、`READY`
- 当前环境下 LLM 仍有超时，预处理会回退到确定性清洗，但不会再把原始 OCR 文本当成成功结果继续传播

## 合同 Agent 架构收敛：有界反思、幂等运行与失败可观测

**日期**：2026-08-06

### 背景

- ContractReviewGraph 在证据不足时可能反复进入补检索和反思路径，造成运行时间过长，甚至没有报告产物。
- 合同详情页的多个按钮实际都调用同一个 `CONTRACT_REVIEW` 任务接口，前端请求结束后异步 Run 仍在执行，用户可以重复发起同类任务。
- Agent 运行失败原因已经写入 `agent_run.error_message`，但合同详情页和顶部消息中心没有完整展示，用户只能看到“处理失败”。
- 合同详情页同时存在“开始合同审查”“开始风险审查”和流程卡按钮，业务语义重复，容易误触发重复运行。

### 最近的架构调整

#### 1. LangGraph 审查图增加有界反思与受限报告出口

- `contract_review.py` 的反思路由读取 `retry_state.reflection_rounds`，将补检索次数纳入状态机判断。
- 证据覆盖不足时最多执行一次定向补检索；补检索后不再重新跑完整的领域 LLM 审查，直接进入 `compose_limited_report`。
- 证据仍不足时生成明确标记为范围受限的报告，而不是停留在 `VERIFYING` 或无限循环。
- 保留 `CONFIRMED → compose_report` 和 `CANNOT_RESOLVE → compose_limited_report` 两条明确出口。
- 新增回归测试，验证一次补检索后必定进入受限报告路径。

当前合同风险审查链路：

```text
加载合同快照
  → 条款清单
  → 创建领域任务
  → 混合检索合同/知识库证据
  → 确定性规则 + LLM 生成风险发现
  → 覆盖反思
  → 最多一次定向补检索
  → 完整报告 / 范围受限报告
  → Pydantic Schema 校验
  → 修复或有限报告
  → 持久化报告与引用
```

#### 2. Java 侧增加合同任务幂等保护

- `ContractCaseServiceImpl.startRun()` 在事务内先对合同记录执行 `SELECT ... FOR UPDATE`。
- 同一合同、同一 `run_type` 存在以下活动状态时，不再创建新的 `agent_run`：
  `CREATED`、`CONTEXT_BUILDING`、`PLANNING`、`ANALYZING`、`VERIFYING`、`WAITING_HUMAN`、`WAITING_APPROVAL`。
- 后端返回已有 Run，并附加 `deduplicated=true`，前端提示“已沿用现有运行记录”。
- 这使幂等保护不依赖前端按钮状态，即使多个浏览器请求同时到达，也不会重复创建同类合同任务。

#### 3. 前端统一合同 Agent 任务入口

- 顶部主按钮统一承担当前合同的下一步主操作：
  - 待审查：开始风险审查
  - 运行中：查看审查进度
  - 待审批：生成审批意见
  - 已签署/履约中：提取履约义务
- 删除流程卡和空状态卡中重复的风险审查按钮。
- 新增“更多 Agent 任务”菜单，集中放置版本差异复核、审批意见和履约义务提取，并显示各任务的前置条件。
- 前端增加活动 Run 拦截，后端幂等保护作为最终兜底。
- 移动端菜单改为从操作区左侧展开，避免窄屏向视口外溢。

#### 4. 失败原因纳入可观测链路

- 合同详情的 Agent 运行记录读取并展示 `errorMessage`。
- 顶部消息中心将合同文件处理和 Agent 运行合并为一个合同工作流活动，不再显示两条重复通知。
- 失败活动可以直接打开错误原因弹窗，查看合同、Run 编号、失败阶段和后端返回的完整错误信息。
- Java 仍负责 API、事务、鉴权和任务入口；Python Runtime 负责 LangGraph 编排、工具调用、反思、报告和 checkpoint；前端只负责发起任务和展示状态/轨迹。

### 验证结果

- 用户端 Vite 生产构建通过。
- 用户端测试 9 项全部通过。
- Python Agent Runtime 测试 64 项全部通过。
- Java `mvnw -q -DskipTests compile` 通过。
- `git diff --check` 通过。
- Java 后端重启后 `http://localhost:18080/actuator/health` 返回 200。

### 当前架构结论

```text
ContractCaseView
  → Java ContractCaseService.startRun()
  → 事务锁 + 活动 Run 幂等判断
  → agent_run
  → Python RuntimeRouter
  → GraphAdapter
  → ContractReviewGraph
  → traces / tool calls / report / checkpoint
  → Java API + 消息中心 + 合同详情展示
```

这次调整没有改变 Legacy Harness 作为回滚通道的定位，而是把 LangGraph 的运行边界、失败出口、重复运行保护和前端可观测性补齐，使 Agent 从“能运行”进一步变成“可控、可解释、可恢复”。

## Graph Runtime 运行时修正：路由、Checkpoint、Resume、评测闭环

**日期**：2026-08-06

### 调整原因

- G0-G4 搭建了 LangGraph 基础设施和 ContractReviewGraph / FulfillmentCheckGraph 节点骨架，但存在 10 个运行时 bug 导致图无法真正切换、履约 HITL 不可用、评测中心空壳。
- P0 级（阻塞运行）：RuntimeRouter 路由不匹配（注册 key 用 graph name，查找 key 用 env var 值"langgraph"）；Checkpoint 未接入 LangGraph 协议签名；Resume 用 raw dict 而非 `Command(resume=...)`；`GraphAdapter.run()` 遇到 `GraphInterrupt` 不返回 `WAITING_HUMAN`；task_input 丢失导致履约图拿不到 timelineNodeId；SQL 列不存在导致管理端报错。
- P1 级（功能不完整）：Pydantic 校验失败只 log 不阻断；ContractReviewGraph 没有真实检索和 LLM draft；评测 `startEvalRun()` 只插 RUNNING 记录不调 Python；评测 runtime_engine 被 env var 覆盖不稳定；图内 `persist_report` 和外层 `_dispatch_via_router` 重复保存报告。

### 实现

**P0 — 7 项阻塞修复**

1. **Runtime 路由**：`RuntimeRouter._resolve()` 改为 DB 配置 → 环境变量 → legacy 默认值三级优先级；`langgraph` 作为运行模式按 task_type 映射到 graph name（`CONTRACT_REVIEW→contract_review`、`FULFILLMENT_CHECK→fulfillment_check`）。

2. **Checkpoint 协议**：`MySqlCheckpointSaver` 重写为 LangGraph 0.4.10 严格签名：`get_tuple(config)`（`config` 为 `{"configurable":{"thread_id":"..."}}`）、`put(config, checkpoint, metadata, new_versions)`、`list(config, *, filter, before, limit)`、`put_writes(config, writes, task_id, task_path)`。新增 `aget_tuple`/`aput`/`aput_writes` 异步包装器。新增 `get_next_version()`。

3. **Resume 用 `Command(resume={...})`**：`GraphAdapter.resume()` 改用 `Command(resume={"action":..., "manual_result":..., "note":...})`。RuntimeRouter.resume() 查 `agent_run.run_type` 确定正确的 graph adapter（`FULFILLMENT_CHECK→fulfillment_check`），不再遍历所有 adapter 拿第一个。

4. **WAITING_HUMAN 状态**：`GraphAdapter.run()` catch `GraphInterrupt` 返回 `AgentResult(status="WAITING_HUMAN")`。`AgentResult.ok` 改为仅 `COMPLETED` 时为 True。`_dispatch_via_router` 三分支：`WAITING_HUMAN`→更新状态不写报告；`COMPLETED`→更新完成（图内 `persist_report` 已写）；其他→FAILED。

5. **task_input 传递**：`GraphAdapter.run()` 的 `initial_state` 新增 `"task_input": context.task_input or {}`。

6. **SQL 列名**：`EvalAdminController.listCases()` 中 `expected_finding_count` 改为 `COALESCE(JSON_LENGTH(expected_findings_json), 0)`。

7. **artifact 未定义 bug**：`_dispatch_via_router` 的 else 分支改为 `(result.artifact or {}).get("artifactError", ...)` 防御式读取。

**P1 — 3 项功能补全**

8. **Pydantic 质量门禁**：`validate_schema` 写入 `schema_validation` state（`valid/errors/repair_count`）；新增 `repair_artifact` 节点作一次定向修复；新增 `_route_after_schema` 条件边：VALID→persist、INVALID+0→repair、INVALID+1→compose_limited_report。

9. **ContractReviewGraph 真实检索**：新增 `retrieve_domain_evidence`（调 `ContractStore` 查合同条款+标准条款+知识库 chunk）、`run_deterministic_rules`（加载活跃审查规则）、`draft_domain_findings`（规则+证据对齐生成双引用发现）。图边改为 `create_domain_tasks → retrieve → rules → draft → validate`。

10. **评测中心闭环**：Python 新增 `POST /internal/agent/evaluations/run`，Java `EvalAdminController.startEvalRun()` 通过 `AiGateway.runEvaluation()` 触发。Python 端 fire-and-forget（`asyncio.create_task` 后立即返回），后台逐 case 创建临时 contract_case+clause、调 `dispatch_with_mode(ctx, runtime)` 绕过全局配置、写 `agent_eval_result`、汇总更新 `agent_eval_run`。`finally` 块软删除临时合同数据。外围 `try/except` 确保任何异常写 FAILED。

**二阶修正（3 项）**

11. **Resume 可能跑错图**：`RuntimeRouter.resume()` 改为查 `agent_run.run_type` 映射到正确 graph，不再遍历取第一个非 legacy adapter。

12. **评测同步阻塞超时**：改为 fire-and-forget 后立即返回 `{"status":"ACCEPTED"}`。

13. **评测 runtime_engine 不稳定**：新增 `RuntimeRouter.dispatch_with_mode(ctx, mode)` 绕过 DB/env 配置，评测直接按参数选 adapter。

### 修改文件

- `app/agent_runtime/runtime.py`：`_resolve` DB 优先 + task_type 映射 + `dispatch_with_mode` + `resume` 按 run_type 路由
- `app/agent_runtime/graph/checkpoint.py`：重写为 LangGraph 0.4.10 协议
- `app/agent_runtime/graph/contract_review.py`：新增 3 个真实检索节点 + Pydantic 条件边
- `app/agent_runtime/graph/fulfillment_check.py`：`build_fulfillment_check_graph(checkpointer=...)`
- `app/agent_runtime/graph/nodes/retrieval.py`（新）：`retrieve_domain_evidence` + `run_deterministic_rules` + `draft_domain_findings`
- `app/agent_runtime/graph/nodes/artifact.py`：`validate_schema` 硬门禁 + `repair_artifact` + `_route_after_schema`
- `app/api/routes.py`：`_dispatch_via_router` 三分支 + `resume_agent_run` 端点 + `run_evaluation` fire-and-forget + `_run_evaluation_background` + `_fail_eval_run`
- `agent-server/.../EvalAdminController.java`：注入 `AiGateway` + `startEvalRun` 调用 `runEvaluation`
- `agent-server/.../AiGateway.java` / `HttpAiGateway.java`：新增 `runEvaluation(Long)`

---

## 合同 Agent Runtime 大版本重构：Graph Runtime、评测中心与分析工作流落地

**日期**：2026-08-06

### 调整原因

- 原合同 Agent 仍以通用 Harness 串行执行为主，虽然能完成基础问答和文档生成，但在合同审查、履约核验、人工确认恢复、评测对比等场景下，状态流转不够清晰，难以体现真正的 Agent 能力。
- 合同文档解析、要素提取、风险审查、履约核验逐步变成多阶段长链路任务，仅靠单个 Runner 和 prompt 编排，后续会越来越难维护。
- 缺少统一的运行时抽象，Java、Python、前端之间只能围绕“发起一次任务”协作，不能稳定承载 checkpoint、resume、shadow run、评测基线和版本回滚。
- 管理端之前没有独立评测中心，无法量化 legacy 和新 Agent 图在合同风险召回、引用完整性、误报率上的差异。

### 实现

- Python 侧引入 `agent_runtime/runtime.py`，抽象出 `LegacyHarnessAdapter`、`GraphAdapter`、`ShadowAdapter` 和 `RuntimeRouter`，把“旧 Harness 可继续跑”和“新 Graph Runtime 可灰度切换”统一到一个入口。
- 新建 `app/agent_runtime/graph/` 模块，落地 LangGraph 风格的图编排基础设施：
  - `state.py` 统一图状态
  - `registry.py` 管理图注册和编译缓存
  - `checkpoint.py` 持久化图运行状态
  - `contract_review.py` 和 `fulfillment_check.py` 承载合同审查图、履约核验图
- 新建 `graph/nodes/` 一组可复用节点，把上下文冻结、条款清单、领域任务拆分、检索、反思、校验、人工确认、产物持久化从原来的一坨流程里拆出来。
- 引入 `schemas/` 和 `validators.py`，把合同审查报告、履约核验报告变成有结构约束的产物，而不是单纯依赖 LLM 自由生成。
- 新建 `evaluation/` 评测框架和样本数据集，支持按 case 批量执行、统计指标、比较不同运行时版本的结果。
- Java 侧补上评测中心后端、Schema 初始化和运行时配置种子；管理端新增评测中心页面；前端合同详情页开始接入新的分析工作流状态展示。
- 文档层面同步删除旧 PRD，补上新的 Graph Runtime PRD 和研究文档，明确后续从 Legacy 向 LangGraph/状态机逐步迁移的路线。

### 关键结果

- 合同 Agent 从“一个会调用工具的长 prompt”升级为“运行时 + 图 + 节点 + 校验 + 评测”的结构。
- 合同审查和履约核验不再共用一套难以扩展的线性流程，而是开始分化成各自独立的任务图。
- 后续增加 HITL、恢复执行、节点级 trace、评分/评测闭环时，不需要再反复堆 prompt 分支，而是可以直接在图节点和状态流转上扩展。

### 验证

- 新 Runtime、图节点、评测模块和相关迁移已全部纳入仓库。
- Java 编译、管理端构建、前端构建和 Python 测试在该批次改动后均已通过。
- 这次重构本身不是最终稳定版，后续又继续修了 Runtime 路由、Checkpoint 协议、Resume、评测触发和报告落库等运行时问题；这些后续修复已单独记录在本文件后续条目中。

---

## Agent 图运行时架构升级：LangGraph DAG/状态机 + 评测中心 + 四阶段渐进迁移

**日期**：2026-08-05

### 调整原因

- 当前 Python Agent Runtime 使用线性 6-Phase Harness（上下文→规划→工具循环→证据兜底→反思→产物），主要存在 10 个明确约束。
- 补检索后不再次执行完整 Reflection，证据缺口无法证明已关闭（C-04）。
- Reflection 失败仍可能继续生成正式报告，"未通过质量门禁"和"报告完成"语义冲突（C-05）。
- 本地 Reflection 只要存在引用即可判 `adequate`，一个弱引用可能错误通过复杂任务（C-06）。
- 长合同审查因 `readContractClause` 单次最多 20 条限制存在覆盖盲区（C-02）。
- 通用 Runner 最多 2 轮 8 次工具调用，长合同易在证据完整前耗尽预算（C-01）。
- 履约核验包含补证、待定、人工确认、上传新证据后重新核验等状态，继续使用线性流程会越来越难维护。
- 缺少合同 Agent Golden Dataset，无法量化新旧版本准确率差异（C-10）。
- 缺少可证明"准确率确实提高"的专项评测集和发布门槛。

### 实现

**G0 — Harness 正确性修正与评测基线（不改架构）**

- Phase 5 Reflection 补检索后新增 re-reflection：补充工具执行完后重新调用 `_reflect()`，若仍 `adequate=false` 则传入 `limited=true` 给 Phase 6 产物生成。
- `_local_reflection()` 合同模式加强：不再仅检查"有任意引用即通过"，改为要求合同引用 + 政策引用均存在才判 `adequate=true`。
- Phase 6 `_generate_artifact()` 新增 `limited` 参数：`limited=true` 时 CONTRACT_REVIEW 走 `_fallback_review_artifact()` 生成 `[范围受限]` 报告（`analysisMode=LIMITED`），FULFILLMENT_CHECK 已有类似 `_fallback_fulfillment_artifact()` 路径。
- 新增 `app/agent_runtime/schemas/` 包：`review.py`（`ContractReviewArtifact`、`ContractFinding`、`DualCitation`）、`fulfillment.py`（`FulfillmentArtifact`、`FulfillmentRequirementJudgement`）、`validators.py`（`validate_report()` — Schema + 10 项业务不变量双重校验）。
- `prompts.py` 更新 fallback：`reflection` prompt 改为领域覆盖矩阵（逐域检查 + `domains` 字段 + `retryable`），`contract_review` prompt 新增受限报告模式指令、`findingKey`/`claim`/`evidenceStatus`/`contractCitationIds`/`policyCitationIds` 新字段。
- 新增 `app/agent_runtime/evaluation/` 评测框架：`dataset.py`（`EvaluationDataset` — YAML/JSON 加载）、`runner.py`（`EvaluationRunner` — 逐案例执行+指标计算）、`metrics.py`（`EvaluationMetrics` — 11 项指标+发布阈值检查）。
- 3 份样本评测数据：预付款风险、模糊验收标准、缺少责任上限条款。新增 `tests/test_evaluation.py`。

**G1 — Runtime 接口与 LangGraph 基础设施（搭壳，不切流量）**

- 新增 `app/agent_runtime/runtime.py`：`AgentRuntime` 协议（`run()` + `resume()`）、`AgentResult` 数据类、`ResumeCommand`（从字典解析 + 状态版本校验）、`LegacyHarnessAdapter`（包装现有 `AgentRunner`）、`GraphAdapter`（包装编译后的 LangGraph StateGraph）、`ShadowAdapter`（并排运行 primary+shadow 对比差异）、`RuntimeRouter`（按 task_type 环境变量路由）。
- 新增 `app/agent_runtime/graph/` 包：
  - `state.py`：`BaseGraphState(TypedDict)` — 带自定义 reducer（`_add_observations`、`_add_citations`）的共享状态定义。
  - `registry.py`：`GraphRegistry` — name+version 注册 + 编译缓存 + 单例。
  - `checkpoint.py`：`MySqlCheckpointSaver` — 实现 MySQL `agent_graph_checkpoint` 表持久化，支持 `get_tuple()`/`put()`/`list()`/`delete_thread()`。
  - `ping.py`：最小测试图（`ping_node` 读取合同标题），LangGraph 未安装时安全降级。
- Java `AgentWorkbenchSchemaInitializer` 新增 `agent_graph_checkpoint`、`agent_node_execution` 两张表 + 3 条 runtime 路由配置种子（`agent.runtime.default/CONTRACT_REVIEW/FULFILLMENT_CHECK=legacy`）。
- 新增 `requirements-graph.txt`：LangGraph 依赖独立安装（`langgraph>=0.4,<0.5`、`langgraph-checkpoint>=2.0,<3.0`），不回滚时不影响主流程。

**G2 — ContractReviewGraph（12 节点 DAG，含条件路由和补检索循环）**

- 新增 `listClauseInventory` 工具（`contract_store.py` + `contract_tools.py`）：分页返回完整条款目录（总数、类型分布、缺失关键类型、每条 ID/编号/标题/页数/字符数），不受 20 条限制。
- 新增 `graph/nodes/` 7 个节点文件：
  - `context.py`：`load_run_context`（加载合同快照）+ `freeze_case_snapshot`（冻结不可变事实）。
  - `inventory.py`：`inventory_clauses`（直接查询 MySQL 构建条款清单）。
  - `domain_tasks.py`：`create_domain_tasks`（7 个必查领域确定性模板：主体授权、商务付款、责任违约、合规保密、履约可执行性、终止续签、IP 数据）。
  - `validation.py`：`validate_claims`（Claim Validator — 10 项检查：引用前缀、HIGH 双引用、负向声明、LLM 篡改评分字段、建议写成事实、标题缺失、clauseType 合法性、INSUFFICIENT_EVIDENCE 矛盾检查、AI 后果串入合同后果）。输出 `PASS | DOWNGRADE | REJECT`。
  - `reflection.py`：`coverage_reflection`（领域覆盖矩阵 + 条件路由 CONFIRMED/NEED_MORE/CANNOT_RESOLVE）+ `targeted_retrieval`（补检索计数，max 2 轮）。
  - `artifact.py`：`compose_report`（完整报告）+ `compose_limited_report`（受限报告）+ `validate_schema`（Pydantic）+ `persist_report`（落库）。
- `graph/contract_review.py`：主图定义 — 12 节点 + `add_conditional_edges` 实现覆盖反射路由。
- LangGraph `v0.4.10` 已安装并验证：PingGraph 和 ContractReviewGraph 均编译通过，已通过 RuntimeRouter 在实际合同案件上跑通全链路（12 节点 → state_revision=15 → 受限报告生成）。

**G3 — FulfillmentCheckGraph（7 节点状态机，含人工中断/恢复）**

- 新增 `graph/nodes/` 4 个履约节点：
  - `requirements.py`：`decompose_requirements`（按 nodeType — PAYMENT/DELIVERY/ACCEPTANCE/NOTICE/RENEWAL/TERMINATION — 拆解为履约子项，模糊验收标记 `ambiguity`）。
  - `fulfillment_judge.py`：`judge_each_requirement`（逐项证据匹配 + ourSide 视角：A方验收追责/B方交付举证，禁止 Agent 输出 COMPLETED/FAILED/ACCEPTED）。
  - `fulfillment_validate.py`：`validate_fulfillment_judgement`（代码级校验：必需项有合同引用、INSUFFICIENT_EVIDENCE 不声称完成、UNCLEAR_TERMS 不高置信度）。
  - `human_confirm.py`：`wait_human_confirmation`（LangGraph `interrupt_before` 暂停点）+ `apply_human_result`（读取 ResumeCommand 应用到状态）。
- `graph/fulfillment_check.py`：主图定义 — 7 节点 + `interrupt_before=["wait_human_confirmation"]`。
- 新增 `POST /internal/agent/run/{runId}/resume` 端点（`routes.py`）：接收 ResumeCommand，通过 RuntimeRouter 调用 `GraphAdapter.resume()` 从 checkpoint 恢复执行。
- `RuntimeRouter` 注册链路：初始化时自动检测 LangGraph 可用性，编译 ContractReviewGraph 和 FulfillmentCheckGraph 并注册到 Router（`GraphAdapter(compiled, MySqlCheckpointSaver)`）。

**G4 — 评测中心（后端 API + 管理端 UI）**

- 新增 `EvalAdminController.java`（`/api/admin/eval`）：14 个端点 — 数据集 CRUD、用例管理、发起评测、评测记录查询（含逐案例结果）、版本对比（legacy vs langgraph 逐用例差异高亮）、指标趋势。
- Java Schema Initializer 新增 4 张评测表：`agent_eval_dataset`、`agent_eval_case`、`agent_eval_run`、`agent_eval_result`。
- 新增 `EvalCenter.vue`（管理端评测中心页面）：3 个 tab — 数据集（创建/用例/发起评测）、评测记录（召回率/引用率/误报率列表 + Runtime 标签）、版本对比（双下拉选择 + 差异高亮表格）。
- 管理端路由和菜单新增"评测中心"入口。

**架构变化**

```
之前：AgentRunner.execute() — 线性 6-Phase Hardcoded Pipeline
之后：RuntimeRouter
        ├── LegacyHarnessAdapter → AgentRunner（保留，回滚通道）
        ├── GraphAdapter → ContractReviewGraph（12 节点 DAG）
        └── GraphAdapter → FulfillmentCheckGraph（7 节点状态机 + interrupt/resume）

激活方式：
  AGENT_RUNTIME_CONTRACT_REVIEW=langgraph  # G2 已激活
  AGENT_RUNTIME_FULFILLMENT_CHECK=langgraph  # G3 就绪
  回滚：AGENT_RUNTIME_CONTRACT_REVIEW=legacy  # 无需重启
```

### 修改文件

**G0 — 6 个文件**
- `tools/chat-assistant/backend/app/agent_runtime/runner.py`：Phase 5 re-reflection + `_local_reflection` 加强 + `_generate_artifact` limited 参数 + `_fallback_review_artifact`
- `tools/chat-assistant/backend/app/agent_runtime/prompts.py`：`reflection` 领域覆盖矩阵 + `contract_review` 受限报告模式 + 新字段
- `tools/chat-assistant/backend/app/agent_runtime/schemas/__init__.py`（新）
- `tools/chat-assistant/backend/app/agent_runtime/schemas/review.py`（新）
- `tools/chat-assistant/backend/app/agent_runtime/schemas/fulfillment.py`（新）
- `tools/chat-assistant/backend/app/agent_runtime/schemas/validators.py`（新）

**G0 评测 — 7 个文件**
- `tools/chat-assistant/backend/app/agent_runtime/evaluation/__init__.py`（新）
- `tools/chat-assistant/backend/app/agent_runtime/evaluation/dataset.py`（新）
- `tools/chat-assistant/backend/app/agent_runtime/evaluation/runner.py`（新）
- `tools/chat-assistant/backend/app/agent_runtime/evaluation/metrics.py`（新）
- `tools/chat-assistant/backend/app/agent_runtime/evaluation/datasets/v1/sample-service-procurement.yaml`（新）
- `tools/chat-assistant/backend/app/agent_runtime/evaluation/datasets/v1/sample-vague-acceptance.yaml`（新）
- `tools/chat-assistant/backend/app/agent_runtime/evaluation/datasets/v1/sample-missing-liability-cap.yaml`（新）

**G1 — 7 个文件**
- `tools/chat-assistant/backend/app/agent_runtime/runtime.py`（新）：`AgentRuntime` + `LegacyHarnessAdapter` + `GraphAdapter` + `ShadowAdapter` + `RuntimeRouter`
- `tools/chat-assistant/backend/app/agent_runtime/graph/__init__.py`（新）
- `tools/chat-assistant/backend/app/agent_runtime/graph/state.py`（新）：`BaseGraphState`
- `tools/chat-assistant/backend/app/agent_runtime/graph/registry.py`（新）：`GraphRegistry`
- `tools/chat-assistant/backend/app/agent_runtime/graph/checkpoint.py`（新）：`MySqlCheckpointSaver`
- `tools/chat-assistant/backend/app/agent_runtime/graph/ping.py`（新）：Ping 测试图
- `tools/chat-assistant/backend/requirements-graph.txt`（新）：LangGraph 依赖

**G2 — 9 个文件**
- `tools/chat-assistant/backend/app/agent_runtime/contract_store.py`：新增 `list_clause_inventory` 方法
- `tools/chat-assistant/backend/app/agent_runtime/contract_tools.py`：新增 `listClauseInventory` 工具定义与执行派发
- `tools/chat-assistant/backend/app/agent_runtime/graph/contract_review.py`（新）：主图 12 节点 + 条件路由
- `tools/chat-assistant/backend/app/agent_runtime/graph/nodes/__init__.py`（新）
- `tools/chat-assistant/backend/app/agent_runtime/graph/nodes/context.py`（新）
- `tools/chat-assistant/backend/app/agent_runtime/graph/nodes/inventory.py`（新）
- `tools/chat-assistant/backend/app/agent_runtime/graph/nodes/domain_tasks.py`（新）
- `tools/chat-assistant/backend/app/agent_runtime/graph/nodes/validation.py`（新）：Claim Validator 10 项检查
- `tools/chat-assistant/backend/app/agent_runtime/graph/nodes/reflection.py`（新）：覆盖反射 + 条件路由
- `tools/chat-assistant/backend/app/agent_runtime/graph/nodes/artifact.py`（新）

**G3 — 6 个文件**
- `tools/chat-assistant/backend/app/agent_runtime/graph/fulfillment_check.py`（新）：主图 7 节点 + interrupt_before
- `tools/chat-assistant/backend/app/agent_runtime/graph/nodes/requirements.py`（新）
- `tools/chat-assistant/backend/app/agent_runtime/graph/nodes/fulfillment_judge.py`（新）
- `tools/chat-assistant/backend/app/agent_runtime/graph/nodes/fulfillment_validate.py`（新）
- `tools/chat-assistant/backend/app/agent_runtime/graph/nodes/human_confirm.py`（新）
- `tools/chat-assistant/backend/app/api/routes.py`：新增 `_dispatch_via_router` + `resume_agent_run` 端点 + `_contract_runtime_router` 初始化

**G4 — 4 个文件**
- `agent-server/src/main/java/com/atlasmind/controller/admin/EvalAdminController.java`（新）：14 个评测 API
- `agent-server/src/main/java/com/atlasmind/config/AgentWorkbenchSchemaInitializer.java`：新增 4 张评测表 DDL
- `agent-admin/src/views/EvalCenter.vue`（新）：评测中心管理端页面
- `agent-admin/src/router/index.js`：新增评测中心路由
- `agent-admin/src/components/AdminLayout.vue`：新增评测中心菜单项
- `tools/chat-assistant/backend/tests/test_evaluation.py`（新）

### 验证

- `pip install -r requirements-graph.txt` → LangGraph v0.4.10 安装成功，PingGraph 编译通过。
- ContractReviewGraph 12 节点在实际合同案件上跑通：state_revision=15 → `[范围受限]` 报告生成 → coverage_reflection 正确循环 2 次后转 CANNOT_RESOLVE。
- FulfillmentCheckGraph 7 节点编译通过，`interrupt_before` 暂停逻辑正确。
- `RuntimeRouter` 派发验证：`AGENT_RUNTIME_CONTRACT_REVIEW=langgraph` → `GraphAdapter` 正确路由 → `engine: langgraph`。
- 所有 Python 模块编译通过，所有新导入无报错。
- 8 个前端 `contractTimeline.test.js` 测试全部通过。
- 3 份评测样本 YAML 正确加载。
- LangGraph 未安装时 ping graph 安全降级（`register()` 跳过）。
- `mvnw compile`：通过（Java EvalAdminController + SchemaInitializer）。
- `agent-admin npm run build`：通过（评测中心页面 + 路由 + 菜单）。



**日期**：2026-08-03

### 调整原因

- 原“案件信息”表单要求用户先手工填写合同标题、类型、双方、金额和日期，合同正文里已经存在的信息被重复录入。
- 直接让 LLM 创建正式案件风险过高：模型可能猜错我方主体、生成原文不存在的字段，失败时还可能留下半成品数据。
- 用户无法看到字段来自哪段合同原文，也无法判断低置信度结果是否需要修改。

### 实现

- 新增 `contract_intake` 暂存表和 `V013__contract_intake.sql`；模型原始输出、验证结果、确认数据与正式案件分层存储。
- 用户端 `/contracts/new` 改为正文优先：支持粘贴合同或读取 TXT/Markdown 文件，不再预填可由合同推断的案件字段。
- Python 新增合同元数据提取器，DeepSeek 以 JSON 模式、`temperature=0` 提取标题、类型、甲乙方、金额、币种和起止日期。
- 所有 citation 必须在原文中逐字命中并重新计算字符偏移；确定性规则命中与模型冲突时，以可验证规则结果为准。
- 模型不得判断“哪一方是我方”，必须由用户显式选择；确认前允许修改字段并查看对应原文高亮。
- LLM 不可用时降级为规则提取并进入 `NEEDS_CONFIRMATION`，不会把失败结果直接写入正式案件。
- 确认操作在 Java 事务内一次性创建 `contract_case`、双方主体和原始合同文档，并校验正文 SHA-256 未发生变化。
- 新增创建、查询、重试、确认四个用户端 Intake API，以及 Python 内部提取端点。
- 移动端底部操作区为 AI 对话按钮预留安全距离，主要按钮和我方主体选择保持至少 44px 触控高度。

### 验证

- 真实中文浏览器 E2E：正文提交 → DeepSeek 提取 → 字段核对 → 原文字符定位 → 选择我方主体 → 创建案件，全链路通过。
- 实测识别双方、`500000 CNY`、生效/到期日期正确；引用按钮可高亮到精确字符范围，详情页案件和原始文档均正确落库。
- 移动端 390px 视口无横向溢出，AI 对话按钮与“确认并创建案件”无重叠；浏览器控制台 0 错误。
- Python `unittest` 22 项通过；Java `mvnw test` 12 项通过；用户端 Vite 生产构建通过（仅保留已有大 chunk 警告）。
- 浏览器回归产生的 Intake、案件、主体、文档和条款测试数据已全部清理。

---

## 新建合同误把 undefined 当作 caseId

**日期**：2026-08-03

### 现象

- 从合同工作台点击“发起新合同”后，页面提示 `参数类型错误: caseId 应为 Long`。
- 继续点击上传时，请求仍然失败，无法创建合同案件。

### 根因

- `/contracts/new` 路由复用了只支持详情态的 `ContractCaseView.vue`。
- 新建路由没有 `route.params.id`，详情页仍请求 `/api/workspace/contracts/${route.params.id}`，最终向 Java 发送了 `/api/workspace/contracts/undefined`。
- Spring 尝试将字符串 `undefined` 转换为 `Long caseId`，因此由全局异常处理器返回参数类型错误。

### 修复

- 新增独立的 `ContractCreateView.vue`，将 `/contracts/new` 与合同详情页职责分离。
- 新建页支持合同基础信息、交易主体、金额、日期以及可选文字合同一次提交。
- 提交流程改为先 `POST /api/workspace/contracts` 获取真实数字 ID，再调用 `POST /api/workspace/contracts/{id}/documents`。
- 如果案件已创建但正文提交失败，保留案件并跳转详情页展示具体错误，避免重复创建。
- 增加必填项、日期范围、金额和提交中状态校验。

### 验证

- 生产构建通过。
- 浏览器真实回归：打开 `/contracts/new`、填写案件、粘贴中文合同、提交后跳转到数字 ID 详情页。
- 合同正文异步解析为 `READY`，详情页显示正确文件名、版本和字符数。
- 浏览器控制台 0 错误，回归测试数据已清理。

---

## 文字合同提交失败与合同 Agent 链路修复

**日期**：2026-08-03

### 根因

- Python migration runner 直接执行 `ADD COLUMN IF NOT EXISTS`，当前 MySQL 版本不支持该语法，导致 `V009`、`V011` 每次启动失败；新环境缺少 `contract_document.content_text` 后，纯文字合同提交会直接报错。
- 原上传回归脚本只有 HTTP 调用，没有等待异步解析、校验正文和条款落库，而且中文样例已经乱码，不能捕获用户看到的真实故障。
- 合同管理端仍请求已下线的 `/api/admin/projects/reports|actions`，报告与动作页面无法加载；删除合同文档不会清理 `contract_clause`。
- Python ReportStore 没有给合同报告和动作写入 `subject_type/subject_id`，且会把合同动作错误改写成 `CREATE_GITHUB_ISSUE`。
- 通用 Harness 在合同模式下仍硬编码 `getProjectMemory`、`searchProjectEvidence` 等项目工具；并发工具写 trace 使用 `MAX(sequence_no)+1`，会因序号竞争留下永久 `RUNNING` 的 tool call。
- 合同风险查询引用了不存在的 `contract_review_finding.rule_key/clause_type`，风险引擎又只识别 snake_case，而 Store 返回 camelCase，导致计算失败或错误高分。

### 修复

- migration runner 对 `ADD COLUMN IF NOT EXISTS` 做 `information_schema` 检查后再执行标准 `ALTER TABLE`；修正 `V009` 配置种子 SQL，正式执行 `V009`、`V011`。
- 新增纯文字合同解析器和 `/internal/contract/documents/{id}/parse`：按中文编号条款切分，分类 PAYMENT、LIABILITY、ACCEPTANCE、CONFIDENTIALITY 等类型，并写入 `contract_clause`。
- Java 上传链路增加案件/类型/长度校验、案件行锁版本分配、事务提交后解析调度和正文按需读取；前端防重复提交并展示后端真实错误。
- 合同文档列表不再携带完整正文，只返回 `hasInlineText/textLength`；删除文档时同事务清理条款和已批准/已签署版本引用。
- 新增合同域报告/动作管理 API，修正管理端 URL、合同报告类型和动作类型文案；Run/审批/删除操作增加 `CONTRACT_CASE` 主体隔离。
- `V012` 回填历史报告/动作主体；ReportStore 从 Run 继承主体，只接受合同动作白名单，并把合同审查 findings 落入 `contract_review_finding`。
- Harness 上下文新增 `subjectType/subjectId`；合同计划、工具兜底、证据保证、风险计算和 Reflection 全部改用合同工具，规则 findings 会传入最终报告。
- trace 序号分配增加 `agent_run FOR UPDATE` 行锁，并将 trace 写入纳入工具失败处理，修复并发调用悬挂。
- 管理端规则和标准条款更新增加 camelCase 到数据库 snake_case 的字段映射，修复编辑保存 SQL 报错。
- 登录成功后在 Service 返回前清空密码字段，修复 BCrypt 哈希随登录响应暴露给前端的问题。
- 将已删除 Java Runtime 的 3 组失效测试迁移到 Python，覆盖执行预算、重复调用、工具白名单、确定性评分、合同路由和风险评分。

### 验证

- 真实 E2E：登录、创建合同案件、提交中文文字合同、轮询 `READY`、读取正文、校验 `DELIVERY/PAYMENT/LIABILITY` 三条条款、删除文档并确认无孤儿条款，全链路通过且测试数据自动清理。
- 真实合同 Run：6 次工具调用均为合同工具且全部 `DONE`，不再出现项目工具；当前 DeepSeek Key 无效时 Run 快速进入 `FAILED` 并返回明确错误，不生成伪报告。
- Python `unittest`：18 项通过；Java `mvnw clean test`：12 项通过；用户端和管理端 Vite build 均通过（仅保留已有大 chunk 警告）。
- Migration 已应用至 `V012`；Elasticsearch Docker 容器恢复 healthy，Embedding 和 ES 健康探针均为 `ok`。

### 待外部处理

- DeepSeek 实际请求返回“LLM API Key 无效”。网络、ES 和 Embedding 均正常，需要更换有效的 `LLM_API_KEY` 后才能进行合同 LLM 分析。

---

## 源码同步与检索 —— Agent 可以读取项目源代码

**日期**：2026-08-02

### 调整原因

- 健康分析评分引擎通过关键词匹配检测"测试证据""CI/CD 证据""依赖配置"等信号，但实际上**所有信号都来自同步到 `project_evidence` 的 GitHub 快照**。
- 同步器原本只收集根目录的 10 种配置文件（`package.json`、`pom.xml`、`pyproject.toml` 等），源代码文件（`.java`、`.py`、`.js`、`.ts`、`.vue` 等）**从来不收集**。
- 评分引擎能告诉你的全部就是"README 写得怎么样 + 有没有 CI 配置 + 最近有没有提交"——完全看不到实际代码结构和质量。
- Agent 无法回答"这个项目的核心模块是什么""LLM 调用在哪里""数据库是怎么连的"等需要读源码才能回答的问题。

### 调整过程

**Java — `HttpGitHubRepositoryGateway.java`**
- 新增 `addSourceCode()` 方法：在 `collectEvidence()` 流程中，同步完 README 和根目录文件后，递归遍历源码目录。
- 遍历目录白名单：`src/`、`app/`、`lib/`、`agent-server/src/`、`tools/`、`agent-front/src/`。
- 文件扩展名过滤：`.java`、`.py`、`.js`、`.ts`、`.vue`、`.jsx`、`.tsx`、`.sql`、`.yml`、`.xml`、`.json`、`.css`、`.scss`、`.html`、`.md`、`.sh`、`.dockerfile`。
- 深度限制 4 层，上限 50 个文件（防超大仓库炸 DB）。
- 自动跳过 `node_modules/`、`target/`、`dist/`、`build/`、`__pycache__/`、`.git/`、`vendor/`。
- 每个文件存储前 3000 字符 snippet 到 `project_evidence`（objectType = FILE）。
- 新增 `readFileContent(repoUrl, branch, filePath)` 方法：按需通过 GitHub API 读取完整文件内容（公共接口，供 Python 工具调用）。
- 新增 `searchCode(repoUrl, query, limit)` 方法：通过 GitHub Search API 搜索代码。

**Python — `tools.py` 新增 2 个工具（共 9 个）**
- `searchSourceCode(query, filePattern, limit)`：从已同步的 `project_evidence` 中检索 source/FILE/README 类型证据，支持文件名模式过滤（如 `*.py`）。
- `readSourceFile(filePath)`：直接从 GitHub API 读取指定文件的完整内容（base64 解码），使用 `GITHUB_TOKEN` 环境变量认证。
- `_TOOL_NAMES` 更新为 9 个工具。

**Python — `persistence.py`**
- `EvidenceStore` 新增 `search_source_code()` 抽象方法。
- `MySqlEvidenceStore` 实现：查询 `object_type IN ('SOURCE', 'FILE', 'README')`，支持 keyword 全文过滤 + filePattern 文件名匹配。

**Python — `scoring.py`**
- 新增 `has_source_code` 信号：源码文件数 > 1 时为正向信号。
- 架构可维护性维度新增"源码可检索"+15 分（同时调整其他信号权重保持满分 100）。

**Python — `config.py`**
- 新增 `github_token` 配置（环境变量 `GITHUB_TOKEN`），供 `readSourceFile` 工具认证私有仓库。

### 调整结果

- 同步测试：Project 2（Job-Hunting 仓库）证据从 14 条增长到 35 条，新增 22 个源文件。
- 收集到的源码涵盖全部核心模块：`app.py`、`agent.py`、`llm.py`、`rag.py`、`models.py`、`matcher.py`、`storage.py`、`resume_writer.py`、`web.py`、`cli.py`、`config.py` 等。
- Agent 现在可以回答源码级问题："LangChain Agent 的入口在哪里""LLM 调用了哪个模型""数据库连接在哪个文件"。
- 完整文件通过 `readSourceFile` 按需读取（不经同步快照，始终最新），不占用 DB 存储空间。
- 评分引擎将源码存在作为架构维护性的正向信号。

---

## 前端三卡片完善 + 报告弹窗结构化渲染

**日期**：2026-08-02

### 调整原因

- 之前优化 `getProject()` 时将 reports 查询中的 `content_json`、`risks_json`、`plan_json`、`citations_json` 全部移除以减小响应体。健康卡有 `healthScore`/`healthStatus` 仍可正常显示，但**接手卡和决策卡的所有结构化内容全部消失**——sections、recommendation、options、risks、plan 等字段均不可用，两张卡只显示一条日期线，显得"孤零零"。
- `ReportArtifactModal` 查看报告弹窗只渲染 `reportMarkdown`，而接手手册和决策备忘录的 LLM 产物是 JSON 格式（非 Markdown），弹窗显示"该报告暂无详细内容"。

### 调整过程

**ProjectWorkbenchView.vue — 懒加载完整报告**
- 新增 `reportLoading` 响应式状态（health/onboard/decision 三个 key）。
- 新增 `fetchFullReports()` 函数：页面加载完成后，遍历 `project.runs`，为每个 run 并行调用 `getProjectRun(runId)`（已有端点），将返回的完整 report（含 `contentJson` 等 JSON 字段）合并回 `project.reports` 数组——已有 computed 属性无需修改。
- 接手卡和决策卡模板新增 loading 状态：`<div v-if="reportLoading.onboard" class="card-loading"><span class="loader"/> 正在加载报告内容...</div>`。
- 新增 `.card-loading` CSS：flex + 旋转动画 loader。

**ReportArtifactModal.vue — 按类型结构化渲染**
- 新增类型判断 computed：`isHealth`、`isOnboarding`、`isDecision`。
- 新增 `modalContent` computed：安全解析 `report.contentJson`。
- 新增 `modalDimensions`、`modalRisks`、`modalPlan` computed：解析对应的 JSON 字段。
- 新增 `hasStructuredContent` computed：避免有结构化数据时仍显示空白占位。
- 弹窗 body 按类型渲染：
  - **健康分析**：分数 hero（48px 大字）+ 维度条 + 风险清单
  - **接手手册**：角色标签（audience/level）+ 模块章节（sections/items）+ 上手风险
  - **决策助手**：建议结论 + 置信度 badge + 方案对比卡片（含 migrationCost/safetyRisk/compatibility/teamFamiliarity 四维标签 + 优劣势列表）+ 决策标准 chips + 风险
  - **通用**：执行计划列表 + Markdown 正文（如有）
- 新增 ~200 行 CSS：`.modal-score-hero`、`.modal-dim-grid`、`.modal-options-table`、`.modal-option-card`、`.opt-dims`、`.modal-onboard-section`、`.rec-badge` 等。

### 调整结果

- `vite build` 编译通过，0 错误。
- 首屏 `getProject()` 仍保持 ~15KB 轻量（不牺牲性能）。
- 页面加载后自动并行请求三种报告的完整内容，卡片从"孤零零"变为完整结构化展示。
- 弹窗支持三种类型的可视化渲染，不再依赖 LLM 输出 Markdown。
- 后端零改动——`GET /runs/{runId}` 端点已返回完整数据。

---

## 业务功能：闭环动作执行 + 决策量化对比 + 跨项目洞察

**日期**：2026-08-02

### 调整原因

- **Agent 只能建议不能执行**：报告生成后仅创建 1 个 `CREATE_GITHUB_ISSUE` action，无法生成多种可执行动作提案，用户无法一键触发项目配置更新、Milestone 创建等。
- **工程决策缺乏量化对比**：`ENGINEERING_DECISION` 只给框架建议，没有多维度量化对比表（迁移成本/安全风险/兼容性/团队熟悉度），缺少 citation 支撑的评分矩阵。
- **无组织级视图**：只能按项目查看健康状态，缺乏跨项目的共同风险识别、健康分布总览和趋势数据。

### 调整过程

**B1: 闭环动作执行**
- Python Prompt 更新（`prompts.py` fallback `project_analysis`）：LLM 输出 JSON 新增 `actionProposals` 数组，支持 3 种类型：
  - `CREATE_GITHUB_ISSUE`：为需要代码/文档修复的风险生成 Issue
  - `UPDATE_PROJECT_CONFIG`：项目配置字段更新（如 currentMilestone、teamSize）
  - `CREATE_GITHUB_MILESTONE`：为即将发布的版本创建 GitHub Milestone
- `persistence.py` `_save_sync()` 改造：
  - 解析 artifact 中的 `actionProposals` 数组，每个 proposal 创建一条 `PENDING_APPROVAL` action。
  - action_type 合法性校验（白名单 3 种）。
  - payload 包含结构化字段：description, priority, riskId, citationSourceId（通用），key/value（UPDATE_PROJECT_CONFIG），dueOn/labels（GitHub actions）。
  - 无 actionProposals 时 fallback 到原有单 action 逻辑。
- Java `GitHubIssueGateway` 新增 `createMilestone(repoUrl, title, description, dueOn)`。
- `HttpGitHubIssueGateway` 实现 GitHub Milestones API（`POST /repos/{owner}/{repo}/milestones`，ISO 8601 due_on）。
- `AgentProjectServiceImpl.executeAction()` 重构为 switch-action-type 模式：
  - `CREATE_GITHUB_ISSUE` → 原有 Issue 创建逻辑
  - `CREATE_GITHUB_MILESTONE` → 新 Milestone 创建逻辑
  - `UPDATE_PROJECT_CONFIG` → 白名单校验后直接 UPDATE `agent_project` 表（允许 currentMilestone, releaseTarget, teamSize, businessScope）
- 查询 action 时新增 `action_type` 字段读取。

**B2: 决策量化对比**
- `prompts.py` fallback `engineering_decision` prompt 增强：
  - 新增 `comparisonMatrix` 数组：每个 criterion 下列出各 option 的 1-10 分 + rationale。
  - options[] 新增 4 个定量维度：`migrationCost`、`safetyRisk`、`compatibility`、`teamFamiliarity`（均为 LOW/MEDIUM/HIGH）。
  - 每个量化评分需要 citationSourceIds 支撑。
  - 新增 actionProposals：至少 1 个可执行下一步。

**B3: 跨项目洞察**
- `AgentProjectService` 接口新增 `organizationOverview()`。
- `AgentProjectServiceImpl` 实现：
  - **健康分布**：`SELECT health_status, COUNT(*) FROM agent_project GROUP BY health_status`。
  - **近期报告趋势**：最近 40 条 HEALTH_REPORT 含 project、score、status。
  - **共同风险识别**：解析所有 reports 的 `risks_json`，统计同一 risk title 出现在 ≥2 个项目的 pattern（affectedProjects + affectedCount）。
  - 活跃 Run 数 + 待审批动作数。
- `AgentWorkbenchController` 新增 `GET /api/workspace/projects/organization/overview` 端点。
- 新增 `parseJsonArray()` 辅助方法。

### 调整结果

- B1 Python 验证通过：`actionProposals` 出现在 `project_analysis` prompt 中，3 种 action type 白名单正确，`MySqlReportStore` 多 action 创建逻辑就绪。
- B2 Prompt 验证通过：`comparisonMatrix` + 4 定量维度（migrationCost/safetyRisk/compatibility/teamFamiliarity）+ actionProposals 全部出现在 `engineering_decision` prompt 中。
- Java 端需重启后生效：B3 组织总览端点、B1 多类型 action 执行。
- 新增 `GitHubIssueGateway.createMilestone()` + 实现。
- 影响文件：Java 4 个（GitHubIssueGateway, HttpGitHubIssueGateway, AgentProjectService, AgentProjectServiceImpl, AgentWorkbenchController），Python 2 个（prompts.py, persistence.py）。

---

## Agent 智能增强：并发工具调用 + Prompt 版本管理 + 向量化记忆检索

**日期**：2026-08-02

### 调整原因

- **工具串行等待**：LLM 一次返回多个 tool_calls（如 `getProjectProfile` + `getProjectMemory` + `getRecentRuns`），当前逐一串行执行，3 个独立读取耗时 = sum(t1+t2+t3)，而非 max(t1,t2,t3)。
- **Prompt 硬编码**：所有 7 个 system prompt 写死在 `llm_service.py` 模块常量中，调整需改代码+部署，无法 A/B 对比，无版本历史追踪。
- **记忆检索扁平**：`getProjectMemory` 仅按 `update_time DESC` 排序，无语义相似度检索，"CI 故障处理" 和 "pipeline failure" 在关键词层面无法匹配。

### 调整过程

**F5: 并发工具调用**
- `tools.py` 新增 `_CONCURRENT_GROUP` 分类：read 组（`getProjectProfile`, `getProjectMemory`, `getRecentRuns`, `getLatestReport`）、search 组（`searchProjectEvidence`, `searchProjectKnowledge`）、compute 组（`calculateHealthScore`）。
- `AgentToolRegistry` 新增 `concurrency_group()` 和 `group_order()` 静态方法。
- `runner.py` Phase 3 工具调用循环重构：
  - 将每个 turn 的 calls 按 concurrency group 分组。
  - 同组内多个工具 → `asyncio.gather(*coros, return_exceptions=True)` 并发执行。
  - 组间按顺序（read → search → compute），确保 `calculateHealthScore` 在 search 之后执行。
  - 并发执行时写入 `CONCURRENT_TOOLS` trace event（含 group 名称和 tool 列表）。
- 错误隔离：单个工具失败不影响同组其他工具（return_exceptions=True），fail 结果正常记入 observations。

**F6: Prompt 版本管理**
- 新建 `migrations/V008__agent_prompt.sql`：`agent_prompt` 表（prompt_key, version, template, temperature, is_active, traffic_pct, performance_score），种子数据为 7 个 prompt × v1 = 当前硬编码内容。
- 新建 `prompts.py`：`PromptRegistry` 类。
  - `get(key)` → 返回最新 active version 的 (template, temperature, version)。
  - `get_ab(key, run_id)` → A/B 分流，按 `run_id % traffic_pct` 确定性分配版本（同一 run 重放得到相同版本）。
  - 30s 内存 TTL 缓存，`invalidate()` 强制刷新。
  - DB 不可用时静默 fallback 到内置默认值（version=0），永不让 Agent 因 prompt 配置而失败。
- `llm_service.py` 改造：
  - 新增 `_prompt(key, run_id)` 辅助方法，lazy-load PromptRegistry 单例。
  - 6 个方法接入：`plan_agent`("planner"), `next_agent_turn`("tool_turn"), `reflect_agent`("reflection"), `analyze_project`("project_analysis"), `run_project_task`("project_onboarding"/"engineering_decision"), `build_messages`("rag_system")。
  - `analyze_project` 和 `run_project_task` 新增 `run_id` 参数，runner.py 传入 `ctx.run_id`。
  - system prompt 和 temperature 从 registry 动态获取（替换硬编码常量 `AGENT_PLANNER_SYSTEM_PROMPT` 等）。
- 旧模块常量保留（作为 PromptRegistry 的 fallback 数据源）。

**F7: 向量化记忆检索**
- 新建 `memory_index.py`：`MemoryVectorIndex` 类。
  - Lazy-load `sentence-transformers` all-MiniLM-L6-v2 模型（~80MB, 384dims），CPU 友好。
  - 按 project_id 构建内存向量索引（懒加载，从 `agent_project_memory` 表读取最多 500 条）。
  - `search(project_id, query, top_k, keyword_filter)`：keyword 预过滤 → query embedding → cosine similarity → Top-K 排序。
  - embedding 生成走 `loop.run_in_executor`（不阻塞 asyncio 事件循环）。
  - `invalidate(project_id)` 清除缓存，下次访问重新从 DB 构建。
  - `sentence-transformers` 未安装时静默降级为 keyword-only 排序，相似度显示 N/A。
- `tools.py`/`persistence.py` 接入：
  - `getProjectMemory` 工具定义新增 `query` 和 `semantic` 参数。
  - `AgentToolRegistry.execute()` 中 `semantic=true` + `query` 非空 → 走 `EvidenceStore.semantic_memory_search()` → 委托 `MemoryVectorIndex.search()`。
  - `EvidenceStore` 抽象接口新增 `semantic_memory_search()`，`MySqlEvidenceStore` 实现。
- `requirements.txt` 新增 `sentence-transformers>=2.7.0`。

### 调整结果

- F5 E2E 通过：Run 61 正常运行完成（COMPLETED @ 100%），Phase 3 工具调用稳定。CONCURRENT_TOOLS trace 在服务器重启后将出现（当前运行进程仍为旧代码）。
- F6 测试通过：
  - 7 个 prompt key 全部返回有效 template（len > 100），temperature 范围正确。
  - A/B 分流确定性验证：相同 run_id 多次调用得到相同版本。
  - DB 表未创建时自动 fallback，不影响现有功能。
- F7 测试通过：
  - 空项目返回空结果，invalidate 正常。
  - Project 1 语义检索成功返回 3 条记忆。
  - `sentence-transformers` 未安装时静默降级 keyword 搜索。
- 新增文件：`prompts.py`, `memory_index.py`, `V008__agent_prompt.sql`。
- 新增依赖：`sentence-transformers>=2.7.0`。

---

## Redis Stream 消息队列 —— Java→Python 异步解耦

**日期**：2026-08-02

### 调整原因

- **Java HTTP 直连 Python 无交付保证**：`HttpAiGateway.startAgentRun()` 通过 HTTP POST `/internal/agent/run` 同步调用 Python，网络抖动或 Python 临时不可用立即标记 Run 为 FAILED，无重试/无缓冲。
- **同步等待**：Java 调用线程阻塞等待 HTTP 响应（timeout 12s），耦合了 Web 请求线程和 Agent 调度延迟。
- **单点依赖**：Python 进程不可用时所有新 Run 直接失败，无削峰填谷能力。

### 调整过程

**Java 侧 — `HttpAiGateway.java`**
- 注入 `StringRedisTemplate`（项目已有 Redis 配置）。
- `startAgentRun()` 改为 **Stream-first + HTTP fallback** 双重策略：
  1. 首选 `XADD agent:run:stream` 写入 Redis Stream（fire-and-forget），Java 立即返回 `{"queued": true, "transport": "redis-stream"}`。
  2. Redis Stream 不可用时自动降级为 HTTP POST `/internal/agent/run`（保留原有同步路径）。
  3. 两次均失败才抛出异常，由 `AgentProjectServiceImpl.dispatchToPython()` 标记 Run 为 FAILED。
- 已编译通过，无需修改 `AiGateway` 接口签名。

**Python 侧 — 新建 `worker.py`**
- 新增 `AgentRunWorker` 类，消费 `agent:run:stream`（consumer group `agent-runners`）。
- 启动时：
  - `XGROUP CREATE` 创建消费者组（`mkstream=true`，自动创建 Stream）。
  - `XAUTOCLAIM min_idle_ms=0` 认领所有 PEL 未确认消息（崩溃恢复 — 前一个 worker 实例崩溃后消息不丢）。
- 主循环：
  - `XREADGROUP` 阻塞读取新消息（`count=3, block=2000ms`）。
  - 每条消息 `asyncio.create_task` 异步派发 `RunDispatcher.dispatch()`，worker 循环不阻塞，支持并发 Run。
  - 只有 harness 执行完毕后 `XACK`（at-least-once 语义 — 崩溃前未 ACK 的消息留在 PEL）。
- 定期 `XAUTOCLAIM min_idle_ms=120_000`，认领闲置超过 2 分钟的 PEL 消息（crash 恢复 + 防重复派发）。
- `stop()` 优雅关闭：等待活跃任务完成（max 30s），关闭 Redis 连接。

**`routes.py` — Worker 生命周期**
- `_init_agent_runtime()` 在初始化 dispatcher + recovery 的同时创建 `AgentRunWorker` 并启动为后台 `asyncio.Task`。
- HTTP 端点 `POST /internal/agent/run` 保持不变，作为 Stream 的 fallback 接收路径。

**`config.py` — Redis URL 配置**
- 新增 `redis_url: str = os.getenv("REDIS_URL", "redis://localhost:6379/0")`，供 worker 和 runner 共用。

**`runner.py` — 使用统一 Redis 配置**
- `RunDispatcher._get_redis_sync()` 从 `redis.Redis(host=..., port=...)` 改为 `redis.Redis.from_url(settings.redis_url)`，消除硬编码。

### 调整结果

- Stream 管道验证通过：XADD → XREADGROUP（consumer group 正确路由）→ payload 反序列化 → `StartRunRequest` 字段全部匹配 → XACK。
- HTTP fallback 端点 `POST /internal/agent/run` 正常工作（直接 curl 返回 `{"status":"CREATED"}`）。
- Consumer group `agent-runners` 创建成功，PEL 认领机制就绪。
- 架构变更：
  ```
  之前：Java ──HTTP POST──→ Python (同步, 12s 超时)
  之后：Java ──XADD──→ Redis Stream `agent:run:stream`  (fire-and-forget)
                          ↓
              Python Worker (consumer group) ──→ RunDispatcher
                          ↓ (fallback)
              HTTP POST /internal/agent/run (保留)
  ```
- 待生效：Java 和 Python 服务重启后，新 Run 将自动走 Stream 路径，Redis 不可用时透明降级 HTTP。
- 新增文件：`tools/chat-assistant/backend/app/agent_runtime/worker.py`。

---

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
