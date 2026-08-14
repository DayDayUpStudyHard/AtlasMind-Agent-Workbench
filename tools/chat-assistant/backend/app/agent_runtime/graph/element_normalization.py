"""Deterministic normalization + dedicated validation for base identity
fields (PRD contract-agent-harness-v1-migration Phase 5, task 3).

金额、币种、主体、标题、日期走确定性规范化和专用校验，不经 LLM。基础
事实值必须可复现：同一个输入永远得到同一个 normalizedValue 和同一个
validation 结论，与模型、提示词版本无关。

These are pure functions with no DB / LLM / graph dependency, so tests and
nodes import them freely.
"""

from __future__ import annotations

import re
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any

__all__ = (
    "normalize_currency",
    "normalize_date",
    "normalize_money",
    "normalize_party_name",
    "normalize_title",
    "validate_base_field",
)

# ── currencies ──────────────────────────────────────────────────────────────

CURRENCY_ALIASES: dict[str, str] = {
    "CNY": "CNY", "RMB": "CNY", "人民币": "CNY", "¥": "CNY", "￥": "CNY",
    "USD": "USD", "美元": "USD", "美金": "USD", "US$": "USD", "$": "USD",
    "EUR": "EUR", "欧元": "EUR", "€": "EUR",
    "HKD": "HKD", "港币": "HKD", "港元": "HKD",
    "JPY": "JPY", "日元": "JPY",
    "GBP": "GBP", "英镑": "GBP",
}

_CN_DIGITS = {
    "零": 0, "〇": 0,
    "一": 1, "二": 2, "两": 2, "三": 3, "四": 4,
    "五": 5, "六": 6, "七": 7, "八": 8, "九": 9,
    "壹": 1, "贰": 2, "叁": 3, "肆": 4, "伍": 5,
    "陆": 6, "柒": 7, "捌": 8, "玖": 9,
}
_CN_UNIT_SMALL = {"十": 10, "拾": 10, "百": 100, "佰": 100, "千": 1000, "仟": 1000}
_CN_UNIT_BIG = {"万": 10_000, "萬": 10_000, "亿": 100_000_000, "億": 100_000_000}

_MAX_ABS_AMOUNT = Decimal("1e16")  # sanity ceiling for a contract amount


def _cn_numeral_to_int(text: str) -> int | None:
    """Convert a pure Chinese numeral (e.g. 壹仟捌佰陆拾万) to int.

    Returns None when the text contains non-numeral characters.
    """
    if not text:
        return None
    total = 0
    section = 0
    number = 0
    for char in text:
        if char in _CN_DIGITS:
            number = _CN_DIGITS[char]
        elif char in _CN_UNIT_SMALL:
            unit = _CN_UNIT_SMALL[char]
            if number == 0:
                number = 1
            section += number * unit
            number = 0
        elif char in _CN_UNIT_BIG:
            unit = _CN_UNIT_BIG[char]
            section = (section + number) * unit
            total += section
            section = 0
            number = 0
        else:
            return None
    return total + section + number


def normalize_money(value: Any) -> dict[str, Any]:
    """Deterministically parse a contract amount into amount + currency.

    Accepts numeric values, arabic-digit strings with thousands separators
    (``1,860,000.00``), unit multipliers (``1860万元``), and pure Chinese
    numerals (``壹仟捌佰陆拾万元整``). Returns::

        {"amount": Decimal|None, "currency": "CNY"|None,
         "multiplier": int, "ok": bool, "raw": str}

    ``ok=False`` means no reliable numeric amount could be parsed — the
    caller must keep the field for human review, never guess.
    """
    if value is None or value == "":
        return {"amount": None, "currency": None, "multiplier": 1, "ok": False, "raw": str(value or "")}
    raw = str(value).strip()

    currency: str | None = None
    text = raw
    for alias, code in CURRENCY_ALIASES.items():
        if alias.isascii():
            if alias in raw.upper():
                currency = code
                text = re.sub(re.escape(alias), " ", text, flags=re.IGNORECASE)
                break
        elif alias in raw:
            currency = code
            text = text.replace(alias, " ")
            break
    if currency is None and "元" in raw:
        # A bare 元 suffix (万元 / 500元) implies CNY.
        currency = "CNY"

    multiplier = 1
    if re.search(r"[万亿萬億]", text):
        if re.search(r"[亿億]", text):
            multiplier = 100_000_000
        elif re.search(r"[万萬]", text):
            multiplier = 10_000

    amount: Decimal | None = None
    arabic = re.search(r"-?\d[\d,]*(?:\.\d+)?", text)
    if arabic:
        # The unit multiplier only applies to arabic digits ("1860万元");
        # a pure Chinese numeral carries its own 万/亿 units.
        try:
            amount = Decimal(arabic.group(0).replace(",", "")) * multiplier
        except InvalidOperation:
            amount = None
    else:
        # Pure Chinese numeral, e.g. 壹仟捌佰陆拾万元整.
        chinese = re.search(r"[零〇一二两三四五六七八九十百千万亿壹贰叁肆伍陆柒捌玖拾佰仟萬億]+", text)
        numeral = _cn_numeral_to_int(chinese.group(0)) if chinese else None
        if numeral is not None:
            amount = Decimal(numeral)
            multiplier = 1

    ok = amount is not None and amount.is_finite() and abs(amount) < _MAX_ABS_AMOUNT
    return {
        "amount": amount if ok else None,
        "currency": currency,
        "multiplier": multiplier,
        "ok": bool(ok),
        "raw": raw[:4000],
    }


def normalize_currency(value: Any) -> dict[str, Any]:
    """Map a currency token to its ISO code (¥/人民币/美元 → CNY/USD/...)."""
    raw = str(value or "").strip()
    if not raw:
        return {"currency": None, "ok": False, "raw": raw}
    upper = raw.upper()
    for alias, code in CURRENCY_ALIASES.items():
        if alias.isascii():
            if alias in upper:
                return {"currency": code, "ok": True, "raw": raw}
        elif alias in raw:
            return {"currency": code, "ok": True, "raw": raw}
    # Bare Chinese suffix on a number, e.g. "18600000元" / "5万美元".
    if "元" in raw:
        return {"currency": "CNY", "ok": True, "raw": raw}
    # An uppercase ISO code alone ("CNY") normalizes to itself.
    if re.fullmatch(r"[A-Z]{3}", upper):
        return {"currency": upper, "ok": True, "raw": raw}
    return {"currency": None, "ok": False, "raw": raw}


def _normalize_whitespace(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _normalize_fullwidth(text: str) -> str:
    """Full-width parens and punctuation → half-width (values stay otherwise
    untouched: legal names and titles must not be rewritten)."""
    return (
        text.replace("（", "(").replace("）", ")")
        .replace("，", ",").replace("；", ";").replace("：", ":")
    )


def normalize_party_name(value: Any) -> dict[str, Any]:
    """Deterministic party-name normalization: whitespace + full-width only."""
    raw = str(value or "").strip()
    name = _normalize_fullwidth(_normalize_whitespace(raw))
    ok = bool(name) and len(name) >= 2
    return {"value": name if ok else None, "ok": ok, "raw": raw[:4000]}


def normalize_title(value: Any) -> dict[str, Any]:
    """Deterministic title normalization: strip book/quotation brackets and
    collapse whitespace; never rewrite words."""
    raw = str(value or "").strip()
    title = _normalize_fullwidth(_normalize_whitespace(raw))
    title = title.strip("\"'“”‘’《》〈〉【】[]()（） \t")
    ok = bool(title) and len(title) >= 2
    return {"value": title if ok else None, "ok": ok, "raw": raw[:4000]}


_DATE_PATTERNS = (
    re.compile(r"(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})"),
    re.compile(r"(\d{4})年(\d{1,2})月(\d{1,2})日?"),
    re.compile(r"(\d{4})(\d{2})(\d{2})"),  # 20121212
)


def normalize_date(value: Any) -> dict[str, Any]:
    """Deterministically parse a date into YYYY-MM-DD (calendar-validated)."""
    raw = str(value or "").strip()
    if not raw:
        return {"date": None, "ok": False, "raw": raw}
    for pattern in _DATE_PATTERNS:
        match = pattern.search(raw)
        if not match:
            continue
        year, month, day = (int(group) for group in match.groups())
        try:
            parsed = datetime(year, month, day)
        except ValueError:
            return {"date": None, "ok": False, "raw": raw[:4000]}
        return {"date": parsed.strftime("%Y-%m-%d"), "ok": True, "raw": raw[:4000]}
    return {"date": None, "ok": False, "raw": raw[:4000]}


# ── dedicated validation ─────────────────────────────────────────────────────

_BASE_FIELD_NORMALIZERS = {
    "amount": normalize_money,
    "currency": normalize_currency,
    "partyA": normalize_party_name,
    "partyB": normalize_party_name,
    "ourSide": None,  # enum, validated by allowlist below
    "contractTitle": normalize_title,
    "signedDate": normalize_date,
    "effectiveDate": normalize_date,
    "expiryDate": normalize_date,
    "contractType": None,  # enum
}

_VALID_OUR_SIDES = {"A", "B"}


def validate_base_field(field_key: str, value: Any) -> dict[str, Any]:
    """Dedicated per-field validation for the fixed base-identity WorkUnit.

    Returns ``{"normalized": {...}|None, "status": "EXTRACTED"|"NEEDS_REVIEW",
    "issues": [...]}``. Enum fields (contractType / ourSide) use allowlists
    instead of a normalizer; every other base field must parse
    deterministically or it stays for human review.
    """
    issues: list[str] = []
    if field_key in ("ourSide", "contractType"):
        enum_value = str(value or "").strip().upper()
        if field_key == "ourSide":
            ok = enum_value in _VALID_OUR_SIDES
        else:
            ok = bool(enum_value) and bool(re.fullmatch(r"[A-Z0-9_]+", enum_value))
        if not ok:
            issues.append(f"非枚举值: {str(value or '')[:200]}")
        return {"normalized": enum_value or None, "status": "EXTRACTED" if ok else "NEEDS_REVIEW", "issues": issues}

    normalizer = _BASE_FIELD_NORMALIZERS.get(field_key)
    if normalizer is None:
        return {"normalized": None, "status": "NEEDS_REVIEW", "issues": [f"无专用校验: {field_key}"]}
    normalized = normalizer(value)
    if not normalized.get("ok"):
        issues.append(f"确定性解析失败: {normalized.get('raw', '')[:200]}")
    return {
        "normalized": normalized,
        "status": "EXTRACTED" if normalized.get("ok") else "NEEDS_REVIEW",
        "issues": issues,
    }


def validate_money_element(normalized_value: Any) -> tuple[bool, list[str]]:
    """Dedicated check for MONEY-typed extracted elements (LLM or fallback).

    Returns (ok, issues): the structured value must carry a parseable amount
    and a recognized currency; relative/conditional money (null amount) is a
    legitimate structured value, not an error.
    """
    if not isinstance(normalized_value, dict):
        return False, ["MONEY 要素 normalizedValue 必须是结构化对象"]
    issues: list[str] = []
    amount = normalized_value.get("amount")
    currency = normalized_value.get("currency")
    if amount is not None:
        parsed = normalize_money(amount)
        if not parsed["ok"]:
            issues.append(f"金额无法确定性解析: {str(amount)[:120]}")
        elif currency:
            parsed_currency = normalize_currency(currency)
            if not parsed_currency["ok"]:
                issues.append(f"币种无法识别: {str(currency)[:120]}")
            elif parsed.get("currency") and parsed["currency"] != parsed_currency["currency"]:
                issues.append(
                    f"金额与币种标记冲突: {parsed['currency']} vs {parsed_currency['currency']}"
                )
    elif currency and not normalize_currency(currency)["ok"]:
        issues.append(f"币种无法识别: {str(currency)[:120]}")
    return (not issues), issues


def validate_date_element(normalized_value: Any) -> tuple[bool, list[str]]:
    """Dedicated check for DATE-typed extracted elements."""
    if normalized_value in (None, ""):
        return True, []  # conditional / undetermined dates are legitimate
    if isinstance(normalized_value, dict):
        candidate = normalized_value.get("value") or normalized_value.get("date")
    else:
        candidate = normalized_value
    parsed = normalize_date(candidate)
    if parsed["ok"]:
        return True, []
    return False, [f"日期无法确定性解析: {str(candidate)[:120]}"]


def validate_structured_element(value_type: str, normalized_value: Any) -> tuple[bool, list[str]]:
    """Type-dispatched dedicated validation for extracted elements."""
    value_type = str(value_type or "TEXT").upper()
    if value_type == "MONEY":
        return validate_money_element(normalized_value)
    if value_type == "DATE":
        return validate_date_element(normalized_value)
    if value_type == "PARTY":
        party = (
            normalized_value.get("value") if isinstance(normalized_value, dict)
            else normalized_value
        )
        parsed = normalize_party_name(party)
        return parsed["ok"], [] if parsed["ok"] else [f"主体名称无法确定性解析: {str(party)[:120]}"]
    return True, []
