import asyncio

from app.agent_runtime.api_models import AgentTaskContext
from app.agent_runtime.runtime import LegacyHarnessAdapter


def _context() -> AgentTaskContext:
    return AgentTaskContext(
        run_id=3,
        project_id=4,
        task_type="CONTRACT_REVIEW",
        question="",
        subject_type="CONTRACT_CASE",
        subject_id=4,
        project={},
        task_input={},
    )


def test_legacy_adapter_preserves_limited_status_and_diagnostics():
    class LimitedRunner:
        async def execute(self, _context):
            return {
                "rawArtifact": {
                    "analysisMode": "LIMITED",
                    "title": "[范围受限] 技术服务合同审查报告",
                },
                "reflection": {
                    "adequate": False,
                    "domains": {
                        "PAYMENT": {"covered": False, "issues": ["付款条款证据不足"]},
                        "LIABILITY": {"covered": True, "issues": []},
                    },
                    "missingEvidence": ["制度依据"],
                    "retried": True,
                },
            }

    result = asyncio.run(LegacyHarnessAdapter(LimitedRunner()).run(_context()))

    assert result.status == "LIMITED"
    diagnostics = result.graph_info["limitedDiagnostics"]
    assert diagnostics["workUnitId"] == "CONTRACT_REVIEW"
    assert diagnostics["missingCheckItems"] == ["PAYMENT", "付款条款证据不足"]
    assert diagnostics["missingSourceTypes"] == ["制度依据"]
    assert diagnostics["retried"] is True
    assert diagnostics["exceeded"] == []
    assert diagnostics["reasons"] == ["COVERAGE"]
