import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app.agent_runtime import contract_document_parser as parser
from app.agent_runtime.contract_document_parser import (
    _clean_rule_condition,
    _rule_action_from_quote,
    classify_clause,
    split_contract_text,
)


class ContractDocumentParserTest(unittest.TestCase):
    def test_docx_parse_returns_diagnostics(self):
        document = {
            "case_id": 41,
            "content_text": "",
            "file_path": "/upload/contracts/contract.docx",
            "file_name": "contract.docx",
        }
        blocks = [SimpleNamespace(text="合同正文", source_page=1)]

        with patch.object(parser, "_resolve_local_file", return_value=Path("contract.docx")), \
             patch.object(parser, "parse_docx_blocks", return_value=blocks), \
             patch.object(parser, "_update_job"), \
             patch.object(parser, "_append_job_trace"):
            result = parser._parse_document_content(MagicMock(), 41, 41, document)

        self.assertEqual("python-docx", result["parser"])
        self.assertEqual("python-docx", result["diagnostics"]["provider"])
        self.assertIn("quality", result["diagnostics"])

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

    def test_contract_preamble_is_not_classified_from_incidental_payment_words(self):
        self.assertEqual(
            "OTHER",
            classify_clause(
                "甲方委托乙方提供技术服务，并支付相应服务报酬。",
                title="合同前言",
            ),
        )

    def test_clause_heading_outweighs_incidental_body_keywords(self):
        clauses = split_contract_text(
            "第八条 报酬及其支付方式\n"
            "甲方在收到合规发票后十个工作日内支付服务费，乙方应对付款资料保密。\n"
            "第九条 技术服务进度\n"
            "乙方分三个阶段推进工作，阶段成果涉及的知识产权另按本合同约定处理。"
        )

        self.assertEqual("PAYMENT", clauses[0]["clauseType"])
        self.assertEqual("DELIVERY", clauses[1]["clauseType"])

    def test_result_ownership_heading_is_classified_as_ip(self):
        self.assertEqual(
            "IP",
            classify_clause(
                "本项目形成的技术成果由双方按约定使用。",
                title="技术成果的归属",
            ),
        )
        self.assertEqual(
            "IP",
            classify_clause(
                "在合同有效期内形成的新的技术成果归甲方所有。",
                title="甲方利用乙方成果形成的新技术成果",
            ),
        )

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

    def test_corrupted_timeline_candidate_is_held_for_recognition_review(self):
        text = (
            "11.11 逾期超过 :\\0 天以上时，乙方有权暂停履行下阶段工作，"
            "并书面通知 1rfl方。"
        )
        clause = {
            "id": 3,
            "clauseType": "PAYMENT",
            "clauseNumber": "11.11",
            "title": "付款逾期",
            "content": text,
        }

        nodes = parser._extract_clause_timeline_nodes_v2(clause, 2026, None, set())

        self.assertTrue(nodes)
        self.assertTrue(all(node["status"] == "NEEDS_REVIEW" for node in nodes))
        self.assertTrue(all(node["date"] or node["condition"] for node in nodes))
        self.assertTrue(all("待重新识别" not in node["label"] for node in nodes))
        self.assertTrue(all(node["citation"]["textQuality"]["requiresReview"] for node in nodes))

    def test_low_quality_timeline_candidate_is_still_sent_to_llm(self):
        clause = {
            "id": 31,
            "clauseType": "DELIVERY",
            "clauseNumber": "3",
            "title": "交付期限",
            "content": "乙方应在合同签订后10日内提交实施方案。",
        }
        node = {
            "clauseId": 31,
            "nodeType": "DELIVERY",
            "label": "合同签订后10日内",
            "date": None,
            "condition": "合同签订后10日内",
            "responsibleParty": "COUNTERPARTY",
            "businessMeaning": "提交实施方案",
            "confidence": 0.35,
            "status": "NEEDS_RECOGNITION",
            "source": "RULE_CANDIDATE",
            "citation": {"quote": clause["content"], "clauseNumber": "3", "title": "交付期限"},
        }
        captured = {}

        def enrich(candidates):
            captured["candidates"] = candidates
            return {"nodes": []}

        with patch.object(parser.LLMService, "enrich_contract_timeline", side_effect=enrich):
            parser._enrich_timeline_nodes([node], [clause])

        self.assertEqual(1, len(captured["candidates"]))
        self.assertEqual(clause["content"], captured["candidates"][0]["clauseText"])

    def test_timeline_llm_receives_the_complete_clause(self):
        clause_text = (
            "7.2.3 竣工图设计文件：两台机组通过168小时试运后45天内完成编制，"
            "竣工图设计文件应满足机组达标投产的要求。"
            + "本条补充上下文。" * 80
        )
        clause = {
            "id": 4,
            "clauseType": "DELIVERY",
            "clauseNumber": "7.2.3",
            "title": "竣工图设计文件",
            "content": clause_text,
        }
        nodes = parser._extract_clause_timeline_nodes_v2(clause, 2026, None, set())
        captured = {}

        def enrich(candidates):
            captured["candidates"] = candidates
            return {"nodes": []}

        with patch.object(parser.LLMService, "enrich_contract_timeline", side_effect=enrich):
            parser._enrich_timeline_nodes(nodes, [clause])

        self.assertEqual(clause_text, captured["candidates"][0]["clauseText"])
        self.assertIn("两台机组通过168小时试运后45天内", captured["candidates"][0]["matchedText"])

    def test_final_timeline_does_not_publish_unreviewed_rule_candidates(self):
        clause = {
            "id": 41,
            "clauseType": "DELIVERY",
            "clauseNumber": "7.2.3",
            "title": "竣工图设计文件",
            "content": "两台机组通过168小时试运后45天内完成编制。",
        }
        nodes = parser._extract_clause_timeline_nodes_v2(clause, 2026, None, set())

        with patch.object(parser.LLMService, "enrich_contract_timeline", return_value={"nodes": []}):
            final_nodes, result = parser._enrich_timeline_nodes(nodes, [clause], strict=True)

        self.assertEqual([], final_nodes)
        self.assertEqual("LLM_ENRICHED", result["status"])
        self.assertEqual(len(nodes), result["dropped"])

    def test_final_timeline_retries_only_missing_candidates_and_keeps_reviewed_nodes(self):
        clause = {
            "id": 42,
            "clauseType": "DELIVERY",
            "clauseNumber": "7.2.3",
            "title": "竣工图设计文件",
            "content": "两台机组通过168小时试运后45天内完成竣工图编制；收到书面通知后10日内提交资料。",
        }
        nodes = [
            {
                "clauseId": 42,
                "nodeType": "DELIVERY",
                "label": "完成竣工图编制",
                "date": None,
                "condition": "两台机组通过168小时试运后45天内",
                "responsibleParty": "COUNTERPARTY",
                "businessMeaning": "完成竣工图编制",
                "confidence": 0.84,
                "status": "EXTRACTED",
                "source": "RULE_CANDIDATE",
                "citation": {"quote": clause["content"], "clauseNumber": "7.2.3", "title": "竣工图设计文件"},
            },
            {
                "clauseId": 42,
                "nodeType": "NOTICE",
                "label": "提交资料",
                "date": None,
                "condition": "收到书面通知后10日内",
                "responsibleParty": "COUNTERPARTY",
                "businessMeaning": "提交资料",
                "confidence": 0.84,
                "status": "EXTRACTED",
                "source": "RULE_CANDIDATE",
                "citation": {"quote": clause["content"], "clauseNumber": "7.2.3", "title": "竣工图设计文件"},
            },
        ]
        calls = []

        def enrich(candidates):
            calls.append([candidate["candidateId"] for candidate in candidates])
            if len(calls) == 1:
                return {
                    "nodes": [{
                        "candidateId": "timeline-1",
                        "keep": True,
                        "label": "完成竣工图编制",
                        "businessMeaning": "乙方应在两台机组通过168小时试运后45天内完成竣工图编制。",
                        "responsibleParty": "COUNTERPARTY",
                        "eventType": "DELIVERY",
                        "confidence": 0.9,
                    }],
                }
            return {
                "nodes": [{
                    "candidateId": "timeline-2",
                    "keep": True,
                    "label": "提交资料",
                    "businessMeaning": "收到书面通知后10日内提交合同约定资料。",
                    "responsibleParty": "COUNTERPARTY",
                    "eventType": "NOTICE",
                    "confidence": 0.9,
                }],
            }

        with patch.object(parser.LLMService, "enrich_contract_timeline", side_effect=enrich):
            final_nodes, result = parser._enrich_timeline_nodes(nodes, [clause], strict=True)

        self.assertEqual([["timeline-1", "timeline-2"], ["timeline-2"]], calls)
        self.assertEqual(2, len(final_nodes))
        self.assertEqual(2, result["returned"])
        self.assertEqual(0, result["missing"])
        self.assertEqual(1, result["retryCount"])
        self.assertTrue(all(node["source"] == "LLM_ENRICHED" for node in final_nodes))

    def test_final_timeline_allows_partial_llm_review_without_publishing_missing_candidates(self):
        clause = {
            "id": 43,
            "clauseType": "DELIVERY",
            "clauseNumber": "8",
            "title": "交付期限",
            "content": "收到通知后10日内提交资料；验收通过后5日内提交归档文件。",
        }
        nodes = [
            {
                "clauseId": 43,
                "nodeType": "DELIVERY",
                "label": "提交资料",
                "date": None,
                "condition": "收到通知后10日内",
                "responsibleParty": "COUNTERPARTY",
                "businessMeaning": "提交资料",
                "confidence": 0.84,
                "status": "EXTRACTED",
                "source": "RULE_CANDIDATE",
                "citation": {"quote": clause["content"], "clauseNumber": "8", "title": "交付期限"},
            },
            {
                "clauseId": 43,
                "nodeType": "DELIVERY",
                "label": "提交归档文件",
                "date": None,
                "condition": "验收通过后5日内",
                "responsibleParty": "COUNTERPARTY",
                "businessMeaning": "提交归档文件",
                "confidence": 0.84,
                "status": "EXTRACTED",
                "source": "RULE_CANDIDATE",
                "citation": {"quote": clause["content"], "clauseNumber": "8", "title": "交付期限"},
            },
        ]

        def enrich(candidates):
            return {
                "nodes": [{
                    "candidateId": "timeline-1",
                    "keep": True,
                    "label": "提交资料",
                    "businessMeaning": "收到书面通知后10日内提交资料。",
                    "responsibleParty": "COUNTERPARTY",
                    "eventType": "DELIVERY",
                    "confidence": 0.9,
                }],
            }

        with patch.object(parser.LLMService, "enrich_contract_timeline", side_effect=enrich):
            final_nodes, result = parser._enrich_timeline_nodes(nodes, [clause], strict=True)

        self.assertEqual(1, len(final_nodes))
        self.assertEqual("timeline-1", final_nodes[0]["candidateId"])
        self.assertEqual(1, result["missing"])
        self.assertEqual(2, result["retryCount"])
        self.assertEqual("LLM_ENRICHED", result["status"])

    def test_rule_fallback_extracts_action_without_exposing_match_prefix(self):
        quote = (
            "7.2.3 竣工图设计文件：两台机组通过168小时试运后45天内完成编制，"
            "竣工图设计文件应满足机组达标投产的要求。"
        )
        raw_condition = "计文件:两台机组通过168小时试运后45天内"

        self.assertEqual(
            "两台机组通过168小时试运后45天内",
            _clean_rule_condition(raw_condition, quote),
        )
        self.assertEqual(
            "完成编制，竣工图设计文件应满足机组达标投产的要求",
            _rule_action_from_quote(quote, raw_condition),
        )


    def test_extracts_compound_contract_end_condition(self):
        clause = {
            "id": 5,
            "documentId": 8,
            "clauseNumber": "16.4",
            "title": "合同终止",
            "content": "工程移交生产且所有设计费全部付清后，本合同正式结束并失效。",
        }

        conditions = parser._extract_rule_lifecycle_conditions([clause])

        self.assertEqual(1, len(conditions))
        self.assertEqual("CONDITIONAL", conditions[0]["endMode"])
        self.assertEqual("ALL", conditions[0]["logic"])
        self.assertEqual(2, len(conditions[0]["conditions"]))
        self.assertEqual(clause["content"], conditions[0]["citation"]["fullQuote"])

    def test_sends_compressed_contract_end_clause_as_provisional_candidate(self):
        clause = {
            "id": 6,
            "documentId": 9,
            "clauseNumber": "18",
            "title": "履行完毕",
            "content": "工程移交生产且所有设计费全部付清，方可结束合同。",
        }

        candidates = parser._extract_rule_lifecycle_conditions([clause])

        self.assertEqual(1, len(candidates))
        self.assertEqual([], candidates[0]["conditions"])
        self.assertIn("完整条款", candidates[0]["summary"])


if __name__ == "__main__":
    unittest.main()
