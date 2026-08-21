"""Evaluation metrics — computes aggregate statistics from eval run results."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from .specs import get_benchmark_spec, normalize_task_type


RELEASE_GATE_VERSION = "release-gate-v4"
LEGACY_RELEASE_GATE_VERSION = "release-gate-v1"
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
    task_type: str | None = None,
) -> dict[str, Any]:
    """Return a stable, versioned release decision for a completed run.

    Quality failures and operational blockers are kept separate so callers can
    distinguish a model-quality regression from an invalid/incomplete run.
    """
    raw_task_type = task_type or summary.get("benchmarkTaskType") or summary.get("datasetType")
    try:
        spec = get_benchmark_spec(raw_task_type or "CONTRACT_REVIEW")
    except ValueError:
        spec = get_benchmark_spec("CONTRACT_REVIEW")
    # Existing schema-v1 runs retain the historical risk gate so frozen
    # baseline reports remain comparable. Schema-v2 uses task-owned metrics.
    schema_v2 = int(summary.get("benchmarkSchemaVersion") or 1) >= 2
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

    if schema_v2:
        provisional_count = int(summary.get("provisionalCaseCount") or 0)
        approved_count = int(summary.get("approvedCaseCount") or 0)
        if provisional_count:
            blocking_reasons.append("PROVISIONAL_GOLD_LABELS")
        if approved_count < spec.minimum_approved_cases:
            blocking_reasons.append(
                f"INSUFFICIENT_APPROVED_CASES:{approved_count}/{spec.minimum_approved_cases}"
            )

    legacy_values = {
        "highRiskRecall": float(summary.get("highRiskRecall") or 0),
        "dualCitationRate": float(summary.get("dualCitationRate") or 0),
        "falsePositiveRate": float(summary.get("falsePositiveRate") or 0),
        "limitedReportRate": float(summary.get("limitedReportRate") or 0),
    }
    task_metrics = summary.get("taskMetrics")
    if not isinstance(task_metrics, Mapping):
        task_metrics = {}
    metric_denominators = summary.get("metricDenominators")
    if not isinstance(metric_denominators, Mapping):
        metric_denominators = {}
    failures: list[dict[str, Any]] = []
    unobserved_metrics: list[str] = []

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

    if not schema_v2:
        values = legacy_values
        lower_bound("highRiskRecall", "highRiskRecallMin")
        lower_bound("dualCitationRate", "dualCitationRateMin")
        upper_bound("falsePositiveRate", "falsePositiveRateMax")
        upper_bound("limitedReportRate", "limitedReportRateMax")
    else:
        for metric in spec.metrics:
            if not metric.release or metric.threshold is None:
                continue
            value = task_metrics.get(metric.key)
            if value is None:
                if metric.key in metric_denominators and int(metric_denominators.get(metric.key) or 0) == 0:
                    unobserved_metrics.append(metric.key)
                    continue
                failures.append({
                    "metric": metric.key,
                    "actual": None,
                    "operator": metric.operator,
                    "threshold": metric.threshold,
                    "message": f"{metric.label} 未观测",
                })
                continue
            actual = float(value)
            passed_metric = actual >= float(metric.threshold) if metric.operator == ">=" else actual <= float(metric.threshold)
            if not passed_metric:
                failures.append({
                    "metric": metric.key,
                    "label": metric.label,
                    "actual": actual,
                    "operator": metric.operator,
                    "threshold": metric.threshold,
                    "message": f"{metric.label} {actual:.4f} {metric.operator} {float(metric.threshold):.4f} 未满足",
                })

    execution_status = "COMPLETED"
    if normalized_status in {"QUEUED", "PRECHECKING", "RUNNING"}:
        execution_status = "RUNNING"
    elif normalized_status == "CANCELLED":
        execution_status = "CANCELLED"
    elif normalized_status == "ENVIRONMENT_UNAVAILABLE" or env_status == "UNAVAILABLE":
        execution_status = "ENVIRONMENT_UNAVAILABLE"
    elif normalized_status in {"FAILED", "DEGRADED"} and not result_valid:
        execution_status = "FAILED"

    quality_status = "NOT_EVALUATED" if not summary.get("metricCaseCount", summary.get("caseCount", 0)) else (
        "PASSED" if not failures else "FAILED"
    )
    if schema_v2:
        gold_status = "APPROVED" if (
            int(summary.get("provisionalCaseCount") or 0) == 0
            and int(summary.get("approvedCaseCount") or 0) >= spec.minimum_approved_cases
        ) else ("PARTIAL" if int(summary.get("approvedCaseCount") or 0) else "PROVISIONAL")
    else:
        gold_status = "LEGACY"
    limited_impact = int(summary.get("limitedImpactCount") or 0)
    if limited_impact:
        blocking_reasons.append("LIMITED_TARGET_DOMAIN")
    publish_status = "PUBLISHABLE" if (
        execution_status == "COMPLETED"
        and quality_status == "PASSED"
        and gold_status in {"APPROVED", "LEGACY"}
        and not blocking_reasons
    ) else "BLOCKED"
    passed = publish_status == "PUBLISHABLE"
    displayed_thresholds = (
        {metric.key: metric.threshold for metric in spec.metrics if metric.threshold is not None}
        if schema_v2 else limits
    )
    return {
        "passed": passed,
        "status": "PASSED" if passed else ("BLOCKED" if blocking_reasons else "FAILED"),
        "thresholdVersion": RELEASE_GATE_VERSION if schema_v2 else LEGACY_RELEASE_GATE_VERSION,
        "taskType": spec.task_type,
        "taskLabel": spec.label,
        "thresholds": displayed_thresholds,
        "failures": failures,
        "unobservedMetrics": unobserved_metrics,
        "blockingReasons": blocking_reasons,
        "evaluated": execution_status == "COMPLETED" and bool(summary.get("metricCaseCount", summary.get("caseCount", 0))),
        "executionStatus": execution_status,
        "qualityStatus": quality_status,
        "goldStatus": gold_status,
        "publishStatus": publish_status,
        "limitedImpactCount": limited_impact,
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
