"""RetrievalOrchestrator — the single retrieval entry for fixed graphs (PRD §11.2).

Design rules for Phase 2:

* One public interface: ``orchestrator.retrieve(snapshot, request)``.
* Channels run in parallel per query variant; one channel failing must be an
  observable warning, never a silent skip (ES unavailable → other channels
  keep their evidence and the bundle records the fallback).
* Contract / policy / historical evidence stay in separate pools and rerank
  separately (§12.4).
* RRF fusion happens ACROSS channels within the contract pool; ES-internal
  keyword/vector fusion stays inside ContractStore — no duplication here.
* Parent-clause expansion reads the snapshot, not the DB.
* First-round and targeted bundles merge by sourceId union — old evidence is
  never dropped by a later round.

The default adapters wrap ContractStore, so existing tool interfaces stay
intact; graphs switch over to this entry without changing the tools.
"""

from __future__ import annotations

import asyncio
import contextvars
import hashlib
import json
import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Awaitable, Protocol

from .models import EvidenceBundle, RetrievalRequest, default_retrieval_request

logger = logging.getLogger(__name__)


# ── provider pressure gate ────────────────────────────────────────────────
# 2026-08-14: the embedding/reranker provider degrades sharply under
# concurrent bursts (solo ~0.3s → 9–15s or read timeouts at ~6 concurrent).
# The orchestrator fans out up to ~24 calls per work unit, so a process-wide
# semaphore keeps provider pressure under the cliff while queueing the rest.
#
# Must be a *threading* semaphore, not asyncio: graph nodes call retrieve_sync
# from different threads, each with its own fresh event loop (see _run_async);
# an asyncio.Semaphore binds to the first loop that uses it and then rejects
# every later call from another loop ("bound to a different event loop").
_CHANNEL_FANOUT_LIMIT = 3
_fanout_semaphore: threading.Semaphore | None = None
_fanout_init_lock = threading.Lock()


def _fanout_gate() -> threading.Semaphore:
    global _fanout_semaphore
    with _fanout_init_lock:
        if _fanout_semaphore is None:
            _fanout_semaphore = threading.Semaphore(_CHANNEL_FANOUT_LIMIT)
        return _fanout_semaphore


async def _gated_retrieve(adapter: ChannelAdapter, case_id: int, query: str,
                          arguments: dict[str, Any]) -> ChannelResult:
    sem = _fanout_gate()
    # acquire off-loop: a blocking acquire would freeze the owning event loop
    # (and deadlock the holders, whose continuations run on that same loop).
    await asyncio.get_running_loop().run_in_executor(None, sem.acquire)
    try:
        return await adapter.retrieve(case_id, query, arguments)
    finally:
        sem.release()


# ─────────────────────────────── channel protocol ───────────────────────────


class ChannelResult(dict):
    """One channel's result for one query: hits + stats + warnings."""


class ChannelAdapter(Protocol):
    channel_key: str

    async def retrieve(self, case_id: int, query: str, arguments: dict[str, Any]) -> ChannelResult:
        ...


# ───────────────────────────── default adapters ─────────────────────────────


class ContractChannelAdapter:
    """ES keyword/vector + MySQL keyword + RRF + rerank + parent enrichment.

    All of that already lives inside ContractStore.search_contract_clause;
    this adapter is a thin boundary so tests can replace it with a fake.
    """

    channel_key = "contract"

    async def retrieve(self, case_id: int, query: str, arguments: dict[str, Any]) -> ChannelResult:
        from ..contract_store import ContractStore

        top_k = int(arguments.get("topK") or 8)
        hits = await ContractStore().search_contract_clause(case_id, {"query": query, "topK": top_k})
        return ChannelResult({"hits": hits or [], "stats": {}, "warnings": []})


class ClauseTypeChannelAdapter:
    """MySQL rule channel: clauses of exactly the required types (bounded)."""

    channel_key = "clause_type"

    async def retrieve(self, case_id: int, query: str, arguments: dict[str, Any]) -> ChannelResult:
        clause_types = [str(value).upper() for value in (arguments.get("clauseTypes") or [])]
        if not clause_types:
            return ChannelResult({"hits": [], "stats": {}, "warnings": []})
        from ..persistence import _conn, _normalize_value

        placeholders = ",".join(["%s"] * len(clause_types))
        with _conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"""SELECT id AS clauseId, document_id AS documentId,
                               clause_type AS clauseType, clause_number AS clauseNumber,
                               title, page_number AS page, LEFT(content, 1800) AS snippet
                        FROM contract_clause
                        WHERE case_id=%s AND clause_type IN ({placeholders})
                        ORDER BY id LIMIT 8""",
                    [case_id] + clause_types,
                )
                rows = [_normalize_value(row) for row in cur.fetchall()]
        for row in rows:
            row.setdefault("sourceType", "CONTRACT_CLAUSE")
        return ChannelResult({"hits": rows, "stats": {}, "warnings": []})


class PolicyChannelAdapter:
    """KB + standard-clause channel (search_policy)."""

    channel_key = "policy"

    async def retrieve(self, case_id: int, query: str, arguments: dict[str, Any]) -> ChannelResult:
        from ..contract_store import ContractStore

        limit = int(arguments.get("limit") or 8)
        clause_type = (arguments.get("clauseTypes") or [""])[0]
        hits = await ContractStore().search_policy(
            case_id, {"query": query, "clauseType": clause_type, "limit": limit}
        )
        for hit in hits or []:
            hit.setdefault("sourceType", "KB_DOCUMENT")
        return ChannelResult({"hits": hits or [], "stats": {}, "warnings": []})


class HistoricalChannelAdapter:
    """Historical review decisions channel."""

    channel_key = "historical"

    async def retrieve(self, case_id: int, query: str, arguments: dict[str, Any]) -> ChannelResult:
        from ..contract_store import ContractStore

        limit = int(arguments.get("limit") or 3)
        hits = await ContractStore().search_historical(case_id, {"query": query, "limit": limit})
        for hit in hits or []:
            hit.setdefault("sourceType", "HISTORICAL_FINDING")
        return ChannelResult({"hits": hits or [], "stats": {}, "warnings": []})


DEFAULT_ADAPTERS = (
    ContractChannelAdapter(),
    ClauseTypeChannelAdapter(),
    PolicyChannelAdapter(),
    HistoricalChannelAdapter(),
)

# Which pool each channel's hits land in.
_CHANNEL_POOL = {
    "contract": "contract_evidence",
    "clause_type": "contract_evidence",
    "policy": "policy_evidence",
    "historical": "historical_evidence",
}

# Counter-evidence query templates (PRD §12.5) — exceptions, provisos,
# limitations, waivers and reverse expressions of the base intents.
_COUNTER_TEMPLATES = (
    "{query} 除外 但书 例外 前提 限制 豁免 以约定为准",
    "与 {query} 冲突的条款 特殊约定 专用条件",
)


def _counter_variants(queries: list[str]) -> list[str]:
    return [
        template.format(query=query)
        for query in queries
        for template in _COUNTER_TEMPLATES
    ]


def _request_hash(request: RetrievalRequest) -> str:
    payload = {
        "case_id": request.get("case_id"),
        "snapshot_hash": request.get("snapshot_hash"),
        "work_unit_id": request.get("work_unit_id"),
        "query_variants": sorted(request.get("query_variants") or []),
        "clause_types": sorted(request.get("clause_types") or []),
        "final_limit": request.get("final_limit"),
    }
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()[:24]


def _rrf_fuse(ranked_lists: list[list[dict]], k: int = 60) -> list[dict]:
    """Reciprocal-rank fusion across channel rankings, keyed by sourceId.

    Stable: ties fall back to the earlier channel's order. Items keep their
    original dicts (with per-channel metadata intact); only the pooled order
    is fused.
    """
    scores: dict[str, float] = {}
    order: dict[str, dict] = {}
    for hits in ranked_lists:
        for rank, hit in enumerate(hits):
            source_id = str(hit.get("sourceId") or "")
            if not source_id:
                continue
            if source_id not in order:
                order[source_id] = hit
            scores[source_id] = scores.get(source_id, 0.0) + 1.0 / (k + rank + 1)
    return [order[source_id] for source_id, _ in sorted(
        scores.items(), key=lambda pair: pair[1], reverse=True
    )]


def _dedupe_pool(hits: list[dict], limit: int | None = None) -> list[dict]:
    result: list[dict] = []
    seen: set[str] = set()
    for hit in hits:
        source_id = str(hit.get("sourceId") or "")
        if not source_id or source_id in seen:
            continue
        seen.add(source_id)
        result.append(hit)
        if limit and len(result) >= limit:
            break
    return result


def _parent_key(clause_number: str) -> str | None:
    """Longest proper prefix of a dotted clause number ('3.2.1' → '3.2')."""
    text = str(clause_number or "").strip()
    if "." not in text:
        return None
    return text.rsplit(".", 1)[0].strip()


def expand_parent_clauses(
    hits: list[dict],
    snapshot: dict[str, Any],
    clauses: list[dict] | None = None,
) -> list[dict]:
    """Attach ``parentClause`` metadata from the snapshot (PRD §11.2 step 11).

    Uses the snapshot's clause catalog (no content) for identity, and the
    full clause list when the caller provides it, for a text snippet. Never
    queries the DB — the snapshot is the single source of clause facts.
    """
    catalog = {str(item.get("clauseNumber") or ""): item for item in
               (snapshot.get("clause_catalog") or snapshot.get("clauseCatalog") or [])}
    full_text = {str(item.get("clauseNumber") or ""): item for item in (clauses or [])}
    for hit in hits:
        parent_number = _parent_key(hit.get("clauseNumber"))
        if not parent_number or hit.get("parentClause"):
            continue
        catalog_entry = catalog.get(parent_number)
        parent: dict[str, Any] = {
            "clauseNumber": parent_number,
            "clauseId": catalog_entry.get("clauseId") if catalog_entry else None,
            "title": catalog_entry.get("title") if catalog_entry else None,
            "charCount": catalog_entry.get("charCount") if catalog_entry else None,
            "snippet": "",
        }
        text_entry = full_text.get(parent_number)
        if text_entry:
            parent_text = str(text_entry.get("clauseText") or text_entry.get("content") or "")
            parent["snippet"] = parent_text[:600]
        hit["parentClause"] = parent
    return hits


def merge_bundles(primary: EvidenceBundle, targeted: EvidenceBundle) -> EvidenceBundle:
    """Union of a first-round bundle and a targeted (回补) bundle.

    The primary bundle's evidence is never dropped: targeted hits append
    after it, deduplicated per pool by sourceId. Stats keep both rounds.
    """
    pools = (
        "contract_evidence", "policy_evidence",
        "historical_evidence", "counter_evidence",
    )
    merged_pools: dict[str, list[dict]] = {}
    for pool in pools:
        base = list(primary.get(pool) or [])
        extra = [hit for hit in (targeted.get(pool) or [])
                 if str(hit.get("sourceId") or "") not in {
                     str(item.get("sourceId") or "") for item in base
                 }]
        merged_pools[pool] = base + extra
    return EvidenceBundle(
        work_unit_id=primary.get("work_unit_id") or targeted.get("work_unit_id"),
        request_hash=primary.get("request_hash") or "",
        contract_evidence=merged_pools["contract_evidence"],
        policy_evidence=merged_pools["policy_evidence"],
        historical_evidence=merged_pools["historical_evidence"],
        counter_evidence=merged_pools["counter_evidence"],
        retrieval_stats={
            "rounds": [
                primary.get("retrieval_stats") or {},
                targeted.get("retrieval_stats") or {},
            ],
            "merged": {
                pool: len(merged_pools[pool]) for pool in pools
            },
        },
        warnings=list(primary.get("warnings") or []) + list(targeted.get("warnings") or []),
    )


def _normalize_hit(item: dict[str, Any]) -> dict[str, Any]:
    """Shared evidence normalization at the channel boundary.

    ContractStore hits do not always carry ``sourceId``; the orchestrator
    needs it for RRF fusion and pool dedupe, so it happens once here, for
    every graph. Single implementation since PRD §14-4 —
    ``graph/nodes/retrieval.py`` re-imports this instead of keeping a copy.
    """
    value = dict(item)
    source_type = str(value.get("sourceType") or "").upper()
    if source_type == "CONTRACT_CLAUSE" or value.get("clauseId"):
        source_type = "CONTRACT_CLAUSE"
        raw_id = value.get("clauseId") or value.get("id") or value.get("sourceId")
    elif source_type in {"CONTRACT_STANDARD_CLAUSE", "STANDARD_CLAUSE"}:
        source_type = "STANDARD_CLAUSE"
        raw_id = value.get("id") or value.get("sourceId")
    elif source_type in {"KB_CHUNK", "KB_DOCUMENT"} or value.get("chunkId"):
        source_type = "KB_CHUNK" if value.get("chunkId") else "KB_DOCUMENT"
        raw_id = value.get("chunkId") or value.get("sourceId") or value.get("documentId")
    elif source_type == "HISTORICAL_FINDING":
        raw_id = value.get("id") or value.get("sourceId")
    else:
        source_type = source_type or "UNKNOWN"
        raw_id = value.get("id") or value.get("sourceId")
    prefixed = str(raw_id or "")
    if prefixed and ":" not in prefixed:
        prefixed = f"{source_type}:{prefixed}"
    value["sourceType"] = source_type
    value["sourceId"] = prefixed
    value["clauseText"] = str(
        value.get("clauseText")
        or value.get("content")
        or value.get("fullText")
        or value.get("snippet")
        or ""
    )[:12000]
    value["snippet"] = str(
        value.get("snippet") or value.get("content") or value.get("description") or ""
    )[:1800]
    if value.get("pageNumber") is not None and value.get("page") is None:
        value["page"] = value.get("pageNumber")
    return value


# ─────────────────────────────── orchestrator ───────────────────────────────


class RetrievalOrchestrator:
    """One retrieval entry for fixed graphs (PRD §11.2)."""

    def __init__(
        self,
        adapters: tuple[ChannelAdapter, ...] | None = None,
        reranker: Any | None = None,
    ) -> None:
        self._adapters = tuple(adapters) if adapters is not None else DEFAULT_ADAPTERS
        self._reranker = reranker

    def _get_reranker(self):
        if self._reranker is not None:
            return self._reranker
        from ..reranker import get_reranker

        return get_reranker()

    # ── public interface ──

    def retrieve_sync(
        self,
        snapshot: dict[str, Any],
        request: RetrievalRequest | None = None,
        *,
        clauses: list[dict] | None = None,
    ) -> EvidenceBundle:
        """Synchronous entry for LangGraph nodes."""
        return _run_async(self.retrieve(snapshot, request, clauses=clauses))

    async def retrieve(
        self,
        snapshot: dict[str, Any],
        request: RetrievalRequest | None = None,
        *,
        clauses: list[dict] | None = None,
    ) -> EvidenceBundle:
        request = dict(request or {})
        case_id = int(request.get("case_id") or snapshot.get("case_id") or 0)
        request = {
            **default_retrieval_request(
                case_id,
                snapshot,
                str(request.get("work_unit_id") or "unnamed"),
                list(request.get("query_variants") or []),
                clause_types=request.get("clause_types") or [],
                source_quotas=request.get("source_quotas") or {},
                final_limit=int(request.get("final_limit") or 8),
                require_counter_evidence=bool(request.get("require_counter_evidence")),
            ),
            **request,
        }
        queries = [str(value).strip() for value in request["query_variants"] if str(value).strip()]
        if not queries:
            return empty_bundle(request, ["no query variants provided"])

        started = time.monotonic()
        reranker = self._get_reranker()

        # Per-round input counts + per-channel hit counts feed the
        # observation log (acceptance: input / hit count / post-fusion count).
        channel_hits: dict[str, int] = {}
        channel_errors: list[dict] = []
        pools: dict[str, list[dict]] = {
            "contract_evidence": [], "policy_evidence": [],
            "historical_evidence": [], "counter_evidence": [],
        }
        channel_rankings: dict[str, list[dict]] = {}
        pool_rankings: dict[str, list[dict]] = {
            "contract_evidence": [], "policy_evidence": [],
            "historical_evidence": [], "counter_evidence": [],
        }

        counter_queries = _counter_variants(queries) if request.get("require_counter_evidence") else []

        # One parallel fan-out per (query, channel) — no cross-channel barrier.
        # Calls are gated through _gated_retrieve to keep provider pressure
        # under the concurrency cliff (see _CHANNEL_FANOUT_LIMIT).
        calls: list[tuple[str, str, Awaitable[ChannelResult]]] = []
        for query in queries:
            for adapter in self._adapters:
                calls.append((adapter.channel_key, query, _gated_retrieve(
                    adapter, case_id, query, {
                        "topK": request["source_quotas"].get("contract"),
                        "limit": request["source_quotas"].get(
                            adapter.channel_key,
                            request["source_quotas"].get("contract"),
                        ),
                        "clauseTypes": request["clause_types"],
                    },
                )))
        for query in counter_queries:
            for adapter in self._adapters:
                if adapter.channel_key not in ("contract",):
                    continue
                calls.append(("counter", query, _gated_retrieve(
                    adapter, case_id, query, {"topK": request["source_quotas"].get("contract")},
                )))

        results = await asyncio.gather(
            *[call[2] for call in calls], return_exceptions=True,
        )
        for (channel_key, query, _), result in zip(calls, results):
            if isinstance(result, BaseException):
                warning = {
                    "channel": channel_key,
                    "query": query[:120],
                    "error": f"{type(result).__name__}: {result}",
                    "fallback": "channel skipped — other channels keep their evidence",
                }
                channel_errors.append(warning)
                logger.warning("Retrieval channel %s failed: %s", channel_key, warning["error"])
                continue
            hits = list(result.get("hits") or [])
            channel_hits[channel_key] = channel_hits.get(channel_key, 0) + len(hits)
            pool_key = "counter_evidence" if channel_key == "counter" else _CHANNEL_POOL[channel_key]
            normalized = [_normalize_hit(hit) for hit in hits]
            pool_rankings[pool_key].extend(normalized)
            channel_rankings.setdefault(channel_key, []).extend(normalized)

        # Contract pool: RRF fusion across channels (contract + clause_type).
        contract_channels = [
            hits for key, hits in channel_rankings.items()
            if key in ("contract", "clause_type")
        ]
        pools["contract_evidence"] = _rrf_fuse(contract_channels) if contract_channels else []
        pools["policy_evidence"] = _dedupe_pool(pool_rankings["policy_evidence"])
        pools["historical_evidence"] = _dedupe_pool(pool_rankings["historical_evidence"])
        pools["counter_evidence"] = _dedupe_pool(pool_rankings["counter_evidence"])

        fusion_counts = {key: len(value) for key, value in pools.items()}

        # Pooled rerank — pools never compete for one TopK (§12.4).
        primary_query = queries[0]
        final_limit = int(request["final_limit"])
        contract_pool = reranker.rerank_contract_clauses(
            primary_query, pools["contract_evidence"], final_limit
        )
        policy_pool = reranker.rerank_policy_items(
            primary_query, pools["policy_evidence"],
            min(final_limit, int(request["source_quotas"].get("policy") or 8)),
        )
        pools["contract_evidence"] = list(contract_pool)
        pools["policy_evidence"] = list(policy_pool)
        pools["historical_evidence"] = pools["historical_evidence"][
            : int(request["source_quotas"].get("historical") or 3)
        ]
        pools["counter_evidence"] = pools["counter_evidence"][:final_limit]

        if request.get("expand_parent_clause"):
            expand_parent_clauses(pools["contract_evidence"], snapshot, clauses=clauses)
            expand_parent_clauses(pools["counter_evidence"], snapshot, clauses=clauses)

        try:
            from ..reranker import get_rerank_observation
            rerank_observation = get_rerank_observation()
        except Exception:  # pragma: no cover - reranker module always importable
            rerank_observation = {}

        elapsed_ms = int((time.monotonic() - started) * 1000)
        stats = {
            "workUnitId": request["work_unit_id"],
            "snapshotHash": request["snapshot_hash"],
            "round": 1,
            "queryVariantCount": len(queries),
            "counterQueryCount": len(counter_queries),
            "channelHitCounts": channel_hits,
            "postFusionCounts": fusion_counts,
            "finalCounts": {key: len(value) for key, value in pools.items()},
            "rerank": rerank_observation,
            "elapsedMs": elapsed_ms,
            "channels": sorted({adapter.channel_key for adapter in self._adapters}),
        }
        warnings = list(channel_errors)
        if request.get("require_counter_evidence") and not counter_queries:
            warnings.append({"channel": "counter", "warning": "counter evidence requested but no base queries"})

        return EvidenceBundle(
            work_unit_id=request["work_unit_id"],
            request_hash=_request_hash(request),
            contract_evidence=pools["contract_evidence"],
            policy_evidence=pools["policy_evidence"],
            historical_evidence=pools["historical_evidence"],
            counter_evidence=pools["counter_evidence"],
            retrieval_stats=stats,
            warnings=warnings,
        )


def empty_bundle(request: RetrievalRequest, warnings: list[str]) -> EvidenceBundle:
    return EvidenceBundle(
        work_unit_id=request.get("work_unit_id") or "unnamed",
        request_hash=_request_hash(request),
        contract_evidence=[],
        policy_evidence=[],
        historical_evidence=[],
        counter_evidence=[],
        retrieval_stats={"queryVariantCount": 0, "channelHitCounts": {}, "postFusionCounts": {}},
        warnings=[{"channel": "orchestrator", "warning": warning} for warning in warnings],
    )


def flatten_bundle(bundle: EvidenceBundle) -> list[dict]:
    """Flatten all pools into one legacy-shaped evidence list.

    Downstream v1 nodes (draft_domain_findings, compose_report, element
    analysis) read a flat ``domain_results`` / ``evidence_by_pack`` list; this
    keeps those interfaces intact while the bundle stays the canonical form.
    """
    return (
        list(bundle.get("contract_evidence") or [])
        + list(bundle.get("policy_evidence") or [])
        + list(bundle.get("historical_evidence") or [])
        + list(bundle.get("counter_evidence") or [])
    )


def _run_async(awaitable: Awaitable[Any]) -> Any:
    """Run an async call from a synchronous LangGraph node. Single
    implementation — ``graph/nodes/retrieval.py`` re-imports this one."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(awaitable)
    context = contextvars.copy_context()
    with ThreadPoolExecutor(max_workers=1) as executor:
        return executor.submit(context.run, asyncio.run, awaitable).result()


_orchestrator: RetrievalOrchestrator | None = None


def get_orchestrator() -> RetrievalOrchestrator:
    """Module-level shared orchestrator (one retrieval entry for all graphs)."""
    global _orchestrator
    if _orchestrator is None:
        _orchestrator = RetrievalOrchestrator()
    return _orchestrator
