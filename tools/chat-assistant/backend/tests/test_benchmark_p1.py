"""P1 operational telemetry and report contracts."""

from app.agent_runtime.evaluation.cli import compare_snapshots
from app.agent_runtime.evaluation.telemetry import aggregate_telemetry, case_telemetry, stage_telemetry


def _stage(run_id: int, latency: int, token_input: int, token_output: int, model: str = "model-a"):
    return {
        "id": run_id,
        "status": "COMPLETED",
        "wall_latency_ms": latency,
        "node_latency_ms": latency,
        "node_execution_count": 2,
        "token_input": token_input,
        "token_output": token_output,
        "token_observed_count": 1 if token_input or token_output else 0,
        "runtime_engine": "langgraph",
        "graph_name": "contract_review",
        "graph_version": "v1",
        "model": model,
        "prompt_version": "prompt-v3",
        "retrieval_version": "retrieval-v2",
        "rerank_version": "rerank-v1",
        "scorer_version": "eval-scorers-v2",
    }


def test_telemetry_aggregates_percentiles_tokens_and_explicit_cost():
    stages = stage_telemetry([_stage(1, 100, 1000, 500), _stage(2, 200, 2000, 1000)])
    cases = [case_telemetry(11, stages[:1]), case_telemetry(12, stages[1:])]

    result = aggregate_telemetry(
        cases,
        {"currency": "USD", "inputPerMillion": 1, "outputPerMillion": 2},
    )

    assert result["latencyP50Ms"] == 100
    assert result["latencyP95Ms"] == 200
    assert result["tokenInputTotal"] == 3000
    assert result["tokenOutputTotal"] == 1500
    assert result["estimatedCost"] == 0.006
    assert result["costStatus"] == "AVAILABLE"
    assert result["executionStack"]["graphName"] == ["contract_review"]


def test_telemetry_does_not_claim_cost_when_tokens_or_pricing_are_missing():
    no_tokens = case_telemetry(11, stage_telemetry([_stage(1, 100, 0, 0)]))
    missing_price = aggregate_telemetry([no_tokens], {})
    assert missing_price["costStatus"] == "UNAVAILABLE"
    assert missing_price["estimatedCost"] is None
    assert missing_price["costReason"] == "TOKEN_TELEMETRY_UNAVAILABLE"

    no_pricing = aggregate_telemetry([case_telemetry(11, stage_telemetry([_stage(1, 100, 1, 1)]))])
    assert no_pricing["costStatus"] == "UNAVAILABLE"
    assert no_pricing["costReason"] == "PRICING_NOT_CONFIGURED"


def test_compare_reports_operational_deltas_separately_from_quality_metrics():
    left = {
        "runId": 1,
        "datasetHash": "same",
        "scorerVersion": "same",
        "summary": {
            "highRiskRecall": 0.8,
            "operations": {"latencyP95Ms": 200, "tokenInputTotal": 1000, "costStatus": "AVAILABLE"},
        },
    }
    right = {
        "runId": 2,
        "datasetHash": "same",
        "scorerVersion": "same",
        "summary": {
            "highRiskRecall": 0.9,
            "operations": {"latencyP95Ms": 150, "tokenInputTotal": 1200, "costStatus": "AVAILABLE"},
        },
    }

    result = compare_snapshots(left, right)
    assert result["metrics"]["highRiskRecall"]["delta"] == 0.1
    assert result["operations"]["latencyP95Ms"]["delta"] == -50
    assert result["operations"]["tokenInputTotal"]["delta"] == 200


def test_embedding_service_retries_transient_provider_failure(monkeypatch):
    import app.services.embedding_service as module

    class Settings:
        embedding_api_key = "key"
        embedding_base_url = "https://embedding.test/v1"
        embedding_timeout_seconds = 1
        embedding_model = "embed-v1"
        embedding_dim = 2

    calls = {"count": 0}

    class Client:
        class embeddings:
            @staticmethod
            def create(**kwargs):
                calls["count"] += 1
                if calls["count"] == 1:
                    raise TimeoutError("transient")
                return type("Response", (), {"data": [type("Item", (), {"embedding": [0.1, 0.2]})()]})()

    monkeypatch.setattr(module, "settings", Settings)
    monkeypatch.setattr(module, "OpenAI", lambda **kwargs: Client())
    service = module.EmbeddingService()

    assert service.embed("query") == [0.1, 0.2]
    assert calls["count"] == 2
