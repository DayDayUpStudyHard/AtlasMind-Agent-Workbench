import unittest
from types import SimpleNamespace

from app.services.llm_service import LLMService


def response(content="", reasoning_content=""):
    return SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(
                    content=content,
                    reasoning_content=reasoning_content,
                )
            )
        ]
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


if __name__ == "__main__":
    unittest.main()
