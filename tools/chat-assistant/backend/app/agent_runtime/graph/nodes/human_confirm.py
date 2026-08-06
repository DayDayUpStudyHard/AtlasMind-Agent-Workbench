"""Human confirmation interrupt node for fulfillment checks."""

from __future__ import annotations

from typing import Any


def wait_human_confirmation(state: dict[str, Any]) -> dict[str, Any]:
    """Pause execution until a human confirms the fulfillment result."""
    artifacts = state.get("artifacts") or {}
    judgements = artifacts.get("judgements") or []
    assessment = artifacts.get("fulfillmentAssessment") or {}
    evidence_snapshot = []
    for observation in state.get("observations") or []:
        output = observation.get("output") or {}
        for key in ("evidenceDocuments", "contractEvidence"):
            for item in output.get(key) or []:
                if not isinstance(item, dict):
                    continue
                evidence_snapshot.append({
                    "documentId": item.get("documentId") or item.get("id"),
                    "fileName": item.get("fileName") or "",
                    "version": item.get("version"),
                    "contentHash": item.get("contentHash"),
                    "snippet": item.get("snippet") or item.get("content") or "",
                    "matchedTerms": item.get("matchedTerms") or [],
                    "matchReason": item.get("matchReason") or "",
                })

    wait_state = {
        "type": "WAITING_HUMAN_CONFIRMATION",
        "message": f"履约核验已完成，共 {len(judgements)} 个子项需要人工确认。",
        "summary": {
            "evidenceCount": assessment.get("evidenceCount", 0),
            "requirementCount": assessment.get("requirementCount", len(judgements)),
            "supportedCount": assessment.get("supportedCount", 0),
            "partialCount": assessment.get("partialCount", 0),
            "insufficientCount": assessment.get("insufficientCount", 0),
        },
        "judgements": [
            {
                "requirement": j.get("requirement", ""),
                "judgement": j.get("judgement", ""),
                "proofStatus": j.get("proofStatus", ""),
                "nodeUsability": j.get("nodeUsability", ""),
                "gap": j.get("gap", ""),
                "reason": j.get("reason", ""),
                "nextStep": j.get("nextStep", ""),
            }
            for j in judgements
        ],
        "requiredAction": "CONFIRM | REQUEST_SUPPLEMENT | KEEP_PENDING",
    }

    return {
        "state_revision": state.get("state_revision", 0) + 1,
        "current_node": "wait_human_confirmation",
        "wait_state": wait_state,
        "evidence_snapshot": evidence_snapshot,
    }


def apply_human_result(state: dict[str, Any]) -> dict[str, Any]:
    """Apply human confirmation result to the state."""
    manual_result = state.get("manual_result") or "PENDING"
    note = state.get("note") or ""
    artifacts = state.get("artifacts") or {}
    judgements = artifacts.get("judgements") or []
    assessment = artifacts.get("fulfillmentAssessment") or {}
    evidence_snapshot = state.get("evidence_snapshot") or []

    conclusion_map = {
        "SATISFIED": "BASICALLY_SATISFIED",
        "NOT_SATISFIED": "HAS_ISSUES",
        "PENDING": "NEEDS_REVIEW",
    }
    conclusion = conclusion_map.get(manual_result, "NEEDS_REVIEW")

    artifact = {
        "reportType": "FULFILLMENT_REPORT",
        "title": "履约核验报告",
        "summary": (
            f"共核验 {len(judgements)} 个履约子项。"
            f"人工结果：{manual_result}。"
            f"{note}"
        ),
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
        "aiRisk": "AI 推断，仅供参考，不代表最终履约结论；最终结果以人工确认和合同约定为准。",
        "suggestedActions": [],
        "citations": state.get("citations") or [],
        "content": {
            "manualConfirmationRequired": False,
            "manualResult": manual_result,
            "manualNote": note,
            "operatorId": state.get("operator_id", ""),
            "fulfillmentAssessment": assessment,
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
