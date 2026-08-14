"""Human confirmation interrupt node for fulfillment checks."""

from __future__ import annotations

from typing import Any

from ..versioning import stamp_artifact_versions


def _build_wait_state(state: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
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
            "carriedForwardCount": assessment.get("carriedForwardCount", 0),
            "rerunMode": assessment.get("rerunMode", "ALL"),
            "aiSuggestion": assessment.get("aiSuggestion") or {},
        },
        "judgements": [
            {
                "requirementId": j.get("requirementId", ""),
                "requirement": j.get("requirement", ""),
                "judgement": j.get("judgement", ""),
                "proofStatus": j.get("proofStatus", ""),
                "nodeUsability": j.get("nodeUsability", ""),
                "gap": j.get("gap", ""),
                "reason": j.get("reason", ""),
                "nextStep": j.get("nextStep", ""),
                "carriedForward": bool(j.get("carriedForward")),
                "deadline": j.get("deadline"),
                "deadlineCondition": j.get("deadlineCondition"),
                "contractConsequence": j.get("contractConsequence") or {},
                # Task 5: the AI suggestion is shown to the operator, clearly
                # separated from the rule judgement and the human decision.
                "aiSuggestion": {
                    "conclusion": (j.get("aiSuggestion") or {}).get("conclusion"),
                    "status": (j.get("aiSuggestion") or {}).get("status"),
                    "gap": (j.get("aiSuggestion") or {}).get("gap", ""),
                },
            }
            for j in judgements
        ],
        "requiredAction": "CONFIRM | REQUEST_SUPPLEMENT | KEEP_PENDING",
    }
    return wait_state, evidence_snapshot


def prepare_human_confirmation(state: dict[str, Any]) -> dict[str, Any]:
    """Materialize the HITL payload before the graph pauses."""
    wait_state, evidence_snapshot = _build_wait_state(state)
    return {
        "state_revision": state.get("state_revision", 0) + 1,
        "current_node": "prepare_human_confirmation",
        "wait_state": wait_state,
        "evidence_snapshot": evidence_snapshot,
    }


def wait_human_confirmation(state: dict[str, Any]) -> dict[str, Any]:
    """Pause with LangGraph's native interrupt and accept a resume command."""
    from langgraph.types import interrupt

    response = interrupt(state.get("wait_state") or {"type": "WAITING_HUMAN_CONFIRMATION"})
    response = response if isinstance(response, dict) else {}
    wait_state = dict(state.get("wait_state") or {})
    wait_state["responseReceived"] = True
    return {
        "state_revision": state.get("state_revision", 0) + 1,
        "current_node": "wait_human_confirmation",
        "manual_result": str(
            response.get("manualResult") or response.get("manual_result") or "PENDING"
        ).upper(),
        "note": str(response.get("note") or ""),
        "operator_id": str(response.get("operatorId") or response.get("operator_id") or ""),
        "wait_state": wait_state,
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
            # PRD Phase 7, tasks 8/9: the judgement rows (with their
            # evidenceSnapshot + aiSuggestion) are persisted inside content
            # so the next run can diff new material against this history —
            # each run INSERTs its own report row, history is never
            # overwritten.
            "timelineNodeId": int(state.get("task_input", {}).get("timelineNodeId", 0)),
            "requirements": judgements,
        },
    }

    stamp_artifact_versions(state, artifact)

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
