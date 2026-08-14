"""Shadow Run (PRD §26.1/§26.2) — Phase 3 task 10.

Deterministic tests, no DB:
* persist_report skips the official report write when shadow_mode is set;
* ShadowAdapter runs both runtimes, flags the shadow context, returns the
  primary result and never lets the shadow failure fail the dispatch;
* RuntimeRouter shadow_v2 routing (CONTRACT_REVIEW → v1 primary + v2 shadow,
  other task types → their v1 graph).
"""
import asyncio

import pytest

from app.agent_runtime.api_models import AgentTaskContext
from app.agent_runtime.runtime import (
    AgentResult,
    RuntimeRouter,
    ShadowAdapter,
)
from app.agent_runtime.graph.nodes.artifact import persist_report


def test_persist_report_skips_store_in_shadow_mode(monkeypatch):
    """A shadow run's report must not overwrite the official report row."""
    import app.agent_runtime.persistence as persistence

    class _ExplodingReportStore:
        @staticmethod
        def _save_sync(*_args, **_kwargs):
            raise AssertionError("shadow run must not persist a report")

    monkeypatch.setattr(persistence, "MySqlReportStore", _ExplodingReportStore)

    state = {
        "run_id": 555,
        "subject_id": 1,
        "shadow_mode": True,
        "artifact": {"reportType": "CONTRACT_REVIEW"},
        "observations": [],
    }
    result = persist_report(state)
    assert result["current_node"] == "persist_report"
    assert result["observations"][0]["toolName"] == "persistReport"
    assert result["observations"][0]["output"] == {"skipped": True}


def test_persist_report_without_shadow_mode_keeps_behavior(monkeypatch):
    """Non-shadow runs keep persisting through MySqlReportStore."""
    import app.agent_runtime.persistence as persistence

    saved = {}

    class _RecordingReportStore:
        @staticmethod
        def _save_sync(subject_id, run_id, task_type, artifact):
            saved.update(
                subject_id=subject_id, run_id=run_id,
                task_type=task_type, artifact=artifact,
            )
            return 777

    monkeypatch.setattr(persistence, "MySqlReportStore", _RecordingReportStore)

    state = {
        "run_id": 556,
        "subject_id": 2,
        "shadow_mode": False,
        "artifact": {"reportType": "CONTRACT_REVIEW"},
    }
    result = persist_report(state)
    assert result["current_node"] == "persist_report"
    assert saved["run_id"] == 556 and saved["subject_id"] == 2
    assert saved["task_type"] == "CONTRACT_REVIEW"


class _FakeRuntime:
    def __init__(self, name: str, *, fail: bool = False):
        self.name = name
        self.fail = fail
        self.contexts: list = []

    async def run(self, context):
        self.contexts.append(context)
        if self.fail:
            raise RuntimeError("shadow exploded")
        return AgentResult(
            run_id=context.run_id,
            status="COMPLETED",
            artifact={"findings": [{"title": "f", "severity": "HIGH"}]},
            graph_info={"graphName": self.name},
        )

    async def resume(self, run_id, command):
        raise NotImplementedError


def _context(run_id=1001, task_type="CONTRACT_REVIEW"):
    return AgentTaskContext(
        run_id=run_id,
        project_id=1,
        task_type=task_type,
        question="",
        subject_type="CONTRACT_CASE",
        subject_id=1,
    )


def test_shadow_adapter_returns_primary_and_flags_shadow_context(monkeypatch):
    """The user-visible result is always the primary's; the shadow executes
    with shadow_mode=True and its failure must not fail the dispatch."""
    import app.agent_runtime.persistence as persistence

    monkeypatch.setattr(
        persistence, "_conn",
        lambda: (_ for _ in ()).throw(AssertionError("no DB in unit tests")),
    )

    async def exercise():
        primary = _FakeRuntime("contract_review")
        shadow = _FakeRuntime("contract_review_v2", fail=True)
        adapter = ShadowAdapter(primary, shadow)
        context = _context()

        result = await adapter.run(context)

        assert result.graph_info["graphName"] == "contract_review"
        assert result.status == "COMPLETED"
        assert len(shadow.contexts) == 1
        assert shadow.contexts[0].shadow_mode is True
        assert shadow.contexts[0].run_id == context.run_id
        assert context.shadow_mode is False, "primary context must stay untouched"

    asyncio.run(exercise())


def test_router_shadow_v2_routes_contract_review_to_v1_plus_v2_shadow(monkeypatch):
    """dispatch_with_mode('shadow_v2') on CONTRACT_REVIEW wires the
    ShadowAdapter (v1 primary + v2 shadow)."""
    import app.agent_runtime.persistence as persistence

    monkeypatch.setattr(
        persistence, "_conn",
        lambda: (_ for _ in ()).throw(AssertionError("no DB in unit tests")),
    )

    async def exercise():
        router = RuntimeRouter()
        primary = _FakeRuntime("contract_review")
        shadow = _FakeRuntime("contract_review_v2")
        router.register("contract_review", primary)
        router.register("contract_review_v2", shadow)

        result = await router.dispatch_with_mode(_context(), "shadow_v2")

        assert result.graph_info["graphName"] == "contract_review"
        assert len(primary.contexts) == 1
        assert len(shadow.contexts) == 1
        assert shadow.contexts[0].shadow_mode is True

    asyncio.run(exercise())


def test_router_shadow_v2_falls_back_to_v1_for_other_tasks():
    """shadow_v2 only exists for CONTRACT_REVIEW; other task types run their
    v1 graph directly (no shadow wrapper)."""

    async def exercise():
        router = RuntimeRouter()
        fulfillment = _FakeRuntime("fulfillment_check")
        router.register("fulfillment_check", fulfillment)

        result = await router.dispatch_with_mode(
            _context(task_type="FULFILLMENT_CHECK"), "shadow_v2",
        )

        assert result.graph_info["graphName"] == "fulfillment_check"
        assert fulfillment.contexts[0].shadow_mode is False

    asyncio.run(exercise())


def test_router_unknown_mode_raises_instead_of_falling_back():
    """2026-08-14 incident guard: an unrecognized runtime mode (e.g. one the
    loaded code predates, like langgraph_v2 in an old API process) must fail
    loudly, never silently run legacy."""

    async def exercise():
        router = RuntimeRouter()
        legacy = _FakeRuntime("legacy")
        router.register("legacy", legacy)

        with pytest.raises(RuntimeError, match="未知运行时模式"):
            await router.dispatch_with_mode(_context(), "langgraph_v2_but_old_code")

        assert legacy.contexts == [], "silent legacy fallback is forbidden"

    asyncio.run(exercise())


def test_router_missing_adapter_raises_instead_of_falling_back():
    """Asking for a graph this process does not have registered (e.g. an old
    process without contract_review_v2) must fail loudly, not run legacy."""

    async def exercise():
        router = RuntimeRouter()
        router.register("contract_review", _FakeRuntime("contract_review"))
        router.register("legacy", _FakeRuntime("legacy"))

        with pytest.raises(RuntimeError, match="无可用适配器"):
            await router.dispatch_with_mode(_context(), "langgraph_v2")

    asyncio.run(exercise())
