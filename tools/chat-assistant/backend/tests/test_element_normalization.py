"""Deterministic base-identity normalization + dedicated validation
(PRD Phase 5, task 3): money / currency / party / title / date must be
reproducible without any LLM involved."""

from decimal import Decimal

from app.agent_runtime.graph.element_normalization import (
    normalize_currency,
    normalize_date,
    normalize_money,
    normalize_party_name,
    normalize_title,
    validate_base_field,
    validate_date_element,
    validate_money_element,
    validate_structured_element,
)


# ── money ────────────────────────────────────────────────────────────────────

def test_money_numeric_value_passes_through():
    result = normalize_money(18600000)
    assert result["ok"] is True
    assert result["amount"] == Decimal("18600000")
    assert result["currency"] is None


def test_money_arabic_with_wan_multiplier():
    result = normalize_money("1860万元")
    assert result["ok"] is True
    assert result["amount"] == Decimal("18600000")
    assert result["multiplier"] == 10000


def test_money_thousands_separators_and_decimals():
    result = normalize_money("1,860,000.00")
    assert result["amount"] == Decimal("1860000")


def test_money_chinese_uppercase_numeral():
    result = normalize_money("人民币壹仟捌佰陆拾万元整（¥1860万元）")
    assert result["ok"] is True
    assert result["amount"] == Decimal("18600000")
    assert result["currency"] == "CNY"


def test_money_pure_chinese_numeral_without_arabic():
    result = normalize_money("壹佰贰拾叁万肆仟伍佰陆拾柒")
    assert result["amount"] == Decimal("1234567")


def test_money_currency_symbol_and_multiplier():
    result = normalize_money("5万美元")
    assert result["amount"] == Decimal("50000")
    assert result["currency"] == "USD"


def test_money_unparseable_is_flagged():
    result = normalize_money("按审计报告据实结算")
    assert result["ok"] is False
    assert result["amount"] is None


def test_money_empty_is_flagged():
    assert normalize_money(None)["ok"] is False
    assert normalize_money("")["ok"] is False


# ── currency ─────────────────────────────────────────────────────────────────

def test_currency_aliases_map_to_iso():
    assert normalize_currency("人民币")["currency"] == "CNY"
    assert normalize_currency("¥")["currency"] == "CNY"
    assert normalize_currency("美元")["currency"] == "USD"
    assert normalize_currency("US$")["currency"] == "USD"
    assert normalize_currency("欧元")["currency"] == "EUR"


def test_currency_bare_iso_code():
    result = normalize_currency("CNY")
    assert result["currency"] == "CNY" and result["ok"] is True


def test_currency_bare_yuan():
    assert normalize_currency("18600000元")["currency"] == "CNY"


def test_currency_unknown_is_flagged():
    result = normalize_currency("卢布")
    assert result["ok"] is False and result["currency"] is None


# ── party / title ────────────────────────────────────────────────────────────

def test_party_name_trims_and_normalizes_fullwidth_parens():
    result = normalize_party_name("  江西省电力设计院（联合体牵头人） ")
    assert result["ok"] is True
    assert result["value"] == "江西省电力设计院(联合体牵头人)"


def test_party_name_empty_is_flagged():
    assert normalize_party_name("  ")["ok"] is False


def test_title_strips_book_brackets():
    result = normalize_title("《勘察设计合同》")
    assert result["value"] == "勘察设计合同"
    assert result["ok"] is True


# ── date ─────────────────────────────────────────────────────────────────────

def test_date_formats():
    assert normalize_date("2012-12-12")["date"] == "2012-12-12"
    assert normalize_date("2012/12/12")["date"] == "2012-12-12"
    assert normalize_date("2012.12.12")["date"] == "2012-12-12"
    assert normalize_date("2012年12月12日")["date"] == "2012-12-12"
    assert normalize_date("20121212")["date"] == "2012-12-12"


def test_date_invalid_calendar_is_flagged():
    result = normalize_date("2012-13-40")
    assert result["ok"] is False and result["date"] is None


def test_date_conditional_text_is_flagged_not_guessed():
    result = normalize_date("自验收合格之日起")
    assert result["ok"] is False


# ── dedicated base-field validation ──────────────────────────────────────────

def test_base_field_amount_valid():
    result = validate_base_field("amount", "1860万元")
    assert result["status"] == "EXTRACTED"
    assert result["normalized"]["amount"] == Decimal("18600000")


def test_base_field_amount_invalid():
    assert validate_base_field("amount", "以最终结算为准")["status"] == "NEEDS_REVIEW"


def test_base_field_our_side_allowlist():
    assert validate_base_field("ourSide", "B")["status"] == "EXTRACTED"
    result = validate_base_field("ourSide", "X")
    assert result["status"] == "NEEDS_REVIEW"
    assert any("非枚举值" in issue for issue in result["issues"])


def test_base_field_date_ok_and_bad():
    assert validate_base_field("effectiveDate", "2012-12-12")["status"] == "EXTRACTED"
    assert validate_base_field("effectiveDate", "2012年13月12日")["status"] == "NEEDS_REVIEW"


def test_base_field_unknown_key_needs_review():
    assert validate_base_field("no_such_field", "x")["status"] == "NEEDS_REVIEW"


# ── dedicated element validation ─────────────────────────────────────────────

def test_money_element_valid_structured_value():
    ok, issues = validate_money_element({"amount": "1860万元", "currency": "CNY"})
    assert ok is True and issues == []


def test_money_element_relative_amount_without_number_is_legitimate():
    ok, issues = validate_money_element({"amount": None, "currency": "CNY"})
    assert ok is True


def test_money_element_currency_conflict_flagged():
    ok, issues = validate_money_element({"amount": "1860万元", "currency": "USD"})
    assert ok is False
    assert any("冲突" in issue for issue in issues)


def test_money_element_unparseable_amount_flagged():
    ok, issues = validate_money_element({"amount": "按时支付", "currency": "CNY"})
    assert ok is False
    assert any("无法确定性解析" in issue for issue in issues)


def test_date_element_valid_and_conditional():
    assert validate_date_element("2012-12-12")[0] is True
    assert validate_date_element({"value": "2012年12月12日"})[0] is True
    assert validate_date_element(None)[0] is True  # conditional date is legitimate


def test_date_element_garbage_flagged():
    ok, issues = validate_date_element("大概年底")
    assert ok is False
    assert any("无法确定性解析" in issue for issue in issues)


def test_party_element_validated():
    ok, _ = validate_structured_element("PARTY", {"value": "华能安源发电有限责任公司"})
    assert ok is True
    ok, issues = validate_structured_element("PARTY", {"value": " "})
    assert ok is False


def test_text_elements_pass_without_special_checks():
    assert validate_structured_element("TEXT", "任意文本") == (True, [])
