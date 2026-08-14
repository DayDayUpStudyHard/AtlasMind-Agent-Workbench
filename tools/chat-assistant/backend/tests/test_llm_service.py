import unittest
from types import SimpleNamespace
from unittest.mock import patch

from openai import APIError

from app.services.llm_service import LLMService, _compact_timeline_candidate_for_llm


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


if __name__ == "__main__":
    unittest.main()
