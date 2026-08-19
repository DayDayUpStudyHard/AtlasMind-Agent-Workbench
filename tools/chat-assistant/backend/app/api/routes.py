"""Chat, knowledge-base ingest, and retrieval debug routes."""
from __future__ import annotations

import asyncio
from difflib import SequenceMatcher
import hashlib
import json
import logging
import os
import re
import secrets
import threading
import time
from pathlib import Path
from typing import Any

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
from app.agent_runtime.evaluation.versioning import EVAL_SCORER_VERSION
from app.agent_runtime.evaluation.telemetry import aggregate_telemetry, case_telemetry, stage_telemetry
from app.agent_runtime.evaluation.metrics import build_release_gate

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
_eval_queue: asyncio.Queue[int] | None = None
_eval_worker_task: asyncio.Task | None = None
_eval_active_run_id: int | None = None
_eval_enqueued_ids: set[int] = set()


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

        # Build and register ContractReviewGraph v2 (PRD Phase 3 pilot, §15).
        # Registered under a distinct adapter key so eval runs can force it via
        # runtime_engine="langgraph_v2" — it is NOT the default dispatch target.
        try:
            from app.agent_runtime.graph.review_v2 import build_contract_review_v2_graph
            cr_v2_graph = build_contract_review_v2_graph(checkpointer=checkpointer)
            _contract_runtime_router.register(
                "contract_review_v2",
                GraphAdapter(
                    cr_v2_graph,
                    checkpointer,
                    graph_name="contract_review",
                    graph_version="v2",
                    run_store=run_store,
                ),
            )
            logger.info("Registered contract_review v2 graph adapter (pilot, not default)")
        except Exception as exc:
            logger.warning("contract_review v2 graph init failed: %s", exc)

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
async def chat_send(
    request: ChatRequest,
    x_internal_token: str | None = Header(default=None),
):
    """Stream a RAG answer and persist session messages, trace, hits, and tool steps."""
    _check_internal_token(x_internal_token)

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
        elif result.status == "LIMITED":
            # §7.2: over-budget / coverage-limited runs end LIMITED with
            # their diagnostics — never FAILED, never a false COMPLETED.
            diagnostics = (result.graph_info or {}).get("limitedDiagnostics") or {}
            missing_units = len(diagnostics.get("missingCheckItems") or [])
            report = await report_store.get_report(run_id)
            if not report and result.artifact:
                try:
                    await report_store.save_report(
                        request.project_id or request.subject_id,
                        run_id,
                        request.task_type,
                        result.artifact,
                    )
                except Exception as exc:
                    logger.exception("LIMITED report persist failed for run %s", run_id)
                    await run_store.update_run(
                        run_id,
                        status="FAILED",
                        progress=0,
                        error_message=f"Report persistence failed: {exc}",
                    )
                    return
            await run_store.update_run(
                run_id, status="LIMITED", progress=100,
                current_step=f"范围受限（{missing_units} 项未覆盖，详见运行诊断）",
                limited_diagnostics=diagnostics or None,
            )
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
    """Queue an eval run. A single in-process worker executes runs sequentially."""
    _check_internal_token(x_internal_token)
    eval_run_id = int(payload.get("evalRunId", 0))
    if not eval_run_id:
        raise HTTPException(status_code=400, detail="evalRunId is required")

    queued = _enqueue_eval_run(eval_run_id)
    return {
        "evalRunId": eval_run_id,
        "status": "QUEUED" if queued else "ALREADY_QUEUED",
        "message": "Evaluation queued",
    }


def _enqueue_eval_run(eval_run_id: int) -> bool:
    global _eval_queue, _eval_worker_task
    if _eval_queue is None:
        _eval_queue = asyncio.Queue()
    if eval_run_id == _eval_active_run_id or eval_run_id in _eval_enqueued_ids:
        return False
    _eval_enqueued_ids.add(eval_run_id)
    _eval_queue.put_nowait(eval_run_id)
    _update_eval_progress(
        eval_run_id,
        status="QUEUED",
        current_step="Waiting for evaluation worker",
        queue_position=_eval_queue.qsize(),
    )
    if _eval_worker_task is None or _eval_worker_task.done():
        _eval_worker_task = asyncio.create_task(_eval_worker_loop())
    return True


async def _eval_worker_loop() -> None:
    global _eval_active_run_id
    assert _eval_queue is not None
    while True:
        eval_run_id = await _eval_queue.get()
        _eval_enqueued_ids.discard(eval_run_id)
        _eval_active_run_id = eval_run_id
        try:
            await _run_evaluation_background(eval_run_id)
        finally:
            _eval_active_run_id = None
            _eval_queue.task_done()
        if _eval_queue.empty():
            return


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


def _json_safe(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)


def _update_eval_progress(
    eval_run_id: int,
    *,
    status: str | None = None,
    case_count: int | None = None,
    passed_count: int | None = None,
    current_case_index: int | None = None,
    current_case_key: str | None = None,
    current_step: str | None = None,
    queue_position: int | None = None,
    environment_status: str | None = None,
    environment_snapshot: dict | None = None,
    summary_patch: dict | None = None,
    finished: bool = False,
) -> None:
    from app.agent_runtime.persistence import _conn

    sets: list[str] = []
    params: list[Any] = []
    for column, value in (
        ("status", status),
        ("case_count", case_count),
        ("passed_count", passed_count),
        ("current_case_index", current_case_index),
        ("current_case_key", current_case_key),
        ("current_step", current_step),
        ("queue_position", queue_position),
        ("environment_status", environment_status),
        ("environment_snapshot_json", _json_safe(environment_snapshot) if environment_snapshot is not None else None),
    ):
        if value is not None:
            sets.append(f"{column}=%s")
            params.append(value)
    if status not in (None, "QUEUED"):
        # First driver touch = real start. Rows created by direct DB insert sit
        # QUEUED with started_at NULL; COALESCE keeps a pre-set value if one
        # exists and stamps NOW() on the QUEUED -> first-active transition, so
        # the UI never shows row-creation time as the run's start.
        sets.append("started_at=COALESCE(started_at, NOW())")
    if finished:
        sets.append("finished_at=NOW()")
    if not sets and summary_patch is None:
        return
    with _conn() as conn:
        with conn.cursor() as cur:
            if summary_patch is not None:
                cur.execute("SELECT summary_json FROM agent_eval_run WHERE id=%s", (eval_run_id,))
                row = cur.fetchone() or {}
                try:
                    summary = json.loads(row.get("summary_json") or "{}")
                except Exception:
                    summary = {}
                summary.update(summary_patch)
                sets.append("summary_json=%s")
                params.append(_json_safe(summary))
            params.append(eval_run_id)
            cur.execute(f"UPDATE agent_eval_run SET {', '.join(sets)} WHERE id=%s", params)
            conn.commit()


async def _eval_environment_gate(features: dict) -> dict[str, Any]:
    checked_at = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    snapshot: dict[str, Any] = {
        "environmentStatus": "READY",
        "checkedAt": checked_at,
        "reasons": [],
        "components": {},
    }

    def _component_status(name: str, value: dict | None) -> str:
        status = str((value or {}).get("status") or "unknown").lower()
        snapshot["components"][name] = value or {"status": "unknown"}
        return status

    # External embedding / LLM providers occasionally drop a single health
    # request while remaining usable. Accuracy evaluations must not silently
    # fall back, but a bounded re-probe avoids recording that transient as an
    # entire unusable evaluation run.
    probe_attempts = max(1, min(int(features.get("environmentProbeAttempts", 3)), 3))
    probe: dict[str, Any] = {}
    for attempt in range(probe_attempts):
        probe = await health(probe=True)
        probe_components = probe.get("components") or {}
        if all(
            str((probe_components.get(name) or {}).get("status") or "").lower() == "ok"
            for name in ("llm", "embedding")
        ):
            break
        if attempt + 1 < probe_attempts:
            await asyncio.sleep(0.5 * (attempt + 1))
    snapshot["probeAttempts"] = attempt + 1
    components = probe.get("components") or {}
    hard_fail = False
    for name in ("llm", "embedding"):
        status = _component_status(name, components.get(name))
        if status != "ok":
            hard_fail = True
            snapshot["reasons"].append(f"{name} unavailable")

    retrieval = components.get("elasticsearch") or {}
    retrieval_status = _component_status("elasticsearch", retrieval)
    require_es = bool(features.get("requireElasticsearch") or features.get("requireEs"))
    allow_mysql_fallback = bool(features.get("allowMysqlRetrievalFallback", True))
    if retrieval_status != "ok":
        if require_es or not allow_mysql_fallback:
            hard_fail = True
            snapshot["reasons"].append("elasticsearch unavailable")
        else:
            snapshot["environmentStatus"] = "DEGRADED"
            snapshot["reasons"].append("elasticsearch unavailable; MySQL fallback allowed")

    if hard_fail:
        snapshot["environmentStatus"] = "UNAVAILABLE"
    return snapshot


def _is_infra_error(error: Any) -> bool:
    text = str(error or "").lower()
    return any(token in text for token in (
        "llm connection",
        "llm unreachable",
        "api connection",
        "apiconnection",
        "apierror",
        "embedding api",
        "request timed out",
        "timeout",
        "circuit breaker",
        "connection refused",
        "service unavailable",
    ))


def _eval_task_plan(dataset_type: str) -> list[str]:
    raw = str(dataset_type or "").upper()
    mapping = {
        "CONTRACT_REVIEW": ["CONTRACT_REVIEW"],
        "RISK_REVIEW": ["CONTRACT_REVIEW"],
        "INTAKE": ["CONTRACT_ELEMENT_EXTRACTION"],
        "ELEMENT_EXTRACTION": ["CONTRACT_ELEMENT_EXTRACTION"],
        "CONTRACT_ELEMENT_EXTRACTION": ["CONTRACT_ELEMENT_EXTRACTION"],
        "FULFILLMENT_TIMELINE": ["TIMELINE_EXTRACTION"],
        "TIMELINE_EXTRACTION": ["TIMELINE_EXTRACTION"],
        # Fulfillment verification is evidence-based.  It must first produce
        # the target timeline node from the contract, then verify separately
        # uploaded proof against that node.  Never mix proof text into the
        # contract fixture just to make an evaluation executable.
        "FULFILLMENT_CHECK": ["TIMELINE_EXTRACTION", "FULFILLMENT_CHECK"],
        "FULFILLMENT_VERIFICATION": ["TIMELINE_EXTRACTION", "FULFILLMENT_CHECK"],
        "COMPREHENSIVE": [
            "CONTRACT_ELEMENT_EXTRACTION",
            "TIMELINE_EXTRACTION",
            "CONTRACT_REVIEW",
        ],
    }
    return mapping.get(raw, ["CONTRACT_REVIEW"])


class EvalCaseConfigurationError(ValueError):
    """The case cannot exercise the requested production workflow honestly."""


async def _run_evaluation_background_legacy(eval_run_id: int):
    """Background worker: iterate cases, run agent, compute metrics, write results."""
    from app.agent_runtime.persistence import _conn

    temp_case_ids: list[int] = []  # Track temp cases for cleanup

    def _eval_task_type(value: Any) -> str:
        raw = str(value or "").upper()
        return {
            "INTAKE": "CONTRACT_ELEMENT_EXTRACTION",
            "ELEMENT_EXTRACTION": "CONTRACT_ELEMENT_EXTRACTION",
            "CONTRACT_ELEMENT_EXTRACTION": "CONTRACT_ELEMENT_EXTRACTION",
            "FULFILLMENT_TIMELINE": "TIMELINE_EXTRACTION",
            "TIMELINE_EXTRACTION": "TIMELINE_EXTRACTION",
            "FULFILLMENT_CHECK": "FULFILLMENT_CHECK",
            "COMPREHENSIVE": "CONTRACT_REVIEW",
        }.get(raw, "CONTRACT_REVIEW")

    def _create_eval_agent_run(
        *,
        task_type: str,
        temp_case_id: int,
        title: str,
        case_key: str,
        idx: int,
        features: dict,
    ) -> int:
        import json as _json_run

        with _conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """INSERT INTO agent_run
                       (project_id, run_type, trigger_type, question, status,
                        progress, current_step, input_json, subject_type, subject_id)
                       VALUES (%s,%s,'EVALUATION',%s,'CREATED',
                               0,'Evaluation case queued',%s,'CONTRACT_CASE',%s)""",
                    (
                        temp_case_id,
                        task_type,
                        f"Eval {case_key}: {title}",
                        _json_run.dumps({
                            "evalRunId": eval_run_id,
                            "evalCaseKey": case_key,
                            "evalCaseIndex": idx,
                            "features": features,
                        }, ensure_ascii=False, default=str),
                        temp_case_id,
                    ),
                )
                run_id = int(cur.lastrowid)
                conn.commit()
                return run_id

    def _finish_eval_agent_run(
        run_id: int,
        status: str,
        message: str = "",
        limited_diagnostics: dict | None = None,
    ) -> None:
        try:
            with _conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """UPDATE agent_run
                           SET status=%s,
                               progress=CASE WHEN %s IN ('COMPLETED','LIMITED') THEN 100 ELSE progress END,
                               current_step=%s,
                               error_message=CASE WHEN %s='FAILED' THEN %s ELSE NULL END,
                               limited_diagnostics=COALESCE(%s, limited_diagnostics),
                               finished_at=NOW(),
                               last_heartbeat_at=NOW()
                           WHERE id=%s""",
                        (
                            status,
                            status,
                            message[:120] if message else status,
                            status,
                            message[:4000] if message else None,
                            _json_safe(limited_diagnostics) if limited_diagnostics is not None else None,
                            run_id,
                        ),
                    )
                    conn.commit()
        except Exception:
            logger.exception("Could not finish eval agent run %s", run_id)

    def _record_eval_failure(
        *,
        case_id: int,
        error: str,
        artifact: dict | None = None,
        per_case_results: list,
    ) -> None:
        import json as _json_result

        with _conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO agent_eval_result
                    (run_id, case_id, success, high_recall, dual_citation_rate,
                     false_positives, analysis_mode, risk_score, finding_count,
                     error_message, result_json)
                    VALUES (%s,%s,0,0,0,0,%s,0,0,%s,%s)
                    ON DUPLICATE KEY UPDATE success=VALUES(success),
                                            high_recall=VALUES(high_recall),
                                            dual_citation_rate=VALUES(dual_citation_rate),
                                            false_positives=VALUES(false_positives),
                                            analysis_mode=VALUES(analysis_mode),
                                            risk_score=VALUES(risk_score),
                                            finding_count=VALUES(finding_count),
                                            error_message=VALUES(error_message),
                                            result_json=VALUES(result_json)
                    """, (
                    eval_run_id,
                    case_id,
                    str((artifact or {}).get("analysisMode") or "FAILED")[:32],
                    error[:500],
                    _json_result.dumps(artifact or {"artifactError": error}, ensure_ascii=False, default=str),
                ))
                conn.commit()

        per_case_results.append({
            "caseId": case_id,
            "highRecall": 0,
            "dualCitationRate": 0,
            "falsePositives": 0,
            "schemaValid": 0,
            "analysisMode": "FAILED",
        })

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
                eval_case_timeout_seconds = max(
                    60,
                    int(features.get("caseTimeoutSeconds") or 900),
                )
                cur.execute(
                    "SELECT id, case_key, title, contract_type, contract_text, expected_findings_json, should_not_find_json FROM agent_eval_case WHERE dataset_id=%s AND status='ACTIVE'",
                    (dataset_id,),
                )
                cases = cur.fetchall()
                cur.execute(
                    "SELECT contract_type FROM agent_eval_dataset WHERE id=%s",
                    (dataset_id,),
                )
                dataset_row = cur.fetchone()

        if not cases:
            _fail_eval_run(eval_run_id, "No active cases in dataset")
            return

        if runtime == "legacy":
            # Fail the whole run up front instead of one cryptic failure per
            # case: the legacy pipeline cannot produce extraction artifacts.
            from app.agent_runtime.runtime import is_legacy_task_supported

            probe_task = _eval_task_type(
                str((dataset_row or {}).get("contract_type") or "CONTRACT_REVIEW")
            )
            if not is_legacy_task_supported(probe_task):
                _fail_eval_run(
                    eval_run_id,
                    f"传统流水线引擎不支持任务类型 {probe_task}，请改用 LangGraph 引擎重新发起",
                )
                return

        with _conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE agent_eval_run SET case_count=%s, passed_count=0 WHERE id=%s",
                    (len(cases), eval_run_id),
                )
                conn.commit()

        logger.info("Eval run %s: %d cases, runtime=%s", eval_run_id, len(cases), runtime)

        per_case_results = []
        success_count = 0

        for idx, case in enumerate(cases):
            case_id = int(case["id"])
            eval_agent_run_id = 0
            try:
                # Execute a minimal contract review for this case
                from app.agent_runtime.api_models import AgentTaskContext
                router = get_contract_runtime_router()
                task_type = _eval_task_type(case.get("contract_type"))

                # Create temp contract_case for eval context so ContractStore can find clauses
                temp_case_id = 0
                contract_text = str(case.get("contract_text") or "")
                if contract_text.strip():
                    with _conn() as conn:
                        with conn.cursor() as cur:
                            cur.execute(
                                """INSERT INTO contract_case
                                   (case_key, title, contract_type, status, counterparty, is_evaluation)
                                   VALUES (%s,%s,%s,'MATERIAL_PENDING','评测对方主体',1)""",
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

                eval_agent_run_id = _create_eval_agent_run(
                    task_type=task_type,
                    temp_case_id=temp_case_id,
                    title=str(case.get("title") or ""),
                    case_key=str(case.get("case_key") or ""),
                    idx=idx,
                    features=features,
                )

                ctx = AgentTaskContext(
                    run_id=eval_agent_run_id,
                    project_id=temp_case_id,
                    task_type=task_type,
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

                result = await asyncio.wait_for(
                    router.dispatch_with_mode(ctx, runtime),
                    timeout=eval_case_timeout_seconds,
                )
                artifact = result.artifact or {}
                findings = artifact.get("findings") or []
                if not _is_scoreable_eval_result(
                    result,
                    artifact,
                    findings,
                    require_findings=True,
                ):
                    error = str(
                        artifact.get("artifactError")
                        or f"Agent runtime ended with status {result.status}"
                    )
                    _finish_eval_agent_run(eval_agent_run_id, "FAILED", error)
                    _record_eval_failure(
                        case_id=case_id,
                        error=error,
                        artifact=artifact,
                        per_case_results=per_case_results,
                    )
                    logger.warning(
                        "Eval run %s: case %s/%s failed (%s)",
                        eval_run_id, idx + 1, len(cases), error,
                    )
                    continue
                _finish_eval_agent_run(
                    eval_agent_run_id,
                    result.status,
                    "Evaluation case completed" if result.status == "COMPLETED"
                    else "Evaluation case completed with limited coverage",
                    limited_diagnostics=(result.graph_info or {}).get("limitedDiagnostics")
                    if result.status == "LIMITED" else None,
                )
                # ── Per-case metrics: shared scorer registry (same entry as
                # the LangGraph worker — no duplicate scoring logic) ─────
                import json as _json
                score = _score_eval_artifact(case, artifact, task_type)
                high_recall = score["highRecall"]
                dual_rate = score["dualCitationRate"]
                false_pos = score["falsePositives"]
                analysis_mode = score["analysisMode"]
                schema_valid = score["schemaValid"]

                with _conn() as conn:
                    with conn.cursor() as cur:
                        cur.execute("""
                            INSERT INTO agent_eval_result
                            (run_id, case_id, success, high_recall, dual_citation_rate,
                             false_positives, analysis_mode, risk_score, finding_count,
                             error_message, result_json)
                            VALUES (%s,%s,1,%s,%s,%s,%s,%s,%s,NULL,%s)
                            ON DUPLICATE KEY UPDATE success=VALUES(success),
                                                    high_recall=VALUES(high_recall),
                                                    dual_citation_rate=VALUES(dual_citation_rate),
                                                    false_positives=VALUES(false_positives),
                                                    analysis_mode=VALUES(analysis_mode),
                                                    risk_score=VALUES(risk_score),
                                                    finding_count=VALUES(finding_count),
                                                    error_message=VALUES(error_message),
                                                    result_json=VALUES(result_json)
                            """, (
                            eval_run_id, case_id,
                            high_recall, dual_rate, false_pos,
                            analysis_mode,
                            score["riskScore"],
                            score["findingCount"],
                            _json.dumps(artifact, ensure_ascii=False, default=str),
                        ))
                        conn.commit()

                _finish_eval_agent_run(eval_agent_run_id, "COMPLETED", "Evaluation case completed")
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
                if eval_agent_run_id:
                    _finish_eval_agent_run(eval_agent_run_id, "FAILED", str(exc))
                _record_eval_failure(
                    case_id=case_id,
                    error=str(exc),
                    artifact={"artifactError": str(exc)},
                    per_case_results=per_case_results,
                )

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
            failed_count = n - success_count
        else:
            avg_recall = 0
            avg_dual_cite = 0
            avg_false_pos = 0
            avg_schema_valid = 0
            limited_report_rate = 0
            limited_count = 0
            failed_count = 0

        if success_count == 0:
            eval_status = "FAILED"
        elif failed_count > 0 or limited_count > 0:
            eval_status = "DEGRADED"
        else:
            eval_status = "COMPLETED"

        import json as _json_summary
        summary_payload = {
            "highRiskRecall": round(avg_recall, 4),
            "dualCitationRate": round(avg_dual_cite, 4),
            "falsePositiveRate": round(avg_false_pos, 4),
            "schemaValidRate": round(avg_schema_valid, 4),
            "limitedReportRate": round(limited_report_rate, 4),
            "caseCount": len(cases),
            "passedCount": success_count,
            "failedCount": failed_count,
            "limitedCount": limited_count,
            "resultValid": eval_status == "COMPLETED",
        }
        summary_payload["releaseGate"] = build_release_gate(summary_payload, status=eval_status)
        summary = _json_summary.dumps(summary_payload, ensure_ascii=False)

        with _conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    UPDATE agent_eval_run
                    SET status=%s, high_risk_recall=%s, dual_citation_rate=%s,
                        false_positive_rate=%s, schema_valid_rate=%s,
                        case_count=%s, passed_count=%s, summary_json=%s,
                        finished_at=NOW()
                    WHERE id=%s
                    """, (eval_status, avg_recall, avg_dual_cite, avg_false_pos,
                          avg_schema_valid, len(cases), success_count, summary, eval_run_id))
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


def _record_eval_result(eval_run_id: int, case_id: int, row: dict[str, Any]) -> None:
    from app.agent_runtime.persistence import _conn

    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO agent_eval_result
                (run_id, case_id, success, high_recall, dual_citation_rate,
                 false_positives, analysis_mode, risk_score, finding_count,
                 error_message, result_json, schema_valid_rate)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON DUPLICATE KEY UPDATE success=VALUES(success),
                                        high_recall=VALUES(high_recall),
                                        dual_citation_rate=VALUES(dual_citation_rate),
                                        false_positives=VALUES(false_positives),
                                        analysis_mode=VALUES(analysis_mode),
                                        risk_score=VALUES(risk_score),
                                        finding_count=VALUES(finding_count),
                                        error_message=VALUES(error_message),
                                        result_json=VALUES(result_json),
                                        schema_valid_rate=VALUES(schema_valid_rate)
                """, (
                eval_run_id,
                case_id,
                1 if row.get("success") else 0,
                float(row.get("highRecall") or 0),
                float(row.get("dualCitationRate") or 0),
                int(row.get("falsePositives") or 0),
                str(row.get("analysisMode") or "FAILED")[:32],
                float(row.get("riskScore") or 0),
                int(row.get("findingCount") or 0),
                str(row.get("error") or "")[:500] or None,
                _json_safe(row.get("artifact") or row),
                float(row.get("schemaValid") or 0),
            ))
            conn.commit()


_EVAL_SCENARIO_TYPE_NORMALIZATION = {
    # Seed data and the admin UI use GOODS_PROCUREMENT; rule sets, clause
    # inventories, and intake extraction all key off GOODS_PURCHASE.
    "GOODS_PROCUREMENT": "GOODS_PURCHASE",
}

_EVAL_BUSINESS_TYPES = {
    "SERVICE_PROCUREMENT", "GOODS_PURCHASE", "NDA",
    "ENGINEERING_EPC", "SOFTWARE_IT", "OPS_MAINTENANCE", "MIXED", "OTHER",
}
_EVAL_FIXTURE_CHUNKING_VERSION = "eval-split-v3"


def _eval_business_contract_type(case: dict[str, Any]) -> str:
    """Derive the business contract type for an eval case.

    Eval cases store the dataset task type (CONTRACT_REVIEW/INTAKE/...) in the
    ``contract_type`` column; the business scenario lives in ``scenario``.
    Rule-set selection, mandatory-clause inventories, and policy retrieval all
    key off the business type, so prefer the scenario and normalize its
    spelling to the canonical token.
    """
    scenario = str(case.get("scenario") or "").strip().upper()
    candidate = _EVAL_SCENARIO_TYPE_NORMALIZATION.get(scenario, scenario)
    if candidate in _EVAL_BUSINESS_TYPES:
        return candidate
    raw = str(case.get("contract_type") or "").strip().upper()
    candidate = _EVAL_SCENARIO_TYPE_NORMALIZATION.get(raw, raw)
    if candidate in _EVAL_BUSINESS_TYPES:
        return candidate
    return "OTHER"


def _eval_fixture_key(case: dict[str, Any]) -> tuple[str, str]:
    """Stable cache key for reusable evaluation contract fixtures."""
    contract_text = str(case.get("contract_text") or "")
    payload = {
        "contractTextHash": hashlib.sha256(contract_text.encode("utf-8")).hexdigest(),
        "title": str(case.get("title") or ""),
        "businessType": _eval_business_contract_type(case),
        "embeddingModel": str(settings.embedding_model or ""),
        "embeddingDim": int(settings.embedding_dim or 0),
        "chunkingVersion": _EVAL_FIXTURE_CHUNKING_VERSION,
    }
    # A fulfillment fixture owns uploaded evidence as well as its contract.
    # Keeping that payload in the key prevents one case's proof material from
    # leaking into another case that happens to use the same contract text.
    # ``contract_type`` is the business scenario (or legacy ``OTHER``), while
    # the task purpose belongs to the parent dataset.  The worker injects it
    # before fixture construction so evidence-bearing fulfillment cases do not
    # share a cache entry merely because their contract text is identical.
    if str(case.get("evaluation_dataset_type") or case.get("contract_type") or "").upper() in {
        "FULFILLMENT_CHECK", "FULFILLMENT_VERIFICATION",
    }:
        payload["fulfillmentEvidence"] = str(case.get("fulfillment_evidence_json") or "")
        payload["timelineSelector"] = str(case.get("target_timeline_selector_json") or "")
    digest = hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()
    return f"EVAL-FIX-{digest[:40]}", digest


def _eval_fixture_intake_metadata(contract_text: str) -> dict[str, Any]:
    """Seed an evaluation fixture with the deterministic intake facts.

    Production contracts receive these fields during document intake. Evaluation
    fixtures bypass that workflow for speed, so they must explicitly carry the
    same deterministic facts before the extraction graph treats base identity
    as immutable. This does not call an LLM or use expected-answer data.
    """
    from app.agent_runtime.contract_intake_extractor import deterministic_hints

    hints = deterministic_hints(contract_text, "evaluation.txt")

    def value(key: str) -> Any:
        item = hints.get(key) or {}
        return item.get("value") if isinstance(item, dict) else None

    return {
        "our_entity": value("partyA"),
        "counterparty": value("partyB") or "Evaluation Counterparty",
        "amount": value("amount"),
        "currency": value("currency") or "CNY",
        "signed_date": value("signedDate"),
        "effective_date": value("effectiveDate"),
        "expiry_date": value("expiryDate"),
    }


def _eval_fixture_ready(cur, case_id: int) -> bool:
    """Return true when DB chunks and the latest ES indexing pass are reusable."""
    cur.execute(
        """SELECT COUNT(*) AS total,
                  SUM(CASE WHEN embedding_status IN ('DONE','SKIPPED') THEN 1 ELSE 0 END) AS embedded,
                  SUM(CASE WHEN index_status='DONE' THEN 1 ELSE 0 END) AS indexed,
                  MAX(document_id) AS document_id
           FROM contract_clause_chunk
           WHERE case_id=%s""",
        (case_id,),
    )
    row = cur.fetchone() or {}
    total = int(row.get("total") or 0)
    if total <= 0:
        return False
    embedded = int(row.get("embedded") or 0)
    indexed = int(row.get("indexed") or 0)
    if embedded < total:
        return False
    # MySQL keyword retrieval remains usable when ES is unavailable, but when
    # ES is available the fixture should already have a ready private index.
    try:
        es = ESService()
        if es.ping():
            if indexed < total:
                return False
            document_id = int(row.get("document_id") or 0)
            if document_id:
                response = es.client.count(
                    index=es.contract_index,
                    body={"query": {"term": {"document_id": document_id}}},
                )
                if int(response.get("count") or 0) < total:
                    return False
    except Exception:
        return False
    return True


def _eval_expected_dimensions(case: dict[str, Any]) -> list[str]:
    """Distinct risk dimensions from expected_findings_json (normalized via _risk_dimension)."""
    try:
        expected = json.loads(case.get("expected_findings_json") or "[]")
    except Exception:
        return []
    dims: list[str] = []
    for item in expected if isinstance(expected, list) else []:
        dim = _risk_dimension(item if isinstance(item, dict) else {})
        if dim and dim not in dims:
            dims.append(dim)
    return dims


def _create_eval_temp_case(
    eval_run_id: int,
    case: dict[str, Any],
    idx: int,
    temp_case_ids: list[int],
    reuse_stats: list[int] | None = None,
) -> int:
    from app.agent_runtime.persistence import _conn
    from app.agent_runtime.contract_document_parser import (
        _index_contract_chunks,
        _iter_clause_chunks,
        classify_clause,
        split_contract_text,
    )

    contract_text = str(case.get("contract_text") or "")
    fixture_key, fixture_hash = _eval_fixture_key(case)
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT id
                   FROM contract_case
                   WHERE case_key=%s AND is_evaluation=1 AND deleted=0
                   ORDER BY id DESC LIMIT 1""",
                (fixture_key,),
            )
            cached = cur.fetchone()
            if cached:
                cached_case_id = int(cached["id"])
                if _eval_fixture_ready(cur, cached_case_id):
                    # PRD Phase 8 task 2: the text-hash fixture cache reused
                    # the existing case — no re-split, no embedding/index
                    # rebuild. The run summary reports the reuse count.
                    if reuse_stats is not None:
                        reuse_stats.append(1)
                    logger.info(
                        "Eval run %s case %s/%s reusing fixture case %s (%s)",
                        eval_run_id, idx + 1, case.get("case_key") or case.get("id"), cached_case_id, fixture_hash[:12],
                    )
                    return cached_case_id
                cur.execute(
                    """SELECT id FROM contract_document
                       WHERE case_id=%s AND parse_status='READY'
                       ORDER BY version DESC, id DESC LIMIT 1""",
                    (cached_case_id,),
                )
                cached_doc = cur.fetchone()
                if cached_doc:
                    conn.commit()
                    _index_contract_chunks(cur, None, int(cached_doc["id"]), commit_callback=conn.commit)
                    if _eval_fixture_ready(cur, cached_case_id):
                        logger.info(
                            "Eval run %s case %s/%s repaired fixture case %s (%s)",
                            eval_run_id, idx + 1, case.get("case_key") or case.get("id"), cached_case_id, fixture_hash[:12],
                        )
                        return cached_case_id
                cur.execute(
                    "UPDATE contract_case SET deleted=1, case_key=%s WHERE id=%s",
                    (f"EVAL-STALE-{cached_case_id}-{fixture_hash[:24]}", cached_case_id),
                )
                conn.commit()

            intake_metadata = _eval_fixture_intake_metadata(contract_text)
            cur.execute(
                """INSERT INTO contract_case
                   (case_key, title, contract_type, status, our_entity, counterparty,
                    amount, currency, signed_date, effective_date, expiry_date, our_side,
                    description, is_evaluation)
                   VALUES (%s,%s,%s,'MATERIAL_PENDING',%s,%s,%s,%s,%s,%s,%s,'A',%s,1)""",
                (
                    fixture_key,
                    case.get("title") or "",
                    _eval_business_contract_type(case),
                    intake_metadata["our_entity"],
                    intake_metadata["counterparty"],
                    intake_metadata["amount"],
                    intake_metadata["currency"],
                    intake_metadata["signed_date"],
                    intake_metadata["effective_date"],
                    intake_metadata["expiry_date"],
                    json.dumps({
                        "evalFixture": True,
                        "evalFixtureHash": fixture_hash,
                        "evalCaseId": int(case.get("id") or 0),
                        "evalCaseKey": str(case.get("case_key") or ""),
                        "chunkingVersion": _EVAL_FIXTURE_CHUNKING_VERSION,
                        "embeddingModel": settings.embedding_model,
                        "embeddingDim": settings.embedding_dim,
                    }, ensure_ascii=False),
                ),
            )
            temp_case_id = int(cur.lastrowid)
            if contract_text.strip():
                content_hash = hashlib.sha256(contract_text.encode("utf-8")).hexdigest()
                cur.execute(
                    """INSERT INTO contract_document
                       (case_id, document_type, file_name, file_path, version, parse_status, content_hash, content_text)
                       VALUES (%s,'MAIN',%s,%s,1,'READY',%s,%s)""",
                    (
                        temp_case_id,
                        str(case.get("title") or "evaluation") + ".txt",
                        f"eval://fixture/{fixture_hash}",
                        content_hash,
                        contract_text,
                    ),
                )
                doc_id = int(cur.lastrowid)
                clauses = _split_eval_contract_clauses(
                    contract_text,
                    split_contract_text=split_contract_text,
                    classify_clause=classify_clause,
                )
                for ci, clause in enumerate(clauses):
                    content = str(clause.get("content") or "").strip()
                    if len(content) < 10:
                        continue
                    cur.execute(
                        """INSERT INTO contract_clause
                           (document_id, case_id, clause_number, title, content, clause_type)
                           VALUES (%s,%s,%s,%s,LEFT(%s,8000),%s)""",
                        (
                            doc_id,
                            temp_case_id,
                            str(clause.get("clauseNumber") or ci + 1),
                            str(clause.get("title") or content[:80])[:256],
                            content,
                            str(clause.get("clauseType") or classify_clause(content)),
                        ),
                    )
                    clause_id = int(cur.lastrowid)
                    for chunk_index, chunk_text in enumerate(_iter_clause_chunks(content)):
                        content_hash = hashlib.sha256(chunk_text.encode("utf-8")).hexdigest()
                        cur.execute(
                            """INSERT INTO contract_clause_chunk
                               (case_id, document_id, clause_id, clause_number, chunk_index,
                                chunk_text, source_page, content_hash, embedding_status, index_status)
                               VALUES (%s,%s,%s,%s,%s,%s,1,%s,'PENDING','PENDING')""",
                            (
                                temp_case_id,
                                doc_id,
                                clause_id,
                                str(clause.get("clauseNumber") or ci + 1),
                                chunk_index,
                                chunk_text,
                                content_hash,
                            ),
                        )
            conn.commit()
            if contract_text.strip():
                _index_contract_chunks(cur, None, doc_id, commit_callback=conn.commit)
                logger.info(
                    "Eval run %s case %s/%s built fixture case %s (%s)",
                    eval_run_id, idx + 1, case.get("case_key") or case.get("id"), temp_case_id, fixture_hash[:12],
                )
            return temp_case_id


def _split_eval_contract_clauses(
    contract_text: str,
    *,
    split_contract_text=None,
    classify_clause=None,
) -> list[dict[str, Any]]:
    if split_contract_text is None or classify_clause is None:
        from app.agent_runtime.contract_document_parser import classify_clause, split_contract_text

    clauses = split_contract_text(contract_text)
    if len(clauses) > 1:
        return clauses

    lines = [line.strip() for line in re.split(r"[\r\n]+", contract_text) if line.strip()]
    if len(lines) <= 1:
        lines = [
            segment.strip()
            for segment in re.split(r"(?<=[。；;])", contract_text)
            if segment.strip()
        ]
    if len(lines) <= 1:
        content = contract_text.strip()
        return [{
            "clauseNumber": "1",
            "title": content[:80],
            "content": content,
            "clauseType": classify_clause(content),
        }] if content else []

    return [
        {
            "clauseNumber": str(index),
            "title": line[:80],
            "content": line,
            "clauseType": classify_clause(line),
        }
        for index, line in enumerate(lines, 1)
        if len(line) >= 4
    ]


def _cleanup_eval_search_indexes(temp_case_ids: list[int]) -> None:
    if not temp_case_ids:
        return
    try:
        from app.agent_runtime.persistence import _conn
        from app.services.es_service import ESService

        placeholders = ",".join(["%s"] * len(temp_case_ids))
        with _conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"SELECT id FROM contract_document WHERE case_id IN ({placeholders})",
                    temp_case_ids,
                )
                document_ids = [int(row["id"]) for row in cur.fetchall()]
        es = ESService()
        for document_id in document_ids:
            es.delete_contract_document(document_id)
    except Exception:
        logger.exception("Could not clean evaluation search indexes")


def _latest_eval_timeline_node_id(temp_case_id: int) -> int:
    from app.agent_runtime.persistence import _conn

    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id FROM contract_timeline_node WHERE case_id=%s ORDER BY id LIMIT 1",
                (temp_case_id,),
            )
            row = cur.fetchone()
            return int(row["id"]) if row else 0


def _eval_json_object(raw: Any, field_name: str) -> dict[str, Any]:
    if not str(raw or "").strip():
        return {}
    try:
        value = json.loads(str(raw))
    except json.JSONDecodeError as exc:
        raise EvalCaseConfigurationError(f"{field_name} must be valid JSON") from exc
    if not isinstance(value, dict):
        raise EvalCaseConfigurationError(f"{field_name} must be a JSON object")
    return value


def _eval_json_list(raw: Any, field_name: str) -> list[dict[str, Any]]:
    if not str(raw or "").strip():
        return []
    try:
        value = json.loads(str(raw))
    except json.JSONDecodeError as exc:
        raise EvalCaseConfigurationError(f"{field_name} must be valid JSON") from exc
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        raise EvalCaseConfigurationError(f"{field_name} must be a JSON array of objects")
    return [dict(item) for item in value]


def _eval_fulfillment_input(case: dict[str, Any]) -> dict[str, Any]:
    """Read the explicit non-contract inputs needed by a fulfillment case."""
    selector = _eval_json_object(
        case.get("target_timeline_selector_json"), "targetTimelineSelectorJson"
    )
    evidence = _eval_json_list(
        case.get("fulfillment_evidence_json"), "fulfillmentEvidenceJson"
    )
    expected_judgements = _eval_json_list(
        case.get("expected_judgements_json"), "expectedJudgementsJson"
    )
    manual_result = str(case.get("expected_manual_result") or "").upper()
    if not selector:
        raise EvalCaseConfigurationError(
            "FULFILLMENT_CHECK requires targetTimelineSelectorJson; refusing arbitrary latest node"
        )
    if not evidence:
        raise EvalCaseConfigurationError(
            "FULFILLMENT_CHECK requires fulfillmentEvidenceJson; proof must be independent from contract text"
        )
    if manual_result not in {"SATISFIED", "NOT_SATISFIED", "PENDING"}:
        raise EvalCaseConfigurationError(
            "FULFILLMENT_CHECK requires expectedManualResult: SATISFIED, NOT_SATISFIED, or PENDING"
        )
    return {
        "selector": selector,
        "evidence": evidence,
        "expectedJudgements": expected_judgements,
        "expectedManualResult": manual_result,
    }


def _select_eval_timeline_node_id(temp_case_id: int, selector: dict[str, Any]) -> int:
    """Select one extracted node using an auditable semantic selector."""
    clauses: list[str] = ["case_id=%s", "(source='AGENT_FINAL' OR manual_override=1)"]
    params: list[Any] = [temp_case_id]
    fields = {
        "nodeType": "node_type",
        "date": "node_date",
        "labelContains": "label",
        "conditionContains": "condition_text",
    }
    for key, column in fields.items():
        value = str(selector.get(key) or "").strip()
        if not value:
            continue
        if key.endswith("Contains"):
            clauses.append(f"{column} LIKE %s")
            params.append(f"%{value}%")
        else:
            clauses.append(f"{column}=%s")
            params.append(value.upper() if key == "nodeType" else value)
    if len(clauses) == 2:
        raise EvalCaseConfigurationError("targetTimelineSelectorJson has no supported selector field")
    from app.agent_runtime.persistence import _conn

    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"SELECT id FROM contract_timeline_node WHERE {' AND '.join(clauses)} ORDER BY id LIMIT 2",
                params,
            )
            rows = cur.fetchall() or []
    if len(rows) != 1:
        raise EvalCaseConfigurationError(
            f"timeline selector must match exactly one final node; matched {len(rows)}"
        )
    return int(rows[0]["id"])


def _seed_eval_fulfillment_evidence(
    temp_case_id: int, timeline_node_id: int, evidence: list[dict[str, Any]]
) -> list[int]:
    """Attach immutable synthetic proof documents to the selected node."""
    from app.agent_runtime.persistence import _conn

    document_ids: list[int] = []
    with _conn() as conn:
        with conn.cursor() as cur:
            # contract_document.version is unique per case, not per document
            # type.  The main contract has normally consumed version 1, and a
            # fulfillment case may attach several proof documents.
            cur.execute(
                "SELECT COALESCE(MAX(version), 0) AS max_version FROM contract_document WHERE case_id=%s",
                (temp_case_id,),
            )
            next_version = int((cur.fetchone() or {}).get("max_version") or 0)
            for index, item in enumerate(evidence, 1):
                content = str(item.get("content") or item.get("text") or "").strip()
                if not content:
                    raise EvalCaseConfigurationError(
                        f"fulfillmentEvidenceJson[{index - 1}] requires content"
                    )
                content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
                file_name = str(item.get("fileName") or f"evaluation-proof-{index}.txt")[:255]
                cur.execute(
                    """SELECT id FROM contract_document
                       WHERE case_id=%s AND document_type='FULFILLMENT_EVIDENCE'
                         AND content_hash=%s AND COALESCE(deleted,0)=0
                       ORDER BY id DESC LIMIT 1""",
                    (temp_case_id, content_hash),
                )
                row = cur.fetchone()
                if row:
                    document_id = int(row["id"])
                else:
                    next_version += 1
                    cur.execute(
                        """INSERT INTO contract_document
                           (case_id, document_type, file_name, file_path, version, parse_status,
                            content_hash, content_text)
                           VALUES (%s,'FULFILLMENT_EVIDENCE',%s,%s,%s,'READY',%s,%s)""",
                        (
                            temp_case_id,
                            file_name,
                            f"eval://fulfillment-evidence/{content_hash}",
                            next_version,
                            content_hash,
                            content,
                        ),
                    )
                    document_id = int(cur.lastrowid)
                document_ids.append(document_id)
                cur.execute(
                    """INSERT INTO contract_timeline_evidence_link
                       (case_id, timeline_node_id, document_id, check_id, link_source,
                        relation_type, evidence_version, evidence_hash, deleted)
                       VALUES (%s,%s,%s,NULL,'EVALUATION','FULFILLMENT_EVIDENCE',1,%s,0)
                       ON DUPLICATE KEY UPDATE deleted=0, evidence_hash=VALUES(evidence_hash)""",
                    (temp_case_id, timeline_node_id, document_id, content_hash),
                )
            conn.commit()
    return document_ids


def _set_eval_feature_overrides(features: dict) -> None:
    from app.agent_runtime.reranker import _rerank_disabled, reset_rerank_observation
    from app.agent_runtime.runtime import (
        _coverage_reflection_disabled,
        _model_override,
        _prompt_version_override,
        _recall_max_override,
        _recall_min_override,
        _recall_multiplier_override,
        _retry_limit_override,
        _temperature_override,
        _v2_analysis_concurrency,
        _v2_skip_llm_on_no_evidence,
    )

    reset_rerank_observation()
    _rerank_disabled.set(not features.get("rerank", True))
    _model_override.set(str(features.get("model") or ""))
    _prompt_version_override.set(str(features.get("promptVersion") or ""))
    _recall_multiplier_override.set(int(features.get("recallMultiplier") or 0))
    _recall_min_override.set(int(features.get("recallMin") or 0))
    _recall_max_override.set(int(features.get("recallMax") or 0))
    _retry_limit_override.set(int(features.get("targetedRetrievalRetries", 1)))
    _coverage_reflection_disabled.set(not features.get("coverageReflection", True))
    _temperature_override.set(float(features.get("temperature") or 0))
    _v2_analysis_concurrency.set(max(1, min(8, int(features.get("v2AnalysisConcurrency") or 3))))
    _v2_skip_llm_on_no_evidence.set(bool(features.get("v2SkipLlmOnNoEvidence", True)))


def _normalize_eval_text(value: Any) -> str:
    return re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", str(value or "").lower())


def _eval_bigrams(value: str) -> set[str]:
    return {value[index:index + 2] for index in range(max(0, len(value) - 1))}


# Expected findings carry riskDimension; artifact findings carry domainKey
# (riskDimension is always empty there) plus a coarse clauseType. Both
# vocabularies must land on one canonical dimension per bucket family.
_EXPECTED_DIMENSION_ALIASES = {
    "COMPLIANCE": "DATA",  # corpus uses COMPLIANCE/DATA interchangeably
}
_ACTUAL_DIMENSION_BUCKETS = {
    # payment family
    "PRICE_PAYMENT_TAX": "PAYMENT",
    "PAYMENT_SECURITY": "PAYMENT",
    "PAYMENT_SECURITY_AND_WORK_STOPPAGE": "PAYMENT",
    "PAYMENT_TERMS_RISK": "PAYMENT",
    "PAYMENT_TERMS_ACCURACY": "PAYMENT",
    "PRICE_ADJUSTMENT_MECHANISM": "PAYMENT",
    "EARLY_TERMINATION_PAYMENT": "PAYMENT",
    # acceptance family
    "SCOPE_DELIVERY_ACCEPTANCE": "ACCEPTANCE",
    "ACCEPTANCE_MECHANISM": "ACCEPTANCE",
    "ACCEPTANCE_INSPECTION": "ACCEPTANCE",
    "ACCEPTANCE_CRITERIA": "ACCEPTANCE",
    "ACCEPTANCE_LOOP_GOVERNANCE": "ACCEPTANCE",
    "SPECIFICATION_CONFLICT_RESOLUTION": "ACCEPTANCE",
    # termination family
    "TERM_CHANGE_TERMINATION": "TERMINATION",
    "TERMINATION_RIGHTS": "TERMINATION",
    # liability family
    "LIABILITY_REMEDIES": "LIABILITY",
    "PRODUCT_LIABILITY": "LIABILITY",
    # ip / confidentiality family (corpus files employment restrictions here too)
    "CONFIDENTIALITY_DATA_IP": "IP",
    "IP_OWNERSHIP_TRANSFER": "IP",
    "IP_TRANSFER_VALIDITY": "IP",
    "IP_OWNERSHIP": "IP",
    "IP_OWNERSHIP_LICENSE": "IP",
    "IP_OWNERSHIP_LICENSES": "IP",
    "IP_OWNERSHIP_LICENSE_SCOPE": "IP",
    "IP_OWNERSHIP_AND_MORAL_RIGHTS": "IP",
    "INTELLECTUAL_PROPERTY": "IP",
    "CONFIDENTIALITY": "IP",
    # force majeure family
    "FORCE_MAJEURE": "FORCE_MAJEURE",
    "FORCE_MAJEURE_RISK": "FORCE_MAJEURE",
    "FORCE_MAJEURE_RISK_ALLOCATION": "FORCE_MAJEURE",
    # data protection family
    "DATA_PROTECTION": "DATA",
    "DATA_PROTECTION_SECURITY": "DATA",
    "DATA_PRIVACY": "DATA",
    "PERSONAL_INFORMATION_PROTECTION": "DATA",
    "HEALTHCARE_DATA_REGULATION": "DATA",
    "HEALTH_DATA_REGULATION": "DATA",
    "DATA_PRIVACY_FOOD_INDUSTRY": "DATA",
    "CYBERSECURITY": "DATA",
    "DATA_TRANSFER_PRIVACY": "DATA",
    # change family
    "CHANGE_MANAGEMENT": "CHANGE",
    # dispute family
    "DISPUTE_RESOLUTION_FAIRNESS": "DISPUTE",
    "JURISDICTION_PROCEDURE": "DISPUTE",
    "CROSS_BORDER_LAW_JURISDICTION": "DISPUTE",
    # party family
    "PARTY_AUTHORITY": "PARTY",
    "PARTY_IDENTITY_VERIFICATION": "PARTY",
}


def _risk_dimension(value: dict[str, Any]) -> str:
    # domainKey before clauseType on the actual side: clauseType=OTHER masked
    # the specific domainKey on nearly every artifact finding (all 364 in the
    # eval corpus). Expected findings use riskDimension, but may carry
    # domainKey-style values, so one combined map normalizes both sides.
    raw = str(
        value.get("riskDimension") or value.get("domainKey")
        or value.get("clauseType") or ""
    ).upper()
    return _EXPECTED_DIMENSION_ALIASES.get(raw, _ACTUAL_DIMENSION_BUCKETS.get(raw, raw))


def _risk_finding_matches(expected: dict[str, Any], actual: dict[str, Any]) -> bool:
    expected_text = _normalize_eval_text(expected.get("title"))
    actual_text = _normalize_eval_text(" ".join(str(actual.get(key) or "") for key in (
        "title", "oneLineSummary", "claim", "riskExplanation", "description",
    )))
    if not expected_text or not actual_text:
        return False
    expected_dimension = _risk_dimension(expected)
    actual_dimension = _risk_dimension(actual)
    if expected_text in actual_text or actual_text in expected_text:
        return True
    # Benchmark cases may intentionally use a canonical title while the
    # runtime uses a more specific wording. Within the same normalized risk
    # dimension, a declared key term is sufficient semantic evidence when it
    # is present in the actual explanation/evidence text. This avoids scoring
    # an evidence-backed finding as missed merely because its title differs.
    key_terms = [
        _normalize_eval_text(term)
        for term in (expected.get("keyTerms") or [])
        if _normalize_eval_text(term)
    ]
    if expected_dimension and expected_dimension == actual_dimension:
        distinctive_terms = [term for term in key_terms if len(term) >= 2]
        if distinctive_terms and any(term in actual_text for term in distinctive_terms):
            return True
    expected_pairs = _eval_bigrams(expected_text)
    actual_pairs = _eval_bigrams(actual_text)
    shared = len(expected_pairs & actual_pairs)
    overlap = shared / max(len(expected_pairs), 1)
    # Containment from the shorter side so "不可抗力范围过宽" matches an
    # expected title that embeds the same phrase.
    shorter_pairs = min(len(expected_pairs), len(actual_pairs))
    containment = shared / max(shorter_pairs, 1)
    # Strong text evidence bypasses the dimension gate: the two dimension
    # vocabularies (expected riskDimension vs artifact domainKey/clauseType)
    # do not line up, and a hard gate was killing text-level true matches
    # across the corpus. The minimum shared-bigram count keeps the
    # ACCEPTANCE-vs-PAYMENT guard pair (shared=3) and appendix-description
    # coincidences (shared<=7) behind the gate.
    if shared >= 8 and shorter_pairs >= 8 and containment >= 0.5:
        return True
    if expected_dimension and actual_dimension and expected_dimension != actual_dimension:
        return False
    if shared >= 3 and shorter_pairs >= 3 and containment >= 0.5:
        return True
    sequence_ratio = SequenceMatcher(None, expected_text, actual_text).ratio()
    return overlap >= 0.28 or sequence_ratio >= 0.42


def _failed_eval_stage_run_ids(run_ids: list[int], completed_run_ids: set[int]) -> list[int]:
    return [run_id for run_id in run_ids if run_id not in completed_run_ids]


def _eval_rerank_observation(artifact: dict[str, Any]) -> dict[str, Any]:
    methods: set[str] = set()
    retrieval = artifact.get("retrievalValidation") or artifact.get("retrieval_validation") or {}
    if isinstance(retrieval, dict):
        for value in retrieval.values():
            if not isinstance(value, dict):
                continue
            methods.update(str(method) for method in value.get("rerankMethods") or [] if method)
    normalized = {
        "MODEL_RERANK" if method == "MODEL_RERANK" else
        "KEYWORD_FALLBACK" if method.startswith("KEYWORD_") else method
        for method in methods
    }
    if not normalized:
        actual = "NOT_USED"
    elif len(normalized) == 1:
        actual = next(iter(normalized))
    else:
        actual = "MIXED"
    return {"actualMethod": actual, "methods": sorted(normalized)}


def _score_risk_review(case: dict[str, Any], artifact: dict[str, Any]) -> dict[str, Any]:
    """Score a CONTRACT_REVIEW artifact: HIGH-risk recall against expected
    HIGH findings, dual citation coverage, and should-not-find false positives."""
    findings = artifact.get("findings") or []
    if not isinstance(findings, list):
        findings = []
    try:
        expected = json.loads(case.get("expected_findings_json") or "[]")
    except Exception:
        expected = []
    expected_high = [
        f for f in (expected if isinstance(expected, list) else [])
        if str((f or {}).get("severity", "")).upper() == "HIGH"
    ]
    actual_high = [f for f in findings if str((f or {}).get("severity", "")).upper() == "HIGH"]
    if expected_high:
        high_recall = len([
            h for h in expected_high
            if any(_risk_finding_matches(h, a) for a in actual_high)
        ]) / len(expected_high)
    else:
        # Vacuous recall: no expected HIGH findings — nothing can be missed.
        high_recall = 1.0
    dual_cited = sum(
        1 for f in findings
        if (f.get("contractCitation") or f.get("contractCitationIds"))
        and (f.get("policyCitation") or f.get("policyCitationIds"))
    )
    try:
        should_not = json.loads(case.get("should_not_find_json") or "[]")
    except Exception:
        should_not = []
    false_pos = sum(
        1 for f in findings
        for s in (should_not if isinstance(should_not, list) else [])
        if str(s).lower() in str(f.get("title", "")).lower()
    )
    return {
        "success": True,
        "scored": True,
        "scorerVersion": EVAL_SCORER_VERSION,
        "highRecall": high_recall,
        "dualCitationRate": dual_cited / max(len(findings), 1),
        "falsePositives": false_pos,
        "schemaValid": 1,
        "analysisMode": artifact.get("analysisMode", "FULL"),
        "riskScore": artifact.get("riskScore", 0),
        "findingCount": len(findings),
        "dualCitationCount": dual_cited,
        "contractCitationMissingCount": sum(
            1 for f in findings
            if not (f.get("contractCitation") or f.get("contractCitationIds"))
        ),
        "policyCitationMissingCount": sum(
            1 for f in findings
            if not (f.get("policyCitation") or f.get("policyCitationIds"))
        ),
        "uncitedFindingCount": sum(
            1 for f in findings
            if not (f.get("contractCitation") or f.get("contractCitationIds"))
            and not (f.get("policyCitation") or f.get("policyCitationIds"))
        ),
        "artifact": artifact,
    }


_MISSING_ELEMENT_MARKERS = (
    "缺失", "缺少", "空白", "不明确", "未定义", "未约定", "无法判断", "待确认",
)


def _intake_extraction_surfaces(artifact: dict[str, Any]) -> list[dict[str, Any]]:
    """Flatten the element-extraction artifact into matchable surfaces.

    Each surface is a dict carrying a `_surface` text (elementKey/category/
    rawValue or profile field label/value) so the shared title matcher can
    compare expected entries against what the agent actually extracted.
    """
    stages = artifact.get("evaluationStages") or {}
    stage = stages.get("CONTRACT_ELEMENT_EXTRACTION") if isinstance(stages, dict) else None
    if not isinstance(stage, dict):
        stage = artifact if isinstance(artifact.get("elements"), list) else {}
    items: list[dict[str, Any]] = []
    for element in stage.get("elements") or []:
        if not isinstance(element, dict):
            continue
        normalized = element.get("normalizedValue")
        if isinstance(normalized, dict):
            normalized = json.dumps(normalized, ensure_ascii=False)
        item = dict(element)
        item["_surface"] = " ".join(str(element.get(key) or "") for key in (
            "elementKey", "category", "rawValue",
        )) + (f" {normalized}" if normalized else "")
        items.append(item)
    profile = stage.get("contractProfile") or {}
    for field in (profile.get("baseFields") or []):
        if not isinstance(field, dict):
            continue
        item = dict(field)
        item["_surface"] = " ".join(str(field.get(key) or "") for key in (
            "key", "label", "value", "displayValue",
        ))
        items.append(item)
    for group in (profile.get("groups") or []):
        if not isinstance(group, dict):
            continue
        for field in (group.get("fields") or []):
            if not isinstance(field, dict):
                continue
            item = dict(field)
            item["_surface"] = " ".join(str(field.get(key) or "") for key in (
                "key", "label", "value", "displayValue",
            ))
            items.append(item)
    return items


def _element_expectation_matches(expected: dict[str, Any], surface: str) -> bool:
    """Strict element matching — the shared `_risk_finding_matches` bigram
    overlap is too loose for element values: digit-heavy expectations (amounts,
    dates) collapse to few unique bigrams, and two coincidental shared pairs
    ("00", "0元") push unrelated values over the 0.28 threshold. Extracted
    element values are copied from the contract, so containment is the reliable
    signal; fuzzy sequence similarity applies only to long descriptive titles.
    """
    expected_text = _normalize_eval_text(str(expected.get("title") or ""))
    actual_text = _normalize_eval_text(surface or "")
    if not expected_text or not actual_text:
        return False
    if expected_text in actual_text or actual_text in expected_text:
        return True
    raw_expected = str(expected.get("title") or "")
    if any(token in raw_expected for token in ("金额", "总价", "价款", "单价", "付款")):
        expected_amounts = _eval_amount_values(raw_expected)
        actual_amounts = _eval_amount_values(surface)
        if expected_amounts and actual_amounts and any(
            abs(left - right) <= max(1.0, abs(left) * 0.0001)
            for left in expected_amounts for right in actual_amounts
        ):
            return True
    if len(expected_text) >= 12:
        return SequenceMatcher(None, expected_text, actual_text).ratio() >= 0.5
    return False


_EVAL_AMOUNT_PATTERN = re.compile(
    r"(?<![\d.])(\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?)\s*(万元|万|元|cny|rmb)?",
    re.IGNORECASE,
)


def _eval_amount_values(text: str) -> list[float]:
    """Normalize amounts only for semantic evaluation matching, not contract data."""
    values: list[float] = []
    for match in _EVAL_AMOUNT_PATTERN.finditer(str(text or "")):
        value = float(match.group(1).replace(",", ""))
        unit = str(match.group(2) or "").lower()
        if unit in {"万", "万元"}:
            value *= 10_000
        if value > 0:
            values.append(value)
    return values


def _score_element_extraction(case: dict[str, Any], artifact: dict[str, Any]) -> dict[str, Any]:
    """Score a CONTRACT_ELEMENT_EXTRACTION artifact.

    Expected entries come in two flavors (both share the same
    expected_findings_json shape):
      - element expectations (e.g. "甲方:北京xx公司"): matched against the
        extracted elements/profile fields via the shared title matcher.
      - missing-clause detections (e.g. "开工日期:缺失", HIGH): the agent must
        flag the absence in profile group reasons/summary, otherwise the case
        would score 1.0 without ever detecting anything.

    dualCitationRate is reused as citation coverage: the fraction of extracted
    items that carry at least one contract citation.
    """
    try:
        expected = json.loads(case.get("expected_findings_json") or "[]")
    except Exception:
        expected = []
    if not isinstance(expected, list):
        expected = []
    items = _intake_extraction_surfaces(artifact)
    stages = artifact.get("evaluationStages") or {}
    stage = stages.get("CONTRACT_ELEMENT_EXTRACTION") if isinstance(stages, dict) else None
    if not isinstance(stage, dict):
        stage = artifact if isinstance(artifact.get("elements"), list) else {}
    profile = stage.get("contractProfile") or {}
    reason_texts = [
        str(group.get("reason"))
        for group in (profile.get("groups") or [])
        if isinstance(group, dict) and group.get("reason")
    ]
    context = "\n".join(reason_texts) + "\n" + str(stage.get("summary") or "")

    matched = 0
    for entry in expected:
        if not isinstance(entry, dict):
            continue
        title = str(entry.get("title") or "")
        if any(marker in title for marker in _MISSING_ELEMENT_MARKERS):
            # Missing-clause detection: the subject must be named and a
            # missing marker must appear in the artifact's own account.
            subject = title.split(":", 1)[0].strip() if ":" in title else title
            if (
                subject
                and subject in context
                and any(marker in context for marker in _MISSING_ELEMENT_MARKERS)
            ):
                matched += 1
            continue
        if any(
            _element_expectation_matches(entry, str(item.get("_surface") or ""))
            for item in items
        ):
            matched += 1

    try:
        should_not = json.loads(case.get("should_not_find_json") or "[]")
    except Exception:
        should_not = []
    false_pos = sum(
        1 for item in items
        for s in (should_not if isinstance(should_not, list) else [])
        if str(s).lower() in str(item.get("_surface", "")).lower()
    )
    return {
        "success": True,
        "scored": True,
        "scorerVersion": EVAL_SCORER_VERSION,
        "highRecall": matched / max(len(expected), 1),
        "dualCitationRate": sum(1 for item in items if item.get("citations")) / max(len(items), 1),
        "falsePositives": false_pos,
        "schemaValid": 1 if (
            isinstance(stage.get("elements"), list)
            and isinstance(stage.get("contractProfile"), dict)
        ) else 0,
        "analysisMode": stage.get("analysisMode") or artifact.get("analysisMode", "FULL"),
        "riskScore": artifact.get("riskScore", 0),
        "findingCount": len(items),
        "artifact": artifact,
    }


# PRD Phase 8 / §10: every scored run freezes the scorer version it was
# evaluated with — agent_eval_result rows and eval summaries must be
# traceable to this exact implementation.
def _timeline_node_surface(node: dict[str, Any]) -> str:
    """Flatten one timeline node into the text surface expected titles match."""
    return " ".join(str(node.get(key) or "") for key in (
        "label", "businessMeaning", "date", "condition",
        "responsibleParty", "nodeType",
    ))


def _timeline_expected_parts(entry: dict[str, Any]) -> tuple[str, str]:
    """Split an expected timeline entry "label:detail" into its two parts."""
    title = str(entry.get("title") or "")
    if ":" in title:
        label, detail = title.split(":", 1)
        return label.strip(), detail.strip()
    return title.strip(), ""


_DATE_TOKEN = re.compile(r"\d{4}-\d{1,2}-\d{1,2}")


def _score_timeline_extraction(case: dict[str, Any], artifact: dict[str, Any]) -> dict[str, Any]:
    """Score a TIMELINE_EXTRACTION artifact (PRD §9.3).

    Golden expectations share the expected_findings_json shape, e.g.
    "生效:2026-01-01", "终止:双方权利义务履行完毕之日(条件事件)",
    "每月5日前:公示收支明细(周期)":

      - label matches a node via containment / bigram overlap on the node
        surface (label/businessMeaning/date/condition);
      - a date in the detail must equal the matched node's date exactly
        (日期计算准确率);
      - a 条件事件 entry must land on a node with no fixed date and a
        non-empty condition (非固定结束条件识别率);
      - should_not_find_json entries must not appear in any node surface
        (e.g. a fabricated fixed termination date).

    Every rate carries its explicit denominator for Phase 8 task 5.
    """
    stages = artifact.get("evaluationStages") or {}
    stage = stages.get("TIMELINE_EXTRACTION") if isinstance(stages, dict) else None
    if not isinstance(stage, dict):
        stage = artifact
    nodes = stage.get("nodes") or []
    if not isinstance(nodes, list):
        nodes = []
    try:
        expected = json.loads(case.get("expected_findings_json") or "[]")
    except Exception:
        expected = []
    if not isinstance(expected, list):
        expected = []

    matched = 0
    date_expected = 0
    date_correct = 0
    cond_expected = 0
    cond_recognized = 0
    for entry in expected:
        if not isinstance(entry, dict):
            continue
        label, detail = _timeline_expected_parts(entry)
        if not label:
            continue
        label_text = _normalize_eval_text(label)
        expected_date = _DATE_TOKEN.search(detail)
        conditional = (
            not expected_date and ("条件" in detail or "事件" in detail)
        )
        if conditional:
            cond_expected += 1
        if expected_date:
            date_expected += 1

        best: dict[str, Any] | None = None
        for node in nodes:
            if not isinstance(node, dict):
                continue
            node_label = _normalize_eval_text(str(node.get("label") or ""))
            surface = _normalize_eval_text(_timeline_node_surface(node))
            if not label_text:
                continue
            if label_text in node_label or label_text in surface:
                best = node
                break
            label_grams = _eval_bigrams(label_text)
            overlap = len(label_grams & _eval_bigrams(surface)) if label_grams else 0
            if label_grams and overlap >= max(2, len(label_grams) // 2):
                best = node
                break

        if best is None:
            continue
        matched += 1
        node_date = _DATE_TOKEN.search(str(best.get("date") or ""))
        if expected_date:
            if node_date and node_date.group(0) == expected_date.group(0):
                date_correct += 1
        if conditional:
            if not node_date and str(best.get("condition") or "").strip():
                cond_recognized += 1

    try:
        should_not = json.loads(case.get("should_not_find_json") or "[]")
    except Exception:
        should_not = []
    false_pos = 0
    for node in nodes:
        surface = _normalize_eval_text(_timeline_node_surface(node))
        for entry in (should_not if isinstance(should_not, list) else []):
            token = _normalize_eval_text(entry)
            if token and token in surface:
                false_pos += 1

    validation = (stage.get("content") or {}).get("validation") or {}
    cited = sum(
        1 for node in nodes
        if isinstance(node, dict) and (node.get("citation") or {}).get("quote")
    )
    return {
        "success": True,
        "scored": True,
        "scorerVersion": EVAL_SCORER_VERSION,
        "highRecall": matched / len(expected) if expected else 1.0,
        "expectedNodeCount": len(expected),
        "dualCitationRate": cited / max(len(nodes), 1),
        "falsePositives": false_pos,
        "schemaValid": 1 if isinstance(stage.get("nodes"), list) else 0,
        "analysisMode": stage.get("analysisMode") or artifact.get("analysisMode", "FULL"),
        "riskScore": stage.get("riskScore") or artifact.get("riskScore", 0),
        "findingCount": len(nodes),
        "dateAccuracy": date_correct / date_expected if date_expected else 1.0,
        "dateDenominator": date_expected,
        "conditionalRecognitionRate": (
            cond_recognized / cond_expected if cond_expected else 1.0
        ),
        "conditionalDenominator": cond_expected,
        "responsiblePartyCoverage": (
            sum(1 for node in nodes
                if isinstance(node, dict) and node.get("responsibleParty"))
            / max(len(nodes), 1)
        ),
        "mojibakeFlaggedCount": int(validation.get("mojibakeFlaggedCount") or 0),
        "artifact": artifact,
    }


def _fulfillment_requirement_surface(row: dict[str, Any]) -> str:
    """Flatten one fulfilment judgement row for expected-title matching."""
    return " ".join(str(row.get(key) or "") for key in (
        "requirement", "judgement", "proofStatus", "evidence",
        "gap", "deadline",
    ))


def _score_fulfillment_check(case: dict[str, Any], artifact: dict[str, Any]) -> dict[str, Any]:
    """Score a FULFILLMENT_REPORT artifact (PRD §9.4).

    Expected entries are requirement titles ("首付款:2026-03-01前支付").
    The acceptance-critical metrics are structural:

      - aiAutoConfirmViolations — a conclusion present without a human
        manualResult counts as one violation; PRD requires it to be 0;
      - restraintRate — among rows that found no evidence snapshot, the
        fraction judged INSUFFICIENT/NEEDS_REVIEW rather than claiming a
        satisfied state (证据不足克制率);
      - aiSuggestionSchemaRate — fraction of rows whose advisory suggestion
        layer normalized cleanly (LLM_ENRICHED), PRD ≥99%.
    """
    stages = artifact.get("evaluationStages") or {}
    stage = stages.get("FULFILLMENT_CHECK") if isinstance(stages, dict) else None
    if isinstance(stage, dict):
        artifact = stage
    content = artifact.get("content") or {}
    if not isinstance(content, dict):
        content = {}
    requirements = artifact.get("requirements") or content.get("requirements") or []
    if not isinstance(requirements, list):
        requirements = []
    try:
        expected = json.loads(case.get("expected_findings_json") or "[]")
    except Exception:
        expected = []
    if not isinstance(expected, list):
        expected = []

    matched = 0
    for entry in expected:
        if not isinstance(entry, dict):
            continue
        if any(
            _element_expectation_matches(
                entry, _fulfillment_requirement_surface(row)
            )
            for row in requirements
            if isinstance(row, dict)
        ):
            matched += 1

    no_evidence_rows = [
        row for row in requirements
        if isinstance(row, dict)
        and not (row.get("evidenceSnapshot") or row.get("evidenceCitationIds"))
    ]
    restrained = sum(
        1 for row in no_evidence_rows
        if str(row.get("proofStatus") or row.get("judgement") or "").upper()
        in ("INSUFFICIENT", "EVIDENCE_INSUFFICIENT", "NEEDS_REVIEW", "UNCLEAR", "UNCLEAR_TERMS")
    )
    manual_result = str(content.get("manualResult") or "").strip().upper()
    expected_manual_result = str(case.get("expected_manual_result") or "").strip().upper()
    conclusion = str(artifact.get("conclusion") or "").strip()
    ai_violations = 1 if (conclusion and not manual_result) else 0
    conflict_rows = sum(
        1 for row in requirements
        if isinstance(row, dict)
        and str(row.get("judgement") or (row.get("aiSuggestion") or {}).get("conclusion") or "")
        .upper() in ("UNCLEAR_TERMS", "UNCLEAR")
    )
    cited_rows = sum(
        1 for row in requirements
        if isinstance(row, dict)
        and (row.get("evidenceCitationIds") or row.get("contractCitationIds"))
    )
    try:
        should_not = json.loads(case.get("should_not_find_json") or "[]")
    except Exception:
        should_not = []
    false_pos = sum(
        1 for row in requirements
        for entry in (should_not if isinstance(should_not, list) else [])
        if _normalize_eval_text(entry)
        in _normalize_eval_text(_fulfillment_requirement_surface(row))
        if _normalize_eval_text(entry)
    )
    try:
        expected_judgements = json.loads(case.get("expected_judgements_json") or "[]")
    except Exception:
        expected_judgements = []
    if not isinstance(expected_judgements, list):
        expected_judgements = []
    judgement_matches = 0
    for expected_judgement in expected_judgements:
        if not isinstance(expected_judgement, dict):
            continue
        requirement_token = _normalize_eval_text(
            expected_judgement.get("requirementContains") or expected_judgement.get("requirement")
        )
        for actual in requirements:
            if not isinstance(actual, dict):
                continue
            surface = _normalize_eval_text(_fulfillment_requirement_surface(actual))
            if requirement_token and requirement_token not in surface:
                continue
            expected_status = str(expected_judgement.get("proofStatus") or "").upper()
            expected_judgement_value = str(expected_judgement.get("judgement") or "").upper()
            if expected_status and str(actual.get("proofStatus") or "").upper() != expected_status:
                continue
            if expected_judgement_value and str(actual.get("judgement") or "").upper() != expected_judgement_value:
                continue
            judgement_matches += 1
            break
    return {
        "success": True,
        "scored": True,
        "scorerVersion": EVAL_SCORER_VERSION,
        "highRecall": matched / len(expected) if expected else 1.0,
        "expectedRequirementCount": len(expected),
        "dualCitationRate": cited_rows / max(len(requirements), 1),
        "falsePositives": false_pos,
        "schemaValid": 1 if (
            isinstance(artifact.get("requirements") or content.get("requirements"), list)
            and isinstance(artifact.get("content"), dict)
        ) else 0,
        "analysisMode": artifact.get("analysisMode") or content.get("analysisMode", "FULL"),
        "riskScore": artifact.get("riskScore", 0),
        "findingCount": len(requirements),
        "restraintRate": restrained / max(len(no_evidence_rows), 1),
        "restraintDenominator": len(no_evidence_rows),
        "aiSuggestionSchemaRate": sum(
            1 for row in requirements
            if isinstance(row, dict)
            and (row.get("aiSuggestion") or {}).get("status") == "LLM_ENRICHED"
        ) / max(len(requirements), 1),
        "aiAutoConfirmViolations": ai_violations,
        "conflictRecognitionRate": conflict_rows / max(len(requirements), 1),
        "humanAdoptionRate": 1.0 if manual_result else 0.0,
        "humanResultMatch": (
            1.0 if manual_result == expected_manual_result else 0.0
        ) if expected_manual_result else (1.0 if manual_result else 0.0),
        "judgementAccuracy": (
            judgement_matches / len(expected_judgements)
            if expected_judgements else 1.0
        ),
        "judgementDenominator": len(expected_judgements),
        "artifact": artifact,
    }


_EVAL_SCORERS = {
    "CONTRACT_REVIEW": _score_risk_review,
    "RISK_REVIEW": _score_risk_review,
    "CONTRACT_ELEMENT_EXTRACTION": _score_element_extraction,
    "INTAKE": _score_element_extraction,
    "ELEMENT_EXTRACTION": _score_element_extraction,
    "TIMELINE_EXTRACTION": _score_timeline_extraction,
    "FULFILLMENT_TIMELINE": _score_timeline_extraction,
    "FULFILLMENT_CHECK": _score_fulfillment_check,
}


def _score_eval_artifact(case: dict[str, Any], artifact: dict[str, Any], score_mode: str) -> dict[str, Any]:
    """Score one eval case through the per-task-type scorer registry.

    PRD Phase 8 acceptance: no constant-1.0 placeholder scoring. An
    unregistered task type is reported as explicitly UNSCORED (scored=False
    + skipReason) so the run summary can exclude it from the metrics
    denominators instead of publishing fake 1.0s.
    """
    scorer = _EVAL_SCORERS.get(str(score_mode or "").upper())
    if scorer:
        return scorer(case, artifact or {})
    return {
        "success": False,
        "scored": False,
        "skipReason": f"NO_SCORER:{str(score_mode or 'UNKNOWN').upper()}",
        "highRecall": 0.0,
        "dualCitationRate": 0.0,
        "falsePositives": 0,
        "schemaValid": 0,
        "analysisMode": "UNSCORED",
        "riskScore": 0,
        "findingCount": 0,
        "artifact": artifact,
    }


def _is_scoreable_eval_result(
    result: Any,
    artifact: dict[str, Any],
    findings: Any = None,
    *,
    require_findings: bool = False,
) -> bool:
    """Return whether a terminal agent result is valid input for an eval scorer.

    A scope-limited report is still a real evidence-backed result. Preserve its
    findings, citations, and version metadata for scoring; its LIMITED mode
    makes the aggregate evaluation degraded rather than completed.
    """
    if getattr(result, "status", None) not in {"COMPLETED", "LIMITED"}:
        return False
    if artifact.get("artifactError"):
        return False
    if not require_findings:
        return True
    return isinstance(artifact.get("findings") if findings is None else findings, list)


async def _dispatch_eval_task(
    *,
    eval_run_id: int,
    case: dict[str, Any],
    idx: int,
    temp_case_id: int,
    task_type: str,
    features: dict,
    runtime: str,
    timeout_seconds: int,
) -> tuple[int, Any]:
    from app.agent_runtime.api_models import AgentTaskContext
    from app.agent_runtime.persistence import _conn

    task_input = {
        "evalRunId": eval_run_id,
        "evalCaseId": case.get("case_key"),
        "features": features,
        "evaluationTaskType": task_type,
    }
    if task_type == "FULFILLMENT_CHECK":
        fulfillment_input = _eval_fulfillment_input(case)
        node_id = _select_eval_timeline_node_id(temp_case_id, fulfillment_input["selector"])
        evidence_document_ids = _seed_eval_fulfillment_evidence(
            temp_case_id, node_id, fulfillment_input["evidence"]
        )
        task_input["timelineNodeId"] = node_id
        task_input["evaluationFulfillment"] = {
            "selector": fulfillment_input["selector"],
            "evidenceDocumentIds": evidence_document_ids,
            "expectedJudgements": fulfillment_input["expectedJudgements"],
            "expectedManualResult": fulfillment_input["expectedManualResult"],
        }

    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO agent_run
                   (project_id, run_type, trigger_type, question, status,
                    progress, current_step, input_json, subject_type, subject_id)
                   VALUES (%s,%s,'EVALUATION',%s,'CREATED',
                           0,'Evaluation case queued',%s,'CONTRACT_CASE',%s)""",
                (
                    temp_case_id,
                    task_type,
                    f"Eval {case.get('case_key')}: {case.get('title')}",
                    _json_safe({
                        "evalRunId": eval_run_id,
                        "evalCaseKey": case.get("case_key"),
                        "evalCaseIndex": idx,
                        "features": features,
                    }),
                    temp_case_id,
                ),
            )
            run_id = int(cur.lastrowid)
            conn.commit()

    # Stamp the actual stage start before handing control to either runtime.
    # Without this transition graph runs had a NULL started_at and P1 could
    # not derive their wall-clock latency even though finished_at was present.
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """UPDATE agent_run
                   SET status='RUNNING', started_at=COALESCE(started_at, NOW()),
                       last_heartbeat_at=NOW(), current_step='Agent stage running'
                   WHERE id=%s AND status='CREATED'""",
                (run_id,),
            )
        conn.commit()

    ctx = AgentTaskContext(
        run_id=run_id,
        project_id=temp_case_id,
        task_type=task_type,
        question=f"Evaluate contract: {case.get('title')}",
        subject_type="CONTRACT_CASE",
        subject_id=temp_case_id,
        project={
            "id": temp_case_id,
            "title": case.get("title"),
            "contractType": _eval_business_contract_type(case),
            "scenario": case.get("scenario") or "",
            "industry": case.get("industry") or "",
            "difficulty": case.get("difficulty") or "",
            "evalExpectedDimensions": _eval_expected_dimensions(case),
            # Preserve the evaluation identity in the graph's initial
            # case_snapshot so focused-domain planning is explicitly scoped
            # to benchmark runs and never inferred for production reviews.
            "evalCaseKey": case.get("case_key"),
            "evalCaseIndex": idx,
        },
        task_input=task_input,
    )
    router = get_contract_runtime_router()
    return run_id, await asyncio.wait_for(
        router.dispatch_with_mode(ctx, runtime),
        timeout=timeout_seconds,
    )


def _read_actual_engine(run_id: int) -> str:
    """Derive which runtime engine actually executed a dispatched run row.

    Graph adapters stamp agent_run.runtime_engine='langgraph' plus graph
    name/version; the legacy pipeline leaves them NULL. Used to surface
    silent fallbacks (e.g. a stale API server process that doesn't know
    langgraph_v2 and runs legacy instead) in the eval summary.
    """
    try:
        from app.agent_runtime.persistence import _conn

        with _conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT runtime_engine, graph_name, graph_version FROM agent_run WHERE id=%s",
                    (run_id,),
                )
                row = cur.fetchone()
                if not row or not row.get("runtime_engine"):
                    return "legacy"
                parts = [str(row["runtime_engine"])]
                if row.get("graph_name"):
                    parts.append(str(row["graph_name"]))
                    if row.get("graph_version"):
                        parts.append(str(row["graph_version"]))
                return "/".join(parts)
    except Exception:
        logger.exception("Could not read actual engine for run %s", run_id)
        return "unknown"


def _read_eval_run_versions(run_id: int) -> dict[str, str]:
    """Read the immutable execution stack for one scored evaluation stage."""
    try:
        from app.agent_runtime.persistence import _conn

        with _conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """SELECT evidence_snapshot_hash, graph_name, graph_version,
                              model, prompt_version, retrieval_version, rerank_version
                         FROM agent_run WHERE id=%s""",
                    (run_id,),
                )
                row = cur.fetchone() or {}
        return {
            "snapshotHash": str(row.get("evidence_snapshot_hash") or ""),
            "graphName": str(row.get("graph_name") or ""),
            "graphVersion": str(row.get("graph_version") or ""),
            "model": str(row.get("model") or ""),
            "promptVersion": str(row.get("prompt_version") or ""),
            "retrievalVersion": str(row.get("retrieval_version") or ""),
            "rerankVersion": str(row.get("rerank_version") or ""),
            "scorerVersion": EVAL_SCORER_VERSION,
        }
    except Exception:
        logger.exception("Could not read version snapshot for eval run %s", run_id)
        return {"scorerVersion": EVAL_SCORER_VERSION}


def _read_eval_case_telemetry(case_id: int, run_ids: list[int]) -> dict[str, Any]:
    """Read observed runtime facts after a case's production stages finish."""
    if not run_ids:
        return case_telemetry(case_id, [])
    try:
        from app.agent_runtime.persistence import _conn

        placeholders = ",".join(["%s"] * len(run_ids))
        with _conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"""SELECT r.id, r.status, r.runtime_engine, r.graph_name, r.graph_version,
                                  r.model, r.prompt_version, r.retrieval_version, r.rerank_version,
                                  r.scorer_version,
                                  CASE WHEN r.started_at IS NOT NULL AND r.finished_at IS NOT NULL
                                       THEN TIMESTAMPDIFF(MICROSECOND, r.started_at, r.finished_at) DIV 1000
                                       ELSE NULL END AS wall_latency_ms,
                                  COALESCE(SUM(n.latency_ms), 0) AS node_latency_ms,
                                  COUNT(n.id) AS node_execution_count,
                                  COALESCE(SUM(n.token_input), 0) AS token_input,
                                  COALESCE(SUM(n.token_output), 0) AS token_output,
                                  COALESCE(SUM(CASE WHEN COALESCE(n.token_input, 0) > 0
                                                         OR COALESCE(n.token_output, 0) > 0
                                                    THEN 1 ELSE 0 END), 0) AS token_observed_count
                           FROM agent_run r
                           LEFT JOIN agent_node_execution n ON n.run_id=r.id
                           WHERE r.id IN ({placeholders})
                           GROUP BY r.id, r.status, r.runtime_engine, r.graph_name, r.graph_version,
                                    r.model, r.prompt_version, r.retrieval_version, r.rerank_version,
                                    r.scorer_version, r.started_at, r.finished_at
                           ORDER BY r.id""",
                    run_ids,
                )
                rows = cur.fetchall()
        return case_telemetry(case_id, stage_telemetry(rows))
    except Exception:
        logger.exception("Could not read operational telemetry for eval case %s", case_id)
        return case_telemetry(case_id, [])


def _eval_runtime_mismatch(runtime: str, actual_engine: str | None) -> bool:
    """True when the engine that actually ran differs from the requested one."""
    if not actual_engine or actual_engine == "unknown":
        return bool(actual_engine)
    parts = actual_engine.split("/")
    if parts[0] == "legacy":
        return runtime != "legacy"
    # graph-dispatched run: base is 'langgraph' for all graph modes
    if runtime not in ("langgraph", "langgraph_v2", "shadow_v2"):
        return True
    if runtime == "langgraph_v2" and len(parts) >= 3 and parts[2] != "v2":
        return True
    return False


def _finish_eval_agent_run(
    run_id: int,
    status: str,
    message: str = "",
    limited_diagnostics: dict | None = None,
) -> None:
    if not run_id:
        return
    from app.agent_runtime.persistence import _conn

    try:
        with _conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """UPDATE agent_run
                       SET status=%s,
                           progress=CASE WHEN %s IN ('COMPLETED','LIMITED') THEN 100 ELSE progress END,
                           current_step=%s,
                           error_message=CASE WHEN %s='FAILED' THEN %s ELSE NULL END,
                           limited_diagnostics=COALESCE(%s, limited_diagnostics),
                           finished_at=NOW(),
                           last_heartbeat_at=NOW()
                       WHERE id=%s""",
                    (
                        status,
                        status,
                        message[:120] if message else status,
                        status,
                        message[:4000] if message else None,
                        _json_safe(limited_diagnostics) if limited_diagnostics is not None else None,
                        run_id,
                    ),
                )
                conn.commit()
    except Exception:
        logger.exception("Could not finish eval agent run %s", run_id)


async def _run_evaluation_background(eval_run_id: int):
    from app.agent_runtime.persistence import _conn

    temp_case_ids: list[int] = []
    total_cases = 0
    success_count = 0
    avg_recall = 0.0
    actual_engine: str | None = None
    try:
        _update_eval_progress(
            eval_run_id,
            status="PRECHECKING",
            current_step="Checking evaluation environment",
            queue_position=0,
        )
        with _conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """SELECT r.id, r.dataset_id, r.runtime_engine, r.features_json,
                              d.contract_type AS dataset_type
                       FROM agent_eval_run r
                       JOIN agent_eval_dataset d ON d.id=r.dataset_id
                       WHERE r.id=%s""",
                    (eval_run_id,),
                )
                run_row = cur.fetchone()
                if not run_row:
                    _fail_eval_run(eval_run_id, "Eval run not found")
                    return
                dataset_id = int(run_row["dataset_id"])
                runtime = str(run_row["runtime_engine"] or "legacy")
                dataset_type = str(run_row.get("dataset_type") or "CONTRACT_REVIEW")
                try:
                    features = json.loads(run_row.get("features_json") or "{}")
                except Exception:
                    features = {}
                timeout_seconds = max(60, int(features.get("caseTimeoutSeconds") or 900))
                cur.execute(
                    """SELECT id, case_key, title, contract_type, contract_text,
                              expected_findings_json, should_not_find_json,
                              scenario, industry, difficulty, noise_level,
                              must_have_contract_citation, must_have_policy_citation,
                              fulfillment_evidence_json, target_timeline_selector_json,
                              expected_judgements_json, expected_manual_result
                       FROM agent_eval_case
                       WHERE dataset_id=%s AND status='ACTIVE'
                       ORDER BY id""",
                    (dataset_id,),
                )
                cases = cur.fetchall()
                total_cases = len(cases)

        # The case table stores a business scenario, whereas the parent
        # dataset owns the evaluation task.  Keep both meanings explicit for
        # fixture-key construction and stage dispatch.
        for case in cases:
            case["evaluation_dataset_type"] = dataset_type

        if not cases:
            _fail_eval_run(eval_run_id, "No active cases in dataset")
            return

        env_snapshot = await _eval_environment_gate(features)
        env_status = str(env_snapshot.get("environmentStatus") or "UNAVAILABLE")
        unavailable = env_status == "UNAVAILABLE"
        _update_eval_progress(
            eval_run_id,
            status="ENVIRONMENT_UNAVAILABLE" if unavailable else "RUNNING",
            case_count=total_cases,
            passed_count=0,
            current_case_index=0,
            current_step="Environment unavailable" if unavailable else "Running evaluation cases",
            environment_status=env_status,
            environment_snapshot=env_snapshot,
            summary_patch={"environment": env_snapshot, "percent": 0, "infraFailedCount": 0},
            finished=unavailable,
        )
        if unavailable:
            return

        task_plan = _eval_task_plan(dataset_type)
        per_case_results: list[dict[str, Any]] = []
        infra_failed_count = 0
        scored_case_run_ids: list[int] = []
        fixture_reuse_count: list[int] = []
        logger.info(
            "Eval run %s: %d cases, runtime=%s, dataset=%s, tasks=%s",
            eval_run_id, total_cases, runtime, dataset_type, task_plan,
        )

        for idx, case in enumerate(cases):
            case_id = int(case["id"])
            case_key = str(case.get("case_key") or case_id)
            case_run_ids: list[int] = []
            completed_run_ids: set[int] = set()
            try:
                _update_eval_progress(
                    eval_run_id,
                    status="RUNNING",
                    current_case_index=idx + 1,
                    current_case_key=case_key,
                    current_step=f"Running case {idx + 1}/{total_cases}: {case_key}",
                    summary_patch={"percent": round((idx / total_cases) * 100, 2)},
                )
                temp_case_id = _create_eval_temp_case(eval_run_id, case, idx, temp_case_ids, fixture_reuse_count)
                _set_eval_feature_overrides(features)
                stage_outputs: dict[str, Any] = {}
                review_artifact: dict[str, Any] | None = None
                for task_type in task_plan:
                    try:
                        run_id, result = await _dispatch_eval_task(
                            eval_run_id=eval_run_id,
                            case=case,
                            idx=idx,
                            temp_case_id=temp_case_id,
                            task_type=task_type,
                            features=features,
                            runtime=runtime,
                            timeout_seconds=timeout_seconds,
                        )
                        case_run_ids.append(run_id)
                    except EvalCaseConfigurationError:
                        raise
                    except ValueError as skip_exc:
                        stage_outputs[task_type] = {"skipped": True, "reason": str(skip_exc)}
                        continue
                    if task_type == "FULFILLMENT_CHECK" and result.status == "WAITING_HUMAN":
                        # Preserve the AI proposal before the controlled human
                        # decision.  A fulfillment graph is not considered a
                        # completed report until the same production resume
                        # path has applied the expected manual decision.
                        stage_outputs["FULFILLMENT_CHECK_PRE_HUMAN"] = {
                            "status": "WAITING_HUMAN",
                            "waitState": (result.graph_info or {}).get("waitState") or {},
                        }
                        from app.agent_runtime.runtime import ResumeAction, ResumeCommand

                        expected_manual_result = _eval_fulfillment_input(case)["expectedManualResult"]
                        command = ResumeCommand(
                            action=(
                                ResumeAction.KEEP_PENDING
                                if expected_manual_result == "PENDING"
                                else ResumeAction.CONFIRM
                            ),
                            manual_result=expected_manual_result,
                            note="Controlled evaluation human decision",
                            operator_id="evaluation-harness",
                        )
                        adapter = get_contract_runtime_router().get_adapter("fulfillment_check")
                        if adapter is None:
                            raise RuntimeError("Fulfillment graph adapter is unavailable for evaluation resume")
                        result = await asyncio.wait_for(
                            adapter.resume(run_id, command), timeout=timeout_seconds
                        )
                    artifact = result.artifact or {}
                    if not _is_scoreable_eval_result(result, artifact):
                        error = str(artifact.get("artifactError") or f"Agent runtime ended with status {result.status}")
                        _finish_eval_agent_run(run_id, "FAILED", error)
                        raise RuntimeError(error)
                    _finish_eval_agent_run(
                        run_id,
                        result.status,
                        "Evaluation case completed" if result.status == "COMPLETED"
                        else "Evaluation case completed with limited coverage",
                        limited_diagnostics=(result.graph_info or {}).get("limitedDiagnostics")
                        if result.status == "LIMITED" else None,
                    )
                    if actual_engine is None:
                        actual_engine = _read_actual_engine(run_id)
                    completed_run_ids.add(run_id)
                    stage_outputs[task_type] = artifact
                    if task_type == "CONTRACT_REVIEW":
                        review_artifact = artifact

                score_mode = "CONTRACT_REVIEW" if "CONTRACT_REVIEW" in task_plan else task_plan[-1]
                artifact_for_score = review_artifact or {
                    "analysisMode": "FULL",
                    "evaluationStages": stage_outputs,
                }
                row = _score_eval_artifact(case, artifact_for_score, score_mode)
                if row.get("scored", True):
                    row["scorerVersion"] = EVAL_SCORER_VERSION
                    score_artifact = row.get("artifact")
                    if isinstance(score_artifact, dict) and case_run_ids:
                        score_artifact["versions"] = {
                            **dict(score_artifact.get("versions") or {}),
                            **_read_eval_run_versions(case_run_ids[-1]),
                        }
                rerank_observation = _eval_rerank_observation(artifact_for_score)
                if rerank_observation["actualMethod"] == "NOT_USED":
                    # Legacy artifacts lack retrievalValidation; the per-case
                    # contextvar observation captures actual legacy rerank usage.
                    try:
                        from app.agent_runtime.reranker import get_rerank_observation
                        rerank_observation = get_rerank_observation()
                    except Exception:
                        pass
                row["artifact"] = {
                    **(row.get("artifact") or {}),
                    "evaluationStages": stage_outputs,
                    "evaluationTaskPlan": task_plan,
                    "rerank": rerank_observation,
                }
                row["rerankMethod"] = rerank_observation["actualMethod"]
                row["telemetry"] = _read_eval_case_telemetry(case_id, case_run_ids)
                row["artifact"]["telemetry"] = row["telemetry"]
                _record_eval_result(eval_run_id, case_id, row)
                per_case_results.append({"caseId": case_id, **row})
                if row.get("scored", True):
                    scored_case_run_ids.extend(case_run_ids)
                success_count += 1
            except Exception as exc:
                for run_id in _failed_eval_stage_run_ids(case_run_ids, completed_run_ids):
                    _finish_eval_agent_run(run_id, "FAILED", str(exc))
                infra_failed = _is_infra_error(exc)
                if infra_failed:
                    infra_failed_count += 1
                row = {
                    "caseId": case_id,
                    "success": False,
                    "highRecall": 0,
                    "dualCitationRate": 0,
                    "falsePositives": 0,
                    "schemaValid": 0,
                    "analysisMode": "INFRA_FAILED" if infra_failed else "FAILED",
                    "error": str(exc),
                    "artifact": {"artifactError": str(exc), "infraFailed": infra_failed},
                }
                try:
                    from app.agent_runtime.reranker import get_rerank_observation
                    rerank_observation = get_rerank_observation()
                    row["rerankMethod"] = rerank_observation["actualMethod"]
                    row["artifact"]["rerank"] = rerank_observation
                except Exception:
                    pass
                row["telemetry"] = _read_eval_case_telemetry(case_id, case_run_ids)
                row["artifact"]["telemetry"] = row["telemetry"]
                _record_eval_result(eval_run_id, case_id, row)
                per_case_results.append(row)
                logger.warning("Eval run %s case %s/%s failed: %s", eval_run_id, idx + 1, total_cases, exc)
            finally:
                _update_eval_progress(
                    eval_run_id,
                    passed_count=success_count,
                    summary_patch={
                        "completedCases": idx + 1,
                        "failedCases": len([
                            r for r in per_case_results
                            if not r.get("success") and r.get("analysisMode") != "INFRA_FAILED"
                        ]),
                        "infraFailedCases": infra_failed_count,
                        "percent": round(((idx + 1) / total_cases) * 100, 2),
                    },
                )

        # PRD §10: freeze the scorer version on the executed run rows so the
        # stack behind every scored case is queryable from agent_run.
        if scored_case_run_ids:
            try:
                with _conn() as conn:
                    with conn.cursor() as cur:
                        placeholders = ",".join(["%s"] * len(scored_case_run_ids))
                        cur.execute(
                            f"UPDATE agent_run SET scorer_version=%s WHERE id IN ({placeholders})",
                            [EVAL_SCORER_VERSION, *scored_case_run_ids],
                        )
                        conn.commit()
            except Exception as exc:
                logger.debug("Could not stamp scorer version on eval case runs: %s", exc)

        # Freeze the scorer version into the already-collected operational
        # stage snapshots before building the immutable run summary.
        for result in per_case_results:
            telemetry = result.get("telemetry")
            if not isinstance(telemetry, dict):
                continue
            for stage in telemetry.get("stages") or []:
                if isinstance(stage, dict):
                    stack = stage.setdefault("executionStack", {})
                    if isinstance(stack, dict):
                        stack["scorerVersion"] = EVAL_SCORER_VERSION
            refreshed = case_telemetry(int(result.get("caseId") or 0), telemetry.get("stages") or [])
            result["telemetry"] = refreshed
            artifact = result.get("artifact")
            if isinstance(artifact, dict):
                artifact["telemetry"] = refreshed

        # Phase 8 task 5: UNSCORED rows (no scorer registered for the task
        # type) are excluded from metric denominators and reported explicitly
        # with their skip reason instead of leaking 0.0s into the averages.
        metric_results = [
            r for r in per_case_results
            if r.get("analysisMode") != "INFRA_FAILED" and r.get("scored", True) is not False
        ]
        unscored_count = sum(
            1 for r in per_case_results
            if r.get("analysisMode") != "INFRA_FAILED" and r.get("scored") is False
        )
        skip_reasons = {
            str(r.get("caseId")): str(r.get("skipReason"))
            for r in per_case_results
            if r.get("skipReason")
        }
        if metric_results:
            n = len(metric_results)
            avg_recall = sum(float(r.get("highRecall") or 0) for r in metric_results) / n
            avg_dual_cite = sum(float(r.get("dualCitationRate") or 0) for r in metric_results) / n
            avg_false_pos = sum(float(r.get("falsePositives") or 0) for r in metric_results) / n
            avg_schema_valid = sum(1 for r in metric_results if r.get("schemaValid")) / n
            limited_count = sum(1 for r in metric_results if r.get("analysisMode") == "LIMITED")
            limited_report_rate = limited_count / n
            finding_count = sum(int(r.get("findingCount") or 0) for r in metric_results)
            dual_citation_count = sum(int(r.get("dualCitationCount") or 0) for r in metric_results)
            contract_citation_missing_count = sum(
                int(r.get("contractCitationMissingCount") or 0) for r in metric_results
            )
            policy_citation_missing_count = sum(
                int(r.get("policyCitationMissingCount") or 0) for r in metric_results
            )
            uncited_finding_count = sum(int(r.get("uncitedFindingCount") or 0) for r in metric_results)
        else:
            avg_recall = 0.0
            avg_dual_cite = 0.0
            avg_false_pos = 0.0
            avg_schema_valid = 0.0
            limited_count = 0
            limited_report_rate = 0.0
            finding_count = 0
            dual_citation_count = 0
            contract_citation_missing_count = 0
            policy_citation_missing_count = 0
            uncited_finding_count = 0
        failed_count = len([
            r for r in per_case_results
            if not r.get("success") and r.get("analysisMode") != "INFRA_FAILED"
            and r.get("scored", True) is not False
        ])
        rerank_methods = sorted({
            str(result.get("rerankMethod") or "NOT_USED")
            for result in per_case_results
        })
        requested_rerank = bool(features.get("rerank", True))
        rerank_fallback_count = sum(
            1 for result in per_case_results
            if result.get("rerankMethod") in {"KEYWORD_FALLBACK", "MIXED"}
        )
        operations = aggregate_telemetry(
            [result.get("telemetry") or case_telemetry(int(result.get("caseId") or 0), [])
             for result in per_case_results],
            features.get("pricing") if isinstance(features, dict) else None,
        )

        if success_count == 0 and infra_failed_count == total_cases:
            eval_status = "ENVIRONMENT_UNAVAILABLE"
        elif success_count == 0:
            eval_status = "FAILED"
        elif (
            failed_count > 0 or limited_count > 0 or infra_failed_count > 0
            or unscored_count > 0
            or env_status == "DEGRADED" or (requested_rerank and rerank_fallback_count > 0)
        ):
            eval_status = "DEGRADED"
        else:
            eval_status = "COMPLETED"

        summary_payload = {
            "highRiskRecall": round(avg_recall, 4),
            "dualCitationRate": round(avg_dual_cite, 4),
            "falsePositiveRate": round(avg_false_pos, 4),
            "schemaValidRate": round(avg_schema_valid, 4),
            "limitedReportRate": round(limited_report_rate, 4),
            "caseCount": total_cases,
            "metricCaseCount": len(metric_results),
            # PRD Phase 8 task 2: how many cases hit the text-hash fixture
            # cache (no re-split / no embedding-index rebuild).
            "fixtureReuseCount": len(fixture_reuse_count),
            "fixtureBuildCount": total_cases - len(fixture_reuse_count),
            "unscoredCount": unscored_count,
            "skipReasons": skip_reasons or None,
            "scorerVersions": sorted({
                str(r.get("scorerVersion"))
                for r in per_case_results
                if r.get("scorerVersion")
            }),
            "passedCount": success_count,
            "failedCount": failed_count,
            "infraFailedCount": infra_failed_count,
            "limitedCount": limited_count,
            "findingCount": finding_count,
            "dualCitationCount": dual_citation_count,
            "contractCitationMissingCount": contract_citation_missing_count,
            "policyCitationMissingCount": policy_citation_missing_count,
            "uncitedFindingCount": uncited_finding_count,
            "resultValid": eval_status == "COMPLETED",
            "environment": env_snapshot,
            "evaluationTaskPlan": task_plan,
            "rerankRequested": requested_rerank,
            "rerankActualMethods": rerank_methods,
            "rerankFallbackCount": rerank_fallback_count,
            "actualRuntimeEngine": actual_engine or "",
            "runtimeEngineMismatch": _eval_runtime_mismatch(runtime, actual_engine),
            "operations": operations,
            "percent": 100,
        }
        summary_payload["releaseGate"] = build_release_gate(summary_payload, status=eval_status)
        summary = _json_safe(summary_payload)
        current_step = {
            "FAILED": f"Evaluation failed: {failed_count}/{total_cases} cases failed",
            "DEGRADED": "Evaluation completed with limited results",
            "ENVIRONMENT_UNAVAILABLE": "Evaluation environment unavailable",
        }.get(eval_status, "Evaluation completed")
        with _conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    UPDATE agent_eval_run
                    SET status=%s, high_risk_recall=%s, dual_citation_rate=%s,
                        false_positive_rate=%s, schema_valid_rate=%s,
                        case_count=%s, passed_count=%s, current_step=%s,
                        summary_json=%s, latency_p50_ms=%s, latency_p95_ms=%s,
                        token_input_total=%s, token_output_total=%s,
                        estimated_cost=%s, cost_currency=%s, cost_status=%s,
                        execution_stack_json=%s, finished_at=NOW()
                    WHERE id=%s
                    """, (
                    eval_status,
                    avg_recall,
                    avg_dual_cite,
                    avg_false_pos,
                    avg_schema_valid,
                    total_cases,
                    success_count,
                        current_step,
                    summary,
                    operations.get("latencyP50Ms"),
                    operations.get("latencyP95Ms"),
                    operations.get("tokenInputTotal"),
                    operations.get("tokenOutputTotal"),
                    operations.get("estimatedCost"),
                    operations.get("costCurrency"),
                    operations.get("costStatus"),
                    _json_safe(operations.get("executionStack") or {}),
                    eval_run_id,
                ))
                conn.commit()
    except Exception as exc:
        logger.exception("Eval run %s background task failed", eval_run_id)
        _fail_eval_run(eval_run_id, str(exc)[:500])
    finally:
        if temp_case_ids:
            try:
                _cleanup_eval_search_indexes(temp_case_ids)
                placeholders = ",".join(["%s"] * len(temp_case_ids))
                with _conn() as conn:
                    with conn.cursor() as cur:
                        cur.execute(
                            f"UPDATE contract_case SET deleted=1, is_evaluation=1 WHERE id IN ({placeholders})",
                            temp_case_ids,
                        )
                        conn.commit()
            except Exception:
                logger.exception("Could not clean evaluation temp cases")

    logger.info("Eval run %s completed: recall=%.3f, %d/%d passed", eval_run_id, avg_recall, success_count, total_cases)


@kb_router.post("/qa/test")
async def kb_qa_test(request: KbQaRequest):
    return get_kb().qa_test(
        request.message,
        space_id=request.spaceId,
        document_id=request.documentId,
        top_k=request.topK,
    )
