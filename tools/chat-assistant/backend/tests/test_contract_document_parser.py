import unittest

from app.agent_runtime import contract_document_parser as parser
from app.agent_runtime.contract_document_parser import classify_clause, split_contract_text


class ContractDocumentParserTest(unittest.TestCase):
    def test_splits_and_classifies_numbered_chinese_clauses(self):
        clauses = split_contract_text(
            "第1条 服务范围：乙方提供咨询服务。\n"
            "第2条 付款方式：按季度支付，每季度5万元。\n"
            "第3条 违约责任：逾期每日支付违约金。"
        )

        self.assertEqual(3, len(clauses))
        self.assertEqual("DELIVERY", clauses[0]["clauseType"])
        self.assertEqual("PAYMENT", clauses[1]["clauseType"])
        self.assertEqual("LIABILITY", clauses[2]["clauseType"])

    def test_falls_back_to_paragraphs(self):
        clauses = split_contract_text("服务内容如下。\n\n双方应承担保密义务。")

        self.assertEqual(2, len(clauses))
        self.assertEqual("CONFIDENTIALITY", clauses[1]["clauseType"])

    def test_empty_text_has_no_clauses(self):
        self.assertEqual([], split_contract_text("  \n "))

    def test_data_protection_precedes_generic_confidentiality(self):
        self.assertEqual("DATA_PROTECTION", classify_clause("个人信息和数据删除义务"))

    def test_timeline_v2_splits_service_range_and_skips_signing_date(self):
        text = (
            "\u6280\u672f\u670d\u52a1\u6709\u6548\u671f\uff1a"
            "2025\u5e748\u670815\u65e5\u81f3 2026\u5e7412\u670831\u65e5\u3002"
            "\u7b7e\u8ba2\u65f6\u95f4\uff1a2025\u5e748\u67081\u65e5\u3002"
        )
        clause = {
            "id": 1,
            "clauseType": "DELIVERY",
            "clauseNumber": "2",
            "title": "\u6280\u672f\u670d\u52a1\u6709\u6548\u671f",
            "content": text,
        }

        nodes = parser._extract_clause_timeline_nodes_v2(clause, 2025, None, set())
        dates = sorted(node.get("date") for node in nodes if node.get("date"))
        types = {node.get("nodeType") for node in nodes}

        self.assertEqual(["2025-08-15", "2026-12-31"], dates)
        self.assertIn("SERVICE_START", types)
        self.assertIn("SERVICE_END", types)

    def test_timeline_v2_keeps_force_majeure_duration_condition(self):
        text = (
            "\u4e0d\u53ef\u6297\u529b\u6301\u7eed10\u65e5\u4ee5\u4e0a"
            "\u5e76\u5bfc\u81f4\u672c\u5408\u540c\u65e0\u6cd5\u7ee7\u7eed\u5c65\u884c\u7684\uff0c"
            "\u53cc\u65b9\u534f\u5546\u89e3\u9664\u5408\u540c\uff0c"
            "\u4e92\u4e0d\u627f\u62c5\u8fdd\u7ea6\u8d23\u4efb\u3002"
        )
        clause = {
            "id": 2,
            "clauseType": "DELIVERY",
            "clauseNumber": "9",
            "title": "\u4e0d\u53ef\u6297\u529b",
            "content": text,
        }

        nodes = parser._extract_clause_timeline_nodes_v2(clause, 2025, None, set())
        force_majeure = [node for node in nodes if "\u4e0d\u53ef\u6297\u529b" in (node.get("condition") or "")]

        self.assertTrue(force_majeure)
        self.assertTrue(any("\u4ee5\u4e0a" in (node.get("condition") or "") for node in force_majeure))
        self.assertTrue(any(node.get("nodeType") == "TERMINATION" for node in force_majeure))
        self.assertTrue(all(node["citation"]["fullQuote"] == text for node in force_majeure))


if __name__ == "__main__":
    unittest.main()
