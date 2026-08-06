import unittest

from app.agent_runtime.contract_intake_extractor import (
    FIELD_KEYS,
    _case_backfill_patch,
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

    def test_verified_rule_candidate_wins_over_conflicting_model_value(self):
        result = validate_extraction({
            "fields": {
                "amount": {
                    "value": 999999,
                    "confidence": 0.99,
                    "citations": [{"quote": "合同金额：人民币 12.5 万元"}],
                }
            }
        }, CONTRACT)

        self.assertEqual(125000.0, result["fields"]["amount"]["value"])
        self.assertEqual("RULE_VERIFIED", result["fields"]["amount"]["source"])

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
