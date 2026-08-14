"""PRD Phase 7: fulfillment coverage audit — citation support, evidence rule
flags, AI suggestion quality and per-layer durations in one observable rollup
(Phase 8 acceptance: every metric traceable, no constant placeholders)."""

from __future__ import annotations

from typing import Any


def audit_fulfillment_coverage(state: dict[str, Any]) -> dict[str, Any]:
    """Aggregate the rule / LLM / validation layers into one audit block."""
    artifacts = state.get("artifacts") or {}
    judgements = [
        row for row in (artifacts.get("judgements") or []) if isinstance(row, dict)
    ]
    assessment = artifacts.get("fulfillmentAssessment") or {}
    evidence_rules = state.get("evidence_rules") or {}
    fulfillment_ai = state.get("fulfillment_ai") or {}
    fulfillment_validation = state.get("fulfillment_validation") or {}
    rerun_scope = state.get("rerun_scope") or {}

    total = len(judgements)
    with_contract_citation = sum(
        1 for row in judgements if row.get("contractCitationIds")
    )
    with_ai_suggestion = sum(
        1 for row in judgements if (row.get("aiSuggestion") or {}).get("conclusion")
    )
    hard_flag_count = sum(
        len((row.get("evidenceRuleFlags") or {}).get("hard") or []) for row in judgements
    )

    audit = {
        "auditVersion": "fulfillment-audit-v1",
        "totalRequirements": total,
        "citationSupportRate": round(with_contract_citation / total, 4) if total else 0.0,
        "aiSuggestionCoverageRate": round(with_ai_suggestion / total, 4) if total else 0.0,
        "evidenceRuleHardFlagCount": hard_flag_count,
        "evidenceRuleSummary": {
            "ruleVersion": evidence_rules.get("ruleVersion"),
            "documentCount": evidence_rules.get("documentCount", 0),
            "hardFlagCount": evidence_rules.get("hardFlagCount", 0),
            "softFlagCount": evidence_rules.get("softFlagCount", 0),
        },
        "aiSuggestion": {
            "status": fulfillment_ai.get("status"),
            "schemaErrors": fulfillment_ai.get("schemaErrors") or [],
        },
        "rerun": {
            "mode": rerun_scope.get("mode") or "ALL",
            "affectedRequirementIds": rerun_scope.get("affectedRequirementIds") or [],
            "changedEvidence": rerun_scope.get("changedEvidence") or [],
            "newEvidence": rerun_scope.get("newEvidence") or [],
            "removedEvidence": rerun_scope.get("removedEvidence") or [],
        },
        # Per-layer durations, same shape as the Phase 6 timeline DAG —
        # rules / LLM / validation must be observable separately.
        "stageDurationsMs": {
            "ruleLayer": evidence_rules.get("durationMs", 0),
            "llmLayer": fulfillment_ai.get("durationMs", 0),
            "validationLayer": fulfillment_validation.get("durationMs", 0),
        },
    }
    merged_assessment = dict(assessment)
    merged_assessment["audit"] = audit
    return {
        "state_revision": state.get("state_revision", 0) + 1,
        "current_node": "audit_fulfillment_coverage",
        "artifacts": {
            **artifacts,
            "fulfillmentAssessment": merged_assessment,
        },
        "observations": [{
            "callId": f"fulfillment-audit-{state.get('run_id', 0)}",
            "planStepId": "audit_fulfillment_coverage",
            "toolName": "auditFulfillmentCoverage",
            "arguments": {},
            "output": {
                "citationSupportRate": audit["citationSupportRate"],
                "aiSuggestionCoverageRate": audit["aiSuggestionCoverageRate"],
                "rerunMode": audit["rerun"]["mode"],
                "stageDurationsMs": audit["stageDurationsMs"],
            },
            "status": "DONE",
        }],
    }
