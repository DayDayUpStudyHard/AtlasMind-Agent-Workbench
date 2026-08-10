# Debug 修复记录

## 2026-08-11：检索重排序 — 关键词奖励 → LLM Cross-Encoder Reranker

### 问题

合同条款检索的最终排序使用 `_rerank_contract_hits()` 做简单的关键词命中奖励（命中一个合同术语 +1000 分），不理解"该条款是否实际回答当前审查问题"。见 [contract_store.py:223](tools/chat-assistant/backend/app/agent_runtime/contract_store.py#L223)。

### 修复

新增 [reranker.py](tools/chat-assistant/backend/app/agent_runtime/reranker.py)（378 行），实现 LLM 语义重排序：

- **召回扩大**：`candidate_k` 从 `max(top_k * 4, 20)` 扩大到 `min(max(top_k * 6, 30), 50)`，即 30～50 条候选
- **LLM Reranker**：使用独立的 `RERANKER_API_KEY` 调用 LLM（key 为空时自动降级到关键词启发式），按四项标准排序：
  1. 问题相关性 — 条款是否直接回答审查问题
  2. 条款完整性 — 完整条款优先于碎片
  3. 主体/条件匹配 — 是否涉及相同的当事人、金额、日期
  4. 同章连贯性 — 同章节条款形成完整画面
- **合同与知识库分离**：`rerank_contract_clauses()` 和 `rerank_policy_items()` 各自独立排序，不交叉竞争
- **配置项**（[config.py](tools/chat-assistant/backend/app/config.py)）：

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `RERANKER_API_KEY` | `""` | 空 = 关键词 fallback，填入即启用 LLM |
| `RERANKER_BASE_URL` | `""` | 空 = 回退到 `LLM_BASE_URL` |
| `RERANKER_MODEL` | `""` | 空 = 回退到 `LLM_MODEL` |
| `RERANKER_MIN_RECALL` | `30` | 最少召回数 |
| `RERANKER_MAX_RECALL` | `50` | 最多召回数 |

### 影响范围

- `contract_store.py` — `search_contract_clause()` 和 `search_policy()` 的召回窗口 + 重排序调用
- `config.py` — 7 个新配置项
- `reranker.py` — 新增模块

---

## 2026-08-11：Targeted Retrieval 补充检索未反馈到分析 — P0

### 问题

合同审查图（ContractReviewGraph）在覆盖不足时执行 `targeted_retrieval` 补充检索，但检索到的关键条款**从未送回领域分析和结论校验**，直接生成"范围受限报告"。即使第二次检索找到了能填补缺口的关键条款，也不能真正修正风险发现。

见 [contract_review.py:117](tools/chat-assistant/backend/app/agent_runtime/graph/contract_review.py#L117)：
```python
# 硬编码边 — 直接跳到 compose_limited_report，跳过 re-analysis
builder.add_edge("targeted_retrieval", "compose_limited_report")
```

而 `_route_after_targeted` 函数（返回 `"validate_claims"`）已正确定义但从未被注册为条件边 — 死代码。

### 修复

将死胡同链路改为闭环：

```
修复前：
  coverage_reflection → targeted_retrieval → compose_limited_report (死胡同)

修复后：
  coverage_reflection → targeted_retrieval
    → draft_domain_findings (只重新分析缺失领域)
    → validate_claims (再次验证)
    → coverage_reflection (再查覆盖)
    → 缺口已补齐 → compose_report (完整报告!)
    → 缺口仍存在 → compose_limited_report (retry_count>=1 终止)
```

四处修改：

1. **[contract_review.py:51-57](tools/chat-assistant/backend/app/agent_runtime/graph/contract_review.py#L51)** — `_route_after_targeted` 改为路由到 `draft_domain_findings`
2. **[contract_review.py:120-129](tools/chat-assistant/backend/app/agent_runtime/graph/contract_review.py#L120)** — 硬编码边替换为条件边
3. **[retrieval.py:582-597](tools/chat-assistant/backend/app/agent_runtime/graph/nodes/retrieval.py#L582)** — `draft_domain_findings` 新增 `gap_domains` 参数，仅重新分析缺失领域，已覆盖领域的 findings/analysis 保持不变
4. **[reflection.py:217-224](tools/chat-assistant/backend/app/agent_runtime/graph/nodes/reflection.py#L217)** — `targeted_retrieval` 返回 `gap_domains` 标记

### 影响范围

- `contract_review.py` — 图边路由
- `retrieval.py` — `draft_domain_findings` 支持选择性重分析
- `reflection.py` — `targeted_retrieval` 传回 `gap_domains`
