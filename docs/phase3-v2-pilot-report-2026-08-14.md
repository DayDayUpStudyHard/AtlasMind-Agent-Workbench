# Phase 3 试点报告：contract_review v2 DAG（WorkUnit 子项化 + 反证 + 负向门禁）

> 日期：2026-08-14
> 对应 PRD：§15（contract_review 高召回 DAG 试点）
> 代码版本：4574097
> 状态：评测暂停，改由用户手动评测（run 30 在旧 42-WU 架构下完成 12/30 例后停止；runs 31/32 待手动执行）

---

## 1. 交付物清单

| PRD Phase 3 交付物 | 状态 | 位置 |
|---|---|---|
| contract_review v2 DAG 图 | ✅ | app/agent_runtime/graph/review_v2.py（22 节点） |
| v2 注册（非默认） | ✅ | routes.py `_init_contract_runtime`（adapter `contract_review_v2`，graph_name=contract_review, version=v2） |
| dispatch 扩展 | ✅ | runtime.py `dispatch_with_mode` 新增 `langgraph_v2` 分支（仅 CONTRACT_REVIEW 走 v2，其余回退 v1 图） |
| 单元测试 | ✅ | tests/test_review_v2.py（22 测试）+ 全套 176 通过 |
| v1 保持默认且不动 | ✅ | contract_review.py v1 未改；v1 adapter 未动 |
| v1/v2 对照评测 | ⏳ | run 25（v1 基线）vs run 30（v2）；Golden run 31（v1）vs 32（v2）— 用户手动评测 |
| Shadow Run（任务 10） | ✅ | `shadow_v2` 运行时模式已接线：dispatch_with_mode + DB 配置 `agent.runtime.CONTRACT_REVIEW=shadow_v2`；影子图用独立 `shadow-` checkpoint 线程，不写 run 行/报告/trace，差异落一条 SHADOW_DIFF trace |

---

## 2. v2 图结构

```
load_run_context → freeze_case_snapshot → inventory_clauses
→ build_contract_map（条款目录/附件覆盖/类型清单）
→ plan_work_units（6 固定域 WorkUnit，42 子检查内嵌为清单；动态领域 ≤4，总上限 10）
→ retrieve_evidence_for_work_units（每域 ≤2 意图变体 + 反证查询，并发 4）
→ run_deterministic_rules
→ analyze_work_unit_risks（每域 LLM 或确定性缺失结论，并发可调）
→ analyze_counter_evidence（EXCEPTION/LIMITATION/EXEMPTION/CONFLICT 分类）
→ merge_candidates（LLM 发现 + 未被覆盖的规则发现）
→ validate_grounding（GroundingValidator + §15.3 负向门禁）
→ audit_coverage（OmissionAuditor：没审到/有证据无发现/证据不足 + 未用条款）
→ targeted_retrieval（仅 reanalysis_targets，merge_bundles UNION）→ reanalyze_affected_work_units
→ compose_report / compose_limited_report → validate_schema → repair_artifact
→ prepare_human_review → persist_report
```

> 变体说明：初版按 42 个子项每个独立建 WorkUnit（每项独立检索+分析），§3.4 诊断显示检索层占 ~80% 耗时后，改为快速运行时——子项收缩为域内检查清单，检索/分析在域粒度共享。召回保障不变（42 项检查仍全部进入分析提示词与 Omission Auditor 范围），检索轮次与外部 API 调用次数大幅下降。

五个关键变化（PRD §15 验收对照）：

| # | 要求 | 实现 |
|---|---|---|
| 1 | 领域任务拆子项 WorkUnit | `_SUB_ITEM_BASELINE` 固定表：6 领域 42 子项（快速运行时：6 个域级 WorkUnit，子项作为 subCheckItems 内嵌清单，每域 ≤2 查询意图）；动态领域 ≤4，总上限 10 |
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

### 3.4 每例耗时分层诊断（前 3 例节点级时间线，agent_run_trace）

> 注：下表是**旧 42 子项 WorkUnit 架构**下的数据（run 30 前 3 例）。诊断结论（慢在检索层）已被采纳：v2 已改为**快速运行时**——6 个固定域各为一个 WorkUnit，42 个子检查作为内嵌清单（subCheckItems）共享同一证据束，每 WorkUnit ≤2 查询意图，动态域 ≤4、总上限 10。手工评测将以该压缩变体为准，耗时预计显著下降。

| 阶段 | 748 | 749 | 750 | 均值 | 占比 |
|---|---|---|---|---|---|
| plan_work_units | 5s | 4s | 6s | 5s | ~1% |
| retrieve_evidence_for_work_units（首轮检索） | 326s | 230s | 301s | 286s | 33% |
| analyze_work_unit_risks（LLM 分析） | 162s | 154s | 138s | 151s | 18% |
| analyze_counter_evidence（反证） | 1s | 0s | 0s | <1s | ~0% |
| targeted_retrieval 第 1 轮 | 189s | 157s | 226s | 191s | 22% |
| reanalyze 第 1 轮 | 38s | 41s | 33s | 37s | 4% |
| targeted_retrieval 第 2 轮 | 160s | 173s | 293s | 209s | 24% |
| reanalyze 第 2 轮 | 42s | 40s | 32s | 38s | 4% |
| 组装+校验+持久化 | ~3s | ~2s | ~2s | 2s | ~0% |

结论：**慢在检索层（首轮+两轮回补 ≈ 686s/例，约 80%），不在 LLM（151s，45-46 WU 并发 4 ≈ 3.3s/WU）**。

检索慢的三个叠加因素：
1. 外部 API 超时税：Embedding（siliconflow）反复 30s 超时才走 keyword/RRF 降级；Reranker 同样 read timed out。每 WU 2+ 意图变体 × 2 反证模板放大了超时次数。
2. kb_chunks ES 索引 404：vector+keyword 双通道每次先打 ES 再降级，开发环境纯白打（生产索引存在可缓解，但 embedding 超时是外部依赖问题）。
3. 回补不收敛：3 例均跑满 2 轮 targeted_retrieval，且 750 第二轮（293s）> 第一轮（226s）——OmissionAuditor 每轮仍产出新 EvidenceNeed，回补范围未收敛。

已识别、暂未实施的优化候选（评测期间不动代码，等 runs 30-32 出结果后决策）：
- 补 latency 测量：agent_tool_call.latency_ms 列已存在，graph 路径当前写 0 → 补测量后管理端运行详情可展示分层耗时
- embedding 超时缩至 5-8s；kb_chunks ES 404 时直接跳过向量通道（纯去税，不影响召回）
- targeted_retrieval 收敛性观察（涉及召回逻辑，谨慎评估）

### 3.5 已修复/已记录的问题

- **started_at 显示缺陷**：建行脚本在 QUEUED 行预填 started_at=NOW()（行创建时间），UI 把 03:44 显示成评测开始时间。已修复：`_update_eval_progress` 在首次 active 触达时 `started_at=COALESCE(started_at, NOW())`，建行脚本不再预填（评测行 31/32 已清空，待驱动触达时打真实时间；行 30 的 03:44 为历史遗留，真实开始 12:40）。
- **900s 超时杀（已修复）**：recovery.py 规则 #2 原按 create_time+900s 杀 active 状态的 run，与评测配置 caseTimeoutSeconds=2400 无关、心跳不豁免。行 747（case 1 第一次尝试）被 12:20 版驱动的 900s 超时杀死。已修复：规则 #2 改为**心跳失联判定**（`find_timed_out_runs(require_stale_heartbeat=True)`）——持续心跳的 run 即使超过 900s 也视为存活，仅当心跳也丢失（或本无心跳的旧派发路径）才按超时杀；僵尸扫描（60s 心跳失联）不受影响。修复后手动评测与生产 >15min 的 run 不再被误杀。
- **GraphAdapter 心跳**：graph 派发无心跳导致跨进程误杀，已修复（15s 自终止心跳循环）+ 独立驱动脚本内禁用本进程 RunRecovery 扫描器。

---

## 4. 结论

待填（用户手动评测后补录）：召回是否过线（PRD §22 门槛）、v2 是否具备转默认条件、Phase 4 通用 Harness 是否放行。

评测执行方式备忘（供手动评测）：
- 评测驱动脚本 scripts/run_v2_evals.py / run_baseline_evals.py（独立进程、自带 RunRecovery 禁用、每例超时由 features caseTimeoutSeconds 控制）；
- 建行脚本 scripts/create_v2_eval_runs.py（QUEUED 行不再预填 started_at，首次触达打真实时间）；
- 运行观察 scripts/watch_v2_runs.py / watch_baseline_runs.py；
- run 30（v2，30 例）在旧 42-WU 架构下完成 12/30 例，状态 RUNNING@case13 残留——手动评测建议以压缩变体新开 run 对照，旧 run 30 数据仅作参考；
- API server 扫描器在修 900s 规则后，>15min 且持续心跳的 case 不会再被误杀。
