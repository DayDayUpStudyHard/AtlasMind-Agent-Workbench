# AtlasMind 企业合同全生命周期运营 Agent PRD

**版本**：v1.0  
**日期**：2026-08-03  
**状态**：Draft  
**产品代号**：AtlasMind ContractOps Agent  
**首期合同类型**：企业服务采购合同

---

## 1. 文档目的

本文档定义 AtlasMind 从“研发项目智能交付 Agent”转向“企业合同全生命周期运营 Agent”的完整产品方案和分阶段实施计划。

本次转向不是把页面中的“项目”替换为“合同”，而是将系统业务主对象、知识体系、Agent 工具、报告结构、审批动作和持续跟踪机制全部切换到合同全生命周期。

### 1.1 产品定位

AtlasMind ContractOps Agent 面向企业业务、采购、法务、财务和合同管理人员，围绕一个合同案件持续完成：

1. 合同发起、类型判断和材料清单生成。
2. 基于企业批准模板生成或准备合同初稿。
3. 合同和附件收集、关键信息与条款结构化。
4. 基于企业制度和标准条款的风险审查。
5. 缺失材料、条款修改、协商和审批动作提案。
6. 合同版本变化复核和签署版本核验。
7. 签署后履约义务登记、提醒和异常升级。
8. 续签、重新谈判或终止评估。
9. 全过程证据引用、运行轨迹和审计留痕。

### 1.2 一句话价值

> 帮助企业更快发起和签署合同、降低审查错误，并持续保证履约事项不遗漏。

### 1.3 产品边界

AtlasMind 提供辅助审查和履约管理，不替代律师出具法律意见，不自动代表企业签署合同，不自动付款，也不允许模型绕过审批执行高风险动作。

---

## 2. 转向背景与现有资产

### 2.1 原方向的主要困难

研发项目交付状态依赖需求、人员排期、CI、发布平台和团队意图。单靠 GitHub 难以准确判断项目能否按期交付，容易退化为一次性报告。

合同场景具有更明确的输入、规则、责任人、审批结果和时间节点，更适合现有 Agent 底座形成可验证闭环。

### 2.2 可保留能力

以下能力继续复用：

- Java 用户、鉴权、管理端、审批和外部动作层。
- Python Agent Runtime、Redis Stream、恢复、取消、幂等和熔断。
- Planner、工具调用、Reflection、执行预算和运行轨迹。
- MySQL 结构化数据存储。
- Elasticsearch、Embedding、PDF 解析、OCR 和知识库。
- Agent Run、Trace、Tool Call、Memory、Report、Action。
- SSE 实时进度、消息中心和运行可观测性。
- Prompt 版本管理和评测基础设施。

### 2.3 必须替换的业务能力

- `agent_project` 项目主对象改为 `contract_case` 合同案件。
- GitHub 数据同步改为合同文件、附件和履约证据导入。
- 项目健康评分改为合同风险和材料完整性评分。
- 项目接手、研发决策报告改为合同审查、审批建议和履约计划。
- GitHub Issue、Milestone 动作改为补材料、协商、法务复核、义务登记和提醒动作。
- 项目组合页改为合同案件组合、风险分布和到期预警。

### 2.4 新旧产品完整对应关系

本节是转向实施的依据。对应关系表示“复用原有机制承载新领域”，不表示把研发项目历史数据直接解释成合同数据。

#### 2.4.1 产品概念对应

| 旧产品概念 | 新产品概念 | 迁移方式 | 说明 |
|---|---|---|---|
| 研发项目 | 合同案件 | 新建领域对象 | 合同案件覆盖发起、审查、签署、履约和续签，不等同于一个文件 |
| GitHub 仓库 | 合同文件集合 | 替换 | 输入从仓库、Issue、PR 改为合同正文、附件、报价和履约证据 |
| 项目证据 | 合同证据 | 重建结构 | 必须支持文件版本、页码、条款编号和文本范围 |
| Agent 参考库 | 合同知识中心 | 保留平台、替换内容 | 存放企业制度、标准模板、条款 Playbook 和历史决策 |
| 项目健康分析 | 合同风险审查 | 替换规则与产物 | 保留确定性评分机制，不复用原健康关键词和权重 |
| 项目接手任务 | 合同发起与材料准备 | 替换任务 | 输出材料清单、模板推荐和审批参与方 |
| 研发决策助手 | 合同审批决策 | 替换任务 | 输出接受、修改后接受、升级审批或拒绝建议 |
| 交付计划 | 协商与履约计划 | 替换产物 | 包含修改任务、义务、责任人、日期和证据要求 |
| 项目记忆 | 合同案件记忆 | 泛化存储 | 保存案件事实、审查确认、已批准例外和履约历史 |
| 项目对话 | 合同案件对话 | 改造上下文 | 回答必须限定当前合同版本、规则版本和用户权限 |
| 项目组合总览 | 合同组合驾驶舱 | 重做指标 | 展示待审、待批、到期、逾期、风险和金额分布 |

#### 2.4.2 Agent 任务对应

| 旧 Task Type | 新 Task Type | 是否迁移旧数据 | 实现策略 |
|---|---|---:|---|
| `HEALTH_ANALYSIS` | `CONTRACT_REVIEW` | 否 | 复用 Runner 和评分入口，替换工具、规则、Prompt 和 Artifact Schema |
| `PROJECT_ONBOARDING` | `CONTRACT_INTAKE` | 否 | 复用任务启动与报告框架，重新实现材料清单和模板推荐 |
| `ENGINEERING_DECISION` | `APPROVAL_DECISION` | 否 | 复用结构化比较能力，改为风险接受和审批路径决策 |
| 无 | `DRAFT_FROM_TEMPLATE` | 不适用 | 新增基于批准模板的受控初稿生成 |
| 无 | `VERSION_REVIEW` | 不适用 | 新增合同版本比较和增量复核 |
| 无 | `SIGNING_READINESS` | 不适用 | 新增批准版本、签署版本和附件完整性核验 |
| 无 | `OBLIGATION_EXTRACTION` | 不适用 | 新增履约义务候选项抽取 |
| 无 | `FULFILLMENT_CHECK` | 不适用 | 新增履约证据验证 |
| 无 | `RENEWAL_ASSESSMENT` | 不适用 | 新增续签、重谈或终止建议 |

旧 Run、Report 和 Action 只作为历史研发数据归档，不转换为合同任务。

#### 2.4.3 前台页面与模块对应

| 当前文件或入口 | 新入口 | 处理方式 |
|---|---|---|
| `ProjectOverviewView.vue` | `ContractPortfolioView.vue` | 新建合同组合页；旧页由产品模式开关控制，稳定后删除 |
| `ProjectWorkbenchView.vue` | `ContractCaseView.vue` | 新建合同工作台，不在旧页面继续堆叠条件分支 |
| `AgentTaskCard.vue` | `ContractTaskLauncher.vue` | 保留任务启动交互模式，替换任务定义和产物摘要 |
| `ReportArtifactModal.vue` | `ContractArtifactView.vue` | 从健康分布局改为合同原文、规则、风险和建议联动视图 |
| `RunFeed.vue` | 通用 Agent Run Feed | 保留并泛化 Subject 展示，不复制第二套运行组件 |
| `ChatWindow.vue` | 合同案件对话 | 项目选择器改为合同案件选择器，切换时隔离 Session |
| `KnowledgeView.vue` | 合同知识中心 | 增加知识类型、合同类型、适用地区和有效期筛选 |

新首页的四个一级入口固定为：

1. 发起新合同。
2. 审查待签合同。
3. 处理待办与审批。
4. 查看履约和到期事项。

#### 2.4.4 管理端对应

| 当前入口 | 新入口 | 处理方式 |
|---|---|---|
| `ProjectManage.vue` | 合同案件管理 | 替换业务管理页 |
| `EvidenceSync.vue` | 文件解析与索引任务 | 去除 GitHub 同步语言，展示合同解析、OCR、分块和索引状态 |
| `KnowledgeBase.vue` | 合同知识与规则管理 | 保留文档治理，增加元数据、规则集和发布流程 |
| `AgentRuns.vue` | 通用 Agent 运行 | 保留，增加 Subject Type、合同类型和 Task Type 筛选 |
| `ReportsApproval.vue` | 合同审查与动作审批 | 替换报告类型、风险例外和动作类型 |
| `AiObservability.vue` | 通用可观测性 | 保留，新增检索双引用覆盖率和合同敏感信息脱敏状态 |
| `Settings.vue` | 运行与合同配置 | 保留模型配置，新增产品模式、规则版本和提醒策略 |

#### 2.4.5 Java 后端对应

| 当前模块 | 新模块 | 决策 |
|---|---|---|
| `AgentProjectServiceImpl` | `ContractCaseModule` + 通用 `AgentRunModule` | 不把合同逻辑继续塞进原类；合同 CRUD 和运行查询分开 |
| `AgentWorkbenchController` | `ContractWorkspaceController` | 新增 `/api/workspace/contracts`，旧接口只用于兼容期 |
| `AgentProjectAdminController` | `ContractAdminController` | 新建合同、规则、报告和动作管理接口 |
| `HttpGitHubRepositoryGateway` | `ContractDocumentGateway` | GitHub 适配器停止扩展；新建文件、版本和解析状态适配器 |
| `GitHubIssueGateway` | `ContractWorkflowGateway` | 替换为任务、通知和审批动作适配器 |
| `AgentActionExecutor` | 通用 Action Dispatcher | 保留异步执行框架，按合同动作类型注册执行器 |
| `HttpAiGateway` | 通用 AI Gateway | 保留 Redis Stream + HTTP fallback，Payload 改用 Subject |
| `KnowledgeBaseServiceImpl` | 通用知识治理 | 保留，新增合同元数据和规则关联接口 |

Java 新模块不得重新形成一个合同巨石。建议外部接口保持为：案件管理、运行协调、审批动作和履约管理四个清晰模块。

#### 2.4.6 Python Runtime 对应

| 当前实现 | 新实现 | 处理方式 |
|---|---|---|
| `agent_runtime/runner.py` | 通用 Subject Runner | 保留 Harness、进度、取消、恢复和预算；移除项目字段假设 |
| `agent_runtime/tools.py` | 合同工具注册表 | 替换 GitHub/项目工具，保留注册、并发分组和结果隔离机制 |
| `agent_runtime/scoring.py` | `contract_risk_scoring.py` | 新建合同规则评分，不在原健康评分文件持续加条件 |
| `agent_runtime/prompts.py` | 合同任务 Prompt Registry | 保留版本和 A/B 机制，新增合同任务 Prompt Key |
| `agent_runtime/persistence.py` | Subject Store + Contract Store | 保留 Run/Trace 接口；新增合同发现、义务 Store，避免单类继续膨胀 |
| `memory_index.py` | Subject Memory Index | 将 `project_id` 改为 Subject Key |
| `llm_service.py` | 通用 LLM 调用层 | 保留重试熔断；合同 Prompt 和 Artifact 解析移出通用调用层 |
| `document_parser.py` | Contract Parser Adapter | 复用 PDF/OCR 能力，增加页码、条款和版本结构化 |
| `kb_service.py` / `es_service.py` | Policy Knowledge Retriever | 保留索引能力，增加元数据过滤、融合检索和双引用输出 |

#### 2.4.7 数据表对应

| 旧表 | 新表或处理方式 |
|---|---|
| `agent_project` | 新建 `contract_case`，旧表只归档，不改名复用 |
| `project_source` | 新建 `contract_document`，记录文件类型、版本和解析状态 |
| `project_sync_job` | 泛化为文档处理 Job，或新建 `contract_document_job` |
| `project_evidence` | 新建 `contract_clause` 与合同证据结构，旧表不承载合同条款 |
| `project_kb_document` | 新建 `contract_case_kb_document` |
| `agent_project_memory` | 迁移到 `agent_subject_memory` |
| `agent_run` | 增加 `subject_type`、`subject_id`，保留原表 |
| `agent_report` | 增加 Subject 关联和合同 Artifact Type，逐步废弃健康专用列 |
| `agent_action` | 增加 Subject 关联，保留审批和执行字段 |
| `agent_run_trace` | 原样保留，Trace 内容增加脱敏要求 |
| `agent_tool_call` | 原样保留，工具名和参数改为合同领域 |
| `kb_*` | 保留，增加合同知识元数据和适用范围 |

#### 2.4.8 动作对应

| 旧动作 | 新动作 | 迁移说明 |
|---|---|---|
| `CREATE_GITHUB_ISSUE` | `CREATE_NEGOTIATION_TASK` | 复用待审批、异步执行和结果记录，不复用 GitHub Payload |
| `CREATE_GITHUB_MILESTONE` | `SCHEDULE_REMINDER` | 从研发里程碑改为合同日期提醒 |
| `UPDATE_PROJECT_CONFIG` | `UPDATE_CONTRACT_METADATA` | 仅允许白名单字段，并记录前后值 |
| 无 | `REQUEST_MATERIAL` | 请求业务方或相对方补充材料 |
| 无 | `REQUEST_LEGAL_REVIEW` | 创建法务复核任务 |
| 无 | `DRAFT_CLAUSE_REVISION` | 生成受控修改建议，不直接覆盖原合同 |
| 无 | `REGISTER_OBLIGATIONS` | 审批后批量登记履约义务 |
| 无 | `ACCEPT_RISK_EXCEPTION` | 授权人员接受风险并设置失效时间 |
| 无 | `ESCALATE_OBLIGATION` | 逾期或违约事项升级 |

#### 2.4.9 迁移原则

1. **不做字符串替换式转向**：Project 与 Contract Case 的生命周期不同，必须新建合同领域模型。
2. **先泛化通用底座**：Run、Trace、Tool Call、Memory、Report 和 Action 先支持 Subject，再接合同功能。
3. **旧数据不伪迁移**：研发报告不能转成合同报告，只能归档和只读查看。
4. **双模式只用于过渡**：`PRODUCT_MODE` 是回滚保护，不作为长期同时维护两套产品的方案。
5. **先新增、后切流、再删除**：合同 MVP 验收前不删除旧表和旧入口。
6. **禁止巨石迁移**：不把原 `AgentProjectServiceImpl` 政名后继续承载全部合同逻辑。
7. **单一写入方**：新表必须明确 Java 或 Python 的主要写入所有权。
8. **所有删除独立提交**：旧 GitHub、项目页面和表结构的删除必须在归档和恢复验证后单独执行。

#### 2.4.10 路由与接口切换

| 旧接口 | 新接口 | 兼容策略 |
|---|---|---|
| `/api/workspace/projects` | `/api/workspace/contracts` | 不复用旧路径；产品模式决定前端调用哪套接口 |
| `/api/workspace/projects/{id}` | `/api/workspace/contracts/{caseId}` | 新建合同聚合响应 |
| `/api/workspace/projects/{id}/sync` | `/api/workspace/contracts/{caseId}/documents` | 从仓库同步改为文件上传和解析 Job |
| `/api/workspace/projects/{id}/runs` | `/api/workspace/contracts/{caseId}/runs` | Java 在内部转换为通用 Subject Run 请求 |
| `/api/workspace/projects/runs/{runId}` | `/api/workspace/contracts/runs/{runId}` | 底层读取相同 Agent Run Store |
| `/api/workspace/projects/runs/{runId}/stream` | `/api/workspace/contracts/runs/{runId}/stream` | 复用 Redis PubSub 和 SSE 转发 |
| `/api/workspace/projects/.../approval` | `/api/workspace/contracts/actions/{actionId}/approval` | 保留审批语义，增加合同资源权限校验 |
| `/api/admin/projects/*` | `/api/admin/contracts/*` | 管理接口独立建设，旧接口最终下线 |

Python 的 `/internal/agent/run` 保持不变，但请求从 `projectId` 升级为：

```json
{
  "requestId": "contract-case-42-review-v3",
  "subjectType": "CONTRACT_CASE",
  "subjectId": 42,
  "taskType": "CONTRACT_REVIEW",
  "goal": "审查当前待签版本",
  "inputs": {"documentVersionId": 108, "ruleSetVersion": "SERVICE_PROCUREMENT_V1"}
}
```

兼容期仍接受旧 `projectId` Payload，但合同代码不得生成旧格式请求。

#### 2.4.11 数据迁移顺序

1. 新增合同领域表，不修改旧项目表。
2. 为 Agent 通用表添加 Subject 字段和索引。
3. 回填旧 Agent 数据的 Subject，运行完整一致性检查。
4. 将 `project_id` 改为可空，开始写入合同 Run。
5. 新增 `agent_subject_memory` 并迁移旧项目记忆。
6. 合同前端切流，持续保留旧产品模式回滚能力。
7. Phase 5 验收后将旧研发数据改为只读归档。
8. Phase 6 稳定后，以独立迁移删除旧领域表和健康专用字段。

任何一步失败都不得通过清空数据库解决；每个迁移必须支持在测试库重复执行并具有验证 SQL。

---

## 3. 目标与非目标

### 3.1 MVP 目标

- 支持企业服务采购合同及附件上传。
- 根据业务信息判断合同类型、生成材料清单并推荐批准模板。
- 基于批准模板填充合同初稿，不允许模型自由创造未批准条款。
- 自动识别合同类型、主体、金额、期限、付款、验收、违约、终止和续签条款。
- 管理企业制度、标准合同和标准条款。
- 每个风险结论同时引用合同条款和企业规则。
- 通过固定规则计算风险分，LLM 只负责抽取、解释和建议。
- 生成缺失材料、协商修改、法务复核等动作提案。
- 在签署前核验签署版本、批准版本、主体和附件是否一致。
- 经人工审批后执行动作并记录结果。
- 从已批准合同中提取履约义务，生成负责人和提醒。
- 展示 Planner、Tool Call、Observation、Reflection、Retry 和 Action Trace。

### 3.2 非目标

- MVP 不支持所有合同类型。
- MVP 不提供电子签章。
- MVP 不直接连接银行执行付款。
- MVP 不自动修改原始合同文件。
- MVP 不根据公开互联网内容直接判定企业内部违规。
- MVP 不做完全自治的法律决策。
- MVP 不立即建设多租户 SaaS，首期按企业内部单租户部署设计。

---

## 4. 用户与权限

| 角色 | 主要职责 | 关键权限 |
|---|---|---|
| 业务发起人 | 发起合同、补充业务背景 | 创建案件、上传材料、查看本人案件 |
| 采购人员 | 管理供应商与商务条款 | 编辑商务信息、处理补充材料任务 |
| 法务审查员 | 审查风险和例外 | 确认风险、修改建议、批准或驳回例外 |
| 财务人员 | 核对付款、发票和税务要求 | 查看及确认财务义务 |
| 合同管理员 | 管理签署、归档、续签和履约 | 登记签署、分配义务、关闭合同 |
| 部门审批人 | 对高风险条款作业务决策 | 批准、驳回、接受风险 |
| 平台管理员 | 管理规则、知识、模型和运行 | 全局配置、审计、失败处理 |

权限原则：案件、文档、条款、Agent 运行、审批和履约动作均需进行资源级权限校验；前端隐藏不等于后端授权。

---

## 5. 领域模型

### 5.1 核心术语

| 术语 | 定义 |
|---|---|
| 合同案件 `Contract Case` | 一次合同送审及其后续履约的业务容器，不等同于某一个文件 |
| 合同文件 `Contract Document` | 合同正文、附件、报价、资质或履约证据的一个版本化文件 |
| 条款 `Contract Clause` | 从合同文件中识别出的可定位文本单元，具有页码、章节和内容范围 |
| 审查规则 `Review Rule` | 企业批准的确定性检查要求，包含适用范围、严重度和评分影响 |
| 审查发现 `Review Finding` | 某条合同内容与审查规则之间的差异、缺失、冲突或待确认事项 |
| 已批准例外 `Approved Exception` | 经授权人员接受的规则偏离，包含理由、补偿措施和失效日期 |
| 履约义务 `Obligation` | 合同签署后需要由一方在条件或截止日期前完成的事项 |
| 履约证据 `Fulfillment Evidence` | 用来证明义务已完成的发票、验收单、邮件、回执或其他材料 |
| Agent 动作 `Agent Action` | Agent 提出的外部副作用，必须经过相应审批才能执行 |

### 5.2 聚合关系

```text
Contract Case
├── Contract Document (1..n, versioned)
│   └── Contract Clause (0..n)
├── Agent Run (0..n)
│   ├── Agent Plan
│   ├── Tool Call / Observation
│   ├── Reflection
│   └── Review Report
├── Review Finding (0..n)
│   └── Approved Exception (0..1)
├── Agent Action (0..n)
└── Obligation (0..n)
    └── Fulfillment Evidence (0..n)
```

### 5.3 状态模型

合同案件状态：

```text
DRAFT
→ MATERIAL_PENDING
→ READY_FOR_REVIEW
→ REVIEWING
→ NEEDS_REVISION / PENDING_APPROVAL
→ APPROVED
→ READY_TO_SIGN
→ SIGNED
→ IN_FULFILLMENT
→ EXPIRED / TERMINATED
```

审查发现状态：

```text
OPEN → REMEDIATED / ACCEPTED_EXCEPTION / DISMISSED
```

履约义务状态：

```text
PLANNED → DUE_SOON → COMPLETED
                   → OVERDUE → ESCALATED → COMPLETED / WAIVED
```

---

## 6. 核心业务流程

### 6.1 合同发起与初稿准备

1. 业务人员填写交易背景、相对方、金额、期限和服务内容。
2. Agent 判断合同类型和适用的企业流程。
3. 检索企业制度，生成必需材料、参与部门和审批角色清单。
4. 推荐有效的企业标准模板及适用附件。
5. 用户选择模板后，系统只在允许的变量和条款选项内生成初稿。
6. 非标准输入或超出模板范围的内容自动标记为待法务确认。

### 6.2 签署前审查

1. 发起人创建合同案件并选择合同类型。
2. 上传合同正文、附件和业务背景材料。
3. 系统完成解析、OCR、版本识别和结构化抽取。
4. Agent Planner 根据合同类型和材料生成审查计划。
5. Agent 调用条款、知识、历史决策和评分工具。
6. Reflection 检查证据覆盖、引用质量和未解决假设。
7. 系统生成审查报告、风险清单和动作提案。
8. 法务确认风险，业务审批人接受或拒绝高风险例外。

### 6.3 协商与版本复核

1. 用户上传对方返回的新版本。
2. 系统识别基线版本和待审版本。
3. Agent 比较条款变化并优先复核受影响规则。
4. 已解决发现自动进入 `REMEDIATED_PENDING_CONFIRMATION`。
5. 新增或扩大风险创建新的审查发现。
6. 法务确认后更新协商状态。

### 6.4 审批与签署就绪核验

1. Agent 根据合同类型、金额、部门和风险计算建议审批路径。
2. 审批人查看一页式合同摘要、未解决风险和已批准例外。
3. 完成审批后，系统记录批准版本哈希。
4. 签署前重新核验待签文件与批准版本是否一致。
5. 检查主体、签署人、日期、附件和未关闭风险。
6. 核验通过后才允许标记为 `READY_TO_SIGN`。

### 6.5 签署与履约

1. 合同管理员登记签署版本和生效日期。
2. Agent 从批准版本提取履约义务。
3. 人工确认责任人、截止日期、提醒时间和所需证据。
4. 系统创建履约任务并按计划提醒。
5. 用户上传履约证据或标记异常。
6. Agent 验证证据是否覆盖义务要求。
7. 逾期或不充分证据触发升级动作。

### 6.6 续签与终止

1. 在通知期限前触发续签评估。
2. 汇总合同履约记录、争议、付款和例外情况。
3. 生成续签、重新谈判或终止建议。
4. 审批后创建续签案件或终止任务。

---

## 7. 知识库与检索设计

### 7.1 知识空间

| 知识空间 | 内容 | 主要用途 |
|---|---|---|
| 企业制度库 | 采购、授权、印章、付款、信息安全制度 | 判断是否符合内部要求 |
| 标准合同库 | 企业合同模板和标准附件 | 比较标准结构与条款 |
| 条款 Playbook | 推荐条款、可接受替代、谈判底线 | 生成修改和协商建议 |
| 法律行业规则库 | 适用法规和行业规范 | 辅助识别外部合规风险 |
| 历史决策库 | 已批准例外、历史谈判结论 | 保持企业决策一致性 |

### 7.2 必须维护的元数据

- `contractType`
- `jurisdiction`
- `businessDepartment`
- `effectiveFrom`
- `effectiveTo`
- `version`
- `mandatory`
- `riskLevel`
- `approvalRole`
- `confidentialityLevel`

无有效期或适用范围的知识不得作为确定性违规依据。

### 7.3 检索流程

```text
合同分类
→ 条款识别
→ 按条款生成检索意图
→ 元数据过滤
→ Elasticsearch 关键词检索
→ Embedding 语义检索
→ 结果融合与重排
→ 返回可定位片段
```

### 7.4 双引用约束

每个确定性审查发现必须具有：

- `contractCitation`：合同文件、版本、页码、章节和命中片段。
- `policyCitation`：企业规则、版本、条款编号和命中片段。

如果只有合同引用，没有规则引用，结果必须标记为 `REQUIRES_HUMAN_JUDGMENT`，不得表述为“违反公司制度”。

如果规则已失效或不适用于该合同类型，检索结果不得进入评分。

---

## 8. Agent Harness 设计

### 8.1 Harness 目标

Harness 必须根据合同内容和证据缺口动态规划，不能使用固定阶段文案伪装 Agent 行为。

外部主接口保持足够小：

```text
runContractTask(caseId, taskType, goal, inputs) → runId
getContractRun(runId) → status + traces + toolCalls + artifact + actions
cancelContractRun(runId)
```

规划、工具选择、检索、重试、反思和重规划均隐藏在 Python Runtime 内部。

### 8.2 任务类型

| Task Type | 目标 | 主要产物 |
|---|---|---|
| `CONTRACT_INTAKE` | 判断合同类型、材料和审批参与方 | Intake Checklist |
| `DRAFT_FROM_TEMPLATE` | 基于批准模板准备受控初稿 | Contract Draft |
| `CONTRACT_REVIEW` | 完成签署前风险审查 | Review Report |
| `APPROVAL_DECISION` | 汇总风险并建议审批路径 | Approval Memo |
| `VERSION_REVIEW` | 比较新旧版本并复核风险 | Version Review Report |
| `SIGNING_READINESS` | 核验待签版本、主体和附件 | Signing Checklist |
| `OBLIGATION_EXTRACTION` | 从批准版本提取义务 | Obligation Plan |
| `FULFILLMENT_CHECK` | 验证履约证据 | Fulfillment Report |
| `RENEWAL_ASSESSMENT` | 评估续签、谈判或终止 | Renewal Memo |
| `RULE_IMPACT_REVIEW` | 企业规则变更后主动扫描受影响合同 | Impact Report |
| `NEGOTIATION_STRATEGY` | 基于历史数据生成协商策略建议 | Strategy Memo |
| `FULFILLMENT_BREACH_ANALYSIS` | 履约异常时自主分析违约条款和应对方案 | Breach Assessment |
| `RULE_EFFECTIVENESS_REVIEW` | 检测低采纳率规则并建议优化 | Rule Health Report |

### 8.3 Planner

Planner 根据任务类型、合同分类、现有材料、知识范围和权限输出：

```json
{
  "goal": "审查服务采购合同并生成履约计划",
  "objectives": [
    "确认合同主体、期限和金额",
    "检查付款与验收条款",
    "检查违约、终止和续签条款",
    "检索适用的企业采购制度",
    "识别签署后履约义务"
  ],
  "requiredEvidence": ["CONTRACT_MAIN", "PRICING_ATTACHMENT"],
  "allowedTools": ["extractContractStructure", "searchPolicyKnowledge"],
  "stopConditions": ["关键条款已覆盖", "高风险结论具有双引用"]
}
```

### 8.4 工具注册表

无外部副作用的读取、检索、计算和候选产物工具可自动执行：

| 工具 | 用途 |
|---|---|
| `getContractCase` | 读取案件基本信息和权限范围 |
| `classifyContractType` | 根据交易事实和材料判断合同类型 |
| `buildMaterialChecklist` | 根据制度生成所需材料和参与部门 |
| `recommendApprovedTemplate` | 检索有效的企业批准模板 |
| `fillApprovedTemplate` | 在模板允许字段内生成合同初稿候选版本 |
| `listContractDocuments` | 列出正文、附件和版本 |
| `readContractClause` | 按页码或章节读取条款 |
| `extractContractStructure` | 抽取主体、金额、日期和章节结构 |
| `searchPolicyKnowledge` | 检索适用企业制度 |
| `findStandardClause` | 检索标准条款和替代方案 |
| `searchHistoricalDecisions` | 检索已确认的历史例外 |
| `compareContractVersions` | 比较两个合同版本 |
| `determineApprovalRoute` | 根据金额、类型和风险计算建议审批路径 |
| `verifySigningPackage` | 核验批准版本、待签版本、主体和附件 |
| `evaluateReviewRules` | 执行确定性规则 |
| `calculateContractRisk` | 计算维度风险和总分 |
| `extractObligations` | 抽取履约义务候选项 |
| `verifyFulfillmentEvidence` | 验证履约证据覆盖情况 |
| `scanAffectedCases` | 按规则变更扫描受影响的合同案件（主动巡检） |
| `searchHistoricalNegotiations` | 检索历史协商数据：初始要价、最终结果、谈判轮次 |
| `analyzeBreachClause` | 分析违约条款：违约金计算、宽限期、免责情形 |
| `searchCommunicationRecords` | 检索与相对方的沟通记录（邮件、对话） |
| `evaluateRuleEffectiveness` | 计算规则的历史采纳率、驳回率和驳回理由分布 |
| `checkCrossDomainConflicts` | 检测多 Reviewer 之间的发现冲突（Synthesizer） |
| `matchClauseToStandard` | 语义匹配对方条款到企业标准条款（非关键词，用向量 + 语义要素） |
| `extractClauseSemantics` | 抽取条款的实质语义要素（责任上限、付款节点、保密范围等 7 种） |
| `generateApprovalSummary` | 按审批角色生成定制化一页式审批摘要（含历史参考数据） |
| `getApprovalContext` | 获取审批链上下文：前序审批人的决策和理由 |

写入工具必须生成待审批动作：

| 工具 | 动作类型 |
|---|---|
| `requestMissingMaterial` | `REQUEST_MATERIAL` |
| `createNegotiationTask` | `CREATE_NEGOTIATION_TASK` |
| `submitLegalReview` | `REQUEST_LEGAL_REVIEW` |
| `draftClauseRevision` | `DRAFT_CLAUSE_REVISION` |
| `registerObligations` | `REGISTER_OBLIGATIONS` |
| `scheduleReminder` | `SCHEDULE_REMINDER` |
| `escalateBreach` | `ESCALATE_OBLIGATION` |

### 8.5 Memory

合同记忆分为：

- 案件事实：主体、金额、版本和当前协商状态。
- 审查记忆：已确认发现、已排除误报和证据缺口。
- 决策记忆：谁在何时接受了什么例外及其理由。
- 履约记忆：义务状态、历史提醒和异常处置。
- 用户偏好：报告格式和默认审批路径。

模型生成的记忆默认 `UNCONFIRMED`；合同事实、例外和履约完成状态必须经人工或系统证据确认。

### 8.6 Reflection 与 Re-plan

Reflection 至少检查：

- 关键章节是否覆盖。
- 高风险发现是否具有双引用。
- 引用规则是否有效且适用。
- 主体、金额、日期是否存在矛盾。
- 确定性评分是否已执行。
- 工具失败是否影响结论。
- 履约义务是否具备责任人、时间或触发条件。

结果不充分时可 Re-plan，但受执行预算约束。预算耗尽后必须输出明确缺口，不得填充不存在的事实。

### 8.7 可观测性

前端运行详情需要展示：

- Planner 目标和动态计划。
- 工具调用原因、输入摘要、耗时和结果摘要。
- 检索命中的知识及引用位置。
- Reflection 的充分性判断和缺口。
- Re-plan 原因。
- 重试、熔断、降级和错误。
- 最终结论如何关联到规则与证据。
- 动作何时生成、由谁审批、执行和验证。

敏感合同正文不得完整写入 Trace；Trace 只保存脱敏摘要和引用标识。

---

## 9. Agent 主动价值与自主行为

> 本章是 ContractOps Agent 区别于"合同管理 SaaS + LLM 辅助审查"的核心差异化设计。
> 一个规则引擎可以逐条检查合同。一个 RAG 系统可以回答条款问题。但只有 Agent 能在无人指令时主动发现风险、在谈判陷入僵局时检索历史策略、在履约异常时自主分析违约条款并生成应对方案。

### 9.1 设计原则

Agent 的主动行为遵循"感知 → 关联 → 分析 → 提案"四步循环，每一步都有可审计的证据链：

1. **感知**：外部事件（规则变更、履约逾期、对方返回新版本）触发 Agent 启动，而非等待用户点击按钮。
2. **关联**：Agent 自主检索相关知识——不只查合同原文，还查历史案件、企业制度、沟通记录、已批准例外。
3. **分析**：Planner 动态生成审查计划，不是固定流程图。两个相同类型的合同可能因缺失材料不同而产生不同的工具调用顺序。
4. **提案**：所有结论以 Action Proposal 形式输出，进入审批闸门，不自动执行。

五种主动行为按实现优先级排列。

### 9.2 跨案件规则变更主动巡检（P0）

**场景**：法务部发布《采购付款管理规范 v3》，预付款上限从 50% 降至 30%。这不是一个需要人工逐份排查的公告——Agent 应该自主响应。

**Agent 行为**：

```text
触发：企业规则库中 rule_set_version 发生变化
  → Agent 自动创建 RULE_IMPACT_REVIEW 任务
  → Planner 检索所有状态为 DRAFT/REVIEWING/PENDING_APPROVAL 的合同案件
  → 对每份合同调用 extractContractStructure → 获取付款条款
  → 调用 evaluateReviewRules → 用新规则重新评分
  → 生成受影响案件清单 + 风险增量
  → 为每份受影响的合同创建审查 Action → 推送到对应法务的消息中心
```

**关键实现要素**：
- 新增 `RuleChangeMonitor` Python cron 任务（复用 F10 主动巡检基础设施）。
- 新增 Task Type：`RULE_IMPACT_REVIEW`。
- 增量复审：只重跑受新规则影响的条款维度，不重跑整份合同的所有审查。
- 消息推送："贵部门 3 份在途合同的付款条款可能与新制度冲突，点击查看。"

**验收**：
- 规则更新后 5 分钟内，所有受影响合同的法务收到通知。
- 同一规则版本不会重复触发同一合同的审查。
- 已签署合同的履约义务不受规则变更影响（法律不溯及既往）。

### 9.3 协商策略建议（P0）

**场景**：对方返回修改版，把违约责任上限从合同金额 100% 压到 30%。传统做法是法务凭经验判断能不能接受。Agent 的价值是用历史数据支撑策略。

**Agent 行为**：

```text
触发：用户上传对方修改版本（VERSION_REVIEW 任务）
  → Agent 调用 compareContractVersions → 识别争议条款
  → 对每个争议条款，调用 searchHistoricalDecisions：
      "过去 2 年内，服务采购合同中类似条款的协商结果是什么？"
  → 检索历史例外记录："我方是否曾经接受过低于 50% 的责任上限？在什么条件下？"
  → LLM 综合以下输入生成策略建议：
      - 我方标准条款文本和谈判底线
      - 历史协商数据：对方初始要价 → 最终接受值
      - 合同类型和金额是否影响历史接受度
      - 是否已有已批准例外可作为先例
  → 输出格式：
      {
        "clause": "违约责任上限",
        "ourBaseline": "合同金额的 100%",
        "counterpartyDemand": "合同金额的 30%",
        "historicalOutcomes": [
          {"case": "2025-Q3-服务采购-某某科技", "finalValue": "50%", "notes": "对方初始要求20%，经三轮协商"}
        ],
        "strategy": "建议第一轮还价 70%，最终底线 50%。50% 在过去 8 个类似案件中为可达成妥协点。",
        "talkingPoints": ["强调我方交付质量记录降低对方风险感知", "可考虑在付款节奏上让步换取责任条款"],
        "precedents": ["case-42-exception", "case-58-exception"]
      }
```

**与普通文档对比的区别**：普通审查工具只能标注"条款 A 从 100% 变成了 30%"。Agent 还能告诉你"30% 是否可接受、历史上怎么谈成的、这次应该报什么价"。

**验收**：
- 每个争议条款至少检索 5 条历史决策记录。
- 策略建议引用具体的历史案件 ID 和协商结果。
- 不能基于不适用于当前合同类型的历史数据生成建议。

### 9.4 履约异常自主分析链（P1）

**场景**：付款义务逾期 3 天。普通系统发一条提醒就结束了。Agent 应该自己去查"逾期会怎样、有没有免责条款、上周是不是通知过对方"。

**Agent 行为**：

```text
触发：履约义务状态变为 OVERDUE
  → Agent 创建 FULFILLMENT_BREACH_ANALYSIS 任务
  → Planner 自主规划分析步骤：
      1. 读合同违约条款："逾期付款的违约金计算方式？宽限期几天？"
      2. 读沟通记录："我方是否在逾期前通知过对方？"
      3. 查不可抗力条款："是否有可引用的免责情形？"
      4. 查历史类似处置："公司过去 5 次逾期付款的处置方式和结果"
  → Agent 输出：
      {
        "breachAssessment": "逾期 3 天。违约金条款：日万分之五，无宽限期。",
        "mitigationOptions": [
          "引用邮件记录证明我方在逾期前 2 天已通知对方支付系统升级",
          "建议立即支付并附道歉函，争取对方放弃违约金",
          "如对方不接受，可参考 2025 年类似案例的协商结果：对方最终放弃 70% 违约金"
        ],
        "recommendedAction": "立即支付 + 引用不可抗力沟通记录争取免责",
        "escalationTrigger": "逾期超过 7 天或对方发送正式违约函 → 升级至法务"
      }
```

**与普通履约提醒的区别**：一个待办管理工具告诉你"逾期了，去处理"。Agent 告诉你"逾期了，根据合同第 8.3 条、上周的邮件记录、以及去年类似情况的处置经验，建议这样做"。

**验收**：
- 逾期触发后 2 分钟内生成分析报告。
- 所有合同引用可定位到具体条款页码。
- 沟通记录引用来自系统内的对话或上传文件。
- 不能基于不存在的免责条款虚构建议。

### 9.5 审查规则持续优化（P1）

**场景**：法务人员连续 10 次驳回"验收标准模糊"这条审查发现，每次标注"该条款是行业通行写法，不构成风险"。系统应该注意到这个模式。

**Agent 行为**：

```text
触发：同一审查规则被驳回次数超过阈值（如近期 80% 的适用案件中被标记为 DISMISSED）
  → Agent 创建 RULE_EFFECTIVENESS_REVIEW 任务
  → 检索该规则在所有案件中的历史表现：创建次数、确认次数、驳回次数、驳回理由
  → 分析驳回理由的共性："多数驳回理由提到'行业标准'或'市场通行'"
  → 输出 Rule Health Report：
      {
        "rule": "验收标准模糊",
        "period": "2026-Q1 to 2026-Q3",
        "totalApplications": 18,
        "confirmed": 3,
        "dismissed": 12,
        "acceptedException": 3,
        "dismissalReasons": ["行业通行写法(8)", "不影响验收实质(3)", "已有SLA补充(1)"],
        "recommendation": "建议将本规则降级为 'LOW' 严重度，或增加'已签署 SLA 的合同可豁免'条件",
        "confidence": "HIGH"
      }
  → 推送至管理员消息中心："3 条审查规则的有效性可能下降，点击查看分析报告"
```

**验收**：
- 规则采纳率计算基于确定性的驳回记录，不用 LLM 估计。
- 规则降级或修改建议进入人工审批，不自动变更。
- 已处置为误报但仍在生效的规则不影响评分。

### 9.6 多 Agent 拆分审理（P2）

**场景**：一份服务采购合同，付款条款、IP 条款、违约条款之间无依赖关系。单线程审查耗时 = sum(三个领域)，多 Agent 并发 = max(三个领域)。

**Agent 行为**：

```text
触发：CONTRACT_REVIEW 任务
  → Coordinator Agent 分析条款结构 → 生成审查子任务：
      ├── Payment Reviewer Agent：付款条款、发票、验收
      ├── IP Reviewer Agent：知识产权、保密、数据
      └── Liability Reviewer Agent：违约责任、终止、赔偿
  → 三个 Reviewer 并行调用 extractContractStructure + searchPolicyKnowledge + evaluateReviewRules
  → 并发执行（复用现有 asyncio.gather() 基础设施，F5 已实现）
  → Synthesizer Agent 收集三个 Reviewer 的发现：
      - 去重
      - 检测冲突："Payment Reviewer 通过，但 Liability Reviewer 发现同一付款条件存在风险"
      - 合并评分
  → 输出统一的审查报告
```

**与单线程的区别**：一份 50 页合同审查从 ~5 分钟缩短到 ~2 分钟。更关键的是，Synthesizer 的冲突检测能发现跨领域的问题——这种问题是顺序审查很难注意到的。

**验收**：
- 3 个 Reviewer 并发执行，总耗时 ≤ max(单个) + 合成开销。
- Synthesizer 至少检测到 1 个跨领域冲突（在存在冲突的测试合同上）。
- 单个 Reviewer 失败不影响其他 Reviewer 的输出。
- 合并报告标记哪些发现来自哪个 Reviewer。

### 9.7 智能审批路由（P1）

**痛点**：审批人不缺流程——企业内部审批链通常是固定的。真正的问题是：审批人面对一份 50 页合同 + 8 页审查报告，不知道该看哪里、不知道前面的人批了什么、不知道这个风险是不是已经被讨论过了。

**Agent 行为**：

```text
触发：合同进入 PENDING_APPROVAL 状态
  → Agent 创建 APPROVAL_DECISION 任务
  → Planner 自主规划审批摘要生成步骤：
      1. 调用 getContractCase → 获取案件基本信息和当前状态
      2. 调用 evaluateReviewRules → 获取当前规则评分结果
      3. 调用 searchHistoricalDecisions → 检索历史上类似风险的处置结果
      4. 调用 determineApprovalRoute → 确认审批路径和各节点负责人
  → Agent 为每个审批角色生成定制化的一页式审批摘要：

  给法务审查员的摘要：
  {
    "caseKey": "SRV-2026-0042",
    "contractType": "企业服务采购",
    "parties": "我方 vs 某某科技",
    "totalAmount": "120万元 / 2年",
    
    "mustReview": [
      {
        "finding": "违约责任上限从合同金额100%压至30%",
        "severity": "HIGH",
        "contractCitation": {"page": 8, "clause": "8.3", "text": "..."},
        "policyCitation": {"rule": "采购-违约-001", "version": "v2", "text": "..."},
        "negotiationHistory": "对方初始要求20%，我方在首轮协商中谈到30%。历史数据：类似合同最终接受范围 50%-100%",
        "decisionRequired": "是否接受30%？如果接受，建议作为已批准例外记录，有效期至合同终止"
      },
      {
        "finding": "自动续签通知期仅15天，低于公司制度要求的30天",
        "severity": "MEDIUM",
        "decisionRequired": "是否接受缩短通知期？历史上3次类似情况均被拒绝"
      }
    ],
    
    "resolvedItems": [
      {"finding": "验收标准缺失", "resolution": "已补充《服务水平协议》作为附件，标准已明确", "status": "RESOLVED"}
    ],
    
    "approverContext": {
      "role": "法务审查员",
      "decisionScope": "条款风险、合规性、例外接受",
      "previousApproverDecisions": [],  // 上一级尚未审批
      "escalationPath": "如拒绝，案件返回业务发起人补充材料"
    },
    
    "historicalReference": {
      "similarCases": 4,
      "similarApprovalOutcomes": "3个接受了50%以上的责任上限，1个接受了30%但对方在付款方式上做了重大让步"
    }
  }
```

**关键设计原则**：

1. **角色定制**：审批摘要根据审批人的角色自动裁剪。财务审批人看到付款条款、预算匹配和发票要求；法务看到风险发现和法规引用；部门负责人看到商务条款和交付承诺。
2. **上下文感知**：审批摘要包含前面所有审批节点的决策历史——第二个审批人能看到第一个人批了什么、为什么批。
3. **历史参考**：每个待决策项附带历史上类似决策的统计："过去 10 次类似决策中，7 次接受、2 次拒绝、1 次修改后接受"。
4. **一页原则**：摘要长度不超过审批人在 3 分钟内能完成的阅读量。详细审查报告始终可展开。

**与普通审批流的区别**：

| 普通审批流 | Agent 智能审批 |
|-----------|-------------|
| "去找张总审批" | "张总，这份合同你只需要关注 1 个问题，决策依据在此" |
| 审批人翻 50 页 | 一页摘要 + 可展开详情 |
| 不知道前面的人批了什么 | 审批链上下文完整可见 |
| 不知道风险严重不严重 | 每个发现附带历史同类决策数据 |

**验收**：
- 不同审批角色（法务/财务/业务负责人）看到不同侧重点的摘要。
- 每个 MUST_REVIEW 项附带 ≥ 3 条历史参考数据。
- 已解决项（RESOLVED）不出现在审批人的决策清单中（除非该审批人主动展开）。
- 审批摘要生成时间不超过完整审查报告的 20%。

### 9.8 条款语义匹配（P0）

**痛点**：对方不会按你的模板发合同。当前 PRD 的"逐条对比"能发现第 7.3 条和第 8.2 条被改了，但无法回答最关键的问题：**"这个改动到底重不重要？"**

条款语义匹配解决的是合同审查中最耗时的环节——不是"发现差异"，而是"判断差异的实质影响"。

**Agent 行为**：

```text
触发：CONTRACT_REVIEW 或 VERSION_REVIEW 任务
  → Agent 调用 extractContractStructure → 获取对方合同的所有条款
  → 对每个条款，调用 matchClauseToStandard：
      1. 用 LLM 提取条款的"实质语义要素"：
         违约责任条款 → {责任上限比例, 是否包含间接损失, 是否包含第三方索赔, 赔偿触发条件}
         付款条款     → {付款方式, 付款节点, 发票要求, 逾期违约金比例, 预付款比例}
         保密条款     → {保密范围, 保密期限, 违约责任, 接收方义务, 除外情形}
      2. 在企业标准条款库中搜索同类型条款
      3. 语义向量相似度匹配（不是关键词匹配——"赔偿上限为合同金额"和"责任不超过总价"语义相同但关键词不同）
      4. 输出匹配结果：
      
  {
    "clause": "对方第 8.3 条（违约责任）",
    "matchedStandardClause": "SRV-STD-LIABILITY-001（服务采购标准违约责任）",
    "semanticSimilarity": 0.94,
    "extractedElements": {
      "liabilityCap": {"value": "合同金额的 100%", "matchesStandard": true},
      "indirectDamages": {"value": "包含", "matchesStandard": false, "standardValue": "排除间接损失"},
      "thirdPartyClaims": {"value": "未提及", "matchesStandard": false, "standardValue": "明确包含第三方索赔"},
      "curePeriod": {"value": "30天", "matchesStandard": true}
    },
    "verdict": "PARTIAL_MATCH",
    "mustNegotiate": ["indirectDamages", "thirdPartyClaims"],
    "negotiationPriority": ["indirectDamages": "HIGH", "thirdPartyClaims": "MEDIUM"],
    "riskIfAccepted": "对方条款包含间接损失赔偿，可能增加敞口。如果不修改，建议购买保险覆盖。"
  }
```

**条款语义要素提取（MVP 首批支持的条款类型）**：

| 条款类型 | 语义要素 |
|---------|---------|
| 违约责任 | 责任上限、间接损失、第三方索赔、赔偿触发条件、宽限期 |
| 付款条款 | 付款方式、付款节点、发票要求、逾期违约金、预付款比例、币种 |
| 保密条款 | 保密范围、保密期限、接收方义务、除外情形、违约责任 |
| 验收条款 | 验收标准、验收方式、验收期限、拒收权利、返工义务 |
| 终止条款 | 终止触发条件、通知期限、终止后义务、退款条款 |
| 知识产权 | 所有权归属、许可范围、背景知识产权、改进归属、侵权赔偿 |
| 数据保护 | 数据类型、处理目的、存储位置、跨境传输、删除义务、安全措施 |

**与"逐条文档对比"的区别**：

| 文档对比工具 | Agent 语义匹配 |
|------------|------------|
| "第 7.3 条从 A 变成了 B" | "第 7.3 条虽然措辞不同，但实质内容和标准条款一致，不需要协商" |
| "发现 12 处差异" | "12 处差异中，3 处是措辞变化（实质一致），2 处是轻微偏离（可接受），1 处是实质性冲突（必须协商）" |
| 逐条标注 | 按协商优先级排序——先处理必须争的 |

**实现基础设施**：

- `contract_clause` 表增加 `semantic_elements` JSON 列，存储条款的实质语义要素（LLM 抽取 + 人工确认）。
- `contract_standard_clause` 表增加 `semantic_elements` JSON 列，作为匹配基准。
- 语义匹配使用向量相似度（复用 ES kNN + 现有 Embedding 基础设施），不是关键词匹配。
- 语义要素的抽取和确认是**一次性的**——同一标准条款只需确认一次，后续自动复用。

**验收**：
- 首批 7 种条款类型的语义要素抽取准确率 ≥ 0.90。
- 条款匹配不依赖措辞相似度——"赔偿上限为合同金额"和"责任不超过总价"能正确匹配（相似度 ≥ 0.85）。
- 错误匹配（实质不同但短文本相似度高导致误匹配）能通过语义要素对比检测并降级为"不确定"。
- 新标准条款首次入库后自动生成语义要素候选版本，人工确认后才生效。

### 9.9 边界与安全

Agent 的自主行为必须受到以下约束：

1. **读取优先于写入**：所有主动行为的前三个阶段（感知、关联、分析）只执行读取操作。写入（创建 Action、发送通知）必须在最后一步且进入审批。
2. **预算上限**：主动巡检每次最多处理 20 个案件，超出分批执行。
3. **不溯及既往**：规则变更不触发已签署合同的重新审查（除非规则明确要求）。
4. **幂等保护**：同一事件（如规则 v3 发布）不会在同一合同上触发重复审查。
5. **人工确认的不可替代性**：策略建议、规则修改建议、异常应对方案均为提案，必须经人工确认后才执行。
6. **语义要素需人工确认**：条款语义要素的 LLM 抽取结果首次入库时标记为 `UNCONFIRMED`，经法务确认后才用于评分和匹配。
7. **审批摘要不得隐藏信息**：智能审批摘要必须保留展开到完整审查报告的能力，不得通过摘要形式让审批人在不知情的情况下做决策。

---

## 10. 确定性风险评分

### 10.1 评分原则

- LLM 不直接输出最终总分。
- 评分输入只能来自结构化规则结果和证据状态。
- 同一合同版本、规则版本和证据快照必须得到相同分数。
- 每份报告保存 `scoringVersion`、`ruleSetVersion`、`evidenceHash` 和 `llmModel`。

### 10.2 MVP 维度

| 维度 | 权重 | 示例信号 |
|---|---:|---|
| 主体与授权 | 15% | 主体完整、签署权限、证照有效期 |
| 商务与付款 | 20% | 金额、付款节点、发票、验收前置条件 |
| 责任与违约 | 25% | 责任上限、违约责任、终止权、赔偿范围 |
| 合规与保密 | 20% | 保密、数据、分包、知识产权 |
| 履约可执行性 | 20% | 交付标准、验收方式、通知期限、续签机制 |

风险状态：

- `LOW`：80-100
- `MEDIUM`：60-79
- `HIGH`：0-59 或存在一票否决规则

一票否决规则优先于总分，例如主体无效、超越授权、关键附件缺失或存在企业明确禁止条款。

---

## 11. 功能需求

### 11.1 前台合同工作区

#### 合同组合页

- 合同总数、待审、待审批、履约中、即将到期和逾期数量。
- 风险分布和近期开闭环趋势。
- 按合同类型、部门、负责人、相对方和状态筛选。
- 快速创建合同案件。

#### 首页一级任务

- `发起新合同`：进入业务信息采集、材料清单和模板推荐。
- `审查待签合同`：查看待解析、待审查和待复核案件。
- `处理待办与审批`：集中处理材料、协商、法务和风险例外任务。
- `查看履约和到期事项`：进入义务日历、逾期事项和续签预警。

#### 合同案件页

建议使用以下标签页：

1. `概览`：案件状态、关键字段、最新风险和下一动作。
2. `发起与材料`：业务信息、材料清单、模板和参与部门。
3. `文件与版本`：正文、附件、解析状态和版本关系。
4. `审查发现`：按严重度、规则、章节和状态筛选。
5. `审批与协商`：动作提案、例外审批和版本反馈。
6. `履约义务`：责任人、截止日期、状态和证据。
7. `Agent 运行`：计划、工具、反思、错误和报告。
8. `合同对话`：仅围绕当前案件、知识和历史决策问答。

#### 文档审查视图

- 左侧合同页或条款目录。
- 中间原文及高亮。
- 右侧风险、企业规则、标准条款和建议。
- 点击引用可定位到合同页码和规则原文。
- 支持确认、驳回误报、接受例外和创建协商任务。

### 10.2 管理端

- 合同类型管理。
- 审查规则集、版本和生效时间管理。
- 标准条款和替代条款管理。
- 知识文档上传、解析、元数据和适用范围管理。
- Agent Prompt 版本和效果管理。
- Run、Trace、Tool Call、失败和 PEL 积压管理。
- 报告、动作、审批和执行审计。
- 模型、Embedding、OCR 和外部连接状态。
- 数据保留、脱敏和导出策略。

### 10.3 消息中心

消息类型至少包括：

- 文档解析完成或失败。
- Agent 审查完成或失败。
- 材料缺失。
- 待本人审批。
- 审批通过或驳回。
- 履约义务即将到期。
- 履约义务逾期。
- 合同即将续签或终止。
- 外部模型、OCR、ES、Redis 不可用。

---

## 12. 数据模型与存储

### 11.1 新增业务表

| 表 | 用途 |
|---|---|
| `contract_case` | 合同案件主表 |
| `contract_party` | 合同主体及角色 |
| `contract_document` | 文件、附件、版本和解析状态 |
| `contract_clause` | 条款结构和原文定位 |
| `contract_case_kb_document` | 案件与知识文档绑定 |
| `contract_review_rule` | 确定性审查规则 |
| `contract_rule_set` | 规则集和版本 |
| `contract_review_finding` | 审查发现及双引用 |
| `contract_exception` | 已批准例外及失效时间 |
| `contract_obligation` | 履约义务 |
| `contract_fulfillment_evidence` | 履约证据 |
| `contract_reminder` | 提醒计划和发送状态 |
| `contract_version_diff` | 版本变化摘要和受影响条款 |

### 11.2 通用 Agent 表改造

当前 `agent_run`、`agent_report`、`agent_action` 被 `project_id` 强绑定。采用兼容迁移：

1. 增加 `subject_type` 和 `subject_id`。
2. 旧数据回填为 `subject_type='PROJECT'`、`subject_id=project_id`。
3. 合同数据使用 `subject_type='CONTRACT_CASE'`、`subject_id=contract_case.id`。
4. 过渡期保留 `project_id`，改为可空。
5. 所有新查询必须通过 Subject 关联，不允许同时依赖两套字段。
6. 原研发项目功能下线并完成数据归档后，再删除 `project_id`。

`agent_project_memory` 改造为通用 `agent_subject_memory`，或新增同结构表后迁移。不得继续增加更多以领域命名的重复 Memory 表。

### 11.3 数据所有权

- Java 拥有用户、权限、合同案件 CRUD、审批和外部动作状态。
- Python 拥有 Agent Run、Trace、Tool Call、Prompt、解析结果和 Agent 产物写入。
- 知识文档元数据由 Java 管理，解析、分块和索引状态由 Python 更新。
- 每张共享表只指定一个主要写入方，另一方默认只读，避免双写竞争。

### 11.4 存储分工

- MySQL：案件、结构化条款、规则、发现、义务、审批和审计。
- Elasticsearch：合同和知识分块、关键词与语义检索。
- 文件存储：合同原文件、附件和履约证据。
- Redis：Agent 队列、进度 PubSub、缓存和短期去重。

---

## 13. 系统架构

```text
用户端 / 管理端
       ↓
Java Thin Proxy
  ├── 鉴权与资源权限
  ├── 合同案件 CRUD
  ├── 审批与动作执行
  ├── 文件元数据与消息
  └── SSE 转发
       ↓ Redis Stream / Internal HTTP fallback
Python Agent Runtime
  ├── Contract Parser
  ├── Policy Knowledge Retriever
  ├── Contract Tool Registry
  ├── Planner / Runner / Reflection
  ├── Deterministic Risk Engine
  ├── Report / Finding / Obligation Persistence
  └── Recovery / Retry / Circuit Breaker
       ↓
MySQL + Elasticsearch + File Storage + LLM / Embedding / OCR
```

关键模块应保持深模块设计：调用方只需要传入案件、任务和目标，不需要知道文档切分、查询扩展、规则执行和 Reflection 的内部顺序。

---

## 14. 内部接口草案

### 13.1 Java Workspace 接口

| Method | Path | 用途 |
|---|---|---|
| `GET` | `/api/workspace/contracts` | 合同组合与筛选 |
| `POST` | `/api/workspace/contracts` | 创建合同案件 |
| `GET` | `/api/workspace/contracts/{caseId}` | 案件详情 |
| `POST` | `/api/workspace/contracts/{caseId}/documents` | 上传合同或附件 |
| `POST` | `/api/workspace/contracts/{caseId}/drafts` | 从批准模板生成初稿候选版本 |
| `POST` | `/api/workspace/contracts/{caseId}/runs` | 启动 Agent 任务 |
| `GET` | `/api/workspace/contracts/runs/{runId}` | 运行详情 |
| `GET` | `/api/workspace/contracts/runs/{runId}/stream` | SSE 进度 |
| `POST` | `/api/workspace/contracts/runs/{runId}/cancel` | 取消运行 |
| `POST` | `/api/workspace/contracts/findings/{findingId}/decision` | 确认、驳回或例外 |
| `POST` | `/api/workspace/contracts/actions/{actionId}/approval` | 动作审批 |
| `POST` | `/api/workspace/contracts/{caseId}/signing-check` | 启动签署就绪核验 |
| `POST` | `/api/workspace/contracts/obligations/{id}/evidence` | 上传履约证据 |

### 13.2 Python Internal 接口

| Method | Path | 用途 |
|---|---|---|
| `POST` | `/internal/contract/documents/{id}/parse` | 解析合同文件 |
| `POST` | `/internal/agent/run` | HTTP fallback 启动任务 |
| `GET` | `/internal/agent/run/{runId}` | 返回运行与产物 |
| `POST` | `/internal/agent/run/{runId}/cancel` | 取消任务 |
| `POST` | `/internal/contract/obligations/{id}/verify` | 验证履约证据 |

内部接口使用服务令牌，并验证 `subject_type`、`subject_id` 与当前 Run 一致。

---

## 15. 分阶段实施路线

每个阶段必须独立可演示、可测试、可回滚。不得在前一阶段验收失败时继续叠加后续业务。

### Phase 0：转向基线与旧功能冻结

**建议周期**：3-5 天  
**目标**：建立可回滚基线，停止继续扩展研发项目业务。

任务：

- 冻结当前研发项目功能，仅修复阻断缺陷。
- 保存现有数据库结构和测试数据备份。
- 在 `system_config` 建立 `PRODUCT_MODE=contract` 动态配置。
- 记录现有 Java、Python、前台、管理端能力清单。
- 按本 PRD 2.4 节建立逐文件迁移看板，标记保留、改造、新建和删除。
- 建立首批 20-30 份脱敏合同测试集。
- 确定首期企业服务采购合同规则清单。

验收：

- 当前系统构建和关键 E2E 测试通过。
- 可以通过配置回到旧产品模式。
- 测试集、字段标注和规则样例完成评审。
- 新旧模块对应关系、数据所有权和删除条件通过评审。

### Phase 1：合同案件底座与产品换壳

**建议周期**：1 周  
**目标**：用户可以创建和管理合同案件。

任务：

- 新增 `contract_case`、`contract_party`、`contract_document`。
- 将 Agent 表增加 Subject 关联并完成旧数据回填。
- 新建合同组合页和合同案件工作台骨架。
- 实现合同发起表单、合同类型候选和材料清单占位流程。
- 新建管理端合同类型、案件和文件管理入口。
- 将聊天框改为选择合同案件，不再选择研发项目。
- 消息中心支持合同文件和案件事件。

验收：

- 创建合同案件、填写双方和业务背景。
- 首页出现“发起、审查、审批、履约”四个真实入口。
- 上传合同及附件并看到处理状态。
- 权限不足的用户无法读取其他案件。
- 旧项目数据未被删除，配置切换可恢复旧页面。

### Phase 2：合同解析与结构化

**建议周期**：1-2 周  
**目标**：合同从文件转为可定位、可检索、可比较的结构化数据。

任务：

- 复用 PDF、Word、OCR 解析链路。
- 识别页码、章节、条款编号和附件关系。
- 抽取主体、金额、币种、期限、生效、付款、验收、违约、终止和续签字段。
- 建立合同版本关系和内容哈希。
- 将条款写入 MySQL，将分块写入 Elasticsearch。
- 前端实现文档目录、原文和字段确认界面。

验收：

- 支持 PDF、DOCX 和扫描 PDF。
- 测试集关键字段抽取 F1 不低于 0.90。
- 95% 以上条款引用可以定位到正确页码或章节。
- 重复上传同一文件不会产生重复版本。
- 抽取失败时保留原文件并明确显示失败原因。

### Phase 3：企业规则知识库与确定性检查

**建议周期**：1-2 周  
**目标**：系统可以基于企业知识判断合同，而不是使用通用模型常识。

任务：

- 新增合同知识空间和元数据字段。
- 建立企业标准模板库、模板变量定义和允许替代条款。
- 新增规则集、规则版本和适用范围管理。
- 首期配置 15-20 条服务采购合同规则。
- 实现元数据过滤、关键词与向量混合检索。
- 实现双引用数据结构。
- 实现确定性风险评分引擎。
- 管理端支持启用、停用和发布规则版本。
- 支持根据合同类型推荐有效模板，并在允许变量范围内生成初稿候选版本。
- **新增标准条款语义要素库**：为 7 种核心条款类型定义语义要素模板，LLM 抽取 + 人工确认后入库。标准条款的语义要素作为条款匹配基准。

验收：

- 每条规则可追踪到版本和生效日期。
- 同一快照和规则版本重复评分完全一致。
- 没有规则引用时不会输出确定性违规结论。
- 前端可以从发现跳转到合同原文和企业规则原文。
- 模板生成不能引入未批准条款；非标准输入必须进入法务确认。

### Phase 4：合同 Agent Harness + 主动巡检

**建议周期**：2-3 周  
**目标**：实现动态规划 + 工具调用 + 反思的合同审查 Agent，同时上线规则变更主动巡检。

任务：

- 新增合同 Planner Prompt 和结构化 Plan Schema。
- 将工具注册表替换为合同读取、检索、规则和比较工具。
- 接入合同类型判断、材料清单、模板推荐、审批路径和签署核验工具。
- 支持同组读取与检索工具并发（复用 F5 并发基础设施）。
- 实现 Reflection、Re-plan 和停止条件。
- 将合同记忆接入当前 Memory 机制。
- **新增 `RuleChangeMonitor` Python cron 任务**：规则库版本变化 → 自动创建 `RULE_IMPACT_REVIEW` → 批量扫描在途合同。
- **接入消息中心推送**：规则变更影响通知、审查完成通知。
- 前端展示计划、工具原因、观察、反思和降级。

验收：

- 不同材料组合产生不同计划。
- Planner 只能选择允许的合同工具。
- 缺失关键附件时 Agent 提出补充材料，不生成虚假结论。
- 高风险结论双引用覆盖率达到 100%。
- **规则更新后 5 分钟内受影响合同的法务收到通知。**
- 取消、超时、重试、幂等和恢复测试通过。

### Phase 5：审查报告、协商策略与审批闭环

**建议周期**：2 周  
**目标**：完成从风险发现到人工决策和整改复核的 MVP 闭环，上线协商策略 Agent。

任务：

- 实现结构化合同审查报告。
- 实现发现确认、误报驳回和例外接受。
- 实现补材料、协商修改和法务复核动作。
- **新增 `NEGOTIATION_STRATEGY` 任务**：上传对方修改版本 → Agent 识别争议条款 → 检索历史协商数据 → 生成策略建议（底线、还价建议、话术要点、历史先例）。
- **引入条款语义匹配**（9.8）：审查时自动调用 `matchClauseToStandard` → 区分"措辞变化（实质一致）"、"轻微偏离（可接受）"、"实质性冲突（必须协商）" → 按协商优先级排序审查发现。
- **实现智能审批路由**（9.7）：`generateApprovalSummary` → 按审批角色生成定制化一页式摘要，附历史参考数据和审批链上下文。
- 审批后异步执行动作并记录结果。
- 支持上传修改版本后复核原发现。
- 保存批准版本哈希并实现签署就绪核验。
- 实现动作验证状态。

验收：

- 报告展示风险、引用、规则、评分和建议。
- **每个争议条款的策略建议引用 ≥ 3 条历史决策记录。**
- 高风险例外必须由授权角色审批。
- 新版本复核标记已解决、新增和未变化风险。
- 待签版本与批准版本不一致时阻止进入 `READY_TO_SIGN`。

**到此完成第一版可用 MVP。**

### Phase 6：履约闭环 + 异常自主分析

**建议周期**：2 周  
**目标**：履约义务管理 + 逾期时的 Agent 自主分析链（查合同条款→查沟通记录→查历史先例→生成方案）。

任务：

- 从批准版本提取履约义务候选项。
- 人工确认责任人、日期、条件和证据要求。
- 建立提醒调度和消息通知。
- 上传履约证据并由 Agent 验证。
- **新增 `FULFILLMENT_BREACH_ANALYSIS` 任务**：义务逾期 → Agent 自主拉取违约条款、免责情形、沟通记录、历史类似处置 → 生成应对方案。
- 实现逾期、证据不足和违约升级动作。
- 提供义务日历和负责人视图。
- **新增 `RULE_EFFECTIVENESS_REVIEW`**：定期扫描低采纳率规则，向管理员推送优化建议。

验收：

- 逾期后 2 分钟内生成自主分析报告。
- 分析报告包含合同条款引用 + 沟通记录引用 + 历史先例引用（三引用）。
- 无明确日期的条件型义务不会被伪造日期。
- 规则采纳率低于阈值时管理员收到优化建议。

### Phase 7：版本、续签与合同组合管理

**建议周期**：2 周  
**目标**：支持合同持续协商和管理层组合视图。

任务：

- 完善合同版本可视化比较。
- 实现规则影响范围增量复核。
- 实现续签、终止和重新谈判评估。
- 建立组织级风险、到期、义务和例外总览。
- 识别跨合同共同风险和异常条款模式。
- 支持按部门、相对方和合同类型统计。

验收：

- 新版本只重跑受影响条款和必要规则。
- 续签评估引用履约记录和历史例外。
- 组合总览数据可追溯到具体合同和发现。
- 管理指标不依赖 LLM 临时生成。

### Phase 8：企业安全、评测与上线准备

**建议周期**：1-2 周  
**目标**：达到企业内部试点要求。

任务：

- 合同文件访问控制和下载审计。
- Trace、日志和模型请求脱敏。
- 文件加密、保留期限和删除策略。
- 外部模型数据发送范围配置。
- 建立合同抽取、检索、规则和报告评测集。
- 建立 Prompt 版本效果看板。
- 压测并验证 Redis PEL、MySQL 连接池和恢复流程。
- 完成备份、恢复和故障演练。

验收：

- 未授权访问测试全部失败并有审计记录。
- 日志和 Trace 不出现完整合同正文或敏感身份信息。
- Gold Set 高风险召回率不低于 0.90。
- 引用准确率不低于 0.95。
- 无证据结论率低于 2%。
- Agent Run 成功率高于 99%，失败可恢复或明确终态。

---

## 16. 阶段依赖与发布节点

```text
Phase 0 基线
   ↓
Phase 1 合同案件
   ↓
Phase 2 文档结构化
   ↓
Phase 3 规则与知识
   ↓
Phase 4 Agent Harness
   ↓
Phase 5 审查审批 MVP
   ↓
Phase 6 履约闭环
   ↓
Phase 7 组合管理
   ↓
Phase 8 企业试点
```

发布节点：

- **Milestone A**：Phase 2 完成，可作为合同结构化工具演示。
- **Milestone B**：Phase 5 完成，形成签署前审查 MVP。
- **Milestone C**：Phase 6 完成，形成合同审查与履约闭环。
- **Milestone D**：Phase 8 完成，进入企业内部试点。

---

## 17. 测试策略

### 16.1 确定性测试

- 字段和条款抽取样例测试。
- 规则引擎逐规则测试。
- 评分快照测试。
- 相同证据哈希重复运行一致性测试。
- 状态机和权限测试。
- 动作审批和幂等测试。

### 16.2 Agent 评测

- Planner 是否覆盖必需目标。
- 工具选择是否正确。
- 检索是否命中适用规则。
- Reflection 是否识别证据缺口。
- 是否存在无引用或引用错误结论。
- 风险标题允许语义差异，规则编号、严重度和引用必须精确一致。

### 16.3 E2E 场景

至少覆盖：

1. 材料齐全、低风险合同。
2. 缺少报价附件。
3. 扫描版合同 OCR。
4. 条款与标准模板冲突。
5. 企业规则已过期。
6. 高风险例外审批。
7. 新版本解决部分风险。
8. 履约义务即将到期。
9. 履约证据不充分。
10. LLM、ES、Redis 或 OCR 暂时不可用。

---

## 18. 成功指标

### 17.1 产品指标

| 指标 | 试点目标 |
|---|---:|
| 合同首次审查平均耗时 | 降低 50% |
| 高风险发现人工采纳率 | > 70% |
| 风险双引用覆盖率 | 100% |
| 待办动作闭环率 | > 80% |
| 到期义务漏提醒率 | < 1% |
| 用户每周回访率 | > 40% |

### 17.2 技术指标

| 指标 | 目标 |
|---|---:|
| Agent Run 成功率 | > 99% |
| 引用准确率 | > 95% |
| 高风险召回率 | > 90% |
| 无证据结论率 | < 2% |
| 重复请求双写率 | 0 |
| 取消生效时间 | < 5s |

---

## 19. 风险与缓解

| 风险 | 影响 | 缓解方案 |
|---|---|---|
| 法律结论错误 | 高 | 辅助审查定位；双引用；高风险人工确认 |
| 合同数据泄露 | 高 | 资源权限、脱敏、加密、审计、模型发送控制 |
| OCR 或条款切分错误 | 高 | 原文定位、置信度、人工确认、失败不评分 |
| 企业规则过期 | 高 | 生效/失效日期、版本发布、禁止失效规则参与评分 |
| LLM 输出不稳定 | 中 | 结构化输出、确定性规则、Prompt 版本和 Gold Set |
| 一次支持过多合同类型 | 高 | MVP 仅服务采购合同，规则集按类型逐步扩展 |
| 大爆炸式重写失败 | 高 | 产品模式开关、兼容 Subject 字段、阶段验收后再删除旧模块 |
| 履约提醒不可靠 | 高 | 幂等调度、发送记录、失败重试和逾期扫描 |

---

## 20. 旧功能下线策略

1. Phase 0-4 保留旧研发项目代码，但默认进入合同产品模式。
2. Phase 5 MVP 验收前不删除 `agent_project` 和 GitHub 同步模块。
3. Phase 5 通过后导出旧项目、Run、报告和动作数据归档。
4. Phase 6 稳定后移除前后台研发项目入口和 GitHub 专用工具。
5. 通用 Agent Runtime、知识库、可观测性和消息中心继续保留。
6. 数据库删除旧表必须作为独立迁移，并在备份恢复演练后执行。

---

## 21. MVP 演示脚本

### 第一幕：签署前审查（被动响应 + 语义匹配）

1. 业务人员输入”采购一年期办公服务、预算30万元”等交易信息。
2. Agent 判断合同类型，生成材料清单、参与部门和审批建议。
3. 用户上传**对方用自己的模板写的合同正文**（不是我们的模板）。
4. 系统完成解析并展示主体、金额、期限和条款目录。
5. 用户点击”开始合同审查”。
6. 前端实时展示 Planner、知识检索、规则检查和 Reflection。
7. **Agent 语义匹配**（9.8）：对方第 7.3 条违约责任条款——虽然措辞和我们的标准条款完全不同，但 Agent 识别实质语义一致（”责任上限 = 合同金额 100%”），标注为”措辞变化，无需协商”。
8. **Agent 语义匹配**：对方第 8.2 条——Agent 检测到”间接损失赔偿”未排除（与我方标准条款实质性冲突），标注为”必须协商，优先级 HIGH”。
9. **Agent 规则检查**：付款条件偏离公司制度 v2、自动续签通知期短于制度要求的 30 天。
10. 审查发现按协商优先级排序，不是按条款顺序。法务先看到 2 个必须争的，再看到 1 个可接受的。
11. 用户点击每个风险，跳转到双引用——合同原文页 vs 我方标准条款 + 企业制度条文。

### 第二幕：协商策略（Agent 主动价值）

10. 用户上传对方返回的修改版本。
11. Agent 调用 `compareContractVersions` 识别所有变更。
12. **Agent 不只是标红差异**。对每一条争议条款，Agent 调用 `searchHistoricalNegotiations` 检索过去 2 年内类似条款的协商结果。
13. Agent 生成策略建议：初始要价 vs 历史妥协点 vs 建议还价策略。
14. 法务在策略面板上看到”50% 是过去 8 个案件中的可达成妥协点，建议第一轮还价 70%”，每条建议可追溯到具体的历史案件 ID。
15. 法务批准协商方案，系统创建协商任务。

### 第三幕：智能审批（一页式摘要 + 上下文感知）

17. 法务确认所有审查发现后，合同进入审批流程。
18. **Agent 不把 50 页合同 + 10 页审查报告堆给审批人。**
19. 财务审批人打开审批页面，看到**定制化摘要**："您需要关注 1 个问题——付款条款中的预付款比例为 50%，超出公司财务制度上限 30%。历史 4 次类似决策中，3 次要求降低预付款，1 次接受了 50% 但对方提供了银行保函。"
20. 法务审批人的摘要侧重风险发现和法规引用；财务审批人的摘要侧重付款条款和预算匹配；业务负责人的摘要侧重交付承诺和商务条款。
21. 第二个审批人（财务总监）能看到第一个审批人（财务经理）的决策："财务经理已批准，附加条件：要求对方提供银行保函。"
22. 审批人点击任一待决策项，可展开完整审查报告和合同原文定位。不需要的已解决项默认折叠。
23. 审批通过后，系统记录完整的审批链：谁、何时、基于什么信息、做出了什么决策。

### 第四幕：主动巡检（Agent 无人指令下的自主行为）

16. 管理员在后台发布《采购付款管理规范 v3》，预付款上限从 50% 降至 30%。
17. **Agent 不需要任何人点击按钮**。`RuleChangeMonitor` 检测到规则变更，自动创建 `RULE_IMPACT_REVIEW` 任务。
18. Agent 扫描所有在途合同，发现 3 份合同的付款条款与新规则冲突。
19. 3 位对应法务的消息中心同时收到通知：”贵部门在途合同可能受制度 v3 影响，点击查看。”
20. 管理员在驾驶舱看到”规则变更影响：3 份合同待复核”。

### 第五幕：履约异常自主分析

21. 合同签署后，系统从批准版本提取付款、交付、验收、续签义务。
22. 付款义务逾期 3 天。**Agent 不只是提醒**。
23. Agent 自动创建 `FULFILLMENT_BREACH_ANALYSIS` 任务，自主拉取：
    - 合同违约条款：”日万分之五，无宽限期。”
    - 沟通记录：”我方逾期前 2 天的邮件通知（支付系统升级）。”
    - 历史处置：”去年类似案例，对方最终放弃 70% 违约金。”
24. Agent 输出应对方案：”建议立即支付并引用沟通记录争取免责。”
25. 负责人一键采纳方案，系统生成支付任务和致歉函草稿。

### 第六幕：规则持续优化

26. 3 个月后，Agent 发现”验收标准模糊”规则在 80% 的案件中被驳回。
27. Agent 自动生成 `Rule Health Report`：建议降级或增加豁免条件。
28. 管理员审核后发布规则 v2，系统记录规则变更历史。
29. 旧版本规则自动失效，新案件使用 v2 规则。

---

该演示完整覆盖 Agent 的七种工作模式：**语义匹配、被动审查、协商策略、智能审批、自主巡检、异常分析、自我改进**。

核心差异化不在”能不能审查合同”，而在：
- 条款改了 → Agent 告诉你”这个改动实质是什么、要不要争”（语义匹配）
- 审批时 → Agent 告诉审批人”你只需要决策这 1 个问题”（智能审批）  
- 没人点按钮 → Agent 自己在做事（自主巡检、履约异常分析）
