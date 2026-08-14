"""Tests for the contract_review v2 pilot graph (PRD Phase 3, §15).

Deterministic nodes only — no DB, no ES, no LLM:

* fixed domain baseline (§15.2) — detailed sub-checks share six bounded
  WorkUnits with at most two query intents and the five grounding checks;
* adjacent-clause expansion from the snapshot catalog (§15.3(5));
* counter-evidence classification (EXCEPTION/LIMITATION/EXEMPTION/CONFLICT);
* candidate merge (LLM findings + unmatched deterministic rules);
* negative-conclusion gate — failing preconditions soften the claim to
  "当前证据范围内暂未确认";
* OmissionAuditor need generation (no evidence / evidence-but-no-findings /
  unused catalog clauses) and budget routing;
* targeted retrieval unions evidence and only re-analyzes its targets.
"""

from __future__ import annotations

from copy import deepcopy

import pytest

from app.agent_runtime.graph import review_v2
from app.agent_runtime.harness.fakes import fake_clause, fake_policy_item, fake_snapshot
from app.agent_runtime.harness import retrieval as harness_retrieval
from app.services import llm_service as llm_module


class _FailingLLM:
    """Deterministic LLM outage — every node must degrade to rule fallback."""

    def plan_contract_risk_domains(self, *args, **kwargs):
        raise RuntimeError("no LLM in tests")

    def analyze_contract_risk_domain(self, *args, **kwargs):
        raise RuntimeError("no LLM in tests")


@pytest.fixture(autouse=True)
def _no_llm(monkeypatch):
    monkeypatch.setattr(llm_module, "LLMService", _FailingLLM)


class _ScriptedOrchestrator:
    def __init__(self, bundle):
        self._bundle = bundle
        self.calls = []

    def retrieve_sync(self, snapshot, request, *, clauses=None):
        self.calls.append(request)
        bundle = deepcopy(self._bundle)
        bundle["work_unit_id"] = request.get("work_unit_id")
        bundle["request_hash"] = request.get("request_hash")
        return bundle


def _base_state(**overrides):
    snapshot = fake_snapshot()
    state = {
        "subject_id": 1,
        "run_id": 1,
        "state_revision": 0,
        "evidence_snapshot": snapshot,
        "contract_evidence_snapshot": [],
        "case_snapshot": {},
        "extraction_snapshot": {"elements": []},
        "document_snapshot": [{"documentId": 1}],
        "observations": [],
        "domain_tasks": [],
        "rule_findings": [],
        "coverage": {},
    }
    state.update(overrides)
    return state


def _bundle(contract=(), policy=(), counter=(), *, stats=None):
    base_stats = {
        "round": 1,
        "queryVariantCount": 2,
        "counterQueryCount": 0,
        "channelHitCounts": {"contract": len(contract), "policy": len(policy)},
        "postFusionCounts": {"contract_evidence": len(contract)},
        "finalCounts": {"contract_evidence": len(contract)},
    }
    if stats:
        base_stats.update(stats)
    return {
        "work_unit_id": "wu",
        "request_hash": "r1",
        "contract_evidence": list(contract),
        "policy_evidence": list(policy),
        "historical_evidence": [],
        "counter_evidence": list(counter),
        "retrieval_stats": base_stats,
        "warnings": [],
    }


def _plan_result(monkeypatch=None):
    return review_v2.plan_work_units(_base_state())


def _wu(work_unit_id="price_payment_tax.wu_a", *, label="付款条件",
         intents=("付款前提 付款条件", "付款触发 先票后款"), clause_types=("PAYMENT",)):
    return {
        "work_unit_id": work_unit_id,
        "label": label,
        "domainKey": work_unit_id.split(".", 1)[0],
        "domainName": "价款付款税务",
        "objective": f"检查“{label}”在合同中的约定",
        "priority": "HIGH",
        "query_intents": list(intents),
        "required_clause_types": list(clause_types),
        "negative_claim_allowed": True,
    }


# ─────────────────────────── plan_work_units (§15.2) ─────────────────────────


def test_plan_work_units_fixed_baseline_table():
    result = _plan_result()
    work_units = result["work_units"]
    assert len(work_units) == 6

    ids = {unit["work_unit_id"] for unit in work_units}
    assert len(ids) == 6  # unique
    assert "price_payment_tax" in ids
    assert "scope_delivery_acceptance" in ids
    assert "confidentiality_data_ip" in ids

    for unit in work_units:
        assert 1 <= len(unit["query_intents"]) <= 2
        assert unit["required_clause_types"]
        assert unit["priority"] in {"HIGH", "MEDIUM", "LOW"}
        assert unit["negative_claim_allowed"] is True
        assert unit["category"] == "risk_domain"
        assert unit["sub_check_items"]
        assert set(unit["required_checks"]) >= {
            "CITATION_EXISTS", "CITATION_FROM_SNAPSHOT", "CLAIM_SUPPORTED",
            "VALUE_CONSISTENCY", "NEGATIVE_CLAIM_BAR",
        }

    # v1-compatible domain_tasks derived from the same baseline
    domain_tasks = result["domain_tasks"]
    assert len(domain_tasks) == 6
    assert all(task["source"] == "V2_WORK_UNITS" for task in domain_tasks)
    assert result["retry_budget"] == 2
    assert result["observations"][0]["toolName"] == "planWorkUnits"
    output = result["observations"][0]["output"]
    assert output["workUnitCount"] == 6
    assert output["baselineWorkUnitCount"] == 6
    assert output["fixedItemCount"] == 42
    assert output["dynamicCount"] == 0
    assert output["maxWorkUnitCount"] == 10
    assert sum(len(unit["sub_check_items"]) for unit in work_units) == 42


def test_plan_work_units_dynamic_domains_bounded(monkeypatch):
    class _DynamicLLM(_FailingLLM):
        def plan_contract_risk_domains(self, *args, **kwargs):
            return {"domains": [
                {
                    "domainKey": f"custom {i}",
                    "domainName": f"定制领域{i}",
                    "objective": "检查定制风险",
                    "queries": [f"查询{i}A", f"查询{i}B"],
                }
                for i in range(5)  # capped at 4
            ]}

    monkeypatch.setattr(llm_module, "LLMService", _DynamicLLM)
    result = _plan_result()
    dynamic = [unit for unit in result["work_units"]
               if unit["work_unit_id"].split(".")[-1] == "dynamic"]
    assert len(dynamic) == 4
    assert len(result["work_units"]) == 10
    assert all(1 <= len(unit["query_intents"]) <= 2 for unit in dynamic)
    assert dynamic[0]["query_intents"] == ["查询0A", "查询0B"]
    # key normalization strips whitespace
    assert dynamic[0]["work_unit_id"] == "custom_0.dynamic"
    assert result["observations"][0]["output"]["dynamicCount"] == 4


# ─────────────────────────── build_contract_map ──────────────────────────────


def test_build_contract_map_from_inventory_and_snapshot():
    state = _base_state(observations=[{
        "callId": "graph-inventory-1",
        "planStepId": "clause_inventory",
        "toolName": "listClauseInventory",
        "output": {"inventory": {"clauseTypes": {"PAYMENT": 5, "LIABILITY": 3}}},
        "status": "DONE",
    }])
    result = review_v2.build_contract_map(state)
    contract_map = result["contract_map"]
    assert contract_map["clauseCatalogCount"] == 3
    assert contract_map["documentCount"] == 1
    assert contract_map["attachmentsChecked"] is True
    assert contract_map["domains"]["price_payment_tax"]["requiredClauseTypes"] == ["PAYMENT"]
    assert contract_map["domains"]["price_payment_tax"]["clauseCount"] == 5


# ─────────────────────── retrieve_evidence_for_work_units ────────────────────


def test_retrieve_per_work_unit_and_domain_aggregation(monkeypatch):
    clause = fake_clause(1, number="3.1", title="付款条款")
    policy = fake_policy_item(101)
    orchestrator = _ScriptedOrchestrator(_bundle(contract=[clause], policy=[policy]))
    monkeypatch.setattr(harness_retrieval, "get_orchestrator", lambda: orchestrator)

    units = [_wu("price_payment_tax.wu_a"), _wu("price_payment_tax.wu_b", label="调价")]
    state = _base_state(work_units=units)
    result = review_v2.retrieve_evidence_for_work_units(state)

    assert len(orchestrator.calls) == 2
    # per-WU bundles, per-WU work_unit_id
    assert set(result["evidence_bundles_by_work_unit"]) == {"price_payment_tax.wu_a", "price_payment_tax.wu_b"}
    for request in orchestrator.calls:
        assert request["require_counter_evidence"] is True
        assert request["final_limit"] == 10
        assert len(request["query_variants"]) >= 2
    # round tagged into the bundle stats
    assert result["evidence_bundles_by_work_unit"]["price_payment_tax.wu_a"]["retrieval_stats"]["round"] == 1
    # v1-compatible flat domain view — union deduped by sourceId
    domain_flat = result["domain_results"]["price_payment_tax"]
    assert [item["sourceId"] for item in domain_flat] == ["CONTRACT_CLAUSE:1", "KB_DOCUMENT:101"]
    assert result["retrieval_validation"]["price_payment_tax"]["evidenceCount"] == 2
    assert result["retrieval_validation"]["price_payment_tax"]["mode"] == "MULTI_CHANNEL"
    assert result["observations"][0]["toolName"] == "retrieveEvidenceBundle"
    assert result["observations"][0]["output"]["workUnitCount"] == 2


def test_adjacent_clause_expansion_from_catalog():
    snapshot = fake_snapshot(clauses=[
        fake_clause(1, number="3.1", title="付款条款"),
        fake_clause(2, number="3.2", title="发票条款"),
        fake_clause(3, number="3.2.1", title="发票类型"),
        fake_clause(4, number="3.2.2", title="发票税率"),
        fake_clause(5, number="3.2.3", title="开票要求"),
        fake_clause(6, number="3.2.4", title="发票送达"),
    ])
    hit = fake_clause(4, number="3.2.2", title="发票税率")
    attached = review_v2._expand_adjacent_clauses([hit], snapshot)
    assert attached == 1
    neighbours = [item["clauseNumber"] for item in hit["adjacentClauses"]]
    assert neighbours == ["3.2.1", "3.2.3", "3.2.4"]  # ±2 siblings, ordered
    assert all(item.get("clauseId") for item in hit["adjacentClauses"])


# ─────────────────────── counter-evidence analysis ──────────────────────────


def test_counter_classification_markers():
    assert review_v2._classify_counter_hit(fake_clause(1, number="9.1", title="付款条件除外")) == "EXCEPTION"
    assert review_v2._classify_counter_hit(fake_clause(2, number="9.2", title="赔偿责任上限")) == "LIMITATION"
    assert review_v2._classify_counter_hit(fake_clause(3, number="9.3", title="免责声明")) == "EXEMPTION"
    assert review_v2._classify_counter_hit(fake_clause(4, number="9.4", title="条款冲突时以本合同为准")) == "CONFLICT"
    assert review_v2._classify_counter_hit(fake_clause(5, number="9.5", title="其他约定")) == "OTHER"


def test_analyze_counter_evidence_annotates_findings():
    units = [_wu("price_payment_tax.wu_a")]
    counter = [
        fake_clause(9, number="9.1", title="付款条件除外"),
        fake_clause(10, number="9.2", title="赔偿限额另行约定"),
    ]
    state = _base_state(
        work_units=units,
        evidence_bundles_by_work_unit={
            "price_payment_tax.wu_a": _bundle(contract=[fake_clause(1, number="3.1")], counter=counter),
        },
        findings_by_work_unit={
            "price_payment_tax.wu_a": [{"findingKey": "f1", "title": "付款条件未约定"}],
        },
    )
    result = review_v2.analyze_counter_evidence(state)
    entries = result["counter_analysis_by_work_unit"]["price_payment_tax.wu_a"]
    assert [entry["classification"] for entry in entries] == ["EXCEPTION", "LIMITATION"]
    finding = result["findings_by_work_unit"]["price_payment_tax.wu_a"][0]
    assert finding["counterEvidenceCount"] == 2
    assert finding["counterEvidence"][0]["classification"] == "EXCEPTION"


# ─────────────────────────── merge candidates ───────────────────────────────


def test_merge_candidates_keeps_unmatched_rules():
    units = [_wu("price_payment_tax.wu_a", clause_types=("PAYMENT",))]
    llm_finding = {
        "findingKey": "f1", "title": "付款条件：验收后30日内支付",
        "contractCitationIds": ["CONTRACT_CLAUSE:1"], "structuredValue": {},
    }
    rule_payment = {
        "ruleKey": "RULE_PAY_001", "ruleTitle": "付款条款必须明确", "clauseType": "PAYMENT",
        "contractCitationIds": ["CONTRACT_CLAUSE:1"], "description": "付款条件需明确",
    }
    rule_liability = {
        "ruleKey": "RULE_LIAB_001", "ruleTitle": "责任上限检查", "clauseType": "LIABILITY",
    }
    state = _base_state(
        work_units=units,
        findings_by_work_unit={"price_payment_tax.wu_a": [llm_finding]},
        rule_findings=[rule_payment, rule_liability],
    )
    result = review_v2.merge_candidates(state)
    candidates = result["merged_candidates_by_work_unit"]["price_payment_tax.wu_a"]
    assert len(candidates) == 2  # LLM + unmatched PAYMENT rule; LIABILITY rule excluded
    assert {candidate["source"] for candidate in candidates} == {"LLM", "RULE"}
    rule_candidate = next(c for c in candidates if c["source"] == "RULE")
    assert rule_candidate["candidate_id"].startswith("price_payment_tax.wu_a:r")
    assert rule_candidate["negative_claim"] is False


def test_no_evidence_work_unit_takes_deterministic_absence_path():
    units = [_wu("price_payment_tax.wu_a")]
    state = _base_state(
        work_units=units,
        evidence_bundles_by_work_unit={"price_payment_tax.wu_a": _bundle()},
        rule_findings=[],
    )
    result = review_v2.analyze_work_unit_risks(state)
    findings = result["findings_by_work_unit"]["price_payment_tax.wu_a"]
    assert len(findings) == 1
    finding = findings[0]
    assert "未约定" in finding["title"]
    assert finding["negativeClaim"] is True  # triggers the §15.3 gate downstream
    assert finding["evidenceStatus"] == "MISSING"
    assert finding["contractCitationIds"] == []
    obs = next(o for o in result["observations"]
               if o["planStepId"] == "analyze_price_payment_tax.wu_a")
    assert obs["output"]["status"] == "DETERMINISTIC_NO_EVIDENCE"  # no LLM call


def test_validate_gate_only_path_softens_without_citations():
    units = [_gate_work_unit()]
    bundle = _bundle(  # zero contract hits — absence conclusion
        stats={"counterQueryCount": 0, "parentExpansionCount": 0, "adjacentExpansionCount": 0},
    )
    candidate = {
        "candidate_id": "price_payment_tax.wu_a:f1",
        "work_unit_id": "price_payment_tax.wu_a",
        "claim": "付款条件未约定",
        "contract_citation_ids": [],
        "structured_value": {},
        "negative_claim": True,
        "finding": {"findingKey": "f1", "title": "付款条件未约定",
                    "contractCitationIds": [], "structuredValue": {}},
    }
    state = _base_state(
        work_units=units,
        evidence_bundles_by_work_unit={"price_payment_tax.wu_a": bundle},
        merged_candidates_by_work_unit={"price_payment_tax.wu_a": [candidate]},
        contract_map={"attachmentsChecked": True, "documentCount": 1},
    )
    result = review_v2.validate_grounding(state)
    assert len(result["validated_findings"]) == 1  # not dropped despite zero citations
    finding = result["validated_findings"][0]
    assert finding["negativeConclusionSoftened"] is True
    assert finding["claim"].startswith("当前证据范围内暂未确认")
    assert result["negative_conclusion_checks"][0]["validationPath"] == "GATE_ONLY"
    codes = {need["reason_code"] for need in result["evidence_needs"]}
    assert "NEGATIVE_CLAIM_NOT_PROVEN" in codes
    assert "POSSIBLE_COUNTER_EVIDENCE" in codes


def test_validate_gate_only_path_passes_when_all_preconditions_hold():
    units = [_gate_work_unit()]
    bundle = _bundle(
        stats={"counterQueryCount": 2, "parentExpansionCount": 1, "adjacentExpansionCount": 1},
    )
    candidate = {
        "candidate_id": "price_payment_tax.wu_a:f1",
        "work_unit_id": "price_payment_tax.wu_a",
        "claim": "付款条件未约定",
        "contract_citation_ids": [],
        "structured_value": {},
        "negative_claim": True,
        "finding": {"findingKey": "f1", "title": "付款条件未约定",
                    "contractCitationIds": [], "structuredValue": {}},
    }
    state = _base_state(
        work_units=units,
        evidence_bundles_by_work_unit={"price_payment_tax.wu_a": bundle},
        merged_candidates_by_work_unit={"price_payment_tax.wu_a": [candidate]},
        contract_map={"attachmentsChecked": True, "documentCount": 1},
    )
    result = review_v2.validate_grounding(state)
    finding = result["validated_findings"][0]
    assert finding["validationVerdict"] == "PASS"
    assert "negativeConclusionSoftened" not in finding
    assert result["negative_conclusion_checks"][0]["passed"] is True


# ─────────────────────── negative-conclusion gate (§15.3) ───────────────────


def _gate_work_unit():
    return _wu("price_payment_tax.wu_a", intents=("付款前提 付款条件", "付款触发 先票后款"))


def test_negative_gate_all_preconditions_pass():
    snapshot = fake_snapshot()
    work_unit = _gate_work_unit()
    bundle = _bundle(
        contract=[fake_clause(1, number="3.1")],
        stats={"counterQueryCount": 2, "parentExpansionCount": 1, "adjacentExpansionCount": 1},
    )
    contract_map = {"attachmentsChecked": True, "documentCount": 1}
    passed, checks = review_v2._negative_gate(work_unit, bundle, contract_map, [], snapshot)
    assert passed is True
    assert {check["check"] for check in checks} == {
        "CATALOG_LOADED", "SYNONYM_QUERIES", "REVERSE_EXPRESSION_QUERIES",
        "CLAUSE_TYPE_FILTER", "PARENT_CLAUSE_CHECKED", "ADJACENT_CLAUSE_CHECKED",
        "ATTACHMENTS_CHECKED", "NO_CRITICAL_CHANNEL_FAILURE", "AUDITOR_NO_COUNTER_EVIDENCE",
    }
    assert all(check["ok"] for check in checks)


def test_negative_gate_fails_on_thin_evidence_and_counter_hits():
    snapshot = fake_snapshot()
    work_unit = _gate_work_unit()
    thin = _bundle(contract=[fake_clause(1, number="3.1")])  # no counter queries, no expansions
    contract_map = {"attachmentsChecked": False, "documentCount": 0}
    counter_entries = [{"classification": "EXCEPTION"}]
    passed, checks = review_v2._negative_gate(work_unit, thin, contract_map, counter_entries, snapshot)
    assert passed is False
    failed = {check["check"] for check in checks if not check["ok"]}
    assert {"REVERSE_EXPRESSION_QUERIES", "PARENT_CLAUSE_CHECKED",
            "ADJACENT_CLAUSE_CHECKED", "ATTACHMENTS_CHECKED",
            "AUDITOR_NO_COUNTER_EVIDENCE"} <= failed


def test_validate_grounding_softens_negative_claim_on_gate_failure():
    units = [_gate_work_unit()]
    clause = fake_clause(1, number="3.1", title="付款条款")
    bundle = _bundle(contract=[clause])  # 1 hit, counterQueryCount 0 → gate must fail
    candidates = [{
        "candidate_id": "price_payment_tax.wu_a:f1",
        "work_unit_id": "price_payment_tax.wu_a",
        "claim": "付款条件未约定",
        "contract_citation_ids": ["CONTRACT_CLAUSE:1"],
        "structured_value": {},
        "negative_claim": True,
        "finding": {"findingKey": "f1", "title": "付款条件未约定",
                    "contractCitationIds": ["CONTRACT_CLAUSE:1"], "structuredValue": {}},
    }]
    state = _base_state(
        work_units=units,
        evidence_bundles_by_work_unit={"price_payment_tax.wu_a": bundle},
        merged_candidates_by_work_unit={"price_payment_tax.wu_a": candidates},
        contract_map={"attachmentsChecked": True, "documentCount": 1},
    )
    result = review_v2.validate_grounding(state)
    # the candidate survives but is softened, never silently dropped
    validated = result["validated_findings"]
    assert len(validated) == 1
    finding = validated[0]
    assert finding["negativeConclusionSoftened"] is True
    assert finding["claim"].startswith("当前证据范围内暂未确认")
    assert finding["needsMoreEvidence"] is True
    checks = result["negative_conclusion_checks"]
    assert len(checks) == 1
    assert checks[0]["passed"] is False
    assert checks[0]["workUnitId"] == "price_payment_tax.wu_a"


def test_validate_grounding_drops_rejected_candidates():
    units = [_gate_work_unit()]
    clause = fake_clause(1, number="3.1", title="付款条款")
    bundle = _bundle(contract=[clause])
    ghost = {
        "candidate_id": "price_payment_tax.wu_a:f9",
        "work_unit_id": "price_payment_tax.wu_a",
        "claim": "付款条件：验收后30日内支付",
        "contract_citation_ids": ["CONTRACT_CLAUSE:999"],  # not in bundle / snapshot
        "structured_value": {},
        "negative_claim": False,
        "finding": {"findingKey": "f9", "title": "付款条件：验收后30日内支付"},
    }
    state = _base_state(
        work_units=units,
        evidence_bundles_by_work_unit={"price_payment_tax.wu_a": bundle},
        merged_candidates_by_work_unit={"price_payment_tax.wu_a": [ghost]},
    )
    result = review_v2.validate_grounding(state)
    assert result["validated_findings"] == []
    assert result["validation_by_work_unit"]["price_payment_tax.wu_a"]["acceptedCount"] == 0


# ─────────────────────────── omission audit + routing ───────────────────────


def _audit_state(budget=2):
    units = [_wu("price_payment_tax.wu_a"), _wu("price_payment_tax.wu_b", label="调价")]
    clause = fake_clause(1, number="3.1", title="付款条款")
    snapshot = fake_snapshot(clauses=[
        clause,
        fake_clause(2, number="3.2", title="发票条款"),
        fake_clause(9, number="9.9", title="争议解决", clause_type="TERMINATION"),
    ])
    return _base_state(
        work_units=units,
        retry_budget=budget,
        evidence_snapshot=snapshot,
        domain_tasks=[{"domainKey": "price_payment_tax", "domainName": "价款付款税务"}],
        evidence_bundles_by_work_unit={
            "price_payment_tax.wu_a": _bundle(contract=[clause]),
            "price_payment_tax.wu_b": _bundle(),
        },
        validation_by_work_unit={
            "price_payment_tax.wu_a": {"candidateCount": 1, "verdictCounts": {"PASS": 1}, "acceptedCount": 1},
            "price_payment_tax.wu_b": {"candidateCount": 0, "verdictCounts": {}, "acceptedCount": 0},
        },
        counter_analysis_by_work_unit={"price_payment_tax.wu_a": [], "price_payment_tax.wu_b": []},
        evidence_needs=[],
        negative_conclusion_checks=[],
    )


def test_audit_generates_needs_and_targets():
    result = review_v2.audit_coverage(_audit_state(budget=2))
    coverage = result["coverage"]
    assert coverage["status"] == "NEED_MORE_EVIDENCE"
    # covered unit
    assert result["coverage_by_work_unit"]["price_payment_tax.wu_a"]["status"] == "COVERED"
    # no-evidence unit → need + target
    assert result["coverage_by_work_unit"]["price_payment_tax.wu_b"]["status"] == "NO_EVIDENCE"
    reason_codes = {need["reason_code"] for need in result["evidence_needs"]}
    assert "NO_CONTRACT_EVIDENCE" in reason_codes
    assert result["reanalysis_targets"] == ["price_payment_tax.wu_b"]
    # unused catalog clause (different clause type) → 没审到 need
    unused = [need for need in result["evidence_needs"] if need["work_unit_id"] == "unused_evidence"]
    assert unused and unused[0]["reason_code"] == "MISSING_SUBCHECK"
    assert "TERMINATION" in coverage["summary"]["unusedClauseTypes"]
    # v1-compatible domain matrix
    domain = coverage["domains"]["price_payment_tax"]
    assert domain["coverageState"] == "PARTIAL"
    assert domain["workUnitCount"] == 2 and domain["coveredWorkUnitCount"] == 1


def test_audit_exhausted_budget_is_cannot_resolve():
    result = review_v2.audit_coverage(_audit_state(budget=0))
    assert result["coverage"]["status"] == "CANNOT_RESOLVE"
    assert result["reanalysis_targets"] == []
    assert result["coverage"]["retryable"] is False


def test_audit_evidence_without_findings_is_analyzed_no_findings():
    state = _audit_state(budget=2)
    # wu_b has evidence but no accepted findings this time
    state["evidence_bundles_by_work_unit"]["price_payment_tax.wu_b"] = _bundle(
        contract=[fake_clause(2, number="3.2", title="发票条款")],
    )
    state["validation_by_work_unit"]["price_payment_tax.wu_b"] = {
        "candidateCount": 0, "verdictCounts": {}, "acceptedCount": 0,
    }
    result = review_v2.audit_coverage(state)
    assert result["coverage_by_work_unit"]["price_payment_tax.wu_b"]["status"] == "ANALYZED_NO_FINDINGS"
    codes = {need["reason_code"] for need in result["evidence_needs"]}
    assert "MISSING_SUBCHECK" in codes


def test_route_after_audit():
    assert review_v2._route_after_audit({"coverage": {"status": "CONFIRMED"},
                                          "retry_budget": 2, "reanalysis_targets": []}) == "compose_report"
    assert review_v2._route_after_audit({"coverage": {"status": "NEED_MORE_EVIDENCE"},
                                          "retry_budget": 2, "reanalysis_targets": ["wu_b"]}) == "targeted_retrieval"
    assert review_v2._route_after_audit({"coverage": {"status": "NEED_MORE_EVIDENCE"},
                                          "retry_budget": 0, "reanalysis_targets": ["wu_b"]}) == "compose_limited_report"
    assert review_v2._route_after_audit({"coverage": {"status": "NEED_MORE_EVIDENCE"},
                                          "retry_budget": 1, "reanalysis_targets": []}) == "compose_limited_report"


# ─────────────────── targeted retrieval + reanalysis (§15.4) ─────────────────


def test_targeted_retrieval_unions_evidence_and_budgets(monkeypatch):
    clause = fake_clause(1, number="3.1", title="付款条款")
    new_clause = fake_clause(2, number="3.2", title="发票条款")
    orchestrator = _ScriptedOrchestrator(_bundle(contract=[new_clause]))
    monkeypatch.setattr(harness_retrieval, "get_orchestrator", lambda: orchestrator)

    snapshot = fake_snapshot(clauses=[clause, new_clause])
    state = _base_state(
        work_units=[_wu("price_payment_tax.wu_b", label="调价")],
        retry_budget=2,
        retry_state={},
        evidence_snapshot=snapshot,
        reanalysis_targets=["price_payment_tax.wu_b"],
        evidence_bundles_by_work_unit={
            "price_payment_tax.wu_b": _bundle(contract=[clause]),
        },
        evidence_needs=[{
            "need_id": "need-wu_b-NO_CONTRACT_EVIDENCE",
            "work_unit_id": "price_payment_tax.wu_b",
            "query_hints": ["调价机制 价格调整"],
            "retryable": True,
        }],
        domain_results={},
    )
    result = review_v2.targeted_retrieval(state)
    # UNION: first-round evidence is never dropped
    merged = result["evidence_bundles_by_work_unit"]["price_payment_tax.wu_b"]
    assert [item["sourceId"] for item in merged["contract_evidence"]] == [
        "CONTRACT_CLAUSE:1", "CONTRACT_CLAUSE:2",
    ]
    # the need's query hints drive the targeted round
    assert orchestrator.calls[0]["query_variants"] == ["调价机制 价格调整"]
    assert result["retry_budget"] == 1
    assert result["retry_state"]["reflection_rounds"] == 1
    # domain view refreshed from the merged bundles
    assert len(result["domain_results"]["price_payment_tax"]) == 2


def test_reanalyze_touches_only_targets(monkeypatch):
    rule = {
        "ruleKey": "RULE_PAY_001", "ruleTitle": "付款条款必须明确", "clauseType": "PAYMENT",
        "contractCitationIds": ["CONTRACT_CLAUSE:1"], "description": "付款条件需明确",
    }
    old_a = {"findingKey": "old-a", "title": "旧发现A", "workUnitId": "price_payment_tax.wu_a",
             "contractCitationIds": ["CONTRACT_CLAUSE:1"]}
    old_b = {"findingKey": "old-b", "title": "旧发现B", "workUnitId": "price_payment_tax.wu_b",
             "contractCitationIds": ["CONTRACT_CLAUSE:1"]}
    clause = fake_clause(1, number="3.1", title="付款条款")
    state = _base_state(
        work_units=[_wu("price_payment_tax.wu_a"), _wu("price_payment_tax.wu_b", label="调价")],
        rule_findings=[rule],
        reanalysis_targets=["price_payment_tax.wu_a"],
        evidence_bundles_by_work_unit={
            "price_payment_tax.wu_a": _bundle(contract=[clause]),
            "price_payment_tax.wu_b": _bundle(contract=[clause]),
        },
        findings_by_work_unit={
            "price_payment_tax.wu_a": [dict(old_a)],
            "price_payment_tax.wu_b": [dict(old_b)],
        },
        counter_analysis_by_work_unit={"price_payment_tax.wu_a": [], "price_payment_tax.wu_b": []},
        merged_candidates_by_work_unit={},
        validation_by_work_unit={},
        validated_findings=[dict(old_a), dict(old_b)],
        evidence_needs=[],
        negative_conclusion_checks=[],
    )
    result = review_v2.reanalyze_affected_work_units(state)
    # the target was re-analyzed (rule fallback produced a fresh finding)
    new_a = result["findings_by_work_unit"]["price_payment_tax.wu_a"]
    assert all(finding["ruleKey"] == "RULE_PAY_001" for finding in new_a)
    # the untouched unit is preserved exactly
    assert result["findings_by_work_unit"]["price_payment_tax.wu_b"] == [old_b]
    validated_ids = {finding.get("findingKey") for finding in result["validated_findings"]}
    assert "old-b" in validated_ids  # untouched finding kept
    assert not any(finding.get("findingKey") == "old-a" for finding in result["validated_findings"])


# ─────────────────────────── graph assembly ─────────────────────────────────


def test_graph_builds_and_registers_v2():
    graph = review_v2.build_contract_review_v2_graph()
    node_names = {node for node in graph.get_graph().nodes.keys()}
    assert "plan_work_units" in node_names
    assert "retrieve_evidence_for_work_units" in node_names
    assert "audit_coverage" in node_names
    assert "targeted_retrieval" in node_names
    assert "reanalyze_affected_work_units" in node_names
    assert "compose_report" in node_names  # v1 tail reused
    assert "persist_report" in node_names
