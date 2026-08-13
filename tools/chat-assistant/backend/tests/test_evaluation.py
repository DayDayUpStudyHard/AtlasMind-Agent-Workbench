"""Tests for the evaluation framework."""

import json
import os
import sys
from pathlib import Path

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


def test_only_current_failed_stage_is_marked_failed():
    from app.api.routes import _failed_eval_stage_run_ids

    assert _failed_eval_stage_run_ids(
        [101, 102, 103],
        completed_run_ids={101, 102},
    ) == [103]


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
