import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from openai import APIError

from app.services.llm_service import (
    LLMService,
    _compact_timeline_candidate_for_llm,
    _merge_rule_findings,
)


def response(content="", reasoning_content="", usage=None):
    return SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(
                    content=content,
                    reasoning_content=reasoning_content,
                )
            )
        ],
        usage=usage,
    )


class LlmServiceStructuredResponseTest(unittest.TestCase):
    def test_rule_finding_merge_recognizes_policy_citation_rule_key(self):
        artifact = {
            "findings": [{
                "title": "责任上限待明确",
                "policyCitation": {"ruleKey": "PROC-LIAB-001"},
            }],
        }
        rule_findings = [{
            "ruleKey": "PROC-LIAB-001",
            "ruleTitle": "责任上限合理性",
            "title": "责任上限合理性",
            "clauseType": "LIABILITY",
            "severity": "HIGH",
        }]

        merged = _merge_rule_findings(artifact, rule_findings)

        self.assertEqual(1, len(merged["findings"]))
        self.assertEqual("责任上限待明确", merged["findings"][0]["title"])

    def test_recovers_json_when_reasoning_model_leaves_visible_content_empty(self):
        service = LLMService()
        parsed = service._parse_structured_response(
            response(
                reasoning_content=(
                    "分析过程略。最终输出："
                    '{"fields":{"contractTitle":{"value":"示例合同","confidence":1.0,"citations":[]}}}'
                )
            ),
            required_key="fields",
        )

        self.assertEqual("示例合同", parsed["fields"]["contractTitle"]["value"])

    def test_contract_metadata_retries_without_response_format_after_empty_content(self):
        service = LLMService()
        responses = [
            response(),
            response(
                '{"fields":{"contractTitle":{"value":"示例合同","confidence":1.0,"citations":[]}}}'
            ),
        ]
        call_count = 0

        def fake_call(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            return responses.pop(0)

        service._call_llm_with_retry = fake_call
        result = service.extract_contract_metadata(
            "debug.txt",
            "示例合同正文",
            {},
        )

        self.assertEqual(2, call_count)
        self.assertEqual("示例合同", result["fields"]["contractTitle"]["value"])

    def test_contract_review_keeps_perspective_diverse_evidence_and_rule_findings(self):
        service = LLMService()
        captured = {}

        def fake_create(**kwargs):
            captured["kwargs"] = kwargs
            return response(json.dumps({
                "title": "审查报告",
                "summary": "需要复核责任上限。",
                "riskStatus": "MEDIUM_RISK",
                "riskScore": 80,
                "analysisMode": "FULL",
                "findings": [],
                "actionProposals": [],
            }, ensure_ascii=False))

        service.analysis_client = SimpleNamespace(
            chat=SimpleNamespace(completions=SimpleNamespace(create=fake_create))
        )
        citations = [
            {
                "id": index,
                "sourceType": "CONTRACT_CLAUSE",
                "clauseType": clause_type,
                "title": f"{clause_type}-{index}",
                "content": "合同条款原文",
            }
            for index, clause_type in enumerate(
                ["PAYMENT"] * 8 + ["LIABILITY", "ACCEPTANCE", "TERMINATION", "IP"],
                start=1,
            )
        ] + [{
            "id": 3,
            "sourceType": "CONTRACT_STANDARD_CLAUSE",
            "clauseType": "ACCEPTANCE",
            "title": "标准验收条款",
            "content": "15个工作日内按量化指标验收。",
        }]
        rule_finding = {
            "ruleId": 10,
            "ruleKey": "PROC-LIAB-001",
            "ruleTitle": "责任上限合理性",
            "title": "责任上限合理性",
            "clauseType": "LIABILITY",
            "severity": "HIGH",
            "detail": "未能确认 liabilityCapPct",
            "description": "合同应明确责任上限",
            "contractCitation": {
                "clause": "违约责任",
                "snippet": "乙方每逾期一天支付违约金。",
            },
            "contractCitationIds": ["CONTRACT_CLAUSE:111"],
        }

        artifact = service.contract_review(
            {
                "caseKey": "CTR-1",
                "title": "技术服务合同",
                "ourEntity": "中国矿业大学",
                "counterparty": "某矿业公司",
                "ourSide": "B",
                "contractType": "SERVICE_PROCUREMENT",
            },
            [rule_finding],
            citations,
            {"riskScore": 80, "riskStatus": "MEDIUM_RISK"},
        )

        payload = json.loads(captured["kwargs"]["messages"][1]["content"])
        self.assertEqual("B", payload["case"]["ourSide"])
        self.assertEqual("中国矿业大学", payload["case"]["ourEntity"])
        self.assertEqual("某矿业公司", payload["case"]["partyA"])
        self.assertEqual("中国矿业大学", payload["case"]["partyB"])
        sent_types = {item.get("clauseType") for item in payload["citations"]}
        sent_sources = {item.get("sourceType") for item in payload["citations"]}
        self.assertTrue({"PAYMENT", "LIABILITY", "ACCEPTANCE", "TERMINATION", "IP"} <= sent_types)
        self.assertIn("CONTRACT_STANDARD_CLAUSE", sent_sources)
        self.assertEqual("PROC-LIAB-001", artifact["findings"][0]["ruleKey"])


    def test_structured_completion_recovers_reasoning_only_json(self):
        service = LLMService()
        service._call_llm_with_retry = lambda *args, **kwargs: response(
            reasoning_content=(
                "Reasoning omitted. Final JSON: "
                '{"elements":[{"elementKey":"contract_title","rawValue":"example contract"}]}'
            )
        )

        result = service._structured_completion(
            "Return contract elements as JSON.",
            {"elementPack": {"elementKeys": ["contract_title"]}},
        )

        self.assertEqual("example contract", result["elements"][0]["rawValue"])

    def test_structured_completion_disables_deepseek_thinking_for_json_tasks(self):
        service = LLMService()
        calls = []

        def fake_call(fn, *args, **kwargs):
            calls.append(fn.__defaults__[0])
            return response('{"elements":[]}')

        service._call_llm_with_retry = fake_call
        service._structured_completion(
            "Return JSON.",
            {"elementPack": {"elementKeys": []}},
            required_key="elements",
        )

        if service._uses_deepseek_reasoning_model():
            self.assertEqual({"thinking": {"type": "disabled"}}, calls[0]["extra_body"])

    def test_contract_risk_domain_uses_bounded_tokens_and_one_retry(self):
        service = LLMService()
        captured = {}
        service._prompt = lambda *args, **kwargs: ("Return findings.", 0.0)

        def fake_completion(*args, **kwargs):
            captured.update(kwargs)
            return {"findings": []}

        service._structured_completion = fake_completion
        result = service.analyze_contract_risk_domain(
            {"title": "case"},
            {"domainKey": "payment"},
            [],
            [],
        )

        self.assertEqual([], result["findings"])
        self.assertEqual(4096, captured["max_tokens"])
        self.assertEqual(1, captured["max_retries"])
        self.assertFalse(captured["allow_unstructured_fallback"])

    def test_structured_completion_can_skip_duplicate_unstructured_fallback(self):
        service = LLMService()
        calls = {"count": 0}

        def fake_call(fn, *args, **kwargs):
            calls["count"] += 1
            return response('{"wrong": []}')

        service._call_llm_with_retry = fake_call
        with self.assertRaises(ValueError):
            service._structured_completion(
                "Return JSON.", {"x": 1}, required_key="findings",
                allow_unstructured_fallback=False,
            )
        self.assertEqual(1, calls["count"])

    def test_call_llm_with_retry_meters_attempts_and_cumulative_tokens(self):
        """§7.2: retried API attempts are real calls — the ledger must count
        them and sum tokens across responses, not keep the last one."""
        service = LLMService()
        attempts = {"count": 0}

        def fake_fn():
            attempts["count"] += 1
            if attempts["count"] < 3:
                raise APIError("flaky", request=None, body=None)
            return response(
                content='{"elements":[]}',
                usage=SimpleNamespace(total_tokens=80, prompt_tokens=50, completion_tokens=30),
            )

        usage_out = {}
        with patch("app.services.llm_service.time.sleep"):
            service._call_llm_with_retry(
                fake_fn, max_retries=3, backoff_base=2.0, usage_out=usage_out,
            )

        self.assertEqual(3, attempts["count"])
        self.assertEqual(
            {"calls": 3, "tokens": 80, "promptTokens": 50, "completionTokens": 30},
            usage_out,
        )

    def test_structured_completion_meters_fallback_phase_cumulatively(self):
        """§7.2: the structured→unstructured fallback is a second real call —
        usage_out must count both phases and sum their tokens."""
        service = LLMService()
        responses = [
            response("this is not json"),
            response(
                '{"elements":[]}',
                usage=SimpleNamespace(total_tokens=50, prompt_tokens=30, completion_tokens=20),
            ),
        ]

        def fake_create(**kwargs):
            return responses.pop(0)

        service.analysis_client = SimpleNamespace(
            chat=SimpleNamespace(completions=SimpleNamespace(create=fake_create))
        )

        usage_out = {}
        result = service._structured_completion(
            "Return JSON.",
            {"elementPack": {"elementKeys": []}},
            required_key="elements",
            usage_out=usage_out,
        )

        self.assertEqual([], result["elements"])
        # one structured attempt + one unstructured fallback attempt
        self.assertEqual(
            {"calls": 2, "tokens": 50, "promptTokens": 30, "completionTokens": 20},
            usage_out,
        )

    def test_compacts_long_timeline_clause_around_quote(self):
        clause = "前文" * 1200 + "收到发票后10日内付款" + "后文" * 1200
        candidate = {
            "candidateId": "timeline-1",
            "quote": "收到发票后10日内付款",
            "clauseText": clause,
        }

        compacted = _compact_timeline_candidate_for_llm(candidate, max_clause_chars=1200)

        self.assertLess(len(compacted["clauseText"]), len(clause))
        self.assertIn("收到发票后10日内付款", compacted["clauseText"])
        self.assertTrue(compacted["clauseTextWasTruncated"])
        self.assertEqual(len(clause), compacted["originalClauseTextLength"])

    def test_complete_timeline_candidate_never_truncates(self):
        clause = "前文" * 1200 + "收到发票后10日内付款" + "后文" * 1200
        from app.services.llm_service import _complete_timeline_candidate_for_llm

        prepared = _complete_timeline_candidate_for_llm({
            "candidateId": "timeline-1",
            "quote": "收到发票后10日内付款",
            "clauseText": clause,
        })

        self.assertEqual(clause, prepared["clauseText"])
        self.assertTrue(prepared["clauseTextComplete"])
        self.assertEqual(len(clause), prepared["clauseTextLength"])

    def test_enrich_contract_timeline_sends_complete_clause_text(self):
        """PRD Phase 6, task 6: the LLM judges on the complete parent clause —
        the legacy 4500-char compaction must not be applied on this path."""
        import json

        service = LLMService()
        long_clause = (
            "7.2.3 竣工图设计文件：两台机组通过168小时试运后45天内完成编制。"
            + "本条补充上下文。" * 800
        )
        self.assertGreater(len(long_clause), 4500)
        captured = {}

        def fake_call(fn, *args, **kwargs):
            captured["kwargs"] = fn.__defaults__[0]
            return response('{"nodes":[]}')

        service._call_llm_with_retry = fake_call
        client = SimpleNamespace()
        client.with_options = lambda **kw: client
        client.chat = SimpleNamespace(completions=SimpleNamespace(create=None))
        service.analysis_client = client

        result = service.enrich_contract_timeline([{
            "candidateId": "timeline-1",
            "date": None,
            "condition": "两台机组通过168小时试运后45天内",
            "quote": "两台机组通过168小时试运后45天内完成编制",
            "clauseText": long_clause,
        }])

        self.assertEqual([], result["nodes"])
        payload = json.loads(captured["kwargs"]["messages"][1]["content"])
        sent = payload["candidates"][0]["clauseText"]
        self.assertEqual(long_clause, sent)
        self.assertNotIn("...", sent)
        self.assertTrue(payload["candidates"][0]["clauseTextComplete"])


if __name__ == "__main__":
    unittest.main()
