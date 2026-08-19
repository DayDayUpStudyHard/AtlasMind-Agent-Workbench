"""Tests for file-backed benchmark P0 contracts."""

from __future__ import annotations

from pathlib import Path

import pytest


def _write_dataset(root: Path, *, contract_text: str = "合同正文") -> Path:
    (root / "cases").mkdir(parents=True)
    (root / "manifest.yaml").write_text(
        """schemaVersion: 1
id: sample-review-v1
name: Sample review
version: v1
taskType: CONTRACT_REVIEW
caseDirectory: cases
""",
        encoding="utf-8",
    )
    (root / "cases" / "b.yaml").write_text(
        f"""caseId: CR-002
contractText: {contract_text}
expectedFindings:
  - title: payment risk
    severity: high
""",
        encoding="utf-8",
    )
    (root / "cases" / "a.yaml").write_text(
        """caseId: CR-001
contractText: another contract
expectedFindings:
  - title: acceptance risk
    severity: HIGH
""",
        encoding="utf-8",
    )
    return root


def test_file_backed_benchmark_loads_with_stable_case_order_and_hash(tmp_path):
    from app.agent_runtime.evaluation.benchmark import load_benchmark_dataset

    dataset = load_benchmark_dataset(_write_dataset(tmp_path / "first"))
    duplicate = load_benchmark_dataset(_write_dataset(tmp_path / "second"))

    assert [case.case_id for case in dataset.cases] == ["CR-001", "CR-002"]
    assert dataset.dataset_hash == duplicate.dataset_hash
    assert dataset.report()["caseCount"] == 2


def test_file_backed_benchmark_hash_changes_with_contract_or_expectation(tmp_path):
    from app.agent_runtime.evaluation.benchmark import load_benchmark_dataset

    first = load_benchmark_dataset(_write_dataset(tmp_path / "first", contract_text="版本 A"))
    second = load_benchmark_dataset(_write_dataset(tmp_path / "second", contract_text="版本 B"))

    assert first.dataset_hash != second.dataset_hash


def test_file_backed_benchmark_rejects_invalid_case(tmp_path):
    from app.agent_runtime.evaluation.benchmark import BenchmarkDatasetError, load_benchmark_dataset

    root = _write_dataset(tmp_path / "invalid")
    (root / "cases" / "a.yaml").write_text(
        "caseId: CR-001\ncontractText: text\nexpectedFindings: not-a-list\n",
        encoding="utf-8",
    )

    with pytest.raises(BenchmarkDatasetError, match="expectedFindings"):
        load_benchmark_dataset(root)


def test_experiment_snapshot_is_stable_when_features_have_different_key_order(tmp_path, monkeypatch):
    from app.agent_runtime.evaluation.benchmark import load_benchmark_dataset
    from app.agent_runtime.evaluation.cli import build_experiment_snapshot
    import app.agent_runtime.evaluation.cli as cli

    monkeypatch.setattr(cli, "_git_commit", lambda: "abc123")
    dataset = load_benchmark_dataset(_write_dataset(tmp_path / "dataset"))
    first = build_experiment_snapshot(
        dataset, engine="langgraph", profile="live", features={"temperature": 0, "rerank": True}, baseline_run_id=7
    )
    second = build_experiment_snapshot(
        dataset, engine="langgraph", profile="live", features={"rerank": True, "temperature": 0}, baseline_run_id=7
    )

    assert first["configHash"] == second["configHash"]


def test_compare_rejects_mismatched_dataset_or_scorer():
    from app.agent_runtime.evaluation.benchmark import BenchmarkDatasetError
    from app.agent_runtime.evaluation.cli import compare_snapshots

    left = {
        "runId": 1,
        "datasetHash": "a",
        "scorerVersion": "scorer-v1",
        "summary": {"highRiskRecall": 0.8},
    }
    right = {
        "runId": 2,
        "datasetHash": "b",
        "scorerVersion": "scorer-v1",
        "summary": {"highRiskRecall": 0.9},
    }

    with pytest.raises(BenchmarkDatasetError, match="datasetHash"):
        compare_snapshots(left, right)

    comparison = compare_snapshots(left, right, allow_incompatible=True)
    assert comparison["compatible"] is False
    assert comparison["metrics"]["highRiskRecall"]["delta"] == 0.1
