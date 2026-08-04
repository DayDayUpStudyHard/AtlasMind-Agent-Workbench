"""Contract intake metadata extraction with citation validation."""

from __future__ import annotations

import hashlib
import json
import logging
import re
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from app.config import settings
from app.services.llm_service import LLMService

from .persistence import _conn

logger = logging.getLogger(__name__)

SCHEMA_VERSION = "contract-intake-v1"
PROMPT_VERSION = "contract-intake-v1"
FIELD_KEYS = (
    "contractTitle",
    "contractType",
    "partyA",
    "partyB",
    "amount",
    "currency",
    "effectiveDate",
    "expiryDate",
    "department",
)
CONTRACT_TYPES = {"SERVICE_PROCUREMENT", "GOODS_PURCHASE", "NDA", "OTHER"}
_REQUIRED_FIELDS = {"contractTitle", "contractType", "partyA", "partyB"}
_MAX_EXCERPT_CHARS = 48_000


def _citation(text: str, quote: str) -> dict | None:
    normalized = str(quote or "").strip()
    if not normalized:
        return None
    start = text.find(normalized)
    if start < 0:
        return None
    return {"quote": normalized, "startOffset": start, "endOffset": start + len(normalized)}


def _field(value: Any = None, confidence: float = 0.0,
           citation: dict | None = None, source: str = "RULE") -> dict:
    return {
        "value": value,
        "confidence": round(max(0.0, min(1.0, float(confidence))), 2),
        "citations": [citation] if citation else [],
        "source": source,
    }


def _line_match(text: str, labels: tuple[str, ...]) -> tuple[str, str] | None:
    label_pattern = "|".join(re.escape(label) for label in labels)
    # Match: LABEL：VALUE (on its own line, optional parenthetical after label)
    # e.g. "甲方：星河科技" / "甲方（委托方）：星河科技" / "甲方(采购方)：星河科技"
    m = re.search(
        rf"(?m)^\s*(?:{label_pattern})(?:[(（][^)）]+[)）])?\s*[:：]\s*"
        rf"([^\n]{{2,256}}?)(?:[(（][^)）]*[)）])?\s*$",
        text,
    )
    if m:
        value = m.group(1).strip().rstrip(":：；;，,。.")
        return value, m.group(0).strip()
    # Fallback: search anywhere (not just line-start) for label:value
    m = re.search(
        rf"(?:^|\n|。|；)\s*(?:{label_pattern})(?:[(（][^)）]+[)）])?\s*[:：]\s*"
        rf"([^\n。；]{{2,256}}?)(?:[。；\n]|$)",
        text,
    )
    if m:
        value = m.group(1).strip().rstrip(":：；;，,。.")
        if len(value) >= 2:
            return value, m.group(0).strip()
    return None


def _normalize_date(value: Any) -> str | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    normalized = raw.replace("年", "-").replace("月", "-").replace("日", "")
    normalized = normalized.replace("年", "-").replace("月", "-").replace("日", "")
    normalized = normalized.replace("/", "-").replace(".", "-")
    normalized = re.sub(r"\s+", "", normalized)
    for pattern in ("%Y-%m-%d", "%Y-%m", "%Y%m%d"):
        try:
            parsed = datetime.strptime(normalized, pattern)
            if pattern == "%Y-%m":
                return parsed.strftime("%Y-%m-01")
            return parsed.strftime("%Y-%m-%d")
        except ValueError:
            continue
    return None


def _normalize_amount(value: Any) -> float | None:
    if value is None or value == "":
        return None
    raw = str(value).replace(",", "").replace("，", "").strip()
    multiplier = Decimal("1")
    if raw.endswith("万"):
        multiplier = Decimal("10000")
        raw = raw[:-1]
    elif raw.endswith("亿"):
        multiplier = Decimal("100000000")
        raw = raw[:-1]
    raw = re.sub(r"[^0-9.\-]", "", raw)
    try:
        amount = Decimal(raw) * multiplier
    except (InvalidOperation, ValueError):
        return None
    if amount < 0:
        return None
    return float(amount)


def deterministic_hints(text: str, file_name: str = "") -> dict[str, dict]:
    """Extract conservative candidates without calling the model."""
    hints = {key: _field() for key in FIELD_KEYS}

    title = None
    title_quote = None
    for line in (line.strip() for line in text.splitlines()[:20]):
        if 2 <= len(line) <= 120 and any(word in line for word in ("合同", "协议", "确认书")):
            title = line
            title_quote = line
            break
    if not title and file_name:
        title = re.sub(r"\.(txt|pdf|docx?|md)$", "", file_name, flags=re.IGNORECASE).strip()
    if title:
        hints["contractTitle"] = _field(
            title, 0.82 if title_quote else 0.62,
            _citation(text, title_quote or ""),
        )

    party_a = _line_match(text, ("甲方", "委托方", "采购方", "买方", "买受人", "需方", "发包人", "定作人"))
    party_b = _line_match(text, ("乙方", "受托方", "供应商", "卖方", "出卖人", "供方", "承包人", "承揽人", "服务方"))
    if party_a:
        hints["partyA"] = _field(party_a[0], 0.78, _citation(text, party_a[1]))
    if party_b:
        hints["partyB"] = _field(party_b[0], 0.78, _citation(text, party_b[1]))

    if "保密协议" in text or "非披露协议" in text:
        contract_type = "NDA"
        type_quote = "保密协议" if "保密协议" in text else "非披露协议"
    elif any(word in text for word in ("货物采购", "产品采购", "设备采购")):
        contract_type, type_quote = "GOODS_PURCHASE", next(
            word for word in ("货物采购", "产品采购", "设备采购") if word in text
        )
    elif any(word in text for word in ("服务采购", "技术服务", "咨询服务", "运维服务")):
        contract_type = "SERVICE_PROCUREMENT"
        type_quote = next(
            word for word in ("服务采购", "技术服务", "咨询服务", "运维服务") if word in text
        )
    else:
        contract_type, type_quote = "OTHER", ""
    hints["contractType"] = _field(
        contract_type, 0.8 if type_quote else 0.45, _citation(text, type_quote)
    )

    amount_match = re.search(
        r"(?:合同(?:总)?金额|合同价款|含税总价|总价)\s*(?:为|是)?\s*[：:]?\s*"
        r"(?:人民币)?\s*[¥￥]?\s*([0-9][0-9,，]*(?:\.\d+)?)\s*(万|亿)?\s*元?",
        text,
    )
    if amount_match:
        raw_amount = amount_match.group(1) + (amount_match.group(2) or "")
        hints["amount"] = _field(
            _normalize_amount(raw_amount), 0.84, _citation(text, amount_match.group(0).strip())
        )
        hints["currency"] = _field(
            "CNY", 0.88, _citation(text, amount_match.group(0).strip())
        )

    for key, labels in (
        ("effectiveDate", ("生效日期", "合同生效日")),
        ("expiryDate", ("到期日期", "合同到期日", "终止日期")),
    ):
        matched = _line_match(text, labels)
        if matched:
            normalized_date = _normalize_date(matched[0])
            if normalized_date:
                hints[key] = _field(normalized_date, 0.8, _citation(text, matched[1]))
        # Fallback: "本合同自YYYY年MM月DD日起生效" patterns
        if not hints[key]["value"]:
            if key == "effectiveDate":
                fm = re.search(
                    r"(?:自|从|于)\s*(\d{4})\s*[年/\-.]\s*(\d{1,2})\s*[月/\-.]\s*(\d{1,2})\s*日?\s*(?:起|开始)?\s*(?:生效|执行|履行)",
                    text,
                )
                if fm:
                    d = f"{int(fm.group(1)):04d}-{int(fm.group(2)):02d}-{int(fm.group(3)):02d}"
                    hints[key] = _field(d, 0.74, _citation(text, fm.group(0).strip()))
            elif key == "expiryDate":
                fm = re.search(
                    r"(?:至|到|止于)\s*(\d{4})\s*[年/\-.]\s*(\d{1,2})\s*[月/\-.]\s*(\d{1,2})\s*日?\s*(?:止|到期|终止|届满)",
                    text,
                )
                if fm:
                    d = f"{int(fm.group(1)):04d}-{int(fm.group(2)):02d}-{int(fm.group(3)):02d}"
                    hints[key] = _field(d, 0.72, _citation(text, fm.group(0).strip()))

    department = _line_match(text, ("所属部门", "业务部门", "需求部门", "采购部门", "经办部门"))
    if department:
        hints["department"] = _field(department[0], 0.72, _citation(text, department[1]))

    if not hints["contractTitle"]["value"]:
        for line in (line.strip() for line in text.splitlines()[:20]):
            if 2 <= len(line) <= 120 and any(word in line for word in ("合同", "协议", "确认书")):
                hints["contractTitle"] = _field(line, 0.82, _citation(text, line))
                break

    actual_party_a = _line_match(text, ("甲方", "委托方", "采购方", "买方"))
    actual_party_b = _line_match(text, ("乙方", "受托方", "供应商", "卖方"))
    if actual_party_a:
        hints["partyA"] = _field(actual_party_a[0], 0.78, _citation(text, actual_party_a[1]))
    if actual_party_b:
        hints["partyB"] = _field(actual_party_b[0], 0.78, _citation(text, actual_party_b[1]))

    if "保密协议" in text or "非披露协议" in text:
        hints["contractType"] = _field("NDA", 0.8, _citation(text, "保密协议" if "保密协议" in text else "非披露协议"))
    elif any(word in text for word in ("货物采购", "产品采购", "设备采购")):
        type_quote = next(word for word in ("货物采购", "产品采购", "设备采购") if word in text)
        hints["contractType"] = _field("GOODS_PURCHASE", 0.8, _citation(text, type_quote))
    elif any(word in text for word in ("服务采购", "技术服务", "咨询服务", "运维服务")):
        type_quote = next(word for word in ("服务采购", "技术服务", "咨询服务", "运维服务") if word in text)
        hints["contractType"] = _field("SERVICE_PROCUREMENT", 0.8, _citation(text, type_quote))

    actual_amount = re.search(
        r"(?:合同(?:总)?金额|合同价款|含税总价|总价)\s*(?:为|是)?\s*[:：]?\s*"
        r"(?:人民币|RMB|CNY|￥)?\s*([0-9][0-9,]*(?:\.\d+)?)\s*(万|亿)?\s*元?",
        text,
    )
    if actual_amount:
        raw_amount = actual_amount.group(1) + (actual_amount.group(2) or "")
        hints["amount"] = _field(
            _normalize_amount(raw_amount), 0.84, _citation(text, actual_amount.group(0).strip())
        )
        hints["currency"] = _field("CNY", 0.88, _citation(text, actual_amount.group(0).strip()))

    for key, labels in (
        ("effectiveDate", ("生效日期", "合同生效日", "生效日")),
        ("expiryDate", ("到期日期", "合同到期日", "终止日期", "截止日期")),
    ):
        matched = _line_match(text, labels)
        if matched:
            normalized_date = _normalize_date(matched[0])
            if normalized_date:
                hints[key] = _field(normalized_date, 0.8, _citation(text, matched[1]))

    return hints


def _normalize_field(key: str, raw: Any, text: str, fallback: dict) -> dict:
    candidate = raw if isinstance(raw, dict) else {"value": raw}
    value = candidate.get("value")

    if key == "contractType":
        value = str(value or "").strip().upper()
        if value not in CONTRACT_TYPES:
            value = None
    elif key == "amount":
        value = _normalize_amount(value)
    elif key in {"effectiveDate", "expiryDate"}:
        value = _normalize_date(value)
    elif key == "currency":
        value = str(value or "").strip().upper()
        if value not in {"CNY", "USD", "EUR", "GBP", "JPY", "HKD"}:
            value = None
    else:
        value = str(value or "").strip()[:512] or None

    citations = []
    raw_citations = candidate.get("citations") or []
    if isinstance(raw_citations, dict):
        raw_citations = [raw_citations]
    for item in raw_citations[:2]:
        quote = item.get("quote", "") if isinstance(item, dict) else str(item)
        verified = _citation(text, quote)
        if verified and verified not in citations:
            citations.append(verified)

    if not citations and value is not None:
        inferred = _citation(text, str(value))
        if inferred:
            citations.append(inferred)

    try:
        confidence = float(candidate.get("confidence", 0.0))
    except (TypeError, ValueError):
        confidence = 0.0
    confidence = max(0.0, min(1.0, confidence))
    if value is not None and not citations:
        confidence = min(confidence, 0.55)

    fallback_value = fallback.get("value")
    fallback_confidence = float(fallback.get("confidence") or 0.0)
    fallback_citations = fallback.get("citations") or []
    if value is None and fallback_value is not None:
        return dict(fallback)

    # Exact label/amount/date matches are deterministic evidence. Prefer them
    # when a model answer conflicts or cannot provide a verifiable quote.
    if fallback_value is not None and fallback_citations and fallback_confidence >= 0.78:
        comparable_value = str(value).strip().lower() if value is not None else ""
        comparable_fallback = str(fallback_value).strip().lower()
        if comparable_value != comparable_fallback or not citations:
            preferred = dict(fallback)
            preferred["source"] = "RULE_VERIFIED"
            return preferred

    return {
        "value": value,
        "confidence": round(confidence, 2),
        "citations": citations,
        "source": "LLM",
    }


def validate_extraction(raw: dict, text: str, hints: dict[str, dict] | None = None) -> dict:
    """Normalize model output and reject citations absent from the source text."""
    hints = hints or deterministic_hints(text)
    raw_fields = raw.get("fields", raw) if isinstance(raw, dict) else {}
    fields = {
        key: _normalize_field(key, raw_fields.get(key), text, hints.get(key, _field()))
        for key in FIELD_KEYS
    }

    warnings: list[str] = []
    effective = fields["effectiveDate"]["value"]
    expiry = fields["expiryDate"]["value"]
    if effective and expiry and expiry < effective:
        warnings.append("到期日期早于生效日期，请人工核对")

    needs_confirmation = []
    for key, field in fields.items():
        if key in _REQUIRED_FIELDS and field["value"] is None:
            needs_confirmation.append(key)
        elif field["value"] is not None and field["confidence"] < 0.85:
            needs_confirmation.append(key)
    # The system cannot infer which legal party belongs to the logged-in user.
    needs_confirmation.append("ourSide")

    return {
        "schemaVersion": SCHEMA_VERSION,
        "fields": fields,
        "needsConfirmation": list(dict.fromkeys(needs_confirmation)),
        "warnings": warnings,
    }


def _candidate(validated: dict, key: str, min_confidence: float = 0.5) -> Any:
    field = (validated.get("fields") or {}).get(key) or {}
    value = field.get("value")
    if value is None or value == "":
        return None
    try:
        confidence = float(field.get("confidence") or 0.0)
    except (TypeError, ValueError):
        confidence = 0.0
    if confidence < min_confidence:
        return None
    return value


def _case_backfill_patch(validated: dict) -> dict[str, Any]:
    patch: dict[str, Any] = {}

    title = _candidate(validated, "contractTitle")
    if title:
        patch["title"] = str(title).strip()[:512]

    contract_type = str(_candidate(validated, "contractType") or "").strip().upper()
    if contract_type in CONTRACT_TYPES:
        patch["contract_type"] = contract_type

    party_a = _candidate(validated, "partyA")
    party_b = _candidate(validated, "partyB")
    if party_a:
        patch["our_entity"] = str(party_a).strip()[:256]
    if party_b:
        patch["counterparty"] = str(party_b).strip()[:256]

    amount = _candidate(validated, "amount")
    if amount is not None:
        patch["amount"] = amount
    currency = str(_candidate(validated, "currency") or "").strip().upper()
    if currency:
        patch["currency"] = currency

    effective_date = _candidate(validated, "effectiveDate")
    expiry_date = _candidate(validated, "expiryDate")
    if effective_date:
        patch["effective_date"] = str(effective_date)
    if expiry_date:
        patch["expiry_date"] = str(expiry_date)
    if effective_date and expiry_date and str(expiry_date) < str(effective_date):
        patch.pop("expiry_date", None)

    department = _candidate(validated, "department", 0.6)
    if department:
        patch["department"] = str(department).strip()[:128]

    return {key: value for key, value in patch.items() if value not in (None, "")}


def _blank(value: Any) -> bool:
    return value is None or str(value).strip() == ""


def _is_placeholder_title(value: Any, file_name: str) -> bool:
    title = str(value or "").strip()
    if not title:
        return True
    if "待识别" in title:
        return True
    file_stem = re.sub(r"\.(txt|pdf|docx?|md|markdown)$", "", file_name or "", flags=re.IGNORECASE).strip()
    return bool(file_stem) and title == file_stem


def _should_backfill(column: str, current: dict, file_name: str) -> bool:
    value = current.get(column)
    if column == "title":
        return _is_placeholder_title(value, file_name)
    if column == "contract_type":
        return _blank(value) or str(value).strip().upper() == "OTHER"
    if column == "currency":
        return _blank(value)
    return _blank(value)


def _ensure_case_party(cur, case_id: int, role: str, name: str | None) -> None:
    if not name:
        return
    cur.execute(
        "SELECT COUNT(*) AS total FROM contract_party WHERE case_id=%s AND party_role=%s",
        (case_id, role),
    )
    row = cur.fetchone() or {}
    if int(row.get("total") or 0) == 0:
        cur.execute(
            "INSERT INTO contract_party (case_id, party_name, party_role) VALUES (%s,%s,%s)",
            (case_id, name, role),
        )


def _backfill_case_from_validated(cur, intake: dict, validated: dict) -> dict:
    case_id = intake.get("case_id")
    if not case_id:
        return {}
    patch = _case_backfill_patch(validated)
    cur.execute(
        """SELECT id, title, contract_type, our_entity, counterparty, amount,
                  currency, effective_date, expiry_date, department, status
           FROM contract_case
           WHERE id=%s AND deleted=0
           FOR UPDATE""",
        (case_id,),
    )
    current = cur.fetchone()
    if not current:
        return {}

    updates: dict[str, Any] = {}
    file_name = str(intake.get("file_name") or "")
    for column, value in patch.items():
        if _should_backfill(column, current, file_name):
            updates[column] = value

    status = str(current.get("status") or "").upper()
    if status in {"DRAFT", "INTAKE_PARSING", "INTAKE_CONFIRMING"}:
        updates["status"] = "INTAKE_CONFIRMING"

    if updates:
        assignments = ", ".join(f"{column}=%s" for column in updates)
        cur.execute(
            f"UPDATE contract_case SET {assignments} WHERE id=%s AND deleted=0",
            list(updates.values()) + [case_id],
        )

    _ensure_case_party(cur, int(case_id), "OUR_ENTITY", updates.get("our_entity") or patch.get("our_entity"))
    _ensure_case_party(cur, int(case_id), "COUNTERPARTY", updates.get("counterparty") or patch.get("counterparty"))
    return updates


def build_excerpts(text: str) -> str:
    """Bound model input while retaining front matter, signatures and key clauses."""
    if len(text) <= _MAX_EXCERPT_CHARS:
        return text
    windows = [text[:28_000], text[-12_000:]]
    for keyword in ("合同金额", "合同价款", "生效日期", "到期日期", "甲方", "乙方"):
        index = text.find(keyword)
        if index >= 0:
            windows.append(text[max(0, index - 800):index + 2200])
    result = "\n\n[...合同片段分隔...]\n\n".join(windows)
    return result[:_MAX_EXCERPT_CHARS]


def extract_intake(intake_id: int) -> dict:
    """Extract and persist one intake. LLM failure degrades to rule candidates."""
    try:
        with _conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """SELECT id, file_name, source_type, case_id, content_text, content_hash
                       FROM contract_intake WHERE id=%s""",
                    (intake_id,),
                )
                intake = cur.fetchone()
                if not intake:
                    raise ValueError(f"Contract intake {intake_id} not found")
                cur.execute(
                    "UPDATE contract_intake SET status='EXTRACTING', error_message=NULL WHERE id=%s",
                    (intake_id,),
                )
            conn.commit()

        text = str(intake.get("content_text") or "")
        if not text.strip() and intake.get("case_id"):
            with _conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """SELECT content_text
                           FROM contract_document
                           WHERE case_id=%s AND parse_status='READY'
                             AND content_text IS NOT NULL
                           ORDER BY version DESC, id DESC
                           LIMIT 1""",
                        (intake["case_id"],),
                    )
                    document = cur.fetchone()
                    text = str((document or {}).get("content_text") or "")
        if not text.strip():
            raise ValueError("Contract intake text is empty")
        content_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
        if intake.get("content_hash") and intake["content_hash"] != content_hash and intake.get("source_type") != "FILE":
            raise ValueError("Contract intake content hash does not match")

        hints = deterministic_hints(text, str(intake.get("file_name") or ""))
        raw: dict = {}
        llm_error = None
        try:
            raw = LLMService().extract_contract_metadata(
                str(intake.get("file_name") or ""), build_excerpts(text), hints
            )
        except Exception as exc:
            llm_error = str(exc)[:1000]
            logger.exception("LLM contract intake extraction failed; using deterministic hints")

        validated = validate_extraction(raw, text, hints)
        validated.update({
            "model": settings.llm_model,
            "promptVersion": PROMPT_VERSION,
            "sourceHash": content_hash,
            "llmAvailable": llm_error is None,
        })
        if llm_error:
            validated["warnings"].append("模型提取不可用，当前仅展示规则识别结果")

        with _conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """UPDATE contract_intake
                       SET status='NEEDS_CONFIRMATION', content_text=%s, content_hash=%s,
                           extracted_json=%s, validated_json=%s,
                           schema_version=%s, prompt_version=%s, model=%s, error_message=%s
                       WHERE id=%s""",
                    (
                        text,
                        content_hash,
                        json.dumps(raw, ensure_ascii=False),
                        json.dumps(validated, ensure_ascii=False),
                        SCHEMA_VERSION,
                        PROMPT_VERSION,
                        settings.llm_model,
                        llm_error,
                        intake_id,
                    ),
                )
                _backfill_case_from_validated(cur, intake, validated)
            conn.commit()
        return {"intakeId": intake_id, "status": "NEEDS_CONFIRMATION", "validated": validated}
    except Exception as exc:
        logger.exception("Contract intake %s extraction failed", intake_id)
        try:
            with _conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "UPDATE contract_intake SET status='FAILED', error_message=%s WHERE id=%s",
                        (str(exc)[:1000], intake_id),
                    )
                conn.commit()
        except Exception:
            logger.exception("Could not persist intake extraction failure")
        return {"intakeId": intake_id, "status": "FAILED", "error": str(exc)}
