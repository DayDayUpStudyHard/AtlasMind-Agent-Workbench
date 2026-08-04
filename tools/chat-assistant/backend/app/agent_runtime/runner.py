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

import redis

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
from .policy import AgentExecutionPolicy, BudgetExceeded, RunCancelled
from .scoring import HealthScoringEngine
from .tools import AgentToolRegistry

logger = logging.getLogger(__name__)

MAX_TOOL_CALLS = 8
MAX_TURNS = 2
TIMEOUT_SECONDS = 300
HEARTBEAT_INTERVAL = 15
CONTRACT_TASK_TYPES = {
    "CONTRACT_REVIEW", "CONTRACT_INTAKE", "APPROVAL_DECISION",
    "VERSION_REVIEW", "OBLIGATION_EXTRACTION", "FULFILLMENT_CHECK",
    "RENEWAL_ASSESSMENT", "RULE_IMPACT_REVIEW", "NEGOTIATION_STRATEGY",
    "FULFILLMENT_BREACH_ANALYSIS", "RULE_EFFECTIVENESS_REVIEW",
}
# When LLM is unreachable, the runner gives each phase at most this many
# seconds before falling back (avoids cascading 12s+ timeouts across 6 phases).
LLM_PER_CALL_TIMEOUT_HARD = 20  # seconds


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
        on_progress=None,  # async callable(run_id, phase, progress, status, step)
    ):
        self.llm = llm
        self.tools = tools
        self.scoring = scoring
        self.run_store = run_store
        self.trace_store = trace_store
        self.evidence_store = evidence_store
        self.report_store = report_store
        self.memory_store = memory_store
        self.on_progress = on_progress
        self._connection_dead = False  # set when LLM is confirmed unreachable

    def _check_connection_error(self, exc: Exception) -> None:
        """If *exc* is a connection error, flag that LLM is unreachable.
        Called from every phase's except block so subsequent phases
        skip straight to fallback instead of retrying dead connections.
        """
        from openai import APIConnectionError, AuthenticationError, PermissionDeniedError
        if isinstance(exc, (APIConnectionError, AuthenticationError, PermissionDeniedError)):
            self._connection_dead = True
            logger.warning("LLM unavailable — subsequent phases will use fallback")

    async def _update_progress(self, ctx: AgentTaskContext, status: str,
                               progress: int, current_step: str = "") -> None:
        """Update run status in DB and optionally publish a progress event."""
        await self.run_store.update_run(
            ctx.run_id, status=status, progress=progress,
            current_step=current_step or f"Harness → {status}",
        )
        if self.on_progress:
            try:
                await self.on_progress(
                    ctx.run_id, status, progress, status,
                    current_step or f"Harness → {status}",
                )
            except Exception:
                pass  # best-effort

    # -- public entry point ------------------------------------------------

    async def execute(self, ctx: AgentTaskContext) -> dict[str, Any]:
        """Run the full six-phase harness loop."""
        self._connection_dead = False
        policy = AgentExecutionPolicy(MAX_TOOL_CALLS, MAX_TURNS, TIMEOUT_SECONDS)
        observations: list[dict] = []
        execution_mode = "native-function-calling"
        contract_mode = self._is_contract(ctx)

        # ── Phase 1: Context Building ───────────────────────────────
        await self._check_cancelled(ctx.run_id)
        await self._update_progress(ctx, "CONTEXT_BUILDING", 8,
                                    "Harness 正在加载合同上下文" if contract_mode
                                    else "Harness 正在加载项目记忆")
        await self._execute_tool(
            ctx, policy, observations, "bootstrap-memory",
            "getContractCase" if contract_mode else "getProjectMemory",
            {} if contract_mode else {"limit": 12},
        )
        await self.trace_store.append_trace(
            ctx.run_id, "MEMORY_LOADED",
            "已加载合同上下文" if contract_mode else "已加载项目记忆",
            {"contextObservations": len(observations)},
        )

        # ── Phase 2: Planning ───────────────────────────────────────
        await self._check_cancelled(ctx.run_id)
        plan = await self._plan(ctx, observations)
        await self.trace_store.append_trace(
            ctx.run_id, "PLAN_CREATED", "Planner 已生成有界执行计划", plan,
        )
        await self._update_progress(ctx, "PLANNING", 18,
                                    "Planner 已生成执行计划")

        # ── Phase 3: Tool-Calling Turn Loop ─────────────────────────
        planner_finished = False
        for turn_index in range(MAX_TURNS):
            await self._check_cancelled(ctx.run_id)
            if policy.remaining_tool_calls() <= 2:
                break
            try:
                policy.begin_turn()
            except BudgetExceeded as exc:
                await self.trace_store.append_trace(
                    ctx.run_id, "BUDGET_EXHAUSTED", str(exc),
                )
                break

            await self._update_progress(
                ctx, "ANALYZING", min(62, 25 + turn_index * 9),
                "Agent 正在选择并调用工具")

            turn = await self._tool_turn(ctx, plan, observations, policy, turn_index)
            calls = turn.get("toolCalls") or []
            if not calls:
                planner_finished = str(turn.get("mode", "")).lower() == "final"
                if planner_finished:
                    break
                continue

            # ── F5: Concurrent tool execution ────────────────────────
            # Group calls by concurrency group, run independent tools
            # within each group via asyncio.gather().
            valid_calls = []
            for call in calls:
                tool_name = str(call.get("name", ""))
                if not tool_name or not self.tools.supports(tool_name):
                    await self.trace_store.append_trace(
                        ctx.run_id, "TOOL_FAILED",
                        "Planner 请求了无效工具",
                        {"toolName": tool_name, "reason": "not allowlisted"},
                    )
                    continue
                valid_calls.append(call)

            if not valid_calls:
                continue

            grouped: dict[str, list[dict]] = {}
            for call in valid_calls:
                group = self.tools.concurrency_group(str(call.get("name", "")))
                grouped.setdefault(group, []).append(call)

            for group_name in self.tools.group_order():
                group_calls = grouped.get(group_name, [])
                if not group_calls:
                    continue

                await self._check_cancelled(ctx.run_id)
                if policy.remaining_tool_calls() <= 2:
                    break

                if len(group_calls) == 1:
                    # Single tool — execute directly
                    call = group_calls[0]
                    await self._execute_tool(
                        ctx, policy, observations,
                        str(call.get("planStepId", f"turn-{turn_index + 1}")),
                        str(call.get("name", "")),
                        call.get("arguments") or {},
                    )
                else:
                    # Multiple independent tools — run concurrently
                    await self.trace_store.append_trace(
                        ctx.run_id, "CONCURRENT_TOOLS",
                        f"并发执行 {len(group_calls)} 个 {group_name} 组工具",
                        {"group": group_name, "tools": [str(c.get("name")) for c in group_calls]},
                    )
                    coros = [
                        self._execute_tool(
                            ctx, policy, observations,
                            str(call.get("planStepId", f"turn-{turn_index + 1}")),
                            str(call.get("name", "")),
                            call.get("arguments") or {},
                        )
                        for call in group_calls
                    ]
                    await asyncio.gather(*coros, return_exceptions=True)

        # ── Phase 4: Evidence & Scoring Guarantee ───────────────────
        await self._check_cancelled(ctx.run_id)
        await self._ensure_evidence_and_scoring(ctx, policy, observations)

        # ── Phase 5: Reflection ─────────────────────────────────────
        await self._check_cancelled(ctx.run_id)
        citations = self.tools.citations_from(observations)
        scoring = self.tools.scoring_from(observations)

        await self._update_progress(ctx, "VERIFYING", 72,
                                    "Reflection 正在核验证据覆盖与引用")
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
        await self._check_cancelled(ctx.run_id)
        await self._update_progress(ctx, "PLANNING", 86,
                                    "执行器正在生成结构化产物")
        raw_artifact = await self._generate_artifact(ctx, observations, citations, scoring)
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

    # -- cancellation -----------------------------------------------------

    async def _check_cancelled(self, run_id: int) -> None:
        """Query the current run status and abort if it has been cancelled."""
        try:
            run = await self.run_store.get_run(run_id)
            if run and run.get("status") == "CANCELLED":
                raise RunCancelled(f"Run {run_id} was cancelled")
        except RunCancelled:
            raise
        except Exception:
            # If we can't read the run (e.g. DB blip), continue —
            # we'd rather finish than abort on a transient read error.
            pass

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
        started = time.monotonic()
        try:
            await self.trace_store.append_trace(
                ctx.run_id, "TOOL_REQUESTED", f"请求工具 {tool_name}",
                {"callId": call_id, "toolName": tool_name, "arguments": arguments},
            )
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
        if self._connection_dead:
            return self._fallback_plan(ctx.task_type, "LLM unreachable")
        try:
            return self.llm.plan_agent({
                "task": self._task_payload(ctx),
                "memory": observations,
                "availableTools": self.tools.definitions(),
                "limits": {"maxToolCalls": MAX_TOOL_CALLS, "maxTurns": MAX_TURNS},
            })
        except Exception as exc:
            self._check_connection_error(exc)
            logger.warning("Planner failed, using fallback: %s", exc)
            return self._fallback_plan(ctx.task_type, str(exc))

    @staticmethod
    def _fallback_plan(task_type: str, reason: str) -> dict:
        if task_type in CONTRACT_TASK_TYPES:
            return {
                "goal": f"完成 {task_type} 并形成可审计合同产物",
                "plannerMode": "fallback",
                "fallbackReason": reason or "planner unavailable",
                "steps": [
                    {"id": "C1", "title": "读取合同案件与文件",
                     "suggestedTools": ["getContractCase", "listContractDocuments"]},
                    {"id": "C2", "title": "读取条款并检索适用制度",
                     "suggestedTools": ["readContractClause", "searchPolicyKnowledge"]},
                    {"id": "C3", "title": "执行规则并计算合同风险",
                     "suggestedTools": ["evaluateReviewRules", "calculateContractRisk"]},
                ],
            }
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
        if self._connection_dead:
            return self._fallback_turn(
                ctx.task_type, observations, "LLM unreachable", ctx.task_input
            )
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
            self._check_connection_error(exc)
            logger.warning("Tool turn failed, using fallback: %s", exc)
            return self._fallback_turn(ctx.task_type, observations, str(exc), ctx.task_input)

    @staticmethod
    def _fallback_turn(
        task_type: str, observations: list[dict], reason: str,
        task_input: dict | None = None,
    ) -> dict[str, Any]:
        if task_type in CONTRACT_TASK_TYPES:
            used = {str(item.get("toolName")) for item in observations}
            if task_type == "FULFILLMENT_CHECK":
                timeline_node_id = int((task_input or {}).get("timelineNodeId") or 0)
                candidates = [
                    ("getContractCase", "C1", {}),
                    ("listContractTimeline", "C1", {"limit": 80}),
                    ("searchPolicyKnowledge", "C2", {"query": "履约核验 验收标准 付款条件 企业制度", "limit": 8}),
                    ("verifyFulfillmentEvidence", "C3", {"timelineNodeId": timeline_node_id}),
                ]
            else:
                candidates = [
                    ("getContractCase", "C1", {}),
                    ("listContractDocuments", "C1", {}),
                    ("readContractClause", "C2", {"limit": 20}),
                    ("searchPolicyKnowledge", "C2", {"query": task_type, "limit": 8}),
                    ("evaluateReviewRules", "C3", {}),
                    ("calculateContractRisk", "C3", {}),
                ]
            calls = [
                {"name": name, "planStepId": step, "arguments": arguments}
                for name, step, arguments in candidates if name not in used
            ][:3]
            return {
                "mode": "tool_calls" if calls else "final",
                "toolCalls": calls,
                "providerMode": "structured-tool-fallback",
                "fallbackReason": reason or "unknown",
            }
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
        if self._connection_dead:
            return self._local_reflection(ctx, observations, citations, "LLM unreachable")
        try:
            return self.llm.reflect_agent({
                "task": self._task_payload(ctx),
                "plan": plan,
                "observations": self._bounded(observations),
                "citationCount": len(citations),
                "plannerFinished": planner_finished,
            })
        except Exception as exc:
            self._check_connection_error(exc)
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
        contract_mode = AgentRunner._is_contract(ctx)
        if adequate:
            suggested = []
        elif contract_mode:
            suggested = [
                {"name": "readContractClause", "arguments": {"limit": 20}},
                {"name": "searchPolicyKnowledge", "arguments": {"query": ctx.task_type, "limit": 8}},
            ]
        else:
            suggested = [{"name": "searchProjectEvidence", "arguments": {"query": "", "limit": 12}}]
        return {
            "adequate": adequate,
            "summary": (
                "本地反思确认已有可引用证据"
                if adequate
                else ("本地反思发现合同条款或制度证据为空" if contract_mode
                      else "本地反思发现项目证据为空")
            ),
            "missingEvidence": [] if adequate else [
                "合同条款或适用制度证据" if contract_mode else "项目仓库或绑定知识证据"
            ],
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
        if self._is_contract(ctx):
            used_tools = {str(item.get("toolName")) for item in observations}
            if (
                ctx.task_type == "FULFILLMENT_CHECK"
                and "verifyFulfillmentEvidence" not in used_tools
                and policy.remaining_tool_calls() > 0
            ):
                await self._execute_tool(
                    ctx, policy, observations,
                    "harness-required-fulfillment", "verifyFulfillmentEvidence",
                    {"timelineNodeId": int((ctx.task_input or {}).get("timelineNodeId") or 0)},
                )
                used_tools.add("verifyFulfillmentEvidence")
            if not self.tools.citations_from(observations) and policy.remaining_tool_calls() > 0:
                await self._execute_tool(
                    ctx, policy, observations,
                    "harness-required-evidence", "readContractClause",
                    {"limit": 20},
                )
                used_tools.add("readContractClause")
            if "searchPolicyKnowledge" not in used_tools and policy.remaining_tool_calls() > 0:
                await self._execute_tool(
                    ctx, policy, observations,
                    "harness-required-policy", "searchPolicyKnowledge",
                    {"query": self._policy_query(ctx), "limit": 8},
                )
                used_tools.add("searchPolicyKnowledge")
            if (
                ctx.task_type == "CONTRACT_REVIEW"
                and not self.tools.scoring_from(observations)
                and policy.remaining_tool_calls() > 0
            ):
                await self._execute_tool(
                    ctx, policy, observations,
                    "harness-required-scoring", "calculateContractRisk", {},
                )
            return
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
        observations: list[dict],
        citations: list[dict],
        scoring: dict[str, Any],
    ) -> dict[str, Any]:
        try:
            # ── Project tasks ──────────────────────────────────
            if ctx.task_type == "HEALTH_ANALYSIS":
                effective_scoring = scoring or (self.scoring.score(
                    ctx.project, citations) if self.scoring else {})
                return self.llm.analyze_project(
                    ctx.project, citations, deterministic_scoring=effective_scoring,
                    run_id=ctx.run_id,
                )
            if ctx.task_type in ("PROJECT_ONBOARDING", "ENGINEERING_DECISION"):
                return self.llm.run_project_task(
                    ctx.task_type, ctx.project, ctx.task_input, citations,
                    run_id=ctx.run_id,
                )

            # ── Contract tasks ─────────────────────────────────
            contract_case = dict(ctx.project)
            findings = []
            for observation in observations:
                output = observation.get("output")
                if not isinstance(output, dict):
                    continue
                if isinstance(output.get("case"), dict):
                    contract_case.update(output["case"])
                if isinstance(output.get("findings"), list):
                    findings.extend(
                        item for item in output["findings"] if isinstance(item, dict)
                    )
                scoring_output = output.get("scoring")
                if isinstance(scoring_output, dict) and isinstance(scoring_output.get("findings"), list):
                    findings.extend(
                        item for item in scoring_output["findings"] if isinstance(item, dict)
                    )
            unique_findings = {}
            for finding in findings:
                key = str(
                    finding.get("ruleId") or finding.get("ruleKey")
                    or finding.get("title") or finding.get("detail") or finding
                )
                unique_findings.setdefault(key, finding)
            findings = list(unique_findings.values())
            if ctx.task_type == "CONTRACT_REVIEW":
                # ── Pre-review metadata extraction (LLM + rules) ──
                meta = await self._ensure_contract_metadata(ctx, contract_case)
                if meta:
                    contract_case.update(meta)
                return self.llm.contract_review(
                    contract_case, findings, citations, scoring or {},
                    run_id=ctx.run_id,
                )
            if ctx.task_type == "CONTRACT_INTAKE":
                return self.llm.contract_intake(
                    contract_case, run_id=ctx.run_id,
                )
            if ctx.task_type == "APPROVAL_DECISION":
                return self.llm.contract_approval(
                    contract_case, findings, scoring or {},
                    run_id=ctx.run_id,
                )
            if ctx.task_type == "FULFILLMENT_CHECK":
                verification = self._fulfillment_verification_from(observations)
                try:
                    return self.llm.contract_fulfillment_check(
                        contract_case, verification, citations, ctx.task_input,
                        run_id=ctx.run_id,
                    )
                except Exception as fulfillment_exc:
                    self._check_connection_error(fulfillment_exc)
                    logger.warning(
                        "Fulfillment artifact LLM failed, using local artifact: %s",
                        fulfillment_exc,
                    )
                    return self._fallback_fulfillment_artifact(
                        ctx, contract_case, verification, citations,
                    )

            # Fallback
            return self.llm.run_project_task(
                ctx.task_type, ctx.project, ctx.task_input, citations,
                run_id=ctx.run_id,
            )
        except Exception as exc:
            self._check_connection_error(exc)
            return {"artifactError": str(exc)}

    # -- episodic memory --------------------------------------------------

    # -- contract metadata extraction (LLM + rules) ------------------------

    async def _ensure_contract_metadata(
        self, ctx: "AgentTaskContext", contract_case: dict
    ) -> dict | None:
        """Extract contract metadata via LLM + deterministic rules, backfill
        high-confidence fields, and stage the rest for human confirmation."""
        case_id = int(contract_case.get("id") or ctx.project.get("id") or ctx.project_id or 0)
        if not case_id:
            return None
        try:
            from .persistence import _conn, _run_sync
            from .contract_intake_extractor import (
                deterministic_hints, validate_extraction,
                _case_backfill_patch, _should_backfill, _ensure_case_party,
            )
            import hashlib, json as _json

            # Get contract text from documents
            def _get_text():
                with _conn() as conn:
                    with conn.cursor() as cur:
                        cur.execute(
                            """SELECT content_text FROM contract_document
                               WHERE case_id=%s AND content_text IS NOT NULL
                               ORDER BY version DESC, id DESC LIMIT 1""",
                            (case_id,),
                        )
                        row = cur.fetchone()
                        return str(row["content_text"]) if row and row.get("content_text") else ""
            text = await _run_sync(_get_text)
            if not text.strip():
                # Try intake table
                def _get_intake_text():
                    with _conn() as conn:
                        with conn.cursor() as cur:
                            cur.execute(
                                """SELECT content_text FROM contract_intake
                                   WHERE case_id=%s AND content_text IS NOT NULL
                                   ORDER BY id DESC LIMIT 1""",
                                (case_id,),
                            )
                            row = cur.fetchone()
                            return str(row["content_text"]) if row and row.get("content_text") else ""
                text = await _run_sync(_get_intake_text)
            if not text.strip():
                logger.info("No contract text found for case %s, skipping metadata extraction", case_id)
                return None

            file_name = str(contract_case.get("title") or contract_case.get("caseKey") or f"contract-{case_id}")
            hints = deterministic_hints(text, file_name)
            raw: dict = {}
            llm_ok = False
            try:
                raw = self.llm.extract_contract_metadata(file_name, text, hints)
                llm_ok = True
            except Exception as exc:
                logger.warning("LLM metadata extraction failed for case %s: %s", case_id, exc)

            validated = validate_extraction(raw, text, hints)
            validated.update({
                "model": getattr(self.llm, "model", "unknown"),
                "promptVersion": "contract-intake-v1",
                "llmAvailable": llm_ok,
            })

            # Backfill high-confidence fields to contract_case
            def _backfill():
                with _conn() as conn:
                    with conn.cursor() as cur:
                        cur.execute(
                            """SELECT id, title, contract_type, our_entity, counterparty,
                                      amount, currency, signed_date, effective_date,
                                      expiry_date, department, status
                               FROM contract_case WHERE id=%s AND deleted=0 FOR UPDATE""",
                            (case_id,),
                        )
                        current = cur.fetchone()
                        if not current:
                            return {}
                        patch = _case_backfill_patch(validated)
                        updates = {}
                        for column, value in patch.items():
                            if _should_backfill(column, current, file_name):
                                updates[column] = value
                        status = str(current.get("status") or "").upper()
                        if status in ("DRAFT", "INTAKE_PARSING", "INTAKE_CONFIRMING"):
                            updates["status"] = "MATERIAL_PENDING"
                        if updates:
                            assignments = ", ".join(f"{col}=%s" for col in updates)
                            values = list(updates.values()) + [case_id]
                            cur.execute(f"UPDATE contract_case SET {assignments} WHERE id=%s", values)
                        # Update parties
                        party_a_val = (patch.get("our_entity") or
                                       (validated.get("fields") or {}).get("partyA", {}).get("value"))
                        party_b_val = (patch.get("counterparty") or
                                       (validated.get("fields") or {}).get("partyB", {}).get("value"))
                        _ensure_case_party(cur, case_id, "OUR_ENTITY_CANDIDATE", party_a_val)
                        _ensure_case_party(cur, case_id, "COUNTERPARTY_CANDIDATE", party_b_val)
                        logger.info("Backfilled %s fields for case %s: %s", len(updates), case_id, list(updates.keys()))
                    conn.commit()
                return updates
            await _run_sync(_backfill)

            # Store in intake for frontend confirmation modal
            content_hash = hashlib.sha256(text.encode()).hexdigest()
            def _upsert_intake():
                with _conn() as conn:
                    with conn.cursor() as cur:
                        cur.execute(
                            "SELECT owner_id FROM contract_case WHERE id=%s",
                            (case_id,),
                        )
                        case_row = cur.fetchone() or {}
                        owner_id = case_row.get("owner_id")
                        cur.execute(
                            """SELECT id FROM contract_intake
                               WHERE case_id=%s AND source_type='FILE' AND status='NEEDS_CONFIRMATION'
                               ORDER BY id DESC LIMIT 1""",
                            (case_id,),
                        )
                        existing = cur.fetchone()
                        if existing:
                            cur.execute(
                                """UPDATE contract_intake
                                   SET validated_json=%s, created_by=COALESCE(created_by, %s), error_message=NULL
                                   WHERE id=%s""",
                                (_json.dumps(validated, ensure_ascii=False), owner_id, existing["id"]),
                            )
                        else:
                            cur.execute(
                                """INSERT INTO contract_intake
                                   (status, source_type, file_name, content_text, content_hash,
                                    validated_json, schema_version, prompt_version, case_id, created_by)
                                   VALUES ('NEEDS_CONFIRMATION','FILE',%s,%s,%s,%s,%s,%s,%s,%s)""",
                                (file_name, text, content_hash,
                                 _json.dumps(validated, ensure_ascii=False),
                                 "contract-intake-v1", "contract-intake-v1", case_id, owner_id),
                            )
                    conn.commit()
            await _run_sync(_upsert_intake)

            # Return a flat dict of extracted fields for the downstream report
            meta = {}
            fields = validated.get("fields") or {}
            for key in ("contractTitle", "contractType", "amount", "currency",
                         "signedDate", "effectiveDate", "expiryDate", "department"):
                v = (fields.get(key) or {}).get("value")
                if v is not None and v != "":
                    meta[key] = v
            party_a = (fields.get("partyA") or {}).get("value")
            party_b = (fields.get("partyB") or {}).get("value")
            if party_a:
                meta["_extractedPartyA"] = party_a
            if party_b:
                meta["_extractedPartyB"] = party_b
            if party_a and party_b:
                meta["_needsOurSideSelection"] = True
            return meta
        except Exception as exc:
            logger.exception("Contract metadata extraction failed for case %s: %s", case_id, exc)
            return None

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

    @staticmethod
    def _fulfillment_verification_from(observations: list[dict]) -> dict[str, Any]:
        for observation in reversed(observations):
            if observation.get("toolName") != "verifyFulfillmentEvidence":
                continue
            output = observation.get("output")
            if isinstance(output, dict):
                return output
        return {}

    @staticmethod
    def _fallback_fulfillment_artifact(
        ctx: AgentTaskContext,
        contract_case: dict,
        verification: dict,
        citations: list[dict],
    ) -> dict[str, Any]:
        conclusion = str(verification.get("conclusion") or "NEEDS_REVIEW")
        missing = verification.get("missingEvidence")
        if not isinstance(missing, list):
            missing = []
        evidence = verification.get("evidenceDocuments")
        if not isinstance(evidence, list):
            evidence = []
        summary = verification.get("summary") or (
            "已完成履约核验，仍需人工确认最终履约结果。"
        )
        return {
            "reportType": "FULFILLMENT_REPORT",
            "title": "履约核验报告",
            "summary": summary,
            "timelineNodeId": int((ctx.task_input or {}).get("timelineNodeId") or 0),
            "conclusion": conclusion,
            "riskLevel": verification.get("riskLevel") or ("HIGH" if missing else "MEDIUM"),
            "confidenceLevel": verification.get("confidenceLevel") or "LOW",
            "requirements": verification.get("requirementItems") or [],
            "evidenceSnapshot": evidence,
            "missingEvidence": missing,
            "explicitConsequence": verification.get("explicitConsequence") or "",
            "aiRisk": verification.get("aiRisk") or "AI 推断仅供参考，不代表合同明确约定。",
            "suggestedActions": verification.get("suggestedActions") or [],
            "citations": citations,
            "content": {
                "case": contract_case,
                "verification": verification,
                "manualConfirmationRequired": True,
            },
        }

    # -- helpers ----------------------------------------------------------

    @staticmethod
    def _is_contract(ctx: AgentTaskContext) -> bool:
        return ctx.subject_type == "CONTRACT_CASE" or ctx.task_type in CONTRACT_TASK_TYPES

    @staticmethod
    def _policy_query(ctx: AgentTaskContext) -> str:
        task_terms = {
            "CONTRACT_REVIEW": "合同审查 企业制度 标准条款 风险 验收 付款 违约",
            "FULFILLMENT_CHECK": "履约核验 验收标准 交付证据 付款条件 企业制度",
            "FULFILLMENT_BREACH_ANALYSIS": "履约违约 逾期 违约责任 免责 通知 企业制度",
            "OBLIGATION_EXTRACTION": "履约义务 付款 交付 验收 通知 续签 企业制度",
            "APPROVAL_DECISION": "合同审批 金额阈值 例外审批 企业制度",
            "RENEWAL_ASSESSMENT": "续签 履约表现 终止 到期 企业制度",
        }
        base = task_terms.get(ctx.task_type, f"{ctx.task_type} 企业制度 标准条款")
        question = (ctx.question or "").strip()
        if question:
            return f"{base} {question}"[:500]
        return base

    @staticmethod
    def _task_payload(ctx: AgentTaskContext) -> dict[str, Any]:
        return {
            "runId": ctx.run_id,
            "projectId": ctx.project_id,
            "subjectType": ctx.subject_type,
            "subjectId": ctx.subject_id,
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
    """Wraps AgentRunner with asyncio task scheduling and heartbeat.

    Publishes progress events to Redis PubSub (channel ``run:{id}:progress``)
    so that the Java SSE endpoint can stream live updates to the frontend.
    """

    def __init__(
        self,
        runner: AgentRunner,
        run_store: RunStore,
        report_store: ReportStore,
    ):
        self.runner = runner
        self.run_store = run_store
        self.report_store = report_store
        self._redis: redis.Redis | None = None

    def _get_redis_sync(self) -> redis.Redis:
        if self._redis is None:
            from app.config import settings
            self._redis = redis.Redis.from_url(
                settings.redis_url,
                decode_responses=True,
                socket_connect_timeout=2,
                socket_timeout=2,
            )
        return self._redis

    async def _publish_progress(self, run_id: int, phase: str, progress: int,
                                status: str, current_step: str) -> None:
        """Publish a progress event to Redis PubSub (best-effort)."""
        try:
            redis_conn = self._get_redis_sync()
            event = json.dumps({
                "runId": run_id,
                "phase": phase,
                "progress": progress,
                "status": status,
                "currentStep": current_step,
                "timestamp": int(time.time()),
            }, ensure_ascii=False)
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(
                None, redis_conn.publish, f"run:{run_id}:progress", event,
            )
        except Exception:
            pass  # progress publishing is best-effort; never fail the run

    async def dispatch(self, run_id: int, request: StartRunRequest) -> None:
        """Launch a harness run as a background asyncio task with heartbeat.

        Enforces a hard timeout (TIMEOUT_SECONDS) on the full harness
        execution so that LLM-unreachable scenarios never hang forever.
        """
        ctx = AgentTaskContext.from_request(run_id, request)
        heartbeat_task = asyncio.create_task(self._heartbeat_loop(run_id))
        try:
            await self.run_store.update_run(
                run_id, status="CONTEXT_BUILDING", progress=0,
                current_step="Harness 开始执行",
            )
            await self._publish_progress(run_id, "CONTEXT_BUILDING", 0,
                                         "CONTEXT_BUILDING", "Harness 开始执行")

            # Enforce global timeout on the full harness
            try:
                result = await asyncio.wait_for(
                    self.runner.execute(ctx), timeout=TIMEOUT_SECONDS,
                )
            except asyncio.TimeoutError:
                await self.trace_store.append_trace(
                    run_id, "HARNESS_TIMEOUT",
                    f"Agent 执行超时（{TIMEOUT_SECONDS}s），可能因 LLM 不可达或任务过于复杂",
                )
                raise RuntimeError(
                    f"Agent 执行超时（{TIMEOUT_SECONDS}s）。"
                    f"可能原因：LLM 服务不可达、网络异常或合同内容过多。"
                    f"请检查 LLM 服务状态后重试。"
                )

            # If runner flagged connection as dead during execution,
            # fail the run with a clear user-facing message.
            if self.runner._connection_dead:
                raise RuntimeError(
                    "LLM 服务不可达，Agent 无法完成合同分析。"
                    "请检查 DeepSeek API 连接（网络 / API Key / 服务状态）后重试。"
                )

            raw = result.get("rawArtifact", {})
            # Merge deterministic scoring metadata into the artifact.
            scoring = result.get("scoring") or {}
            if isinstance(scoring, dict) and scoring:
                for key in ("healthScore", "healthStatus", "dimensions",
                            "riskScore", "riskStatus",
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
            await self._publish_progress(run_id, "COMPLETED", 100,
                                         "COMPLETED", "产物已生成")
        except RunCancelled:
            await self._publish_progress(run_id, "CANCELLED", 0,
                                         "CANCELLED", "任务已取消")
            logger.info("Harness run %s cancelled by external request", run_id)
        except Exception as exc:
            logger.exception("Harness run %s failed", run_id)
            await self.run_store.update_run(
                run_id, status="FAILED", progress=0,
                error_message=str(exc)[:500],
            )
            await self._publish_progress(run_id, "FAILED", 0,
                                         "FAILED", f"执行失败: {str(exc)[:100]}")
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
