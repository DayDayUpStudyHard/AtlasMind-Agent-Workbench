"""Chat API — SSE 流式对话 + RAG 检索（语义搜索优先，文本搜索降级）。"""
import json
import logging
import secrets
from fastapi import APIRouter, BackgroundTasks, Header, HTTPException
from fastapi.responses import StreamingResponse
from openai import APIError, APIConnectionError, AuthenticationError
from app.models.schemas import ChatRequest, KbIngestRequest, KbQaRequest, KbReindexRequest, SuggestionResponse
from app.services.es_service import ESService
from app.services.kb_service import KbService
from app.services.llm_service import LLMService
from app.services.embedding_service import EmbeddingService
from app.config import settings

logger = logging.getLogger(__name__)

router = APIRouter()
internal_router = APIRouter()
kb_router = APIRouter()


def _check_internal_token(token: str | None) -> None:
    expected = settings.internal_token
    if expected and (not token or not secrets.compare_digest(token, expected)):
        raise HTTPException(status_code=401, detail="Invalid internal token")

# 模块级延迟初始化（避免 import 时就连接外部服务导致启动失败）
_es_service: ESService | None = None
_llm_service: LLMService | None = None
_embedding_service: EmbeddingService | None = None
_kb_service: KbService | None = None


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
    "企业知识库里有哪些核心资料？",
    "Spring Boot怎么部署？",
    "MySQL索引如何优化？",
    "Vue 3有什么新特性？",
]


def _sse(event_type: str, data: dict) -> str:
    """格式化为 SSE 事件。"""
    payload = json.dumps(data, ensure_ascii=False)
    return f"event: {event_type}\ndata: {payload}\n\n"


@router.post("/send")
async def chat_send(request: ChatRequest):
    """发送消息，返回 SSE 流。

    检索策略（自动选择）：
    1. Embedding 已配置 → kNN 语义搜索（dense_vector + cosine 相似度）
    2. Embedding 未配置 → ES multi_match 文本搜索
    3. ES 不可用 → 降级为纯 LLM 对话
    """

    async def generate():
        try:
            # 0. 验证配置
            config_errors = settings.validate()
            if config_errors:
                yield _sse("error", {"error": "服务配置错误: " + "; ".join(config_errors)})
                return

            # 1. 初始化服务
            try:
                llm = get_llm()
            except ValueError as e:
                yield _sse("error", {"error": f"LLM 配置错误: {e}"})
                return

            # 2. 检索相关文章（语义搜索优先 → 文本搜索降级 → 空列表兜底）
            yield _sse("status", {"status": "searching"})
            sources = []
            emb = get_embedding()

            if emb.configured:
                # --- 语义搜索：embedding → kNN ---
                query_vec = emb.embed(request.message)
                if query_vec:
                    try:
                        sources.extend(get_es().search_by_embedding(query_vec))
                        sources.extend(get_es().search_kb_by_embedding(query_vec))
                    except Exception:
                        pass
                # embedding 失败 → 降级到文本搜索
                if not sources:
                    try:
                        sources.extend(get_es().search_articles(request.message))
                        sources.extend(get_es().search_kb_by_keyword(request.message))
                    except Exception:
                        pass
            else:
                # --- 文本搜索（embedding 未配置）---
                try:
                    sources.extend(get_es().search_articles(request.message))
                    sources.extend(get_es().search_kb_by_keyword(request.message))
                except Exception:
                    pass
            top_k = max(1, min(request.topK, 20))
            sources = sorted(sources, key=lambda x: x.get("score", 0), reverse=True)[:top_k]

            # 3. 构建上下文 + 流式生成
            contexts = llm.build_context(sources)
            sources = [
                {
                    "sourceType": a.get("sourceType", "ARTICLE"),
                    "id": a.get("id") or a.get("sourceId"),
                    "chunkId": a.get("chunkId"),
                    "title": a["title"],
                    "snippet": a["snippet"],
                    "page": a.get("page"),
                }
                for a in sources
            ]
            history_dicts = [
                {"role": m.role, "content": m.content} for m in request.history
            ]

            yield _sse("status", {"status": "thinking"})
            full = ""
            try:
                for token in llm.chat_stream(request.message, contexts, history_dicts):
                    full += token
                    yield _sse("chunk", {"content": token})
                yield _sse("sources", {"sources": sources})
                yield _sse("done", {"content": full})
            except AuthenticationError:
                yield _sse(
                    "error",
                    {"error": "LLM API Key 无效，请检查 .env 中的 LLM_API_KEY"},
                )
            except APIConnectionError as e:
                yield _sse(
                    "error",
                    {"error": f"无法连接 LLM 服务 ({settings.llm_base_url}): {e}"},
                )
            except APIError as e:
                yield _sse(
                    "error",
                    {"error": f"LLM API 返回错误 (model={settings.llm_model}): {e}"},
                )
        except Exception as e:
            yield _sse("error", {"error": f"服务内部错误: {e}"})

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
    """推荐问题。"""
    return SuggestionResponse(suggestions=DEFAULT_SUGGESTIONS)


@router.get("/health")
async def health():
    """健康检查 — 返回各组件连接状态（不发起外部 API 调用）。"""
    result = {"status": "ok", "components": {}}

    # LLM 配置检查
    if not settings.llm_api_key:
        result["components"]["llm"] = {
            "status": "error",
            "message": "LLM_API_KEY 未设置",
        }
        result["status"] = "degraded"
    else:
        result["components"]["llm"] = {
            "status": "ok",
            "model": settings.llm_model,
            "base_url": settings.llm_base_url,
        }

    # Embedding 配置检查
    emb = get_embedding()
    if emb.configured:
        result["components"]["embedding"] = {
            "status": "ok",
            "model": settings.embedding_model,
            "base_url": settings.embedding_base_url,
            "dim": settings.embedding_dim,
        }
    else:
        result["components"]["embedding"] = {
            "status": "info",
            "message": "embedding 未配置，使用文本搜索",
        }

    # ES 连接检查
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
            result["components"]["elasticsearch"] = {
                "status": "error",
                "message": "TCP 端口不可达",
            }
            result["status"] = "degraded"
    except Exception as e:
        result["components"]["elasticsearch"] = {
            "status": "error",
            "message": str(e),
        }
        result["status"] = "degraded"

    return result


@internal_router.post("/kb/ingest/jobs")
async def ingest_job(
    request: KbIngestRequest,
    background_tasks: BackgroundTasks,
    x_internal_token: str | None = Header(default=None),
):
    """Java 后台触发文档导入。"""
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
    """使用 MySQL chunk 重建 ES 索引。"""
    _check_internal_token(x_internal_token)
    background_tasks.add_task(get_kb().reindex_document, document_id, request.jobId)
    return {"ok": True, "jobId": request.jobId}


@internal_router.delete("/kb/documents/{document_id}/index")
async def delete_document_index(
    document_id: int,
    x_internal_token: str | None = Header(default=None),
):
    """从 ES 移除某文档索引。"""
    _check_internal_token(x_internal_token)
    ok = get_es().delete_kb_document(document_id)
    return {"ok": ok}


@kb_router.post("/qa/test")
async def kb_qa_test(request: KbQaRequest):
    """后台知识库问答测试台的检索调试接口。"""
    return get_kb().qa_test(
        request.message,
        space_id=request.spaceId,
        document_id=request.documentId,
        top_k=request.topK,
    )
