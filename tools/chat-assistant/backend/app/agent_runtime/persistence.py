"""Agent Runtime persistence — 5 store interfaces + MySQL implementations.

All database access is concentrated here. Tools, runner, and recovery modules
never embed raw SQL.
"""

from __future__ import annotations

import asyncio
import json
import logging
from abc import ABC, abstractmethod

import pymysql
from dbutils.pooled_db import PooledDB
from pymysql.cursors import DictCursor

from app.config import settings

logger = logging.getLogger(__name__)


# ── helpers ──────────────────────────────────────────────────────────

from decimal import Decimal
from datetime import date, datetime

_pool: PooledDB | None = None


def _get_pool() -> PooledDB:
    """Return the module-level connection pool (lazy initialisation)."""
    global _pool
    if _pool is None:
        _pool = PooledDB(
            creator=pymysql,
            maxconnections=12,
            mincached=2,
            maxcached=6,
            blocking=True,
            ping=1,  # ping MySQL before using connection
            host=settings.mysql_host,
            port=settings.mysql_port,
            user=settings.mysql_user,
            password=settings.mysql_password,
            database=settings.mysql_db,
            charset="utf8mb4",
            cursorclass=DictCursor,
            autocommit=False,
        )
    return _pool


def _conn():
    """Borrow a connection from the pool (drop-in replacement for direct pymysql.connect)."""
    return _get_pool().connection()


def new_connection():
    """Create a dedicated connection for long-running document pipelines.

    A document parse can hold a connection while waiting on an external parser,
    LLM, embedding provider, or Elasticsearch. It must not consume a slot from
    the shared Agent Runtime pool while doing so.
    """
    return pymysql.connect(
        host=settings.mysql_host,
        port=settings.mysql_port,
        user=settings.mysql_user,
        password=settings.mysql_password,
        database=settings.mysql_db,
        charset="utf8mb4",
        cursorclass=DictCursor,
        autocommit=False,
        connect_timeout=10,
        read_timeout=60,
        write_timeout=60,
    )


def _normalize_value(obj):
    """Recursively convert Decimal → float, datetime/date → isoformat string."""
    if isinstance(obj, Decimal):
        return float(obj)
    if isinstance(obj, (date, datetime)):
        return obj.isoformat()
    if isinstance(obj, dict):
        return {k: _normalize_value(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_normalize_value(v) for v in obj]
    return obj


def _json_default(obj):
    """Convert non-JSON-serialisable types (Decimal, datetime, etc.) to primitives."""
    if isinstance(obj, Decimal):
        return float(obj)
    if isinstance(obj, (date, datetime)):
        return obj.isoformat()
    raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")


def _json_dumps(obj, **kwargs):
    """json.dumps with Decimal/datetime support."""
    return json.dumps(obj, ensure_ascii=False, default=_json_default, **kwargs)


def _json_object(value):
    if isinstance(value, dict):
        return value
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, dict) else {}
        except Exception:
            return {}
    return {}


def _sanitize_fulfillment_requirements(value):
    if not isinstance(value, list):
        return value
    sanitized = []
    for item in value:
        if not isinstance(item, dict):
            sanitized.append(item)
            continue
        row = dict(item)
        has_contract_source = bool(
            row.get("sourceQuote")
            or row.get("contractQuote")
            or row.get("contractCitation")
            or row.get("citation")
        )
        if row.get("required") is True and not has_contract_source:
            row["required"] = False
            gap = str(row.get("gap") or "").strip()
            note = "缺少合同原文依据，已按辅助项处理，需人工复核。"
            row["gap"] = f"{gap}；{note}" if gap else note
        judgement = str(row.get("judgement") or row.get("judgment") or "")
        requirement = str(row.get("requirement") or "")
        if any(term in requirement + judgement for term in ("满意", "按甲方要求", "符合要求", "另行确认")):
            row.setdefault("judgement", "条款不明确，需要人工复核")
        sanitized.append(row)
    return sanitized


def _finding_rule_key(finding: dict) -> str:
    policy = _json_object(finding.get("policyCitation") or finding.get("policy_citation"))
    return str(
        finding.get("ruleKey")
        or finding.get("rule_key")
        or policy.get("ruleKey")
        or policy.get("rule_key")
        or ""
    ).strip()


def _finding_clause_type(finding: dict) -> str:
    policy = _json_object(finding.get("policyCitation") or finding.get("policy_citation"))
    return str(
        finding.get("clauseType")
        or finding.get("clause_type")
        or policy.get("clauseType")
        or policy.get("clause_type")
        or "OTHER"
    ).strip().upper()


async def _run_sync(fn, *args):
    """Run a synchronous DB call in the default thread-pool executor."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, fn, *args)


# ── interface: RunStore ──────────────────────────────────────────────

class RunStore(ABC):
    """Run lifecycle, heartbeat, and recovery queries."""

    @abstractmethod
    async def get_run(self, run_id: int) -> dict:
        ...

    @abstractmethod
    async def update_run(
        self,
        run_id: int,
        *,
        status: str | None = None,
        progress: int | None = None,
        current_step: str | None = None,
        error_message: str | None = None,
        limited_diagnostics: dict | None = None,
    ) -> None:
        ...

    @abstractmethod
    async def set_runtime_metadata(
        self,
        run_id: int,
        *,
        runtime_engine: str,
        graph_name: str,
        graph_version: str,
        model: str,
        prompt_version: str,
        retrieval_version: str = "",
        rerank_version: str = "",
        scorer_version: str = "",
    ) -> None:
        """Persist runtime identity before a graph reaches its first checkpoint.

        PRD Phase 8 / §10: retrieval/rerank/scorer versions freeze the full
        stack behind a run so evaluation results stay traceable.
        """
        ...

    @abstractmethod
    async def heartbeat(self, run_id: int) -> None:
        ...

    @abstractmethod
    async def find_timed_out_runs(
        self,
        timeout_seconds: int,
        statuses: tuple[str, ...] | None = None,
        require_stale_heartbeat: bool = False,
    ) -> list[int]:
        """Return runs older than *timeout_seconds* in *statuses*.

        With *require_stale_heartbeat*, a run whose heartbeat is still fresh
        is considered alive regardless of age — long graph runs (e.g. the v2
        pilot's >900s cases) are only killed when their heartbeat is lost.
        """
        ...

    @abstractmethod
    async def find_zombie_runs(self, max_heartbeat_age_seconds: int) -> list[int]:
        ...

    @abstractmethod
    async def get_run_detail(self, run_id: int) -> dict:
        """Return {run, traces, toolCalls, report, actions, memories}."""
        ...


# ── interface: TraceStore ────────────────────────────────────────────

class TraceStore(ABC):
    """Execution trace + tool-call records."""

    @abstractmethod
    async def append_trace(
        self, run_id: int, event_type: str, summary: str, payload: dict | None = None
    ) -> None:
        ...

    @abstractmethod
    async def save_tool_call_start(
        self,
        run_id: int,
        plan_step_id: str,
        call_id: str,
        tool_name: str,
        input_json: str,
    ) -> None:
        ...

    @abstractmethod
    async def save_tool_call_done(
        self,
        run_id: int,
        call_id: str,
        tool_name: str,
        output_json: str,
        latency_ms: int,
    ) -> None:
        ...

    @abstractmethod
    async def save_tool_call_failed(
        self,
        run_id: int,
        call_id: str,
        tool_name: str,
        error_message: str,
        latency_ms: int,
    ) -> None:
        ...

    @abstractmethod
    async def get_traces(self, run_id: int) -> list[dict]:
        ...

    @abstractmethod
    async def get_tool_calls(self, run_id: int) -> list[dict]:
        ...


# ── interface: EvidenceStore ─────────────────────────────────────────

class EvidenceStore(ABC):
    """Tool data sources: evidence, knowledge, project memory, history."""

    @abstractmethod
    async def search_evidence(
        self, project_id: int, arguments: dict
    ) -> list[dict]:
        ...

    @abstractmethod
    async def search_knowledge(
        self, project_id: int, question: str, arguments: dict
    ) -> list[dict]:
        ...

    @abstractmethod
    async def project_memory(
        self, project_id: int, arguments: dict
    ) -> list[dict]:
        ...

    @abstractmethod
    async def recent_runs(
        self, project_id: int, current_run_id: int, arguments: dict
    ) -> list[dict]:
        ...

    @abstractmethod
    async def search_source_code(
        self, project_id: int, arguments: dict
    ) -> list[dict]:
        """Search synced source code evidence by keyword + optional file pattern."""
        ...

    @abstractmethod
    async def semantic_memory_search(
        self, project_id: int, query: str, arguments: dict
    ) -> list[dict]:
        """Return memory entries ranked by semantic similarity (vector index) + keyword filter."""
        ...

    @abstractmethod
    async def canonical_evidence(self, project_id: int) -> list[dict]:
        """Load up to 500 evidence rows for deterministic scoring."""
        ...


# ── interface: ReportStore ───────────────────────────────────────────

class ReportStore(ABC):
    """Report persistence and queries."""

    @abstractmethod
    async def save_report(
        self, project_id: int, run_id: int, task_type: str, artifact: dict
    ) -> int:
        """Persist a DRAFT report + PENDING_APPROVAL action. Returns report_id."""
        ...

    @abstractmethod
    async def get_report(self, run_id: int) -> dict | None:
        ...

    @abstractmethod
    async def latest_report(
        self, project_id: int, arguments: dict
    ) -> dict:
        ...


# ── interface: MemoryStore ───────────────────────────────────────────

class MemoryStore(ABC):
    """Episodic memory persistence."""

    @abstractmethod
    async def save_memory(
        self,
        project_id: int,
        run_id: int,
        memory_type: str,
        title: str,
        content: str,
        source_id: str,
        confirmed: bool = False,
    ) -> None:
        ...


# ══════════════════════════════════════════════════════════════════════
#  MySQL implementations
# ══════════════════════════════════════════════════════════════════════

class MySqlRunStore(RunStore):
    async def get_run(self, run_id: int) -> dict:
        def _get():
            with _conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """SELECT id, project_id AS projectId, subject_type AS subjectType,
                                  subject_id AS subjectId, run_type AS runType,
                                  trigger_type AS triggerType, question, status,
                                  progress, current_step AS currentStep,
                                  error_message AS errorMessage,
                                  limited_diagnostics AS limitedDiagnostics,
                                  workflow_id AS workflowId, workflow_stage AS workflowStage,
                                  evidence_snapshot_hash AS evidenceSnapshotHash,
                                  runtime_engine AS runtimeEngine, graph_name AS graphName,
                                  graph_version AS graphVersion, model,
                                  prompt_version AS promptVersion,
                                  retrieval_version AS retrievalVersion,
                                  rerank_version AS rerankVersion,
                                  scorer_version AS scorerVersion,
                                  started_at AS startedAt, finished_at AS finishedAt,
                                  create_time AS createTime, update_time AS updateTime
                           FROM agent_run WHERE id=%s""",
                        (run_id,),
                    )
                    row = cur.fetchone() or {}
                    if row:
                        row["limitedDiagnostics"] = (
                            _json_object(row.get("limitedDiagnostics")) or None
                        )
                    return row

        return await _run_sync(_get)

    async def update_run(
        self,
        run_id: int,
        *,
        status: str | None = None,
        progress: int | None = None,
        current_step: str | None = None,
        error_message: str | None = None,
        limited_diagnostics: dict | None = None,
    ) -> None:
        def _update():
            sets = []
            params: list = []
            if status is not None:
                sets.append("status=%s")
                params.append(status)
                if status in ("COMPLETED", "FAILED", "CANCELLED", "LIMITED"):
                    sets.append("finished_at=NOW()")
                # set started_at on first transition out of CREATED
                sets.append("started_at=IF(started_at IS NULL AND %s NOT IN ('CREATED'), NOW(), started_at)")
                params.append(status)
            if progress is not None:
                sets.append("progress=%s")
                params.append(progress)
            if current_step is not None:
                sets.append("current_step=%s")
                params.append(current_step)
            if limited_diagnostics is not None:
                # §6.4: the run row carries the LIMITED disclosure — the
                # stable read entry behind "详见运行诊断" (get_run /
                # get_run_detail return it as limitedDiagnostics).
                sets.append("limited_diagnostics=%s")
                params.append(_json_dumps(limited_diagnostics))
            if error_message is not None:
                sets.append("error_message=%s")
                params.append(error_message[:4000] if error_message else "")
            elif error_message is None and status is not None:
                # Clear error when transitioning to a non-FAILED status
                sets.append("error_message=IF(%s='FAILED', error_message, NULL)")
                params.append(status)
            if not sets:
                return
            params.append(run_id)
            with _conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        f"UPDATE agent_run SET {', '.join(sets)} WHERE id=%s", params
                    )
                    if status in ("COMPLETED", "FAILED", "CANCELLED", "LIMITED"):
                        cur.execute(
                            "SELECT workflow_id AS workflowId, run_type AS runType FROM agent_run WHERE id=%s",
                            (run_id,),
                        )
                        workflow = cur.fetchone() or {}
                        workflow_id = workflow.get("workflowId")
                        # The analysis workflow's terminal state belongs to
                        # risk review. Element extraction and fulfillment use
                        # the same linkage for provenance, but must not make a
                        # not-yet-reviewed contract look completed or failed.
                        if workflow_id and str(workflow.get("runType") or "").upper() == "CONTRACT_REVIEW":
                            workflow_status = (
                                "COMPLETED" if status == "COMPLETED"
                                else "LIMITED" if status == "LIMITED"
                                else "FAILED"
                            )
                            cur.execute(
                                """UPDATE contract_analysis_workflow
                                   SET status=%s, current_stage='RISK_REVIEW',
                                       last_error=%s
                                   WHERE id=%s""",
                                (workflow_status, error_message[:4000] if error_message else None, workflow_id),
                            )
                conn.commit()

        await _run_sync(_update)

    async def set_runtime_metadata(
        self,
        run_id: int,
        *,
        runtime_engine: str,
        graph_name: str,
        graph_version: str,
        model: str,
        prompt_version: str,
        retrieval_version: str = "",
        rerank_version: str = "",
        scorer_version: str = "",
    ) -> None:
        def _update():
            try:
                with _conn() as conn:
                    with conn.cursor() as cur:
                        cur.execute(
                            """UPDATE agent_run
                               SET runtime_engine=%s,
                                   graph_name=%s,
                                   graph_version=%s,
                                   model=%s,
                                   prompt_version=%s,
                                   retrieval_version=%s,
                                   rerank_version=%s,
                                   scorer_version=%s
                               WHERE id=%s""",
                            (
                                str(runtime_engine or "")[:32],
                                str(graph_name or "")[:64],
                                str(graph_version or "")[:32],
                                str(model or "")[:128],
                                str(prompt_version or "")[:64],
                                str(retrieval_version or "")[:64],
                                str(rerank_version or "")[:64],
                                str(scorer_version or "")[:64],
                                run_id,
                            ),
                        )
                    conn.commit()
            except Exception as exc:
                # Older databases may not yet have the optional runtime columns.
                logger.debug("Agent runtime metadata update skipped: %s", exc)

        await _run_sync(_update)

    async def heartbeat(self, run_id: int) -> None:
        def _beat():
            with _conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "UPDATE agent_run SET last_heartbeat_at=NOW() WHERE id=%s",
                        (run_id,),
                    )
                conn.commit()

        await _run_sync(_beat)

    async def find_timed_out_runs(
        self,
        timeout_seconds: int,
        statuses: tuple[str, ...] | None = None,
        require_stale_heartbeat: bool = False,
    ) -> list[int]:
        def _find():
            selected_statuses = statuses or (
                "CREATED", "CONTEXT_BUILDING", "PLANNING", "ANALYZING", "VERIFYING",
            )
            placeholders = ",".join(["%s"] * len(selected_statuses))
            heartbeat_clause = ""
            if require_stale_heartbeat:
                # Alive-if-heartbeating: only runs without a heartbeat at all
                # (pre-heartbeat dispatch paths) or with a lost heartbeat are
                # eligible. Runs actively heartbeating are never "timed out".
                heartbeat_clause = (
                    "AND (last_heartbeat_at IS NULL"
                    " OR last_heartbeat_at < DATE_SUB(NOW(), INTERVAL %s SECOND))"
                )
            with _conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        f"""SELECT id FROM agent_run
                            WHERE status IN ({placeholders})
                              AND create_time < DATE_SUB(NOW(), INTERVAL %s SECOND)
                              {heartbeat_clause}""",
                        (*selected_statuses, timeout_seconds,
                         *((timeout_seconds,) if require_stale_heartbeat else ())),
                    )
                    return [row["id"] for row in cur.fetchall()]

        return await _run_sync(_find)

    async def find_zombie_runs(self, max_heartbeat_age_seconds: int) -> list[int]:
        def _find():
            with _conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """SELECT id FROM agent_run
                           WHERE status IN ('CONTEXT_BUILDING','PLANNING','ANALYZING','VERIFYING')
                             AND ((last_heartbeat_at IS NOT NULL
                                   AND last_heartbeat_at < DATE_SUB(NOW(), INTERVAL %s SECOND))
                                  OR (last_heartbeat_at IS NULL
                                      AND COALESCE(started_at, create_time)
                                          < DATE_SUB(NOW(), INTERVAL %s SECOND)))""",
                        (max_heartbeat_age_seconds, max_heartbeat_age_seconds),
                    )
                    return [row["id"] for row in cur.fetchall()]

        return await _run_sync(_find)

    async def get_run_detail(self, run_id: int) -> dict:
        return await _run_sync(self._get_detail_sync, run_id)

    @staticmethod
    def _get_detail_sync(run_id: int) -> dict:
        with _conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """SELECT id, project_id AS projectId, run_type AS runType,
                              trigger_type AS triggerType, question, status, progress,
                              current_step AS currentStep, error_message AS errorMessage,
                              limited_diagnostics AS limitedDiagnostics,
                              workflow_id AS workflowId, workflow_stage AS workflowStage,
                              evidence_snapshot_hash AS evidenceSnapshotHash,
                              started_at AS startedAt, finished_at AS finishedAt,
                              create_time AS createTime
                       FROM agent_run WHERE id=%s""",
                    (run_id,),
                )
                run = cur.fetchone()
                if not run:
                    return {}
                run["limitedDiagnostics"] = (
                    _json_object(run.get("limitedDiagnostics")) or None
                )

                # traces
                cur.execute(
                    """SELECT id, event_type AS eventType, sequence_no AS sequenceNo,
                              summary, payload_json AS payloadJson, create_time AS createTime
                       FROM agent_run_trace WHERE run_id=%s ORDER BY sequence_no""",
                    (run_id,),
                )
                traces = list(cur.fetchall())

                # tool calls
                cur.execute(
                    """SELECT id, plan_step_id AS planStepId, call_id AS callId,
                              tool_name AS toolName, input_json AS inputJson,
                              output_json AS outputJson, status, latency_ms AS latencyMs,
                              error_message AS errorMessage, create_time AS createTime
                       FROM agent_tool_call WHERE run_id=%s ORDER BY id""",
                    (run_id,),
                )
                tool_calls = list(cur.fetchall())

                # report
                cur.execute(
                    """SELECT id, report_type AS reportType, title, summary,
                              health_status AS healthStatus, health_score AS healthScore,
                              dimensions_json AS dimensionsJson, risks_json AS risksJson,
                              plan_json AS planJson, citations_json AS citationsJson,
                              scoring_version AS scoringVersion, evidence_hash AS evidenceHash,
                              analysis_mode AS analysisMode, content_json AS contentJson,
                              report_markdown AS reportMarkdown, status
                       FROM agent_report WHERE run_id=%s LIMIT 1""",
                    (run_id,),
                )
                report = cur.fetchone()

                # actions
                cur.execute(
                    """SELECT id, action_type AS actionType, status, title,
                              payload_json AS payloadJson, external_id AS externalId,
                              approved_by AS approvedBy, approved_at AS approvedAt,
                              executed_at AS executedAt, error_message AS errorMessage,
                              create_time AS createTime
                       FROM agent_action WHERE run_id=%s ORDER BY id""",
                    (run_id,),
                )
                actions = list(cur.fetchall())

                # memories
                cur.execute(
                    """SELECT id, memory_type AS memoryType, title, content,
                              source_type AS sourceType, source_id AS sourceId,
                              confirmed, create_time AS createTime
                       FROM agent_project_memory
                       WHERE source_type='AGENT_RUN' AND source_id=%s
                       ORDER BY id DESC""",
                    (str(run_id),),
                )
                memories = list(cur.fetchall())

                return {
                    "run": run,
                    "traces": traces,
                    "toolCalls": tool_calls,
                    "report": report,
                    "actions": actions,
                    "memories": memories,
                }


class MySqlTraceStore(TraceStore):
    async def append_trace(
        self, run_id: int, event_type: str, summary: str, payload: dict | None = None
    ) -> None:
        await _run_sync(self._append_sync, run_id, event_type, summary, payload)

    @staticmethod
    def _append_sync(run_id, event_type, summary, payload):
        with _conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT id FROM agent_run WHERE id=%s FOR UPDATE",
                    (run_id,),
                )
                if cur.fetchone() is None:
                    raise ValueError(f"Agent run {run_id} not found while appending trace")
                cur.execute(
                    "SELECT COALESCE(MAX(sequence_no), 0) + 1 AS seq FROM agent_run_trace WHERE run_id=%s",
                    (run_id,),
                )
                seq = (cur.fetchone() or {}).get("seq", 1)
                cur.execute(
                    """INSERT INTO agent_run_trace (run_id, event_type, sequence_no, summary, payload_json)
                       VALUES (%s, %s, %s, %s, %s)""",
                    (
                        run_id,
                        event_type,
                        seq,
                        (summary or "")[:500],
                        _json_dumps(payload) if payload else "{}",
                    ),
                )
            conn.commit()

    async def save_tool_call_start(
        self, run_id: int, plan_step_id: str, call_id: str, tool_name: str, input_json: str
    ) -> None:
        await _run_sync(self._start_sync, run_id, plan_step_id, call_id, tool_name, input_json)

    @staticmethod
    def _start_sync(run_id, plan_step_id, call_id, tool_name, input_json):
        with _conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """INSERT INTO agent_tool_call
                       (run_id, plan_step_id, call_id, tool_name, input_json, status)
                       VALUES (%s, %s, %s, %s, %s, 'RUNNING')""",
                    (run_id, plan_step_id, call_id, tool_name, input_json),
                )
            conn.commit()

    async def save_tool_call_done(
        self, run_id: int, call_id: str, tool_name: str, output_json: str, latency_ms: int
    ) -> None:
        await _run_sync(self._done_sync, run_id, call_id, tool_name, output_json, latency_ms)

    @staticmethod
    def _done_sync(run_id, call_id, tool_name, output_json, latency_ms):
        with _conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """UPDATE agent_tool_call
                       SET status='DONE', output_json=%s, latency_ms=%s, error_message=NULL
                       WHERE run_id=%s AND call_id=%s""",
                    (output_json, latency_ms, run_id, call_id),
                )
            conn.commit()

    async def save_tool_call_failed(
        self, run_id: int, call_id: str, tool_name: str, error_message: str, latency_ms: int
    ) -> None:
        await _run_sync(self._failed_sync, run_id, call_id, tool_name, error_message, latency_ms)

    @staticmethod
    def _failed_sync(run_id, call_id, tool_name, error_message, latency_ms):
        with _conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """UPDATE agent_tool_call
                       SET status='FAILED', latency_ms=%s, error_message=%s
                       WHERE run_id=%s AND call_id=%s""",
                    (latency_ms, (error_message or "")[:4000], run_id, call_id),
                )
            conn.commit()

    async def get_traces(self, run_id: int) -> list[dict]:
        def _get():
            with _conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """SELECT id, event_type AS eventType, sequence_no AS sequenceNo,
                                  summary, create_time AS createTime
                           FROM agent_run_trace WHERE run_id=%s ORDER BY sequence_no""",
                        (run_id,),
                    )
                    return list(cur.fetchall())

        return await _run_sync(_get)

    async def get_tool_calls(self, run_id: int) -> list[dict]:
        def _get():
            with _conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """SELECT id, tool_name AS toolName, status, latency_ms AS latencyMs,
                                  error_message AS errorMessage, create_time AS createTime
                           FROM agent_tool_call WHERE run_id=%s ORDER BY id""",
                        (run_id,),
                    )
                    return list(cur.fetchall())

        return await _run_sync(_get)


class MySqlEvidenceStore(EvidenceStore):
    async def search_source_code(
        self, project_id: int, arguments: dict
    ) -> list[dict]:
        return await _run_sync(self._source_code_sync, project_id, arguments)

    @staticmethod
    def _source_code_sync(project_id, arguments):
        limit = max(1, min(15, int(arguments.get("limit", 8))))
        query = str(arguments.get("query", "")).lower()
        file_pattern = str(arguments.get("filePattern", ""))
        with _conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """SELECT id AS sourceId, source_type AS sourceType,
                              object_type AS objectType, title, source_ref AS sourceRef,
                              source_url AS sourceUrl, content_snippet AS snippet,
                              confidence_score AS score, observed_at AS observedAt
                       FROM project_evidence
                       WHERE project_id=%s
                         AND object_type IN ('SOURCE', 'FILE', 'README')
                       ORDER BY confidence_score DESC, update_time DESC
                       LIMIT 200""",
                    (project_id,),
                )
                rows = list(cur.fetchall())
        filtered = []
        for row in rows:
            if query:
                haystack = (
                    str(row.get("title", "")) + " "
                    + str(row.get("sourceRef", "")) + " "
                    + str(row.get("snippet", ""))
                ).lower()
                if query not in haystack:
                    continue
            if file_pattern:
                fp = file_pattern.lower().lstrip("*")
                if fp and fp not in str(row.get("title", "")).lower():
                    continue
            filtered.append(row)
            if len(filtered) >= limit:
                break
        return [_normalize_value(r) for r in filtered]

    async def search_evidence(self, project_id: int, arguments: dict) -> list[dict]:
        return await _run_sync(self._search_sync, project_id, arguments)

    @staticmethod
    def _search_sync(project_id, arguments):
        limit = max(1, min(20, int(arguments.get("limit", 8))))
        query = str(arguments.get("query", "")).lower()
        requested = {
            t.upper()
            for t in (arguments.get("objectTypes") or [])
            if isinstance(t, str)
        }
        with _conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """SELECT id AS sourceId, source_type AS sourceType,
                              object_type AS objectType, title, source_ref AS sourceRef,
                              source_url AS sourceUrl, content_snippet AS snippet,
                              confidence_score AS score, observed_at AS observedAt
                       FROM project_evidence
                       WHERE project_id=%s
                       ORDER BY confidence_score DESC, update_time DESC
                       LIMIT 100""",
                    (project_id,),
                )
                rows = list(cur.fetchall())

        filtered = []
        for row in rows:
            obj_type = str(row.get("objectType", "")).upper()
            if requested and obj_type not in requested:
                continue
            if query:
                haystack = (
                    str(row.get("title", ""))
                    + " "
                    + str(row.get("sourceRef", ""))
                    + " "
                    + str(row.get("snippet", ""))
                ).lower()
                if query not in haystack:
                    continue
            filtered.append(row)
            if len(filtered) >= limit:
                break

        if not filtered and not query:
            filtered = [r for r in rows if not requested or str(r.get("objectType", "")).upper() in requested][:limit]
        elif not filtered:
            filtered = [r for r in rows if not requested or str(r.get("objectType", "")).upper() in requested][:limit]

        return [_normalize_value(r) for r in filtered]

    async def search_knowledge(
        self, project_id: int, question: str, arguments: dict
    ) -> list[dict]:
        return await _run_sync(self._search_kb_sync, project_id, question, arguments)

    @staticmethod
    def _search_kb_sync(project_id, question, arguments):
        limit = max(1, min(10, int(arguments.get("limit", 5))))
        query = str(arguments.get("query", "")).strip()
        if not query:
            query = question

        with _conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """SELECT d.id, d.title, s.name AS spaceName
                       FROM project_kb_document pkd
                       JOIN kb_document d ON d.id = pkd.document_id
                       JOIN kb_space s ON s.id = d.space_id
                       WHERE pkd.project_id=%s AND d.deleted=0 AND d.status='READY'
                         AND s.deleted=0 AND s.enabled=1
                       ORDER BY pkd.create_time DESC, d.update_time DESC
                       LIMIT 8""",
                    (project_id,),
                )
                documents = list(cur.fetchall())

        # Delegate to ES for actual chunk retrieval
        results = []
        try:
            from app.services.es_service import ESService

            es = ESService()
            for doc in documents:
                if len(results) >= limit:
                    break
                remaining = limit - len(results)
                try:
                    hits = es.search_kb_by_keyword(
                        query, top_k=min(3, remaining), document_id=doc["id"]
                    )
                except Exception:
                    hits = []
                for hit in hits:
                    if len(results) >= limit:
                        break
                    hit["sourceType"] = "DOCUMENT"
                    hit["objectType"] = "KB_DOCUMENT"
                    hit["sourceId"] = str(doc["id"])
                    hit["sourceRef"] = f"{doc.get('spaceName', '')} / {doc.get('title', '')}"
                    hit.setdefault("title", doc.get("title", ""))
                    if "content" in hit and "snippet" not in hit:
                        hit["snippet"] = hit["content"]
                    results.append(hit)
        except Exception:
            logger.exception("ES knowledge search failed")

        return results

    async def project_memory(self, project_id: int, arguments: dict) -> list[dict]:
        return await _run_sync(self._memory_sync, project_id, arguments)

    @staticmethod
    def _memory_sync(project_id, arguments):
        limit = max(1, min(20, int(arguments.get("limit", 10))))
        with _conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """SELECT id, memory_type AS memoryType, title, content,
                              source_type AS sourceType, source_id AS sourceId,
                              confirmed, create_time AS createTime
                       FROM agent_project_memory
                       WHERE project_id=%s
                       ORDER BY confirmed DESC, update_time DESC
                       LIMIT %s""",
                    (project_id, limit),
                )
                return list(cur.fetchall())

    async def recent_runs(
        self, project_id: int, current_run_id: int, arguments: dict
    ) -> list[dict]:
        return await _run_sync(self._runs_sync, project_id, current_run_id, arguments)

    @staticmethod
    def _runs_sync(project_id, current_run_id, arguments):
        limit = max(1, min(10, int(arguments.get("limit", 5))))
        with _conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """SELECT id, run_type AS runType, question, status,
                              current_step AS currentStep, error_message AS errorMessage,
                              create_time AS createTime
                       FROM agent_run
                       WHERE project_id=%s AND id <> %s
                       ORDER BY id DESC LIMIT %s""",
                    (project_id, current_run_id, limit),
                )
                return list(cur.fetchall())

    async def semantic_memory_search(
        self, project_id: int, query: str, arguments: dict
    ) -> list[dict]:
        """Semantic search over project memory via MemoryVectorIndex."""
        limit = max(1, min(20, int(arguments.get("limit", 5))))
        keyword = str(arguments.get("keyword", ""))

        from .memory_index import get_memory_index
        index = get_memory_index()
        results = await index.search(
            project_id, query, top_k=limit, keyword_filter=keyword,
        )
        return results

    async def canonical_evidence(self, project_id: int) -> list[dict]:
        def _load():
            with _conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """SELECT id AS sourceId, source_type AS sourceType,
                                  object_type AS objectType, title, source_ref AS sourceRef,
                                  source_url AS sourceUrl, content_snippet AS snippet,
                                  confidence_score AS score, observed_at AS observedAt
                           FROM project_evidence
                           WHERE project_id=%s
                           ORDER BY object_type, source_ref, evidence_hash
                           LIMIT 500""",
                        (project_id,),
                    )
                    return [_normalize_value(r) for r in cur.fetchall()]

        return await _run_sync(_load)


class MySqlReportStore(ReportStore):
    _PROJECT_ACTION_TYPES = {
        "CREATE_GITHUB_ISSUE",
        "UPDATE_PROJECT_CONFIG",
        "CREATE_GITHUB_MILESTONE",
    }
    _CONTRACT_ACTION_TYPES = {
        "CREATE_NEGOTIATION_TASK",
        "REQUEST_MATERIAL",
        "REQUEST_LEGAL_REVIEW",
        "SCHEDULE_REMINDER",
    }

    async def save_report(
        self, project_id: int, run_id: int, task_type: str, artifact: dict
    ) -> int:
        return await _run_sync(self._save_sync, project_id, run_id, task_type, artifact)

    _REPORT_TYPE_MAP = {
        "HEALTH_ANALYSIS": "HEALTH_REPORT",
        "PROJECT_ONBOARDING": "ONBOARDING_GUIDE",
        "ENGINEERING_DECISION": "DECISION_MEMO",
        # Contract task types
        "CONTRACT_REVIEW": "CONTRACT_REVIEW_REPORT",
        "CONTRACT_INTAKE": "CONTRACT_INTAKE_REPORT",
        "APPROVAL_DECISION": "APPROVAL_MEMO",
        "VERSION_REVIEW": "VERSION_REVIEW_REPORT",
        "OBLIGATION_EXTRACTION": "OBLIGATION_PLAN",
        "TIMELINE_EXTRACTION": "TIMELINE_EXTRACTION_REPORT",
        "FULFILLMENT_CHECK": "FULFILLMENT_REPORT",
        "RENEWAL_ASSESSMENT": "RENEWAL_MEMO",
        "RULE_IMPACT_REVIEW": "RULE_IMPACT_REPORT",
        "NEGOTIATION_STRATEGY": "NEGOTIATION_STRATEGY_MEMO",
        "FULFILLMENT_BREACH_ANALYSIS": "BREACH_ASSESSMENT_REPORT",
        "RULE_EFFECTIVENESS_REVIEW": "RULE_HEALTH_REPORT",
    }

    @staticmethod
    def _save_sync(project_id, run_id, task_type, artifact):
        is_health = task_type == "HEALTH_ANALYSIS"
        report_type = artifact.get("reportType") or MySqlReportStore._REPORT_TYPE_MAP.get(
            task_type, "HEALTH_REPORT")
        with _conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """SELECT COALESCE(subject_type, 'PROJECT') AS subjectType,
                               COALESCE(subject_id, project_id) AS subjectId,
                               workflow_id AS workflowId
                       FROM agent_run WHERE id=%s""",
                    (run_id,),
                )
                run_subject = cur.fetchone()
                if not run_subject:
                    raise ValueError(f"Agent run {run_id} not found while saving report")
                subject_type = str(run_subject.get("subjectType") or "PROJECT")
                subject_id = int(run_subject.get("subjectId") or project_id)
                report_status = artifact.get("healthStatus") if is_health else artifact.get("riskStatus")
                report_score = artifact.get("healthScore", 0) if is_health else artifact.get("riskScore", 0)
                report_dimensions = artifact.get("dimensions")
                cur.execute(
                    """INSERT INTO agent_report
                       (project_id, run_id, subject_type, subject_id,
                        report_type, title, summary, health_status,
                        health_score, dimensions_json, risks_json, plan_json,
                        citations_json, scoring_version, evidence_hash, analysis_mode,
                        scoring_rationale_json, content_json, report_markdown, status)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'DRAFT')""",
                    (
                        project_id,
                        run_id,
                        subject_type,
                        subject_id,
                        report_type,
                        artifact.get("title", ""),
                        artifact.get("summary", ""),
                        report_status,
                        report_score,
                        _json_dumps(report_dimensions) if report_dimensions else None,
                        _json_dumps(artifact.get("risks")),
                        _json_dumps(artifact.get("plan")),
                        _json_dumps(artifact.get("citations")),
                        artifact.get("scoringVersion"),
                        artifact.get("evidenceHash"),
                        artifact.get("analysisMode"),
                        _json_dumps(artifact.get("scoringRationale")) if artifact.get("scoringRationale") else None,
                        _json_dumps(artifact.get("content", artifact)),
                        artifact.get("reportMarkdown", ""),
                    ),
                )
                report_id = int(cur.lastrowid)

                if subject_type == "CONTRACT_CASE":
                    findings = artifact.get("findings")
                    if isinstance(findings, list):
                        cur.execute(
                            "DELETE FROM contract_review_finding WHERE run_id=%s",
                            (run_id,),
                        )
                        for finding in findings:
                            if not isinstance(finding, dict):
                                continue
                            title = str(
                                finding.get("title")
                                or finding.get("ruleTitle")
                                or "合同审查发现"
                            ).strip()
                            if not title:
                                continue
                            rule_key = _finding_rule_key(finding)
                            clause_type = _finding_clause_type(finding)
                            detail_payload = {
                                key: finding.get(key)
                                for key in (
                                    "findingKey", "domainKey", "domainName", "sourceBasis",
                                    "oneLineSummary", "keyPoint", "riskExplanation",
                                    "businessImpact", "contractBasis", "knowledgeBasis",
                                    "explicitConsequence", "inferredConsequence",
                                    "inferredConsequenceDisclaimer", "revisionAdvice",
                                    "reviewQuestions", "contractCitationIds", "policyCitationIds",
                                    "evidenceStatus", "confidenceLevel", "frontendDisplay",
                                    "validationVerdict", "validationReasons",
                                )
                                if finding.get(key) not in (None, "", [], {})
                            }
                            cur.execute(
                                """INSERT INTO contract_review_finding
                                   (case_id, run_id, rule_id, rule_key, clause_type,
                                    severity, status, title, description, impact,
                                    remediation_advice, negotiation_advice,
                                    verification_points, contract_citation,
                                    policy_citation, suggested_action, detail_json)
                                   VALUES (%s,%s,%s,%s,%s,%s,'OPEN',%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                                (
                                    subject_id,
                                    run_id,
                                    finding.get("ruleId"),
                                    rule_key or None,
                                    clause_type or None,
                                    str(finding.get("severity") or "MEDIUM").upper(),
                                    title[:512],
                                    str(finding.get("description") or finding.get("detail") or ""),
                                    str(finding.get("impact") or finding.get("businessImpact") or ""),
                                    str(
                                        finding.get("remediationAdvice")
                                        or finding.get("recommendedRevision")
                                        or finding.get("remediation")
                                        or ""
                                    ),
                                    str(
                                        finding.get("negotiationAdvice")
                                        or finding.get("negotiationPosition")
                                        or ""
                                    ),
                                    _json_dumps(finding.get("verificationPoints"))
                                    if isinstance(finding.get("verificationPoints"), list) else None,
                                    _json_dumps(finding.get("contractCitation"))
                                    if isinstance(finding.get("contractCitation"), dict) else None,
                                    _json_dumps(finding.get("policyCitation"))
                                    if isinstance(finding.get("policyCitation"), dict) else None,
                                    str(finding.get("suggestedAction") or "") or None,
                                    _json_dumps(detail_payload) if detail_payload else None,
                                ),
                            )
                    if task_type == "CONTRACT_REVIEW":
                        cur.execute(
                            """SELECT COUNT(*) AS cnt FROM contract_review_finding
                               WHERE case_id=%s AND run_id=%s AND status='OPEN'""",
                            (subject_id, run_id),
                        )
                        open_findings = int((cur.fetchone() or {}).get("cnt") or 0)
                        next_status = "NEEDS_REVISION" if open_findings > 0 else "PENDING_APPROVAL"
                        cur.execute(
                            """UPDATE contract_case
                               SET status=%s, last_run_id=%s, last_run_at=NOW()
                               WHERE id=%s AND deleted=0""",
                            (next_status, run_id, subject_id),
                        )
                        if run_subject.get("workflowId"):
                            cur.execute(
                                """UPDATE contract_analysis_workflow
                                   SET status='COMPLETED', current_stage='REPORT_READY', last_error=NULL
                                   WHERE id=%s""",
                                (run_subject.get("workflowId"),),
                            )
                    if task_type == "FULFILLMENT_CHECK":
                        timeline_node_id = int(artifact.get("timelineNodeId") or 0)
                        if timeline_node_id:
                            manual_result = str(
                                (artifact.get("content") or {}).get("manualResult")
                                or artifact.get("manualResult")
                                or ""
                            ).upper()
                            check_status = (
                                "PENDING"
                                if manual_result in {"PENDING", "NEEDS_MORE_EVIDENCE"}
                                else "COMPLETED"
                            )
                            cur.execute(
                                """UPDATE contract_fulfillment_check
                                   SET status=%s,
                                       conclusion=%s,
                                       risk_level=%s,
                                       confidence_level=%s,
                                       summary=%s,
                                       requirement_json=%s,
                                       evidence_snapshot_json=%s,
                                       missing_evidence_json=%s,
                                       explicit_consequence=%s,
                                       ai_risk=%s,
                                       suggested_actions_json=%s
                                   WHERE run_id=%s
                                     AND case_id=%s
                                     AND timeline_node_id=%s""",
                                (
                                    check_status,
                                    str(artifact.get("conclusion") or "NEEDS_REVIEW"),
                                    str(artifact.get("riskLevel") or "MEDIUM"),
                                    str(artifact.get("confidenceLevel") or "LOW"),
                                    str(artifact.get("summary") or ""),
                                    _json_dumps(_sanitize_fulfillment_requirements(
                                        artifact.get("requirements")
                                    )),
                                    _json_dumps(artifact.get("evidenceSnapshot")),
                                    _json_dumps(artifact.get("missingEvidence")),
                                    str(artifact.get("explicitConsequence") or ""),
                                    str(artifact.get("aiRisk") or ""),
                                    _json_dumps(artifact.get("suggestedActions")),
                                    run_id,
                                    subject_id,
                                    timeline_node_id,
                                ),
                            )
                            cur.execute(
                                """SELECT id FROM contract_fulfillment_check
                                   WHERE run_id=%s AND case_id=%s AND timeline_node_id=%s
                                   ORDER BY id DESC LIMIT 1""",
                                (run_id, subject_id, timeline_node_id),
                            )
                            check_row = cur.fetchone() or {}
                            check_id = int(check_row.get("id") or 0)
                            evidence_snapshot = artifact.get("evidenceSnapshot")
                            if check_id and isinstance(evidence_snapshot, list):
                                cur.execute(
                                    "DELETE FROM contract_timeline_evidence_link WHERE check_id=%s",
                                    (check_id,),
                                )
                                for evidence in evidence_snapshot:
                                    if not isinstance(evidence, dict):
                                        continue
                                    document_id = int(evidence.get("documentId") or evidence.get("id") or 0)
                                    if not document_id:
                                        continue
                                    cur.execute(
                                        """INSERT INTO contract_timeline_evidence_link
                                           (case_id, timeline_node_id, document_id, check_id,
                                            link_source, relation_type, evidence_version,
                                            evidence_hash, snippet)
                                           VALUES (%s,%s,%s,%s,'AGENT','FULFILLMENT_EVIDENCE',%s,%s,%s)
                                           ON DUPLICATE KEY UPDATE
                                             evidence_version=VALUES(evidence_version),
                                             evidence_hash=VALUES(evidence_hash),
                                             snippet=VALUES(snippet),
                                             deleted=0""",
                                        (
                                            subject_id,
                                            timeline_node_id,
                                            document_id,
                                            check_id,
                                            evidence.get("version"),
                                            str(evidence.get("contentHash") or evidence.get("hash") or "") or None,
                                            str(evidence.get("snippet") or "")[:1000] or None,
                                        ),
                                    )

                # ── B1: Action Proposals ────────────────────────────
                # Parse actionProposals from the LLM artifact and create
                # one PENDING_APPROVAL row per proposal.
                proposals = artifact.get("actionProposals")
                if isinstance(proposals, list) and proposals:
                    allowed_action_types = (
                        MySqlReportStore._CONTRACT_ACTION_TYPES
                        if subject_type == "CONTRACT_CASE"
                        else MySqlReportStore._PROJECT_ACTION_TYPES
                    )
                    for p in proposals:
                        if not isinstance(p, dict):
                            continue
                        action_type = str(p.get("type") or "").strip().upper()
                        if action_type not in allowed_action_types:
                            logger.warning(
                                "Ignoring unsupported %s action type %s for run %s",
                                subject_type, action_type, run_id,
                            )
                            continue
                        cur.execute(
                            """INSERT INTO agent_action
                               (project_id, run_id, subject_type, subject_id,
                                action_type, status, title, payload_json)
                               VALUES (%s,%s,%s,%s,%s,'PENDING_APPROVAL',%s,%s)""",
                            (
                                project_id, run_id, subject_type, subject_id, action_type,
                                str(p.get("title", artifact.get("title", ""))),
                                _json_dumps({
                                    "description": str(p.get("description", "")),
                                    "priority": str(p.get("priority", "MEDIUM")),
                                    "riskId": str(p.get("riskId", "")),
                                    "citationSourceId": str(p.get("citationSourceId", "")),
                                    # For UPDATE_PROJECT_CONFIG:
                                    "key": str(p.get("key", "")),
                                    "value": str(p.get("value", "")),
                                    # For CREATE_GITHUB_MILESTONE:
                                    "dueOn": str(p.get("dueOn", "")),
                                    # For CREATE_GITHUB_ISSUE:
                                    "labels": p.get("labels") if isinstance(p.get("labels"), list) else [],
                                }),
                            ),
                        )
                elif subject_type == "PROJECT":
                    # Legacy fallback: single CREATE_GITHUB_ISSUE action
                    cur.execute(
                        """INSERT INTO agent_action
                           (project_id, run_id, subject_type, subject_id,
                            action_type, status, title, payload_json)
                           VALUES (%s,%s,%s,%s,'CREATE_GITHUB_ISSUE','PENDING_APPROVAL',%s,%s)""",
                        (
                            project_id, run_id, subject_type, subject_id,
                            artifact.get("issueTitle", artifact.get("title", "")),
                            _json_dumps({
                                "body": artifact.get("issueBody",
                                                     artifact.get("reportMarkdown", "")),
                                "source": artifact.get("reportType", ""),
                            }),
                        ),
                    )

            conn.commit()
        return report_id

    async def get_report(self, run_id: int) -> dict | None:
        def _get():
            with _conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """SELECT id, report_type AS reportType, title, summary,
                                  health_status AS healthStatus, health_score AS healthScore,
                                  dimensions_json AS dimensionsJson, risks_json AS risksJson,
                                  plan_json AS planJson, citations_json AS citationsJson,
                                  scoring_version AS scoringVersion, evidence_hash AS evidenceHash,
                                  analysis_mode AS analysisMode, content_json AS contentJson,
                                  report_markdown AS reportMarkdown, status,
                                  create_time AS createTime
                           FROM agent_report WHERE run_id=%s LIMIT 1""",
                        (run_id,),
                    )
                    return cur.fetchone()

        return await _run_sync(_get)

    async def latest_report(self, project_id: int, arguments: dict) -> dict:
        def _get():
            report_type = str(arguments.get("reportType", "HEALTH_REPORT")).upper()
            valid = {"HEALTH_REPORT", "ONBOARDING_GUIDE", "DECISION_MEMO"}
            if report_type not in valid:
                report_type = "HEALTH_REPORT"
            with _conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """SELECT id, report_type AS reportType, title, summary,
                                  health_status AS healthStatus, health_score AS healthScore,
                                  evidence_hash AS evidenceHash, analysis_mode AS analysisMode,
                                  create_time AS createTime
                           FROM agent_report
                           WHERE project_id=%s AND report_type=%s
                           ORDER BY id DESC LIMIT 1""",
                        (project_id, report_type),
                    )
                    row = cur.fetchone()
                    return row if row else {}

        return await _run_sync(_get)


class MySqlMemoryStore(MemoryStore):
    async def save_memory(
        self,
        project_id: int,
        run_id: int,
        memory_type: str,
        title: str,
        content: str,
        source_id: str,
        confirmed: bool = False,
    ) -> None:
        await _run_sync(
            self._save_sync,
            project_id,
            run_id,
            memory_type,
            title,
            content,
            source_id,
            confirmed,
        )

    @staticmethod
    def _save_sync(project_id, run_id, memory_type, title, content, source_id, confirmed):
        with _conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """INSERT INTO agent_project_memory
                       (project_id, memory_type, title, content, source_type, source_id, confirmed)
                       VALUES (%s, %s, %s, %s, 'AGENT_RUN', %s, %s)""",
                    (project_id, memory_type, title, content, source_id, 1 if confirmed else 0),
                )
            conn.commit()
