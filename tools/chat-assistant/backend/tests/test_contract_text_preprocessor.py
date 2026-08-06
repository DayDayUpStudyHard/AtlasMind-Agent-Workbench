import json
import unittest

from app.agent_runtime.contract_text_preprocessor import ContractTextPreprocessor


class _Message:
    def __init__(self, content: str):
        self.content = content


class _Choice:
    def __init__(self, content: str):
        self.message = _Message(content)


class _Response:
    def __init__(self, content: str):
        self.choices = [_Choice(content)]


class _FakeCompletions:
    def __init__(self, mode: str):
        self.mode = mode
        self.calls = 0

    def create(self, **kwargs):
        self.calls += 1
        if self.mode == "invalid-json":
            return _Response("{not valid json")
        payload = json.loads(kwargs["messages"][-1]["content"])
        cleaned = payload["rawText"].replace("草包商", "承包商")
        return _Response(json.dumps({
            "cleanedText": cleaned,
            "parties": [],
            "quality": {"overall": "GOOD", "garbledSections": []},
            "corrections": [],
        }, ensure_ascii=False))


class _FakeChat:
    def __init__(self, completions: _FakeCompletions):
        self.completions = completions


class _FakeClient:
    def __init__(self, completions: _FakeCompletions):
        self.chat = _FakeChat(completions)


class _FakeLLM:
    model = "fake-model"

    def __init__(self, mode: str):
        self.completions = _FakeCompletions(mode)
        self.analysis_client = _FakeClient(self.completions)

    def _call_llm_with_retry(self, fn, max_retries=3, backoff_base=2.0):
        return fn()


class ContractTextPreprocessorTest(unittest.TestCase):
    def test_falls_back_to_deterministic_text_when_llm_json_is_invalid(self):
        raw = (
            "第一条 合同范围\n\n"
            "中华人民共和国科学技术部印制\n\n"
            "乙方应在合同签订后10日内提交履约保证函。" * 6
        )

        result = ContractTextPreprocessor(_FakeLLM("invalid-json")).process(raw, "contract.pdf")

        self.assertFalse(result.llm_used)
        self.assertNotIn("中华人民共和国科学技术部印制", result.cleaned_text)
        self.assertIn("乙方应在合同签订后10日内", result.cleaned_text)
        self.assertGreater(len(result.corrections), 0)

    def test_cleans_long_text_in_chunks_without_flattening_paragraphs(self):
        paragraph = "第十四条 质量保证期。设计草包商应在验收后12个月内承担质量保证责任。"
        raw = "\n\n".join([paragraph] * 180)
        fake_llm = _FakeLLM("valid-json")

        result = ContractTextPreprocessor(fake_llm).process(raw, "contract.pdf")

        self.assertTrue(result.llm_used)
        self.assertGreater(fake_llm.completions.calls, 1)
        self.assertIn("承包商", result.cleaned_text)
        self.assertNotIn("草包商", result.cleaned_text)
        self.assertIn("\n\n", result.cleaned_text)


if __name__ == "__main__":
    unittest.main()
