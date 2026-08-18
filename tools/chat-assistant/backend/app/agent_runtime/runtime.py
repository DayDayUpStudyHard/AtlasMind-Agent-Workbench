"""Agent Runtime interface, adapters, and dynamic routing.

Provides the stable protocol that Redis Worker uses to dispatch runs,
plus LegacyAdapter (existing harness) and GraphAdapter (LangGraph) implementations.
"""

from __future__ import annotations

import asyncio
import contextvars
import json
import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Protocol, runtime_checkable

from langgraph.errors import GraphInterrupt

# Graph dispatch heartbeat cadence, matching AgentRunner.HEARTBEAT_INTERVAL.
# Exposed as a module constant so tests can shorten it.
GRAPH_HEARTBEAT_INTERVAL = 15

logger = logging.getLogger(__name__)

# Per-run overrides — set by eval runner or any caller that wants to
# override global settings for a specific run.
_model_override: contextvars.ContextVar[str] = contextvars.ContextVar("model_override", default="")
_prompt_version_override: contextvars.ContextVar[str] = contextvars.ContextVar("prompt_version_override", default="")
_recall_multiplier_override: contextvars.ContextVar[int] = contextvars.ContextVar("recall_multiplier_override", default=0)
_recall_min_override: contextvars.ContextVar[int] = contextvars.ContextVar("recall_min_override", default=0)
_recall_max_override: contextvars.ContextVar[int] = contextvars.ContextVar("recall_max_override", default=0)
_retry_limit_override: contextvars.ContextVar[int] = contextvars.ContextVar("retry_limit_override", default=-1)
_coverage_reflection_disabled: contextvars.ContextVar[bool] = contextvars.ContextVar("coverage_reflection_disabled", default=False)
_temperature_override: contextvars.ContextVar[float] = contextvars.ContextVar("temperature_override", default=-1.0)
# Contract review v2 pilot (PRD Phase 3, §15) — tunable via eval features_json
_v2_analysis_concurrency: contextvars.ContextVar[int] = contextvars.ContextVar("v2_analysis_concurrency", default=3)
_v2_skip_llm_on_no_evidence: contextvars.ContextVar[bool] = contextvars.ContextVar("v2_skip_llm_on_no_evidence", default=True)

_GRAPH_PROMPT_VERSIONS = {
    "CONTRACT_REVIEW": "contract-review-graph-v1",
    "FULFILLMENT_CHECK": "fulfillment-check-graph-v1",
    "CONTRACT_ELEMENT_EXTRACTION": "contract-elements-v1",
}

# Task types the legacy pipeline (AgentRunner) can actually produce artifacts
# for. Extraction/timeline tasks have no legacy implementation — forcing them
# through the legacy adapter falls into run_project_task and fails per case.
LEGACY_SUPPORTED_TASK_TYPES = frozenset({
    "HEALTH_ANALYSIS",
    "PROJECT_ONBOARDING",
    "ENGINEERING_DECISION",
    "CONTRACT_REVIEW",
    "CONTRACT_INTAKE",
    "APPROVAL_DECISION",
    "FULFILLMENT_CHECK",
})


def is_legacy_task_supported(task_type: str) -> bool:
    return str(task_type or "").upper() in LEGACY_SUPPORTED_TASK_TYPES


# PRD Phase 8 / §10: the frozen retrieval pipeline version. Mirrors
# contract_extraction.EXTRACTION_RETRIEVAL_VERSION — every graph shares the
# same hybrid retrieval implementation; the value lives here (runtime
# cannot import the graph package without a cycle) and contract_extraction
# pins the same string for its snapshot rows.
RETRIEVAL_VERSION = "contract-hybrid-retrieval-v2"


def _runtime_model_metadata(task_type: str) -> tuple[str, str]:
    """Return the configured model and stable prompt version for a graph.

    Per-run overrides (set via contextvars) take precedence over global settings.
    """
    # Model: contextvar override → global settings → empty
    model = _model_override.get()
    if not model:
        try:
            from app.config import settings
            model = str(getattr(settings, "llm_model", "") or "")
        except Exception:
            model = ""

    # Prompt version: contextvar override → hardcoded lookup
    prompt = _prompt_version_override.get()
    if not prompt:
        prompt = _GRAPH_PROMPT_VERSIONS.get(str(task_type or "").upper(), "")

    return model, prompt


# ── Protocol & models ────────────────────────────────────────────────

class ResumeAction(str, Enum):
    CONFIRM = "CONFIRM"
    REQUEST_SUPPLEMENT = "REQUEST_SUPPLEMENT"
    KEEP_PENDING = "KEEP_PENDING"
    CANCEL = "CANCEL"


@dataclass
class ResumeCommand:
    """Command to resume a paused graph run."""

    action: ResumeAction
    expected_state_revision: int = 0
    manual_result: str = ""  # SATISFIED | NOT_SATISFIED | PENDING
    note: str = ""
    operator_id: str = ""

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ResumeCommand":
        action_raw = str(data.get("command") or data.get("action") or "").upper()
        try:
            action = ResumeAction(action_raw)
        except ValueError:
            action = ResumeAction.KEEP_PENDING
        return cls(
            action=action,
            expected_state_revision=int(data.get("expectedStateRevision", 0)),
            manual_result=str(data.get("manualResult", "")).upper(),
            note=str(data.get("note", "")),
            operator_id=str(data.get("operatorId", "")),
        )


@dataclass
class AgentResult:
    """Standard result from any AgentRuntime implementation."""

    run_id: int
    status: str  # COMPLETED | LIMITED | FAILED | WAITING_HUMAN | CANCELLED
    artifact: dict[str, Any] = field(default_factory=dict)
    observations: list[dict[str, Any]] = field(default_factory=list)
    citations: list[dict[str, Any]] = field(default_factory=list)
    scoring: dict[str, Any] = field(default_factory=dict)
    graph_info: dict[str, Any] | None = None  # populated by GraphAdapter

    @property
    def ok(self) -> bool:
        return self.status == "COMPLETED"


@runtime_checkable
class AgentRuntime(Protocol):
    """Stable interface for agent run execution.

    Implementations:
      - LegacyHarnessAdapter: wraps existing AgentRunner.execute()
      - GraphAdapter: wraps compiled LangGraph StateGraph
    """

    async def run(self, context: Any) -> AgentResult:
        """Execute a full agent run. *context* is AgentTaskContext."""
        ...

    async def resume(self, run_id: int, command: ResumeCommand) -> AgentResult:
        """Resume a paused run (graph mode only)."""
        ...


# ── Graph Adapter ─────────────────────────────────────────────────────

class GraphAdapter:
    """Adapts a compiled LangGraph StateGraph as an AgentRuntime.

    Uses LangGraph's ainvoke() for async execution. Thread ID is derived
    from run_id for checkpoint correlation.
    """

    def __init__(
        self,
        compiled_graph: Any,
        checkpointer: Any = None,
        graph_name: str = "",
        graph_version: str = "v1",
        run_store: Any = None,
    ):
        self._graph = compiled_graph
        self._checkpointer = checkpointer
        self._graph_name = graph_name
        self._graph_version = graph_version
        self._run_store = run_store
        self._heartbeat_task: asyncio.Task | None = None

    async def _persist_start_metadata(
        self,
        run_id: int,
        graph_name: str,
        graph_version: str,
        model: str,
        prompt_version: str,
        retrieval_version: str = "",
        rerank_version: str = "",
    ) -> None:
        """Make a graph run identifiable even when it fails before checkpointing."""
        writer = getattr(self._run_store, "set_runtime_metadata", None)
        if not callable(writer):
            return
        try:
            await writer(
                run_id,
                runtime_engine="langgraph",
                graph_name=graph_name,
                graph_version=graph_version,
                model=model,
                prompt_version=prompt_version,
                retrieval_version=retrieval_version,
                rerank_version=rerank_version,
            )
        except Exception as exc:
            logger.debug("Could not persist graph runtime metadata for run %s: %s", run_id, exc)

    async def run(self, context: Any) -> AgentResult:
        """Execute the graph for a new run."""
        shadow_mode = bool(getattr(context, "shadow_mode", False))
        # Shadow runs get their own checkpoint thread so the primary graph's
        # checkpoint stream (and resume history) stays untouched; checkpoint
        # persistence skips run-row/trace writes for shadow- threads.
        thread_id = f"{'shadow-' if shadow_mode else ''}run-{context.run_id}"
        graph_name = self._graph_name or getattr(context, "graph_name", "unknown")
        graph_version = self._graph_version or getattr(context, "graph_version", "v1")
        model, prompt_version = _runtime_model_metadata(context.task_type)
        # PRD Phase 8 / §10: freeze the retrieval + rerank stack alongside
        # graph/prompt/model so every run (and every artifact) is traceable.
        from app.agent_runtime.reranker import RERANK_VERSION
        retrieval_version = RETRIEVAL_VERSION
        rerank_version = RERANK_VERSION

        initial_state = {
            "run_id": context.run_id,
            "subject_type": context.subject_type,
            "subject_id": context.subject_id,
            "task_type": context.task_type,
            "task_input": context.task_input or {},
            "graph_name": graph_name,
            "graph_version": graph_version,
            "model": model,
            "prompt_version": prompt_version,
            "retrieval_version": retrieval_version,
            "rerank_version": rerank_version,
            "scorer_version": "",
            "trigger_type": "MANUAL",
            "state_revision": 0,
            "case_snapshot": context.project or {},
            "observations": [],
            "citations": [],
            "errors": [],
            "shadow_mode": shadow_mode,
        }

        config = {
            "configurable": {
                "thread_id": thread_id,
                "run_id": context.run_id,
            }
        }
        heartbeat_task = None
        if not shadow_mode:
            await self._persist_start_metadata(
                context.run_id,
                graph_name,
                graph_version,
                model,
                prompt_version,
                retrieval_version,
                rerank_version,
            )
            # Keep the run row heartbeating while the graph executes: the
            # RunRecovery sweeper (this process's or the API server's) marks runs
            # in active statuses with a stale heartbeat as FAILED. The legacy
            # AgentRunner beats from its dispatch path; graph dispatches did not,
            # so any run whose event loop stays responsive (e.g. the v2 pilot's
            # async retrieval) could be flagged mid-run. The task reference is
            # kept and cancelled below — a paused (WAITING_HUMAN) run must not
            # keep a heartbeat task alive.
            if callable(getattr(self._run_store, "heartbeat", None)):
                heartbeat_task = asyncio.create_task(self._heartbeat_loop(context.run_id))
                self._heartbeat_task = heartbeat_task
        try:
            final_state = await self._graph.ainvoke(initial_state, config)
        except GraphInterrupt:
            # Graph paused at an interrupt() node — expected for HITL.
            # Typed on the exception class, never on message text: a plain
            # failure whose message happens to say "interrupted" must stay
            # FAILED, and a GraphInterrupt whose message has no English
            # marker must stay HITL.
            logger.info("Graph %s interrupted for run %s (HITL)",
                       initial_state.get("graph_name", ""), context.run_id)
            return AgentResult(
                run_id=context.run_id,
                status="WAITING_HUMAN",
                artifact={},
                graph_info={
                    "runtimeEngine": "langgraph",
                    "graphName": initial_state.get("graph_name", ""),
                    "graphVersion": initial_state.get("graph_version", ""),
                    "model": initial_state.get("model", ""),
                    "promptVersion": initial_state.get("prompt_version", ""),
                    "waitState": initial_state.get("wait_state") or {"type": "WAITING_HUMAN"},
                },
            )
        except Exception as exc:
            logger.exception("Graph run failed for run %s", context.run_id)
            return AgentResult(
                run_id=context.run_id,
                status="FAILED",
                artifact={"artifactError": str(exc)},
                graph_info={
                    "runtimeEngine": "langgraph",
                    "graphName": initial_state.get("graph_name", ""),
                    "graphVersion": initial_state.get("graph_version", ""),
                    "model": initial_state.get("model", ""),
                    "promptVersion": initial_state.get("prompt_version", ""),
                },
            )
        finally:
            # run() is over on every exit path — stop beating the run row.
            # The loop's own status check is the backstop; this cancel makes
            # the stop immediate (no lingering 15s tick after return). The
            # cancelled task is then awaited so its resources are reclaimed
            # (same pattern as the legacy AgentRunner).
            if heartbeat_task is not None:
                heartbeat_task.cancel()
                try:
                    await heartbeat_task
                except asyncio.CancelledError:
                    pass
                self._heartbeat_task = None

        if final_state.get("__interrupt__"):
            wait_state = final_state.get("wait_state") or {}
            try:
                snapshot = await self._graph.aget_state(config)
                wait_state = (snapshot.values or {}).get("wait_state") or wait_state
            except Exception:
                pass
            return AgentResult(
                run_id=context.run_id,
                status="WAITING_HUMAN",
                artifact={},
                observations=final_state.get("observations") or [],
                citations=final_state.get("citations") or [],
                graph_info={
                    "runtimeEngine": "langgraph",
                    "graphName": final_state.get("graph_name", self._graph_name),
                    "graphVersion": final_state.get("graph_version", self._graph_version),
                    "model": final_state.get("model", model),
                    "promptVersion": final_state.get("prompt_version", prompt_version),
                    "stateRevision": final_state.get("state_revision", 0),
                    "waitState": wait_state,
                },
            )

        artifact = final_state.get("artifact") or {}
        if not artifact:
            # A graph can return a partial checkpoint state after an internal
            # routing failure. Do not let the API report a false completion.
            return AgentResult(
                run_id=context.run_id,
                status="FAILED",
                artifact={
                    "artifactError": (
                        "Contract graph ended without a report artifact "
                        f"(lastNode={final_state.get('current_node') or 'unknown'})"
                    )
                },
                observations=final_state.get("observations") or [],
                citations=final_state.get("citations") or [],
                graph_info={
                    "runtimeEngine": "langgraph",
                    "graphName": final_state.get("graph_name", ""),
                    "graphVersion": final_state.get("graph_version", ""),
                    "model": final_state.get("model", model),
                    "promptVersion": final_state.get("prompt_version", prompt_version),
                    "stateRevision": final_state.get("state_revision", 0),
                    "lastNode": final_state.get("current_node", ""),
                },
            )
        limited_diagnostics = final_state.get("limited_diagnostics")
        graph_info = {
            "runtimeEngine": "langgraph",
            "graphName": final_state.get("graph_name", ""),
            "graphVersion": final_state.get("graph_version", ""),
            "model": final_state.get("model", model),
            "promptVersion": final_state.get("prompt_version", prompt_version),
            # PRD §10: the frozen retrieval/rerank/scorer stack travels with
            # the result so eval observers can record it without re-querying.
            "retrievalVersion": final_state.get("retrieval_version", ""),
            "rerankVersion": final_state.get("rerank_version", ""),
            "scorerVersion": final_state.get("scorer_version", ""),
            "stateRevision": final_state.get("state_revision", 0),
        }
        if limited_diagnostics:
            # §7.2/§6.4: an over-budget / coverage-limited run is LIMITED
            # with its mandatory diagnostics — never FAILED, never a false
            # COMPLETED. The diagnostics travel in graph_info so callers
            # persist them with the run row.
            graph_info["limitedDiagnostics"] = limited_diagnostics
        return AgentResult(
            run_id=context.run_id,
            status="LIMITED" if limited_diagnostics else "COMPLETED",
            artifact=artifact,
            observations=final_state.get("observations") or [],
            citations=final_state.get("citations") or [],
            graph_info=graph_info,
        )

    async def _heartbeat_loop(self, run_id: int) -> None:
        """Refresh last_heartbeat_at every 15s until the run row is terminal.

        Self-terminating: exits once the row leaves the active statuses, so it
        needs no cancellation plumbing across `run()`'s return paths (run()
        still cancels the task explicitly on return). WAITING_HUMAN is
        deliberately NOT active here: a paused run is not executing, and the
        RunRecovery sweeper does not kill WAITING_HUMAN rows — a long-pending
        confirmation must not keep a background task and heartbeat writes
        alive. A failed read must not kill the loop — try again next tick.
        """
        active_statuses = (
            "CREATED", "CONTEXT_BUILDING", "PLANNING", "ANALYZING", "VERIFYING",
        )
        while True:
            await asyncio.sleep(GRAPH_HEARTBEAT_INTERVAL)
            try:
                row = await self._run_store.get_run(run_id)
                if (row or {}).get("status") not in active_statuses:
                    return
            except Exception:
                pass
            try:
                await self._run_store.heartbeat(run_id)
            except Exception:
                logger.warning("Heartbeat write failed for run %s", run_id, exc_info=True)

    async def resume(self, run_id: int, command: ResumeCommand) -> AgentResult:
        """Resume a paused graph from its last checkpoint using Command(resume=...)."""
        thread_id = f"run-{run_id}"
        config = {
            "configurable": {
                "thread_id": thread_id,
                "run_id": run_id,
            }
        }

        try:
            from langgraph.types import Command
            final_state = await self._graph.ainvoke(
                Command(resume={
                    "action": command.action.value,
                    "manual_result": command.manual_result,
                    "note": command.note,
                    "operator_id": command.operator_id,
                }),
                config,
            )
        except GraphInterrupt:
            # The graph paused again after the human input — stay in the HITL
            # state, never report a failure for an expected pause.
            logger.info("Graph re-interrupted on resume for run %s (HITL)", run_id)
            return AgentResult(
                run_id=run_id,
                status="WAITING_HUMAN",
                artifact={},
                graph_info={
                    "runtimeEngine": "langgraph",
                    "waitState": {"type": "WAITING_HUMAN"},
                },
            )
        except Exception as exc:
            logger.exception("Graph resume failed for run %s", run_id)
            return AgentResult(
                run_id=run_id,
                status="FAILED",
                artifact={"artifactError": str(exc)},
            )

        if final_state.get("__interrupt__"):
            wait_state = final_state.get("wait_state") or {}
            try:
                snapshot = await self._graph.aget_state(config)
                wait_state = (snapshot.values or {}).get("wait_state") or wait_state
            except Exception:
                pass
            return AgentResult(
                run_id=run_id,
                status="WAITING_HUMAN",
                artifact={},
                observations=final_state.get("observations") or [],
                citations=final_state.get("citations") or [],
                graph_info={
                    "runtimeEngine": "langgraph",
                    "graphName": final_state.get("graph_name", self._graph_name),
                    "graphVersion": final_state.get("graph_version", self._graph_version),
                    "model": final_state.get("model", ""),
                    "promptVersion": final_state.get("prompt_version", ""),
                    "stateRevision": final_state.get("state_revision", 0),
                    "waitState": wait_state,
                },
            )

        artifact = final_state.get("artifact") or {}
        if not artifact:
            return AgentResult(
                run_id=run_id,
                status="FAILED",
                artifact={"artifactError": "Graph resumed without generating an artifact"},
            )
        return AgentResult(
            run_id=run_id,
            status="COMPLETED",
            artifact=artifact,
            observations=final_state.get("observations") or [],
            citations=final_state.get("citations") or [],
            graph_info={
                "runtimeEngine": "langgraph",
                "graphName": final_state.get("graph_name", ""),
                "graphVersion": final_state.get("graph_version", ""),
                "model": final_state.get("model", ""),
                "promptVersion": final_state.get("prompt_version", ""),
                "stateRevision": final_state.get("state_revision", 0),
            },
        )


# ── Legacy Harness Adapter ───────────────────────────────────────────

# ── Shadow Adapter ────────────────────────────────────────────────────

class ShadowAdapter:
    """Runs two adapters in parallel, compares results, returns primary.

    PRD §26.1/§26.2 (`shadow_v2`): the shadow graph executes beside the
    production graph on the same case. The user-visible result is always the
    primary's; the shadow result is recorded as a SHADOW_DIFF trace for
    evaluation and never persisted as the official report.
    """

    def __init__(self, primary: AgentRuntime, shadow: AgentRuntime):
        self._primary = primary
        self._shadow = shadow

    async def run(self, context: Any) -> AgentResult:
        import dataclasses
        import time

        # The shadow executes on a copy of the context flagged shadow_mode so
        # GraphAdapter uses a separate checkpoint thread and skips run-row,
        # trace and report writes (the primary owns those).
        shadow_context = context
        if dataclasses.is_dataclass(context) and not isinstance(context, type):
            try:
                shadow_context = dataclasses.replace(context, shadow_mode=True)
            except TypeError:
                shadow_context = context

        started = time.monotonic()
        primary_task = asyncio.create_task(self._primary.run(context))
        shadow_task = asyncio.create_task(self._shadow.run(shadow_context))

        primary_result = await primary_task
        primary_elapsed = time.monotonic() - started
        try:
            shadow_result = await shadow_task
            shadow_elapsed = time.monotonic() - started
            # Log differences for evaluation
            _log_shadow_diff(
                context.run_id, primary_result, shadow_result,
                primary_elapsed_s=primary_elapsed,
                shadow_elapsed_s=shadow_elapsed,
            )
        except Exception as exc:
            logger.warning("Shadow run failed for run %s: %s", context.run_id, exc)

        return primary_result

    async def resume(self, run_id: int, command: ResumeCommand) -> AgentResult:
        return await self._primary.resume(run_id, command)


def _log_shadow_diff(
    run_id: int,
    primary: AgentResult,
    shadow: AgentResult,
    *,
    primary_elapsed_s: float = 0.0,
    shadow_elapsed_s: float = 0.0,
) -> None:
    """Compare primary and shadow results, log and record key differences.

    The comparison (PRD §26.2: 发现/引用/遗漏/延迟差异) is appended to the
    primary run's trace as one SHADOW_DIFF event so the management UI shows it
    beside the official result.
    """
    p_artifact = primary.artifact or {}
    s_artifact = shadow.artifact or {}

    diffs: list[str] = []

    # Compare risk scores
    p_score = p_artifact.get("riskScore") or p_artifact.get("risk_score") or 0
    s_score = s_artifact.get("riskScore") or s_artifact.get("risk_score") or 0
    if p_score != s_score:
        diffs.append(f"riskScore: primary={p_score} shadow={s_score}")

    # Compare finding counts
    p_findings = p_artifact.get("findings") or []
    s_findings = s_artifact.get("findings") or []
    if len(p_findings) != len(s_findings):
        diffs.append(f"findingCount: primary={len(p_findings)} shadow={len(s_findings)}")

    # Compare citation counts
    p_citations = primary.citations or []
    s_citations = shadow.citations or []
    if len(p_citations) != len(s_citations):
        diffs.append(f"citationCount: primary={len(p_citations)} shadow={len(s_citations)}")

    # Compare HIGH severity findings
    p_high = {f.get("title", "") for f in p_findings if str(f.get("severity", "")).upper() == "HIGH"}
    s_high = {f.get("title", "") for f in s_findings if str(f.get("severity", "")).upper() == "HIGH"}
    missing_in_shadow = p_high - s_high
    if missing_in_shadow:
        diffs.append(f"HIGH findings MISSING in shadow: {missing_in_shadow}")

    # Latency comparison (PRD §26.2) — always recorded, even when the
    # finding/citation dimensions above show no difference.
    diffs.append(
        f"elapsed: primary={primary_elapsed_s:.1f}s shadow={shadow_elapsed_s:.1f}s"
    )

    summary = "Shadow v2 对照: " + "; ".join(diffs)
    logger.info("Shadow diff for run %s: %s", run_id, "; ".join(diffs))

    # Record the comparison on the primary run's trace. Best-effort: the
    # shadow instrument must never fail the production dispatch.
    try:
        from .persistence import _conn

        with _conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT COALESCE(MAX(sequence_no), 0) + 1 AS seq"
                    " FROM agent_run_trace WHERE run_id=%s",
                    (run_id,),
                )
                seq_row = cur.fetchone()
                if seq_row is None:
                    return
                cur.execute(
                    """INSERT INTO agent_run_trace
                       (run_id, event_type, sequence_no, summary, payload_json)
                       VALUES (%s,'SHADOW_DIFF',%s,%s,%s)""",
                    (
                        run_id,
                        int(seq_row["seq"]),
                        summary[:500],
                        json.dumps(
                            {
                                "primaryStatus": primary.status,
                                "shadowStatus": shadow.status,
                                "primaryGraph": (primary.graph_info or {}).get("graphName", ""),
                                "shadowGraph": (shadow.graph_info or {}).get("graphName", ""),
                                "primaryElapsedS": round(primary_elapsed_s, 1),
                                "shadowElapsedS": round(shadow_elapsed_s, 1),
                                "findingCounts": {"primary": len(p_findings), "shadow": len(s_findings)},
                                "citationCounts": {"primary": len(p_citations), "shadow": len(s_citations)},
                            },
                            ensure_ascii=False,
                        ),
                    ),
                )
    except Exception as exc:
        logger.debug("Shadow diff trace persist skipped for run %s: %s", run_id, exc)


class LegacyHarnessAdapter:
    """Wraps the existing AgentRunner as an AgentRuntime implementation."""

    def __init__(self, runner):  # AgentRunner
        self._runner = runner

    async def run(self, context: Any) -> AgentResult:
        raw = await self._runner.execute(context)
        artifact = raw.get("rawArtifact") or {}
        reflection = raw.get("reflection") or {}
        failed = bool(raw.get("artifactError") or artifact.get("artifactError"))
        limited = (
            str(artifact.get("analysisMode") or "").upper() == "LIMITED"
            or reflection.get("adequate") is False
        )
        graph_info = {
            "runtimeEngine": "legacy",
            "graphName": "harness-v1",
            "graphVersion": "legacy",
        }
        if limited and not failed:
            from .harness.budget import coverage_limited_diagnostics

            missing_items: list[str] = []
            domains = reflection.get("domains") or {}
            if isinstance(domains, dict):
                for domain_key, domain_info in domains.items():
                    if not isinstance(domain_info, dict) or domain_info.get("covered") is not False:
                        continue
                    missing_items.append(str(domain_info.get("domainName") or domain_key))
                    missing_items.extend(str(issue) for issue in (domain_info.get("issues") or []) if issue)
            missing_sources = [
                str(item) for item in (reflection.get("missingEvidence") or []) if item
            ]
            graph_info["limitedDiagnostics"] = coverage_limited_diagnostics(
                work_unit_id=str(context.task_type or "LEGACY_HARNESS"),
                missing_check_items=tuple(missing_items),
                missing_source_types=tuple(missing_sources),
                retried=bool(reflection.get("retried")),
            )
        return AgentResult(
            run_id=context.run_id,
            status="FAILED" if failed else ("LIMITED" if limited else "COMPLETED"),
            artifact=artifact,
            observations=raw.get("observations") or [],
            citations=raw.get("citations") or [],
            scoring=raw.get("scoring") or {},
            graph_info=graph_info,
        )

    async def resume(self, run_id: int, command: ResumeCommand) -> AgentResult:
        raise NotImplementedError("Legacy harness does not support resume")


# ── Runtime Router ────────────────────────────────────────────────────

class RuntimeRouter:
    """Selects and dispatches to the correct AgentRuntime based on DB config.

    Config keys (in system_config or system_settings table):
      - agent.runtime.default = "legacy" | "langgraph"
      - agent.runtime.<TASK_TYPE> = override for specific task type

    Cache TTL: 30 seconds.
    """

    CACHE_TTL = 30.0

    def __init__(self):
        self._adapters: dict[str, AgentRuntime] = {}
        self._default: str = "legacy"
        self._cache: dict[str, tuple[float, str]] = {}

    def register(self, name: str, adapter: AgentRuntime) -> None:
        self._adapters[name] = adapter

    def _resolve(self, task_type: str) -> Any:
        """Resolve runtime: DB config → env → legacy default.

        When mode='langgraph', maps task_type to graph name:
          CONTRACT_REVIEW → contract_review
          FULFILLMENT_CHECK → fulfillment_check
        """
        import os

        # ── Read config: DB → env → default ──
        resolved = self._default
        has_db_override = False
        try:
            from .persistence import _conn
            with _conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT config_value FROM system_config WHERE config_key=%s",
                        (f"agent.runtime.{task_type}",),
                    )
                    row = cur.fetchone()
                    if row and row.get("config_value"):
                        resolved = str(row["config_value"])
                        has_db_override = True
        except Exception:
            pass  # DB unavailable, use env/default

        env_override = ""
        if not has_db_override:
            env_key = f"AGENT_RUNTIME_{task_type}"
            env_override = str(os.environ.get(env_key, "")).strip()
            if env_override:
                resolved = env_override

        # Extraction has no meaningful legacy implementation. Use its graph
        # by default while still allowing DB or environment configuration to
        # opt out during a rollback.
        if (
            task_type in {"CONTRACT_ELEMENT_EXTRACTION", "TIMELINE_EXTRACTION"}
            and not has_db_override
            and not env_override
            and self._adapters.get(
                "timeline_extraction" if task_type == "TIMELINE_EXTRACTION" else "contract_extraction"
            ) is not None
        ):
            resolved = "langgraph"

        # ── langgraph mode: map task_type → graph name ──
        if resolved == "langgraph":
            graph_name = {
                "CONTRACT_REVIEW": "contract_review",
                "FULFILLMENT_CHECK": "fulfillment_check",
                "CONTRACT_ELEMENT_EXTRACTION": "contract_extraction",
                "TIMELINE_EXTRACTION": "timeline_extraction",
            }.get(task_type, "")
            if graph_name:
                adapter = self._adapters.get(graph_name)
                if adapter:
                    return adapter
            logger.warning("No graph adapter for task_type=%s, falling back to legacy", task_type)

        # ── shadow_v2 mode (PRD §26.1 灰度期): v1 stays the production
        # answer while v2 runs beside it for comparison ──
        if resolved == "shadow_v2" and task_type == "CONTRACT_REVIEW":
            primary = self._adapters.get("contract_review")
            shadow = self._adapters.get("contract_review_v2")
            if primary is not None and shadow is not None:
                return ShadowAdapter(primary, shadow)
            if primary is not None or shadow is not None:
                return primary or shadow
            logger.warning("shadow_v2 configured but v1/v2 adapters missing, falling back")

        # ── Fallback to legacy ──
        adapter = self._adapters.get(self._default)
        if adapter is None:
            # Last resort: pick any registered adapter
            adapter = next(iter(self._adapters.values()), None)
        return adapter

    async def dispatch(self, context: Any) -> AgentResult:
        """Route to the correct adapter and execute."""
        adapter = self._resolve(context.task_type)
        engine_name = getattr(adapter, "__class__", type(adapter)).__name__
        logger.info(
            "RuntimeRouter: run %s task %s → %s",
            context.run_id, context.task_type, engine_name,
        )
        return await adapter.run(context)

    async def dispatch_with_mode(self, context: Any, mode: str) -> AgentResult:
        """Dispatch using an explicit runtime mode, bypassing DB/env config.

        Used by eval center to force legacy or langgraph regardless of system config.
        """
        graph_name = None
        if mode == "langgraph_v2":
            # PRD Phase 3 pilot: contract_review v2 only; other task types
            # fall through to their v1 graphs rather than failing an eval run.
            graph_name = {
                "CONTRACT_REVIEW": "contract_review_v2",
                "FULFILLMENT_CHECK": "fulfillment_check",
                "CONTRACT_ELEMENT_EXTRACTION": "contract_extraction",
                "TIMELINE_EXTRACTION": "timeline_extraction",
            }.get(context.task_type, "")
            adapter = self._adapters.get(graph_name) if graph_name else None
        elif mode == "shadow_v2":
            # PRD §26.1/§26.2: v2 runs beside the production graph on the same
            # case; the user-visible result stays the primary's (v1) and the
            # shadow result is recorded as a SHADOW_DIFF trace for evaluation.
            if context.task_type == "CONTRACT_REVIEW":
                primary = self._adapters.get("contract_review")
                shadow = self._adapters.get("contract_review_v2")
                if primary is not None and shadow is not None:
                    adapter = ShadowAdapter(primary, shadow)
                else:
                    adapter = primary or shadow
            else:
                graph_name = {
                    "FULFILLMENT_CHECK": "fulfillment_check",
                    "CONTRACT_ELEMENT_EXTRACTION": "contract_extraction",
                    "TIMELINE_EXTRACTION": "timeline_extraction",
                }.get(context.task_type, "")
                adapter = self._adapters.get(graph_name) if graph_name else None
        elif mode == "langgraph":
            graph_name = {
                "CONTRACT_REVIEW": "contract_review",
                "FULFILLMENT_CHECK": "fulfillment_check",
                "CONTRACT_ELEMENT_EXTRACTION": "contract_extraction",
                "TIMELINE_EXTRACTION": "timeline_extraction",
            }.get(context.task_type, "")
            adapter = self._adapters.get(graph_name) if graph_name else None
        elif mode == "legacy":
            if not is_legacy_task_supported(context.task_type):
                # Forcing legacy on extraction/timeline tasks used to fall
                # through to run_project_task and fail per case with a cryptic
                # "unsupported project task type". Reject it up front instead.
                raise ValueError(
                    f"legacy 引擎不支持任务类型 {context.task_type}，请使用 langgraph 引擎"
                )
            adapter = self._adapters.get("legacy")
        else:
            # 未知模式绝不能静默回退（2026-08-14 事故：langgraph_v2 在旧
            # API 进程里被当作 legacy 执行，评测结果整体失真）。
            raise RuntimeError(
                f"未知运行时模式 {mode!r}（支持 legacy / langgraph / langgraph_v2 / shadow_v2）。"
                "若该值来自最新版管理端，说明本 API 服务进程加载的是旧代码，请重启服务。"
            )

        if adapter is None:
            # 请求的图未注册（如旧进程不认识 v2 图）时同样必须显式失败，
            # 而不是静默跑去执行 legacy 导致结果失真。
            raise RuntimeError(
                f"运行时 {mode} 在任务 {context.task_type} 下无可用适配器"
                f"（图 {graph_name or 'legacy'} 未注册）。"
                "若该图应为已知图，说明本 API 服务进程加载的是旧代码，请重启服务。"
            )

        engine_name = getattr(adapter, "__class__", type(adapter)).__name__
        logger.info(
            "RuntimeRouter (forced %s): run %s task %s → %s",
            mode, context.run_id, context.task_type, engine_name,
        )
        return await adapter.run(context)

    async def resume(self, run_id: int, command: ResumeCommand) -> AgentResult:
        """Resume a paused graph run.

        Looks up the original run's task_type to find the correct graph adapter:
          FULFILLMENT_CHECK → fulfillment_check
          CONTRACT_REVIEW   → contract_review
        """
        # Look up the run's task_type from DB to route to the correct graph
        graph_name = None
        try:
            from .persistence import _conn
            with _conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT run_type FROM agent_run WHERE id=%s",
                        (run_id,),
                    )
                    row = cur.fetchone()
                    if row:
                        run_type = str(row.get("run_type") or "")
                        _TASK_TO_GRAPH = {
                            "FULFILLMENT_CHECK": "fulfillment_check",
                            "CONTRACT_REVIEW": "contract_review",
                            "CONTRACT_ELEMENT_EXTRACTION": "contract_extraction",
                            "TIMELINE_EXTRACTION": "timeline_extraction",
                        }
                        graph_name = _TASK_TO_GRAPH.get(run_type)
        except Exception:
            pass

        if graph_name:
            adapter = self._adapters.get(graph_name)
            if adapter is not None and hasattr(adapter, "resume"):
                return await adapter.resume(run_id, command)

        raise NotImplementedError(
            f"No graph adapter found for run {run_id}. "
            "Ensure the graph is registered and the run uses a graph-based task type."
        )

    def get_adapter(self, name: str):
        """Get a registered adapter by name."""
        return self._adapters.get(name)
