"""Tests for the common evidence harness (PRD Phase 2, 2026-08-14).

Covers the user's Phase 2 test requirements:

* Fake adapters for pure unit tests (no DB / ES / settings)
* first-round + targeted merge never loses the first round's evidence
* rerank-off degradation (pass-through reranker)
* ES-unavailable → observable fallback, other channels keep their evidence
* risk + intake graphs consume the same EvidenceBundle entry
* observation logs show per-round input / hit count / post-fusion count
* PRD §14-4: v1 nodes re-import the harness helpers (single implementation)
  with identical outputs — the v1 output-field contract must not move
"""

import asyncio

import pytest

from app.agent_runtime.harness.fakes import (
    FakeChannelAdapter,
    FakeReranker,
    fake_clause,
    fake_policy_item,
    fake_snapshot,
)
from app.agent_runtime.harness.models import default_retrieval_request
from app.agent_runtime.harness.observation import ObservabilityRecorder
from app.agent_runtime.harness.retrieval import (
    RetrievalOrchestrator,
    expand_parent_clauses,
    flatten_bundle,
    merge_bundles,
)


def _run(coro):
    return asyncio.run(coro)


# ─────────────────────────── orchestrator retrieval ─────────────────────────


def test_orchestrator_parallel_channels_rrf_and_pools():
    clause_3_1 = fake_clause(1, number="3.1", title="付款")
    clause_3_2 = fake_clause(2, number="3.2", title="发票")
    policy_1 = fake_policy_item(101, title="标准条款-发票")
    history_1 = {"sourceType": "HISTORICAL_FINDING", "sourceId": "HISTORICAL_FINDING:9",
                 "id": 9, "title": "历史决策", "snippet": "历史"}

    calls: list[tuple[str, str]] = []
    orchestrator = RetrievalOrchestrator(
        adapters=(
            FakeChannelAdapter("contract", [clause_3_1], hit_recorder=calls),
            FakeChannelAdapter("clause_type", [clause_3_2], hit_recorder=calls),
            FakeChannelAdapter("policy", [policy_1], hit_recorder=calls),
            FakeChannelAdapter("historical", [history_1], hit_recorder=calls),
        ),
        reranker=FakeReranker(),
    )
    snapshot = fake_snapshot()
    request = default_retrieval_request(
        1, snapshot, "wu-1", ["付款条件"],
        clause_types=["PAYMENT"],
    )
    bundle = _run(orchestrator.retrieve(snapshot, request))

    # every channel was called exactly once for the one query
    assert sorted(call[0] for call in calls) == ["clause_type", "contract", "historical", "policy"]
    # pools stay separate — contract hits never leak into policy pool
    assert [item["sourceId"] for item in bundle["contract_evidence"]] == [
        "CONTRACT_CLAUSE:1", "CONTRACT_CLAUSE:2",
    ]
    assert [item["sourceId"] for item in bundle["policy_evidence"]] == ["KB_DOCUMENT:101"]
    assert [item["sourceId"] for item in bundle["historical_evidence"]] == ["HISTORICAL_FINDING:9"]
    # per-round input / hit / post-fusion counts (acceptance surface)
    stats = bundle["retrieval_stats"]
    assert stats["queryVariantCount"] == 1
    assert stats["channelHitCounts"] == {"contract": 1, "clause_type": 1, "policy": 1, "historical": 1}
    assert stats["postFusionCounts"]["contract_evidence"] == 2
    assert stats["finalCounts"]["contract_evidence"] == 2


def test_merge_bundles_never_drops_first_round_evidence():
    primary = {
        "work_unit_id": "wu-1",
        "request_hash": "r1",
        "contract_evidence": [fake_clause(1, number="3.1"), fake_clause(2, number="3.2")],
        "policy_evidence": [fake_policy_item(101)],
        "historical_evidence": [],
        "counter_evidence": [],
        "retrieval_stats": {"round": 1, "queryVariantCount": 1},
        "warnings": [{"channel": "policy", "error": "timeout"}],
    }
    targeted = {
        "work_unit_id": "wu-1",
        "request_hash": "r2",
        "contract_evidence": [fake_clause(2, number="3.2"), fake_clause(3, number="3.2.1")],
        "policy_evidence": [],
        "historical_evidence": [],
        "counter_evidence": [fake_clause(4, number="3.2.2")],
        "retrieval_stats": {"round": 2, "queryVariantCount": 2},
        "warnings": [],
    }
    merged = merge_bundles(primary, targeted)
    assert [item["sourceId"] for item in merged["contract_evidence"]] == [
        "CONTRACT_CLAUSE:1", "CONTRACT_CLAUSE:2", "CONTRACT_CLAUSE:3",
    ]
    assert [item["sourceId"] for item in merged["counter_evidence"]] == ["CONTRACT_CLAUSE:4"]
    assert len(merged["retrieval_stats"]["rounds"]) == 2
    assert len(merged["warnings"]) == 1


def test_rerank_off_degradation_passthrough():
    hits = [fake_clause(1, number="3.1"), fake_clause(2, number="3.2")]
    orchestrator = RetrievalOrchestrator(
        adapters=(FakeChannelAdapter("contract", hits),),
        reranker=FakeReranker(method="KEYWORD_FALLBACK"),
    )
    bundle = _run(orchestrator.retrieve(
        fake_snapshot(), default_retrieval_request(1, fake_snapshot(), "wu-1", ["付款"]),
    ))
    assert len(bundle["contract_evidence"]) == 2
    assert all(item["rerankerMethod"] == "KEYWORD_FALLBACK" for item in bundle["contract_evidence"])


def test_es_unavailable_is_observable_and_other_channels_survive():
    policy_1 = fake_policy_item(101)
    orchestrator = RetrievalOrchestrator(
        adapters=(
            FakeChannelAdapter("contract", raise_exc=RuntimeError("ES index_not_found")),
            FakeChannelAdapter("policy", [policy_1]),
        ),
        reranker=FakeReranker(),
    )
    bundle = _run(orchestrator.retrieve(
        fake_snapshot(), default_retrieval_request(1, fake_snapshot(), "wu-1", ["付款"]),
    ))
    # the failure is recorded, not silent
    assert any(
        warning["channel"] == "contract" and "index_not_found" in warning["error"]
        for warning in bundle["warnings"]
    )
    # the surviving channel's evidence is intact
    assert [item["sourceId"] for item in bundle["policy_evidence"]] == ["KB_DOCUMENT:101"]
    assert bundle["contract_evidence"] == []
    # observation summary surfaces the warning
    summary = ObservabilityRecorder.bundle_summary(bundle)
    assert summary["warningCount"] == 1
    assert summary["warnings"][0]["channel"] == "contract"


def test_counter_evidence_pool_when_requested():
    main_hit = fake_clause(1, number="3.1", title="付款")
    calls: list[tuple[str, str]] = []

    def hits_for(query):
        return [main_hit] if "除外" not in query else [fake_clause(2, number="9.9", title="责任上限")]

    orchestrator = RetrievalOrchestrator(
        adapters=(
            FakeChannelAdapter("contract", hits_by_query={
                "付款条件": [main_hit],
                "付款条件 除外 但书 例外 前提 限制 豁免 以约定为准": [fake_clause(2, number="9.9", title="责任上限")],
                "与 付款条件 冲突的条款 特殊约定 专用条件": [],
            }, hit_recorder=calls),
        ),
        reranker=FakeReranker(),
    )
    snapshot = fake_snapshot()
    request = default_retrieval_request(
        1, snapshot, "wu-1", ["付款条件"], require_counter_evidence=True,
    )
    bundle = _run(orchestrator.retrieve(snapshot, request))
    assert len(calls) == 3  # base + 2 counter templates
    assert [item["sourceId"] for item in bundle["counter_evidence"]] == ["CONTRACT_CLAUSE:2"]
    assert bundle["retrieval_stats"]["counterQueryCount"] == 2


def test_parent_clause_expansion_from_snapshot_without_db():
    hit = fake_clause(3, number="3.2.1", title="发票类型")
    snapshot = fake_snapshot(clauses=[
        fake_clause(1, number="3.1", title="付款条款"),
        fake_clause(2, number="3.2", title="发票条款", content="父条款正文：发票开具要求"),
        fake_clause(3, number="3.2.1", title="发票类型"),
    ])
    expand_parent_clauses([hit], snapshot, clauses=snapshot["clauses"])
    parent = hit["parentClause"]
    assert parent["clauseNumber"] == "3.2"
    assert parent["title"] == "发票条款"
    assert "父条款正文" in parent["snippet"]


def test_request_hash_stable_and_snapshot_sensitive():
    snapshot = fake_snapshot(snapshot_hash="snap-a")
    a = default_retrieval_request(1, snapshot, "wu-1", ["付款"])
    b = default_retrieval_request(1, snapshot, "wu-1", ["付款"])
    from app.agent_runtime.harness.retrieval import _request_hash

    assert _request_hash(a) == _request_hash(b)
    other = default_retrieval_request(1, fake_snapshot(snapshot_hash="snap-b"), "wu-1", ["付款"])
    assert _request_hash(a) != _request_hash(other)


# ───────────────────── risk + intake share one retrieval entry ──────────────


class _ScriptedOrchestrator:
    def __init__(self, bundle):
        self._bundle = bundle
        self.calls = []

    def retrieve_sync(self, snapshot, request, *, clauses=None):
        self.calls.append((request, clauses))
        return self._bundle


def _shared_bundle():
    return {
        "work_unit_id": "wu-1",
        "request_hash": "r1",
        "contract_evidence": [fake_clause(1, number="3.1")],
        "policy_evidence": [fake_policy_item(101)],
        "historical_evidence": [],
        "counter_evidence": [],
        "retrieval_stats": {
            "queryVariantCount": 1,
            "channelHitCounts": {"contract": 1, "policy": 1},
            "postFusionCounts": {"contract_evidence": 1, "policy_evidence": 1},
            "finalCounts": {"contract_evidence": 1, "policy_evidence": 1},
        },
        "warnings": [],
    }


def test_risk_and_intake_graphs_consume_same_bundle(monkeypatch):
    bundle = _shared_bundle()

    # risk graph entry
    from app.agent_runtime.graph.nodes import retrieval as risk_retrieval
    from app.agent_runtime.harness import retrieval as harness_retrieval

    risk_orchestrator = _ScriptedOrchestrator(bundle)
    monkeypatch.setattr(harness_retrieval, "get_orchestrator", lambda: risk_orchestrator)

    risk_state = risk_retrieval.retrieve_domain_evidence({
        "subject_id": 1,
        "run_id": 1,
        "state_revision": 0,
        "domain_tasks": [{
            "domainKey": "price_payment_tax",
            "domainName": "价格付款税务",
            "queries": ["付款条件"],
            "requiredClauseTypes": ["PAYMENT"],
        }],
        "evidence_snapshot": fake_snapshot(),
        "contract_evidence_snapshot": [],
    })
    assert risk_state["domain_results"]["price_payment_tax"][0]["sourceId"] == "CONTRACT_CLAUSE:1"
    risk_obs = risk_state["observations"][0]
    # per-round input / hit / post-fusion counts are in the observation log
    assert risk_obs["output"]["queryVariantCount"] == 1
    assert risk_obs["output"]["channelHitCounts"] == {"contract": 1, "policy": 1}
    assert risk_obs["output"]["postFusionCounts"]["contract_evidence"] == 1
    assert risk_obs["toolName"] == "retrieveEvidenceBundle"

    # intake (element extraction) graph entry
    from app.agent_runtime.graph import contract_extraction

    intake_orchestrator = _ScriptedOrchestrator(bundle)
    monkeypatch.setattr(
        contract_extraction, "_extraction_orchestrator_instance", intake_orchestrator,
    )
    intake_state = contract_extraction.retrieve_element_evidence({
        "subject_id": 1,
        "run_id": 2,
        "state_revision": 0,
        "element_packs": [{"packKey": "payment", "packName": "付款要素", "queries": ["付款条件"]}],
        "evidence_snapshot": fake_snapshot(),
        "contract_evidence_snapshot": [],
    })
    assert intake_state["element_evidence"]["payment"][0]["sourceId"] == "CONTRACT_CLAUSE:1"
    intake_obs = intake_state["observations"][0]
    assert intake_obs["toolName"] == "retrieveEvidenceBundle"
    assert intake_obs["output"]["bundleStats"]["postFusionCounts"]["contract_evidence"] == 1

    # both went through one orchestrator-style entry, one call each
    assert len(risk_orchestrator.calls) == 1
    assert len(intake_orchestrator.calls) == 1
    assert risk_orchestrator.calls[0][1] == []  # risk passes the (empty) clause snapshot through
    assert risk_orchestrator.calls[0][0]["work_unit_id"] == "price_payment_tax"
    assert intake_orchestrator.calls[0][0]["work_unit_id"] == "payment"


def test_flatten_bundle_preserves_all_pools():
    bundle = _shared_bundle()
    flattened = flatten_bundle(bundle)
    assert [item["sourceId"] for item in flattened] == ["CONTRACT_CLAUSE:1", "KB_DOCUMENT:101"]


# ─────────────────────────── GroundingValidator ─────────────────────────────


def _candidate(**overrides):
    base = {
        "candidate_id": "c-1",
        "work_unit_id": "wu-1",
        "claim": "付款条件：验收后30日内支付",
        "contract_citation_ids": ["CONTRACT_CLAUSE:1"],
        "structured_value": {},
    }
    base.update(overrides)
    return base


def _bundle_with(contract=(), counter=()):
    return {
        "work_unit_id": "wu-1",
        "request_hash": "r1",
        "contract_evidence": list(contract),
        "policy_evidence": [],
        "historical_evidence": [],
        "counter_evidence": list(counter),
        "retrieval_stats": {"counterQueryCount": 0},
        "warnings": [],
    }


def test_validator_citation_exists_and_from_snapshot():
    from app.agent_runtime.harness.validation import GroundingValidator

    snapshot = fake_snapshot()
    clause = fake_clause(1, number="3.1", title="付款条款", content="付款应在验收后30日内完成")
    bundle = _bundle_with(contract=[clause])
    validator = GroundingValidator()

    ok = validator.validate([_candidate()], bundle, snapshot)[0]
    assert ok["verdict"] == "PASS", ok

    # citation id not in the bundle → REJECT
    ghost = validator.validate(
        [_candidate(contract_citation_ids=["CONTRACT_CLAUSE:999"])], bundle, snapshot,
    )[0]
    assert ghost["verdict"] == "REJECT"
    assert any(check["check"] == "CITATION_EXISTS" and not check["ok"] for check in ghost["checks"])

    # citation from another document version → REJECT (not current snapshot)
    foreign = fake_clause(7, number="3.1", document_id=2)
    foreign_bundle = _bundle_with(contract=[foreign])
    alien = validator.validate(
        [_candidate(contract_citation_ids=["CONTRACT_CLAUSE:7"])], foreign_bundle, snapshot,
    )[0]
    assert alien["verdict"] == "REJECT"
    assert any(check["check"] == "CITATION_FROM_SNAPSHOT" and not check["ok"] for check in alien["checks"])


def test_validator_value_consistency_against_confirmed_intake():
    from app.agent_runtime.harness.validation import GroundingValidator

    snapshot = fake_snapshot(confirmed_intake={"fields": {"amount": 100000, "currency": "CNY"}})
    clause = fake_clause(1, number="3.1", content="合同总价为人民币十万元")
    bundle = _bundle_with(contract=[clause])
    validator = GroundingValidator()

    conflicting = validator.validate(
        [_candidate(structured_value={"amount": 300000})], bundle, snapshot,
    )[0]
    assert conflicting["verdict"] == "REJECT"
    assert any(
        check["check"] == "VALUE_CONSISTENCY" and check.get("verdict") == "fatal"
        for check in conflicting["checks"]
    )

    matching = validator.validate(
        [_candidate(structured_value={"amount": 100000})], bundle, snapshot,
    )[0]
    assert matching["verdict"] in {"PASS", "NEED_MORE_EVIDENCE"}  # negative claim bar may still apply


def test_validator_negative_claim_bar_requires_minimum_evidence_and_counter_search():
    from app.agent_runtime.harness.validation import GroundingValidator

    snapshot = fake_snapshot()
    validator = GroundingValidator(policy={"min_negative_contract_evidence": 3})

    thin = _bundle_with(contract=[fake_clause(1, number="3.1")])  # only 1 hit, no counter search
    outcome = validator.validate([_candidate(negative_claim=True)], thin, snapshot)[0]
    assert outcome["verdict"] == "NEED_MORE_EVIDENCE"
    reasons = {need["reason_code"] for need in outcome["evidence_needs"]}
    assert "NEGATIVE_CLAIM_NOT_PROVEN" in reasons
    assert "POSSIBLE_COUNTER_EVIDENCE" in reasons

    rich = _bundle_with(
        contract=[fake_clause(i, number=f"3.{i}") for i in range(1, 5)],
        counter=[fake_clause(9, number="9.9")],
    )
    rich["retrieval_stats"] = {"counterQueryCount": 2}
    outcome = validator.validate([_candidate(negative_claim=True)], rich, snapshot)[0]
    assert outcome["verdict"] in {"PASS", "DOWNGRADE_CONFIDENCE"}
    assert not any(
        check["check"] == "NEGATIVE_CLAIM_BAR" and not check["ok"]
        for check in outcome["checks"]
    )


def test_observation_summary_has_round_counts():
    bundle = _shared_bundle()
    summary = ObservabilityRecorder.bundle_summary(bundle)
    assert summary["queryVariantCount"] == 1
    assert summary["channelHitCounts"] == {"contract": 1, "policy": 1}
    assert summary["postFusionCounts"]["contract_evidence"] == 1
    assert summary["finalCounts"]["contract_evidence"] == 1


# ─────────────────────────── provider pressure gate ──────────────────────────


def test_fanout_concurrency_stays_under_provider_safe_limit():
    """The (query × channel) fan-out must never exceed _CHANNEL_FANOUT_LIMIT
    concurrent adapter calls — the embedding/reranker provider degrades
    sharply under bursts (2026-08-14 incident)."""
    from app.agent_runtime.harness.retrieval import ChannelResult, _CHANNEL_FANOUT_LIMIT

    active = 0
    peak = 0

    class _SlowContractAdapter:
        channel_key = "contract"

        async def retrieve(self, case_id: int, query: str,
                           arguments: dict) -> ChannelResult:
            nonlocal active, peak
            active += 1
            peak = max(peak, active)
            try:
                await asyncio.sleep(0.02)  # hold the gate slot
            finally:
                active -= 1
            return ChannelResult({"hits": [], "stats": {}, "warnings": []})

    async def exercise():
        orchestrator = RetrievalOrchestrator(
            adapters=(
                _SlowContractAdapter(),
                FakeChannelAdapter("clause_type", []),
                FakeChannelAdapter("policy", []),
                FakeChannelAdapter("historical", []),
            ),
            reranker=FakeReranker(),
        )
        request = default_retrieval_request(
            1, fake_snapshot(), "wu-1",
            [f"查询意图{i}" for i in range(4)],
            require_counter_evidence=True,  # +8 contract calls from counter templates
        )
        bundle = await orchestrator.retrieve(fake_snapshot(), request)
        assert bundle is not None
        # 20 gated calls ran; concurrency never crossed the provider-safe limit
        # but did overlap (a fully serialised fan-out would also be a bug).
        assert 2 <= peak <= _CHANNEL_FANOUT_LIMIT

    _run(exercise())


def test_fanout_gate_survives_cross_loop_usage():
    """Production topology: graph nodes call retrieve_sync from different
    threads, each running its own fresh event loop (see _run_async). The gate
    must keep working across loops — an asyncio.Semaphore would bind to the
    first loop and reject every later call (2026-08-14 regression)."""
    import threading

    from app.agent_runtime.harness.retrieval import (
        ChannelResult,
        _CHANNEL_FANOUT_LIMIT,
    )

    active = 0
    peak = 0

    class _SlowContractAdapter:
        channel_key = "contract"

        async def retrieve(self, case_id: int, query: str,
                           arguments: dict) -> ChannelResult:
            nonlocal active, peak
            active += 1
            peak = max(peak, active)
            try:
                await asyncio.sleep(0.05)  # hold the gate slot
            finally:
                active -= 1
            return ChannelResult({"hits": [], "stats": {}, "warnings": []})

    orchestrator = RetrievalOrchestrator(
        adapters=(
            _SlowContractAdapter(),
            FakeChannelAdapter("clause_type", []),
            FakeChannelAdapter("policy", []),
            FakeChannelAdapter("historical", []),
        ),
        reranker=FakeReranker(),
    )
    request = default_retrieval_request(
        1, fake_snapshot(), "wu-1", ["查询意图"],
        require_counter_evidence=True,
    )
    results: list[bool] = []
    errors: list[BaseException] = []

    def worker():
        try:
            bundle = orchestrator.retrieve_sync(fake_snapshot(), request)
            results.append(bool(bundle))
        except BaseException as exc:  # noqa: BLE001 - gather any loop-binding error
            errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(3)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors, f"cross-loop gate failed: {errors}"
    assert len(results) == 3
    assert peak <= _CHANNEL_FANOUT_LIMIT


# ─────────────── PRD §14-4: v1 re-imports the harness (equivalence) ─────────


def test_v1_nodes_reimport_harness_helpers_as_single_implementation():
    """The mirror copies in graph/nodes/retrieval.py must now BE the harness
    functions (identity, not just behavioral equality) — otherwise a future
    edit to one side silently forks the two implementations again."""
    from app.agent_runtime.graph.nodes import retrieval as v1_retrieval
    from app.agent_runtime import harness as harness_pkg

    assert v1_retrieval._run_async is harness_pkg.retrieval._run_async
    assert v1_retrieval._normalize_evidence is harness_pkg.retrieval._normalize_hit


def test_v1_validation_prefixes_are_the_harness_vocabulary():
    from app.agent_runtime.graph.nodes import validation as v1_validation
    from app.agent_runtime.harness.models import VALID_CITATION_PREFIXES

    assert v1_validation._VALID_PREFIXES is VALID_CITATION_PREFIXES


def test_v1_deduplicate_evidence_matches_old_algorithm_exactly():
    """Pin the exact pre-extraction behavior of graph/nodes/retrieval.py
    ``_deduplicate_evidence``: normalize → first-wins by sourceId → cap.
    Raw items here are the shapes ContractStore used to hand v1 nodes."""
    from app.agent_runtime.graph.nodes.retrieval import _deduplicate_evidence

    items = [
        {"clauseId": 1, "content": "第一条", "pageNumber": 3, "sourceType": "CONTRACT_CLAUSE"},
        {"clauseId": 1, "content": "第一条重复", "sourceType": "CONTRACT_CLAUSE"},  # dupe → dropped
        {"id": 7, "chunkId": 7, "snippet": "知识条目", "sourceType": "KB_CHUNK"},
        {"sourceType": "HISTORICAL_FINDING", "id": 9, "fullText": "历史结论"},
        {},  # no id → empty sourceId → dropped by the old algorithm too
        {"clauseId": 2, "content": "第二条"},
    ]
    result = _deduplicate_evidence(items)

    assert [item["sourceId"] for item in result] == [
        "CONTRACT_CLAUSE:1", "KB_CHUNK:7", "HISTORICAL_FINDING:9", "CONTRACT_CLAUSE:2",
    ]
    # old normalization contract: clauseText from content, snippet filled,
    # page copied from pageNumber, first occurrence wins
    assert result[0]["clauseText"] == "第一条"
    assert result[0]["snippet"] == "第一条"
    assert result[0]["page"] == 3
    assert result[1]["snippet"] == "知识条目"
    assert result[2]["clauseText"] == "历史结论"


def test_v1_deduplicate_evidence_caps_at_limit():
    from app.agent_runtime.graph.nodes.retrieval import _deduplicate_evidence

    items = [
        {"clauseId": i, "content": f"条款{i}", "sourceType": "CONTRACT_CLAUSE"}
        for i in range(1, 6)
    ]
    assert len(_deduplicate_evidence(items, limit=2)) == 2
    assert len(_deduplicate_evidence(items, limit=18)) == 5
    assert len(_deduplicate_evidence(items)) == 5  # default limit 18 unchanged


# ─────────────── PRD Phase 4 task 6: runtime fakes self-test ─────────────────


def test_fake_llm_scripts_by_exact_prompt_and_records():
    from app.agent_runtime.harness.fakes import FakeLLM

    llm = FakeLLM(
        {"起草一份报告": '{"reportType": "X"}'},
        fallback='{"reportType": "FALLBACK"}',
    )
    assert llm.complete_json("起草一份报告") == {"reportType": "X"}
    assert llm.complete_json("别的提示") == {"reportType": "FALLBACK"}
    assert llm.calls == ["起草一份报告", "别的提示"]
    # exact-prompt keying means callers can script per-round replies
    llm.complete("起草一份报告")
    assert llm.calls.count("起草一份报告") == 2

    def exercise():
        with pytest.raises(ValueError):
            FakeLLM(fallback="not-json").complete_json("任意提示")

    exercise()


def test_fake_persistence_records_runtime_contract_writes():
    from app.agent_runtime.harness.fakes import FakePersistence

    async def exercise():
        store = FakePersistence(default_status="CREATED")
        assert (await store.get_run(9))["status"] == "CREATED"
        await store.update_run(9, status="COMPLETED")
        await store.heartbeat(9)
        await store.set_runtime_metadata(
            9, runtime_engine="langgraph", graph_name="g", graph_version="v2",
            model="m", prompt_version="p",
        )
        assert store.updates == [(9, {"status": "COMPLETED"})]
        assert store.heartbeats == [9]
        assert store.metadata[0] == (9, {
            "runtime_engine": "langgraph", "graph_name": "g",
            "graph_version": "v2", "model": "m", "prompt_version": "p",
        })
        # raise_on models transient persistence failures
        with pytest.raises(RuntimeError):
            await FakePersistence(raise_on="heartbeat").heartbeat(1)

    _run(exercise())
