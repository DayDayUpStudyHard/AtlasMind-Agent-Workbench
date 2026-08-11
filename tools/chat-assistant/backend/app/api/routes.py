"""Chat, knowledge-base ingest, and retrieval debug routes."""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import secrets
import threading
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
HEALTH_PROBE_TIMEOUT_SECONDS = 15.0

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
_active_runs: dict[str, asyncio.Task] = {}  # requestId → Task (idempotency)

# Contract Agent runtime singletons
_contract_dispatcher = None  # RunDispatcher (contract mode)
_contract_runtime_router = None  # RuntimeRouter (G1+)
_contract_initialized = False
_contract_document_tasks: dict[int, asyncio.Task] = {}


def _check_internal_token(token: str | None) -> None:
    expected = settings.internal_token
    if not expected:
        # Fail-closed: production must configure SERVICE_TOKEN
        raise HTTPException(status_code=500, detail="SERVICE_TOKEN not configured")
    if not token or not secrets.compare_digest(token, expected):
        raise HTTPException(status_code=403, detail="Forbidden")


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
    """Lazily initialise the Agent Runtime singletons (dispatcher + recovery)."""
    global _agent_dispatcher, _agent_recovery_task
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

    logger.info("Agent Runtime initialised (stores, runner, recovery)")


def get_dispatcher():
    _init_agent_runtime()
    return _agent_dispatcher


def _init_contract_runtime():
    """Lazily initialise the Contract Agent Runtime."""
    global _contract_dispatcher, _contract_initialized, _contract_runtime_router
    if _contract_initialized:
        return

    from app.agent_runtime.persistence import MySqlRunStore, MySqlTraceStore, MySqlReportStore, MySqlMemoryStore
    from app.agent_runtime.policy import AgentExecutionPolicy
    from app.agent_runtime.recovery import RunRecovery
    from app.agent_runtime.runner import AgentRunner, RunDispatcher
    from app.agent_runtime.contract_tools import ContractToolRegistry
    from app.agent_runtime.contract_store import ContractStore
    from app.agent_runtime.recovery import RunRecovery
    from app.agent_runtime.runtime import LegacyHarnessAdapter, RuntimeRouter
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

    # ── Runtime Router for G1+ ──
    _contract_runtime_router = RuntimeRouter()
    _contract_runtime_router.register("legacy", LegacyHarnessAdapter(runner))

    # Conditionally register graph adapters if LangGraph is installed
    try:
        from app.agent_runtime.graph.checkpoint import MySqlCheckpointSaver
        from app.agent_runtime.runtime import GraphAdapter

        checkpointer = MySqlCheckpointSaver()

        # Build and register ContractReviewGraph
        try:
            from app.agent_runtime.graph.contract_review import build_contract_review_graph
            cr_graph = build_contract_review_graph(checkpointer=checkpointer)
            _contract_runtime_router.register(
                "contract_review",
                GraphAdapter(
                    cr_graph,
                    checkpointer,
                    graph_name="contract_review",
                    graph_version="v1",
                    run_store=run_store,
                ),
            )
            logger.info("Registered contract_review graph adapter")
        except Exception as exc:
            logger.warning("contract_review graph init failed: %s", exc)

        # Build and register FulfillmentCheckGraph
        try:
            from app.agent_runtime.graph.fulfillment_check import build_fulfillment_check_graph
            fc_graph = build_fulfillment_check_graph(checkpointer=checkpointer)
            _contract_runtime_router.register(
                "fulfillment_check",
                GraphAdapter(
                    fc_graph,
                    checkpointer,
                    graph_name="fulfillment_check",
                    graph_version="v1",
                    run_store=run_store,
                ),
            )
            logger.info("Registered fulfillment_check graph adapter")
        except Exception as exc:
            logger.warning("fulfillment_check graph init failed: %s", exc)

        try:
            from app.agent_runtime.graph.contract_extraction import build_contract_extraction_graph
            extraction_graph = build_contract_extraction_graph(checkpointer=checkpointer)
            _contract_runtime_router.register(
                "contract_extraction",
                GraphAdapter(
                    extraction_graph,
                    checkpointer,
                    graph_name="contract_extraction",
                    graph_version="v1",
                    run_store=run_store,
                ),
            )
            logger.info("Registered contract_extraction graph adapter")
        except Exception as exc:
            logger.warning("contract_extraction graph init failed: %s", exc)
        try:
            from app.agent_runtime.graph.timeline_extraction import build_timeline_extraction_graph
            timeline_graph = build_timeline_extraction_graph(checkpointer=checkpointer)
            _contract_runtime_router.register(
                "timeline_extraction",
                GraphAdapter(
                    timeline_graph,
                    checkpointer,
                    graph_name="timeline_extraction",
                    graph_version="v1",
                    run_store=run_store,
                ),
            )
            logger.info("Registered timeline_extraction graph adapter")
        except Exception as exc:
            logger.warning("timeline_extraction graph init failed: %s", exc)
        logger.info("Graph adapters registered via RuntimeRouter")
    except Exception as exc:
        logger.info("Graph adapters not available (LangGraph may not be installed): %s", exc)

    # HTTP dispatch uses asyncio tasks; recovery handles stale runs.
    recovery = RunRecovery(run_store)
    global _agent_recovery_task
    _agent_recovery_task = asyncio.create_task(recovery.run_forever())

    _contract_initialized = True
    logger.info("Contract Agent Runtime initialised (stores, runner, recovery)")


def get_contract_dispatcher():
    _init_contract_runtime()
    return _contract_dispatcher


def get_contract_runtime_router():
    """Get the RuntimeRouter for G2+ graph dispatch and resume."""
    _init_contract_runtime()
    return _contract_runtime_router


# ── Migration runner ────────────────────────────────────────────────

_MIGRATIONS_DIR = Path(__file__).resolve().parent.parent.parent / "migrations"

_ALTER_TABLE_RE = re.compile(
    r"^ALTER\s+TABLE\s+`?([A-Za-z0-9_]+)`?\s+(.+)$",
    re.IGNORECASE | re.DOTALL,
)
_ADD_COLUMN_IF_MISSING_RE = re.compile(
    r"^ADD\s+COLUMN\s+IF\s+NOT\s+EXISTS\s+`?([A-Za-z0-9_]+)`?\s+(.+)$",
    re.IGNORECASE | re.DOTALL,
)


def _execute_migration_statement(cur, statement: str) -> None:
    """Execute one migration statement with portable idempotent column adds.

    MySQL does not accept ``ADD COLUMN IF NOT EXISTS``. Migrations use that
    readable form, so the runner checks information_schema and emits one
    standard ALTER statement for each missing column.
    """
    alter_match = _ALTER_TABLE_RE.match(statement.strip())
    if not alter_match or "ADD COLUMN IF NOT EXISTS" not in statement.upper():
        cur.execute(statement)
        return

    table_name, alter_body = alter_match.groups()
    clauses = re.split(
        r",\s*(?=ADD\s+COLUMN\s+IF\s+NOT\s+EXISTS)",
        alter_body.strip(),
        flags=re.IGNORECASE,
    )
    for clause in clauses:
        column_match = _ADD_COLUMN_IF_MISSING_RE.match(clause.strip())
        if not column_match:
            raise ValueError(f"Unsupported idempotent ALTER clause: {clause}")
        column_name, definition = column_match.groups()
        cur.execute(
            """SELECT 1 FROM information_schema.COLUMNS
               WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME=%s AND COLUMN_NAME=%s""",
            (table_name, column_name),
        )
        if cur.fetchone() is None:
            cur.execute(
                f"ALTER TABLE `{table_name}` ADD COLUMN `{column_name}` {definition.strip()}"
            )


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
                            _execute_migration_statement(cur, stmt)
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


async def _stream_sync_tokens(sync_iter_factory):
    """Bridge a blocking token iterator into the async SSE response."""
    loop = asyncio.get_running_loop()
    queue: asyncio.Queue[tuple[str, object]] = asyncio.Queue()

    def _worker() -> None:
        try:
            for token in sync_iter_factory():
                loop.call_soon_threadsafe(queue.put_nowait, ("token", token))
        except BaseException as exc:
            loop.call_soon_threadsafe(queue.put_nowait, ("error", exc))
        finally:
            loop.call_soon_threadsafe(queue.put_nowait, ("done", None))

    threading.Thread(target=_worker, name="llm-chat-stream", daemon=True).start()

    while True:
        kind, payload = await queue.get()
        if kind == "done":
            break
        if kind == "error":
            raise payload
        yield str(payload)


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


def _safe_int(value) -> int | None:
    if value is None:
        return None
    try:
        result = int(value)
        return result if result > 0 else None
    except (TypeError, ValueError):
        return None


def _chat_case_id(request: ChatRequest) -> int | None:
    return _safe_int(getattr(request, "caseId", None)) or _safe_int(getattr(request, "projectId", None))


def _chat_scope(request: ChatRequest) -> str:
    scope = str(getattr(request, "scope", "") or "").strip().upper()
    if scope:
        return scope
    return "CONTRACT_CASE" if _chat_case_id(request) else "GLOBAL"


def _compact_contract_case(case: dict) -> dict:
    keys = (
        "id", "caseKey", "title", "contractType", "status", "ourEntity",
        "counterparty", "ourSide", "amount", "currency", "department",
        "signedDate", "effectiveDate", "expiryDate",
    )
    return {key: case.get(key) for key in keys if case.get(key) not in (None, "")}


def _timeline_source(item: dict) -> dict:
    citation = item.get("citationJson") if isinstance(item.get("citationJson"), dict) else {}
    quote = citation.get("quote") or citation.get("sourceQuote") or ""
    parts = [
        f"节点: {item.get('label') or item.get('nodeType') or '合同时间节点'}",
        f"日期/条件: {item.get('nodeDate') or item.get('conditionText') or '待确认'}",
        f"业务含义: {item.get('businessMeaning') or ''}",
        f"责任方: {item.get('responsibleParty') or '待确认'}",
        f"原文依据: {quote}",
    ]
    content = "\n".join(part for part in parts if part and not part.endswith(": "))
    return {
        "sourceType": "CONTRACT_TIMELINE",
        "sourceId": item.get("id"),
        "id": item.get("id"),
        "chunkId": item.get("clauseId"),
        "title": item.get("label") or item.get("clauseTitle") or "合同时间节点",
        "content": content,
        "snippet": quote or item.get("businessMeaning") or item.get("conditionText") or "",
        "page": item.get("pageNumber") or item.get("page"),
        "score": item.get("score") or item.get("confidence") or 0,
        "retrievalType": "CONTRACT_TIMELINE",
    }


def _contract_source(item: dict) -> dict:
    content = item.get("clauseText") or item.get("content") or item.get("snippet") or ""
    title = item.get("title") or item.get("clauseNumber") or "合同条款"
    return {
        **item,
        "sourceType": item.get("sourceType") or "CONTRACT_CLAUSE",
        "sourceId": item.get("sourceId") or item.get("clauseId") or item.get("id"),
        "id": item.get("sourceId") or item.get("clauseId") or item.get("id"),
        "chunkId": item.get("chunkId") or item.get("clauseId"),
        "title": title,
        "content": content,
        "snippet": item.get("snippet") or content[:220],
        "page": item.get("page") or item.get("pageNumber"),
    }


def _contract_profile_source(item: dict) -> dict:
    content = item.get("content") or item.get("snippet") or ""
    return {
        **item,
        "sourceType": item.get("sourceType") or "CONTRACT_PROFILE",
        "sourceId": item.get("sourceId") or item.get("id"),
        "id": item.get("sourceId") or item.get("id"),
        "chunkId": item.get("chunkId"),
        "title": item.get("title") or "合同画像",
        "content": content,
        "snippet": item.get("snippet") or content[:220],
        "page": item.get("page") or item.get("pageNumber"),
    }


def _looks_like_amount_question(message: str) -> bool:
    text = str(message or "")
    return any(term in text for term in ("总价", "总金额", "总额", "金额", "价款", "合同金额", "多少钱"))


def _amount_source_score(item: dict) -> int:
    source_type = str(item.get("sourceType") or "")
    title = str(item.get("title") or "")
    snippet = str(item.get("snippet") or "")
    content = str(item.get("content") or "")
    text = title + "\n" + snippet + "\n" + content
    score = 0
    if source_type == "CONTRACT_CASE":
        score += 60
    if source_type == "CONTRACT_PROFILE":
        score += 10
    if any(term in title for term in ("合同金额", "合同总价", "总价款", "合同价款", "币种")):
        score += 40
    if any(term in text for term in ("本合同总价款为", "合同总价款为", "合同金额", "合同总价为", "总价款为")):
        score += 35
    if re.search(r"(¥|￥|人民币|CNY)\s*[\d,]+|[\d,]+(?:\.\d+)?\s*(?:万元|元)", text):
        score += 25
    if any(term in text for term in ("赔偿责任累计不超过合同总价", "合同份数", "总体设计院")):
        score -= 40
    if title.strip() in {"合同内容", "合同依据", "合同价格与支付", "合同价款支付", "合同价款与调整"}:
        score -= 25
    return score


def _select_amount_sources(sources: list[dict], limit: int = 3) -> list[dict]:
    if not sources:
        return []
    case_sources = sorted(
        [item for item in sources if str(item.get("sourceType") or "") == "CONTRACT_CASE" and _amount_source_score(item) > 50],
        key=_amount_source_score,
        reverse=True,
    )
    amount_profile = sorted(
        [item for item in sources if str(item.get("sourceType") or "") == "CONTRACT_PROFILE" and _amount_source_score(item) > 40],
        key=_amount_source_score,
        reverse=True,
    )
    amount_clauses = sorted(
        [item for item in sources if str(item.get("sourceType") or "") == "CONTRACT_CLAUSE" and _amount_source_score(item) > 40],
        key=_amount_source_score,
        reverse=True,
    )
    selected: list[dict] = []
    for group in (case_sources[:1], amount_profile[:1], amount_clauses[:1], amount_profile[1:2]):
        for item in group:
            if item not in selected:
                selected.append(item)
            if len(selected) >= limit:
                return selected
    return selected


def _extract_amount_fact(profile_bundle: dict, contract_case: dict) -> dict | None:
    profile = profile_bundle.get("profile") if isinstance(profile_bundle, dict) else {}
    base_fields = profile.get("baseFields") if isinstance(profile, dict) else []
    groups = profile.get("groups") if isinstance(profile, dict) else []

    candidates = []
    if isinstance(base_fields, list):
        candidates.extend(base_fields)
    if isinstance(groups, list):
        for group in groups:
            if not isinstance(group, dict):
                continue
            fields = group.get("fields")
            if isinstance(fields, list):
                candidates.extend(fields)

    for field in candidates:
        if not isinstance(field, dict):
            continue
        key = str(field.get("key") or "").lower()
        label = str(field.get("label") or "")
        if not any(term in (key + label).lower() for term in ("amount", "金额", "价款", "总额", "总价")):
            continue
        value = field.get("value")
        if value in (None, "", []):
            normalized = field.get("normalizedValue") if isinstance(field.get("normalizedValue"), dict) else {}
            value = normalized.get("amount") if isinstance(normalized, dict) else value
        if value in (None, "", []):
            continue
        currency = contract_case.get("currency") or ""
        normalized = field.get("normalizedValue") if isinstance(field.get("normalizedValue"), dict) else {}
        if isinstance(normalized, dict):
            currency = normalized.get("currency") or currency
        citations = field.get("citations") if isinstance(field.get("citations"), list) else []
        quote = ""
        if citations:
            quote = str(citations[0].get("quote") or "").strip()
        return {
            "label": str(field.get("label") or field.get("key") or "合同金额"),
            "value": value,
            "currency": currency or "CNY",
            "quote": quote,
            "status": str(field.get("status") or ""),
            "confidence": field.get("confidence"),
            "source": "合同画像",
        }
    amount = contract_case.get("amount")
    if amount not in (None, "", 0, "0"):
        return {
            "label": "合同金额",
            "value": amount,
            "currency": contract_case.get("currency") or "CNY",
            "quote": "",
            "status": "CONTRACT_CASE",
            "confidence": None,
            "source": "合同基本信息",
        }
    return None


def _policy_source(item: dict) -> dict:
    content = item.get("content") or item.get("snippet") or ""
    return {
        **item,
        "sourceType": item.get("sourceType") or "POLICY_KNOWLEDGE",
        "sourceId": item.get("sourceId") or item.get("id") or item.get("chunkId"),
        "id": item.get("sourceId") or item.get("id") or item.get("chunkId"),
        "chunkId": item.get("chunkId"),
        "title": item.get("title") or item.get("sectionTitle") or "知识库依据",
        "content": content,
        "snippet": item.get("snippet") or content[:220],
        "page": item.get("page") or item.get("sourcePage"),
    }


def _historical_source(item: dict) -> dict:
    content = json.dumps(item, ensure_ascii=False, default=str)
    return {
        "sourceType": "CONTRACT_HISTORY",
        "sourceId": item.get("id"),
        "id": item.get("id"),
        "title": item.get("title") or "历史风险/处理记录",
        "content": content,
        "snippet": item.get("summary") or item.get("title") or "",
        "score": item.get("score") or 0,
        "retrievalType": "CONTRACT_HISTORY",
    }


def _dedupe_sources(items: list[dict], limit: int) -> list[dict]:
    seen: set[str] = set()
    result: list[dict] = []
    for item in items:
        key = "%s:%s:%s" % (
            item.get("sourceType") or "",
            item.get("sourceId") or item.get("id") or "",
            item.get("chunkId") or "",
        )
        if key in seen:
            continue
        seen.add(key)
        result.append(item)
        if len(result) >= limit:
            break
    return result


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
            chat_scope = _chat_scope(request)
            case_id = _chat_case_id(request)
            contract_context_prefix = ""
            direct_answer = None
            project_context = None if chat_scope == "CONTRACT_CASE" else store.get_project_context(request.projectId)
            if request.sessionId:
                session = store.get_session(request.sessionId, request.ownerToken)
                if not session:
                    yield _sse("error", {"error": "AI session is invalid or expired"})
                    return
                if not case_id:
                    case_id = _safe_int(session.get("case_id"))
                if chat_scope == "GLOBAL" and case_id:
                    chat_scope = "CONTRACT_CASE"
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

            if chat_scope == "CONTRACT_CASE" and case_id:
                retrieval_type = "CONTRACT_CASE"
                from app.agent_runtime.contract_store import ContractStore

                contract_store = ContractStore()
                step_started = time.perf_counter()
                try:
                    contract_case = await contract_store.get_case(case_id)
                    remember_tool(
                        "getContractCase",
                        step_started,
                        "DONE" if contract_case else "EMPTY",
                        f"caseId={case_id}",
                        json.dumps(_compact_contract_case(contract_case), ensure_ascii=False, default=str),
                    )
                except Exception as exc:
                    remember_tool("getContractCase", step_started, "FAILED", f"caseId={case_id}", error_message=str(exc))
                    contract_case = {}

                if not contract_case:
                    yield _sse("error", {"error": "当前合同案件不存在，或合同资料还没有完成入库。"})
                    return

                contract_context_prefix = (
                    "当前对话绑定在一个合同案件内。回答时只能把当前合同的结构化事实、合同原文条款、"
                    "本合同可用知识库、Agent 风险/履约历史作为证据；不要跨全部合同全文检索。"
                    "如果信息未人工确认、证据不足或只来自 AI 推断，需要明确说明。\n"
                    "当前合同基本信息：\n"
                    + json.dumps(_compact_contract_case(contract_case), ensure_ascii=False, default=str)
                    + "\n\n"
                )
                direct_answer = None

                step_started = time.perf_counter()
                try:
                    contract_profile_bundle = await contract_store.get_contract_profile_sources(
                        case_id,
                        request.message,
                        limit=min(max(top_k * 2, 8), 12),
                    )
                    profile_sources = [
                        _contract_profile_source(hit)
                        for hit in (contract_profile_bundle.get("sources") or [])
                    ]
                    if profile_sources:
                        sources.extend(profile_sources)
                    profile_summary = str(contract_profile_bundle.get("summary") or "").strip()
                    if profile_summary:
                        contract_context_prefix = profile_summary + "\n\n" + contract_context_prefix
                    if any(term in request.message for term in ("总价", "总金额", "总额", "金额", "价款", "合同金额", "多少钱")):
                        contract_context_prefix = (
                            "用户正在询问合同总价或金额，请优先使用合同画像中的金额字段和原文依据作答，"
                            "再用条款中的付款明细或金额条款补充说明，不要回答“未获取”除非画像和原文都没有金额。\n\n"
                            + contract_context_prefix
                        )
                    direct_amount_fact = _extract_amount_fact(contract_profile_bundle, contract_case)
                    direct_answer = None
                    if direct_amount_fact and _looks_like_amount_question(request.message):
                        amount_value = direct_amount_fact.get("value")
                        amount_currency = str(direct_amount_fact.get("currency") or contract_case.get("currency") or "CNY")
                        amount_label = str(direct_amount_fact.get("label") or "合同金额")
                        amount_quote = str(direct_amount_fact.get("quote") or "").strip()
                        amount_status = str(direct_amount_fact.get("status") or "").strip()
                        if isinstance(amount_value, (int, float)):
                            amount_display = f"{amount_value:,.0f}" if float(amount_value).is_integer() else f"{amount_value:,}"
                        else:
                            amount_display = str(amount_value)
                        direct_answer = f"{amount_label}：{amount_display} 元（{amount_currency}）"
                        if amount_quote:
                            direct_answer += f"\n原文依据：{amount_quote}"
                        if amount_status and amount_status not in {"CONFIRMED", "CONTRACT_CASE"}:
                            direct_answer += f"\n当前状态：{amount_status}"
                        direct_answer += f"\n[来源: {direct_amount_fact.get('source') or '合同画像'}]"
                        sources.insert(0, {
                            "sourceType": "CONTRACT_CASE",
                            "sourceId": case_id,
                            "id": case_id,
                            "title": direct_amount_fact.get("source") or "合同基本信息",
                            "content": direct_answer,
                            "snippet": f"{amount_label}：{amount_display} 元（{amount_currency}）",
                            "score": 1.0,
                            "retrievalType": "CONTRACT_CASE",
                        })
                    remember_tool(
                        "getContractProfile",
                        step_started,
                        "DONE" if profile_sources else "EMPTY",
                        f"caseId={case_id}",
                        f"sources={len(profile_sources)}",
                    )
                except Exception as exc:
                    remember_tool(
                        "getContractProfile",
                        step_started,
                        "FAILED",
                        f"caseId={case_id}",
                        error_message=str(exc),
                    )

                step_started = time.perf_counter()
                try:
                    clause_hits = await contract_store.search_contract_clause(
                        case_id,
                        {"query": request.message, "topK": max(top_k * 2, 8)},
                    )
                    sources.extend(_contract_source(hit) for hit in clause_hits)
                    remember_tool(
                        "searchContractClause",
                        step_started,
                        "DONE",
                        f"caseId={case_id}, topK={max(top_k * 2, 8)}",
                        f"hits={len(clause_hits)}",
                    )
                except Exception as exc:
                    remember_tool("searchContractClause", step_started, "FAILED", request.message, error_message=str(exc))

                step_started = time.perf_counter()
                try:
                    timeline_hits = await contract_store.search_timeline(
                        case_id,
                        {"query": request.message, "limit": min(max(top_k * 2, 8), 20)},
                    )
                    if not timeline_hits and any(term in request.message for term in ("时间", "节点", "日程", "履约", "付款", "验收", "期限", "到期")):
                        timeline_hits = await contract_store.list_timeline(
                            case_id,
                            {"limit": min(max(top_k * 2, 8), 20)},
                        )
                    sources.extend(_timeline_source(hit) for hit in timeline_hits)
                    remember_tool(
                        "searchContractTimeline",
                        step_started,
                        "DONE",
                        f"caseId={case_id}",
                        f"hits={len(timeline_hits)}",
                    )
                except Exception as exc:
                    remember_tool("searchContractTimeline", step_started, "FAILED", request.message, error_message=str(exc))

                step_started = time.perf_counter()
                try:
                    policy_hits = await contract_store.search_policy(
                        case_id,
                        {"query": request.message, "limit": min(max(top_k, 4), 8)},
                    )
                    sources.extend(_policy_source(hit) for hit in policy_hits)
                    remember_tool(
                        "searchPolicyKnowledge",
                        step_started,
                        "DONE",
                        f"caseId={case_id}",
                        f"hits={len(policy_hits)}",
                    )
                except Exception as exc:
                    remember_tool("searchPolicyKnowledge", step_started, "FAILED", request.message, error_message=str(exc))

                step_started = time.perf_counter()
                try:
                    history_hits = await contract_store.search_historical(
                        case_id,
                        {"query": request.message, "limit": 3},
                    )
                    sources.extend(_historical_source(hit) for hit in history_hits)
                    remember_tool(
                        "searchHistoricalDecisions",
                        step_started,
                        "DONE",
                        f"caseId={case_id}",
                        f"hits={len(history_hits)}",
                    )
                except Exception as exc:
                    remember_tool("searchHistoricalDecisions", step_started, "FAILED", request.message, error_message=str(exc))

                if not sources:
                    fallback_reason = "contract_no_hits"

            elif emb.configured:
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

            if chat_scope == "CONTRACT_CASE" and case_id:
                sources = _dedupe_sources(sources, min(max(top_k * 3, 10), 18))
                if _looks_like_amount_question(request.message):
                    sources = _select_amount_sources(sources, limit=3)
            else:
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
            if contract_context_prefix:
                contexts = contract_context_prefix + "已检索到的合同/知识库证据：\n" + contexts
            if project_context:
                contexts = (
                    "当前对话绑定的项目上下文（只能基于这些事实回答，不要补造未知信息）：\n"
                    + json.dumps(project_context, ensure_ascii=False, default=str)
                    + "\n\n"
                    + contexts
                )
            citations = [_citation_payload(hit, retrieval_type) for hit in sources]

            yield _sse("status", {"status": "thinking"})
            if direct_answer:
                full = direct_answer
                if trace_id:
                    store.create_tool_call(trace_id, "direct_contract_amount_answer", "DONE", 0, f"caseId={case_id}", "contract_profile")
                if session:
                    store.append_qa_message(request.sessionId, "assistant", full, model="deterministic-contract-profile", latency_ms=0)
                yield _sse("chunk", {"content": full})
                yield _sse("sources", {"sources": citations, "traceId": trace_id})
                yield _sse("done", {"content": full, "traceId": trace_id})
                return
            full = ""
            try:
                llm_started_at = time.perf_counter()
                async for token in _stream_sync_tokens(
                    lambda: llm.chat_stream(request.message, contexts, history_dicts)
                ):
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
async def health(probe: bool = False, component: str | None = None):
    result = {"status": "ok", "probe": probe, "components": {}}
    component_key = (component or "").strip().lower()
    llm_only = component_key in {"llm", "deepseek", "model"}

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
            try:
                error = await asyncio.wait_for(
                    asyncio.to_thread(get_llm().validate_connection),
                    timeout=HEALTH_PROBE_TIMEOUT_SECONDS,
                )
            except asyncio.TimeoutError:
                error = f"LLM health probe timed out after {HEALTH_PROBE_TIMEOUT_SECONDS:.0f}s"
            result["components"]["llm"]["status"] = "ok" if error is None else "error"
            if error:
                result["components"]["llm"]["message"] = error
                result["status"] = "degraded"

    if llm_only:
        return result

    emb = get_embedding()
    if emb.configured:
        result["components"]["embedding"] = {
            "status": "ok" if not probe else "checking",
            "model": settings.embedding_model,
            "base_url": settings.embedding_base_url,
            "dim": settings.embedding_dim,
        }
        if probe:
            try:
                vector = await asyncio.wait_for(
                    asyncio.to_thread(emb.embed, "AtlasMind health check"),
                    timeout=HEALTH_PROBE_TIMEOUT_SECONDS,
                )
            except asyncio.TimeoutError:
                vector = None
                result["components"]["embedding"]["message"] = (
                    f"Embedding health probe timed out after {HEALTH_PROBE_TIMEOUT_SECONDS:.0f}s"
                )
            result["components"]["embedding"]["status"] = "ok" if vector else "error"
            if not vector:
                result["status"] = "degraded"
            if not vector and "message" not in result["components"]["embedding"]:
                result["components"]["embedding"]["message"] = "Embedding API 请求失败或未返回向量"
                result["status"] = "degraded"
    else:
        result["components"]["embedding"] = {"status": "info", "message": "Embedding is not configured; keyword search is used"}

    try:
        es = get_es()
        if es.health():
            ping_ok = await asyncio.wait_for(
                asyncio.to_thread(es.ping),
                timeout=HEALTH_PROBE_TIMEOUT_SECONDS,
            )
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


@internal_router.post("/contract/documents/{document_id}/parse")
async def parse_contract_document(
    document_id: int,
    x_internal_token: str | None = Header(default=None),
):
    """Queue a contract document parse in a tracked worker task."""
    _check_internal_token(x_internal_token)
    active = _contract_document_tasks.get(document_id)
    if active is not None and not active.done():
        return {"ok": True, "documentId": document_id, "status": "PROCESSING", "scheduled": False}

    from app.agent_runtime.contract_document_parser import parse_contract_document as parse_worker

    async def run_worker() -> dict:
        return await asyncio.to_thread(parse_worker, document_id)

    task = asyncio.create_task(run_worker(), name=f"contract-document-parse-{document_id}")
    _contract_document_tasks[document_id] = task

    def on_done(done: asyncio.Task) -> None:
        _contract_document_tasks.pop(document_id, None)
        try:
            result = done.result()
            logger.info("Contract document parse finished: document=%s result=%s", document_id, result)
        except asyncio.CancelledError:
            logger.warning("Contract document parse cancelled: document=%s", document_id)
        except Exception:
            logger.exception("Contract document parse task crashed: document=%s", document_id)

    task.add_done_callback(on_done)
    return {"ok": True, "documentId": document_id, "status": "QUEUED", "scheduled": True}


@internal_router.post("/contract/intakes/{intake_id}/extract")
async def extract_contract_intake(
    intake_id: int,
    background_tasks: BackgroundTasks,
    x_internal_token: str | None = Header(default=None),
):
    """Extract citable metadata candidates for an unconfirmed intake."""
    _check_internal_token(x_internal_token)
    from app.agent_runtime.contract_intake_extractor import extract_intake

    background_tasks.add_task(extract_intake, intake_id)
    return {"ok": True, "intakeId": intake_id, "status": "PENDING"}


async def _dispatch_via_router(router, request) -> None:
    """Execute a run via RuntimeRouter with progress updates and persistence."""
    from app.agent_runtime.api_models import AgentTaskContext
    from app.agent_runtime.persistence import MySqlReportStore, MySqlRunStore

    run_store = MySqlRunStore()
    report_store = MySqlReportStore()
    run_id = request.run_id
    heartbeat_task: asyncio.Task | None = None

    async def mark_timeline_failed(error_message: str) -> None:
        if request.task_type != "TIMELINE_EXTRACTION":
            return
        from app.agent_runtime.persistence import _conn

        def _mark() -> None:
            with _conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """UPDATE contract_analysis_workflow
                           SET timeline_status='FAILED', current_stage='TIMELINE_EXTRACTION',
                               last_error=%s
                           WHERE id=(SELECT workflow_id FROM agent_run WHERE id=%s)""",
                        (str(error_message or "正式履约日程生成失败")[:4000], run_id),
                    )
                conn.commit()

        await asyncio.to_thread(_mark)

    async def mark_extraction_failed(error_message: str) -> None:
        if request.task_type != "CONTRACT_ELEMENT_EXTRACTION":
            return
        try:
            from app.agent_runtime.graph.contract_extraction import mark_extraction_workflow_failed

            await asyncio.to_thread(
                mark_extraction_workflow_failed,
                int(request.subject_id or 0),
                int(run_id),
                error_message,
            )
        except Exception as exc:
            logger.warning("Could not mark extraction workflow %s as failed: %s", run_id, exc)

    try:
        await run_store.update_run(run_id, status="CONTEXT_BUILDING", progress=5,
                                   current_step="Graph Runtime 开始执行")
        await run_store.heartbeat(run_id)
        heartbeat_task = asyncio.create_task(_graph_heartbeat_loop(run_store, run_id))
        ctx = AgentTaskContext.from_request(run_id, request)
        result: AgentResult = await router.dispatch(ctx)

        if result.status == "WAITING_HUMAN":
            # HITL: graph paused at interrupt, state in checkpoint
            await run_store.update_run(run_id, status="WAITING_HUMAN", progress=85,
                                       current_step="等待人工确认")
        elif result.status == "COMPLETED":
            if request.task_type == "CONTRACT_ELEMENT_EXTRACTION":
                artifact = result.artifact or {}
                snapshot_id = artifact.get("extractionSnapshotId")
                if not snapshot_id:
                    message = "合同要素提取完成但没有生成提取快照"
                    await run_store.update_run(
                        run_id,
                        status="FAILED",
                        progress=0,
                        error_message=message,
                    )
                    await mark_extraction_failed(message)
                    return
                await run_store.update_run(
                    run_id,
                    status="COMPLETED",
                    progress=100,
                    current_step=f"合同要素已生成（快照 #{snapshot_id}）",
                )
                if bool((request.task_input or {}).get("autoPipeline")):
                    await _enqueue_contract_pipeline_followup(router, request, "TIMELINE_EXTRACTION")
                return
            # Graphs normally persist inside persist_report. Keep a second
            # guard here so a successful graph response cannot hide a missing
            # report when a node was skipped or failed silently.
            report = await report_store.get_report(run_id)
            if not report and result.artifact:
                try:
                    await report_store.save_report(
                        request.project_id or request.subject_id,
                        run_id,
                        request.task_type,
                        result.artifact,
                    )
                    report = await report_store.get_report(run_id)
                except Exception as exc:
                    logger.exception("Report fallback persist failed for run %s", run_id)
                    await run_store.update_run(
                        run_id,
                        status="FAILED",
                        progress=0,
                        error_message=f"Report persistence failed: {exc}",
                    )
                    return
            if not report:
                await run_store.update_run(
                    run_id,
                    status="FAILED",
                    progress=0,
                    error_message="Agent finished without generating a report",
                )
                return
            await run_store.update_run(run_id, status="COMPLETED", progress=100,
                                       current_step="Graph 产物已生成")
            if request.task_type == "TIMELINE_EXTRACTION" and bool((request.task_input or {}).get("autoPipeline")):
                await _enqueue_contract_pipeline_followup(router, request, "CONTRACT_REVIEW")
        else:
            # FAILED or other
            error_msg = str((result.artifact or {}).get("artifactError", "Graph execution failed"))[:500]
            await run_store.update_run(run_id, status="FAILED", progress=0,
                                       error_message=error_msg)
            await mark_extraction_failed(error_msg)
            await mark_timeline_failed(error_msg)
    except Exception as exc:
        logger.exception("Graph dispatch failed for run %s", run_id)
        error_message = str(exc)[:500]
        try:
            await run_store.update_run(run_id, status="FAILED", progress=0,
                                       error_message=error_message)
        except Exception:
            pass
        await mark_extraction_failed(error_message)
        await mark_timeline_failed(error_message)
    finally:
        if heartbeat_task is not None:
            heartbeat_task.cancel()
            try:
                await heartbeat_task
            except asyncio.CancelledError:
                pass


async def _enqueue_contract_pipeline_followup(router, parent_request, task_type: str) -> int | None:
    """Create and dispatch the next background stage for one analysis workflow."""
    from app.agent_runtime.api_models import StartRunRequest
    from app.agent_runtime.persistence import _conn, _json_dumps

    questions = {
        "TIMELINE_EXTRACTION": "生成经 LLM 语义复核的正式履约日程",
        "CONTRACT_REVIEW": "复用合同画像和正式履约日程进行合同风险审查",
    }
    workflow_stages = {
        "TIMELINE_EXTRACTION": "TIMELINE_EXTRACTION",
        "CONTRACT_REVIEW": "RISK_REVIEW",
    }

    def _create() -> tuple[int | None, dict]:
        with _conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """SELECT workflow_id AS workflowId, initiated_by AS initiatedBy,
                              evidence_snapshot_hash AS evidenceSnapshotHash,
                              document_snapshot_json AS documentSnapshotJson
                       FROM agent_run WHERE id=%s""",
                    (parent_request.run_id,),
                )
                parent = cur.fetchone() or {}
                workflow_id = parent.get("workflowId")
                if not workflow_id:
                    return None, {}
                cur.execute(
                    """SELECT id, status FROM agent_run
                       WHERE workflow_id=%s AND run_type=%s
                         AND status IN ('CREATED','CONTEXT_BUILDING','PLANNING','ANALYZING',
                                        'VERIFYING','WAITING_HUMAN','WAITING_APPROVAL')
                       ORDER BY id DESC LIMIT 1""",
                    (workflow_id, task_type),
                )
                existing = cur.fetchone()
                if existing:
                    return None, {}

                task_input = dict(parent_request.task_input or {})
                task_input["autoPipeline"] = True
                task_input["pipelineParentRunId"] = parent_request.run_id
                cur.execute(
                    """INSERT INTO agent_run
                       (subject_type, subject_id, project_id, run_type, trigger_type,
                        question, input_json, workflow_id, workflow_stage,
                        evidence_snapshot_hash, document_snapshot_json, initiated_by,
                        status, progress, current_step)
                       VALUES (%s,%s,%s,%s,'AUTO',%s,%s,%s,%s,%s,%s,%s,
                               'CREATED',0,'等待前序分析结果')""",
                    (
                        parent_request.subject_type,
                        parent_request.subject_id,
                        parent_request.project_id,
                        task_type,
                        questions[task_type],
                        _json_dumps(task_input),
                        workflow_id,
                        workflow_stages[task_type],
                        parent.get("evidenceSnapshotHash"),
                        parent.get("documentSnapshotJson"),
                        parent.get("initiatedBy"),
                    ),
                )
                next_run_id = int(cur.lastrowid)
                if task_type == "TIMELINE_EXTRACTION":
                    cur.execute(
                        """UPDATE contract_analysis_workflow
                           SET timeline_run_id=%s, timeline_status='RUNNING',
                               current_stage='TIMELINE_EXTRACTION', last_error=NULL
                           WHERE id=%s""",
                        (next_run_id, workflow_id),
                    )
                else:
                    cur.execute(
                        """UPDATE contract_analysis_workflow
                           SET review_run_id=%s, status='REVIEWING',
                               current_stage='RISK_REVIEW', last_error=NULL
                           WHERE id=%s""",
                        (next_run_id, workflow_id),
                    )
            conn.commit()
        payload = {
            "requestId": f"auto-pipeline-{next_run_id}",
            "runId": next_run_id,
            "subjectType": parent_request.subject_type,
            "subjectId": parent_request.subject_id,
            "projectId": parent_request.project_id,
            "taskType": task_type,
            "question": questions[task_type],
            "actor": "analysis-pipeline",
            "project": parent_request.project,
            "taskInput": task_input,
            "options": {},
        }
        return next_run_id, payload

    next_run_id, payload = await asyncio.to_thread(_create)
    if not next_run_id:
        return None
    next_request = StartRunRequest(payload)
    task = asyncio.create_task(_dispatch_via_router(router, next_request))
    request_id = next_request.request_id
    if request_id:
        _active_runs[request_id] = task
        task.add_done_callback(lambda _t, rid=request_id: _active_runs.pop(rid, None))
    return next_run_id


async def _graph_heartbeat_loop(run_store, run_id: int) -> None:
    """Keep graph runs distinguishable from abandoned active rows."""
    while True:
        await asyncio.sleep(10)
        await run_store.heartbeat(run_id)


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
    from app.agent_runtime.runtime import AgentResult

    request = StartRunRequest(payload)
    if not request.run_id:
        raise HTTPException(status_code=400, detail="runId is required")

    # ── G2+: Try RuntimeRouter for graph-based tasks ──
    router = get_contract_runtime_router()
    if router is not None and request.subject_type == "CONTRACT_CASE":
        try:
            # Dispatch via RuntimeRouter (async graph run)
            task = asyncio.create_task(
                _dispatch_via_router(router, request)
            )
            request_id = request.request_id or ""
            if request_id:
                _active_runs[request_id] = task
                task.add_done_callback(lambda _t, rid=request_id: _active_runs.pop(rid, None))

            return StartRunResponse(
                run_id=request.run_id,
                status=RunStatus.CREATED,
                progress=0,
                current_step="已接收，Graph Runtime 调度中",
            ).to_dict()
        except NotImplementedError:
            pass  # Fall through to legacy dispatcher

    # Route to contract dispatcher (legacy fallback)
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


@internal_router.post("/agent/run/{run_id}/resume")
async def resume_agent_run(
    run_id: int,
    payload: dict,
    x_internal_token: str | None = Header(default=None),
):
    """Resume a paused graph run with a human command.

    Used by fulfillment check graph when human confirms/rejects/requests supplement.
    Requires agent.runtime to be 'langgraph' for the given task type.
    """
    _check_internal_token(x_internal_token)

    from app.agent_runtime.runtime import ResumeCommand

    command = ResumeCommand.from_dict(payload)
    router = get_contract_runtime_router()

    if router is None:
        raise HTTPException(
            status_code=400,
            detail="RuntimeRouter not initialized. Resume requires LangGraph infrastructure.",
        )

    try:
        result = await router.resume(run_id, command)
        from app.agent_runtime.persistence import MySqlReportStore, MySqlRunStore

        run_store = MySqlRunStore()
        if result.status == "WAITING_HUMAN":
            await run_store.update_run(
                run_id,
                status="WAITING_HUMAN",
                progress=85,
                current_step="等待人工补充或确认",
            )
        elif result.status == "COMPLETED":
            try:
                run = await run_store.get_run(run_id)
                report_store = MySqlReportStore()
                report = await report_store.get_report(run_id)
                if not report:
                    await report_store.save_report(
                        int(run.get("projectId") or run.get("subjectId") or 0),
                        run_id,
                        str(run.get("runType") or "FULFILLMENT_CHECK"),
                        result.artifact or {},
                    )
                await run_store.update_run(
                    run_id,
                    status="COMPLETED",
                    progress=100,
                    current_step="已保存人工确认后的履约核验结果",
                )
            except Exception as exc:
                error_message = f"履约核验报告保存失败: {exc}"[:500]
                logger.exception("Could not persist resumed fulfillment run %s", run_id)
                await run_store.update_run(
                    run_id,
                    status="FAILED",
                    progress=0,
                    error_message=error_message,
                )
                return {
                    "runId": run_id,
                    "status": "FAILED",
                    "artifact": {"artifactError": error_message},
                }
        else:
            await run_store.update_run(
                run_id,
                status="FAILED",
                progress=0,
                error_message=str((result.artifact or {}).get("artifactError") or "履约核验恢复失败")[:500],
            )
        return {
            "runId": run_id,
            "status": result.status,
            "artifact": result.artifact,
        }
    except NotImplementedError:
        raise HTTPException(
            status_code=400,
            detail="Resume is not supported by the current agent runtime. "
                   "Set AGENT_RUNTIME_DEFAULT=langgraph to enable graph-based resume.",
        )
    except Exception as exc:
        logger.exception("Resume failed for run %s", run_id)
        raise HTTPException(status_code=500, detail=str(exc))


@internal_router.post("/agent/evaluations/run")
async def run_evaluation(
    payload: dict,
    x_internal_token: str | None = Header(default=None),
):
    """Fire-and-forget eval run. Returns immediately, runs in background."""
    _check_internal_token(x_internal_token)
    eval_run_id = int(payload.get("evalRunId", 0))
    if not eval_run_id:
        raise HTTPException(status_code=400, detail="evalRunId is required")

    # Spawn background task, return immediately to avoid HTTP timeout
    asyncio.create_task(_run_evaluation_background(eval_run_id))
    return {"evalRunId": eval_run_id, "status": "ACCEPTED", "message": "评测已开始后台执行"}


def _fail_eval_run(eval_run_id: int, error: str) -> None:
    """Mark an eval run as FAILED."""
    try:
        from app.agent_runtime.persistence import _conn
        with _conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE agent_eval_run SET status='FAILED', summary_json=%s, finished_at=NOW() WHERE id=%s",
                    (f'{{"error": "{error}"}}', eval_run_id),
                )
                conn.commit()
    except Exception:
        pass


async def _run_evaluation_background(eval_run_id: int):
    """Background worker: iterate cases, run agent, compute metrics, write results."""
    from app.agent_runtime.persistence import _conn

    temp_case_ids: list[int] = []  # Track temp cases for cleanup

    try:
        # ── Load eval run config ──
        with _conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT id, dataset_id, runtime_engine, features_json FROM agent_eval_run WHERE id=%s",
                    (eval_run_id,),
                )
                run_row = cur.fetchone()
                if not run_row:
                    _fail_eval_run(eval_run_id, "Eval run not found")
                    return
                dataset_id = int(run_row["dataset_id"])
                runtime = str(run_row["runtime_engine"])
                import json as _json_features
                try:
                    features = _json_features.loads(run_row.get("features_json") or "{}")
                except Exception:
                    features = {}
                cur.execute(
                    "SELECT id, case_key, title, contract_type, contract_text, expected_findings_json, should_not_find_json FROM agent_eval_case WHERE dataset_id=%s AND status='ACTIVE'",
                    (dataset_id,),
                )
                cases = cur.fetchall()

        if not cases:
            _fail_eval_run(eval_run_id, "No active cases in dataset")
            return

        logger.info("Eval run %s: %d cases, runtime=%s", eval_run_id, len(cases), runtime)

        per_case_results = []
        success_count = 0

        for idx, case in enumerate(cases):
            case_id = int(case["id"])
            try:
                # Execute a minimal contract review for this case
                from app.agent_runtime.api_models import AgentTaskContext
                router = get_contract_runtime_router()

                # Create temp contract_case for eval context so ContractStore can find clauses
                temp_case_id = 0
                contract_text = str(case.get("contract_text") or "")
                if contract_text.strip():
                    with _conn() as conn:
                        with conn.cursor() as cur:
                            cur.execute(
                                """INSERT INTO contract_case (case_key, title, contract_type, status, counterparty)
                                   VALUES (%s,%s,%s,'MATERIAL_PENDING','评测对方主体')""",
                                (f"EVAL-{eval_run_id}-{idx}", case["title"], case["contract_type"]),
                            )
                            temp_case_id = cur.lastrowid
                            temp_case_ids.append(temp_case_id)
                            cur.execute(
                                """INSERT INTO contract_document (case_id, document_type, file_name, file_path, version, parse_status, content_text)
                                   VALUES (%s,'MAIN',%s,'eval://text',1,'READY',%s)""",
                                (temp_case_id, case["title"] + ".txt", contract_text),
                            )
                            doc_id = cur.lastrowid
                            import re as _re
                            parts = _re.split(r'(?=(?:第[一二三四五六七八九十百千]+[章节条]|\d+[.、．]))', contract_text)
                            for ci, part in enumerate(parts):
                                part = part.strip()
                                if len(part) < 10:
                                    continue
                                cur.execute(
                                    """INSERT INTO contract_clause (document_id, case_id, clause_number, title, content, clause_type)
                                       VALUES (%s,%s,%s,%s,LEFT(%s,8000),'OTHER')""",
                                    (doc_id, temp_case_id, str(ci + 1), part[:80], part),
                                )
                            conn.commit()

                ctx = AgentTaskContext(
                    run_id=eval_run_id * 10000 + idx,
                    project_id=temp_case_id,
                    task_type="CONTRACT_REVIEW",
                    question=f"审查合同: {case['title']}",
                    subject_type="CONTRACT_CASE",
                    subject_id=temp_case_id,
                    project={
                        "id": temp_case_id,
                        "title": case["title"],
                        "contractType": case["contract_type"],
                    },
                    task_input={
                        "evalCaseId": case["case_key"],
                        "features": features,
                    },
                )

                # Set per-run feature overrides via contextvars
                from app.agent_runtime.reranker import _rerank_disabled
                from app.agent_runtime.runtime import (
                    _model_override, _prompt_version_override,
                    _recall_multiplier_override, _recall_min_override, _recall_max_override,
                    _retry_limit_override, _coverage_reflection_disabled, _temperature_override,
                )
                rerank_on = features.get("rerank", True)
                _rerank_disabled.set(not rerank_on)
                _model_override.set(str(features.get("model") or ""))
                _prompt_version_override.set(str(features.get("promptVersion") or ""))
                _recall_multiplier_override.set(int(features.get("recallMultiplier") or 0))
                _recall_min_override.set(int(features.get("recallMin") or 0))
                _recall_max_override.set(int(features.get("recallMax") or 0))
                # P1: targeted retrieval retries; coverage reflection toggle
                _retry_limit_override.set(int(features.get("targetedRetrievalRetries", 1)))
                _coverage_reflection_disabled.set(not features.get("coverageReflection", True))
                # P2: temperature override (0 = use prompt default)
                _temperature_override.set(float(features.get("temperature") or 0))

                result = await router.dispatch_with_mode(ctx, runtime)
                artifact = result.artifact or {}
                findings = artifact.get("findings") or []
                expected_json = case["expected_findings_json"] or "[]"
                import json as _json
                try:
                    expected = _json.loads(expected_json) if isinstance(expected_json, str) else expected_json
                except Exception:
                    expected = []

                # ── Per-case metrics ──────────────────────────────────
                expected_high = [f for f in expected if str(f.get("severity", "")).upper() == "HIGH"]
                actual_high = [f for f in findings if str(f.get("severity", "")).upper() == "HIGH"]
                high_recall = len([h for h in expected_high if any(
                    str(h.get("title", "")).lower() in str(a.get("title", "")).lower()
                    for a in actual_high
                )]) / max(len(expected_high), 1)

                # dualCitationRate: findings with BOTH contract AND policy citations
                dual_cited = sum(
                    1 for f in findings
                    if (f.get("contractCitation") or f.get("contractCitationIds"))
                    and (f.get("policyCitation") or f.get("policyCitationIds"))
                )
                dual_rate = dual_cited / max(len(findings), 1)

                # falsePositives: count findings whose title matches should_not_find substrings
                should_not_json = case.get("should_not_find_json") or "[]"
                try:
                    should_not_list = _json.loads(should_not_json) if isinstance(should_not_json, str) else should_not_json
                except Exception:
                    should_not_list = []
                false_pos = sum(
                    1 for f in findings
                    for s in (should_not_list if isinstance(should_not_list, list) else [])
                    if str(s).lower() in str(f.get("title", "")).lower()
                )

                analysis_mode = artifact.get("analysisMode", "FULL")
                # schema_valid: 1 if report produced structured output (has findings array), 0 otherwise
                schema_valid = 1 if isinstance(findings, list) else 0

                with _conn() as conn:
                    with conn.cursor() as cur:
                        cur.execute("""
                            INSERT INTO agent_eval_result
                            (run_id, case_id, success, high_recall, dual_citation_rate,
                             false_positives, analysis_mode, risk_score, finding_count, result_json)
                            VALUES (%s,%s,1,%s,%s,%s,%s,%s,%s,%s)
                            ON DUPLICATE KEY UPDATE high_recall=VALUES(high_recall),
                                                    dual_citation_rate=VALUES(dual_citation_rate),
                                                    false_positives=VALUES(false_positives),
                                                    analysis_mode=VALUES(analysis_mode),
                                                    risk_score=VALUES(risk_score),
                                                    finding_count=VALUES(finding_count),
                                                    result_json=VALUES(result_json)
                            """, (
                            eval_run_id, case_id,
                            high_recall, dual_rate, false_pos,
                            analysis_mode,
                            artifact.get("riskScore", 0),
                            len(findings),
                            _json.dumps(artifact, ensure_ascii=False, default=str),
                        ))
                        conn.commit()

                per_case_results.append({
                    "caseId": case_id,
                    "highRecall": high_recall,
                    "dualCitationRate": dual_rate,
                    "falsePositives": false_pos,
                    "schemaValid": schema_valid,
                    "analysisMode": analysis_mode,
                })
                success_count += 1
                logger.info("Eval run %s: case %s/%s done (recall=%.2f)", eval_run_id, idx + 1, len(cases), high_recall)

            except Exception as exc:
                logger.error("Eval case %s failed: %s", case_id, exc)
                with _conn() as conn:
                    with conn.cursor() as cur:
                        cur.execute("""
                            INSERT INTO agent_eval_result
                            (run_id, case_id, success, error_message)
                            VALUES (%s,%s,0,%s)
                            ON DUPLICATE KEY UPDATE error_message=VALUES(error_message)
                            """, (eval_run_id, case_id, str(exc)[:500]))
                        conn.commit()

        # Compute aggregate metrics
        if per_case_results:
            n = len(per_case_results)
            avg_recall = sum(r["highRecall"] for r in per_case_results) / n
            avg_dual_cite = sum(r["dualCitationRate"] for r in per_case_results) / n
            avg_false_pos = sum(r["falsePositives"] for r in per_case_results) / n
            schema_valid_count = sum(1 for r in per_case_results if r.get("schemaValid"))
            avg_schema_valid = schema_valid_count / n
            limited_count = sum(1 for r in per_case_results if r.get("analysisMode") == "LIMITED")
            limited_report_rate = limited_count / n
        else:
            avg_recall = 0
            avg_dual_cite = 0
            avg_false_pos = 0
            avg_schema_valid = 0
            limited_report_rate = 0

        import json as _json_summary
        summary = _json_summary.dumps({
            "highRiskRecall": round(avg_recall, 4),
            "dualCitationRate": round(avg_dual_cite, 4),
            "falsePositiveRate": round(avg_false_pos, 4),
            "schemaValidRate": round(avg_schema_valid, 4),
            "limitedReportRate": round(limited_report_rate, 4),
            "caseCount": len(cases),
            "passedCount": success_count,
        }, ensure_ascii=False)

        with _conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    UPDATE agent_eval_run
                    SET status='COMPLETED', high_risk_recall=%s, dual_citation_rate=%s,
                        false_positive_rate=%s, schema_valid_rate=%s,
                        case_count=%s, passed_count=%s, summary_json=%s,
                        finished_at=NOW()
                    WHERE id=%s
                    """, (avg_recall, avg_dual_cite, avg_false_pos, avg_schema_valid, len(cases), success_count, summary, eval_run_id))
                conn.commit()

    except Exception as exc:
        logger.exception("Eval run %s background task failed", eval_run_id)
        _fail_eval_run(eval_run_id, str(exc)[:500])

    finally:
        # Clean up temp eval contract cases
        if temp_case_ids:
            try:
                placeholders = ",".join(["%s"] * len(temp_case_ids))
                with _conn() as conn:
                    with conn.cursor() as cur:
                        cur.execute(
                            f"UPDATE contract_case SET deleted=1 WHERE id IN ({placeholders})",
                            temp_case_ids,
                        )
                        conn.commit()
                logger.info("Cleaned up %d temp eval cases", len(temp_case_ids))
            except Exception:
                pass

    logger.info("Eval run %s completed: recall=%.3f, %d/%d passed",
                eval_run_id, avg_recall, success_count, len(cases))


@kb_router.post("/qa/test")
async def kb_qa_test(request: KbQaRequest):
    return get_kb().qa_test(
        request.message,
        space_id=request.spaceId,
        document_id=request.documentId,
        top_k=request.topK,
    )
