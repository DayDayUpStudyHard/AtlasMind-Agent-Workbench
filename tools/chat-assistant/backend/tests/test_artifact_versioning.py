"""PRD Phase 8 / §10: artifact version stamping.

Every published artifact carries a `versions` block freezing the runtime
stack that produced it — the acceptance requirement that every metric be
traceable to artifact + citation + version.
"""

from app.agent_runtime.graph.versioning import (
    ARTIFACT_SCHEMA_VERSION,
    stamp_artifact_versions,
)


def test_stamp_freezes_runtime_stack_from_state():
    state = {
        "graph_name": "contract-review-graph-v1",
        "graph_version": "v1",
        "model": "claude-test",
        "prompt_version": "contract-review-prompt-v1",
        "retrieval_version": "contract-hybrid-retrieval-v2",
        "rerank_version": "reranker-v1",
        "scorer_version": "eval-scorers-v2",
        "evidence_snapshot": {"hash": "snap-abc"},
    }
    artifact = {"reportType": "X"}
    stamp_artifact_versions(state, artifact)
    assert artifact["versions"] == {
        "artifactSchemaVersion": ARTIFACT_SCHEMA_VERSION,
        "snapshotHash": "snap-abc",
        "graphName": "contract-review-graph-v1",
        "graphVersion": "v1",
        "model": "claude-test",
        "promptVersion": "contract-review-prompt-v1",
        "retrievalVersion": "contract-hybrid-retrieval-v2",
        "rerankVersion": "reranker-v1",
        "scorerVersion": "eval-scorers-v2",
    }


def test_stamp_missing_versions_become_empty_strings():
    artifact = {}
    stamp_artifact_versions({}, artifact)
    versions = artifact["versions"]
    assert versions["graphName"] == ""
    assert versions["retrievalVersion"] == ""
    assert versions["rerankVersion"] == ""
    assert versions["scorerVersion"] == ""
    assert versions["snapshotHash"] == ""


def test_stamp_ignores_non_dict_evidence_snapshot():
    artifact = {}
    stamp_artifact_versions({"evidence_snapshot": ["not", "a", "dict"]}, artifact)
    assert artifact["versions"]["snapshotHash"] == ""


def test_stamp_preserves_existing_artifact_keys():
    artifact = {"reportType": "CONTRACT_REVIEW_REPORT", "findings": []}
    stamp_artifact_versions({}, artifact)
    assert artifact["reportType"] == "CONTRACT_REVIEW_REPORT"
    assert artifact["findings"] == []


def test_composers_stamp_versions_on_their_artifacts():
    """The four graph composers must all carry the §10 version block."""
    from app.agent_runtime.graph.nodes.artifact import compose_report
    from app.agent_runtime.graph.nodes.human_confirm import apply_human_result
    from app.agent_runtime.graph.timeline_extraction import compose_final_timeline

    risk = compose_report({
        "validated_findings": [],
        "case_snapshot": {},
        "coverage": {},
        "scoring": {},
        "analysis_workflow": {},
        "graph_name": "g", "graph_version": "v2",
    })
    assert "versions" in risk["artifact"]
    assert risk["artifact"]["versions"]["artifactSchemaVersion"] == ARTIFACT_SCHEMA_VERSION

    timeline = compose_final_timeline({
        "timeline_scope": {"documentId": 1, "documentVersion": 1},
        "timeline_candidates": [],
        "timeline_validation": {},
        "timeline_audit": {},
    })
    assert "versions" in timeline["artifact"]

    fulfillment = apply_human_result({
        "manual_result": "PENDING",
        "note": "",
        "artifacts": {"judgements": [], "fulfillmentAssessment": {}},
        "evidence_snapshot": [],
        "citations": [],
        "task_input": {},
        "operator_id": "",
        "wait_state": {},
        "state_revision": 0,
    })
    assert "versions" in fulfillment["artifact"]
