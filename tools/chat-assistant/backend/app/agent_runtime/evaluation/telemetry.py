"""Operational telemetry for reproducible evaluation runs.

Quality metrics remain in the evaluator. This module only normalizes observed
runtime facts and derives latency, token, cost, and execution-stack summaries.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import math
from typing import Any


_STACK_FIELDS = (
    "runtimeEngine",
    "graphName",
    "graphVersion",
    "model",
    "promptVersion",
    "retrievalVersion",
    "rerankVersion",
    "scorerVersion",
)


def stage_telemetry(rows: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Normalize database rows for the stages executed by an evaluation case."""
    stages: list[dict[str, Any]] = []
    for row in rows:
        stage = {
            "runId": int(row["id"]),
            "status": str(row.get("status") or ""),
            "wallLatencyMs": _optional_int(row.get("wall_latency_ms")),
            "nodeLatencyMs": _int(row.get("node_latency_ms")),
            "nodeExecutionCount": _int(row.get("node_execution_count")),
            "tokenInput": _int(row.get("token_input")),
            "tokenOutput": _int(row.get("token_output")),
            "tokenObserved": _int(row.get("token_observed_count")) > 0,
            "executionStack": {
                "runtimeEngine": str(row.get("runtime_engine") or ""),
                "graphName": str(row.get("graph_name") or ""),
                "graphVersion": str(row.get("graph_version") or ""),
                "model": str(row.get("model") or ""),
                "promptVersion": str(row.get("prompt_version") or ""),
                "retrievalVersion": str(row.get("retrieval_version") or ""),
                "rerankVersion": str(row.get("rerank_version") or ""),
                "scorerVersion": str(row.get("scorer_version") or ""),
            },
        }
        stages.append(stage)
    return stages


def case_telemetry(case_id: int, stages: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    """Summarize one case without blending it into its semantic score."""
    normalized = [dict(stage) for stage in stages]
    wall_values = [int(stage["wallLatencyMs"]) for stage in normalized if stage.get("wallLatencyMs") is not None]
    token_observed = any(bool(stage.get("tokenObserved")) for stage in normalized)
    return {
        "caseId": case_id,
        "stageRunCount": len(normalized),
        "latencyStatus": "AVAILABLE" if wall_values else "UNAVAILABLE",
        "wallLatencyMs": sum(wall_values) if wall_values else None,
        "nodeLatencyTotalMs": sum(_int(stage.get("nodeLatencyMs")) for stage in normalized),
        "tokenStatus": "AVAILABLE" if token_observed else "UNAVAILABLE",
        "tokenInput": sum(_int(stage.get("tokenInput")) for stage in normalized),
        "tokenOutput": sum(_int(stage.get("tokenOutput")) for stage in normalized),
        "executionStack": _execution_stack(normalized),
        "stages": normalized,
    }


def aggregate_telemetry(
    cases: Iterable[Mapping[str, Any]], pricing: Mapping[str, Any] | None = None
) -> dict[str, Any]:
    """Aggregate operational telemetry and optionally calculate configured cost.

    ``pricing`` must be explicit. A global price uses ``inputPerMillion`` and
    ``outputPerMillion``; model-specific prices can be placed in
    ``modelPricing`` with the same fields and an optional ``default`` entry.
    """
    normalized_cases = [dict(case) for case in cases]
    stages = [
        stage
        for case in normalized_cases
        for stage in (case.get("stages") or [])
        if isinstance(stage, Mapping)
    ]
    wall_values = [int(case["wallLatencyMs"]) for case in normalized_cases if case.get("wallLatencyMs") is not None]
    token_observed = any(str(case.get("tokenStatus") or "") == "AVAILABLE" for case in normalized_cases)
    token_input = sum(_int(case.get("tokenInput")) for case in normalized_cases)
    token_output = sum(_int(case.get("tokenOutput")) for case in normalized_cases)
    cost = _estimate_cost(stages, pricing, token_observed)
    return {
        "latencyStatus": "AVAILABLE" if wall_values else "UNAVAILABLE",
        "latencyTotalMs": sum(wall_values) if wall_values else None,
        "latencyP50Ms": _percentile(wall_values, 0.50),
        "latencyP95Ms": _percentile(wall_values, 0.95),
        "latencyObservedCaseCount": len(wall_values),
        "nodeLatencyTotalMs": sum(_int(case.get("nodeLatencyTotalMs")) for case in normalized_cases),
        "tokenStatus": "AVAILABLE" if token_observed else "UNAVAILABLE",
        "tokenInputTotal": token_input,
        "tokenOutputTotal": token_output,
        "tokenObservedCaseCount": sum(
            1 for case in normalized_cases if str(case.get("tokenStatus") or "") == "AVAILABLE"
        ),
        "stageRunCount": len(stages),
        "executionStack": _execution_stack(stages),
        **cost,
    }


def _estimate_cost(
    stages: list[Mapping[str, Any]], pricing: Mapping[str, Any] | None, token_observed: bool
) -> dict[str, Any]:
    if not isinstance(pricing, Mapping):
        return _unavailable_cost("PRICING_NOT_CONFIGURED")
    if not token_observed:
        return _unavailable_cost("TOKEN_TELEMETRY_UNAVAILABLE", pricing.get("currency"))

    model_pricing = pricing.get("modelPricing")
    default_price = _price_pair(pricing)
    if model_pricing is not None and not isinstance(model_pricing, Mapping):
        return _unavailable_cost("INVALID_PRICING_CONFIG", pricing.get("currency"))
    total = Decimal("0")
    for stage in stages:
        if not stage.get("tokenObserved"):
            continue
        configured = default_price
        if isinstance(model_pricing, Mapping):
            model = str((stage.get("executionStack") or {}).get("model") or "")
            configured = _price_pair(model_pricing.get(model) or model_pricing.get("default"))
        if configured is None:
            return _unavailable_cost("PRICING_NOT_CONFIGURED_FOR_MODEL", pricing.get("currency"))
        input_price, output_price = configured
        total += Decimal(_int(stage.get("tokenInput"))) * input_price / Decimal("1000000")
        total += Decimal(_int(stage.get("tokenOutput"))) * output_price / Decimal("1000000")
    return {
        "estimatedCost": float(total.quantize(Decimal("0.00000001"), rounding=ROUND_HALF_UP)),
        "costCurrency": str(pricing.get("currency") or "USD")[:8],
        "costStatus": "AVAILABLE",
        "costReason": None,
    }


def _price_pair(value: Any) -> tuple[Decimal, Decimal] | None:
    if not isinstance(value, Mapping):
        return None
    try:
        input_price = Decimal(str(value["inputPerMillion"]))
        output_price = Decimal(str(value["outputPerMillion"]))
    except (KeyError, InvalidOperation, ValueError):
        return None
    if input_price < 0 or output_price < 0:
        return None
    return input_price, output_price


def _unavailable_cost(reason: str, currency: Any = None) -> dict[str, Any]:
    return {
        "estimatedCost": None,
        "costCurrency": str(currency or "")[:8] or None,
        "costStatus": "UNAVAILABLE",
        "costReason": reason,
    }


def _execution_stack(stages: Iterable[Mapping[str, Any]]) -> dict[str, list[str]]:
    stack = {field: set() for field in _STACK_FIELDS}
    for stage in stages:
        values = stage.get("executionStack") or {}
        if not isinstance(values, Mapping):
            continue
        for field in _STACK_FIELDS:
            value = str(values.get(field) or "").strip()
            if value:
                stack[field].add(value)
    return {field: sorted(values) for field, values in stack.items()}


def _percentile(values: list[int], percentile: float) -> int | None:
    if not values:
        return None
    ordered = sorted(values)
    return ordered[math.ceil(percentile * len(ordered)) - 1]


def _optional_int(value: Any) -> int | None:
    return None if value is None else _int(value)


def _int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0
