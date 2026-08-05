"""Claim Validator — 10 checks on findings before they enter the report."""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

# Known citation source type prefixes
_VALID_PREFIXES = (
    "CONTRACT_CLAUSE:", "KB_CHUNK:", "KB_DOCUMENT:",
    "STANDARD_CLAUSE:", "FULFILLMENT_DOCUMENT:",
)


def validate_claims(state: dict[str, Any]) -> dict[str, Any]:
    """Run 10 business-invariant checks on draft findings.

    Validation results per finding: PASS | NEED_MORE_EVIDENCE |
    DOWNGRADE_CONFIDENCE | REJECT_FINDING
    """
    draft_findings = state.get("draft_findings") or state.get("validated_findings") or []

    # Merge and deduplicate
    seen: set[str] = set()
    merged: list[dict] = []
    for f in draft_findings:
        key = f.get("findingKey") or f.get("title", "")
        if key not in seen:
            merged.append(f)
            seen.add(key)

    validated: list[dict] = []
    rejected: int = 0
    downgraded: int = 0

    for finding in merged:
        verdict, reasons = _validate_one(finding, state)
        finding["validationVerdict"] = verdict
        finding["validationReasons"] = reasons

        if verdict == "REJECT_FINDING":
            rejected += 1
            continue
        if verdict == "DOWNGRADE_CONFIDENCE":
            finding["confidenceLevel"] = "LOW"
            downgraded += 1

        validated.append(finding)

    logger.info(
        "Claim Validator: %d findings → %d validated (%d rejected, %d downgraded)",
        len(merged), len(validated), rejected, downgraded,
    )

    return {
        "state_revision": state.get("state_revision", 0) + 1,
        "current_node": "validate_claims",
        "validated_findings": validated,
        "coverage": state.get("coverage") or {
            "validatedCount": len(validated),
            "rejectedCount": rejected,
            "downgradedCount": downgraded,
        },
    }


def _validate_one(finding: dict, state: dict) -> tuple[str, list[str]]:
    """Run all 10 checks on one finding. Returns (verdict, reasons)."""
    reasons: list[str] = []
    has_fatal = False
    force_downgrade = False

    # Check 1: Citation IDs exist and have valid prefixes
    contract_ids = finding.get("contractCitationIds") or []
    policy_ids = finding.get("policyCitationIds") or []
    available_ids = {
        str(item.get("sourceId") or "") for item in state.get("citations") or []
        if isinstance(item, dict)
    }
    for cid in contract_ids + policy_ids:
        if isinstance(cid, str) and not cid.startswith(_VALID_PREFIXES):
            reasons.append(f"citation ID missing source prefix: {cid}")
            has_fatal = True
        elif available_ids and cid not in available_ids:
            reasons.append(f"citation ID was not returned by retrieval: {cid}")
            has_fatal = True

    # Check 2: HIGH severity must have contract evidence. Missing policy support
    # lowers confidence but does not hide a contract-grounded material risk.
    severity = str(finding.get("severity", "")).upper()
    if severity == "HIGH":
        if not contract_ids and not bool(finding.get("contractCitation")):
            reasons.append("HIGH severity finding missing contract citation")
            has_fatal = True
        if not policy_ids and not bool(finding.get("policyCitation")):
            reasons.append("HIGH severity finding missing policy citation")
            force_downgrade = True

    # Check 3: "contract not found" claims need clause inventory context
    claim = str(finding.get("claim") or finding.get("description") or "")
    if "未约定" in claim or "未发现" in claim or "缺少" in claim:
        reasons.append("negative claim — verify against full clause inventory")

    # Check 4: LLM must not modify deterministic fields
    if finding.get("riskScore") is not None or finding.get("scoringVersion") is not None:
        reasons.append("LLM attempted to set deterministic scoring field")
        finding.pop("riskScore", None)
        finding.pop("scoringVersion", None)
        finding.pop("evidenceHash", None)

    # Check 5: Findings must not duplicate
    # (handled in merge above)

    # Check 6: Advice must not be written as contract fact
    advice = str(finding.get("remediationAdvice") or "")
    if "合同约定" in advice or "合同明确规定" in advice:
        reasons.append("remediationAdvice reads like contract fact, not advice")

    # Check 7: Finding must have a title
    if not str(finding.get("title", "")).strip():
        reasons.append("finding missing title")
        has_fatal = True

    # Check 8: Clause type must be valid
    valid_types = {
        "LIABILITY", "PAYMENT", "CONFIDENTIALITY", "ACCEPTANCE",
        "TERMINATION", "IP", "DATA_PROTECTION", "OTHER",
    }
    if str(finding.get("clauseType", "")).upper() not in valid_types:
        reasons.append(f"invalid clauseType: {finding.get('clauseType')}")

    # Check 9: INSUFFICIENT_EVIDENCE must not claim completion
    if str(finding.get("sourceBasis", "")).upper() == "INSUFFICIENT_EVIDENCE":
        if "completed" in str(finding).lower() or "已完成" in str(finding):
            reasons.append("INSUFFICIENT_EVIDENCE must not claim completion")
            has_fatal = True

    # Check 10: AI risk must not go into contract consequences
    if finding.get("explicitConsequence") and "AI 推断" in str(finding.get("explicitConsequence", "")):
        reasons.append("explicitConsequence contains AI-inferred content")
        has_fatal = True
    if finding.get("explicitConsequence") and not contract_ids:
        reasons.append("explicitConsequence missing contract citation")
        has_fatal = True
    inferred = str(finding.get("inferredConsequence") or "")
    disclaimer = str(finding.get("inferredConsequenceDisclaimer") or "")
    if inferred and "AI 推断" not in disclaimer:
        finding["inferredConsequenceDisclaimer"] = "AI 推断，仅供参考，不代表合同约定"
        reasons.append("inferred consequence disclaimer restored by validator")

    if has_fatal:
        return "REJECT_FINDING", reasons
    if force_downgrade or len(reasons) >= 3:
        return "DOWNGRADE_CONFIDENCE", reasons
    if reasons:
        return "PASS", reasons  # PASS with warnings
    return "PASS", []
