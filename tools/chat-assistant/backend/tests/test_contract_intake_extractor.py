import unittest

from app.agent_runtime.contract_intake_extractor import (
    FIELD_KEYS,
    _case_backfill_patch,
    _preconfirmation_case_updates,
    deterministic_hints,
    validate_extraction,
)


CONTRACT = """技术服务合同
甲方：星河科技有限公司
乙方：云桥信息技术有限公司
合同金额：人民币 12.5 万元
生效日期：2026年8月1日
到期日期：2027年7月31日
"""


def empty_hints():
    return {
        key: {"value": None, "confidence": 0.0, "citations": [], "source": "RULE"}
        for key in FIELD_KEYS
    }


class ContractIntakeExtractorTest(unittest.TestCase):
    def test_deterministic_hints_extract_core_fields(self):
        hints = deterministic_hints(CONTRACT, "技术服务合同.txt")

        self.assertEqual("技术服务合同", hints["contractTitle"]["value"])
        self.assertEqual("星河科技有限公司", hints["partyA"]["value"])
        self.assertEqual("云桥信息技术有限公司", hints["partyB"]["value"])
        self.assertEqual(125000.0, hints["amount"]["value"])
        self.assertEqual("CNY", hints["currency"]["value"])
        self.assertEqual("2026-08-01", hints["effectiveDate"]["value"])
        self.assertEqual("2027-07-31", hints["expiryDate"]["value"])

    def test_generic_document_title_uses_cleaned_specific_file_name(self):
        text = """技术服务合同
甲方：星河科技有限公司
乙方：云桥信息技术有限公司
"""
        file_name = "复杂地形煤层开采灾害防控技术研究项目-合同-10.24-最终版（扫描件）V2.doc"

        hints = deterministic_hints(text, file_name)
        result = validate_extraction({
            "fields": {
                "contractTitle": {
                    "value": "技术服务合同",
                    "confidence": 0.98,
                    "citations": [{"quote": "技术服务合同"}],
                }
            }
        }, text, hints)

        field = result["fields"]["contractTitle"]
        self.assertEqual("复杂地形煤层开采灾害防控技术研究项目合同", field["value"])
        self.assertEqual("FILE_NAME", field["source"])
        self.assertEqual([], field["citations"])
        self.assertIn("contractTitle", result["needsConfirmation"])

    def test_invalid_file_name_does_not_replace_generic_document_title(self):
        hints = deterministic_hints(CONTRACT, "扫描件-最终版-V2.pdf")

        self.assertEqual("技术服务合同", hints["contractTitle"]["value"])

    def test_unverifiable_llm_citation_is_removed_and_confidence_capped(self):
        result = validate_extraction({
            "fields": {
                "contractTitle": {
                    "value": "模型编造的合同名称",
                    "confidence": 0.99,
                    "citations": [{"quote": "原文中不存在的引用"}],
                }
            }
        }, CONTRACT, empty_hints())

        field = result["fields"]["contractTitle"]
        self.assertEqual("模型编造的合同名称", field["value"])
        self.assertEqual([], field["citations"])
        self.assertEqual(0.55, field["confidence"])
        self.assertIn("contractTitle", result["needsConfirmation"])

    def test_expiry_before_effective_date_requires_confirmation(self):
        result = validate_extraction({
            "fields": {
                "effectiveDate": {"value": "2027-01-01", "confidence": 0.9},
                "expiryDate": {"value": "2026-01-01", "confidence": 0.9},
            }
        }, CONTRACT, empty_hints())

        self.assertIn("到期日期早于生效日期，请人工核对", result["warnings"])
        self.assertIn("ourSide", result["needsConfirmation"])

    def test_cited_model_value_wins_over_conflicting_rule_candidate(self):
        text = """勘察设计合同
乙方应提交金额为合同总价10%的履约保函。
本合同总价为人民币壹仟捌佰陆拾万元整（¥1860万元）。
"""
        hints = empty_hints()
        hints["amount"] = {
            "value": 10.0,
            "confidence": 0.84,
            "citations": [{"quote": "合同总价10", "startOffset": 20, "endOffset": 26}],
            "source": "RULE",
        }
        result = validate_extraction({
            "fields": {
                "amount": {
                    "value": 18600000,
                    "confidence": 0.95,
                    "citations": [{"quote": "本合同总价为人民币壹仟捌佰陆拾万元整（¥1860万元）"}],
                }
            }
        }, text, hints)

        self.assertEqual(18600000.0, result["fields"]["amount"]["value"])
        self.assertEqual("LLM", result["fields"]["amount"]["source"])

    def test_total_amount_ignores_earlier_guarantee_percentage(self):
        text = """勘察设计合同
甲方：华能安源发电有限责任公司
乙方：江西省电力设计院
乙方应提交金额为合同总价10%的履约保函。
本合同总价为人民币壹仟捌佰陆拾万元整（¥1860万元）。
"""

        hints = deterministic_hints(text, "勘察设计合同.pdf")

        self.assertEqual(18600000.0, hints["amount"]["value"])
        self.assertIn("1860万元", hints["amount"]["citations"][0]["quote"])
        self.assertEqual("CONTRACT_TOTAL", hints["amount"]["semanticType"])

    def test_amount_candidates_classify_non_total_money(self):
        text = """合同总价：人民币100万元
履约保证金为人民币10万元。
预付款人民币20万元。
逾期违约金人民币2万元。
服务单价为人民币500元/工日。
"""

        candidates = deterministic_hints(text, "服务合同.pdf")["amount"]["candidates"]
        semantic_types = {item["semanticType"] for item in candidates}

        self.assertTrue({
            "CONTRACT_TOTAL", "GUARANTEE", "PAYMENT_INSTALLMENT", "PENALTY", "UNIT_PRICE",
        }.issubset(semantic_types))

    def test_real_engineering_cover_and_payment_schedule(self):
        text = """惠,华能国际电力股份有限公司
_ _ HUANENG POWER INTERNATICNAUNC
合同编号: HSG-2013024-01AY
(HNAY-S] -201212-0101)
华能安源发电有眼责任公司
"上大压小" 2X660MW二次再热机组工程
勘察设计合同
甲方:华能安源发电有限责任公司
乙方:江西省电力设计院
9.合同价格与支付
9.1本合同总价款为人民币肆仟捌佰陆拾万元整(¥4860万元)。
9.2合同生效后，甲方支付合同总价10%作为预付款。
""" + "\n".join(f"核减设计费{i}万元。" for i in range(1, 60))

        hints = deterministic_hints(text, "安源电厂二次再热合同.pdf")

        self.assertEqual(
            '华能安源发电有限责任公司 "上大压小" 2X660MW二次再热机组工程 勘察设计合同',
            hints["contractTitle"]["value"],
        )
        self.assertNotIn("合同编号", hints["contractTitle"]["value"])
        self.assertNotIn("HUANENG", hints["contractTitle"]["value"])
        self.assertEqual(48600000.0, hints["amount"]["value"])
        self.assertTrue(any(
            item["semanticType"] == "PERCENTAGE" and "10" in item["rawValue"]
            for item in hints["amount"]["candidates"]
        ))
        self.assertLessEqual(len(hints["amount"]["candidates"]), 32)

    def test_valid_model_title_is_not_overridden_by_label_like_rule_hint(self):
        text = """合同编号：HSG-2013024-01AY
华能安源发电有限责任公司“上大压小”2X660MW二次再热机组工程勘察设计合同
"""
        hints = empty_hints()
        hints["contractTitle"] = {
            "value": "合同编号：HSG-2013024-01AY",
            "confidence": 0.82,
            "citations": [{"quote": "合同编号：HSG-2013024-01AY", "startOffset": 0, "endOffset": 24}],
            "source": "RULE",
        }
        title = "华能安源发电有限责任公司“上大压小”2X660MW二次再热机组工程勘察设计合同"

        result = validate_extraction({
            "fields": {
                "contractTitle": {
                    "value": title,
                    "confidence": 0.9,
                    "citations": [{"quote": title}],
                }
            }
        }, text, hints)

        self.assertEqual(title, result["fields"]["contractTitle"]["value"])
        self.assertEqual("LLM", result["fields"]["contractTitle"]["source"])

    def test_legal_party_roles_are_not_overridden_by_user_side_hints(self):
        text = "甲方：华能安源发电有限责任公司\n乙方：江西省电力设计院"
        hints = empty_hints()
        hints["partyA"] = {
            "value": "江西省电力设计院",
            "confidence": 0.95,
            "citations": [{"quote": "江西省电力设计院"}],
            "source": "PREPROCESSOR_USER_SIDE",
        }
        hints["partyB"] = {
            "value": "华能安源发电有限责任公司",
            "confidence": 0.95,
            "citations": [{"quote": "华能安源发电有限责任公司"}],
            "source": "PREPROCESSOR_USER_SIDE",
        }

        result = validate_extraction({
            "fields": {
                "partyA": {
                    "value": "华能安源发电有限责任公司",
                    "confidence": 0.95,
                    "citations": [{"quote": "甲方：华能安源发电有限责任公司"}],
                },
                "partyB": {
                    "value": "江西省电力设计院",
                    "confidence": 0.95,
                    "citations": [{"quote": "乙方：江西省电力设计院"}],
                },
            }
        }, text, hints)

        self.assertEqual("华能安源发电有限责任公司", result["fields"]["partyA"]["value"])
        self.assertEqual("江西省电力设计院", result["fields"]["partyB"]["value"])

    def test_preconfirmation_updates_only_workflow_status(self):
        updates = _preconfirmation_case_updates({
            "fields": {
                "contractTitle": {"value": "勘察设计合同", "confidence": 0.9},
                "partyA": {"value": "甲方公司", "confidence": 0.9},
                "partyB": {"value": "乙方公司", "confidence": 0.9},
                "amount": {"value": 18600000.0, "confidence": 0.95},
            }
        })

        self.assertEqual({"status": "INTAKE_CONFIRMING"}, updates)

    def test_deterministic_hints_support_suffix_currency_amount(self):
        text = "合同金额：10cny\n甲方：A\n乙方：B"

        hints = deterministic_hints(text, "sample.txt")

        self.assertEqual(10.0, hints["amount"]["value"])
        self.assertEqual("CNY", hints["currency"]["value"])

    def test_case_backfill_patch_maps_validated_fields(self):
        validated = {
            "fields": {
                "contractTitle": {"value": "技术服务合同", "confidence": 0.9},
                "contractType": {"value": "SERVICE_PROCUREMENT", "confidence": 0.9},
                "partyA": {"value": "星河科技有限公司", "confidence": 0.86},
                "partyB": {"value": "云桥信息技术有限公司", "confidence": 0.86},
                "amount": {"value": 125000.0, "confidence": 0.9},
                "currency": {"value": "CNY", "confidence": 0.9},
                "effectiveDate": {"value": "2026-08-01", "confidence": 0.9},
                "expiryDate": {"value": "2027-07-31", "confidence": 0.9},
                "department": {"value": "采购部", "confidence": 0.72},
            }
        }

        patch = _case_backfill_patch(validated)

        self.assertEqual("技术服务合同", patch["title"])
        self.assertEqual("SERVICE_PROCUREMENT", patch["contract_type"])
        self.assertEqual("星河科技有限公司", patch["our_entity"])
        self.assertEqual("云桥信息技术有限公司", patch["counterparty"])
        self.assertEqual(125000.0, patch["amount"])
        self.assertEqual("CNY", patch["currency"])
        self.assertEqual("2026-08-01", patch["effective_date"])
        self.assertEqual("2027-07-31", patch["expiry_date"])
        self.assertEqual("采购部", patch["department"])

    def test_case_backfill_patch_drops_invalid_expiry(self):
        patch = _case_backfill_patch({
            "fields": {
                "effectiveDate": {"value": "2027-01-01", "confidence": 0.9},
                "expiryDate": {"value": "2026-01-01", "confidence": 0.9},
            }
        })

        self.assertEqual("2027-01-01", patch["effective_date"])
        self.assertNotIn("expiry_date", patch)


if __name__ == "__main__":
    unittest.main()
