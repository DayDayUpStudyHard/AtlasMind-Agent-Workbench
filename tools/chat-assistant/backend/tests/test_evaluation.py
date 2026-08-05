"""Tests for the evaluation framework."""

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
