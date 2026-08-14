# Phase 3 试点报告：contract_review v2 DAG（WorkUnit 子项化 + 反证 + 负向门禁）

> 日期：2026-08-14
> 对应 PRD：§15（contract_review 高召回 DAG 试点）
> 代码版本：待填（commit）
> 状态：v2 评测待 runs 30-32 完成后补录

---

## 1. 交付物清单

| PRD Phase 3 交付物 | 状态 | 位置 |
|---|---|---|
| contract_review v2 DAG 图 | ✅ | app/agent_runtime/graph/review_v2.py（22 节点） |
| v2 注册（非默认） | ✅ | routes.py `_init_contract_runtime`（adapter `contract_review_v2`，graph_name=contract_review, version=v2） |
| dispatch 扩展 | ✅ | runtime.py `dispatch_with_mode` 新增 `langgraph_v2` 分支（仅 CONTRACT_REVIEW 走 v2，其余回退 v1 图） |
| 单元测试 | ✅ | tests/test_review_v2.py（22 测试）+ 全套 176 通过 |
| v1 保持默认且不动 | ✅ | contract_review.py v1 未改；v1 adapter 未动 |
| v1/v2 对照评测 | ⏳ | run 25（v1 基线）vs run 30（v2）；Golden run 31（v1）vs 32（v2） |
| Shadow 说明 | ✅ | v2 评测走临时 fixture case + 独立 run 行，不触碰生产案例；生产 shadow 开关不在本试点范围 |

---

## 2. v2 图结构

```
load_run_context → freeze_case_snapshot → inventory_clauses
→ build_contract_map（条款目录/附件覆盖/类型清单）
→ plan_work_units（固定基线表 42 子项 + 动态领域 ≤4）
→ retrieve_evidence_for_work_units（每子项多意图变体 + 反证查询，并发 4）
→ run_deterministic_rules
→ analyze_work_unit_risks（每子项 LLM 或确定性缺失结论，并发可调）
→ analyze_counter_evidence（EXCEPTION/LIMITATION/EXEMPTION/CONFLICT 分类）
→ merge_candidates（LLM 发现 + 未被覆盖的规则发现）
→ validate_grounding（GroundingValidator + §15.3 负向门禁）
→ audit_coverage（OmissionAuditor：没审到/有证据无发现/证据不足 + 未用条款）
→ targeted_retrieval（仅 reanalysis_targets，merge_bundles UNION）→ reanalyze_affected_work_units
→ compose_report / compose_limited_report → validate_schema → repair_artifact
→ prepare_human_review → persist_report
```

五个关键变化（PRD §15 验收对照）：

| # | 要求 | 实现 |
|---|---|---|
| 1 | 领域任务拆子项 WorkUnit | `_SUB_ITEM_BASELINE` 固定表：6 领域 42 子项，每项 ≥2 查询意图 + 优先级；动态领域 ≤4 |
| 2 | 首轮+定向证据 UNION，检索失败≠立即 LIMITED | `merge_bundles` 按 sourceId 并集；LIMITED 仅当预算耗尽/不可重试 |
| 3 | 反证与例外分析 | 每 WU 反证池（2 模板×意图），确定性四分类 |
| 4 | OmissionAuditor | 三失败类 + 未使用目录条款 → EvidenceNeed[]，驱动回补 |
| 5 | 负向结论门禁 | 9 项检查（§15.3 八前置 + 审计无反证）；不通过即软化为"当前证据范围内暂未确认" |

---

## 3. 对照评测结果

### 3.1 主回归集（dataset 9，30 例）

| 指标 | v1 基线（run 25，冻结代码） | v2 试点（run 30） | 变化 |
|---|---|---|---|
| highRiskRecall | 待填 | 待填 | — |
| dualCitationRate | 待填 | 待填 | — |
| falsePositiveRate | 待填 | 待填 | — |
| schemaValidRate | 待填 | 待填 | — |
| passed/caseCount | 待填 | 待填 | — |
| FULL/LIMITED 比例 | 待填 | 待填 | — |
| 平均耗时/例 | 待填 | 待填 | — |
| infraFailedCount | 待填 | 待填 | — |

### 3.2 Golden 回归集（dataset 20，2 例）

| 用例 | v1（run 31） | v2（run 32） |
|---|---|---|
| GD-RV-001 付款条款引用附件隐藏验收风险 | 待填 | 待填 |
| GD-RV-002 缺验收条款规则发现须带解释 | 待填 | 待填 |

### 3.3 最常遗漏 WorkUnit

| WorkUnit | v1 漏检（对应期望维度） | v2 状态 | 备注 |
|---|---|---|---|
| 待填 | | | |

---

## 4. 结论

待填：召回是否过线（PRD §22 门槛）、v2 是否具备转默认条件、Phase 4 通用 Harness 是否放行。
