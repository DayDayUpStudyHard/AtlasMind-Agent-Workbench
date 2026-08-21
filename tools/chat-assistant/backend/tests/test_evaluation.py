"""Tests for the evaluation framework."""

import asyncio
import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


def test_dataset_loading():
    """Test that sample YAML datasets load correctly."""
    from app.agent_runtime.evaluation.dataset import EvaluationDataset, EvalCase

    dataset_path = Path(__file__).parent.parent / "app" / "agent_runtime" / "evaluation" / "datasets" / "v1"
    if not dataset_path.exists():
        pytest.skip("Dataset directory not found")

    dataset = EvaluationDataset(dataset_path)
    cases = dataset.load()

    assert len(cases) >= 1, "Should load at least 1 sample case"

    for case in cases:
        assert case.case_id, "Each case must have a caseId"
        assert case.contract_text, "Each case must have contractText"
        assert isinstance(case.expected_findings, list)

    # Verify sample-001 has expected HIGH finding
    sample1 = next((c for c in cases if c.case_id == "SAMPLE-001"), None)
    if sample1:
        high_findings = [f for f in sample1.expected_findings if f.severity == "HIGH"]
        assert len(high_findings) >= 1, "SAMPLE-001 should have HIGH severity finding"


def test_metrics_computation():
    """Test that metrics compute correctly from results."""
    from app.agent_runtime.evaluation.metrics import EvaluationMetrics
    from app.agent_runtime.evaluation.runner import EvalRunResult

    # Create mock results
    results = [
        EvalRunResult(
            case_id="CASE-1",
            success=True,
            findings=[{"title": "预付款风险", "severity": "HIGH", "contractCitation": {"snippet": "50%预付"}, "policyCitation": {"snippet": "制度要求"}}],
            metrics={"highRecall": 1.0, "dualCitationRate": 1.0, "falsePositives": 0, "analysisMode": "FULL"},
        ),
        EvalRunResult(
            case_id="CASE-2",
            success=True,
            findings=[{"title": "验收不明确", "severity": "HIGH", "contractCitation": {"snippet": "甲方满意"}}],
            metrics={"highRecall": 0.5, "dualCitationRate": 0.0, "falsePositives": 0, "analysisMode": "LIMITED"},
        ),
    ]

    summary = EvaluationMetrics.compute_summary(results)
    assert summary.total_cases == 2
    assert summary.successful_cases == 2
    assert summary.high_risk_recall == 0.75
    assert summary.dual_citation_rate == 0.5
    assert summary.limited_report_rate == 0.5


def test_meets_thresholds():
    """Test the threshold check function."""
    from app.agent_runtime.evaluation.metrics import EvaluationMetrics

    # Good metrics
    good = EvaluationMetrics(
        total_cases=10,
        successful_cases=10,
        high_risk_recall=0.95,
        dual_citation_rate=0.98,
        false_positive_rate=0.01,
    )
    passed, failures = good.meets_thresholds()
    assert passed, f"Should pass thresholds, failures: {failures}"

    # Bad metrics
    bad = EvaluationMetrics(
        total_cases=10,
        successful_cases=10,
        high_risk_recall=0.70,
        dual_citation_rate=0.80,
        false_positive_rate=0.10,
    )
    passed, failures = bad.meets_thresholds()
    assert not passed, "Should fail thresholds"


def test_release_gate_separates_quality_failures_from_invalid_runs():
    from app.agent_runtime.evaluation.metrics import build_release_gate

    quality_failure = build_release_gate({
        "highRiskRecall": 0.667,
        "dualCitationRate": 0.4714,
        "falsePositiveRate": 0.0,
        "limitedReportRate": 0.0,
        "metricCaseCount": 3,
        "resultValid": True,
    }, status="COMPLETED")
    assert quality_failure["status"] == "FAILED"
    assert quality_failure["blockingReasons"] == []
    assert {item["metric"] for item in quality_failure["failures"]} == {
        "highRiskRecall", "dualCitationRate",
    }

    blocked = build_release_gate({
        "highRiskRecall": 1.0,
        "dualCitationRate": 1.0,
        "falsePositiveRate": 0.0,
        "limitedReportRate": 0.0,
        "metricCaseCount": 0,
        "resultValid": False,
    }, status="ENVIRONMENT_UNAVAILABLE")
    assert blocked["status"] == "BLOCKED"
    assert "ENVIRONMENT_UNAVAILABLE" in blocked["blockingReasons"]
    assert "RESULT_INVALID" in blocked["blockingReasons"]
    assert "NO_SCORED_CASES" in blocked["blockingReasons"]


def test_release_gate_passes_only_for_full_quality_run():
    from app.agent_runtime.evaluation.metrics import build_release_gate

    gate = build_release_gate({
        "highRiskRecall": 0.95,
        "dualCitationRate": 0.98,
        "falsePositiveRate": 0.01,
        "limitedReportRate": 0.0,
        "metricCaseCount": 10,
        "resultValid": True,
    }, status="COMPLETED")
    assert gate["passed"] is True
    assert gate["status"] == "PASSED"
    assert gate["thresholdVersion"] == "release-gate-v1"


def test_v4_release_gate_exposes_four_independent_statuses():
    from app.agent_runtime.evaluation.metrics import build_release_gate

    gate = build_release_gate({
        "benchmarkSchemaVersion": 2,
        "benchmarkTaskType": "FULFILLMENT_CHECK",
        "taskMetrics": {"requirementRecall": 0.9},
        "metricDenominators": {
            "proofStatusAccuracy": 1,
            "judgementAccuracy": 0,
            "aiSuggestionAccuracy": 0,
        },
        "metricCaseCount": 1,
        "resultValid": True,
        "approvedCaseCount": 5,
        "provisionalCaseCount": 0,
    }, status="COMPLETED")

    assert gate["executionStatus"] == "COMPLETED"
    assert gate["qualityStatus"] == "FAILED"  # required metrics not supplied
    assert gate["goldStatus"] == "APPROVED"
    assert gate["publishStatus"] == "BLOCKED"
    assert "judgementAccuracy" in gate["unobservedMetrics"]


def test_unlabelled_fulfillment_dimensions_are_not_scored_as_zero():
    from app.api.routes import _score_fulfillment_check

    case = {
        "expected_findings_json": '[{"title":"交付文件","requirement":"提交交付文件"}]',
        "expected_judgements_json": '[{"requirementContains":"交付文件","proofStatus":"SUPPORTED"}]',
        "expected_manual_result": "SATISFIED",
    }
    artifact = {
        "content": {"manualResult": "SATISFIED"},
        "requirements": [{
            "requirement": "提交交付文件",
            "proofStatus": "SUPPORTED",
            "judgement": "BASICALLY_SATISFIED",
            "aiSuggestion": {"conclusion": "BASICALLY_SATISFIED", "status": "LLM_ENRICHED"},
            "evidenceSnapshot": {"text": "已提交"},
        }],
    }
    result = _score_fulfillment_check(case, artifact)
    assert result["proofStatusAccuracy"] == 1.0
    assert result["proofStatusDenominator"] == 1
    assert result["judgementAccuracy"] is None
    assert result["aiSuggestionAccuracy"] is None


def test_contract_intake_scores_identity_kinds_independently():
    from app.api.routes import _score_contract_intake

    case = {"expected_findings_json": json.dumps([
        {"title": "甲方:甲公司", "key": "partyA", "value": "甲公司", "kind": "partyRole"},
        {"title": "合同金额:100万元", "key": "amount", "value": "100万元", "kind": "amount"},
        {"title": "签订日期:2026-01-01", "key": "signedDate", "value": "2026-01-01", "kind": "date"},
        {"title": "合同名称:技术服务合同", "key": "contractTitle", "value": "技术服务合同", "kind": "title"},
    ], ensure_ascii=False)}
    artifact = {"elements": [
        {"elementKey": "partyA", "rawValue": "甲公司", "citations": [{"quote": "甲公司"}]},
        {"elementKey": "amount", "rawValue": "100万元", "citations": [{"quote": "100万元"}]},
        {"elementKey": "signedDate", "rawValue": "2026-01-01", "citations": [{"quote": "2026-01-01"}]},
        {"elementKey": "contractTitle", "rawValue": "技术服务合同", "citations": [{"quote": "技术服务合同"}]},
    ]}
    result = _score_contract_intake(case, artifact)
    assert result["partyRoleAccuracy"] == 1.0
    assert result["amountAccuracy"] == 1.0
    assert result["dateAccuracy"] == 1.0
    assert result["contractTitleAccuracy"] == 1.0


def test_limited_only_blocks_when_it_hits_expected_risk_dimension():
    from app.api.routes import _limited_result_impacts_target_domain

    case = {"expected_findings_json": '[{"title":"付款周期过长","riskDimension":"PAYMENT"}]'}
    unrelated = {"analysisMode": "LIMITED", "findings": [{"title": "验收不明", "domainKey": "ACCEPTANCE"}]}
    related = {"analysisMode": "LIMITED", "findings": [{"title": "付款无期限", "domainKey": "PAYMENT"}]}
    assert not _limited_result_impacts_target_domain(case, unrelated, "CONTRACT_REVIEW")
    assert _limited_result_impacts_target_domain(case, related, "CONTRACT_REVIEW")


def test_risk_title_matching_accepts_semantically_equivalent_wording():
    from app.api.routes import _risk_finding_matches

    expected = {
        "title": "付款周期过长，乙方现金流风险极高",
        "riskDimension": "PAYMENT",
    }
    actual = {
        "title": "180个工作日付款期限导致服务方承担重大现金流压力",
        "riskDimension": "PAYMENT",
        "riskExplanation": "付款周期接近九个月，回款时间明显过长。",
    }

    assert _risk_finding_matches(expected, actual)


def test_risk_title_matching_uses_expected_key_terms_within_dimension():
    from app.api.routes import _risk_finding_matches

    expected = {
        "title": "预付款缺少保障条件",
        "riskDimension": "PAYMENT",
        "keyTerms": ["预付款", "履约担保", "保障"],
    }
    actual = {
        "title": "预付款比例过高",
        "clauseType": "PAYMENT",
        "riskExplanation": "合同约定50%预付款，且未约定履约担保或其他保障措施。",
    }

    assert _risk_finding_matches(expected, actual)


def test_only_current_failed_stage_is_marked_failed():
    from app.api.routes import _failed_eval_stage_run_ids

    assert _failed_eval_stage_run_ids(
        [101, 102, 103],
        completed_run_ids={101, 102},
    ) == [103]


def test_eval_case_timebox_uses_one_budget_for_all_stages():
    from app.api.routes import _remaining_eval_case_timeout

    # The second stage receives only the budget left by the first stage;
    # multi-stage fulfillment checks cannot consume a full timeout twice.
    assert _remaining_eval_case_timeout(110.1, now=100.0) == 11
    assert _remaining_eval_case_timeout(110.1, now=109.2) == 1
    with pytest.raises(TimeoutError, match="wall-clock timeout"):
        _remaining_eval_case_timeout(110.0, now=110.0)


def test_limited_agent_result_remains_scoreable_for_evaluation():
    """LIMITED is an evidence-coverage outcome, not an execution failure."""
    from app.api.routes import _is_scoreable_eval_result

    artifact = {"analysisMode": "LIMITED", "findings": []}
    assert _is_scoreable_eval_result(SimpleNamespace(status="LIMITED"), artifact)
    assert _is_scoreable_eval_result(SimpleNamespace(status="COMPLETED"), artifact)
    assert _is_scoreable_eval_result(
        SimpleNamespace(status="COMPLETED"),
        {"elements": []},
    )
    assert not _is_scoreable_eval_result(
        SimpleNamespace(status="COMPLETED"),
        {"elements": []},
        require_findings=True,
    )
    assert not _is_scoreable_eval_result(SimpleNamespace(status="FAILED"), artifact)
    assert not _is_scoreable_eval_result(
        SimpleNamespace(status="LIMITED"),
        {"findings": [], "artifactError": "bad artifact"},
    )


def test_limited_eval_run_persists_coverage_diagnostics(monkeypatch):
    import app.agent_runtime.persistence as persistence
    from app.api.routes import _finish_eval_agent_run

    captured = {}

    class Cursor:
        def __enter__(self): return self
        def __exit__(self, *_): return None
        def execute(self, sql, params):
            captured["sql"] = sql
            captured["params"] = params

    class Connection:
        def __enter__(self): return self
        def __exit__(self, *_): return None
        def cursor(self): return Cursor()
        def commit(self): pass

    monkeypatch.setattr(persistence, "_conn", lambda: Connection())
    _finish_eval_agent_run(
        1,
        "LIMITED",
        "Evaluation case completed with limited coverage",
        {"missingCheckItems": ["payment"], "retried": True},
    )

    assert "limited_diagnostics=COALESCE" in captured["sql"]
    assert captured["params"][0] == "LIMITED"
    assert json.loads(captured["params"][-2])["missingCheckItems"] == ["payment"]


def test_eval_environment_gate_retries_transient_embedding_probe(monkeypatch):
    import app.api.routes as routes

    responses = [
        {"components": {
            "llm": {"status": "ok"},
            "embedding": {"status": "error"},
            "elasticsearch": {"status": "ok"},
        }},
        {"components": {
            "llm": {"status": "ok"},
            "embedding": {"status": "ok"},
            "elasticsearch": {"status": "ok"},
        }},
    ]

    async def fake_health(*, probe):
        assert probe is True
        return responses.pop(0)

    async def no_sleep(_):
        return None

    monkeypatch.setattr(routes, "health", fake_health)
    monkeypatch.setattr(routes.asyncio, "sleep", no_sleep)
    snapshot = asyncio.run(routes._eval_environment_gate({"environmentProbeAttempts": 2}))

    assert snapshot["environmentStatus"] == "READY"
    assert snapshot["probeAttempts"] == 2


@pytest.mark.parametrize(
    "message",
    [
        "Error code: 402 - Insufficient Balance",
        "HTTP 403 Forbidden",
        "LLM authentication failed",
    ],
)
def test_eval_provider_auth_and_balance_errors_are_infrastructure_failures(message):
    from app.api.routes import _is_infra_error

    assert _is_infra_error(message) is True


def test_eval_fixture_seeds_deterministic_intake_metadata():
    from app.api.routes import _eval_fixture_intake_metadata

    metadata = _eval_fixture_intake_metadata(
        "甲方：杭州甲公司\n乙方：深圳乙公司\n合同总价：人民币100万元整"
    )

    assert metadata["our_entity"] == "杭州甲公司"
    assert metadata["counterparty"] == "深圳乙公司"
    assert metadata["amount"] == 1000000.0
    assert metadata["currency"] == "CNY"


def test_element_scorer_matches_equivalent_chinese_and_normalized_amounts():
    from app.api.routes import _element_expectation_matches

    assert _element_expectation_matches(
        {"title": "合同总价:100万元"},
        "amount 合同金额 1000000.0 CNY",
    )


def test_unnumbered_comprehensive_contract_is_split_by_business_lines():
    from app.api.routes import _split_eval_contract_clauses
    from app.agent_runtime.contract_document_parser import classify_clause, split_contract_text

    clauses = _split_eval_contract_clauses(
        "测试合同\n总价：680万元\n付款：验收后180日支付\n知识产权：成果归甲方\n争议：甲方所在地法院管辖",
        split_contract_text=split_contract_text,
        classify_clause=classify_clause,
    )

    assert len(clauses) == 5
    assert {clause["clauseType"] for clause in clauses} >= {"PAYMENT", "IP"}


def test_comprehensive_plan_stops_before_evidence_based_fulfillment_check():
    from app.api.routes import _eval_task_plan

    assert _eval_task_plan("COMPREHENSIVE") == [
        "CONTRACT_ELEMENT_EXTRACTION",
        "TIMELINE_EXTRACTION",
        "CONTRACT_REVIEW",
    ]


def test_eval_result_persists_schema_valid_rate(monkeypatch):
    import app.agent_runtime.persistence as persistence
    from app.api.routes import _record_eval_result

    captured = {}

    class Cursor:
        def __enter__(self): return self
        def __exit__(self, *_): return None
        def execute(self, sql, params):
            captured["sql"] = sql
            captured["params"] = params

    class Connection:
        def __enter__(self): return self
        def __exit__(self, *_): return None
        def cursor(self): return Cursor()
        def commit(self): pass

    monkeypatch.setattr(persistence, "_conn", lambda: Connection())
    _record_eval_result(1, 2, {
        "success": True,
        "schemaValid": 1,
        "analysisMode": "FULL",
        "artifact": {},
    })

    assert "schema_valid_rate" in captured["sql"]
    assert captured["params"][-1] == 1.0


def test_eval_rerank_observation_reads_graph_retrieval_metadata():
    from app.api.routes import _eval_rerank_observation

    observation = _eval_rerank_observation({
        "retrievalValidation": {
            "payment": {"rerankMethods": ["MODEL_RERANK"]},
            "liability": {"rerankMethods": ["KEYWORD_BONUS"]},
        }
    })

    assert observation == {
        "actualMethod": "MIXED",
        "methods": ["KEYWORD_FALLBACK", "MODEL_RERANK"],
    }


def test_eval_rerank_observation_reads_legacy_pipeline_metadata():
    from app.api.routes import _eval_rerank_observation

    observation = _eval_rerank_observation({
        "retrievalValidation": {
            "legacyPipeline": {"rerankMethods": ["MODEL_RERANK"]},
        }
    })

    assert observation == {
        "actualMethod": "MODEL_RERANK",
        "methods": ["MODEL_RERANK"],
    }


def test_eval_business_contract_type_maps_scenario():
    from app.api.routes import _eval_business_contract_type

    # Scenario wins over the dataset task type stored in contract_type
    assert _eval_business_contract_type(
        {"scenario": "SERVICE_PROCUREMENT", "contract_type": "CONTRACT_REVIEW"}
    ) == "SERVICE_PROCUREMENT"
    # Spelling normalization to the canonical token used by rule sets/inventories
    assert _eval_business_contract_type(
        {"scenario": "GOODS_PROCUREMENT", "contract_type": "CONTRACT_REVIEW"}
    ) == "GOODS_PURCHASE"
    assert _eval_business_contract_type({"scenario": "NDA"}) == "NDA"
    # Scenario values without a dedicated rule set/inventory pass through
    assert _eval_business_contract_type({"scenario": "ENGINEERING_EPC"}) == "ENGINEERING_EPC"
    assert _eval_business_contract_type({"scenario": "MIXED"}) == "MIXED"
    # Blank/unknown scenario falls back to contract_type when it is a business type
    assert _eval_business_contract_type(
        {"scenario": "", "contract_type": "GOODS_PURCHASE"}
    ) == "GOODS_PURCHASE"
    # Dataset task types are not business types
    assert _eval_business_contract_type(
        {"scenario": "", "contract_type": "CONTRACT_REVIEW"}
    ) == "OTHER"


def test_eval_expected_dimensions_distinct_and_normalized():
    from app.api.routes import _eval_expected_dimensions

    case = {
        "expected_findings_json": json.dumps([
            {"title": "a", "riskDimension": "PAYMENT"},
            {"title": "b", "riskDimension": "PAYMENT"},
            {"title": "c", "riskDimension": "PRICE_PAYMENT_TAX"},
            {"title": "d"},
        ])
    }

    assert _eval_expected_dimensions(case) == ["PAYMENT"]


def test_eval_required_domain_keys():
    from app.agent_runtime.graph.nodes.reflection import _eval_required_domain_keys

    # No eval metadata → full baseline gate (None)
    assert _eval_required_domain_keys({"case_snapshot": {}}) is None
    assert _eval_required_domain_keys(
        {"case_snapshot": {"evalExpectedDimensions": []}}
    ) is None
    # Expected dimensions map to the matching baseline domains
    assert _eval_required_domain_keys({
        "case_snapshot": {"evalExpectedDimensions": ["PAYMENT", "LIABILITY"]}
    }) == {"price_payment_tax", "liability_remedies"}
    # Dimensions without a baseline domain gate on nothing
    assert _eval_required_domain_keys({
        "case_snapshot": {"evalExpectedDimensions": ["FORCE_MAJEURE", "GENERAL"]}
    }) == set()


def test_coverage_gate_trims_to_expected_domains():
    from app.agent_runtime.graph.nodes.domain_tasks import MANDATORY_DOMAINS
    from app.agent_runtime.graph.nodes.reflection import coverage_reflection

    base_state = {
        "case_snapshot": {"evalExpectedDimensions": ["PAYMENT"]},
        "validated_findings": [{"title": "付款周期过长", "domainKey": "price_payment_tax"}],
        "domain_tasks": [dict(item) for item in MANDATORY_DOMAINS],
        "domain_analysis": {"price_payment_tax": {"status": "COMPLETED"}},
        "domain_results": {"price_payment_tax": [{"sourceType": "CONTRACT_CLAUSE"}]},
        "retry_state": {"reflection_rounds": 0},
        "state_revision": 0,
        "errors": [],
    }

    focused = coverage_reflection(dict(base_state))
    assert focused["coverage"]["status"] == "CONFIRMED"
    assert focused["coverage"]["missingDomains"] == []

    # The same evidence without an eval focus fails the full baseline gate
    unfocused_state = dict(base_state)
    unfocused_state["case_snapshot"] = {}
    unfocused = coverage_reflection(unfocused_state)
    assert unfocused["coverage"]["status"] == "NEED_MORE_EVIDENCE"
    assert "scope_delivery_acceptance" in unfocused["coverage"]["missingDomains"]


def test_coverage_gate_passes_ambiguous_gated_domain_with_findings():
    from app.agent_runtime.graph.nodes.domain_tasks import MANDATORY_DOMAINS
    from app.agent_runtime.graph.nodes.reflection import coverage_reflection

    # Low-confidence noise makes the gated domain AMBIGUOUS, but analysis
    # completed and produced validated findings — the expected risk was
    # found, so the gate must not downgrade the case to LIMITED.
    state = {
        "case_snapshot": {"evalExpectedDimensions": ["PAYMENT"]},
        "validated_findings": [
            {"title": "f1", "domainKey": "price_payment_tax", "confidenceLevel": "HIGH"},
            {"title": "f2", "domainKey": "price_payment_tax", "confidenceLevel": "LOW"},
            {"title": "f3", "domainKey": "price_payment_tax", "confidenceLevel": "LOW"},
        ],
        "domain_tasks": [dict(item) for item in MANDATORY_DOMAINS],
        "domain_analysis": {"price_payment_tax": {"status": "COMPLETED"}},
        "domain_results": {"price_payment_tax": [{"sourceType": "CONTRACT_CLAUSE"}]},
        "retry_state": {"reflection_rounds": 0},
        "state_revision": 0,
        "errors": [],
    }

    result = coverage_reflection(state)
    assert result["coverage"]["status"] == "CONFIRMED"
    assert result["coverage"]["missingDomains"] == []


def test_risk_title_matching_accepts_rule_engine_findings():
    from app.api.routes import _risk_finding_matches

    expected = {"title": "验收标准完全由甲方主观判断", "riskDimension": "ACCEPTANCE"}
    actual = {
        "ruleId": 7,
        "ruleKey": "PROC-ACC-001",
        "ruleTitle": "验收标准明确",
        "title": "验收标准明确",
        "riskDimension": "ACCEPTANCE",
        "clauseType": "ACCEPTANCE",
        "severity": "HIGH",
        "description": "验收标准不得为\"甲方单方决定\"，必须具有客观可衡量标准",
    }

    assert _risk_finding_matches(expected, actual)


def test_risk_title_matching_short_actual_contained_in_long_expected():
    from app.api.routes import _risk_finding_matches

    # run-19 style miss: a compact actual title embedded in a long expected
    # title failed the overlap threshold because the denominator was the
    # long expected side. Containment from the shorter side must match.
    expected = {
        "title": "不可抗力范围定义过于宽泛，排除了自然灾害和政府行为的适用范围",
        "riskDimension": "FORCE_MAJEURE",
    }
    actual = {"title": "不可抗力范围过宽", "severity": "HIGH"}
    assert _risk_finding_matches(expected, actual)


def test_risk_title_matching_rejects_unrelated_short_actual():
    from app.api.routes import _risk_finding_matches

    expected = {"title": "付款周期过长，乙方现金流风险极高", "riskDimension": "PAYMENT"}
    actual = {"title": "知识产权归甲方所有", "severity": "HIGH"}
    assert not _risk_finding_matches(expected, actual)


def test_risk_title_matching_respects_dimension_gate_despite_containment():
    from app.api.routes import _risk_finding_matches

    # Same wording family, different dimensions: the dimension gate must
    # still reject before containment matching applies.
    expected = {"title": "验收标准完全由甲方主观判断", "riskDimension": "ACCEPTANCE"}
    actual = {"title": "验收标准明确", "riskDimension": "PAYMENT"}
    assert not _risk_finding_matches(expected, actual)


def test_risk_dimension_prefers_domain_key_over_other_clause_type():
    from app.api.routes import _risk_dimension

    # Artifact findings carry clauseType=OTHER with a specific domainKey;
    # clauseType-first normalization masked the domainKey on every artifact
    # finding and broke the gate (hard3 rescore regression).
    actual = {"clauseType": "OTHER", "domainKey": "FORCE_MAJEURE_RISK"}
    assert _risk_dimension(actual) == "FORCE_MAJEURE"


def test_risk_title_matching_domain_key_family_aligns_expected_dimension():
    from app.api.routes import _risk_finding_matches

    # run-36 CR-016: expected DATA finding vs artifact finding whose only
    # dimension signal is domainKey DATA_PROTECTION_SECURITY — the gate
    # must let the weak text channel through.
    expected = {
        "title": "合同缺失数据安全条款——系统处理医护人员个人信息但无安全保护约定",
        "riskDimension": "DATA",
    }
    actual = {
        "title": "缺少数据安全与个人信息保护条款",
        "clauseType": "OTHER",
        "domainKey": "DATA_PROTECTION_SECURITY",
        "description": "合同涉及医院HR系统，含个人信息，未约定数据安全保护措施",
        "severity": "HIGH",
    }
    assert _risk_finding_matches(expected, actual)


def test_risk_title_matching_strong_text_bypasses_dimension_gate():
    from app.api.routes import _risk_finding_matches

    # run-25 CR-008: the expected force-majeure finding and the artifact
    # finding are the same risk under different dimension vocabularies;
    # strong text evidence must not be killed by the gate.
    expected = {
        "title": "不可抗力范围被严重限缩——排除了常见的地质灾害和政府行为",
        "riskDimension": "FORCE_MAJEURE",
    }
    actual = {
        "title": "不可抗力范围过窄且排除救济",
        "clauseType": "OTHER",
        "description": "不可抗力仅限7级以上地震和百年一遇洪水，排除了地质灾害和政府行为",
        "severity": "HIGH",
    }
    assert _risk_finding_matches(expected, actual)


def test_risk_title_matching_gate_still_rejects_weak_cross_dimension_overlap():
    from app.api.routes import _risk_finding_matches

    # Below the strong-evidence bypass, a dimension mismatch must still
    # reject weak overlaps: shared description wording alone is not a hit.
    expected = {"title": "验收标准完全由甲方主观判断，且无客观衡量标准可依", "riskDimension": "ACCEPTANCE"}
    actual = {
        "title": "付款条件由甲方单方决定",
        "clauseType": "OTHER",
        "domainKey": "PRICE_PAYMENT_TAX",
        "description": "甲方主观判断付款时点，乙方无法预见",
        "severity": "HIGH",
    }
    assert not _risk_finding_matches(expected, actual)


def test_score_eval_artifact_vacuous_recall_without_expected_high():
    from app.api.routes import _score_eval_artifact

    case = {
        "expected_findings_json": json.dumps([
            {"title": "x", "severity": "MEDIUM"},
        ])
    }
    result = _score_eval_artifact(
        case,
        {"findings": [{"title": "a", "severity": "HIGH"}]},
        "CONTRACT_REVIEW",
    )
    assert result["highRecall"] == 1.0


def test_score_eval_artifact_registry_routes_risk_review():
    from app.api.routes import _score_eval_artifact

    case = {
        "expected_findings_json": json.dumps([
            {"title": "付款周期过长", "severity": "HIGH"},
        ])
    }
    artifact = {
        "findings": [{
            "title": "付款周期过长",
            "severity": "HIGH",
            "contractCitation": {"snippet": "180日"},
            "policyCitation": {"snippet": "制度要求"},
        }]
    }
    result = _score_eval_artifact(case, artifact, "CONTRACT_REVIEW")
    assert result["highRecall"] == 1.0
    assert result["dualCitationRate"] == 1.0
    assert result["schemaValid"] == 1
    assert result["scored"] is True
    assert result["scorerVersion"] == "eval-scorers-v4"


def test_score_eval_artifact_element_extraction_scores_elements_and_missing():
    from app.api.routes import _score_eval_artifact

    case = {
        "expected_findings_json": json.dumps([
            {"title": "甲方:北京某某科技有限公司", "severity": "LOW", "riskDimension": "PARTY"},
            {"title": "总价:3,600,000元/月", "severity": "LOW", "riskDimension": "PAYMENT"},
            {"title": "开工日期:缺失", "severity": "HIGH", "riskDimension": "DATE"},
        ])
    }
    artifact = {
        "analysisMode": "FULL",
        "evaluationStages": {
            "CONTRACT_ELEMENT_EXTRACTION": {
                "summary": "已从 6 个合同条款中提取了 1 个合同要素",
                "elements": [{
                    "elementKey": "payment_terms",
                    "category": "FINANCIAL",
                    "rawValue": "月度支付：每月15日前支付服务费150,000元",
                    "citations": [{"sourceId": "CONTRACT_CLAUSE:1"}],
                }],
                "contractProfile": {
                    "baseFields": [
                        {"key": "party_a", "label": "甲方", "value": "北京某某科技有限公司", "citations": []},
                    ],
                    "groups": [{
                        "groupKey": "project_schedule",
                        "reason": "缺少开工日期和中间验收节点，请关注",
                        "fields": [],
                    }],
                },
            }
        },
    }
    result = _score_eval_artifact(case, artifact, "CONTRACT_ELEMENT_EXTRACTION")
    # 甲方 matched via profile field; 总价 unmatched (wrong amount extracted);
    # 开工日期:缺失 detected via group reason → 2/3
    assert result["highRecall"] == pytest.approx(2 / 3)
    # citation coverage: 1 cited element of 2 extracted items
    assert result["dualCitationRate"] == pytest.approx(0.5)
    assert result["schemaValid"] == 1
    assert result["findingCount"] == 2
    assert result["scored"] is True
    assert result["scorerVersion"] == "eval-scorers-v4"


def test_score_eval_artifact_element_missing_not_detected_scores_zero():
    from app.api.routes import _score_eval_artifact

    case = {
        "expected_findings_json": json.dumps([
            {"title": "验收节点:缺失", "severity": "HIGH", "riskDimension": "ACCEPTANCE"},
        ])
    }
    artifact = {
        "evaluationStages": {
            "CONTRACT_ELEMENT_EXTRACTION": {
                "summary": "已提取全部要素，无异常",
                "elements": [],
                "contractProfile": {
                    "baseFields": [],
                    "groups": [{"groupKey": "x", "reason": "合同要素齐全", "fields": []}],
                },
            }
        }
    }
    result = _score_eval_artifact(case, artifact, "CONTRACT_ELEMENT_EXTRACTION")
    assert result["highRecall"] == 0.0


def test_score_eval_artifact_unregistered_mode_is_explicitly_unscored():
    from app.api.routes import _score_eval_artifact

    result = _score_eval_artifact({}, {}, "SOME_FUTURE_TASK_TYPE")
    assert result["success"] is False
    assert result["scored"] is False
    assert result["skipReason"] == "NO_SCORER:SOME_FUTURE_TASK_TYPE"
    assert result["analysisMode"] == "UNSCORED"
    assert result["highRecall"] == 0.0


def test_score_eval_artifact_timeline_extraction_scores_nodes():
    from app.api.routes import _score_eval_artifact

    case = {
        "expected_findings_json": json.dumps([
            {"title": "生效:2026-01-01", "severity": "LOW", "riskDimension": "DATE"},
            {"title": "终止:双方权利义务履行完毕之日(条件事件)",
             "severity": "LOW", "riskDimension": "DATE"},
            {"title": "每月5日前:公示收支明细(周期)",
             "severity": "LOW", "riskDimension": "DATE"},
        ]),
        "should_not_find_json": json.dumps(["合同终止日期为2027-12-31"]),
    }
    artifact = {
        "analysisMode": "LLM_REVIEWED_TIMELINE",
        "nodes": [
            {
                "clauseId": 1, "label": "生效", "date": "2026-01-01",
                "condition": None, "nodeType": "EFFECTIVE",
                "businessMeaning": "合同生效日", "responsibleParty": "甲方",
                "citation": {"quote": "自2026年1月1日起生效"},
            },
            {
                "clauseId": 5, "label": "终止", "date": None,
                "condition": "双方权利义务履行完毕之日", "nodeType": "TERMINATION",
                "businessMeaning": "合同终止(条件事件)", "responsibleParty": None,
                "citation": {"quote": "于双方权利义务履行完毕之日终止"},
            },
            {
                "clauseId": 9, "label": "公示收支明细", "date": None,
                "condition": "每月5日前", "nodeType": "PERIODIC",
                "businessMeaning": "每月公示收支明细", "responsibleParty": "乙方",
                "citation": {"quote": "每月5日前公示收支明细"},
            },
        ],
    }
    result = _score_eval_artifact(case, artifact, "TIMELINE_EXTRACTION")
    assert result["scored"] is True
    assert result["highRecall"] == 1.0
    assert result["expectedNodeCount"] == 3
    assert result["dualCitationRate"] == 1.0
    assert result["dateAccuracy"] == 1.0
    assert result["dateDenominator"] == 1
    assert result["conditionalRecognitionRate"] == 1.0
    assert result["conditionalDenominator"] == 1
    assert result["responsiblePartyCoverage"] == pytest.approx(2 / 3)
    assert result["falsePositives"] == 0


def test_score_eval_artifact_timeline_date_mismatch_and_fabricated_node():
    from app.api.routes import _score_eval_artifact

    case = {
        "expected_findings_json": json.dumps([
            {"title": "生效:2026-01-01", "severity": "LOW", "riskDimension": "DATE"},
        ]),
        "should_not_find_json": json.dumps(["合同终止日期为2027-12-31"]),
    }
    artifact = {
        "nodes": [
            {
                "label": "生效", "date": "2026-02-01", "condition": None,
                "nodeType": "EFFECTIVE", "businessMeaning": "合同生效日",
                "citation": {},
            },
            {
                "label": "终止", "date": "2027-12-31", "condition": None,
                "nodeType": "TERMINATION",
                "businessMeaning": "合同终止日期为2027-12-31",
                "citation": {},
            },
        ],
    }
    result = _score_eval_artifact(case, artifact, "TIMELINE_EXTRACTION")
    # node found, but the calculated date is wrong
    assert result["highRecall"] == 1.0
    assert result["dateAccuracy"] == 0.0
    assert result["dateDenominator"] == 1
    # fabricated fixed termination date surfaces as a false positive
    assert result["falsePositives"] == 1


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("2017年11月30日", "2017-11-30"),
        ("2017/11/30", "2017-11-30"),
        ("二〇一七年十一月三十日", "2017-11-30"),
        ("合同生效后十日内", None),
    ],
)
def test_timeline_scorer_normalizes_contract_date_formats(raw, expected):
    from app.api.routes import _extract_eval_date

    assert _extract_eval_date(raw) == expected


def test_timeline_scorer_compares_chinese_expected_date():
    from app.api.routes import _score_eval_artifact

    result = _score_eval_artifact(
        {"expected_findings_json": json.dumps([
            {"title": "签署:2017年11月30日", "severity": "LOW"},
        ], ensure_ascii=False)},
        {"nodes": [{
            "label": "签署",
            "date": "2017-11-30",
            "condition": None,
            "nodeType": "SIGNING",
            "businessMeaning": "合同签署日期",
        }]},
        "TIMELINE_EXTRACTION",
    )

    assert result["dateAccuracy"] == 1.0
    assert result["dateDenominator"] == 1


def test_timeline_scorer_reads_evaluation_stage_wrapper():
    from app.api.routes import _score_eval_artifact

    case = {"expected_findings_json": json.dumps([
        {"title": "生效:2026-01-01", "severity": "LOW"},
    ])}
    artifact = {
        "evaluationStages": {
            "TIMELINE_EXTRACTION": {
                "analysisMode": "FULL",
                "nodes": [{
                    "label": "生效",
                    "date": "2026-01-01",
                    "condition": None,
                    "citation": {"quote": "合同自2026-01-01生效"},
                }],
                "content": {"validation": {}},
            }
        }
    }

    result = _score_eval_artifact(case, artifact, "TIMELINE_EXTRACTION")
    assert result["highRecall"] == 1.0
    assert result["schemaValid"] == 1
    assert result["dualCitationRate"] == 1.0


def test_score_eval_artifact_fulfillment_check_scores_requirements():
    from app.api.routes import _score_eval_artifact

    case = {
        "expected_findings_json": json.dumps([
            {"title": "完成付款：首付款"},
            {"title": "完成验收：设备调试验收"},
        ]),
        "should_not_find_json": json.dumps(["已完成全部付款"]),
    }
    artifact = {
        "analysisMode": "FULL",
        "content": {
            "manualResult": "SATISFIED",
            "requirements": [
                {
                    "requirement": "完成付款：首付款",
                    "proofStatus": "SUPPORTED",
                    "evidenceCitationIds": [1],
                    "aiSuggestion": {
                        "status": "LLM_ENRICHED", "conclusion": "BASICALLY_SATISFIED",
                    },
                },
                {
                    "requirement": "完成验收：设备调试验收",
                    "proofStatus": "EVIDENCE_INSUFFICIENT",
                    "judgement": "UNCLEAR_TERMS",
                    "evidenceSnapshot": None,
                    "evidenceCitationIds": None,
                },
            ],
        },
        "conclusion": "BASICALLY_SATISFIED",
    }
    result = _score_eval_artifact(case, artifact, "FULFILLMENT_CHECK")
    assert result["scored"] is True
    assert result["highRecall"] == 1.0
    assert result["expectedRequirementCount"] == 2
    # the evidence-less row is honestly judged INSUFFICIENT, not claimed
    assert result["restraintRate"] == 1.0
    assert result["restraintDenominator"] == 1
    assert result["aiSuggestionSchemaRate"] == 0.5
    assert result["conflictRecognitionRate"] == 0.5
    assert result["aiAutoConfirmViolations"] == 0
    assert result["humanAdoptionRate"] == 1.0
    assert result["dualCitationRate"] == 0.5
    assert result["falsePositives"] == 0


def test_score_eval_artifact_fulfillment_ai_auto_confirm_is_flagged():
    from app.api.routes import _score_eval_artifact

    case = {"expected_findings_json": "[]"}
    artifact = {
        "content": {"requirements": [], "manualResult": None},
        "conclusion": "COMPLETED",
    }
    result = _score_eval_artifact(case, artifact, "FULFILLMENT_CHECK")
    assert result["aiAutoConfirmViolations"] == 1
    assert result["humanAdoptionRate"] == 0.0


def test_legacy_task_support_guard():
    from app.agent_runtime.runtime import is_legacy_task_supported

    assert is_legacy_task_supported("CONTRACT_REVIEW")
    assert is_legacy_task_supported("FULFILLMENT_CHECK")
    assert not is_legacy_task_supported("CONTRACT_ELEMENT_EXTRACTION")
    assert not is_legacy_task_supported("TIMELINE_EXTRACTION")
    assert not is_legacy_task_supported("")


def test_fulfillment_eval_plan_requires_timeline_before_evidence_check():
    from app.api.routes import _eval_task_plan

    assert _eval_task_plan("FULFILLMENT_CHECK") == [
        "TIMELINE_EXTRACTION", "FULFILLMENT_CHECK",
    ]


def test_fulfillment_fixture_key_separates_proof_for_same_contract():
    from app.api.routes import _eval_fixture_key

    common = {
        "contract_text": "The supplier shall deliver the system by 2026-09-01.",
        "title": "Same contract",
        "scenario": "SERVICE_PROCUREMENT",
        # New UI-created cases normalize the case-level type to OTHER.  The
        # evaluation task must therefore come from the parent dataset.
        "contract_type": "OTHER",
        "evaluation_dataset_type": "FULFILLMENT_CHECK",
        "target_timeline_selector_json": '{"nodeType":"DELIVERY"}',
    }
    _, first_hash = _eval_fixture_key({
        **common,
        "fulfillment_evidence_json": '[{"content":"delivery receipt A"}]',
    })
    _, second_hash = _eval_fixture_key({
        **common,
        "fulfillment_evidence_json": '[{"content":"delivery receipt B"}]',
    })

    assert first_hash != second_hash


def test_fulfillment_eval_requires_separate_evidence_selector_and_manual_result():
    from app.api.routes import EvalCaseConfigurationError, _eval_fulfillment_input

    with pytest.raises(EvalCaseConfigurationError, match="targetTimelineSelectorJson"):
        _eval_fulfillment_input({
            "fulfillment_evidence_json": '[{"content":"交付清单"}]',
            "expected_manual_result": "SATISFIED",
        })

    result = _eval_fulfillment_input({
        "target_timeline_selector_json": '{"nodeType":"DELIVERY","labelContains":"交付"}',
        "fulfillment_evidence_json": '[{"fileName":"交付清单.txt","content":"已交付"}]',
        "expected_judgements_json": '[{"requirementContains":"交付","proofStatus":"SUPPORTED"}]',
        "expected_manual_result": "SATISFIED",
    })

    assert result["selector"]["nodeType"] == "DELIVERY"
    assert result["evidence"][0]["content"] == "已交付"
    assert result["expectedManualResult"] == "SATISFIED"


def test_fulfillment_timeline_selector_can_relax_mismatched_node_type(monkeypatch):
    from app.api.routes import _select_eval_timeline_node_id

    class Cursor:
        def __init__(self):
            self.calls = []

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def execute(self, query, params):
            self.calls.append((query, params))

        def fetchall(self):
            query, params = self.calls[-1]
            # The extractor classified a delivery obligation as ACCEPTANCE;
            # the gold selector still identifies it by its label.
            if "node_type=%s" in query:
                return []
            return [{"id": 901}]

    cursor = Cursor()

    class Conn:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def cursor(self):
            return cursor

    monkeypatch.setattr("app.agent_runtime.persistence._conn", lambda: Conn())

    assert _select_eval_timeline_node_id(
        7, {"nodeType": "DELIVERY", "labelContains": "交付"}
    ) == 901
    assert len(cursor.calls) == 2


def test_fulfillment_scorer_uses_stage_artifact_and_expected_human_decision():
    from app.api.routes import _score_eval_artifact

    case = {
        "expected_findings_json": json.dumps([{"title": "交付系统"}]),
        "expected_judgements_json": json.dumps([
            {"requirementContains": "交付", "proofStatus": "SUPPORTED"},
        ]),
        "expected_manual_result": "SATISFIED",
    }
    artifact = {
        "evaluationStages": {
            "FULFILLMENT_CHECK": {
                "requirements": [{
                    "requirement": "交付系统",
                    "proofStatus": "SUPPORTED",
                    "evidenceCitationIds": [1],
                    "aiSuggestion": {"status": "LLM_ENRICHED"},
                }],
                "content": {"manualResult": "SATISFIED", "requirements": []},
            }
        }
    }

    result = _score_eval_artifact(case, artifact, "FULFILLMENT_CHECK")
    assert result["highRecall"] == 1.0
    assert result["judgementAccuracy"] is None
    assert result["humanResultMatch"] == 1.0


def test_fulfillment_scorer_matches_requirement_text_and_deadline():
    from app.api.routes import _score_eval_artifact

    case = {
        "expected_findings_json": json.dumps([{
            "title": "交付:2026-03-06",
            "requirement": "提交交付清单、电子文件及验收申请",
        }]),
    }
    artifact = {
        "requirements": [{
            "requirement": "完成交付并提交验收申请",
            "deadline": "2026-03-06",
            "proofStatus": "SUPPORTED",
        }],
        "content": {"requirements": []},
    }

    result = _score_eval_artifact(case, artifact, "FULFILLMENT_CHECK")
    assert result["highRecall"] == 1.0


def test_fulfillment_eval_evidence_versions_follow_main_contract(monkeypatch):
    import app.agent_runtime.persistence as persistence
    from app.api.routes import _seed_eval_fulfillment_evidence

    class Cursor:
        def __init__(self):
            self.phase = ""
            self.lastrowid = 0
            self.created_versions = []

        def __enter__(self): return self
        def __exit__(self, *_): return None

        def execute(self, sql, params=()):
            if "MAX(version)" in sql:
                self.phase = "max"
            elif "SELECT id FROM contract_document" in sql:
                self.phase = "existing"
            elif "INSERT INTO contract_document" in sql:
                self.created_versions.append(params[3])
                self.lastrowid = 100 + len(self.created_versions)
            elif "contract_timeline_evidence_link" in sql:
                self.phase = "link"

        def fetchone(self):
            if self.phase == "max":
                return {"max_version": 1}
            if self.phase == "existing":
                return None
            return None

    cursor = Cursor()

    class Connection:
        def __enter__(self): return self
        def __exit__(self, *_): return None
        def cursor(self): return cursor
        def commit(self): pass

    monkeypatch.setattr(persistence, "_conn", lambda: Connection())
    ids = _seed_eval_fulfillment_evidence(7, 8, [
        {"content": "proof one"}, {"content": "proof two"},
    ])

    assert ids == [101, 102]
    assert cursor.created_versions == [2, 3]
