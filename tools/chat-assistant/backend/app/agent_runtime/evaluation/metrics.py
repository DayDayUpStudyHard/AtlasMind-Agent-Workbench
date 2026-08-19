"""Evaluation metrics — computes aggregate statistics from eval run results."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping


RELEASE_GATE_VERSION = "release-gate-v1"
DEFAULT_RELEASE_THRESHOLDS = {
    "highRiskRecallMin": 0.90,
    "dualCitationRateMin": 0.95,
    "falsePositiveRateMax": 0.03,
    "limitedReportRateMax": 0.0,
}


def build_release_gate(
    summary: Mapping[str, Any],
    *,
    status: str | None = None,
    thresholds: Mapping[str, float] | None = None,
) -> dict[str, Any]:
    """Return a stable, versioned release decision for a completed run.

    Quality failures and operational blockers are kept separate so callers can
    distinguish a model-quality regression from an invalid/incomplete run.
    """
    limits = dict(DEFAULT_RELEASE_THRESHOLDS)
    if thresholds:
        limits.update({key: float(value) for key, value in thresholds.items()})

    env = summary.get("environment")
    env_status = str(env.get("environmentStatus") or "").upper() if isinstance(env, Mapping) else ""
    normalized_status = str(status or summary.get("status") or "").upper()
    result_valid = bool(summary.get("resultValid"))
    blocking_reasons: list[str] = []
    if normalized_status == "ENVIRONMENT_UNAVAILABLE" or env_status == "UNAVAILABLE":
        blocking_reasons.append("ENVIRONMENT_UNAVAILABLE")
    if not result_valid:
        blocking_reasons.append("RESULT_INVALID")
    if not summary.get("metricCaseCount", summary.get("caseCount", 0)):
        blocking_reasons.append("NO_SCORED_CASES")

    values = {
        "highRiskRecall": float(summary.get("highRiskRecall") or 0),
        "dualCitationRate": float(summary.get("dualCitationRate") or 0),
        "falsePositiveRate": float(summary.get("falsePositiveRate") or 0),
        "limitedReportRate": float(summary.get("limitedReportRate") or 0),
    }
    failures: list[dict[str, Any]] = []

    def lower_bound(metric: str, threshold_key: str) -> None:
        if values[metric] < limits[threshold_key]:
            failures.append({
                "metric": metric,
                "actual": values[metric],
                "operator": ">=",
                "threshold": limits[threshold_key],
                "message": f"{metric} {values[metric]:.4f} < {limits[threshold_key]:.4f}",
            })

    def upper_bound(metric: str, threshold_key: str) -> None:
        if values[metric] > limits[threshold_key]:
            failures.append({
                "metric": metric,
                "actual": values[metric],
                "operator": "<=",
                "threshold": limits[threshold_key],
                "message": f"{metric} {values[metric]:.4f} > {limits[threshold_key]:.4f}",
            })

    lower_bound("highRiskRecall", "highRiskRecallMin")
    lower_bound("dualCitationRate", "dualCitationRateMin")
    upper_bound("falsePositiveRate", "falsePositiveRateMax")
    upper_bound("limitedReportRate", "limitedReportRateMax")

    passed = not blocking_reasons and not failures
    return {
        "passed": passed,
        "status": "PASSED" if passed else ("BLOCKED" if blocking_reasons else "FAILED"),
        "thresholdVersion": RELEASE_GATE_VERSION,
        "thresholds": limits,
        "failures": failures,
        "blockingReasons": blocking_reasons,
        "evaluated": not blocking_reasons,
    }


@dataclass
class EvaluationMetrics:
    """Aggregate metrics computed across all eval cases."""

    total_cases: int = 0
    successful_cases: int = 0
    failed_cases: int = 0

    # Risk recall
    high_risk_recall: float = 0.0  # Fraction of expected HIGH findings found
    average_risk_precision: float = 0.0

    # Citation quality
    dual_citation_rate: float = 0.0  # Fraction of findings with both citations
    average_citation_count: float = 0.0

    # Report quality
    schema_valid_rate: float = 0.0
    limited_report_rate: float = 0.0  # Fraction of reports with analysisMode=LIMITED
    false_positive_rate: float = 0.0

    # Per-case details
    per_case: list[dict[str, Any]] = field(default_factory=list)

    @classmethod
    def compute_summary(cls, results: list) -> "EvaluationMetrics":
        """Compute aggregate metrics from a list of EvalRunResult objects."""
        if not results:
            return cls()

        successful = [r for r in results if r.success]
        metrics = cls(
            total_cases=len(results),
            successful_cases=len(successful),
            failed_cases=len(results) - len(successful),
        )

        recalls = []
        dual_rates = []
        false_positives_total = 0
        limited_count = 0

        for r in successful:
            m = r.metrics or {}
            recalls.append(m.get("highRecall", 0))
            dual_rates.append(m.get("dualCitationRate", 0))
            false_positives_total += m.get("falsePositives", 0)
            if m.get("analysisMode") == "LIMITED":
                limited_count += 1

            metrics.per_case.append({
                "caseId": r.case_id,
                "expectedCount": m.get("expectedCount", 0),
                "actualCount": m.get("actualCount", 0),
                "highRecall": m.get("highRecall", 0),
                "dualCitationRate": m.get("dualCitationRate", 0),
                "analysisMode": m.get("analysisMode", "FULL"),
                "riskScore": m.get("riskScore", 0),
            })

        if recalls:
            metrics.high_risk_recall = round(
                sum(recalls) / len(recalls), 3
            )
        if dual_rates:
            metrics.dual_citation_rate = round(
                sum(dual_rates) / len(dual_rates), 3
            )
        metrics.false_positive_rate = round(
            false_positives_total / max(len(successful), 1), 3
        )
        metrics.limited_report_rate = round(
            limited_count / max(len(successful), 1), 3
        )
        schema_values = [
            m.get("schemaValidRate", 1.0 if m.get("schemaValid", True) else 0.0)
            for r in successful
            for m in [r.metrics or {}]
        ]
        if schema_values:
            metrics.schema_valid_rate = round(sum(schema_values) / len(schema_values), 3)

        return metrics

    def to_dict(self) -> dict[str, Any]:
        return {
            "totalCases": self.total_cases,
            "successfulCases": self.successful_cases,
            "failedCases": self.failed_cases,
            "highRiskRecall": self.high_risk_recall,
            "dualCitationRate": self.dual_citation_rate,
            "falsePositiveRate": self.false_positive_rate,
            "limitedReportRate": self.limited_report_rate,
            "schemaValidRate": self.schema_valid_rate,
            "perCase": self.per_case,
            "releaseGate": build_release_gate({
                "highRiskRecall": self.high_risk_recall,
                "dualCitationRate": self.dual_citation_rate,
                "falsePositiveRate": self.false_positive_rate,
                "limitedReportRate": self.limited_report_rate,
                "metricCaseCount": self.successful_cases,
                "resultValid": self.failed_cases == 0 and self.successful_cases > 0,
            }),
        }

    def meets_thresholds(
        self,
        min_high_recall: float = 0.90,
        min_dual_citation: float = 0.95,
        max_false_positive: float = 0.03,
    ) -> tuple[bool, list[str]]:
        """Check if metrics meet release thresholds. Returns (passed, failures)."""
        failures: list[str] = []
        if self.high_risk_recall < min_high_recall:
            failures.append(
                f"highRiskRecall {self.high_risk_recall} < {min_high_recall}"
            )
        if self.dual_citation_rate < min_dual_citation:
            failures.append(
                f"dualCitationRate {self.dual_citation_rate} < {min_dual_citation}"
            )
        if self.false_positive_rate > max_false_positive:
            failures.append(
                f"falsePositiveRate {self.false_positive_rate} > {max_false_positive}"
            )
        return len(failures) == 0, failures
