"""Report validation — Pydantic schema validation + business-invariant checks.

Called before a report artifact reaches MySqlReportStore.save_report().
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from pydantic import ValidationError as PydanticValidationError

from .review import ContractReviewArtifact
from .fulfillment import FulfillmentArtifact

logger = logging.getLogger(__name__)


@dataclass
class ReportValidationResult:
    """Result of validating a report artifact."""

    valid: bool
    report_type: str = ""
    schema_errors: list[str] = field(default_factory=list)
    business_warnings: list[str] = field(default_factory=list)
    repair_attempted: bool = False
    repaired_artifact: dict[str, Any] | None = None

    @property
    def has_warnings(self) -> bool:
        return len(self.business_warnings) > 0


def validate_report(artifact: dict[str, Any]) -> ReportValidationResult:
    """Validate a report artifact against Pydantic schemas and business invariants.

    Returns a ReportValidationResult. If valid=True, the artifact is safe to
    pass to MySqlReportStore.save_report(). If valid=False, schema_errors
    explains what failed.
    """
    report_type = str(artifact.get("reportType") or "")

    # ── Schema validation ──────────────────────────────────────────
    try:
        if report_type in ("CONTRACT_REVIEW_REPORT", ""):
            model = ContractReviewArtifact.model_validate(artifact)
        elif report_type == "FULFILLMENT_REPORT":
            model = FulfillmentArtifact.model_validate(artifact)
        else:
            # Unknown report type — accept as-is, no schema to apply
            return ReportValidationResult(valid=True, report_type=report_type)
    except PydanticValidationError as exc:
        errors = [f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in exc.errors()]
        logger.warning("Report schema validation failed: %s", errors)
        return ReportValidationResult(
            valid=False,
            report_type=report_type,
            schema_errors=errors,
        )

    # ── Business-invariant checks ───────────────────────────────────
    warnings: list[str] = []
    model_dict = model.model_dump(by_alias=True)

    if report_type in ("CONTRACT_REVIEW_REPORT", ""):
        warnings.extend(_check_review_business_rules(model_dict))
    elif report_type == "FULFILLMENT_REPORT":
        warnings.extend(_check_fulfillment_business_rules(model_dict))

    return ReportValidationResult(
        valid=True,
        report_type=report_type,
        business_warnings=warnings,
    )


def _check_review_business_rules(artifact: dict[str, Any]) -> list[str]:
    """Business invariants for contract review reports."""
    warnings: list[str] = []

    findings = artifact.get("findings") or []
    high_findings = [f for f in findings if f.get("severity") == "HIGH"]

    # HIGH severity findings must have dual citations
    for finding in high_findings:
        title = finding.get("title", "unnamed")
        has_contract = bool(
            finding.get("contractCitation")
            or finding.get("contractCitationIds")
        )
        has_policy = bool(
            finding.get("policyCitation")
            or finding.get("policyCitationIds")
        )
        if not has_contract and not has_policy:
            warnings.append(
                f"HIGH severity finding '{title}' has no contract or policy citation"
            )
        elif not has_contract:
            warnings.append(
                f"HIGH severity finding '{title}' missing contract citation"
            )
        elif not has_policy:
            warnings.append(
                f"HIGH severity finding '{title}' missing policy citation"
            )

    # Analysis mode consistency
    mode = artifact.get("analysisMode", "FULL")
    if mode == "LIMITED" and not artifact.get("coverageLimitation"):
        warnings.append("LIMITED analysis mode set but coverageLimitation is empty")

    return warnings


def _check_fulfillment_business_rules(artifact: dict[str, Any]) -> list[str]:
    """Business invariants for fulfillment check reports."""
    warnings: list[str] = []

    requirements = artifact.get("requirements") or []

    # Required items must have contract citations
    for req in requirements:
        if req.get("required") and not req.get("contractCitationIds"):
            warnings.append(
                f"required fulfillment item missing contract citation: "
                f"'{str(req.get('requirement', ''))[:80]}'"
            )

    # Can't have INSUFFICIENT_EVIDENCE and claim completion
    conclusion = artifact.get("conclusion", "")
    if conclusion == "INSUFFICIENT_EVIDENCE":
        summary = str(artifact.get("summary", ""))
        if "已完成" in summary or "确认完成" in summary:
            warnings.append(
                "INSUFFICIENT_EVIDENCE conclusion must not claim completion in summary"
            )

    # UNCLEAR_TERMS should not have HIGH confidence
    if conclusion == "UNCLEAR_TERMS":
        confidence = artifact.get("confidenceLevel", "")
        if confidence == "HIGH":
            warnings.append(
                "UNCLEAR_TERMS conclusion should not have HIGH confidence"
            )

    # AI risk must have disclaimer
    ai_risk = artifact.get("aiRisk", "")
    if ai_risk and "仅供参考" not in ai_risk:
        warnings.append("aiRisk missing '仅供参考' disclaimer")

    # Explicit consequence must not be AI-inferred
    explicit = artifact.get("explicitConsequence", "")
    if explicit and "AI 推断" in explicit:
        warnings.append("explicitConsequence contains AI-inferred content")

    return warnings
