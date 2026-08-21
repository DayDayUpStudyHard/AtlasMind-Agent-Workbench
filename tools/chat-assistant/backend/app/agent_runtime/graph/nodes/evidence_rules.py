"""PRD Phase 7, task 4: evidence rule checks — file type / date / amount /
seal / content rules for uploaded fulfillment proof.

All rules are deterministic code — they FLAG evidence for the judgement
layer and the human operator, never conclude a fulfillment state on their
own (task 6: AI/规则不写最终人工状态). Every rule reports PASS / FLAG /
HINT / SKIPPED with a stable ``code``, so each flag is traceable to the
rule that raised it.
"""

from __future__ import annotations

import re
import time
from typing import Any

from .fulfillment_judge import _match_score

EVIDENCE_RULE_VERSION = "evidence-rules-v1"

_SUPPORTED_EXTENSIONS = {
    "pdf", "ofd", "jpg", "jpeg", "png", "gif", "bmp", "webp",
    "xlsx", "xls", "csv", "docx", "doc",
}
# Node types whose confirming evidence conventionally carries a seal /
# signature (acceptance records, delivery receipts, termination docs).
_SEAL_SENSITIVE_NODE_TYPES = {"ACCEPTANCE", "DELIVERY", "TERMINATION", "RENEWAL"}
_SEAL_TERMS = ("盖章", "签章", "公章", "合同章", "财务章", "签字", "签署", "签名")

_AMOUNT_PATTERN = re.compile(
    r"(?:人民币|¥|￥)?\s*(\d{1,3}(?:,\d{3})+|\d+)(?:\.(\d{1,2}))?\s*(万元|万|亿元|亿|元)?"
)

# Hard flags contradict the claim the evidence is supposed to prove (proof
# dated after the deadline, mismatched amount, missing seal, no content
# match at all). Soft flags are gaps a human must close but that don't
# contradict anything (missing date/amount on the evidence itself).
_HARD_FLAG_CODES = {
    "UNRECOGNIZED_FILE_TYPE", "UNSUPPORTED_FILE_TYPE", "DATE_BEFORE_EFFECTIVE",
    "DATE_AFTER_DEADLINE", "AMOUNT_MISMATCH", "SEAL_MISSING", "CONTENT_NO_MATCH",
}


def _norm_date(value: Any) -> str | None:
    """Normalize any date-ish value to YYYY-MM-DD (or None when unusable)."""
    if value in (None, ""):
        return None
    text = str(value).strip()
    match = re.search(r"(\d{4})-(\d{1,2})-(\d{1,2})", text)
    if match:
        return f"{int(match.group(1)):04d}-{int(match.group(2)):02d}-{int(match.group(3)):02d}"
    return None


def _parse_amount(text: str) -> float | None:
    """Parse the first CNY amount from free text (arabic numerals)."""
    if not text:
        return None
    for match in _AMOUNT_PATTERN.finditer(text):
        digits = match.group(1).replace(",", "")
        fraction = match.group(2) or "0"
        unit = match.group(3) or ""
        try:
            value = float(digits) + float(fraction) / (10 ** len(fraction))
        except ValueError:
            continue
        if unit in ("万", "万元"):
            value *= 10000
        elif unit in ("亿", "亿元"):
            value *= 100000000
        return value
    return None


def _file_extension(doc: dict[str, Any]) -> str:
    file_name = str(doc.get("fileName") or "")
    mime = str(doc.get("mimeType") or doc.get("fileType") or "")
    match = re.search(r"\.([A-Za-z0-9]{2,5})$", file_name)
    if match:
        return match.group(1).lower()
    if "/" in mime:
        return mime.rsplit("/", 1)[-1].lower()
    return ""


def file_type_rule(doc: dict[str, Any], node_type: str) -> dict[str, Any]:
    """Rule 1: the uploaded file type must be recognizable and plausible."""
    ext = _file_extension(doc)
    if not ext:
        return {
            "rule": "FILE_TYPE", "code": "UNRECOGNIZED_FILE_TYPE", "status": "FLAG",
            "detail": "无法识别文件类型，需人工核对原始文件",
        }
    if ext not in _SUPPORTED_EXTENSIONS:
        return {
            "rule": "FILE_TYPE", "code": "UNSUPPORTED_FILE_TYPE", "status": "FLAG",
            "detail": f"文件类型 .{ext} 不在支持的证据格式范围内，需人工核对",
        }
    # Payment proofs are conventionally scanned receipts / bank slips, not
    # editable office documents — a mismatch is only a hint, not a verdict.
    if node_type == "PAYMENT" and ext in {"docx", "doc", "xlsx", "xls", "csv"}:
        return {
            "rule": "FILE_TYPE", "code": "TYPE_MISMATCH_HINT", "status": "HINT",
            "detail": f"付款类证据通常为扫描件（PDF/图片），当前为 .{ext}，建议核对原件",
        }
    return {
        "rule": "FILE_TYPE", "code": "FILE_TYPE_OK", "status": "PASS",
        "detail": f"文件类型 .{ext} 可识别",
    }


def date_rule(doc: dict[str, Any], deadline: str | None,
              effective_date: str | None) -> dict[str, Any]:
    """Rule 2: evidence date must sit inside the contract period and before
    the node deadline. Comparisons are string-based on YYYY-MM-DD."""
    doc_date = _norm_date(
        doc.get("date") or doc.get("documentDate") or doc.get("occurredDate")
        or doc.get("uploadedAt") or doc.get("uploadDate")
    )
    if doc_date is None:
        # Evaluation proof is stored as extracted text, so a dated receipt
        # must remain verifiable even when the synthetic document has no
        # separate metadata column.
        content = " ".join(str(doc.get(key) or "") for key in ("content", "snippet", "contentText"))
        date_match = re.search(r"(20\d{2})[-年](\d{1,2})[-月](\d{1,2})", content)
        if date_match:
            doc_date = f"{int(date_match.group(1)):04d}-{int(date_match.group(2)):02d}-{int(date_match.group(3)):02d}"
    if doc_date is None:
        return {
            "rule": "DATE", "code": "DATE_MISSING", "status": "FLAG",
            "detail": "证据缺少日期，需人工核对其所属履约周期",
        }
    if effective_date and doc_date < _norm_date(effective_date):
        return {
            "rule": "DATE", "code": "DATE_BEFORE_EFFECTIVE", "status": "FLAG",
            "detail": f"证据日期 {doc_date} 早于合同生效日 {effective_date}，可能不属于本周期",
        }
    if deadline and doc_date > _norm_date(deadline):
        return {
            "rule": "DATE", "code": "DATE_AFTER_DEADLINE", "status": "FLAG",
            "detail": f"证据日期 {doc_date} 晚于节点截止时间 {deadline}，可能构成逾期",
        }
    detail = f"证据日期 {doc_date} 在合同周期内"
    if deadline:
        detail += f"（不晚于节点截止时间 {deadline}）"
    return {"rule": "DATE", "code": "DATE_OK", "status": "PASS", "detail": detail}


def amount_rule(doc: dict[str, Any], node_type: str,
                expected_amount: float | None) -> dict[str, Any]:
    """Rule 3 (PAYMENT nodes): the proof amount must match the contracted one."""
    if node_type != "PAYMENT":
        return {"rule": "AMOUNT", "code": "AMOUNT_NOT_APPLICABLE",
                "status": "SKIPPED", "detail": "非付款节点，不适用金额规则"}
    text = " ".join(str(doc.get(key) or "") for key in ("content", "snippet", "contentText"))
    evidence_amount = _parse_amount(text)
    if evidence_amount is None:
        return {
            "rule": "AMOUNT", "code": "AMOUNT_MISSING", "status": "FLAG",
            "detail": "证据未包含金额信息，需人工核对付款凭证金额",
        }
    if expected_amount is None:
        return {
            "rule": "AMOUNT", "code": "AMOUNT_EXPECTED_UNKNOWN", "status": "HINT",
            "detail": f"证据金额 {evidence_amount:g}，合同金额未解析到，需人工比对",
        }
    diff = abs(evidence_amount - expected_amount)
    if diff > max(0.01 * max(abs(expected_amount), 1.0), 0.01):
        return {
            "rule": "AMOUNT", "code": "AMOUNT_MISMATCH", "status": "FLAG",
            "detail": f"证据金额 {evidence_amount:g} 与合同金额 {expected_amount:g} 不符",
        }
    return {
        "rule": "AMOUNT", "code": "AMOUNT_OK", "status": "PASS",
        "detail": f"证据金额 {evidence_amount:g} 与合同金额 {expected_amount:g} 一致",
    }


def seal_rule(doc: dict[str, Any], node_type: str) -> dict[str, Any]:
    """Rule 4: confirming evidence (acceptance / delivery / termination)
    should carry a seal or signature."""
    if node_type not in _SEAL_SENSITIVE_NODE_TYPES:
        return {"rule": "SEAL", "code": "SEAL_NOT_APPLICABLE",
                "status": "SKIPPED", "detail": "节点类型不要求签章检查"}
    text = " ".join(str(doc.get(key) or "") for key in ("content", "snippet", "contentText", "fileName"))
    if any(term in text for term in _SEAL_TERMS):
        return {"rule": "SEAL", "code": "SEAL_OK", "status": "PASS",
                "detail": "检测到签章/签字信息"}
    return {
        "rule": "SEAL", "code": "SEAL_MISSING", "status": "FLAG",
        "detail": "未检测到签章/签字信息，验收/交付确认类证据需人工核对原件签章",
    }


def content_rule(requirement_text: str, evidence: dict[str, Any] | None) -> dict[str, Any]:
    """Rule 5: the evidence content must match the requirement terms."""
    if not evidence:
        return {
            "rule": "CONTENT", "code": "CONTENT_NO_EVIDENCE", "status": "FLAG",
            "detail": "无可核验证据内容",
        }
    score, matched = _match_score(requirement_text, evidence)
    if score >= 4:
        return {
            "rule": "CONTENT", "code": "CONTENT_OK", "status": "PASS",
            "detail": f"证据内容与要求匹配（命中 {matched[:5]}）",
        }
    if score >= 1:
        return {
            "rule": "CONTENT", "code": "CONTENT_WEAK_MATCH", "status": "FLAG",
            "detail": f"证据内容与要求匹配度有限（命中 {matched[:5]}），需人工比对全文",
        }
    return {
        "rule": "CONTENT", "code": "CONTENT_NO_MATCH", "status": "FLAG",
        "detail": "证据内容与要求无关键词匹配",
    }


def run_evidence_rules(
    documents: list[dict[str, Any]],
    node_type: str,
    deadline: str | None,
    effective_date: str | None,
    expected_amount: float | None,
    requirements: list[dict[str, Any]],
) -> dict[str, Any]:
    """Execute all five rule groups over uploaded evidence (pure, testable)."""
    started = time.monotonic()
    doc_results: list[dict[str, Any]] = []
    for doc in documents:
        if not isinstance(doc, dict):
            continue
        doc_results.append({
            "documentId": doc.get("documentId") or doc.get("id"),
            "fileName": doc.get("fileName") or "",
            "rules": [
                file_type_rule(doc, node_type),
                date_rule(doc, deadline, effective_date),
                amount_rule(doc, node_type, expected_amount),
                seal_rule(doc, node_type),
            ],
        })

    compliance: list[dict[str, Any]] = []
    for req in requirements:
        if not isinstance(req, dict):
            continue
        req_text = str(req.get("requirement") or "")
        best_doc: dict[str, Any] | None = None
        best_score = -1
        for doc in documents:
            if not isinstance(doc, dict):
                continue
            score, _ = _match_score(req_text, doc)
            if score > best_score:
                best_doc, best_score = doc, score
        hard_flags: list[dict[str, Any]] = []
        soft_flags: list[dict[str, Any]] = []
        if best_doc:
            row_rules = next(
                (row["rules"] for row in doc_results
                 if row.get("documentId") == (best_doc.get("documentId") or best_doc.get("id"))),
                [],
            )
            for rule in row_rules:
                if rule.get("status") == "FLAG" and rule.get("code") in _HARD_FLAG_CODES:
                    hard_flags.append({"rule": rule["rule"], "code": rule["code"], "detail": rule["detail"]})
                elif rule.get("status") in ("FLAG", "HINT"):
                    soft_flags.append({"rule": rule["rule"], "code": rule["code"], "detail": rule["detail"]})
        content = content_rule(req_text, best_doc)
        if content.get("code") in _HARD_FLAG_CODES:
            hard_flags.append({"rule": "CONTENT", "code": content["code"], "detail": content["detail"]})
        elif content.get("status") in ("FLAG", "HINT"):
            soft_flags.append({"rule": "CONTENT", "code": content["code"], "detail": content["detail"]})
        compliance.append({
            "requirementId": req.get("requirementId") or "",
            "requirement": req_text,
            "bestDocumentId": (best_doc or {}).get("documentId") or (best_doc or {}).get("id"),
            "hardFlags": hard_flags,
            "softFlags": soft_flags,
            "compliance": "FLAG" if hard_flags else ("HINT" if soft_flags else "PASS"),
        })

    return {
        "ruleVersion": EVIDENCE_RULE_VERSION,
        "durationMs": int((time.monotonic() - started) * 1000),
        "documentCount": len(doc_results),
        "hardFlagCount": sum(len(item["hardFlags"]) for item in compliance),
        "softFlagCount": sum(len(item["softFlags"]) for item in compliance),
        "documents": doc_results,
        "requirementCompliance": compliance,
    }


def check_evidence_rules(state: dict[str, Any]) -> dict[str, Any]:
    """Analyzer-role node: run the five evidence rule groups and publish the
    per-document / per-requirement compliance table for the judge and audit."""
    fulfillment_context = state.get("fulfillment_context") or {}
    node = fulfillment_context.get("timelineNode") or {}
    node_type = str(node.get("nodeType") or node.get("type") or "OTHER").upper()
    documents = [
        item for item in (fulfillment_context.get("evidenceDocuments") or [])
        if isinstance(item, dict)
    ]
    requirements = state.get("fulfillment_requirements") or state.get("domain_tasks") or []
    deadline = next(
        (item.get("deadline") for item in requirements if item.get("deadline")), None
    ) or node.get("date") or node.get("nodeDate")
    effective_date = (state.get("case_snapshot") or {}).get("effectiveDate")
    expected_amount = None
    for item in requirements:
        for fact in item.get("supportingFacts") or []:
            if isinstance(fact, dict) and fact.get("elementKey") == "contract_amount":
                expected_amount = _parse_amount(str(fact.get("rawValue") or ""))
                break
        if expected_amount is not None:
            break
    if expected_amount is None:
        expected_amount = _parse_amount(str(node.get("clauseContent") or ""))

    rules = run_evidence_rules(
        documents, node_type, deadline, effective_date, expected_amount, requirements,
    )
    return {
        "state_revision": state.get("state_revision", 0) + 1,
        "current_node": "check_evidence_rules",
        "evidence_rules": rules,
        "observations": [{
            "callId": f"evidence-rules-{state.get('run_id', 0)}",
            "planStepId": "check_evidence_rules",
            "toolName": "runEvidenceRules",
            "arguments": {
                "nodeType": node_type, "documentCount": len(documents),
                "deadline": deadline, "effectiveDate": effective_date,
            },
            "output": {
                "ruleVersion": rules["ruleVersion"],
                "hardFlagCount": rules["hardFlagCount"],
                "softFlagCount": rules["softFlagCount"],
                "durationMs": rules["durationMs"],
            },
            "status": "DONE",
        }],
    }
