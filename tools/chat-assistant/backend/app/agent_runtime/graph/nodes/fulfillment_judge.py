"""Fulfillment judgement - per requirement assessment with evidence matching."""

from __future__ import annotations

from typing import Any
import re


def _normalize_terms(text: str) -> list[str]:
    return [term for term in re.findall(r"[\u4e00-\u9fff]{2,}|[A-Za-z0-9]{2,}", text)]


def _material_hints(requirement: str, acceptance: str, node: dict[str, Any], evidence_text: str) -> list[str]:
    text = " ".join([requirement, acceptance, evidence_text, str(node.get("label") or ""), str(node.get("businessMeaning") or ""), str(node.get("clauseContent") or "")])
    mapping = [
        (("报告", "交付", "成果", "研究"), "交付物、报告、成果文件、签收记录"),
        (("付款", "发票", "开票", "收据", "银行"), "付款记录、银行回单、发票、收据"),
        (("验收", "审查", "复核", "测试"), "验收单、审查意见、测试报告、会议纪要"),
        (("施工", "安装", "调试", "现场"), "施工照片、现场记录、调试记录、签字确认"),
        (("通知", "提醒", "告知"), "书面通知、邮件、送达回执"),
        (("续签", "延期"), "续签协议、延期谈判记录、确认函"),
        (("终止", "解除"), "终止通知、解除协议、结算单、交接清单"),
    ]
    hints: list[str] = []
    for keywords, hint in mapping:
        if any(word in text for word in keywords):
            hints.append(hint)
    if acceptance.strip():
        hints.append(acceptance.strip())
    return list(dict.fromkeys(hints))[:4]


def _match_score(requirement: str, item: dict[str, Any]) -> tuple[int, list[str]]:
    evidence_text = " ".join(str(item.get(key) or "") for key in ("fileName", "snippet", "content", "matchReason", "clauseText"))
    terms = _normalize_terms(requirement)
    matched = [term for term in terms if term in evidence_text]
    score = len(matched)
    if item.get("manuallyLinked"):
        score += 2
    if str(item.get("matchReason") or ""):
        score += 1
    return score, matched[:8]


def _node_usability(score: int, evidence_count: int, ambiguity: str) -> str:
    if evidence_count == 0:
        return "UNUSABLE"
    if ambiguity:
        return "HUMAN_REQUIRED"
    if score >= 4:
        return "USABLE"
    if score >= 2:
        return "LIMITED"
    return "HUMAN_REQUIRED"


def _proof_status(score: int, evidence_count: int, ambiguity: str) -> str:
    if evidence_count == 0:
        return "INSUFFICIENT"
    if ambiguity:
        return "UNCLEAR"
    if score >= 4:
        return "SUPPORTED"
    if score >= 2:
        return "PARTIAL"
    return "INSUFFICIENT"


def judge_each_requirement(state: dict[str, Any]) -> dict[str, Any]:
    """Judge each requirement item against available evidence."""
    requirements = state.get("fulfillment_requirements") or state.get("domain_tasks") or []
    observations = state.get("observations") or []
    case_snapshot = state.get("case_snapshot") or {}
    our_side = case_snapshot.get("ourSide") or ""
    fulfillment_context = state.get("fulfillment_context") or {}

    evidence_items: list[dict[str, Any]] = []
    node = fulfillment_context.get("timelineNode") or {}
    if isinstance(fulfillment_context.get("evidenceDocuments"), list):
        evidence_items.extend([item for item in fulfillment_context.get("evidenceDocuments") or [] if isinstance(item, dict)])
    if isinstance(fulfillment_context.get("contractEvidence"), list):
        evidence_items.extend([item for item in fulfillment_context.get("contractEvidence") or [] if isinstance(item, dict)])

    for obs in observations:
        output = obs.get("output", {})
        if not isinstance(output, dict):
            continue
        for key in ("evidenceDocuments", "documents", "contractEvidence"):
            docs = output.get(key) or []
            for doc in docs:
                if isinstance(doc, dict):
                    evidence_items.append(doc)

    # Deduplicate by sourceId/documentId/file name.
    unique: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in evidence_items:
        key = str(item.get("sourceId") or item.get("documentId") or item.get("id") or item.get("fileName") or "")
        if key and key in seen:
            continue
        if key:
            seen.add(key)
        unique.append(item)
    evidence_items = unique

    def _best_evidence(requirement: str, acceptance: str) -> tuple[dict[str, Any] | None, list[str], int]:
        if not evidence_items:
            return None, [], 0
        best_item: dict[str, Any] | None = None
        best_score = -1
        best_matched: list[str] = []
        anchor = " ".join([requirement, acceptance, str(node.get("label") or ""), str(node.get("businessMeaning") or "")])
        for item in evidence_items:
            score, matched = _match_score(anchor, item)
            if score > best_score:
                best_item = item
                best_score = score
                best_matched = matched
        return best_item, best_matched, max(best_score, 0)

    results = []
    for req in requirements:
        requirement_text = str(req.get("requirement", "")).strip()
        acceptance = str(req.get("acceptanceCriteria") or "").strip()
        required = bool(req.get("required", True))
        ambiguity = str(req.get("ambiguity") or "").strip()
        best_evidence, matched_terms, score = _best_evidence(requirement_text, acceptance)

        if not evidence_items or not best_evidence:
            material_hints = _material_hints(requirement_text, acceptance, node, "")
            result = {
                "requirement": requirement_text,
                "required": required,
                "contractCitationIds": req.get("sourceCitationIds") or [],
                "evidenceCitationIds": [],
                "evidence": "",
                "judgement": "EVIDENCE_INSUFFICIENT",
                "reason": "未找到可用于证明该履约子项的证据，当前仅能提示补证方向",
                "gap": "缺少可核验材料：" + "、".join(material_hints[:2]) if material_hints else "缺少可核验材料",
                "riskLevel": "HIGH",
                "confidenceLevel": "LOW",
                "nodeUsability": "UNUSABLE",
                "proofStatus": "INSUFFICIENT",
                "materialChecklist": material_hints,
                "matchedTerms": [],
                "supportSummary": "当前没有足够证据支撑人工确认",
                "missingItems": material_hints,
                "nextStep": "上传对应履约证明后重新核验",
                "evidenceSnapshot": [],
            }
        else:
            file_name = str(best_evidence.get("fileName") or best_evidence.get("title") or "")
            snippet = str(best_evidence.get("snippet") or best_evidence.get("content") or best_evidence.get("clauseText") or "")
            material_hints = _material_hints(requirement_text, acceptance, node, snippet)
            proof_status = _proof_status(score, len(evidence_items), ambiguity)
            node_usability = _node_usability(score, len(evidence_items), ambiguity)
            missing_items = material_hints[1:] if len(material_hints) > 1 else []
            judgement = "UNCLEAR_TERMS" if ambiguity else "NEEDS_REVIEW"
            confidence = "HIGH" if score >= 4 and not ambiguity else "MEDIUM" if score >= 2 else "LOW"
            risk_level = "MEDIUM" if proof_status in {"SUPPORTED", "PARTIAL"} else "HIGH"
            support_summary = (
                f"已匹配到 {file_name or '证据材料'}，匹配词：{', '.join(matched_terms[:5])}" if matched_terms
                else f"已找到 {file_name or '证据材料'}，但与合同要求的匹配度有限"
            )
            result = {
                "requirement": requirement_text,
                "required": required,
                "contractCitationIds": req.get("sourceCitationIds") or [],
                "evidenceCitationIds": [
                    f"FULFILLMENT_DOCUMENT:{best_evidence.get('documentId', best_evidence.get('id', ''))}"
                ] if best_evidence.get("documentId") or best_evidence.get("id") else [],
                "evidence": snippet[:300] or file_name,
                "judgement": judgement,
                "reason": support_summary,
                "gap": "、".join(missing_items) if missing_items else "暂无明显缺口，但仍需人工确认",
                "riskLevel": risk_level,
                "confidenceLevel": confidence,
                "nodeUsability": node_usability,
                "proofStatus": proof_status,
                "materialChecklist": material_hints,
                "matchedTerms": matched_terms,
                "supportSummary": support_summary,
                "missingItems": missing_items,
                "nextStep": "人工核对证据并确认是否满足合同要求",
                "evidenceSnapshot": [
                    {
                        "documentId": best_evidence.get("documentId") or best_evidence.get("id"),
                        "fileName": file_name,
                        "version": best_evidence.get("version"),
                        "contentHash": best_evidence.get("contentHash") or best_evidence.get("hash"),
                        "snippet": snippet[:500],
                        "matchedTerms": matched_terms,
                        "matchReason": best_evidence.get("matchReason") or best_evidence.get("retrievalType") or "",
                    }
                ],
                "evidenceMatchReason": best_evidence.get("matchReason") or "按履约子项检索到候选证据",
            }

        if our_side == "A":
            result["perspective"] = "我方为甲方，侧重验收、付款和追责角度"
        elif our_side == "B":
            result["perspective"] = "我方为乙方，侧重交付、举证和验收通过角度"

        results.append(result)

    overall_missing = sorted({
        item
        for row in results
        for item in (row.get("missingItems") or [])
        if str(item).strip()
    })

    return {
        "state_revision": state.get("state_revision", 0) + 1,
        "current_node": "judge_each_requirement",
        "artifacts": {
            "judgements": results,
            "missingEvidence": overall_missing,
            "fulfillmentAssessment": {
                "evidenceCount": len(evidence_items),
                "requirementCount": len(results),
                "supportedCount": sum(1 for row in results if row.get("proofStatus") == "SUPPORTED"),
                "partialCount": sum(1 for row in results if row.get("proofStatus") == "PARTIAL"),
                "insufficientCount": sum(1 for row in results if row.get("proofStatus") == "INSUFFICIENT"),
            },
        },
    }
