"""Contract intake metadata extraction with citation validation."""

from __future__ import annotations

import hashlib
import json
import logging
import re
from datetime import datetime
from decimal import Decimal, InvalidOperation
from difflib import SequenceMatcher
from typing import Any

from app.config import settings
from app.services.llm_service import LLMService

from .persistence import _conn

logger = logging.getLogger(__name__)

SCHEMA_VERSION = "contract-intake-v2"
PROMPT_VERSION = "contract-intake-v2"
FIELD_KEYS = (
    "contractTitle",
    "contractType",
    "partyA",
    "partyB",
    "amount",
    "currency",
    "signedDate",
    "effectiveDate",
    "expiryDate",
    "department",
)
CONTRACT_TYPES = {"SERVICE_PROCUREMENT", "GOODS_PURCHASE", "NDA", "OTHER"}
_REQUIRED_FIELDS = {"contractTitle", "contractType", "partyA", "partyB"}
_MAX_EXCERPT_CHARS = 48_000
_AMOUNT_LABEL_PATTERN = "(?:\u5408\u540c(?:\u603b)?\u91d1\u989d|\u5408\u540c\u4ef7\u6b3e|\u542b\u7a0e\u603b\u4ef7|\u603b\u4ef7)"
_AMOUNT_CURRENCY_PATTERN = "(?:\u4eba\u6c11\u5e01|RMB|CNY|\uffe5)"
_AMOUNT_VALUE_PATTERN = re.compile(
    rf"(?:(?P<currency>{_AMOUNT_CURRENCY_PATTERN})\s*)?"
    r"(?P<number>[0-9][0-9,，]*(?:\.\d+)?)\s*"
    rf"(?P<unit>万|亿)?\s*(?P<yuan>元)?\s*(?P<suffix_currency>{_AMOUNT_CURRENCY_PATTERN})?",
    re.IGNORECASE,
)
_TITLE_LABEL_PATTERN = re.compile(
    r"^(?:合同)?(?:编号|编码|号|签订地点|签订日期|签订时间|填写说明|目录|附件)\s*[:：]?",
    re.IGNORECASE,
)
_FILE_NAME_EXTENSION_PATTERN = re.compile(r"\.(?:txt|pdf|docx?|md|markdown)$", re.IGNORECASE)
_FILE_NAME_SUFFIX_NOISE_PATTERN = re.compile(
    r"(?:20\d{2}[-_.年]\d{1,2}(?:[-_.月]\d{1,2}日?)?|\d{8}|\d{1,2}[._-]\d{1,2}|"
    r"v(?:ersion)?\s*\d+(?:\.\d+)*|版本\s*\d+(?:\.\d+)*|"
    r"最终版|终版|定稿版|修改版|修订版|扫描件|扫描版|复印件|副本|盖章版|签字版|草案)",
    re.IGNORECASE,
)
_GENERIC_CONTRACT_TITLES = {
    "合同", "合同书", "协议", "协议书", "确认书",
    "技术服务合同", "技术服务协议", "服务合同", "服务协议",
    "咨询合同", "咨询协议", "采购合同", "采购协议", "合作协议",
    "保密协议", "保密合同", "勘察设计合同", "建设工程合同",
}



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


def _is_plausible_title(value: Any) -> bool:
    title = re.sub(r"\s+", " ", str(value or "")).strip(" ：:;；")
    if len(title) < 4 or len(title) > 256:
        return False
    if _TITLE_LABEL_PATTERN.match(title):
        return False
    return any(word in title for word in ("合同", "协议", "确认书"))


def _is_generic_contract_title(value: Any) -> bool:
    normalized = re.sub(r"[\s_\-—]", "", str(value or "")).strip(" ：:;；")
    return normalized in _GENERIC_CONTRACT_TITLES


def _clean_file_name_title(file_name: str) -> str | None:
    """Return a usable contract title from a file name without versioning noise."""
    title = str(file_name or "").replace("\\", "/").rsplit("/", 1)[-1].strip()
    title = _FILE_NAME_EXTENSION_PATTERN.sub("", title).strip()

    while title:
        match = re.search(
            rf"(?:[（(]\s*)?(?P<noise>{_FILE_NAME_SUFFIX_NOISE_PATTERN.pattern})(?:\s*[）)])?\s*$",
            title,
            re.IGNORECASE,
        )
        if not match:
            break
        title = title[:match.start()].rstrip(" ._-—")

    title = re.sub(r"[\s_\-—]+", "", title).strip(". ：:;；")
    if len(title) < 4 or len(title) > 256 or _TITLE_LABEL_PATTERN.match(title):
        return None
    if _is_generic_contract_title(title):
        return None
    return title or None


def _amount_values_in_quote(quote: str) -> set[float]:
    values: set[float] = set()
    for match in _AMOUNT_VALUE_PATTERN.finditer(str(quote or "")):
        if not (
            match.group("currency") or match.group("suffix_currency")
            or match.group("unit") or match.group("yuan")
        ):
            continue
        suffix = str(quote or "")[match.end():match.end() + 2]
        if suffix.lstrip().startswith("%"):
            continue
        raw = match.group("number") + (match.group("unit") or "")
        normalized = _normalize_amount(raw)
        if normalized is not None:
            values.add(normalized)
    return values


def _extract_amount_candidates(text: str) -> list[dict[str, Any]]:
    """Recall amount candidates while classifying percentages away from totals."""
    candidates: list[dict[str, Any]] = []
    seen: set[tuple[int, str]] = set()

    def append_candidate(
        *, start: int, end: int, raw_value: str, normalized_value: float | None,
        semantic_type: str, confidence: float, reason: str,
    ) -> None:
        key = (start, semantic_type)
        if key in seen:
            return
        seen.add(key)
        quote_start = max(0, start - 56)
        quote_end = min(len(text), end + 56)
        quote = text[quote_start:quote_end].strip()
        actual_start = text.find(quote, quote_start, quote_end + 1) if quote else -1
        citation = None if actual_start < 0 else {
            "quote": quote,
            "startOffset": actual_start,
            "endOffset": actual_start + len(quote),
        }
        candidates.append({
            "rawValue": raw_value,
            "normalizedValue": normalized_value,
            "semanticType": semantic_type,
            "source": "RULE",
            "confidence": confidence,
            "citation": citation,
            "selected": False,
            "reason": reason,
        })

    for label_match in re.finditer(_AMOUNT_LABEL_PATTERN, text, flags=re.IGNORECASE):
        tail_limit = min(len(text), label_match.end() + 160)
        tail = text[label_match.end():tail_limit]
        boundary_positions = [
            index for marker in ("。", "；", ";", "\n")
            if (index := tail.find(marker)) >= 0
        ]
        if boundary_positions:
            tail = tail[:min(boundary_positions)]

        for amount_match in _AMOUNT_VALUE_PATTERN.finditer(tail):
            suffix = tail[amount_match.end():amount_match.end() + 3]
            prefix = tail[:amount_match.start()]
            has_percent = suffix.lstrip().startswith("%")
            if has_percent:
                start = label_match.end() + amount_match.start()
                append_candidate(
                    start=start,
                    end=start + len(amount_match.group("number")) + len(suffix),
                    raw_value=amount_match.group("number"),
                    normalized_value=None,
                    semantic_type="PERCENTAGE",
                    confidence=0.98,
                    reason="金额后紧跟百分号，不是合同总金额",
                )
                continue

            has_money_marker = bool(
                amount_match.group("currency")
                or amount_match.group("suffix_currency")
                or amount_match.group("unit")
                or amount_match.group("yuan")
            )
            if not has_money_marker:
                continue
            raw_value = amount_match.group("number") + (amount_match.group("unit") or "")
            normalized = _normalize_amount(raw_value)
            if normalized is None:
                continue
            explicit_relation = bool(re.search(r"(?:为|是|[:：])\s*", prefix))
            confidence = 0.94 if explicit_relation else 0.86
            start = label_match.end() + amount_match.start()
            append_candidate(
                start=start,
                end=start + len(amount_match.group(0)),
                raw_value=amount_match.group(0).strip(),
                normalized_value=normalized,
                semantic_type="CONTRACT_TOTAL",
                confidence=confidence,
                reason="合同总价标签后的货币金额",
            )
            break

    for match in re.finditer(r"(?<!\d)(\d+(?:\.\d+)?)\s*%", text):
        append_candidate(
            start=match.start(), end=match.end(), raw_value=match.group(0),
            normalized_value=None, semantic_type="PERCENTAGE", confidence=0.98,
            reason="百分比不是货币金额",
        )

    for match in _AMOUNT_VALUE_PATTERN.finditer(text):
        suffix = text[match.end():match.end() + 2]
        if suffix.lstrip().startswith("%"):
            continue
        if not (
            match.group("currency") or match.group("suffix_currency")
            or match.group("unit") or match.group("yuan")
        ):
            continue
        raw_value = match.group("number") + (match.group("unit") or "")
        normalized = _normalize_amount(raw_value)
        if normalized is None:
            continue
        clause_start = max(
            [text.rfind(marker, max(0, match.start() - 120), match.start()) for marker in ("。", "；", ";", "\n")]
            + [-1]
        ) + 1
        clause_ends = [
            index for marker in ("。", "；", ";", "\n")
            if (index := text.find(marker, match.end(), min(len(text), match.end() + 120))) >= 0
        ]
        clause_end = min(clause_ends) if clause_ends else min(len(text), match.end() + 120)
        nearby = text[clause_start:clause_end]
        prefix = text[max(clause_start, match.start() - 40):match.start()]
        if re.search(r"(?:合同(?:总)?金额|合同价款|含税总价|总价)\s*(?:为|是|[:：])\s*$", prefix):
            semantic_type, confidence, reason = "CONTRACT_TOTAL", 0.94, "合同总额标签直接修饰该金额"
        elif re.search(r"履约保函|保证金|质保金|担保", nearby):
            semantic_type, confidence, reason = "GUARANTEE", 0.9, "保证金或担保金额"
        elif re.search(r"违约金|赔偿金|罚款|扣罚", nearby):
            semantic_type, confidence, reason = "PENALTY", 0.9, "违约、赔偿或罚款金额"
        elif re.search(r"单价|每(?:人|件|套|台|吨|公斤|千克|小时|工日)|/[a-zA-Z\u4e00-\u9fff]", nearby):
            semantic_type, confidence, reason = "UNIT_PRICE", 0.88, "单价或计量价格"
        elif re.search(r"预付款|进度款|阶段款|尾款|付款|支付|结算", nearby):
            semantic_type, confidence, reason = "PAYMENT_INSTALLMENT", 0.86, "分期付款或结算金额"
        elif re.search(_AMOUNT_LABEL_PATTERN, nearby, flags=re.IGNORECASE):
            semantic_type, confidence, reason = "CONTRACT_TOTAL", 0.86, "合同总额标签附近的货币金额"
        else:
            semantic_type, confidence, reason = "OTHER", 0.65, "未能确定业务类型的货币金额"
        append_candidate(
            start=match.start(), end=match.end(), raw_value=match.group(0).strip(),
            normalized_value=normalized, semantic_type=semantic_type,
            confidence=confidence, reason=reason,
        )

    totals = [item for item in candidates if item["semanticType"] == "CONTRACT_TOTAL"]
    if totals:
        selected = max(totals, key=lambda item: float(item.get("confidence") or 0.0))
        selected["selected"] = True

    compacted: list[dict[str, Any]] = []
    for semantic_type in (
        "CONTRACT_TOTAL", "GUARANTEE", "PAYMENT_INSTALLMENT",
        "PENALTY", "UNIT_PRICE", "PERCENTAGE", "OTHER",
    ):
        typed = [item for item in candidates if item["semanticType"] == semantic_type]
        typed.sort(
            key=lambda item: (bool(item.get("selected")), float(item.get("confidence") or 0.0)),
            reverse=True,
        )
        compacted.extend(typed[:4])
    return compacted[:32]



def _extract_amount_hint(text: str) -> tuple[str | None, dict | None]:
    selected = next(
        (item for item in _extract_amount_candidates(text) if item.get("selected")),
        None,
    )
    if not selected:
        return None, None
    return str(selected["rawValue"]), selected.get("citation")

def deterministic_hints(text: str, file_name: str = "") -> dict[str, dict]:
    """Extract conservative candidates without calling the model."""
    hints = {key: _field() for key in FIELD_KEYS}

    title = None
    title_quote = None
    title_source = "RULE"
    file_name_title = _clean_file_name_title(file_name)
    # Read first 30 lines, merge short consecutive lines (PDF often splits titles)
    raw_lines = [line.strip() for line in text.splitlines()[:30]]
    merged_lines: list[str] = []
    structured_line_pattern = re.compile(
        r"(?:甲方|乙方|合同(?:编号|编码|(?:总)?金额)|合同价款|生效日期|合同生效日|到期日期|合同到期日|"
        r"签订日期|签订时间|签署日期|签署时间|所属部门|业务部门|需求部门|采购部门|经办部门)\s*[:：]"
    )

    # Covers commonly split PDF titles such as company / project / "勘察设计合同".
    cover_candidates: list[tuple[str, str, int]] = []
    for index, line in enumerate(raw_lines):
        if not _is_plausible_title(line) or structured_line_pattern.search(line):
            continue
        parts = [line]
        if len(line) <= 40 and re.search(r"(?:合同|协议|确认书)\s*$", line):
            preceding = raw_lines[max(0, index - 2):index]
            if preceding and all(
                part
                and len(part) <= 100
                and not structured_line_pattern.search(part)
                and not _TITLE_LABEL_PATTERN.match(part)
                and not re.fullmatch(r"[\W_A-Z0-9-]+", part)
                for part in preceding
            ):
                parts = preceding + parts
        value = " ".join(parts)
        if _is_plausible_title(value):
            quote = "\n".join(parts)
            cover_candidates.append((value, quote, len(value)))
    if cover_candidates:
        title, title_quote, _ = max(cover_candidates, key=lambda item: item[2])

    i = 0
    while i < len(raw_lines):
        line = raw_lines[i]
        if not line:
            i += 1
            continue
        # If this line is short (< 80 chars) and next line also short, merge
        while (i + 1 < len(raw_lines) and len(line) < 80
               and raw_lines[i + 1] and len(raw_lines[i + 1]) < 80
               and not structured_line_pattern.search(line)
               and not structured_line_pattern.search(raw_lines[i + 1])):
            i += 1
            line = line + raw_lines[i]
        merged_lines.append(line)
        i += 1

    # Find the longest merged line containing contract keywords
    candidates = [
        (line, len(line))
        for line in merged_lines
        if 2 <= len(line) <= 200
        and any(word in line for word in ("合同", "协议", "确认书"))
        and not structured_line_pattern.search(line)
        and _is_plausible_title(line)
    ]
    if not title and candidates:
        candidates.sort(key=lambda x: x[1], reverse=True)
        title = candidates[0][0]
        title_quote = title
    if file_name_title and (not title or _is_generic_contract_title(title)):
        title = file_name_title
        title_quote = None
        title_source = "FILE_NAME"
    if title:
        hints["contractTitle"] = _field(
            title, 0.82 if title_quote else 0.62,
            _citation(text, title_quote or ""),
            title_source,
        )

    # ── Party identification: expanded terminology for construction/procurement ──
    party_a = _line_match(text, (
        "甲方", "委托方", "采购方", "买方", "买受人", "需方", "发包人", "定作人",
        "业主", "发包方", "招标人", "建设方", "需方",
    ))
    party_b = _line_match(text, (
        "乙方", "受托方", "供应商", "卖方", "出卖人", "供方", "承包人", "承揽人", "服务方",
        "承包方", "承包商", "设计方", "施工方", "监理方", "投标人",
    ))
    if party_a:
        hints["partyA"] = _field(party_a[0], 0.78, _citation(text, party_a[1]))
    if party_b:
        hints["partyB"] = _field(party_b[0], 0.78, _citation(text, party_b[1]))

    title_field = hints["contractTitle"]
    title_value = str(title_field.get("value") or "")
    title_prefix, separator, title_rest = title_value.partition(" ")
    legal_parties = [value[0] for value in (party_a, party_b) if value]
    if separator and len(title_prefix) >= 5 and legal_parties:
        replacement = max(
            legal_parties,
            key=lambda value: SequenceMatcher(None, title_prefix, value).ratio(),
        )
        similarity = SequenceMatcher(None, title_prefix, replacement).ratio()
        if similarity >= 0.82 and title_prefix != replacement:
            title_field["value"] = f"{replacement} {title_rest}"
            title_field["confidence"] = max(float(title_field.get("confidence") or 0), 0.86)
            title_field["source"] = "RULE_NORMALIZED"

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

    for key, labels in (
        ("signedDate", ("签订日期", "签订时间", "签署日期", "签署时间", "签约日期", "签约时间")),
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
            if 2 <= len(line) <= 120 and _is_plausible_title(line):
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

    amount_candidates = _extract_amount_candidates(text)
    selected_amount = next((item for item in amount_candidates if item.get("selected")), None)
    if selected_amount is not None:
        hints["amount"] = _field(
            selected_amount["normalizedValue"],
            selected_amount["confidence"],
            selected_amount.get("citation"),
        )
        hints["amount"].update({
            "semanticType": "CONTRACT_TOTAL",
            "candidates": amount_candidates,
        })
        hints["currency"] = _field("CNY", 0.88, selected_amount.get("citation"))

    for key, labels in (
        ("signedDate", ("签订日期", "签订时间", "签署日期", "签署时间", "签约日期", "签约时间")),
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
    elif key in {"signedDate", "effectiveDate", "expiryDate"}:
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

    validation_errors: list[str] = []
    if key == "contractTitle" and value is not None and not _is_plausible_title(value):
        validation_errors.append("标题候选是字段标签、通用页眉或不完整标题")
    if key == "amount" and value is not None and citations:
        cited_values = {
            amount
            for citation in citations
            for amount in _amount_values_in_quote(citation.get("quote", ""))
        }
        if cited_values and float(value) not in cited_values:
            validation_errors.append("模型金额与引用中的货币金额不一致")

    fallback_value = fallback.get("value")
    fallback_citations = fallback.get("citations") or []
    is_file_name_title = key == "contractTitle" and fallback.get("source") == "FILE_NAME"
    if is_file_name_title and _is_generic_contract_title(value):
        preferred = dict(fallback)
        preferred["validationErrors"] = []
        preferred["decisionStatus"] = "PROPOSED"
        return preferred

    model_usable = value is not None and bool(citations) and not validation_errors
    if model_usable:
        return {
            "value": value,
            "confidence": round(confidence, 2),
            "citations": citations,
            "source": "LLM",
            "validationErrors": [],
            "decisionStatus": "PROPOSED",
        }

    fallback_usable = fallback_value is not None and bool(fallback_citations)
    if is_file_name_title:
        fallback_usable = _clean_file_name_title(str(fallback_value)) is not None
    if key == "contractTitle" and fallback_usable:
        fallback_usable = _is_plausible_title(fallback_value)
    if fallback_usable:
        preferred = dict(fallback)
        preferred["source"] = "FILE_NAME" if is_file_name_title else "RULE_FALLBACK"
        preferred["validationErrors"] = validation_errors
        preferred["decisionStatus"] = "PROPOSED"
        return preferred

    return {
        "value": value,
        "confidence": round(confidence, 2),
        "citations": citations,
        "source": "LLM",
        "validationErrors": validation_errors,
        "decisionStatus": "NEEDS_REVIEW" if value is not None else "NOT_FOUND",
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


def _enrich_intake_citations(cur: Any, case_id: int | None, validated: dict) -> dict:
    if not case_id:
        return validated
    cur.execute(
        """SELECT id, content_hash AS contentHash, parse_provider AS parseProvider
           FROM contract_document
           WHERE case_id=%s AND document_type='MAIN' AND COALESCE(deleted,0)=0
           ORDER BY version DESC, id DESC LIMIT 1""",
        (case_id,),
    )
    document = cur.fetchone() or {}
    document_id = document.get("id")
    clauses: list[dict[str, Any]] = []
    if document_id:
        cur.execute(
            """SELECT id AS clauseId, clause_number AS clauseNumber,
                      page_number AS pageNumber, content
               FROM contract_clause
               WHERE case_id=%s AND document_id=%s ORDER BY id""",
            (case_id, document_id),
        )
        clauses = list(cur.fetchall())

    for field in (validated.get("fields") or {}).values():
        if not isinstance(field, dict):
            continue
        for citation in field.get("citations") or []:
            if not isinstance(citation, dict):
                continue
            quote = str(citation.get("quote") or "").strip()
            citation.update({
                "documentId": document_id,
                "contentHash": document.get("contentHash"),
                "parserVersion": document.get("parseProvider"),
            })
            if not quote:
                continue
            clause = next(
                (item for item in clauses if quote in str(item.get("content") or "")),
                None,
            )
            if clause:
                citation.update({
                    "clauseId": clause.get("clauseId"),
                    "clauseNumber": clause.get("clauseNumber"),
                    "pageNumber": clause.get("pageNumber"),
                })
    return validated


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

    signed_date = _candidate(validated, "signedDate")
    effective_date = _candidate(validated, "effectiveDate")
    expiry_date = _candidate(validated, "expiryDate")
    if signed_date:
        patch["signed_date"] = str(signed_date)
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


def _preconfirmation_case_updates(validated: dict) -> dict[str, Any]:
    """Return the only case mutation allowed before a human confirms intake facts."""
    del validated
    return {"status": "INTAKE_CONFIRMING"}


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
    """Advance file-intake workflow without promoting unconfirmed facts."""
    case_id = intake.get("case_id")
    if not case_id:
        return {}
    cur.execute(
        """SELECT id, status
           FROM contract_case
           WHERE id=%s AND deleted=0
           FOR UPDATE""",
        (case_id,),
    )
    current = cur.fetchone()
    if not current:
        return {}

    updates: dict[str, Any] = {}
    status = str(current.get("status") or "").upper()
    if status in {"DRAFT", "INTAKE_PARSING", "INTAKE_CONFIRMING"}:
        updates.update(_preconfirmation_case_updates(validated))

    if updates:
        assignments = ", ".join(f"{column}=%s" for column in updates)
        cur.execute(
            f"UPDATE contract_case SET {assignments} WHERE id=%s AND deleted=0",
            list(updates.values()) + [case_id],
        )
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
        # Fallback: read cleaned document text if intake text is empty
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
                validated = _enrich_intake_citations(cur, intake.get("case_id"), validated)
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
