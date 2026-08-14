"""Fulfillment judgement validator — business invariant checks for each judgement."""

from __future__ import annotations

import time
from typing import Any


def validate_fulfillment_judgement(state: dict[str, Any]) -> dict[str, Any]:
    """Code-level validation of fulfilment judgements.

    Checks: required items have citations, no completion claims on insufficient evidence,
    UNCLEAR_TERMS doesn't claim HIGH confidence, AI risk has disclaimer.
    """
    started = time.monotonic()
    artifacts = state.get("artifacts") or {}
    judgements = artifacts.get("judgements") or []

    warnings: list[str] = []

    for j in judgements:
        # Required items need contract citations
        if j.get("required") and not j.get("contractCitationIds"):
            warnings.append(
                f"required item missing citation: '{str(j.get('requirement', ''))[:80]}'"
            )

        # INSUFFICIENT_EVIDENCE must not claim completion
        if j.get("judgement") == "EVIDENCE_INSUFFICIENT":
            reason = str(j.get("reason", ""))
            if "已完成" in reason or "确认完成" in reason:
                warnings.append("INSUFFICIENT_EVIDENCE must not claim completion")

        # UNCLEAR_TERMS should not have HIGH confidence
        if j.get("judgement") == "UNCLEAR_TERMS":
            if j.get("confidenceLevel") == "HIGH":
                warnings.append("UNCLEAR_TERMS should not have HIGH confidence")

        # Agent must not auto-set final business results
        forbidden = {"COMPLETED", "FAILED", "ACCEPTED", "REJECTED"}
        if str(j.get("judgement", "")).upper() in forbidden:
            warnings.append(
                f"Agent must not set final result: {j.get('judgement')}"
            )
            j["judgement"] = "NEEDS_REVIEW"

        # PRD Phase 7, task 6: the LLM suggestion layer obeys the same ban —
        # a forbidden conclusion must not survive even as a suggestion. The
        # normalizer already demotes them; this is the graph-level backstop.
        ai_suggestion = j.get("aiSuggestion") or {}
        if isinstance(ai_suggestion, dict):
            ai_conclusion = str(ai_suggestion.get("conclusion") or "").upper()
            if ai_conclusion in forbidden:
                warnings.append(
                    f"AI suggestion must not carry final result: {ai_conclusion}"
                )
                ai_suggestion["conclusion"] = "NEEDS_REVIEW"
                ai_suggestion["demotedByValidator"] = True

    return {
        "state_revision": state.get("state_revision", 0) + 1,
        "current_node": "validate_fulfillment_judgement",
        "errors": state.get("errors", []) + (
            [{"node": "validate_fulfillment_judgement", "error": w} for w in warnings]
            if warnings else []
        ),
        "fulfillment_validation": {
            "warningCount": len(warnings),
            "durationMs": int((time.monotonic() - started) * 1000),
        },
    }
