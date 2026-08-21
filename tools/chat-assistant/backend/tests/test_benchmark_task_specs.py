import pytest

from app.agent_runtime.evaluation.benchmark import BenchmarkDatasetError, load_benchmark_dataset
from app.agent_runtime.evaluation.metrics import build_release_gate
from app.agent_runtime.evaluation.specs import get_benchmark_spec


@pytest.mark.parametrize(
    ("task_type", "plan", "primary_metric"),
    [
        ("CONTRACT_INTAKE", ("CONTRACT_ELEMENT_EXTRACTION",), "fieldAccuracy"),
        ("CONTRACT_ELEMENT_EXTRACTION", ("CONTRACT_ELEMENT_EXTRACTION",), "fieldRecall"),
        ("TIMELINE_EXTRACTION", ("TIMELINE_EXTRACTION",), "nodeRecall"),
        ("CONTRACT_REVIEW", ("CONTRACT_REVIEW",), "riskRecall"),
        ("FULFILLMENT_CHECK", ("TIMELINE_EXTRACTION", "FULFILLMENT_CHECK"), "judgementAccuracy"),
    ],
)
def test_core_task_specs_own_their_execution_and_primary_metric(task_type, plan, primary_metric):
    spec = get_benchmark_spec(task_type)
    assert spec.task_plan == plan
    assert spec.primary_metric == primary_metric
    assert primary_metric in {metric.key for metric in spec.metrics}


def test_v2_release_gate_blocks_provisional_labels_before_quality_thresholds():
    spec = get_benchmark_spec("TIMELINE_EXTRACTION")
    result = build_release_gate({
        "benchmarkSchemaVersion": 2,
        "benchmarkTaskType": spec.task_type,
        "metricCaseCount": 12,
        "approvedCaseCount": 0,
        "provisionalCaseCount": 12,
        "resultValid": True,
        "environment": {"environmentStatus": "READY"},
        "taskMetrics": {metric.key: metric.threshold for metric in spec.metrics},
    }, status="COMPLETED")
    assert result["status"] == "BLOCKED"
    assert "PROVISIONAL_GOLD_LABELS" in result["blockingReasons"]


def test_v2_release_gate_uses_task_metric_not_risk_recall():
    spec = get_benchmark_spec("FULFILLMENT_CHECK")
    metrics = {metric.key: metric.threshold for metric in spec.metrics}
    result = build_release_gate({
        "benchmarkSchemaVersion": 2,
        "benchmarkTaskType": spec.task_type,
        "metricCaseCount": 10,
        "approvedCaseCount": 10,
        "provisionalCaseCount": 0,
        "resultValid": True,
        "highRiskRecall": 0.0,
        "environment": {"environmentStatus": "READY"},
        "taskMetrics": metrics,
    }, status="COMPLETED")
    assert result["status"] == "PASSED"
    assert result["taskType"] == "FULFILLMENT_CHECK"


def test_v2_file_benchmark_rejects_missing_task_output(tmp_path):
    (tmp_path / "manifest.yaml").write_text("""
schemaVersion: 2
id: timeline-smoke
name: Timeline smoke
version: v1
taskType: TIMELINE_EXTRACTION
labelStatus: CANDIDATE
caseDirectory: cases
""", encoding="utf-8")
    cases = tmp_path / "cases"
    cases.mkdir()
    (cases / "case.yaml").write_text("""
caseId: TL-001
contractText: test contract
expected:
  elements: []
""", encoding="utf-8")
    with pytest.raises(BenchmarkDatasetError, match="timelineNodes"):
        load_benchmark_dataset(tmp_path)


def test_v2_file_benchmark_accepts_candidate_timeline_case(tmp_path):
    (tmp_path / "manifest.yaml").write_text("""
schemaVersion: 2
id: timeline-smoke
name: Timeline smoke
version: v1
taskType: TIMELINE_EXTRACTION
labelStatus: CANDIDATE
caseDirectory: cases
""", encoding="utf-8")
    cases = tmp_path / "cases"
    cases.mkdir()
    (cases / "case.yaml").write_text("""
caseId: TL-001
contractText: test contract
expected:
  timelineNodes:
    - title: 交付:2026-01-01
annotationStatus: CANDIDATE
""", encoding="utf-8")
    dataset = load_benchmark_dataset(tmp_path)
    assert dataset.report()["labelStatus"] == "CANDIDATE"
    assert dataset.cases[0].raw["taskType"] == "TIMELINE_EXTRACTION"
