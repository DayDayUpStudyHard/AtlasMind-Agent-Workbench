"""Evaluation metrics — computes aggregate statistics from eval run results."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


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
            "perCase": self.per_case,
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
