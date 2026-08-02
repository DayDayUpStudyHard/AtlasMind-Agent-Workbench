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
    ) -> None:
        ...

    @abstractmethod
    async def heartbeat(self, run_id: int) -> None:
        ...

    @abstractmethod
    async def find_timed_out_runs(self, timeout_seconds: int) -> list[int]:
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
                        """SELECT id, project_id AS projectId, run_type AS runType,
                                  trigger_type AS triggerType, question, status,
                                  progress, current_step AS currentStep,
                                  error_message AS errorMessage,
                                  started_at AS startedAt, finished_at AS finishedAt,
                                  create_time AS createTime
                           FROM agent_run WHERE id=%s""",
                        (run_id,),
                    )
                    return cur.fetchone() or {}

        return await _run_sync(_get)

    async def update_run(
        self,
        run_id: int,
        *,
        status: str | None = None,
        progress: int | None = None,
        current_step: str | None = None,
        error_message: str | None = None,
    ) -> None:
        def _update():
            sets = []
            params: list = []
            if status is not None:
                sets.append("status=%s")
                params.append(status)
                if status in ("COMPLETED", "FAILED", "CANCELLED"):
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
                conn.commit()

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

    async def find_timed_out_runs(self, timeout_seconds: int) -> list[int]:
        def _find():
            with _conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """SELECT id FROM agent_run
                           WHERE status IN ('CREATED','CONTEXT_BUILDING','PLANNING','ANALYZING','VERIFYING')
                             AND create_time < DATE_SUB(NOW(), INTERVAL %s SECOND)""",
                        (timeout_seconds,),
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
                             AND (last_heartbeat_at IS NULL
                                  OR last_heartbeat_at < DATE_SUB(NOW(), INTERVAL %s SECOND))""",
                        (max_heartbeat_age_seconds,),
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
                              started_at AS startedAt, finished_at AS finishedAt,
                              create_time AS createTime
                       FROM agent_run WHERE id=%s""",
                    (run_id,),
                )
                run = cur.fetchone()
                if not run:
                    return {}

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
    async def save_report(
        self, project_id: int, run_id: int, task_type: str, artifact: dict
    ) -> int:
        return await _run_sync(self._save_sync, project_id, run_id, task_type, artifact)

    @staticmethod
    def _save_sync(project_id, run_id, task_type, artifact):
        is_health = task_type == "HEALTH_ANALYSIS"
        with _conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """INSERT INTO agent_report
                       (project_id, run_id, report_type, title, summary, health_status,
                        health_score, dimensions_json, risks_json, plan_json,
                        citations_json, scoring_version, evidence_hash, analysis_mode,
                        scoring_rationale_json, content_json, report_markdown, status)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'DRAFT')""",
                    (
                        project_id,
                        run_id,
                        artifact.get("reportType", "HEALTH_REPORT" if is_health else "ONBOARDING_GUIDE"),
                        artifact.get("title", ""),
                        artifact.get("summary", ""),
                        artifact.get("healthStatus") if is_health else None,
                        artifact.get("healthScore", 0) if is_health else 0,
                        _json_dumps(artifact.get("dimensions")) if is_health and artifact.get("dimensions") else None,
                        _json_dumps(artifact.get("risks")),
                        _json_dumps(artifact.get("plan")),
                        _json_dumps(artifact.get("citations")),
                        artifact.get("scoringVersion") if is_health else None,
                        artifact.get("evidenceHash"),
                        artifact.get("analysisMode"),
                        _json_dumps(artifact.get("scoringRationale")) if is_health and artifact.get("scoringRationale") else None,
                        _json_dumps(artifact.get("content", artifact)),
                        artifact.get("reportMarkdown", ""),
                    ),
                )
                report_id = int(cur.lastrowid)

                # Create PENDING_APPROVAL action proposal
                cur.execute(
                    """INSERT INTO agent_action
                       (project_id, run_id, action_type, status, title, payload_json)
                       VALUES (%s,%s,'CREATE_GITHUB_ISSUE','PENDING_APPROVAL',%s,%s)""",
                    (
                        project_id,
                        run_id,
                        artifact.get("issueTitle", artifact.get("title", "")),
                        _json_dumps(
                            {
                                "body": artifact.get("issueBody", artifact.get("reportMarkdown", "")),
                                "source": artifact.get("reportType", ""),
                            },
                        ),
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
