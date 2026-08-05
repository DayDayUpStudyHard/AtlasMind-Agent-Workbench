from app.agent_runtime.api_models import AgentTaskContext
from app.agent_runtime.runner import AgentRunner


def _context(task_type: str, task_input: dict) -> AgentTaskContext:
    return AgentTaskContext(
        run_id=17,
        project_id=41,
        task_type=task_type,
        question="",
        subject_type="CONTRACT_CASE" if task_type.startswith("CONTRACT") else "PROJECT",
        subject_id=41,
        task_input=task_input,
    )


def test_legacy_contract_artifact_keeps_analysis_workflow_metadata():
    workflow = {
        "workflowId": 9,
        "stage": "RISK_REVIEW",
        "documentVersion": 3,
        "evidenceSnapshotHash": "sha256:abc123",
    }
    artifact = {"content": {"existing": True}}

    result = AgentRunner._attach_contract_analysis_metadata(
        _context("CONTRACT_REVIEW", {"analysisWorkflow": workflow}),
        artifact,
    )

    assert result["analysisWorkflow"] == workflow
    assert result["evidenceHash"] == "sha256:abc123"
    assert result["content"]["analysisWorkflow"] == workflow
    assert result["content"]["evidenceHash"] == "sha256:abc123"


def test_legacy_limited_contract_artifact_is_not_overwritten():
    workflow = {"workflowId": 10, "evidenceSnapshotHash": "sha256:def456"}
    artifact = {
        "analysisMode": "LIMITED",
        "analysisWorkflow": {"workflowId": 1},
        "evidenceHash": "sha256:old",
    }

    result = AgentRunner._attach_contract_analysis_metadata(
        _context("CONTRACT_REVIEW", {"analysisWorkflow": workflow}),
        artifact,
    )

    assert result["analysisMode"] == "LIMITED"
    assert result["analysisWorkflow"] == {"workflowId": 1}
    assert result["evidenceHash"] == "sha256:old"


def test_project_artifact_does_not_receive_contract_metadata():
    artifact = {"title": "Project report"}

    result = AgentRunner._attach_contract_analysis_metadata(
        _context("HEALTH_ANALYSIS", {"analysisWorkflow": {"workflowId": 9}}),
        artifact,
    )

    assert result == artifact
