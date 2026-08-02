# AtlasMind Agent 架构优化与业务功能 PRD

**版本**: v1.0 | **日期**: 2026-08-02 | **状态**: Draft

---

## 目录

1. [文档概述](#1-文档概述)
2. [现状评估](#2-现状评估)
3. [Tier 1: 可靠性底座 P0](#3-tier-1-可靠性底座-p0)
4. [Tier 2: 智能增强 P1](#4-tier-2-智能增强-p1)
5. [Tier 3: 前瞻架构 P2](#5-tier-3-前瞻架构-p2)
6. [业务功能方案](#6-业务功能方案)
7. [实施路线图](#7-实施路线图)
8. [成功指标](#8-成功指标)
9. [风险与缓解](#9-风险与缓解)
10. [附录](#10-附录)

---

## 1. 文档概述

### 1.1 背景

AtlasMind Agent Workbench 已完成 Agent Runtime 从 Java 到 Python 的迁移（v3-python），当前为：

```
用户 → Java (API / 鉴权 / 审批 / GitHub 同步)
         → HTTP → Python Agent Runtime (6-Phase Harness)
              → MySQL (共享) + DeepSeek (LLM) + Elasticsearch (KB)
```

Shadow Run 验证通过（8/8 逐位项一致），Java 旧 harness 已清理。本文档规划后续架构优化和业务功能。

### 1.2 目标

- **架构优化** — 提升可靠性、性能、可扩展性和可观测性
- **业务功能** — 从"分析建议"走向"闭环执行"

---

## 2. 现状评估

### 2.1 8 个结构性约束

| # | 约束 | 根因 | 严重度 |
|---|------|------|--------|
| C1 | 串行管道 — LLM 推理时工具空闲 | 6 Phase 严格顺序 | 🔴 |
| C2 | 单进程调度 — 进程死 = 所有 Run 死 | `asyncio.create_task()`，无消息队列 | 🔴 |
| C3 | HTTP 桥无交付保证 — 失败直接标 FAILED | 无重试/背压 | 🔴 |
| C4 | 取消不可观测 — 设 `CANCELLED` 后 harness 不检查 | 循环中无 status 检查点 | 🟡 |
| C5 | 无连接池 — 每次 DB 调用新建连接 | `pymysql.connect()` 每次 new | 🟡 |
| C6 | 工具面窄 — 7 个只读工具 | 硬编码白名单 | 🟡 |
| C7 | 记忆扁平 — 仅关键词匹配 | 无向量/语义检索 | 🟢 |
| C8 | 无反馈闭环 — Prompt 无法迭代 | 用户从不评分 | 🟢 |

### 2.2 关键硬编码

| 项目 | 位置 | 当前值 |
|------|------|--------|
| 最大工具调用/轮数/超时 | `runner.py:52-54` | 8 / 2 / 300s |
| 心跳/恢复间隔 | `runner.py:55`, `recovery.py:17` | 15s / 30s |
| 观察窗口上限 | `runner.py:320` | 12 条 |
| 工具白名单 | `tools.py` | 7 个（不可变） |
| 评分关键词/权重 | `scoring.py` | 全部硬编码 |
| 所有 LLM Prompt | `llm_service.py` | 全部硬编码 |
| Java→Python HTTP 超时 | `HttpAiGateway.java` | 连接 3s, 读取 12s |

---

## 3. Tier 1: 可靠性底座 P0

> 工时 2 周 | 低风险 | 解决 C1-C4

### 3.1 F1: Redis Stream 消息队列

**问题**: Java HTTP 直连 Python，Python 不可用时 Run 立即 FAILED。

**方案**:
```
Java ──XADD──→ Redis Stream `agent:run:queue`
                    ↓
         Python Consumer Group 消费 → XACK
                    ↓
         Worker 崩溃 → PEL 保留 → 新 worker 认领
```

- **零新依赖**（已有 Redis 5.0+）
- Java 发布后立即返回（不等 Python），网络抖动不丢任务
- 多 worker 水平扩展
- 保留 HTTP 端点作为 fallback

**改动**: Java `dispatchToPython()` → `XADD`; Python 新增 `worker.py`（Stream 消费循环）; routes.py 保留 `/internal/agent/run` 端点

**验收**:
- Java 发布到返回 < 500ms
- Worker 崩溃重启 → PEL 消息被重新消费
- 端到端延迟增加 < 500ms
- HTTP fallback 仍可用

### 3.2 F2: LLM 重试 + 熔断

**问题**: DeepSeek 短暂波动触发降级，影响报告质量。

**方案** (使用 `tenacity`):

| LLM 调用 | 重试 | 退避 | 超时 |
|----------|------|------|------|
| `plan_agent` | 3 | 2s→4s→8s | 30s |
| `next_agent_turn` | 2 | 1s→4s | 20s |
| `reflect_agent` | 2 | 2s→4s | 20s |
| `analyze_project` | 3 | 2s→4s→8s | 60s |

熔断器: 5 分钟窗口内失败率 > 50% → 熔断 60s → 期间全部走 fallback

**验收**: 503 → 自动重试成功（用户无感知）；连续失败 → 熔断 → 自动恢复

### 3.3 F3: SSE 流式进度

**问题**: 前端每 3s poll，看到滞后快照。

**方案**:
```
Python harness → PUBLISH run:123:status (Redis PubSub)
     → Java SUBSCRIBE → SSE → 前端 EventSource
```

SSE 事件: `phase`, `tool_start`, `tool_done`, `llm_thinking`, `completed`, `failed`, `heartbeat`

**改动**: Python `_heartbeat_loop()` 增加 publish; Java 新增 `GET /.../runs/{id}/stream` (SSE); 前端替换 poll 为 EventSource

**验收**: 首个事件 < 500ms；Phase 顺序正确；不破坏现有 poll 模式

### 3.4 F4: 取消可观测 + 幂等

**问题**: 取消不生效；重复 `requestId` 创建双 task。

**方案**:
- `AgentExecutionPolicy.check_cancelled()` — 每个 Phase 前 + 每次工具前检查
- `_active_runs: dict[requestId, Task]` — 幂等去重

**验收**: 取消请求 → 5s 内状态变 CANCELLED；重复 requestId → 返回已有任务

---

## 4. Tier 2: 智能增强 P1

> 工时 4 周 | 中风险 | 解决 C5-C7

### 4.1 F5: 并发工具调用

**问题**: 无依赖工具（如 `getProjectProfile` + `getProjectMemory`）串行等待。

**方案**: ReAct 模式 — 分析 LLM 返回的 `tool_calls[]` 依赖关系 → `asyncio.gather()` 并发执行无依赖组

**验收**: 3 个无依赖工具并发 → 总耗时 ≈ max(单个)；依赖工具保持串行；去重线程安全

### 4.2 F6: Prompt 版本管理

**问题**: 所有 prompt 硬编码，调整需改代码部署；无法 A/B 对比。

**方案**: `agent_prompt` 表（prompt_key, version, template, temperature, is_active）; `PromptRegistry` 从 DB 加载（30s 缓存）; A/B: 按比例分配 version

**验收**: 修改 prompt → next Run 自动使用；A/B 流量正确记录；DB 故障时 fallback 内置默认

### 4.3 F7: 向量化记忆检索

**问题**: 记忆仅关键词匹配，无法语义查询"类似上次 CI 故障怎么处理"。

**方案**: `sentence-transformers` (all-MiniLM-L6-v2, ~80MB) → 异步生成 embedding; Python 内存索引（< 1000 条/项目）

**验收**: `semantic=true` → Top-5 cosine > 0.7；embedding 生成不阻塞主循环

### 4.4 F8: 连接池

**问题**: 每次 DB 调用 `_conn()` 新建连接，5 并发 Run = 100+ 瞬时连接。

**方案**: `pymysql` → `aiomysql` (asyncio-native pool，pool_size=5, max_overflow=10); 专用 `_db_executor` ThreadPoolExecutor(8)

**验收**: 并发 5 Run → MySQL 连接 ≤ 15；P50 < 5ms, P99 < 50ms

---

## 5. Tier 3: 前瞻架构 P2

> 工时 6-8 周 | 高风险 | 需设计评审

### 5.1 F9: 多 Agent 编排

**概念**:
```
Coordinator Agent (任务分解)
  ├── Evidence Agent ── 专项证据收集
  ├── CodeReview Agent ── 代码质量
  ├── Risk Agent ──────── 风险评估
  └── Delivery Agent ──── 交付规划
        ↓
Synthesizer Agent (去重 + 合并报告)
```

每个 Sub-Agent 复用现有 `AgentRunner`；Coordinator 用 LLM function-calling 决定派发策略；无依赖 Agent 并发执行。

### 5.2 F10: 主动巡检

每天凌晨自动 HEALTH_ANALYSIS → 趋势追踪 → 预警（连续下降 > 2 周 → 自动告警）

### 5.3 F11: 反馈闭环

报告 ★☆☆☆☆ 评分 → 关联 prompt version → `agent_prompt.performance_score` 更新 → 低分 prompt 自动标记 `is_active=0`

---

## 6. 业务功能方案

### 6.1 B1: 闭环动作执行 P0

**问题**: Agent 只能建议，不能执行。

**方案**: Artifact 中生成结构化 Action Proposals:
```json
{
  "actions": [
    {"type": "CREATE_GITHUB_ISSUE", "title": "修复 CI test_login 失败", "labels": ["bug","ci"]},
    {"type": "UPDATE_PROJECT_CONFIG", "key": "currentMilestone", "value": "Q3 Sprint 3"}
  ]
}
```
已有 `agent_action` → `approveAction` → `executeAction` 链路，只需 Python 生成 proposals + Java 扩展 action 类型。

**验收**: 报告含 ≥1 个 action（有风险时）；用户一键审批 → GitHub Issue 创建成功；支持 3 种 action 类型

### 6.2 B2: 决策量化对比 P1

**问题**: `ENGINEERING_DECISION` 只给框架建议。

**方案**: 多方案量化对比表（迁移成本/安全风险/兼容性/团队熟悉度），每维度有 citation 支撑，输出"推荐方案 + 验证路径 + 回滚条件"

### 6.3 B3: 跨项目洞察 P1

`GET /api/workspace/organization/overview`:
- 组织级健康总览（HEALTHY/WATCH/AT_RISK 分布）
- 共同风险识别（"3/5 项目 CI 不稳定"）
- 趋势数据（≥ 4 季度）

### 6.4 B4-B6: 后续

| ID | 功能 | 优先级 |
|----|------|--------|
| B4 | 入职助手 2.0（角色感知接手路线） | P2 |
| B5 | 定时周报（Slack/邮件推送） | P2 |
| B6 | 规范合规检查（对照团队编码规范） | P2 |

---

## 7. 实施路线图

```
Week 1-2  │ F1 (Redis Stream) + F2 (LLM Retry)          ← 开始
Week 3-4  │ F3 (SSE) + F4 (Cancel) + B1 (闭环动作)
Week 5-6  │ F5 (并发工具) + F8 (连接池)
Week 7-8  │ B2 (决策量化) + F6 (Prompt 管理)
Week 9-10 │ F7 (向量记忆) + B3 (跨项目洞察)
Week 11+  │ F9 (多 Agent 编排) [需设计评审]
          │ F10 (主动巡检) + F11 (反馈闭环)
```

---

## 8. 成功指标

| 维度 | 指标 | 当前 | 目标 |
|------|------|------|------|
| 可靠性 | Run 成功率 | ~95% | > 99.5% |
| 可靠性 | 崩溃影响面 | 全部丢失 | 0 丢失 |
| 可靠性 | 取消生效 | ∞ | < 5s |
| 性能 | HEALTH_ANALYSIS 耗时 | ~90s | < 60s |
| 智能 | Fallback 触发率 | ~2% | < 1% |
| 业务 | 闭环 Issue 数 | 0 | > 10/月 |
| 业务 | 用户报告评分 | 无 | > 3.5/5 |

---

## 9. 风险与缓解

| 风险 | 概率 | 缓解 |
|------|------|------|
| Redis Stream 版本不兼容 | 低 | 保留 HTTP fallback；验证 Redis ≥ 5.0 |
| DeepSeek 长时间不可用 | 中 | 熔断器 + Fallback 降级 |
| 并发工具 → LLM 行为变差 | 中 | A/B 测试；灰度发布；可配置开关 |
| 多 Agent 编排 → Token 成本飙升 | 中 | 默认关闭；按 taskType 可选 |
| Prompt 管理 → DB 读延迟 | 低 | 30s 内存缓存 |

---

## 10. 附录

### A. 相关文件

| 文件 | 角色 |
|------|------|
| `agent-server/.../AgentProjectServiceImpl.java` | Run 生命周期 + 审批 |
| `agent-server/.../HttpAiGateway.java` | Java→Python HTTP 桥 |
| `tools/.../agent_runtime/runner.py` | 6-Phase 主循环 |
| `tools/.../agent_runtime/tools.py` | 7 工具注册/执行 |
| `tools/.../agent_runtime/scoring.py` | 确定性评分引擎 |
| `tools/.../agent_runtime/policy.py` | 预算/超时/去重 |
| `tools/.../agent_runtime/persistence.py` | 5 Store 接口 + MySQL |
| `tools/.../agent_runtime/recovery.py` | 心跳/超时/僵尸扫描 |
| `tools/.../app/api/routes.py` | `/internal/agent/*` 端点 |
| `tools/.../app/services/llm_service.py` | LLM 调用 + Prompt |

### B. 配置项

| 配置 | 默认值 | 位置 |
|------|--------|------|
| `AGENT_RUNTIME` | `python` | `system_config` 表 |
| `LLM_MODEL` | `deepseek-chat` | `.env` |
| `LLM_BASE_URL` | `https://api.deepseek.com` | `.env` |
| `MYSQL_HOST` | `localhost:3306` | `.env` |
| `ES_HOST` | `http://localhost:9200` | `.env` |
| `atlasmind.chat-assistant.url` | `http://localhost:18088` | Spring `application.yml` |
