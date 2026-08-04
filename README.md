# AtlasMind Agent Workbench — ContractOps

企业合同全生命周期智能运营平台。将合同案件管理、条款审查、风险评分、履约跟踪与 AI Agent 自动化结合，面向法务、采购和业务团队提供可审计的合同智能服务。

> **当前产品方向**：企业合同生命周期运营 Agent（Contract Lifecycle Operations Agent）
>
> **已落地能力**：合同案件管理、19 条审查规则、5 维风险评分、12 个 Agent 工具、履约义务提取、版本对比、管理端规则/条款库

---

## 产品架构

```text
      合同文件 / 纯文字
          ↓
    AI 结构化提取 + 原文引用核验
          ↓
    人工确认我方主体与关键字段
          ↓
    合同案件创建（前台 / API）
          ↓
    Agent 审查 / 发起 / 审批决策
          ↓
    Python Harness：12 工具 × 6 Phase
          ↓
    审查发现 + 风险评分 + 履约义务
          ↓
    报告 → 审批 → 动作执行
          ↓
    履约跟踪 / 到期提醒 / 续签评估
```

**核心原则**：

- **确定性规则优先**：19 条审查规则覆盖缺失检查 / 关键词 / 阈值 / 语义四类，支持一票否决
- **LLM 增强非替代**：规则引擎兜底评分，LLM 负责语义理解和报告生成
- **所有结论可追溯**：审查发现带双引用（合同原文 + 制度依据），Agent Run 保存完整调用链
- **人工审批边界**：高风险动作（创建协商任务、排期提醒等）必须经过审批

---

## 功能概览

### 前台工作台 (port 15174)

| 模块 | 功能 |
|------|------|
| 合同组合驾驶舱 | 12 KPI 卡片（案件数/待审/履约中/即将到期/逾期义务等）+ 4 快捷动作 |
| 智能合同录入 | 粘贴正文或选择 TXT/Markdown 文件，DeepSeek 提取 8 个核心字段，逐项展示原文引用，人工确认后建案 |
| 合同案件详情 | 元信息 / 主体 / 文件（含纯文字上传）/ Agent Run / 审查发现 / 履约义务 |
| 文件上传 | 支持文件登记 + **纯文字粘贴**两种模式 |
| Agent 对话 | ChatWindow 合同对话模式 |

### 管理端 (port 15173)

| 模块 | 功能 |
|------|------|
| 合同驾驶舱 | 合同案件统计 + 最近 Run + 最近文件 |
| 审查规则管理 | 19 条规则 CRUD、启用/停用、一票否决配置、4 种检查方式 |
| 标准条款库 | 4 类标准条款、语义要素编辑、谈判底线配置 |
| 文件解析任务 | 跨案件文档列表、停止解析（PENDING/PARSING）、删除 |
| Agent 运行记录 | 强制停止运行中 Run、删除 Run + 关联数据 |
| 知识来源 | KB 空间/文档管理、RAG 检索测试 |
| 报告与审批 | 报告列表 + 动作队列审计 |

### Agent 能力（12 工具）

| 工具 | 说明 |
|------|------|
| `getContractCase` | 读取合同基本信息 |
| `getContractParties` | 读取合同主体和风险评分 |
| `listContractDocuments` | 列出合同文件版本 |
| `readContractClause` | 按类型读取条款原文+语义要素 |
| `searchPolicyKnowledge` | 检索企业采购制度和标准条款 |
| `findStandardClause` | 匹配标准条款库 |
| `searchHistoricalDecisions` | 检索历史审查发现 |
| `evaluateReviewRules` | 执行确定性规则检查 |
| `calculateContractRisk` | 5 维加权风险评分（含一票否决） |
| `extractObligations` | 从条款提取履约义务 |
| `verifyFulfillmentEvidence` | 核验履约证据 |
| `compareContractVersions` | 版本差异对比 |

### 5 维风险评分

| 维度 | 权重 | 说明 |
|------|------|------|
| 主体与授权 | 15% | 签约主体资质、授权链条 |
| 商务与付款 | 20% | 付款条件、预付款比例、账期 |
| 责任与违约 | 25% | 责任上限、违约金、间接损失 |
| 合规与保密 | 20% | 数据保护、保密期限、合规要求 |
| 履约可执行性 | 20% | 验收标准、交付物、里程碑 |

---

## 技术架构

| 层级 | 技术 |
|------|------|
| Java 业务后端 | Spring Boot 3.2.5, Java 17, Sa-Token, JdbcTemplate |
| Agent 调度 | Redis Stream (XADD → Consumer Group) + HTTP fallback |
| AI 服务 | Python FastAPI, DeepSeek API, sentence-transformers |
| 数据层 | MySQL 8.x, Redis, Elasticsearch |
| 前端（用户） | Vue 3, Naive UI, marked |
| 前端（管理） | Vue 3, Element Plus |
| 向量记忆 | all-MiniLM-L6-v2 (F7) |
| Prompt 管理 | DB 驱动 + 30s 缓存 + A/B 分流 (F6) |

### 服务边界

```text
agent-server/         Java API、鉴权、审批、Redis Stream 调度
tools/.../backend/    Python Agent Runtime、6-Phase Harness、LLM 调用、向量检索
agent-admin/          管理端：规则/条款库、Agent Run、文件管理、可观测性
agent-front/          用户端：合同工作台、案件详情、Agent 对话
```

---

## 项目结构

```text
AtlasMind-Agent-Workbench/
├── agent-server/                  # Java 业务后端
├── agent-admin/                   # 管理端 (Vue 3 + Element Plus)
├── agent-front/                   # 用户端 (Vue 3 + Naive UI)
├── tools/chat-assistant/backend/  # Python AI 微服务
│   ├── app/agent_runtime/         # Agent Harness、工具注册、风险评分
│   ├── app/services/              # LLM 服务、熔断器
│   └── migrations/                # DB 增量迁移脚本 (V001-V013)
├── docs/                          # PRD 和技术文档
├── nginx/                         # 反向代理配置
└── start.bat                      # 一键启动脚本
```

---

## 本地端口

| 服务 | 地址 |
|------|------|
| Java 后端 | http://localhost:18080 |
| 管理端 | http://localhost:15173 |
| 用户端 | http://localhost:15174 |
| Python AI 服务 | http://localhost:18088 |
| Knife4j API 文档 | http://localhost:18080/doc.html |

---

## 数据库

数据库名 `atlasmind_agent`，核心表：

| 表 | 说明 |
|------|------|
| `contract_case` | 合同案件主表 |
| `contract_intake` | 合同正文暂存、模型提取结果、已验证引用与人工确认数据 |
| `contract_document` | 合同文件（支持纯文字 `content_text`） |
| `contract_clause` | 提取的合同条款 + 语义要素 |
| `contract_party` | 合同主体（我方/对方/担保方） |
| `contract_review_rule` | 审查规则（19 条种子数据） |
| `contract_review_finding` | 审查发现（双引用） |
| `contract_standard_clause` | 标准条款库 |
| `contract_obligation` | 履约义务跟踪 |
| `agent_run` / `agent_report` / `agent_action` | Agent 运行/报告/动作（`subject_type` 抽象） |
| `agent_run_trace` / `agent_tool_call` | 执行追踪 |

---

## 快速启动

1. 启动 MySQL、Redis、Elasticsearch
2. 运行根目录 `start.bat` 一键启动全部服务：

```bash
start.bat
```

或分别启动：

```bash
# Java 后端 (port 18080)
cd agent-server && mvnw.cmd spring-boot:run

# Python AI 服务 (port 18088)
cd tools/chat-assistant/backend && python run.py

# 管理端 (port 15173)
cd agent-admin && npm install && npm run dev

# 用户端 (port 15174)
cd agent-front && npm install && npm run dev
```

---

## AI 服务配置

`tools/chat-assistant/backend/.env`：

```env
LLM_API_KEY=your-deepseek-api-key
LLM_BASE_URL=https://api.deepseek.com
LLM_MODEL=deepseek-chat

MYSQL_HOST=localhost
MYSQL_PORT=3306
MYSQL_USER=root
MYSQL_PASSWORD=123456
MYSQL_DB=atlasmind_agent

REDIS_URL=redis://localhost:6379/0
```

---

## LLM 不可达处理

当 DeepSeek API 不可达时：

1. **连接错误**：首次 12s 超时 → 1s 后重试一次 → 再超时则设置 `_connection_dead = True`
2. **后续 Phase 跳过 LLM**：Planner / Tool Turn / Reflection 直接使用确定性 fallback
3. **Run 标记 FAILED**：总耗时 ~25-60s，错误信息"LLM 服务不可达"
4. **熔断器**：连续 2 次连接失败 → 断路器打开 60s
5. **RunRecovery**：CREATED 超过 120s 未接取 → 自动 FAILED

---

## 最近更新

- **2026-08-03**：合同智能录入上线：DeepSeek 结构化提取、确定性字段/引用校验、人工确认后事务化建案、失败降级与重试
- **2026-08-03**：纯文字合同上传、LLM 不可达快速失败、文件解析停止/删除、后台项目残留清理
- **2026-08-02**：合同案件管理 pivot 完成、审查规则管理 + 标准条款库管理端、12 个 Agent 工具
- **2026-08-01**：Redis Stream 调度 (F1)、SSE 流式进度 (F3)、并发工具执行 (F5)、Prompt 版本管理 (F6)、向量记忆 (F7)
- **2026-07-31**：ContractOps PRD、7 表迁移、5 维风险评分、Agent Harness 适配
