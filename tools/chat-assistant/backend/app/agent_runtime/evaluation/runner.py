"""Evaluation runner — executes Agent against test cases and collects results."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from .dataset import EvalCase, EvaluationDataset
from .metrics import EvaluationMetrics

logger = logging.getLogger(__name__)


@dataclass
class EvalRunResult:
    """Result of evaluating one test case."""

    case_id: str
    success: bool
    error: str = ""
    artifact: dict[str, Any] | None = None
    findings: list[dict[str, Any]] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)


class EvaluationRunner:
    """Runs contract review against a dataset and computes metrics.

    Usage::

        dataset = EvaluationDataset("evaluation/datasets/v1").load()
        runner = EvaluationRunner(agent_runner, llm, tools, stores)
        results = await runner.run_dataset(dataset)
        summary = EvaluationMetrics.compute_summary(results)
    """

    def __init__(
        self,
        agent_runner,   # AgentRunner instance
        llm,            # LLMService instance
        tools,          # ContractToolRegistry
        run_store,
        trace_store,
        evidence_store,
        report_store,
        memory_store,
    ):
        self.agent_runner = agent_runner
        self.llm = llm
        self.tools = tools
        self.run_store = run_store
        self.trace_store = trace_store
        self.evidence_store = evidence_store
        self.report_store = report_store
        self.memory_store = memory_store

    async def run_case(self, case: EvalCase, run_id: int) -> EvalRunResult:
        """Run contract review for one eval case using a synthetic context.

        Note: This is a simplified eval runner that exercises the artifact
        generation path directly. For full end-to-end evaluation, use the
        actual agent run dispatch via the Java API.
        """
        from ..api_models import AgentTaskContext

        ctx = AgentTaskContext(
            run_id=run_id,
            project_id=0,
            task_type="CONTRACT_REVIEW",
            question=f"审查以下合同：{case.title or case.case_id}",
            subject_type="CONTRACT_CASE",
            subject_id=0,
            project={
                "id": 0,
                "title": case.title or case.case_id,
                "contractType": case.contract_type,
            },
            task_input={"evalCaseId": case.case_id},
        )

        try:
            result = await self.agent_runner.execute(ctx)
            artifact = result.get("rawArtifact") or {}
            findings = artifact.get("findings") or []
            metrics = self._compute_case_metrics(case, findings, artifact)
            return EvalRunResult(
                case_id=case.case_id,
                success=True,
                artifact=artifact,
                findings=findings,
                metrics=metrics,
            )
        except Exception as exc:
            logger.exception("Eval run failed for case %s", case.case_id)
            return EvalRunResult(
                case_id=case.case_id,
                success=False,
                error=str(exc),
            )

    async def run_dataset(self, dataset: list[EvalCase]) -> list[EvalRunResult]:
        """Run evaluation for all cases (sequential, not parallel)."""
        results: list[EvalRunResult] = []
        for i, case in enumerate(dataset):
            logger.info("Eval [%d/%d] %s", i + 1, len(dataset), case.case_id)
            result = await self.run_case(case, run_id=90000 + i)
            results.append(result)
        return results

    @staticmethod
    def _compute_case_metrics(
        case: EvalCase,
        actual_findings: list[dict[str, Any]],
        artifact: dict[str, Any],
    ) -> dict[str, Any]:
        """Compute per-case metrics by comparing actual vs expected findings."""
        expected_titles = {f.title.lower() for f in case.expected_findings}
        actual_titles = {
            str(f.get("title", "")).lower() for f in actual_findings
        }

        high_expected = {
            f.title.lower() for f in case.expected_findings if f.severity == "HIGH"
        }
        high_actual = {
            str(f.get("title", "")).lower()
            for f in actual_findings
            if str(f.get("severity", "")).upper() == "HIGH"
        }

        high_recall = (
            len(high_expected & high_actual) / len(high_expected)
            if high_expected else 1.0
        )

        # Check for false positives (things we should NOT find)
        should_not = {s.lower() for s in case.should_not_find}
        false_positives = sum(
            1 for t in actual_titles
            if any(s in t for s in should_not)
        )

        # Citation checks
        dual_cited = sum(
            1 for f in actual_findings
            if (f.get("contractCitation") or f.get("contractCitationIds"))
            and (f.get("policyCitation") or f.get("policyCitationIds"))
        )
        total_findings = max(len(actual_findings), 1)

        return {
            "expectedCount": len(case.expected_findings),
            "actualCount": len(actual_findings),
            "highRecall": round(high_recall, 3),
            "falsePositives": false_positives,
            "dualCitationRate": round(dual_cited / total_findings, 3),
            "analysisMode": artifact.get("analysisMode", "FULL"),
            "riskScore": artifact.get("riskScore") or artifact.get("risk_score") or 0,
        }
