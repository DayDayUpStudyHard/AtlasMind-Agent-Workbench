"""Runtime lifecycle contract tests (PRD §14-5, Phase 4 task 7).

One suite pinning the common lifecycle every contract graph shares through
GraphAdapter — the pieces the harness migration must not regress:

* 成功          → COMPLETED + artifact passthrough + graph_info metadata
* FAILED        → exception captured as artifactError (never a crash)
* 降级          → graph ends without artifact ⇒ FAILED with lastNode,
                  never a false COMPLETED; snapshot load failure ⇒ FAILED
                  (never an empty-snapshot run — 验收 P0)
* WAITING_HUMAN → GraphInterrupt typed on the exception CLASS (Chinese-only
                  messages stay HITL, "interrupted" plain failures stay
                  FAILED — 验收 P1)
* Resume        → success carries the human payload; failure is FAILED;
                  old-shape checkpoints (missing newer fields) still resume;
                  a re-interrupt stays WAITING_HUMAN
* 心跳          → task reference kept on the adapter, cancelled on every
                  run() exit; the loop's active set excludes WAITING_HUMAN
                  (paused runs never keep beating — 验收 P1)
* 预算          → `_retry_limit_override` ContextVar contract behind the v1
                  reflection gate; AgentExecutionPolicy turn/tool-call caps
                  and the 300s wall-clock run timeout; reranker external
                  call carries the configured timeout and degrades (验收 P2)
* Observation   → state reducer dedups by callId; observations survive the
                  WAITING_HUMAN result

Matrix elements pinned elsewhere (deliberately not duplicated):

* heartbeat loop start / stop-on-terminal → tests/test_graph_runtime_adapter.py
* sweeper 超时 rules (900s active-run kill requires stale heartbeat)
  → tests/test_recovery.py
* rerank-off / ES-unavailable 降级 → tests/test_harness.py
* policy.py turn / tool-call / time budgets → tests/test_agent_policy.py
"""

from __future__ import annotations

import asyncio

import pytest
from langgraph.checkpoint.memory import MemorySaver
from langgraph.errors import GraphInterrupt
from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from app.agent_runtime.api_models import AgentTaskContext
from app.agent_runtime.graph.contract_review import _route_after_reflection
from app.agent_runtime.graph.state import BaseGraphState
from app.agent_runtime.harness.fakes import FakePersistence
from app.agent_runtime.runtime import (
    GraphAdapter,
    ResumeAction,
    ResumeCommand,
    _retry_limit_override,
)


def _context(run_id: int) -> AgentTaskContext:
    return AgentTaskContext(
        run_id=run_id,
        project_id=1,
        task_type="CONTRACT_REVIEW",
        question="",
        subject_type="CONTRACT_CASE",
        subject_id=1,
        project={},
        task_input={},
    )


def _adapter(graph, run_id: int, *, run_store=None, name="contract_review"):
    return GraphAdapter(graph, graph_name=name, graph_version="v1", run_store=run_store)


# ── 成功 ─────────────────────────────────────────────────────────────────────


def test_success_run_returns_completed_with_artifact_and_metadata():
    def final_node(state):
        return {
            "artifact": {"reportType": "CONTRACT_REVIEW_REPORT", "content": {"ok": True}},
            "current_node": "final_node",
            "state_revision": 1,
            "observations": [{"callId": "o1", "toolName": "compose"}],
        }

    builder = StateGraph(BaseGraphState)
    builder.add_node("final_node", final_node)
    builder.add_edge(START, "final_node")
    builder.add_edge("final_node", END)

    store = FakePersistence()
    adapter = _adapter(builder.compile(), 7001, run_store=store)

    async def exercise():
        result = await adapter.run(_context(7001))
        assert result.status == "COMPLETED"
        assert result.ok
        assert result.artifact["reportType"] == "CONTRACT_REVIEW_REPORT"
        assert result.observations[0]["callId"] == "o1"
        info = result.graph_info
        assert info["runtimeEngine"] == "langgraph"
        assert info["graphName"] == "contract_review"
        assert info["graphVersion"] == "v1"
        assert "model" in info  # populated from _runtime_model_metadata
        assert info["promptVersion"]
        assert info["stateRevision"] == 1
        # runtime metadata persisted before execution (identifiable even if
        # the graph dies before the first checkpoint)
        assert store.metadata
        assert store.metadata[0][0] == 7001
        assert store.metadata[0][1]["runtime_engine"] == "langgraph"
        assert store.metadata[0][1]["graph_name"] == "contract_review"

    asyncio.run(exercise())


# ── FAILED / 降级 ────────────────────────────────────────────────────────────


def test_failed_run_captures_exception_as_artifact_error():
    def boom(state):
        raise RuntimeError("检索通道爆炸")

    builder = StateGraph(BaseGraphState)
    builder.add_node("boom", boom)
    builder.add_edge(START, "boom")
    builder.add_edge("boom", END)

    adapter = _adapter(builder.compile(), 7002)

    async def exercise():
        result = await adapter.run(_context(7002))
        assert result.status == "FAILED"
        assert not result.ok
        assert "检索通道爆炸" in result.artifact["artifactError"]
        assert result.graph_info["runtimeEngine"] == "langgraph"

    asyncio.run(exercise())


def test_graph_without_artifact_is_failed_with_last_node():
    """降级: a graph that reaches the end without composing an artifact must
    be FAILED with the last node named — never a false COMPLETED."""

    def noop(state):
        return {"current_node": "noop"}

    builder = StateGraph(BaseGraphState)
    builder.add_node("noop", noop)
    builder.add_edge(START, "noop")
    builder.add_edge("noop", END)

    adapter = _adapter(builder.compile(), 7003)

    async def exercise():
        result = await adapter.run(_context(7003))
        assert result.status == "FAILED"
        assert "noop" in result.artifact["artifactError"]
        assert result.graph_info["lastNode"] == "noop"

    asyncio.run(exercise())


def test_snapshot_load_failure_fails_the_run(monkeypatch):
    """验收 P0: a snapshot load failure must end the run as FAILED — never
    degrade into an empty-snapshot run that fabricates "缺少条款" risks
    against zero evidence (PRD §14-5)."""
    import app.agent_runtime.graph.nodes.context as context_nodes

    def explode(case_id, requested_document_id=0, include_content_text=False):
        raise RuntimeError("MySQL 连接失败")

    monkeypatch.setattr(context_nodes, "load_contract_evidence_snapshot", explode)

    builder = StateGraph(BaseGraphState)
    builder.add_node("load_run_context", context_nodes.load_run_context)
    builder.add_node("finish", lambda state: {"artifact": {"content": {}}})
    builder.add_edge(START, "load_run_context")
    builder.add_edge("load_run_context", "finish")
    builder.add_edge("finish", END)

    adapter = _adapter(builder.compile(), 7009)

    async def exercise():
        result = await adapter.run(_context(7009))
        assert result.status == "FAILED"
        assert "证据快照加载失败" in result.artifact["artifactError"]

    asyncio.run(exercise())


# ── WAITING_HUMAN ────────────────────────────────────────────────────────────


class _InterruptRaisingGraph:
    """Fake graph whose ainvoke raises GraphInterrupt — the graph-style HITL
    signal the adapter must translate to WAITING_HUMAN, not FAILED.

    The message carries NO English "interrupt" marker on purpose (验收 P1):
    the contract is the exception TYPE, never message text.
    """

    def __init__(self):
        self.ainvoke_calls = 0

    async def ainvoke(self, state, config=None):
        self.ainvoke_calls += 1
        raise GraphInterrupt("等待人工确认")


def test_graph_interrupt_exception_is_waiting_human_not_failed():
    adapter = _adapter(_InterruptRaisingGraph(), 7004)

    async def exercise():
        result = await adapter.run(_context(7004))
        assert result.status == "WAITING_HUMAN"
        assert result.artifact == {}
        # exception path has no final_state to read → generic waitState marker
        assert result.graph_info["waitState"] == {"type": "WAITING_HUMAN"}

    asyncio.run(exercise())


class _InterruptedMessageGraph:
    """A plain failure whose message happens to say "interrupted" — the
    inverse trap of the text-sniffing contract (验收 P1): it must stay
    FAILED, never be misread as a human pause."""

    async def ainvoke(self, state, config=None):
        raise RuntimeError("connection interrupted: socket read timeout")


def test_plain_failure_with_interrupt_in_message_stays_failed():
    adapter = _adapter(_InterruptedMessageGraph(), 7014)

    async def exercise():
        result = await adapter.run(_context(7014))
        assert result.status == "FAILED"
        assert "connection interrupted" in result.artifact["artifactError"]

    asyncio.run(exercise())


class _InterruptStateGraph:
    """Fake graph whose ainvoke *returns* a state carrying __interrupt__ —
    the interrupt_before / re-interrupt HITL path (no exception raised)."""

    async def ainvoke(self, state, config=None):
        return {
            **state,
            "__interrupt__": True,
            "wait_state": {"type": "WAITING_HUMAN", "target": "fulfillment"},
            "observations": [{"callId": "pre-interrupt", "toolName": "wait"}],
        }

    async def aget_state(self, config=None):
        class _Snapshot:
            values = {"wait_state": {"type": "WAITING_HUMAN", "target": "acceptance"}}

        return _Snapshot()


def test_interrupt_state_passthrough_observations_and_snapshot_wait_state():
    """__interrupt__ return path: observations emitted before the pause
    survive WAITING_HUMAN, and the checkpoint snapshot wins over the
    state-level wait_state."""
    adapter = _adapter(_InterruptStateGraph(), 7008)

    async def exercise():
        result = await adapter.run(_context(7008))
        assert result.status == "WAITING_HUMAN"
        assert [o["callId"] for o in result.observations] == ["pre-interrupt"]
        assert result.graph_info["waitState"]["target"] == "acceptance"

    asyncio.run(exercise())


# ── 心跳生命周期（验收 P1：任务引用 + 取消 + WAITING_HUMAN 不持续心跳）──


def test_heartbeat_task_cancelled_when_run_returns_waiting_human(monkeypatch):
    """A paused run must not keep a heartbeat task alive. The task reference
    lives on the adapter and is cancelled on every run() exit path."""
    import app.agent_runtime.runtime as runtime

    monkeypatch.setattr(runtime, "GRAPH_HEARTBEAT_INTERVAL", 0.01)

    store = FakePersistence(default_status="WAITING_HUMAN")
    adapter = _adapter(_InterruptRaisingGraph(), 7010, run_store=store)

    async def exercise():
        result = await adapter.run(_context(7010))
        assert result.status == "WAITING_HUMAN"
        assert adapter._heartbeat_task is None  # reference cleared
        # let any pending tick surface — the paused run never beats
        await asyncio.sleep(0.05)
        assert store.heartbeats == []

    asyncio.run(exercise())


def test_heartbeat_loop_self_terminates_on_waiting_human_row(monkeypatch):
    """The loop's active set excludes WAITING_HUMAN (the sweeper never kills
    paused rows): a row already paused exits the loop before the first beat.
    Beats-while-active + stop-on-terminal are pinned in
    test_graph_runtime_adapter.test_graph_adapter_heartbeats_run_and_stops_when_terminal."""
    import app.agent_runtime.runtime as runtime

    monkeypatch.setattr(runtime, "GRAPH_HEARTBEAT_INTERVAL", 0.01)

    store = FakePersistence(statuses={7011: "WAITING_HUMAN"})

    async def exercise():
        adapter = runtime.GraphAdapter(None, run_store=store)
        await adapter._heartbeat_loop(7011)
        assert store.heartbeats == []

    asyncio.run(exercise())


# ── Resume ───────────────────────────────────────────────────────────────────


def test_resume_without_checkpoint_is_failed_with_artifact_error():
    builder = StateGraph(BaseGraphState)
    builder.add_node("final_node", lambda state: {"artifact": {"content": {}}})
    builder.add_edge(START, "final_node")
    builder.add_edge("final_node", END)

    adapter = _adapter(builder.compile(), 7005)  # no checkpointer → resume impossible

    async def exercise():
        result = await adapter.resume(
            7005,
            ResumeCommand(action=ResumeAction.CONFIRM, manual_result="SATISFIED"),
        )
        assert result.status == "FAILED"
        assert result.artifact["artifactError"]

    asyncio.run(exercise())


def test_resume_re_interrupt_stays_waiting_human():
    """A graph that pauses again after the human input is still HITL — the
    second interrupt must not be reported as a failure (typed contract)."""

    class _ReInterruptGraph:
        async def ainvoke(self, state, config=None):
            raise GraphInterrupt("再次等待人工确认")

    adapter = _adapter(_ReInterruptGraph(), 7015)

    async def exercise():
        result = await adapter.resume(
            7015, ResumeCommand(action=ResumeAction.CONFIRM, manual_result="SATISFIED"),
        )
        assert result.status == "WAITING_HUMAN"
        assert result.graph_info["waitState"] == {"type": "WAITING_HUMAN"}

    asyncio.run(exercise())


def _build_hitl_graph():
    def set_wait(state):
        return {
            "wait_state": {"type": "WAITING_HUMAN", "target": "fulfillment"},
            "observations": [{"callId": "pre-interrupt", "toolName": "wait"}],
        }

    def gate(state):
        resume_payload = interrupt({"question": "同意?"}) or {}
        return {"manual_result": resume_payload.get("manual_result")}

    def apply_human(state):
        return {
            "artifact": {"content": {"manualResult": state.get("manual_result")}},
            "current_node": "apply_human",
        }

    builder = StateGraph(BaseGraphState)
    builder.add_node("set_wait", set_wait)
    builder.add_node("gate", gate)
    builder.add_node("apply_human", apply_human)
    builder.add_edge(START, "set_wait")
    builder.add_edge("set_wait", "gate")
    builder.add_edge("gate", "apply_human")
    builder.add_edge("apply_human", END)
    return builder


def test_resume_against_old_checkpoint_shape_tolerates_missing_fields():
    """旧 Checkpoint: a checkpoint written by an older schema (no wait_state)
    must still resume — missing fields fall back, never crash."""
    saver = MemorySaver()
    graph = _build_hitl_graph().compile(checkpointer=saver)
    adapter = _adapter(graph, 7006)

    async def exercise():
        paused = await adapter.run(_context(7006))
        assert paused.status == "WAITING_HUMAN"
        # this langgraph returns the interrupted state (__interrupt__) rather
        # than raising: wait_state and pre-interrupt observations survive
        assert paused.graph_info["waitState"]["target"] == "fulfillment"
        assert [o["callId"] for o in paused.observations] == ["pre-interrupt"]

        # Simulate an old-schema checkpoint: wait_state did not exist yet.
        # (get_tuple needs checkpoint_ns filled — ainvoke supplies its own default.)
        config = {
            "configurable": {
                "thread_id": "run-7006",
                "run_id": 7006,
                "checkpoint_ns": "",
            }
        }
        saved = saver.get_tuple(config)
        checkpoint = saved.checkpoint
        checkpoint["channel_values"].pop("wait_state", None)
        saver.put(config, checkpoint, saved.metadata, {})

        resumed = await adapter.resume(
            7006,
            ResumeCommand(action=ResumeAction.CONFIRM, manual_result="SATISFIED"),
        )
        assert resumed.status == "COMPLETED"
        assert resumed.artifact["content"]["manualResult"] == "SATISFIED"

    asyncio.run(exercise())


# ── 预算 ─────────────────────────────────────────────────────────────────────


def test_retry_budget_override_contract():
    """`_retry_limit_override` ContextVar is the graph budget knob: unset
    (or negative) → one targeted-retrieval round; 0 → none; N → N rounds.
    CONFIRMED / CANNOT_RESOLVE bypass the budget entirely."""
    need_more = {"coverage": {"status": "NEED_MORE_EVIDENCE"}, "retry_state": {}}

    # unset: default budget is 1 round
    assert _route_after_reflection({**need_more, "retry_state": {"reflection_rounds": 0}}) \
        == "targeted_retrieval"
    assert _route_after_reflection({**need_more, "retry_state": {"reflection_rounds": 1}}) \
        == "compose_limited_report"

    # negative override collapses to the default (never unbounded)
    token = _retry_limit_override.set(-5)
    try:
        assert _route_after_reflection({**need_more, "retry_state": {"reflection_rounds": 0}}) \
            == "targeted_retrieval"
        assert _route_after_reflection({**need_more, "retry_state": {"reflection_rounds": 1}}) \
            == "compose_limited_report"
    finally:
        _retry_limit_override.reset(token)

    # override 0: targeted retrieval forbidden, degrade straight to limited
    token = _retry_limit_override.set(0)
    try:
        assert _route_after_reflection({**need_more, "retry_state": {"reflection_rounds": 0}}) \
            == "compose_limited_report"
    finally:
        _retry_limit_override.reset(token)

    # override 2: two rounds allowed
    token = _retry_limit_override.set(2)
    try:
        assert _route_after_reflection({**need_more, "retry_state": {"reflection_rounds": 0}}) \
            == "targeted_retrieval"
        assert _route_after_reflection({**need_more, "retry_state": {"reflection_rounds": 1}}) \
            == "targeted_retrieval"
        assert _route_after_reflection({**need_more, "retry_state": {"reflection_rounds": 2}}) \
            == "compose_limited_report"
    finally:
        _retry_limit_override.reset(token)

    # terminal coverage statuses never re-enter retrieval regardless of budget
    assert _route_after_reflection({"coverage": {"status": "CONFIRMED"}, "retry_state": {}}) \
        == "compose_report"
    assert _route_after_reflection({"coverage": {"status": "CANNOT_RESOLVE"}, "retry_state": {}}) \
        == "compose_limited_report"


def test_execution_policy_llm_loop_budgets():
    """LLM/Token 预算 (验收 P2): the LLM loop is bounded by tool-call count
    (8) and turn count (2) — both raising BudgetExceeded — and exposes its
    remaining budget. Ported from Java AgentExecutionPolicy, identical
    semantics."""
    from app.agent_runtime.policy import AgentExecutionPolicy, BudgetExceeded

    policy = AgentExecutionPolicy(max_tool_calls=8, max_turns=2, timeout_seconds=300)
    assert policy.max_tool_calls == 8
    assert policy.max_turns == 2
    assert policy.remaining_tool_calls() == 8

    policy.begin_turn()
    for index in range(8):
        policy.reserve_tool_call(f"tool_{index}", {})
    assert policy.remaining_tool_calls() == 0
    with pytest.raises(BudgetExceeded):
        policy.reserve_tool_call("tool_9", {})

    policy.begin_turn()  # turn 2 allowed
    with pytest.raises(BudgetExceeded):
        policy.begin_turn()  # turn 3 blocked


def test_execution_policy_wall_clock_deadline_is_the_run_timeout(monkeypatch):
    """Run 超时 (验收 P2): 300s wall-clock deadline — any further turn or
    tool call after the deadline raises BudgetExceeded, even with budget
    left."""
    from app.agent_runtime.policy import AgentExecutionPolicy, BudgetExceeded

    clock = {"now": 0.0}
    monkeypatch.setattr("app.agent_runtime.policy.time.monotonic", lambda: clock["now"])

    policy = AgentExecutionPolicy(timeout_seconds=300)
    clock["now"] = 301.0
    with pytest.raises(BudgetExceeded):
        policy.begin_turn()
    with pytest.raises(BudgetExceeded):
        policy.reserve_tool_call("any", {})


def test_reranker_external_call_carries_configured_timeout_and_degrades(monkeypatch):
    """外部服务超时 (验收 P2): the reranker HTTP call must carry the
    configured timeout, and a provider stall degrades to the keyword
    fallback — never hangs the graph, never crashes the run."""
    import urllib.request

    import app.agent_runtime.reranker as reranker_mod

    class _Settings:
        reranker_api_key = "k"
        reranker_base_url = "http://reranker.internal"
        reranker_model = "m"
        reranker_timeout_seconds = 7

    timeouts: list[float] = []

    def fake_urlopen(request, timeout):
        timeouts.append(timeout)
        raise TimeoutError("provider stalled")

    monkeypatch.setattr(reranker_mod, "settings", _Settings)
    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

    reranker = reranker_mod.LLMReranker()
    hits = [{"clauseId": 1, "title": "A", "content": "甲"}, {"clauseId": 2, "title": "B", "content": "乙"}]
    result = reranker.rerank_contract_clauses("付款", hits, 2)

    assert timeouts == [7]  # the configured timeout was actually used
    assert len(result) == 2  # degraded to keyword fallback, evidence preserved


# ── Observation ──────────────────────────────────────────────────────────────


def test_observation_reducer_dedups_by_call_id():
    """Two nodes emitting the same callId → one observation (first wins);
    entries without a callId always append."""

    def emit_a(state):
        return {"observations": [{"callId": "dup", "toolName": "a"}]}

    def emit_b(state):
        return {
            "observations": [
                {"callId": "dup", "toolName": "b"},
                {"toolName": "no-call-id"},
            ]
        }

    def finish(state):
        return {"artifact": {"content": {}}}

    builder = StateGraph(BaseGraphState)
    builder.add_node("emit_a", emit_a)
    builder.add_node("emit_b", emit_b)
    builder.add_node("finish", finish)
    builder.add_edge(START, "emit_a")
    builder.add_edge("emit_a", "emit_b")
    builder.add_edge("emit_b", "finish")
    builder.add_edge("finish", END)

    adapter = _adapter(builder.compile(), 7007)

    async def exercise():
        result = await adapter.run(_context(7007))
        assert result.status == "COMPLETED"
        call_ids = [o.get("callId") for o in result.observations]
        assert call_ids.count("dup") == 1
        assert result.observations[0]["toolName"] == "a"  # 首现保留
        assert call_ids.count(None) == 1

    asyncio.run(exercise())
