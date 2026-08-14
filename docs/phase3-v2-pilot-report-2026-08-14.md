# Phase 3 试点报告：contract_review v2 DAG（WorkUnit 子项化 + 反证 + 负向门禁）

> 日期：2026-08-14
> 对应 PRD：§15（contract_review 高召回 DAG 试点）
> 代码版本：6239e4d + a95f5cf（评分器维度规范化修复，存量分数重算）
> 状态：**部分评测**——run 30（主回归集 dataset 9, langgraph_v2）以 6/30 例部分结果终止（20:38 用户因耗时叫停，第 7 例中止，前 6 例有效）；runs 33/35（标称 langgraph_v2）已作废（API 老进程静默回退 Legacy，详见 §3.5）。v1 基线 = run 25（30 例完整，独立进程驱动）。runs 31/32（golden 2 例对照）未执行，保持 QUEUED。限流（`_CHANNEL_FANOUT_LIMIT=3`，6239e4d）消除了供应商超时税但**未达提速预期**：实测 12.3min/例 vs v1 2.4min/例（详见 §3.1/§3.4）。**评分器口径修正**：a95f5cf 修复维度词表不匹配后，全部存量分数已用新匹配器重算（不重跑），官方原值保留在 DB `officialHighRiskRecall`；本报告 §3.1/§4 同时给出官方与重算两套口径。

---

## 1. 交付物清单

| PRD Phase 3 交付物 | 状态 | 位置 |
|---|---|---|
| contract_review v2 DAG 图 | ✅ | app/agent_runtime/graph/review_v2.py（22 节点） |
| v2 注册（非默认） | ✅ | routes.py `_init_contract_runtime`（adapter `contract_review_v2`，graph_name=contract_review, version=v2） |
| dispatch 扩展 | ✅ | runtime.py `dispatch_with_mode` 新增 `langgraph_v2` 分支（仅 CONTRACT_REVIEW 走 v2，其余回退 v1 图） |
| 单元测试 | ✅ | tests/test_review_v2.py（22 测试）+ 全套 176 通过 |
| v1 保持默认且不动 | ✅ | contract_review.py v1 未改；v1 adapter 未动 |
| v1/v2 对照评测 | ⏳ | runs 33/35（标称 v2）经 trace 查证实际执行 Legacy，作废；待重启 API 服务后重跑 |
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

> ⚠️ v2 列为**部分结果**：2026-08-14 20:38 用户因耗时叫停，run 30 只完成前 6 例（case 121-126）即终止，第 7 例中止。v2 列分母为 6 例，不能直接与 v1 全量 30 例对比；下附同 6 例对齐对比。

| 指标 | v1 基线（run 25，30 例全量） | v2 试点（run 30，6/30 部分） |
|---|---|---|
| highRiskRecall | 0.6167 | 0.9167（部分） |
| dualCitationRate | 0.3694 | 0.3906（部分） |
| falsePositiveRate | 0.0 | 0.0 |
| schemaValidRate | 1.0 | 1.0 |
| passed/caseCount | 30/30 | 6/6（部分） |
| FULL/LIMITED 比例 | 1/29（limited 96.7%） | 0/6（limited 100%） |
| 平均耗时/例 | 145.7s（91-256s） | 739.8s（372-1182s） |
| infraFailedCount | 0 | 0（第 7 例系手动中止，不计入） |

**同 6 例对齐（case 121-126，两版都跑过）：**

| 指标 | v1（run 25 前 6 例） | v2（run 30 前 6 例） | 变化 |
|---|---|---|---|
| highRiskRecall | 0.9167 | 0.9167 | 持平 |
| dualCitationRate | 0.3222 | 0.3906 | **+21%** |
| falsePositiveRate | 0.0 | 0.0 | 持平 |
| schemaValidRate | 1.0 | 1.0 | 持平 |
| 平均耗时/例 | ~150s | 739.8s | **慢 5.1×** |

> 注意：前 6 例是数据集最容易的一批（v1 对其中 5 例 recall 已是 1.0）。双引用率 +21% 是 v2 在相同用例上的一个温和正向信号。

**评分器重算口径（a95f5cf，2026-08-14，仅重算不重跑）：**

| 指标 | 官方原值 | 重算值 | 说明 |
|---|---|---|---|
| v1 highRiskRecall（run 25，30 例） | 0.6167 | **0.9333** | 10 例修正：128/136/139-142/144/146/147 → 1.0，138 → 0.5 |
| v2 highRiskRecall（run 30，6/30 部分） | 0.9167 | 0.9167 | 无变化（前 6 例无门禁误杀） |
| 难例复测 highRiskRecall（run 36，3 例） | 0.0 | **0.8333** | CR-008/CR-016 → 1.0，CR-018 → 0.5 |

官方 0.6167 的低分并非 v1 真漏检：评分器维度门禁把两套不对齐的词表（期望 riskDimension vs 产出 domainKey/clauseType）硬性比较，误杀了大量文本已命中的匹配（详见 §3.5）。重算后 v1 残差真丢分仅 4 例各 0.5：CR-003（责任上限条款）、CR-018（"已为公众所知"维度）、CR-025（长租期退出路径）、CR-028（附件隐藏排他条款）。**"v1 丢分难例"中的 8/10 例是评分器伪像，并非难例。**

难例复测（run 36，dataset 23）重算后的真实对比：CR-008/CR-016 两引擎文本层面均完整命中（v1 官方 0.0 系误杀）；CR-018 是唯一真实差异——v1 命中「保密义务永久有效」、漏「已为公众所知」，v2 恰好相反（漏「保密期限永久有效」、命中「已为公众所知」），各 0.5。

**全量重算（2026-08-14 晚，全部存量 run 一视同仁，scripts/rescore_eval_high_recall.py 自动发现）：**

| Run | 引擎 | 官方 | 重算 | 备注 |
|---|---|---|---|---|
| 15/16/18/19/22 | langgraph | 57.8-64.4% | 78.3-90.0% | 各 8-10 例修正，与 run 25 的 93.3% 汇合 |
| 20/26 | legacy | 31.7/35.0% | 41.7/45.0% | 4-5 例修正 |
| 13/14 | legacy | 1.7% | 3.3/11.7% | artifact 大量缺失（18-19 例无 findings） |
| 35 | 标称 v2 实为 Legacy（§3.5） | 30.0% | **36.7%** | 2 例修正；低分是静默回退 Legacy 的成绩，非 v2 |
| 25/30/36 | — | — | 无变化 | 上次重算已覆盖，口径一致 |

重算范围限定为风险审查数据集（ds 9/20/23）：要素/日程/核验 run（23/24/27/28/29）评分器不同、ds=13 压力测试 artifact 全为 infraFailed 空壳、run 9 的 30 例 artifact 均无 findings（早期格式）——均不可重算并已在脚本中显式跳过。unscoreable case 保留官方值占位，run 级分母与官方口径一致。另：run 16 CR-023 与 run 18 CR-030 重算 1.0→0.0，系早期 v1 artifact 的 domainKey 旧词表与当前维度桶映射不对齐（引擎词表演进），非评分器回归（run 25 同 case 为 1.0）。

### 3.2 Golden 回归集（dataset 20，2 例）

> ⚠️ 已作废：run 33（标称 langgraph_v2）经 agent_run_trace 查证实际执行的是 Legacy 六阶段流水线（trace 为 TOOL_REQUESTED/PLAN_CREATED/REFLECTION，无 GRAPH_NODE），run 34 才是真 v1 图（18×GRAPH_NODE）。下表数据不能作为 v2 证据。golden 对照 runs 31/32 因评测叫停未执行（保持 QUEUED）。

| 用例 | v1（run 34） | 标称 v2（run 33，实际 Legacy，作废） |
|---|---|---|
| GD-RV-001 付款条款引用附件隐藏验收风险 | ✅ 命中高风险（recall 1.0） | ✅ 命中高风险（recall 1.0） |
| GD-RV-002 缺验收条款规则发现须带解释 | ✅ 命中高风险（recall 1.0） | ✅ 命中高风险（recall 1.0） |

（重跑前留空，重跑后填写正式对照表）

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
- **langgraph_v2 静默回退 Legacy（2026-08-14 16:51 发现）**：API 服务进程 02:09 启动时，v2 试点代码（12:21 提交）与 `dispatch_with_mode` 的 `langgraph_v2` 分支（15:26 提交）均不存在；老 dispatch 对未知 mode 走 `else → legacy`。经 UI 发起的 runs 33/35（标称 langgraph_v2）因此实际执行 Legacy 六阶段流水线——trace 证据：33/35 的用例 run 只有 TOOL_REQUESTED/PLAN_CREATED/REFLECTION 事件，34（langgraph）有 18×GRAPH_NODE。run 35 的 recall 30% 是 Legacy 在主回归集上的成绩，不是 v2。修复动作：重启 API 服务加载当前代码（新 dispatch 有 langgraph_v2 分支），重跑 runs 33/35。
- **限流信号量跨事件循环崩溃（18:15-18:30）**：首版限流用 asyncio.Semaphore，但 graph 节点经 `_run_async` 每次在新线程的新事件循环里调用 `retrieve_sync`，信号量绑定首个循环后拒绝后续调用，全部检索通道报 "bound to a different event loop"。已修复为 threading.Semaphore + run_in_executor 非阻塞 acquire（6239e4d），并补跨线程单测复现该拓扑。
- **限流未达提速预期（19:18-20:38 实测）**：window=3 限流消除了 embedding/reranker 超时风暴，但实测 v2 每例 739.8s（372-1182s），与限流前 616s 相比无改善、甚至更慢。**结论：并发劣化不是主瓶颈**——排队成本抵消了省下的超时税，真正的时间在 LLM 分析层（6 域分析 + OmissionAuditor + 两轮 reanalyze）与定向回补轮次本身。对照 v1（无定向回补轮次）每例仅 145.7s。
- **评测手动中止（20:38）**：用户因耗时叫停，run 30 于第 7/30 例处终止。DB 已落终态：第 7 例 agent_run 807 由心跳失联规则 FAILED；run 30 置 FAILED（current_step 注明手动中止），summary_json 回填 actualRuntimeEngine=langgraph/contract_review/v2（无 mismatch）与 partialMetrics（前 6 例）。runs 31/32 未执行，保持 QUEUED。
- **评分器维度词表不匹配（晚发现并修复，a95f5cf）**：`_risk_finding_matches` 的维度门禁把两套不对齐的词表硬比较——期望发现用 riskDimension（19 值），产出发现 riskDimension 全空、用 clauseType（8 值，其中 OTHER 占 104/364 并掩蔽具体 domainKey）与 domainKey（~110 值）。硬门禁把大量文本已命中的真匹配误杀：v1 官方 0.6167 系统性低估（纯文本重算 0.9667），难例 run 36 官方 0.0 同为误杀。修复：`_risk_dimension` 改 domainKey 优先 + 两侧统一桶映射（~40 项）；`_risk_finding_matches` 增加强文本旁路（shared≥8 且 containment≥0.5），弱通道仍受门禁保护（ACCEPTANCE/PAYMENT 守卫用例与附件描述巧合不受影响）。存量分数经 scripts/rescore_eval_high_recall.py 重算（只 UPDATE 存量行，未重跑），官方原值保留在 summary_json.officialHighRiskRecall。

---

## 4. 结论

**部分结论（6/30 例，2026-08-14 20:38 叫停后；召回口径经 a95f5cf 重算修正）**：

1. **召回**：重算后 v1 基线 0.9333（官方 0.6167 系评分器误杀，10/30 例修正），v1 真丢分只剩 4 例各 0.5。同 6 例上 v2 与 v1 持平 0.9167 不变。难例复测重算 0.8333：CR-008/CR-016 的 v1 丢分是评分器伪像（两引擎文本层面均完整命中），CR-018 是唯一真实差异（v1 命中「永久有效」漏「已为公众所知」，v2 恰好相反，各 0.5）。**"v2 在难例上提升召回"的假设未获支持：所谓难例并非真难，v1 文本层面本已找到；且 v2 的 6/30 部分评测未覆盖 v1 真实丢分的那 4 例。**
2. **双引用**：v2 在同 6 例上 +21%（0.3906 vs 0.3222），温和正向信号，与"首轮+定向证据 UNION"的设计预期一致。
3. **误报/结构**：两版 FPR=0、schema 100%，v2 的负向门禁没有引入新问题。
4. **耗时（否决项）**：v2 每例 12.3min，是 v1（2.4min）的 5.1 倍。限流已排除检索扇出并发为根因，主耗时在 LLM 分析层与定向回补轮次。**在耗时问题解决前，v2 不具备转默认条件。**
5. **Phase 4**：不放行，维持原计划（等 Phase 3 评测过线）。

后续方向（待用户决策，评测结论收尾前不动 v2 检索/分析逻辑）：
- 定向回补收敛性：两轮 targeted_retrieval + reanalyze 是 v2 与 v1 的最大结构性差异，也是 5× 耗时的主要来源；观察回补是否收敛、能否单轮化
- 若继续评测：runs 31/32（golden 对照）仍为 QUEUED，可直接驱动；run 30 需重建后从第 7 例续跑

评测执行方式备忘（供手动评测）：
- 评测驱动脚本 scripts/run_v2_evals.py / run_baseline_evals.py（独立进程、自带 RunRecovery 禁用、每例超时由 features caseTimeoutSeconds 控制）；
- 建行脚本 scripts/create_v2_eval_runs.py（QUEUED 行不再预填 started_at，首次触达打真实时间）；
- 运行观察 scripts/watch_v2_runs.py / watch_baseline_runs.py；
- run 30（v2，30 例）在旧 42-WU 架构下完成 12/30 例，状态 RUNNING@case13 残留——手动评测建议以压缩变体新开 run 对照，旧 run 30 数据仅作参考；
- API server 扫描器在修 900s 规则后，>15min 且持续心跳的 case 不会再被误杀。
