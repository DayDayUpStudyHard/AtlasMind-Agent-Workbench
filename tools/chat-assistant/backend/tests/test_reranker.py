import io
import json
import asyncio
from urllib.error import HTTPError


def _hits():
    return [
        {"title": "付款", "content": "验收后付款", "score": 0.8},
        {"title": "保密", "content": "双方承担保密义务", "score": 0.7},
        {"title": "终止", "content": "提前三十日通知", "score": 0.6},
    ]


def test_reranker_uses_provider_native_endpoint(monkeypatch):
    from app.agent_runtime import reranker as module

    monkeypatch.setattr(module.settings, "reranker_api_key", "test-key")
    monkeypatch.setattr(module.settings, "reranker_base_url", "https://provider.example/v1")
    monkeypatch.setattr(module.settings, "reranker_model", "Qwen/Qwen3-Reranker-8B")
    captured = {}

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            return None

        def read(self):
            return json.dumps({
                "results": [
                    {"index": 2, "relevance_score": 0.99},
                    {"index": 0, "relevance_score": 0.8},
                    {"index": 1, "relevance_score": 0.2},
                ]
            }).encode()

    def fake_urlopen(request, timeout):
        captured["url"] = request.full_url
        captured["payload"] = json.loads(request.data.decode())
        captured["authorization"] = request.headers["Authorization"]
        return Response()

    monkeypatch.setattr(module.urllib.request, "urlopen", fake_urlopen)
    module.reset_rerank_observation()
    result = module.LLMReranker().rerank_contract_clauses("终止条件", _hits(), 3)

    assert captured["url"] == "https://provider.example/v1/rerank"
    assert captured["payload"]["model"] == "Qwen/Qwen3-Reranker-8B"
    assert captured["payload"]["query"] == "终止条件"
    assert len(captured["payload"]["documents"]) == 3
    assert captured["authorization"] == "Bearer test-key"
    assert [item["title"] for item in result] == ["终止", "付款", "保密"]
    assert module.get_rerank_observation()["actualMethod"] == "MODEL_RERANK"


def test_reranker_records_keyword_fallback_on_provider_error(monkeypatch):
    from app.agent_runtime import reranker as module

    monkeypatch.setattr(module.settings, "reranker_api_key", "test-key")
    monkeypatch.setattr(module.settings, "reranker_base_url", "https://provider.example/v1")
    monkeypatch.setattr(module.settings, "reranker_model", "missing-model")

    def fail_urlopen(request, timeout):
        raise HTTPError(request.full_url, 400, "bad request", {}, io.BytesIO(b'{"message":"Model does not exist"}'))

    monkeypatch.setattr(module.urllib.request, "urlopen", fail_urlopen)
    module.reset_rerank_observation()
    result = module.LLMReranker().rerank_contract_clauses("付款", _hits(), 3)

    assert result
    assert module.get_rerank_observation()["actualMethod"] == "KEYWORD_FALLBACK"


def test_rerank_context_is_visible_inside_retrieval_worker_thread():
    from app.agent_runtime.graph.nodes.retrieval import run_async
    from app.agent_runtime.reranker import _rerank_disabled

    async def read_setting():
        return _rerank_disabled.get()

    async def run_inside_event_loop():
        token = _rerank_disabled.set(True)
        try:
            return run_async(read_setting())
        finally:
            _rerank_disabled.reset(token)

    assert asyncio.run(run_inside_event_loop()) is True
