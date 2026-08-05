"""Fulfillment judgement — per-requirement assessment with evidence matching."""

from __future__ import annotations

from typing import Any
import re


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

    def _best_evidence(requirement: str) -> dict[str, Any] | None:
        if not evidence_items:
            return None
        terms = [term for term in re.findall(r"[\u4e00-\u9fff]{2,}|[A-Za-z0-9]{2,}", requirement)]
        def score(item: dict[str, Any]) -> tuple[int, int]:
            text = " ".join(str(item.get(key) or "") for key in ("fileName", "snippet", "content"))
            matched = sum(1 for term in terms if term in text)
            return (matched, 1 if item.get("manuallyLinked") else 0)
        return max(evidence_items, key=score)

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
            # Evidence exists, but the Agent still cannot make the final business decision.
            best_evidence = _best_evidence(requirement_text) or evidence_items[0]
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
                "evidenceMatchReason": best_evidence.get("matchReason") or "按履约节点检索到候选证明",
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
