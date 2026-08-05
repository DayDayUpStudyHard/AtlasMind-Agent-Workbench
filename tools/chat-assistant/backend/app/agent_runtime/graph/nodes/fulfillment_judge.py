"""Fulfillment judgement — per-requirement assessment with evidence matching."""

from __future__ import annotations

from typing import Any


def judge_each_requirement(state: dict[str, Any]) -> dict[str, Any]:
    """Judge each requirement item against available evidence.

    Output per item: requirement, judgement, reason, gap, riskLevel, confidenceLevel.
    Agent MUST NOT output COMPLETED/FAILED/ACCEPTED as final business results.
    """
    requirements = state.get("domain_tasks") or []
    observations = state.get("observations") or []
    case_snapshot = state.get("case_snapshot") or {}
    our_side = case_snapshot.get("ourSide") or ""

    # Find evidence from observations
    evidence_items = []
    for obs in observations:
        output = obs.get("output", {})
        if isinstance(output, dict):
            docs = output.get("evidenceDocuments") or output.get("documents") or []
            for doc in docs:
                if isinstance(doc, dict):
                    evidence_items.append(doc)

    results = []
    for req in requirements:
        requirement_text = str(req.get("requirement", ""))
        has_evidence = len(evidence_items) > 0

        if not has_evidence:
            judgement = {
                "requirement": requirement_text,
                "required": bool(req.get("required", True)),
                "contractCitationIds": req.get("sourceCitationIds") or [],
                "evidenceCitationIds": [],
                "evidence": "",
                "judgement": "EVIDENCE_INSUFFICIENT",
                "reason": "未找到可用于该履约项的证明材料",
                "gap": "上传相关证明材料后重新核验",
                "riskLevel": "HIGH",
                "confidenceLevel": "LOW",
            }
        else:
            # Evidence exists — basic check
            best_evidence = evidence_items[0]  # Simplified: take first match
            judgement = {
                "requirement": requirement_text,
                "required": bool(req.get("required", True)),
                "contractCitationIds": req.get("sourceCitationIds") or [],
                "evidenceCitationIds": [
                    f"FULFILLMENT_DOCUMENT:{best_evidence.get('documentId', '')}"
                ],
                "evidence": str(best_evidence.get("snippet") or best_evidence.get("fileName", ""))[:300],
                "judgement": "NEEDS_REVIEW",
                "reason": f"已找到相关证据（{best_evidence.get('fileName', '')}），需人工核验内容是否满足合同要求",
                "gap": "请人工确认证明材料是否充分",
                "riskLevel": "MEDIUM",
                "confidenceLevel": "MEDIUM",
            }

        # ourSide perspective
        if our_side == "A":
            judgement["perspective"] = "我方为甲方，从验收、付款和追责角度分析"
        elif our_side == "B":
            judgement["perspective"] = "我方为乙方，从交付、举证和通过验收角度分析"

        results.append(judgement)

    return {
        "state_revision": state.get("state_revision", 0) + 1,
        "current_node": "judge_each_requirement",
        "artifacts": {  # Use artifacts for intermediate results
            "judgements": results,
        },
    }
