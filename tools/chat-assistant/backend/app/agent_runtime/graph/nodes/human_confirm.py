"""Human confirmation interrupt node for fulfillment checks.

Uses LangGraph interrupt() to pause execution until human confirms.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def wait_human_confirmation(state: dict[str, Any]) -> dict[str, Any]:
    """Interrupt point: save checkpoint, wait for human to confirm/reject/pend.

    The graph pauses here. Human action triggers resume via
    POST /internal/agent/run/{runId}/resume with ResumeCommand.
    """
    artifacts = state.get("artifacts") or {}
    judgements = artifacts.get("judgements") or []
    evidence_snapshot = []
    for observation in state.get("observations") or []:
        output = observation.get("output") or {}
        for item in output.get("evidenceDocuments") or []:
            if not isinstance(item, dict):
                continue
            evidence_snapshot.append({
                "documentId": item.get("documentId") or item.get("id"),
                "fileName": item.get("fileName") or "",
                "version": item.get("version"),
                "contentHash": item.get("contentHash"),
                "snippet": item.get("snippet") or "",
                "matchedTerms": item.get("matchedTerms") or [],
                "matchReason": item.get("matchReason") or "",
            })

    # Build structured wait state for frontend display
    wait_state = {
        "type": "WAITING_HUMAN_CONFIRMATION",
        "message": f"履约核验完成，共 {len(judgements)} 个子项需要人工确认",
        "judgements": [
            {
                "requirement": j.get("requirement", ""),
                "judgement": j.get("judgement", ""),
                "gap": j.get("gap", ""),
            }
            for j in judgements
        ],
        "requiredAction": "CONFIRM | REQUEST_SUPPLEMENT | KEEP_PENDING",
    }

    return {
        "state_revision": state.get("state_revision", 0) + 1,
        "current_node": "wait_human_confirmation",
        "wait_state": wait_state,
    }


def apply_human_result(state: dict[str, Any]) -> dict[str, Any]:
    """Apply human confirmation result to the state.

    Reads from state (set by ResumeCommand via GraphAdapter).
    """
    command = state.get("command") or ""
    manual_result = state.get("manual_result") or "PENDING"
    note = state.get("note") or ""
    artifacts = state.get("artifacts") or {}
    judgements = artifacts.get("judgements") or []

    # Build final artifact with human result
    conclusion_map = {
        "SATISFIED": "BASICALLY_SATISFIED",
        "NOT_SATISFIED": "HAS_ISSUES",
        "PENDING": "NEEDS_REVIEW",
    }

    conclusion = conclusion_map.get(manual_result, "NEEDS_REVIEW")

    artifact = {
        "reportType": "FULFILLMENT_REPORT",
        "title": "履约核验报告",
        "summary": f"共核验 {len(judgements)} 个履约子项。人工结果：{manual_result}。{note}",
        "timelineNodeId": int(state.get("task_input", {}).get("timelineNodeId", 0)),
        "conclusion": conclusion,
        "riskLevel": "LOW" if manual_result == "SATISFIED" else "MEDIUM",
        "confidenceLevel": "HIGH" if manual_result == "SATISFIED" else "MEDIUM",
        "requirements": judgements,
        "evidenceSnapshot": evidence_snapshot,
        "missingEvidence": sorted({
            str(item.get("gap") or "")
            for item in judgements
            if str(item.get("gap") or "").strip()
        }),
        "explicitConsequence": "",
        "aiRisk": "AI 推断，仅供参考：最终履约结果以人工确认为准。",
        "suggestedActions": [],
        "citations": state.get("citations") or [],
        "content": {
            "manualConfirmationRequired": False,
            "manualResult": manual_result,
            "manualNote": note,
            "operatorId": state.get("operator_id", ""),
        },
    }

    wait_state = state.get("wait_state") or {}
    wait_state["resolved"] = True
    wait_state["resolvedBy"] = state.get("operator_id", "")
    wait_state["result"] = manual_result

    return {
        "state_revision": state.get("state_revision", 0) + 1,
        "current_node": "apply_human_result",
        "artifact": artifact,
        "wait_state": wait_state,
    }
