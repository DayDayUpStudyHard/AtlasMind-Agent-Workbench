"""Fulfillment judgement - per requirement assessment with evidence matching.

PRD Phase 7: the rule layer (deterministic keyword matching, tasks 1/4)
stays the conservative base — it never claims completion. The LLM adds a
separate aiSuggestion layer (task 5: 已履约 / 未履约 / 证据不足 / 存在冲突
四种建议), which is advisory only: the final status is written exclusively
from the human confirmation (task 6).
"""

from __future__ import annotations

import re
import time
from typing import Any

from ..state import merge_llm_usage

# Task 6: conclusions the AI may never produce — not even as a suggestion.
_FORBIDDEN_AI_CONCLUSIONS = {"COMPLETED", "FAILED", "ACCEPTED", "REJECTED"}
_ALLOWED_AI_CONCLUSIONS = {
    "BASICALLY_SATISFIED", "HAS_ISSUES", "INSUFFICIENT_EVIDENCE",
    "UNCLEAR_TERMS", "NEEDS_REVIEW",
}
# Task 5 mapping: the LLM's per-requirement judgement vocabulary → the four
# suggestion conclusions (存在冲突/条款不明 folds into UNCLEAR_TERMS).
_LLM_JUDGEMENT_MAP = {
    "满足": "BASICALLY_SATISFIED",
    "已履约": "BASICALLY_SATISFIED",
    "不满足": "HAS_ISSUES",
    "未履约": "HAS_ISSUES",
    "证据不足": "INSUFFICIENT_EVIDENCE",
    "存在冲突": "UNCLEAR_TERMS",
    "需复核": "NEEDS_REVIEW",
    "条款不明确": "UNCLEAR_TERMS",
}


def _normalize_terms(text: str) -> list[str]:
    return [term for term in re.findall(r"[一-鿿]{2,}|[A-Za-z0-9]{2,}", text)]


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


def normalize_ai_suggestion(artifact: Any) -> dict[str, Any]:
    """Validate and normalize the LLM suggestion envelope (task 5).

    Schema violations are recorded, never silently accepted: a conclusion
    outside the four-suggestion vocabulary — or one of the forbidden final
    statuses (task 6) — is demoted to NEEDS_REVIEW.
    """
    if not isinstance(artifact, dict):
        return {
            "status": "FALLBACK_RULE",
            "schemaErrors": ["LLM 返回不是 JSON 对象，已回退规则判断"],
        }
    schema_errors: list[str] = []
    if artifact.get("reportType") != "FULFILLMENT_REPORT":
        schema_errors.append(f"reportType 非 FULFILLMENT_REPORT：{artifact.get('reportType')!r}")
    conclusion = artifact.get("conclusion")
    if conclusion in _FORBIDDEN_AI_CONCLUSIONS:
        schema_errors.append(f"LLM 输出禁止的终态结论 {conclusion}，已降级为 NEEDS_REVIEW")
        conclusion = "NEEDS_REVIEW"
    if conclusion not in _ALLOWED_AI_CONCLUSIONS:
        schema_errors.append(f"结论不在四建议词表内：{conclusion!r}，已降级为 NEEDS_REVIEW")
        conclusion = "NEEDS_REVIEW"
    raw_requirements = artifact.get("requirements")
    if not isinstance(raw_requirements, list):
        schema_errors.append("requirements 不是列表")
        raw_requirements = []
    per_requirement: list[dict[str, Any]] = []
    for row in raw_requirements:
        if not isinstance(row, dict):
            continue
        judgement = str(row.get("judgement") or "")
        if judgement in _FORBIDDEN_AI_CONCLUSIONS:
            schema_errors.append(f"子项输出禁止终态 {judgement}，已降级为 NEEDS_REVIEW")
            judgement = "NEEDS_REVIEW"
        per_requirement.append({
            "requirement": str(row.get("requirement") or ""),
            "conclusion": _LLM_JUDGEMENT_MAP.get(judgement, "NEEDS_REVIEW"),
            "evidence": str(row.get("evidence") or ""),
            "gap": str(row.get("gap") or ""),
            "required": bool(row.get("required", True)),
        })
    suggested_actions = artifact.get("suggestedActions")
    return {
        "status": "LLM_ENRICHED",
        "conclusion": conclusion,
        "riskLevel": str(artifact.get("riskLevel") or "MEDIUM"),
        "confidenceLevel": str(artifact.get("confidenceLevel") or "MEDIUM"),
        "requirements": per_requirement,
        "missingEvidence": [str(item) for item in (artifact.get("missingEvidence") or [])],
        "explicitConsequence": str(artifact.get("explicitConsequence") or ""),
        "aiRisk": str(artifact.get("aiRisk") or "AI 推断，仅供参考，不代表最终履约结论"),
        "suggestedActions": suggested_actions if isinstance(suggested_actions, list) else [],
        "schemaErrors": schema_errors,
    }


def _suggest_with_llm(state: dict[str, Any], rule_results: list[dict[str, Any]]) -> dict[str, Any]:
    """Task 5: call the fulfillment-check LLM for the four-suggestion layer.

    A failure never breaks the run — the rule layer's conservative rows are
    kept, the suggestion is marked FALLBACK_RULE and the human gate still
    decides. This is deliberately different from the timeline graph's strict
    LLM gate: here the LLM output is advisory, not the published artifact.
    """
    started = time.monotonic()
    if not rule_results:
        return {"status": "SKIPPED_EMPTY", "durationMs": int((time.monotonic() - started) * 1000)}
    try:
        from ....services.llm_service import LLMService

        case_snapshot = state.get("case_snapshot") or {}
        fulfillment_context = state.get("fulfillment_context") or {}
        verification = dict(fulfillment_context.get("verification") or {})
        verification.setdefault("requirements", rule_results)
        verification.setdefault(
            "evidenceDocuments", fulfillment_context.get("evidenceDocuments") or []
        )
        case = {
            "ourSide": str(case_snapshot.get("ourSide") or ""),
            "ourEntity": str(case_snapshot.get("ourEntity") or case_snapshot.get("ourName") or ""),
            "counterparty": str(case_snapshot.get("counterparty") or ""),
        }
        task_input = state.get("task_input") or {}
        artifact = LLMService().contract_fulfillment_check(
            case=case,
            verification=verification,
            citations=(state.get("citations") or [])[:10],
            task_input=task_input,
            run_id=int(state.get("run_id") or 0),
        )
        normalized = normalize_ai_suggestion(artifact)
        normalized["llmUsage"] = artifact.get("_llmUsage") or {}
        normalized["durationMs"] = int((time.monotonic() - started) * 1000)
        return normalized
    except Exception as exc:
        return {
            "status": "FALLBACK_RULE",
            "error": str(exc)[:300],
            "schemaErrors": ["LLM 建议层调用失败，已回退规则判断"],
            "durationMs": int((time.monotonic() - started) * 1000),
        }


def _carried_row(previous: dict[str, Any], requirement_id: str,
                 requirement_text: str) -> dict[str, Any] | None:
    """Task 8: reuse the previous run's judgement row for an unaffected
    requirement. The row keeps its historical evidence and aiSuggestion."""
    row = dict(previous)
    row["requirementId"] = row.get("requirementId") or requirement_id
    row["requirement"] = row.get("requirement") or requirement_text
    row["carriedForward"] = True
    return row


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

    # ── Task 8 rerun scope: carry forward unaffected requirements ──
    rerun_scope = state.get("rerun_scope") or {}
    rerun_mode = str(rerun_scope.get("mode") or "ALL")
    affected_ids = {str(value) for value in (rerun_scope.get("affectedRequirementIds") or [])}
    previous_judgements: dict[str, dict[str, Any]] = {}
    for prev in rerun_scope.get("previousJudgements") or []:
        if not isinstance(prev, dict):
            continue
        key = str(prev.get("requirementId") or prev.get("requirement") or "")
        if key:
            previous_judgements.setdefault(key, prev)

    # Task 4 evidence rule compliance, keyed by requirement id / text.
    compliance_map: dict[str, dict[str, Any]] = {}
    for item in ((state.get("evidence_rules") or {}).get("requirementCompliance") or []):
        if isinstance(item, dict):
            compliance_map[str(item.get("requirementId") or item.get("requirement") or "")] = item

    results = []
    for req in requirements:
        if not isinstance(req, dict):
            continue
        requirement_text = str(req.get("requirement", "")).strip()
        requirement_id = str(req.get("requirementId") or "")
        acceptance = str(req.get("acceptanceCriteria") or "").strip()
        required = bool(req.get("required", True))
        ambiguity = str(req.get("ambiguity") or "").strip()

        carried = None
        if rerun_mode == "UNCHANGED":
            carried = previous_judgements.get(requirement_id) or previous_judgements.get(requirement_text)
        elif rerun_mode == "AFFECTED_ONLY" and requirement_id not in affected_ids:
            carried = previous_judgements.get(requirement_id) or previous_judgements.get(requirement_text)
        if carried:
            results.append(_carried_row(carried, requirement_id, requirement_text))
            continue

        best_evidence, matched_terms, score = _best_evidence(requirement_text, acceptance)
        compliance = compliance_map.get(requirement_id) or compliance_map.get(requirement_text) or {}
        hard_flags = [flag for flag in (compliance.get("hardFlags") or []) if isinstance(flag, dict)]
        soft_flags = [flag for flag in (compliance.get("softFlags") or []) if isinstance(flag, dict)]

        if not evidence_items or not best_evidence:
            material_hints = _material_hints(requirement_text, acceptance, node, "")
            result = {
                "requirementId": requirement_id,
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
                "evidenceRuleFlags": {"hard": [], "soft": soft_flags},
                # PRD Phase 7, task 2: 截止条件和合同后果 travel with the
                # requirement into the judgement and the human wait state.
                "deadline": req.get("deadline"),
                "deadlineCondition": req.get("deadlineCondition"),
                "contractConsequence": req.get("contractConsequence") or {},
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
            # Task 4: hard rule flags contradict the claim the evidence is
            # supposed to prove — the proof status must not stay SUPPORTED.
            if hard_flags and proof_status == "SUPPORTED":
                proof_status = "PARTIAL"
                node_usability = "LIMITED"
            gap_parts = list(missing_items)
            for flag in hard_flags:
                detail = str(flag.get("detail") or "")
                if detail and detail not in gap_parts:
                    gap_parts.append(f"证据规则检查：{detail}")
            result = {
                "requirementId": requirement_id,
                "requirement": requirement_text,
                "required": required,
                "contractCitationIds": req.get("sourceCitationIds") or [],
                "evidenceCitationIds": [
                    f"FULFILLMENT_DOCUMENT:{best_evidence.get('documentId', best_evidence.get('id', ''))}"
                ] if best_evidence.get("documentId") or best_evidence.get("id") else [],
                "evidence": snippet[:300] or file_name,
                "judgement": judgement,
                "reason": support_summary,
                "gap": "、".join(gap_parts) if gap_parts else "暂无明显缺口，但仍需人工确认",
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
                "evidenceRuleFlags": {"hard": hard_flags, "soft": soft_flags},
                # PRD Phase 7, task 2: 截止条件和合同后果 travel with the
                # requirement into the judgement and the human wait state.
                "deadline": req.get("deadline"),
                "deadlineCondition": req.get("deadlineCondition"),
                "contractConsequence": req.get("contractConsequence") or {},
            }

        if our_side == "A":
            result["perspective"] = "我方为甲方，侧重验收、付款和追责角度"
        elif our_side == "B":
            result["perspective"] = "我方为乙方，侧重交付、举证和验收通过角度"

        results.append(result)

    # ── Task 5: LLM four-suggestion layer (advisory only, task 6) ──
    ai = _suggest_with_llm(state, results)
    per_map = {
        str(row.get("requirement") or ""): row
        for row in (ai.get("requirements") or []) if isinstance(row, dict)
    }
    for row in results:
        if row.get("carriedForward"):
            # The previous run's aiSuggestion travels with the carried row.
            continue
        matched = per_map.get(str(row.get("requirement") or ""))
        row["aiSuggestion"] = {
            "status": ai.get("status"),
            "conclusion": (matched or {}).get("conclusion"),
            "evidence": (matched or {}).get("evidence") or "",
            "gap": (matched or {}).get("gap") or "",
        } if matched else {
            "status": ai.get("status"),
            "conclusion": None,
            "evidence": "",
            "gap": "LLM 未覆盖该子项，仅规则判断有效",
        }

    overall_missing = sorted({
        item
        for row in results
        for item in (row.get("missingItems") or [])
        if str(item).strip()
    })

    assessment = {
        "evidenceCount": len(evidence_items),
        "requirementCount": len(results),
        "supportedCount": sum(1 for row in results if row.get("proofStatus") == "SUPPORTED"),
        "partialCount": sum(1 for row in results if row.get("proofStatus") == "PARTIAL"),
        "insufficientCount": sum(1 for row in results if row.get("proofStatus") == "INSUFFICIENT"),
        "unclearCount": sum(1 for row in results if row.get("proofStatus") == "UNCLEAR"),
        "carriedForwardCount": sum(1 for row in results if row.get("carriedForward")),
        "rerunMode": rerun_mode,
        "aiSuggestion": {
            "status": ai.get("status"),
            "conclusion": ai.get("conclusion"),
            "riskLevel": ai.get("riskLevel"),
            "confidenceLevel": ai.get("confidenceLevel"),
            "schemaErrors": ai.get("schemaErrors") or [],
            "durationMs": ai.get("durationMs"),
        },
    }

    return {
        "state_revision": state.get("state_revision", 0) + 1,
        "current_node": "judge_each_requirement",
        "artifacts": {
            "judgements": results,
            "missingEvidence": overall_missing,
            "fulfillmentAssessment": assessment,
        },
        "fulfillment_ai": ai,
        "llm_usage": merge_llm_usage(
            state, "judge_each_requirement", ai.get("llmUsage") or {}
        ),
    }
