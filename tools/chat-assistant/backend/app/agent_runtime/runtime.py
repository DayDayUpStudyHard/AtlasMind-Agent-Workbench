"""Agent Runtime interface, adapters, and dynamic routing.

Provides the stable protocol that Redis Worker uses to dispatch runs,
plus LegacyAdapter (existing harness) and GraphAdapter (LangGraph) implementations.
"""

from __future__ import annotations

import contextvars
import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Protocol, runtime_checkable

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

_GRAPH_PROMPT_VERSIONS = {
    "CONTRACT_REVIEW": "contract-review-graph-v1",
    "FULFILLMENT_CHECK": "fulfillment-check-graph-v1",
    "CONTRACT_ELEMENT_EXTRACTION": "contract-elements-v1",
}


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
    status: str  # COMPLETED | FAILED | WAITING_HUMAN | CANCELLED
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

    async def _persist_start_metadata(
        self,
        run_id: int,
        graph_name: str,
        graph_version: str,
        model: str,
        prompt_version: str,
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
            )
        except Exception as exc:
            logger.debug("Could not persist graph runtime metadata for run %s: %s", run_id, exc)

    async def run(self, context: Any) -> AgentResult:
        """Execute the graph for a new run."""
        thread_id = f"run-{context.run_id}"
        graph_name = self._graph_name or getattr(context, "graph_name", "unknown")
        graph_version = self._graph_version or getattr(context, "graph_version", "v1")
        model, prompt_version = _runtime_model_metadata(context.task_type)

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
            "trigger_type": "MANUAL",
            "state_revision": 0,
            "case_snapshot": context.project or {},
            "observations": [],
            "citations": [],
            "errors": [],
        }

        config = {
            "configurable": {
                "thread_id": thread_id,
                "run_id": context.run_id,
            }
        }
        await self._persist_start_metadata(
            context.run_id,
            graph_name,
            graph_version,
            model,
            prompt_version,
        )
        try:
            final_state = await self._graph.ainvoke(initial_state, config)
        except Exception as exc:
            err_str = str(exc)
            # GraphInterrupt: graph paused at interrupt_before — expected for HITL
            if "GraphInterrupt" in err_str or "interrupt" in err_str.lower():
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
        return AgentResult(
            run_id=context.run_id,
            status="COMPLETED",
            artifact=artifact,
            observations=final_state.get("observations") or [],
            citations=final_state.get("citations") or [],
            graph_info={
                "runtimeEngine": "langgraph",
                "graphName": final_state.get("graph_name", ""),
                "graphVersion": final_state.get("graph_version", ""),
                "model": final_state.get("model", model),
                "promptVersion": final_state.get("prompt_version", prompt_version),
                "stateRevision": final_state.get("state_revision", 0),
            },
        )

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

    Shadow result is saved for evaluation. Always returns primary result to user.
    Only enabled when AGENT_RUNTIME_SHADOW_ENABLED=true.
    """

    def __init__(self, primary: AgentRuntime, shadow: AgentRuntime):
        self._primary = primary
        self._shadow = shadow

    async def run(self, context: Any) -> AgentResult:
        import asyncio

        primary_task = asyncio.create_task(self._primary.run(context))
        shadow_task = asyncio.create_task(self._shadow.run(context))

        primary_result = await primary_task
        try:
            shadow_result = await shadow_task
            # Log differences for evaluation
            _log_shadow_diff(context.run_id, primary_result, shadow_result)
        except Exception as exc:
            logger.warning("Shadow run failed for run %s: %s", context.run_id, exc)

        return primary_result

    async def resume(self, run_id: int, command: ResumeCommand) -> AgentResult:
        return await self._primary.resume(run_id, command)


def _log_shadow_diff(run_id: int, primary: AgentResult, shadow: AgentResult) -> None:
    """Compare primary and shadow results, log key differences."""
    p_artifact = primary.artifact or {}
    s_artifact = shadow.artifact or {}

    diffs: list[str] = []

    # Compare risk scores
    p_score = p_artifact.get("riskScore") or p_artifact.get("risk_score") or 0
    s_score = s_artifact.get("riskScore") or s_artifact.get("risk_score") or 0
    if p_score != s_score:
        diffs.append(f"riskScore: legacy={p_score} graph={s_score}")

    # Compare finding counts
    p_findings = p_artifact.get("findings") or []
    s_findings = s_artifact.get("findings") or []
    if len(p_findings) != len(s_findings):
        diffs.append(f"findingCount: legacy={len(p_findings)} graph={len(s_findings)}")

    # Compare HIGH severity findings
    p_high = {f.get("title", "") for f in p_findings if str(f.get("severity", "")).upper() == "HIGH"}
    s_high = {f.get("title", "") for f in s_findings if str(f.get("severity", "")).upper() == "HIGH"}
    missing_in_shadow = p_high - s_high
    if missing_in_shadow:
        diffs.append(f"HIGH findings MISSING in graph: {missing_in_shadow}")

    if diffs:
        logger.warning("Shadow diff for run %s: %s", run_id, "; ".join(diffs))
    else:
        logger.info("Shadow run %s: no significant differences", run_id)


class LegacyHarnessAdapter:
    """Wraps the existing AgentRunner as an AgentRuntime implementation."""

    def __init__(self, runner):  # AgentRunner
        self._runner = runner

    async def run(self, context: Any) -> AgentResult:
        raw = await self._runner.execute(context)
        return AgentResult(
            run_id=context.run_id,
            status="COMPLETED" if not raw.get("artifactError") else "FAILED",
            artifact=raw.get("rawArtifact") or {},
            observations=raw.get("observations") or [],
            citations=raw.get("citations") or [],
            scoring=raw.get("scoring") or {},
            graph_info={
                "runtimeEngine": "legacy",
                "graphName": "harness-v1",
                "graphVersion": "legacy",
            },
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
        if mode == "langgraph":
            graph_name = {
                "CONTRACT_REVIEW": "contract_review",
                "FULFILLMENT_CHECK": "fulfillment_check",
                "CONTRACT_ELEMENT_EXTRACTION": "contract_extraction",
                "TIMELINE_EXTRACTION": "timeline_extraction",
            }.get(context.task_type, "")
            adapter = self._adapters.get(graph_name) if graph_name else None
        else:
            adapter = self._adapters.get("legacy")

        if adapter is None:
            adapter = self._adapters.get("legacy")
        if adapter is None:
            adapter = next(iter(self._adapters.values()), None)

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
