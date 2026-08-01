"""Chat, knowledge-base ingest, and retrieval debug routes."""
from __future__ import annotations

import json
import logging
import secrets
import time

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


@kb_router.post("/qa/test")
async def kb_qa_test(request: KbQaRequest):
    return get_kb().qa_test(
        request.message,
        space_id=request.spaceId,
        document_id=request.documentId,
        top_k=request.topK,
    )
