"""Agent harness main loop + RunDispatcher with heartbeat.

The AgentRunner owns the six-phase execution loop:
  Phase 1 – Context Building  (load project memory)
  Phase 2 – Planning           (LLM: plan_agent)
  Phase 3 – Tool Calling       (LLM: next_agent_turn, up to 2 turns × 3 calls)
  Phase 4 – Evidence Guarantee (force searchProjectEvidence + calculateHealthScore)
  Phase 5 – Reflection         (LLM: reflect_agent, with optional re-plan)
  Phase 6 – Artifact Generation(LLM: analyze_project / run_project_task)

Every LLM call has a deterministic fallback so the harness never fails silently.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from .api_models import AgentTaskContext, StartRunRequest


def _json_default(obj):
    """Convert non-JSON-serialisable types to primitives."""
    if isinstance(obj, Decimal):
        return float(obj)
    if isinstance(obj, (date, datetime)):
        return obj.isoformat()
    raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")


def _json_dumps(obj, **kwargs):
    return json.dumps(obj, ensure_ascii=False, default=_json_default, **kwargs)
from .persistence import (
    EvidenceStore,
    MemoryStore,
    ReportStore,
    RunStore,
    TraceStore,
)
from .policy import AgentExecutionPolicy, BudgetExceeded
from .scoring import HealthScoringEngine
from .tools import AgentToolRegistry

logger = logging.getLogger(__name__)

MAX_TOOL_CALLS = 8
MAX_TURNS = 2
TIMEOUT_SECONDS = 300
HEARTBEAT_INTERVAL = 15


# ══════════════════════════════════════════════════════════════════════
#  AgentRunner
# ══════════════════════════════════════════════════════════════════════

class AgentRunner:
    """Bounded agent harness. LLM calls are delegated to LLMService methods."""

    def __init__(
        self,
        llm,  # LLMService instance
        tools: AgentToolRegistry,
        scoring: HealthScoringEngine,
        run_store: RunStore,
        trace_store: TraceStore,
        evidence_store: EvidenceStore,
        report_store: ReportStore,
        memory_store: MemoryStore,
    ):
        self.llm = llm
        self.tools = tools
        self.scoring = scoring
        self.run_store = run_store
        self.trace_store = trace_store
        self.evidence_store = evidence_store
        self.report_store = report_store
        self.memory_store = memory_store

    # -- public entry point ------------------------------------------------

    async def execute(self, ctx: AgentTaskContext) -> dict[str, Any]:
        """Run the full six-phase harness loop."""
        policy = AgentExecutionPolicy(MAX_TOOL_CALLS, MAX_TURNS, TIMEOUT_SECONDS)
        observations: list[dict] = []
        execution_mode = "native-function-calling"

        # ── Phase 1: Context Building ───────────────────────────────
        await self.run_store.update_run(
            ctx.run_id, status="CONTEXT_BUILDING", progress=8,
            current_step="Harness 正在加载项目记忆",
        )
        await self._execute_tool(
            ctx, policy, observations, "bootstrap-memory",
            "getProjectMemory", {"limit": 12},
        )
        await self.trace_store.append_trace(
            ctx.run_id, "MEMORY_LOADED", "已加载项目记忆",
            {"memoryObservations": len(observations)},
        )

        # ── Phase 2: Planning ───────────────────────────────────────
        plan = await self._plan(ctx, observations)
        await self.trace_store.append_trace(
            ctx.run_id, "PLAN_CREATED", "Planner 已生成有界执行计划", plan,
        )
        await self.run_store.update_run(
            ctx.run_id, status="PLANNING", progress=18,
            current_step="Planner 已生成执行计划",
        )

        # ── Phase 3: Tool-Calling Turn Loop ─────────────────────────
        planner_finished = False
        for turn_index in range(MAX_TURNS):
            if policy.remaining_tool_calls() <= 2:
                break
            try:
                policy.begin_turn()
            except BudgetExceeded as exc:
                await self.trace_store.append_trace(
                    ctx.run_id, "BUDGET_EXHAUSTED", str(exc),
                )
                break

            await self.run_store.update_run(
                ctx.run_id, status="ANALYZING",
                progress=min(62, 25 + turn_index * 9),
                current_step="Agent 正在选择并调用工具",
            )

            turn = await self._tool_turn(ctx, plan, observations, policy, turn_index)
            calls = turn.get("toolCalls") or []
            if not calls:
                planner_finished = str(turn.get("mode", "")).lower() == "final"
                if planner_finished:
                    break
                continue

            for call in calls:
                if policy.remaining_tool_calls() <= 2:
                    break
                tool_name = str(call.get("name", ""))
                if not tool_name or not self.tools.supports(tool_name):
                    await self.trace_store.append_trace(
                        ctx.run_id, "TOOL_FAILED",
                        "Planner 请求了无效工具",
                        {"toolName": tool_name, "reason": "not allowlisted"},
                    )
                    continue
                await self._execute_tool(
                    ctx, policy, observations,
                    str(call.get("planStepId", f"turn-{turn_index + 1}")),
                    tool_name, call.get("arguments") or {},
                )

        # ── Phase 4: Evidence & Scoring Guarantee ───────────────────
        await self._ensure_evidence_and_scoring(ctx, policy, observations)

        # ── Phase 5: Reflection ─────────────────────────────────────
        citations = self.tools.citations_from(observations)
        scoring = self.tools.scoring_from(observations)

        await self.run_store.update_run(
            ctx.run_id, status="VERIFYING", progress=72,
            current_step="Reflection 正在核验证据覆盖与引用",
        )
        await self.trace_store.append_trace(
            ctx.run_id, "REFLECTION_STARTED",
            "开始检查证据覆盖、引用和任务完成度",
            {"observationCount": len(observations), "citationCount": len(citations)},
        )

        reflection = await self._reflect(ctx, plan, observations, citations, planner_finished)

        if not reflection.get("adequate") and policy.remaining_tool_calls() > 0:
            await self.trace_store.append_trace(
                ctx.run_id, "REPLAN_REQUESTED",
                "Reflection 发现证据缺口，执行补充工具",
                reflection,
            )
            for call in reflection.get("suggestedToolCalls") or []:
                if policy.remaining_tool_calls() <= 0:
                    break
                await self._execute_tool(
                    ctx, policy, observations,
                    "reflection-replan",
                    str(call.get("name", "")),
                    call.get("arguments") or {},
                )
            citations = self.tools.citations_from(observations)

        if ctx.task_type == "HEALTH_ANALYSIS" and not scoring:
            await self._execute_tool(
                ctx, policy, observations,
                "reflection-score-refresh",
                "calculateHealthScore",
                {"snapshotRevision": "post-reflection"},
            )
            scoring = self.tools.scoring_from(observations)

        passed = reflection.get("adequate", False)
        await self.trace_store.append_trace(
            ctx.run_id,
            "REFLECTION_PASSED" if passed else "REFLECTION_FAILED",
            reflection.get("summary", "Reflection 已完成"),
            reflection,
        )

        # ── Phase 6: Artifact Generation ────────────────────────────
        await self.run_store.update_run(
            ctx.run_id, status="PLANNING", progress=86,
            current_step="执行器正在生成结构化产物",
        )
        raw_artifact = await self._generate_artifact(ctx, citations, scoring)
        if "artifactError" in raw_artifact:
            await self.trace_store.append_trace(
                ctx.run_id, "ARTIFACT_FAILED",
                "LLM 产物生成失败，将由规则执行器兜底",
                {"error": raw_artifact["artifactError"]},
            )
        else:
            await self.trace_store.append_trace(
                ctx.run_id, "ARTIFACT_CREATED",
                "结构化任务产物已生成",
                {"taskType": ctx.task_type, "citationCount": len(citations),
                 "executionMode": execution_mode},
            )

        # ── Episodic memory ─────────────────────────────────────────
        await self._persist_episodic_memory(ctx, observations, reflection)

        return {
            "plan": plan,
            "observations": observations,
            "citations": citations,
            "scoring": scoring,
            "reflection": reflection,
            "rawArtifact": raw_artifact,
            "executionMode": execution_mode,
        }

    # -- tool execution ---------------------------------------------------

    async def _execute_tool(
        self,
        ctx: AgentTaskContext,
        policy: AgentExecutionPolicy,
        observations: list[dict],
        plan_step_id: str,
        tool_name: str,
        arguments: dict,
    ) -> None:
        call_id = uuid.uuid4().hex[:12]
        await self.trace_store.save_tool_call_start(
            ctx.run_id, plan_step_id, call_id, tool_name,
            _json_dumps(arguments),
        )
        await self.trace_store.append_trace(
            ctx.run_id, "TOOL_REQUESTED", f"请求工具 {tool_name}",
            {"callId": call_id, "toolName": tool_name, "arguments": arguments},
        )
        started = time.monotonic()
        try:
            policy.reserve_tool_call(tool_name, arguments)
            output = await self.tools.execute(ctx, tool_name, arguments)
            latency = max(0, int((time.monotonic() - started) * 1000))
            await self.trace_store.save_tool_call_done(
                ctx.run_id, call_id, tool_name,
                _json_dumps(output), latency,
            )
            observations.append({
                "callId": call_id,
                "planStepId": plan_step_id,
                "toolName": tool_name,
                "arguments": arguments,
                "output": output,
                "status": "DONE",
            })
        except Exception as exc:
            latency = max(0, int((time.monotonic() - started) * 1000))
            error_msg = str(exc)[:4000]
            await self.trace_store.save_tool_call_failed(
                ctx.run_id, call_id, tool_name, error_msg, latency,
            )
            observations.append({
                "callId": call_id,
                "planStepId": plan_step_id,
                "toolName": tool_name,
                "arguments": arguments,
                "status": "FAILED",
                "error": error_msg,
            })

    # -- planning ---------------------------------------------------------

    async def _plan(
        self, ctx: AgentTaskContext, observations: list[dict]
    ) -> dict[str, Any]:
        try:
            return self.llm.plan_agent({
                "task": self._task_payload(ctx),
                "memory": observations,
                "availableTools": self.tools.definitions(),
                "limits": {"maxToolCalls": MAX_TOOL_CALLS, "maxTurns": MAX_TURNS},
            })
        except Exception as exc:
            logger.warning("Planner failed, using fallback: %s", exc)
            return self._fallback_plan(ctx.task_type, str(exc))

    @staticmethod
    def _fallback_plan(task_type: str, reason: str) -> dict:
        return {
            "goal": f"完成 {task_type} 并形成可审计产物",
            "plannerMode": "fallback",
            "fallbackReason": reason or "planner unavailable",
            "steps": [
                {"id": "P1", "title": "读取项目上下文和记忆",
                 "suggestedTools": ["getProjectProfile", "getProjectMemory"]},
                {"id": "P2", "title": "检索项目证据和适用知识",
                 "suggestedTools": ["searchProjectEvidence", "searchProjectKnowledge"]},
                {"id": "P3", "title": "核验覆盖并生成产物",
                 "suggestedTools": ["getRecentRuns"]},
            ],
        }

    # -- tool turn --------------------------------------------------------

    async def _tool_turn(
        self,
        ctx: AgentTaskContext,
        plan: dict,
        observations: list[dict],
        policy: AgentExecutionPolicy,
        turn_index: int,
    ) -> dict[str, Any]:
        try:
            return self.llm.next_agent_turn({
                "task": self._task_payload(ctx),
                "plan": plan,
                "observations": self._bounded(observations),
                "availableTools": self.tools.definitions(),
                "remainingToolCalls": policy.remaining_tool_calls(),
                "turn": turn_index + 1,
            })
        except Exception as exc:
            logger.warning("Tool turn failed, using fallback: %s", exc)
            return self._fallback_turn(ctx.task_type, observations, str(exc))

    @staticmethod
    def _fallback_turn(
        task_type: str, observations: list[dict], reason: str
    ) -> dict[str, Any]:
        has_evidence = any(
            str(o.get("toolName")) == "searchProjectEvidence" for o in observations
        )
        has_knowledge = any(
            str(o.get("toolName")) == "searchProjectKnowledge" for o in observations
        )
        calls = []
        if not has_evidence:
            calls.append({"name": "searchProjectEvidence", "planStepId": "P2",
                          "arguments": {"query": "", "limit": 12}})
        if not has_knowledge:
            calls.append({"name": "searchProjectKnowledge", "planStepId": "P2",
                          "arguments": {"query": task_type, "limit": 5}})
        if not calls:
            calls.append({"name": "getRecentRuns", "planStepId": "P3",
                          "arguments": {"limit": 5}})
        return {
            "mode": "tool_calls", "toolCalls": calls,
            "providerMode": "structured-tool-fallback",
            "fallbackReason": reason or "unknown",
        }

    # -- reflection -------------------------------------------------------

    async def _reflect(
        self,
        ctx: AgentTaskContext,
        plan: dict,
        observations: list[dict],
        citations: list[dict],
        planner_finished: bool,
    ) -> dict[str, Any]:
        try:
            return self.llm.reflect_agent({
                "task": self._task_payload(ctx),
                "plan": plan,
                "observations": self._bounded(observations),
                "citationCount": len(citations),
                "plannerFinished": planner_finished,
            })
        except Exception as exc:
            logger.warning("Reflection failed, using local fallback: %s", exc)
            return self._local_reflection(ctx, observations, citations, str(exc))

    @staticmethod
    def _local_reflection(
        ctx: AgentTaskContext,
        observations: list[dict],
        citations: list[dict],
        reason: str,
    ) -> dict[str, Any]:
        adequate = len(citations) > 0
        suggested = (
            []
            if adequate
            else [{"name": "searchProjectEvidence", "arguments": {"query": "", "limit": 12}}]
        )
        return {
            "adequate": adequate,
            "summary": (
                "本地反思确认已有可引用项目证据"
                if adequate
                else "本地反思发现项目证据为空"
            ),
            "missingEvidence": [] if adequate else ["项目仓库或绑定知识证据"],
            "suggestedToolCalls": suggested,
            "reflectionMode": "local-fallback",
            "fallbackReason": reason or "unknown",
            "taskType": ctx.task_type,
            "observationCount": len(observations),
        }

    # -- evidence & scoring guarantee -------------------------------------

    async def _ensure_evidence_and_scoring(
        self,
        ctx: AgentTaskContext,
        policy: AgentExecutionPolicy,
        observations: list[dict],
    ) -> None:
        if not self.tools.citations_from(observations) and policy.remaining_tool_calls() > 0:
            await self._execute_tool(
                ctx, policy, observations,
                "harness-required-evidence", "searchProjectEvidence",
                {"query": "", "limit": 12},
            )
        if (
            ctx.task_type == "HEALTH_ANALYSIS"
            and not self.tools.scoring_from(observations)
            and policy.remaining_tool_calls() > 0
        ):
            await self._execute_tool(
                ctx, policy, observations,
                "harness-required-scoring", "calculateHealthScore", {},
            )

    # -- artifact generation ----------------------------------------------

    async def _generate_artifact(
        self,
        ctx: AgentTaskContext,
        citations: list[dict],
        scoring: dict[str, Any],
    ) -> dict[str, Any]:
        try:
            if ctx.task_type == "HEALTH_ANALYSIS":
                effective_scoring = scoring or self.scoring.score(
                    ctx.project, citations,
                )
                return self.llm.analyze_project(
                    ctx.project, citations, deterministic_scoring=effective_scoring,
                )
            return self.llm.run_project_task(
                ctx.task_type, ctx.project, ctx.task_input, citations,
            )
        except Exception as exc:
            return {"artifactError": str(exc)}

    # -- episodic memory --------------------------------------------------

    async def _persist_episodic_memory(
        self,
        ctx: AgentTaskContext,
        observations: list[dict],
        reflection: dict[str, Any],
    ) -> None:
        tools_used = ", ".join(
            sorted({str(o.get("toolName", "")) for o in observations if o.get("toolName")})
        ) or "无"
        content = (
            f"任务：{ctx.question}\n"
            f"调用工具：{tools_used}\n"
            f"反思：{reflection.get('summary', '未返回反思摘要')}"
        )
        await self.memory_store.save_memory(
            ctx.project_id, ctx.run_id,
            "EPISODIC", f"Agent Run #{ctx.run_id} 执行记忆",
            content, str(ctx.run_id),
        )
        await self.trace_store.append_trace(
            ctx.run_id, "MEMORY_WRITTEN",
            "已写入待确认的情节记忆",
            {"memoryType": "EPISODIC", "confirmed": False},
        )

    # -- helpers ----------------------------------------------------------

    @staticmethod
    def _task_payload(ctx: AgentTaskContext) -> dict[str, Any]:
        return {
            "runId": ctx.run_id,
            "projectId": ctx.project_id,
            "taskType": ctx.task_type,
            "question": ctx.question,
            "project": ctx.project,
            "taskInput": ctx.task_input,
        }

    @staticmethod
    def _bounded(observations: list[dict]) -> list[dict]:
        """Return the last 12 observations to stay within context limits."""
        return observations[-12:] if len(observations) > 12 else observations


# ══════════════════════════════════════════════════════════════════════
#  RunDispatcher  (asyncio scheduling + heartbeat)
# ══════════════════════════════════════════════════════════════════════

class RunDispatcher:
    """Wraps AgentRunner with asyncio task scheduling and heartbeat."""

    def __init__(
        self,
        runner: AgentRunner,
        run_store: RunStore,
        report_store: ReportStore,
    ):
        self.runner = runner
        self.run_store = run_store
        self.report_store = report_store

    async def dispatch(self, run_id: int, request: StartRunRequest) -> None:
        """Launch a harness run as a background asyncio task with heartbeat."""
        ctx = AgentTaskContext.from_request(run_id, request)
        heartbeat_task = asyncio.create_task(self._heartbeat_loop(run_id))
        try:
            await self.run_store.update_run(
                run_id, status="CONTEXT_BUILDING", progress=0,
                current_step="Harness 开始执行",
            )
            result = await self.runner.execute(ctx)
            raw = result.get("rawArtifact", {})
            # Merge deterministic scoring metadata into the artifact.
            # For fields the scoring engine owns, always prefer its output
            # over the LLM's text rendering (the LLM may drop weight, hash, etc.).
            scoring = result.get("scoring") or {}
            if isinstance(scoring, dict) and scoring:
                # Deterministic fields — always take from scoring engine
                for key in ("healthScore", "healthStatus", "dimensions",
                            "scoringVersion", "evidenceHash", "analysisMode",
                            "scoringRationale", "risks", "citations"):
                    if key in scoring:
                        raw[key] = scoring[key]
            await self.report_store.save_report(
                ctx.project_id, run_id, ctx.task_type, raw,
            )
            await self.run_store.update_run(
                run_id, status="COMPLETED", progress=100,
                current_step="产物已生成",
            )
        except Exception as exc:
            logger.exception("Harness run %s failed", run_id)
            await self.run_store.update_run(
                run_id, status="FAILED", progress=0,
                error_message=str(exc)[:500],
            )
        finally:
            heartbeat_task.cancel()
            try:
                await heartbeat_task
            except asyncio.CancelledError:
                pass

    async def _heartbeat_loop(self, run_id: int) -> None:
        while True:
            await asyncio.sleep(HEARTBEAT_INTERVAL)
            try:
                await self.run_store.heartbeat(run_id)
            except Exception:
                logger.warning("Heartbeat write failed for run %s", run_id, exc_info=True)
