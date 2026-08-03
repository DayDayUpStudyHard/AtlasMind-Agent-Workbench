"""Chat, knowledge-base ingest, and retrieval debug routes."""
from __future__ import annotations

import asyncio
import json
import logging
import os
import secrets
import time
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Header, HTTPException
from fastapi.responses import StreamingResponse
from openai import APIConnectionError, APIError, AuthenticationError

from app.config import settings
from app.models.schemas import (
    ChatRequest,
    KbIngestRequest,
    KbQaRequest,
    KbReindexRequest,
    SuggestionResponse,
)
from app.services.embedding_service import EmbeddingService
from app.services.es_service import ESService
from app.services.kb_service import KbService
from app.services.llm_service import LLMService

logger = logging.getLogger(__name__)

router = APIRouter()
internal_router = APIRouter()
kb_router = APIRouter()

_es_service: ESService | None = None
_llm_service: LLMService | None = None
_embedding_service: EmbeddingService | None = None
_kb_service: KbService | None = None

# ── Agent Runtime singletons ────────────────────────────────────────
_agent_dispatcher = None   # RunDispatcher (project mode)
_agent_recovery_task: asyncio.Task | None = None
_agent_worker = None       # AgentRunWorker
_agent_worker_task: asyncio.Task | None = None
_active_runs: dict[str, asyncio.Task] = {}  # requestId → Task (idempotency)

# Contract Agent runtime singletons
_contract_dispatcher = None  # RunDispatcher (contract mode)
_contract_initialized = False


def _check_internal_token(token: str | None) -> None:
    expected = settings.internal_token
    if expected and (not token or not secrets.compare_digest(token, expected)):
        raise HTTPException(status_code=401, detail="Invalid internal token")


def get_es() -> ESService:
    global _es_service
    if _es_service is None:
        _es_service = ESService()
    return _es_service


def get_llm() -> LLMService:
    global _llm_service
    if _llm_service is None:
        _llm_service = LLMService()
    return _llm_service


def get_embedding() -> EmbeddingService:
    global _embedding_service
    if _embedding_service is None:
        _embedding_service = EmbeddingService()
    return _embedding_service


def get_kb() -> KbService:
    global _kb_service
    if _kb_service is None:
        _kb_service = KbService()
    return _kb_service


# ── Agent Runtime factory ───────────────────────────────────────────

def _init_agent_runtime():
    """Lazily initialise the Agent Runtime singletons (dispatcher + recovery + worker)."""
    global _agent_dispatcher, _agent_recovery_task, _agent_worker, _agent_worker_task
    if _agent_dispatcher is not None:
        return

    from app.agent_runtime.persistence import (
        MySqlEvidenceStore,
        MySqlMemoryStore,
        MySqlReportStore,
        MySqlRunStore,
        MySqlTraceStore,
    )
    from app.agent_runtime.policy import AgentExecutionPolicy
    from app.agent_runtime.recovery import RunRecovery
    from app.agent_runtime.runner import AgentRunner, RunDispatcher
    from app.agent_runtime.scoring import HealthScoringEngine
    from app.agent_runtime.tools import AgentToolRegistry
    from app.agent_runtime.worker import AgentRunWorker

    run_store = MySqlRunStore()
    trace_store = MySqlTraceStore()
    evidence_store = MySqlEvidenceStore()
    report_store = MySqlReportStore()
    memory_store = MySqlMemoryStore()
    scoring = HealthScoringEngine()
    llm = get_llm()

    tools = AgentToolRegistry(evidence_store, report_store, scoring)

    runner = AgentRunner(
        llm=llm, tools=tools, scoring=scoring,
        run_store=run_store, trace_store=trace_store,
        evidence_store=evidence_store, report_store=report_store,
        memory_store=memory_store,
    )

    _agent_dispatcher = RunDispatcher(runner, run_store, report_store)
    runner.on_progress = _agent_dispatcher._publish_progress  # wire SSE progress

    # Start recovery background task
    recovery = RunRecovery(run_store)
    _agent_recovery_task = asyncio.create_task(recovery.run_forever())

    # Start Redis Stream consumer worker (fire-and-forget dispatch from Java)
    _agent_worker = AgentRunWorker(_agent_dispatcher, redis_url=settings.redis_url)
    _agent_worker_task = asyncio.create_task(_agent_worker.run_forever())

    logger.info("Agent Runtime initialised (stores, runner, recovery, stream-worker)")


def get_dispatcher():
    _init_agent_runtime()
    return _agent_dispatcher


def _init_contract_runtime():
    """Lazily initialise the Contract Agent Runtime."""
    global _contract_dispatcher, _contract_initialized
    if _contract_initialized:
        return

    from app.agent_runtime.persistence import MySqlRunStore, MySqlTraceStore, MySqlReportStore, MySqlMemoryStore
    from app.agent_runtime.policy import AgentExecutionPolicy
    from app.agent_runtime.recovery import RunRecovery
    from app.agent_runtime.runner import AgentRunner, RunDispatcher
    from app.agent_runtime.contract_tools import ContractToolRegistry
    from app.agent_runtime.contract_store import ContractStore
    from app.agent_runtime.recovery import RunRecovery
    from app.agent_runtime.worker import AgentRunWorker
    from app.config import settings

    run_store = MySqlRunStore()
    trace_store = MySqlTraceStore()
    report_store = MySqlReportStore()
    memory_store = MySqlMemoryStore()
    contract_store = ContractStore()
    llm = get_llm()

    tools = ContractToolRegistry(contract_store)

    runner = AgentRunner(
        llm=llm, tools=tools, scoring=None,  # Contract uses its own scoring via tools
        run_store=run_store, trace_store=trace_store,
        evidence_store=None, report_store=report_store, memory_store=memory_store,
    )

    _contract_dispatcher = RunDispatcher(runner, run_store, report_store)
    runner.on_progress = _contract_dispatcher._publish_progress

    # Start recovery + stream worker (same infrastructure as project mode)
    recovery = RunRecovery(run_store)
    global _agent_recovery_task, _agent_worker, _agent_worker_task
    _agent_recovery_task = asyncio.create_task(recovery.run_forever())
    _agent_worker = AgentRunWorker(_contract_dispatcher, redis_url=settings.redis_url)
    _agent_worker_task = asyncio.create_task(_agent_worker.run_forever())

    _contract_initialized = True
    logger.info("Contract Agent Runtime initialised (stores, runner, recovery, stream-worker)")


def get_contract_dispatcher():
    _init_contract_runtime()
    return _contract_dispatcher


# ── Migration runner ────────────────────────────────────────────────

_MIGRATIONS_DIR = Path(__file__).resolve().parent.parent.parent / "migrations"


async def run_migrations() -> list[str]:
    """Execute unapplied SQL migrations. Returns list of newly applied versions."""
    if not _MIGRATIONS_DIR.exists():
        logger.warning("Migrations directory not found: %s", _MIGRATIONS_DIR)
        return []

    sql_files = sorted(_MIGRATIONS_DIR.glob("V*.sql"))
    if not sql_files:
        return []

    import pymysql
    from pymysql.cursors import DictCursor

    applied_versions: set[str] = set()
    try:
        conn = pymysql.connect(
            host=settings.mysql_host, port=settings.mysql_port,
            user=settings.mysql_user, password=settings.mysql_password,
            database=settings.mysql_db, charset="utf8mb4",
            cursorclass=DictCursor,
        )
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    """CREATE TABLE IF NOT EXISTS schema_migrations (
                        version VARCHAR(16) PRIMARY KEY,
                        applied_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
                    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4"""
                )
                conn.commit()
                cur.execute("SELECT version FROM schema_migrations ORDER BY version")
                applied_versions = {row["version"] for row in cur.fetchall()}
    except Exception:
        logger.exception("Cannot read schema_migrations; skipping migrations")
        return []

    new_versions = []
    for sql_file in sql_files:
        version = sql_file.stem.split("__")[0]
        if version in applied_versions:
            continue
        try:
            with open(sql_file, encoding="utf-8") as fh:
                sql = fh.read()
            conn = pymysql.connect(
                host=settings.mysql_host, port=settings.mysql_port,
                user=settings.mysql_user, password=settings.mysql_password,
                database=settings.mysql_db, charset="utf8mb4",
                cursorclass=DictCursor,
            )
            with conn:
                with conn.cursor() as cur:
                    # Remove line comments before splitting to avoid
                    # semicolons inside comments breaking the parser
                    clean_lines = [
                        line for line in sql.splitlines()
                        if not line.strip().startswith("--")
                    ]
                    clean_sql = "\n".join(clean_lines)
                    for statement in clean_sql.split(";"):
                        stmt = statement.strip()
                        if stmt:
                            cur.execute(stmt)
                    cur.execute(
                        "INSERT INTO schema_migrations (version) VALUES (%s)",
                        (version,),
                    )
                conn.commit()
            new_versions.append(version)
            logger.info("Applied migration %s", version)
        except Exception:
            logger.exception("Migration %s failed", version)

    return new_versions


DEFAULT_SUGGESTIONS = [
    "What does this knowledge base contain?",
    "How do I deploy the Spring Boot backend?",
    "How should I optimize MySQL indexes?",
    "Explain the AtlasMind RAG architecture.",
]


def _sse(event_type: str, data: dict) -> str:
    payload = json.dumps(data, ensure_ascii=False)
    return f"event: {event_type}\ndata: {payload}\n\n"


def _citation_payload(hit: dict, retrieval_type: str) -> dict:
    source_id = hit.get("sourceId") or hit.get("id")
    return {
        "sourceType": hit.get("sourceType", "ARTICLE"),
        "id": source_id,
        "sourceId": source_id,
        "chunkId": hit.get("chunkId"),
        "title": hit.get("title", ""),
        "snippet": hit.get("snippet", ""),
        "page": hit.get("page"),
        "score": hit.get("score", 0),
        "rank": hit.get("rank"),
        "retrievalType": hit.get("retrievalType", retrieval_type),
    }


@router.post("/send")
async def chat_send(request: ChatRequest):
    """Stream a RAG answer and persist session messages, trace, hits, and tool steps."""

    async def generate():
        store = None
        session = None
        user_message_id = None
        trace_id = None
        tool_calls: list[dict] = []
        llm_started_at = None

        def remember_tool(
            name: str,
            started_at: float,
            status: str,
            input_summary: str = "",
            output_summary: str = "",
            error_message: str = "",
        ) -> None:
            tool_calls.append(
                {
                    "name": name,
                    "status": status,
                    "latency_ms": int((time.perf_counter() - started_at) * 1000),
                    "input_summary": input_summary[:1000],
                    "output_summary": output_summary[:1000],
                    "error_message": error_message,
                }
            )

        try:
            config_errors = settings.validate()
            if config_errors:
                yield _sse("error", {"error": "Service configuration error: " + "; ".join(config_errors)})
                return

            try:
                llm = get_llm()
            except ValueError as exc:
                yield _sse("error", {"error": f"LLM configuration error: {exc}"})
                return

            top_k = max(1, min(request.topK, 20))
            store = get_kb().store
            project_context = store.get_project_context(request.projectId)
            if request.sessionId:
                session = store.get_session(request.sessionId, request.ownerToken)
                if not session:
                    yield _sse("error", {"error": "AI session is invalid or expired"})
                    return
                history_dicts = store.list_session_messages(request.sessionId, 10)
                user_message_id = store.append_qa_message(request.sessionId, "user", request.message)
            else:
                history_dicts = [{"role": m.role, "content": m.content} for m in request.history]

            yield _sse("status", {"status": "searching"})
            sources: list[dict] = []
            emb = get_embedding()
            retrieval_started_at = time.perf_counter()
            retrieval_type = "NONE"
            fallback_reason = ""

            if emb.configured:
                query_vec = None
                step_started = time.perf_counter()
                try:
                    query_vec = emb.embed(request.message)
                    remember_tool(
                        "embedQuery",
                        step_started,
                        "DONE" if query_vec else "EMPTY",
                        request.message,
                        f"dims={len(query_vec) if query_vec else 0}",
                    )
                except Exception as exc:
                    fallback_reason = f"embedding_failed: {exc}"
                    remember_tool("embedQuery", step_started, "FAILED", request.message, error_message=str(exc))

                if query_vec:
                    vector_hits: list[dict] = []
                    step_started = time.perf_counter()
                    try:
                        article_hits = get_es().search_by_embedding(query_vec, top_k)
                        vector_hits.extend(article_hits)
                        remember_tool("searchArticlesByVector", step_started, "DONE", f"topK={top_k}", f"hits={len(article_hits)}")
                    except Exception as exc:
                        remember_tool("searchArticlesByVector", step_started, "FAILED", f"topK={top_k}", error_message=str(exc))

                    step_started = time.perf_counter()
                    try:
                        kb_hits = get_es().search_kb_by_embedding(query_vec, top_k, request.spaceId, request.documentId)
                        vector_hits.extend(kb_hits)
                        remember_tool(
                            "searchKbByVector",
                            step_started,
                            "DONE",
                            f"topK={top_k}, spaceId={request.spaceId}, documentId={request.documentId}",
                            f"hits={len(kb_hits)}",
                        )
                    except Exception as exc:
                        remember_tool("searchKbByVector", step_started, "FAILED", f"topK={top_k}", error_message=str(exc))

                    sources.extend(vector_hits)
                    if vector_hits:
                        retrieval_type = "VECTOR"

                if not sources:
                    if not fallback_reason:
                        fallback_reason = "vector_no_hits" if query_vec else "embedding_empty"
                    retrieval_type = "KEYWORD_FALLBACK"
                    step_started = time.perf_counter()
                    try:
                        article_hits = get_es().search_articles(request.message, top_k)
                        sources.extend(article_hits)
                        remember_tool("searchArticlesByKeyword", step_started, "DONE", f"topK={top_k}", f"hits={len(article_hits)}")
                    except Exception as exc:
                        remember_tool("searchArticlesByKeyword", step_started, "FAILED", f"topK={top_k}", error_message=str(exc))

                    step_started = time.perf_counter()
                    try:
                        kb_hits = get_es().search_kb_by_keyword(request.message, top_k, request.spaceId, request.documentId)
                        sources.extend(kb_hits)
                        remember_tool(
                            "searchKbByKeyword",
                            step_started,
                            "DONE",
                            f"topK={top_k}, spaceId={request.spaceId}, documentId={request.documentId}",
                            f"hits={len(kb_hits)}",
                        )
                    except Exception as exc:
                        remember_tool("searchKbByKeyword", step_started, "FAILED", f"topK={top_k}", error_message=str(exc))
            else:
                retrieval_type = "KEYWORD"
                fallback_reason = "embedding_not_configured"
                step_started = time.perf_counter()
                try:
                    article_hits = get_es().search_articles(request.message, top_k)
                    sources.extend(article_hits)
                    remember_tool("searchArticlesByKeyword", step_started, "DONE", f"topK={top_k}", f"hits={len(article_hits)}")
                except Exception as exc:
                    remember_tool("searchArticlesByKeyword", step_started, "FAILED", f"topK={top_k}", error_message=str(exc))

                step_started = time.perf_counter()
                try:
                    kb_hits = get_es().search_kb_by_keyword(request.message, top_k, request.spaceId, request.documentId)
                    sources.extend(kb_hits)
                    remember_tool(
                        "searchKbByKeyword",
                        step_started,
                        "DONE",
                        f"topK={top_k}, spaceId={request.spaceId}, documentId={request.documentId}",
                        f"hits={len(kb_hits)}",
                    )
                except Exception as exc:
                    remember_tool("searchKbByKeyword", step_started, "FAILED", f"topK={top_k}", error_message=str(exc))

            sources = sorted(sources, key=lambda x: x.get("score", 0), reverse=True)[:top_k]
            normalized_sources = []
            for rank, item in enumerate(sources, 1):
                normalized_sources.append(
                    {
                        **item,
                        "sourceType": item.get("sourceType", "ARTICLE"),
                        "sourceId": item.get("sourceId") or item.get("id"),
                        "rank": rank,
                        "retrievalType": retrieval_type,
                    }
                )
            sources = normalized_sources

            if user_message_id:
                trace_id = store.create_retrieval_trace(
                    user_message_id,
                    request.message,
                    retrieval_type,
                    top_k,
                    int((time.perf_counter() - retrieval_started_at) * 1000),
                    fallback_reason,
                    len(sources),
                )
                store.create_retrieval_hits(trace_id, sources)
                for call in tool_calls:
                    store.create_tool_call(trace_id, **call)

            contexts = llm.build_context(sources)
            if project_context:
                contexts = (
                    "当前对话绑定的项目上下文（只能基于这些事实回答，不要补造未知信息）：\n"
                    + json.dumps(project_context, ensure_ascii=False, default=str)
                    + "\n\n"
                    + contexts
                )
            citations = [_citation_payload(hit, retrieval_type) for hit in sources]

            yield _sse("status", {"status": "thinking"})
            full = ""
            try:
                llm_started_at = time.perf_counter()
                for token in llm.chat_stream(request.message, contexts, history_dicts):
                    full += token
                    yield _sse("chunk", {"content": token})
                llm_latency_ms = int((time.perf_counter() - llm_started_at) * 1000)
                if trace_id:
                    store.create_tool_call(trace_id, "llm.chat_stream", "DONE", llm_latency_ms, f"model={llm.model}", f"chars={len(full)}")
                if session:
                    store.append_qa_message(request.sessionId, "assistant", full, model=llm.model, latency_ms=llm_latency_ms)
                yield _sse("sources", {"sources": citations, "traceId": trace_id})
                yield _sse("done", {"content": full, "traceId": trace_id})
            except AuthenticationError:
                if trace_id and llm_started_at:
                    store.create_tool_call(trace_id, "llm.chat_stream", "FAILED", int((time.perf_counter() - llm_started_at) * 1000), f"model={llm.model}", error_message="authentication_failed")
                yield _sse("error", {"error": "LLM API key is invalid"})
            except APIConnectionError as exc:
                if trace_id and llm_started_at:
                    store.create_tool_call(trace_id, "llm.chat_stream", "FAILED", int((time.perf_counter() - llm_started_at) * 1000), f"model={llm.model}", error_message=str(exc))
                yield _sse("error", {"error": f"Cannot connect to LLM service ({settings.llm_base_url}): {exc}"})
            except APIError as exc:
                if trace_id and llm_started_at:
                    store.create_tool_call(trace_id, "llm.chat_stream", "FAILED", int((time.perf_counter() - llm_started_at) * 1000), f"model={llm.model}", error_message=str(exc))
                yield _sse("error", {"error": f"LLM API error (model={settings.llm_model}): {exc}"})
        except Exception as exc:
            logger.exception("chat_send failed")
            yield _sse("error", {"error": f"Internal service error: {exc}"})

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/suggestions")
async def get_suggestions():
    return SuggestionResponse(suggestions=DEFAULT_SUGGESTIONS)


@router.get("/health")
async def health(probe: bool = False):
    result = {"status": "ok", "probe": probe, "components": {}}

    if not settings.llm_api_key:
        result["components"]["llm"] = {"status": "error", "message": "LLM_API_KEY is not set"}
        result["status"] = "degraded"
    else:
        result["components"]["llm"] = {
            "status": "ok" if not probe else "checking",
            "model": settings.llm_model,
            "base_url": settings.llm_base_url,
        }
        if probe:
            error = get_llm().validate_connection()
            result["components"]["llm"]["status"] = "ok" if error is None else "error"
            if error:
                result["components"]["llm"]["message"] = error
                result["status"] = "degraded"

    emb = get_embedding()
    if emb.configured:
        result["components"]["embedding"] = {
            "status": "ok" if not probe else "checking",
            "model": settings.embedding_model,
            "base_url": settings.embedding_base_url,
            "dim": settings.embedding_dim,
        }
        if probe:
            vector = emb.embed("AtlasMind health check")
            result["components"]["embedding"]["status"] = "ok" if vector else "error"
            if not vector:
                result["components"]["embedding"]["message"] = "Embedding API 请求失败或未返回向量"
                result["status"] = "degraded"
    else:
        result["components"]["embedding"] = {"status": "info", "message": "Embedding is not configured; keyword search is used"}

    try:
        es = get_es()
        if es.health():
            ping_ok = es.ping()
            result["components"]["elasticsearch"] = {
                "status": "ok" if ping_ok else "degraded",
                "host": settings.es_host,
                "ping": ping_ok,
            }
            if not ping_ok:
                result["status"] = "degraded"
        else:
            result["components"]["elasticsearch"] = {"status": "error", "message": "TCP port is unreachable"}
            result["status"] = "degraded"
    except Exception as exc:
        result["components"]["elasticsearch"] = {"status": "error", "message": str(exc)}
        result["status"] = "degraded"

    return result


@internal_router.post("/project-analysis")
async def project_analysis(
    payload: dict,
    x_internal_token: str | None = Header(default=None),
):
    """Generate a structured, evidence-bounded project health report."""
    _check_internal_token(x_internal_token)
    try:
        return get_llm().analyze_project(
            payload.get("project") or {},
            payload.get("citations") or [],
            payload.get("deterministicScoring") or {},
        )
    except AuthenticationError as exc:
        raise HTTPException(status_code=502, detail="LLM API key is invalid") from exc
    except (APIConnectionError, APIError, ValueError) as exc:
        logger.exception("Structured project analysis failed")
        raise HTTPException(status_code=502, detail=f"Project analysis failed: {exc}") from exc


@internal_router.post("/project-tasks")
async def project_task(
    payload: dict,
    x_internal_token: str | None = Header(default=None),
):
    """Generate a structured artifact for an evidence-bounded project task."""
    _check_internal_token(x_internal_token)
    try:
        return get_llm().run_project_task(
            payload.get("taskType") or "",
            payload.get("project") or {},
            payload.get("taskInput") or {},
            payload.get("citations") or [],
        )
    except AuthenticationError as exc:
        raise HTTPException(status_code=502, detail="LLM API key is invalid") from exc
    except (APIConnectionError, APIError, ValueError) as exc:
        logger.exception("Structured project task failed")
        raise HTTPException(status_code=502, detail=f"Project task failed: {exc}") from exc


@internal_router.post("/agent/plan")
async def agent_plan(
    payload: dict,
    x_internal_token: str | None = Header(default=None),
):
    """Create a bounded Agent plan without executing tools."""
    _check_internal_token(x_internal_token)
    try:
        return get_llm().plan_agent(payload)
    except (AuthenticationError, APIConnectionError, APIError, ValueError) as exc:
        logger.exception("Agent planning failed")
        raise HTTPException(status_code=502, detail=f"Agent planning failed: {exc}") from exc


@internal_router.post("/agent/next-turn")
async def agent_next_turn(
    payload: dict,
    x_internal_token: str | None = Header(default=None),
):
    """Select Java-owned tools through native OpenAI-compatible function calling."""
    _check_internal_token(x_internal_token)
    try:
        return get_llm().next_agent_turn(payload)
    except (AuthenticationError, APIConnectionError, APIError, ValueError) as exc:
        logger.exception("Agent function-calling turn failed")
        raise HTTPException(status_code=502, detail=f"Agent turn failed: {exc}") from exc


@internal_router.post("/agent/reflect")
async def agent_reflect(
    payload: dict,
    x_internal_token: str | None = Header(default=None),
):
    """Verify evidence coverage and request bounded re-planning when needed."""
    _check_internal_token(x_internal_token)
    try:
        return get_llm().reflect_agent(payload)
    except (AuthenticationError, APIConnectionError, APIError, ValueError) as exc:
        logger.exception("Agent reflection failed")
        raise HTTPException(status_code=502, detail=f"Agent reflection failed: {exc}") from exc


@internal_router.post("/kb/ingest/jobs")
async def ingest_job(
    request: KbIngestRequest,
    background_tasks: BackgroundTasks,
    x_internal_token: str | None = Header(default=None),
):
    _check_internal_token(x_internal_token)
    background_tasks.add_task(get_kb().ingest_document, request)
    return {"ok": True, "jobId": request.jobId}


@internal_router.post("/kb/documents/{document_id}/reindex")
async def reindex_document(
    document_id: int,
    request: KbReindexRequest,
    background_tasks: BackgroundTasks,
    x_internal_token: str | None = Header(default=None),
):
    _check_internal_token(x_internal_token)
    background_tasks.add_task(get_kb().reindex_document, document_id, request.jobId)
    return {"ok": True, "jobId": request.jobId}


@internal_router.delete("/kb/documents/{document_id}/index")
async def delete_document_index(
    document_id: int,
    x_internal_token: str | None = Header(default=None),
):
    _check_internal_token(x_internal_token)
    ok = get_es().delete_kb_document(document_id)
    return {"ok": ok}


# ── Agent Runtime endpoints ──────────────────────────────────────────

@internal_router.post("/agent/run")
async def start_agent_run(
    payload: dict,
    x_internal_token: str | None = Header(default=None),
):
    """Start a full Agent harness run asynchronously.

    Java creates the agent_run row (CREATED) before calling this endpoint.
    The harness loop executes in a background asyncio task with heartbeat.
    """
    _check_internal_token(x_internal_token)
    from app.agent_runtime.api_models import RunStatus, StartRunRequest, StartRunResponse

    request = StartRunRequest(payload)
    if not request.run_id:
        raise HTTPException(status_code=400, detail="runId is required")

    # Route to contract dispatcher (default) or project dispatcher (legacy)
    if request.subject_type == "CONTRACT_CASE":
        dispatcher = get_contract_dispatcher()
    else:
        dispatcher = get_contract_dispatcher()  # default to contract

    # Idempotency: same requestId → return existing run (no duplicate task)
    request_id = request.request_id or ""
    if request_id and request_id in _active_runs:
        existing = _active_runs[request_id]
        if not existing.done():
            return StartRunResponse(
                run_id=request.run_id,
                status=RunStatus.CREATED,
                progress=0,
                current_step="任务已在调度中",
            ).to_dict()
        # Task finished — clean up stale entry
        _active_runs.pop(request_id, None)

    task = asyncio.create_task(dispatcher.dispatch(request.run_id, request))
    if request_id:
        _active_runs[request_id] = task
        task.add_done_callback(lambda _t, rid=request_id: _active_runs.pop(rid, None))

    return StartRunResponse(
        run_id=request.run_id,
        status=RunStatus.CREATED,
        progress=0,
        current_step="已接收，等待 Agent 调度",
    ).to_dict()


@internal_router.get("/agent/run/{run_id}")
async def get_agent_run(
    run_id: int,
    x_internal_token: str | None = Header(default=None),
):
    """Query a run's status, traces, tool calls, report, actions, and memories."""
    _check_internal_token(x_internal_token)
    from app.agent_runtime.persistence import MySqlRunStore

    store = MySqlRunStore()
    detail = await store.get_run_detail(run_id)
    if not detail.get("run"):
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found")
    return detail


@internal_router.post("/agent/run/{run_id}/cancel")
async def cancel_agent_run(
    run_id: int,
    payload: dict,
    x_internal_token: str | None = Header(default=None),
):
    """Cancel a running Agent run. The harness policy checks for CANCELLED status
    before each turn and tool call."""
    _check_internal_token(x_internal_token)
    from app.agent_runtime.persistence import MySqlRunStore

    store = MySqlRunStore()
    reason = str(payload.get("reason", "用户手动取消"))
    await store.update_run(run_id, status="CANCELLED", error_message=reason)
    return {"runId": run_id, "status": "CANCELLED"}


@kb_router.post("/qa/test")
async def kb_qa_test(request: KbQaRequest):
    return get_kb().qa_test(
        request.message,
        space_id=request.spaceId,
        document_id=request.documentId,
        top_k=request.topK,
    )
