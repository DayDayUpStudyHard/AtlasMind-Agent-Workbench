"""Fake adapters for pure unit tests of the harness.

No DB, no ES, no settings access — scripted hits and failure modes only. The
orchestrator depends solely on the ChannelAdapter protocol and an injectable
reranker, so tests assemble a full pipeline from these fakes.

FakeLLM / FakePersistence extend the same idea to the graph runtime
(PRD Phase 4 task 6): scripted completions and scripted run rows, so
lifecycle contract tests never touch the LLM service or MySQL.
"""

from __future__ import annotations

import json
from typing import Any

from .retrieval import ChannelResult


def fake_clause(clause_id: int, *, number: str, title: str = "", content: str = "条款内容",
                clause_type: str = "PAYMENT", document_id: int = 1) -> dict[str, Any]:
    return {
        "sourceType": "CONTRACT_CLAUSE",
        "sourceId": f"CONTRACT_CLAUSE:{clause_id}",
        "clauseId": clause_id,
        "documentId": document_id,
        "clauseNumber": number,
        "title": title or f"条款{clause_id}",
        "clauseType": clause_type,
        "content": content,
        "clauseText": content,
        "snippet": content[:220],
        "page": 1,
        "score": 0.0,
    }


def fake_policy_item(item_id: int, *, title: str = "标准条款", content: str = "制度内容") -> dict[str, Any]:
    return {
        "sourceType": "KB_DOCUMENT",
        "sourceId": f"KB_DOCUMENT:{item_id}",
        "id": item_id,
        "title": title,
        "content": content,
        "snippet": content[:220],
        "score": 0.0,
    }


class FakeChannelAdapter:
    """Scripted channel: hits per query (optional per-query keying), or a
    raised exception to simulate ES / KB unavailability."""

    def __init__(
        self,
        channel_key: str,
        hits: list[dict[str, Any]] | None = None,
        *,
        hits_by_query: dict[str, list[dict[str, Any]]] | None = None,
        raise_exc: BaseException | None = None,
        hit_recorder: list[tuple[str, str]] | None = None,
    ) -> None:
        self.channel_key = channel_key
        self._hits = list(hits or [])
        self._hits_by_query = dict(hits_by_query or {})
        self._raise_exc = raise_exc
        self._recorder = hit_recorder
        self.call_count = 0

    async def retrieve(self, case_id: int, query: str, arguments: dict[str, Any]) -> ChannelResult:
        self.call_count += 1
        if self._recorder is not None:
            self._recorder.append((self.channel_key, query))
        if self._raise_exc is not None:
            raise self._raise_exc
        if query in self._hits_by_query:
            return ChannelResult({"hits": list(self._hits_by_query[query]), "stats": {}, "warnings": []})
        return ChannelResult({"hits": list(self._hits), "stats": {}, "warnings": []})


class FakeReranker:
    """Pass-through reranker with scripted orderings and call recording.

    ``orderings`` maps a query to the desired hit order (list of sourceIds).
    When None, hits pass through unchanged with ``rerankerMethod`` set to
    ``FAKE_PASSTHROUGH`` — modelling rerank-off degradation for tests.
    """

    def __init__(
        self,
        orderings: dict[str, list[str]] | None = None,
        *,
        method: str = "FAKE_PASSTHROUGH",
        recorder: list[tuple[str, str, int]] | None = None,
    ) -> None:
        self._orderings = dict(orderings or {})
        self._method = method
        self._recorder = recorder

    def rerank_contract_clauses(self, query: str, hits: list[dict], top_k: int) -> list[dict]:
        return self._rerank("contract", query, hits, top_k)

    def rerank_policy_items(self, query: str, hits: list[dict], top_k: int) -> list[dict]:
        return self._rerank("policy", query, hits, top_k)

    def _rerank(self, pool: str, query: str, hits: list[dict], top_k: int) -> list[dict]:
        if self._recorder is not None:
            self._recorder.append((pool, query, len(hits)))
        order = self._orderings.get(query)
        if order is not None:
            by_id = {str(hit.get("sourceId") or ""): hit for hit in hits}
            hits = [by_id[source_id] for source_id in order if source_id in by_id]
        result = [dict(hit) for hit in hits[:top_k]]
        for position, hit in enumerate(result, 1):
            hit["rerankPosition"] = position
            hit["rerankerMethod"] = self._method
        return result


def fake_snapshot(
    case_id: int = 1,
    *,
    document_id: int = 1,
    document_version: int = 1,
    clauses: list[dict[str, Any]] | None = None,
    confirmed_intake: dict[str, Any] | None = None,
    extraction_elements: list[dict[str, Any]] | None = None,
    snapshot_hash: str = "snap-0001",
) -> dict[str, Any]:
    """Minimal canonical EvidenceSnapshot shape (Phase 1 field names)."""
    clause_list = clauses if clauses is not None else [
        fake_clause(1, number="3.1", title="付款条款"),
        fake_clause(2, number="3.2", title="发票条款"),
        fake_clause(3, number="3.2.1", title="发票类型"),
    ]
    catalog = [
        {
            "clauseId": item.get("clauseId"),
            "documentId": item.get("documentId"),
            "clauseNumber": item.get("clauseNumber"),
            "title": item.get("title"),
            "clauseType": item.get("clauseType"),
            "pageNumber": item.get("page"),
            "charCount": len(str(item.get("clauseText") or item.get("content") or "")),
        }
        for item in clause_list
    ]
    return {
        "snapshot_hash": snapshot_hash,
        "case_id": case_id,
        "document_id": document_id,
        "document_version": document_version,
        "content_hash": "h-0001",
        "main_document_parser": {"parseStatus": "READY", "parseQuality": "HIGH"},
        "quality_diagnostics": {"status": "HIGH"},
        "confirmed_intake_fields": confirmed_intake or {},
        "latest_confirmed_extraction_snapshot": {"elements": extraction_elements or []},
        "clause_catalog": catalog,
        "clauses": clause_list,
        "knowledge_scope": {"standardClauseVersion": 3},
        "missing_inputs": [],
        # back-compat aliases
        "currentDocument": {"id": document_id, "version": document_version},
        "confirmedIntake": confirmed_intake or {},
    }


class FakeLLM:
    """Scripted completion model: response per exact prompt key, one shared
    fallback otherwise, with call recording.

    ``responses`` maps the full prompt string to the scripted reply.
    ``complete_json`` parses the reply as JSON (fallback must be valid JSON
    when used that way). Callers model degradation by setting a fallback that
    a downstream deterministic path can consume.
    """

    def __init__(
        self,
        responses: dict[str, str] | None = None,
        *,
        fallback: str = "{}",
        recorder: list[str] | None = None,
    ) -> None:
        self._responses = dict(responses or {})
        self._fallback = fallback
        self._recorder = recorder
        self.calls: list[str] = []

    def complete(self, prompt: str) -> str:
        self.calls.append(prompt)
        if self._recorder is not None:
            self._recorder.append(prompt)
        return self._responses.get(prompt, self._fallback)

    def complete_json(self, prompt: str) -> dict[str, Any]:
        value = json.loads(self.complete(prompt))
        if not isinstance(value, dict):
            raise ValueError(f"FakeLLM scripted reply for {prompt!r} is not a JSON object")
        return value


class FakePersistence:
    """Scripted run-store for runtime lifecycle tests.

    Implements the subset GraphAdapter / RunRecovery touch: ``get_run``,
    ``update_run``, ``heartbeat``, ``set_runtime_metadata``. Statuses come
    from a scripted mapping (per run_id) with a shared default; every write
    is recorded so contract tests can assert *what* was persisted.
    """

    def __init__(
        self,
        statuses: dict[int, str] | None = None,
        *,
        default_status: str = "RUNNING",
        raise_on: str | None = None,
    ) -> None:
        self._statuses = dict(statuses or {})
        self._default_status = default_status
        self._raise_on = raise_on  # method name to fail, e.g. "heartbeat"
        self.runs: dict[int, dict[str, Any]] = {}
        self.heartbeats: list[int] = []
        self.metadata: list[tuple[int, dict[str, Any]]] = []
        self.updates: list[tuple[int, dict[str, Any]]] = []

    def _maybe_raise(self, method: str) -> None:
        if self._raise_on == method:
            raise RuntimeError(f"FakePersistence {method} failure")

    async def get_run(self, run_id: int) -> dict[str, Any] | None:
        self._maybe_raise("get_run")
        status = self._statuses.get(run_id, self._default_status)
        self.runs.setdefault(run_id, {})["status"] = status
        return {"id": run_id, "status": status}

    async def update_run(self, run_id: int, **kwargs: Any) -> None:
        self._maybe_raise("update_run")
        self.updates.append((run_id, kwargs))
        self.runs.setdefault(run_id, {}).update(kwargs)

    async def heartbeat(self, run_id: int) -> None:
        self._maybe_raise("heartbeat")
        self.heartbeats.append(run_id)

    async def set_runtime_metadata(
        self, run_id: int, *, runtime_engine: str = "", graph_name: str = "",
        graph_version: str = "", model: str = "", prompt_version: str = "",
    ) -> None:
        self._maybe_raise("set_runtime_metadata")
        self.metadata.append((run_id, {
            "runtime_engine": runtime_engine,
            "graph_name": graph_name,
            "graph_version": graph_version,
            "model": model,
            "prompt_version": prompt_version,
        }))
