import asyncio

from langgraph.checkpoint.memory import MemorySaver

from app.agent_runtime.api_models import AgentTaskContext
from app.agent_runtime.runtime import GraphAdapter, ResumeCommand, ResumeAction
from app.agent_runtime.graph.checkpoint import MySqlCheckpointSaver


class _CompletedGraph:
    def __init__(self):
        self.initial_state = None

    async def ainvoke(self, state, _config):
        self.initial_state = dict(state)
        return {
            **state,
            "artifact": {"reportType": "CONTRACT_ELEMENT_EXTRACTION"},
        }


class _RecordingRunStore:
    def __init__(self):
        self.runtime_metadata = []

    async def set_runtime_metadata(self, run_id, **kwargs):
        self.runtime_metadata.append((run_id, kwargs))


def test_mysql_checkpoint_versions_are_strictly_monotonic():
    saver = MySqlCheckpointSaver()

    assert saver.get_next_version(None, None) == 1
    assert saver.get_next_version(1, None) == 2
    assert saver.get_next_version(7, None) == 8
    assert saver.get_next_version(1.5, None) > 1.5


def test_mysql_checkpoint_accepts_fulfillment_evidence_list(monkeypatch):
    """The human-gate evidence list must not make a checkpoint unresumable."""
    import app.agent_runtime.persistence as persistence

    executed = []

    class Cursor:
        rowcount = 1

        def __enter__(self): return self
        def __exit__(self, *_): return None
        def execute(self, sql, params=()):
            executed.append(sql)

    class Connection:
        def __enter__(self): return self
        def __exit__(self, *_): return None
        def cursor(self): return Cursor()
        def commit(self): pass

    monkeypatch.setattr(persistence, "_conn", lambda: Connection())
    saver = MySqlCheckpointSaver()
    saver.put(
        {"configurable": {"thread_id": "run-42", "run_id": 42}},
        {
            "id": "checkpoint-42",
            "channel_values": {
                "current_node": "prepare_human_confirmation",
                "graph_name": "fulfillment_check",
                "graph_version": "v1",
                "evidence_snapshot": [{"documentId": 7}],
                "analysis_workflow": [],
            },
        },
        {"step": 9, "source": "loop"},
        {},
    )

    assert any("INSERT INTO agent_graph_checkpoint" in sql for sql in executed)


def test_graph_adapter_keeps_runtime_metadata_in_state_and_result(monkeypatch):
    import app.agent_runtime.runtime as runtime

    monkeypatch.setattr(
        runtime,
        "_runtime_model_metadata",
        lambda _task_type: ("test-llm", "test-contract-prompt-v1"),
    )
    graph = _CompletedGraph()
    run_store = _RecordingRunStore()
    adapter = GraphAdapter(
        graph,
        graph_name="contract_extraction",
        graph_version="v1",
        run_store=run_store,
    )
    context = AgentTaskContext(
        run_id=73,
        project_id=41,
        task_type="CONTRACT_ELEMENT_EXTRACTION",
        question="extract contract facts",
        subject_type="CONTRACT_CASE",
        subject_id=41,
    )

    result = asyncio.run(adapter.run(context))

    assert result.status == "COMPLETED"
    assert graph.initial_state["model"] == "test-llm"
    assert graph.initial_state["prompt_version"] == "test-contract-prompt-v1"
    assert run_store.runtime_metadata == [(
        73,
        {
            "runtime_engine": "langgraph",
            "graph_name": "contract_extraction",
            "graph_version": "v1",
            "model": "test-llm",
            "prompt_version": "test-contract-prompt-v1",
            "retrieval_version": "contract-hybrid-retrieval-v2",
            "rerank_version": "reranker-v1",
        },
    )]
    assert result.graph_info == {
        "runtimeEngine": "langgraph",
        "graphName": "contract_extraction",
        "graphVersion": "v1",
        "model": "test-llm",
        "promptVersion": "test-contract-prompt-v1",
        "retrievalVersion": "contract-hybrid-retrieval-v2",
        "rerankVersion": "reranker-v1",
        "scorerVersion": "",
        "stateRevision": 0,
    }


def test_fulfillment_graph_resume_preserves_human_result(monkeypatch):
    """The real HITL graph must carry manual_result through checkpoint resume.

    The fulfillment graph is compiled from its TaskSpec (Phase 7), so node
    functions are captured by identity at import time. The test therefore
    stubs the DB / store / LLM boundaries the real nodes call — the full
    node chain (context → decompose → retrieve → rules → judge → validate →
    audit → human gate → apply → persist) runs for real.
    """
    import app.agent_runtime.graph.fulfillment_check as fulfillment_graph
    import app.agent_runtime.graph.nodes.context as context_nodes
    import app.agent_runtime.persistence as persistence
    import app.agent_runtime.contract_store as contract_store_module
    from app.services.llm_service import LLMService

    class _FakeCursor:
        def __init__(self):
            self.last_sql = ""

        def execute(self, sql, params=None):
            self.last_sql = sql

        def fetchone(self):
            return {
                "id": 9, "clauseId": 1, "nodeType": "ACCEPTANCE",
                "label": "Acceptance", "businessMeaning": "完成验收",
                "responsibleParty": "COUNTERPARTY",
                "nodeDate": "2026-03-01", "conditionText": None,
                "citationJson": "{}", "clauseNumber": "5",
                "clauseContent": "乙方应于2026年3月1日前完成验收并取得验收单。",
            }

        def fetchall(self):
            return []  # no previous fulfillment reports → rerun scope ALL

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    class _FakeConn:
        def __init__(self):
            self._cursor = _FakeCursor()

        def cursor(self):
            return self._cursor

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    def fake_snapshot(case_id, requested_document_id=None, include_content_text=False):
        return {
            "case": {"id": 1, "ourSide": "A"},
            "extractionSnapshot": {},
            "documents": [],
            "currentDocument": {},
            "documentQuality": {},
            "snapshot_hash": "test-hash",
            "clauseCount": 0,
        }

    class _FakeStore:
        async def verify_evidence(self, case_id, timeline_node_id=None):
            return {
                "node": {
                    "id": 9, "label": "Acceptance", "nodeType": "ACCEPTANCE",
                    "businessMeaning": "完成验收", "conditionText": "",
                    "clauseContent": "乙方应于2026年3月1日前完成验收并取得验收单。",
                },
                "evidenceDocuments": [],
                "missingEvidence": [],
            }

        async def search_contract_clause(self, case_id, payload):
            return []

    def fake_llm_fulfillment(self, case, verification, citations, task_input, run_id=0):
        return {
            "reportType": "FULFILLMENT_REPORT",
            "conclusion": "INSUFFICIENT_EVIDENCE",
            "riskLevel": "HIGH",
            "confidenceLevel": "LOW",
            "requirements": [],
            "missingEvidence": [],
            "suggestedActions": [],
        }

    monkeypatch.setattr(
        context_nodes, "load_contract_evidence_snapshot", fake_snapshot
    )
    monkeypatch.setattr(persistence, "_conn", lambda: _FakeConn())
    monkeypatch.setattr(contract_store_module, "ContractStore", _FakeStore)
    # LLMService() raises without an API key in this env — stub construction
    # so the advisory suggestion layer (task 5) runs instead of falling back.
    monkeypatch.setattr(LLMService, "__init__", lambda self: None)
    monkeypatch.setattr(LLMService, "contract_fulfillment_check", fake_llm_fulfillment)
    monkeypatch.setattr(persistence.MySqlReportStore, "_save_sync", lambda *a, **kw: 1)

    graph = fulfillment_graph.build_fulfillment_check_graph(checkpointer=MemorySaver())
    adapter = GraphAdapter(graph, graph_name="fulfillment_check", graph_version="v1")

    async def exercise() -> list[tuple[str, dict]]:
        results = []
        for offset, (manual_result, action, expected_conclusion) in enumerate([
            ("SATISFIED", ResumeAction.CONFIRM, "BASICALLY_SATISFIED"),
            ("NOT_SATISFIED", ResumeAction.CONFIRM, "HAS_ISSUES"),
            ("PENDING", ResumeAction.KEEP_PENDING, "NEEDS_REVIEW"),
        ]):
            run_id = 500 + offset
            context = AgentTaskContext(
                run_id=run_id,
                project_id=1,
                task_type="FULFILLMENT_CHECK",
                question="",
                subject_type="CONTRACT_CASE",
                subject_id=1,
                project={"ourSide": "A"},
                task_input={"timelineNodeId": 9},
            )
            paused = await adapter.run(context)
            assert paused.status == "WAITING_HUMAN"
            # GraphInterrupt path: the adapter falls back to the generic wait
            # state type; the full HITL payload lives in the checkpoint.
            wait_state = paused.graph_info.get("waitState") or {}
            assert wait_state.get("type") in ("WAITING_HUMAN", "WAITING_HUMAN_CONFIRMATION")

            resumed = await adapter.resume(
                run_id,
                ResumeCommand(
                    action=action,
                    manual_result=manual_result,
                    note="operator note",
                    operator_id="operator-1",
                ),
            )
            assert resumed.status == "COMPLETED"
            assert resumed.artifact["content"]["manualResult"] == manual_result
            assert resumed.artifact["conclusion"] == expected_conclusion
            # Task 6: the final conclusion comes exclusively from the human
            # result — the persisted content carries no AI-written final.
            assert resumed.artifact["content"]["manualConfirmationRequired"] is False
            results.append((manual_result, resumed.artifact))
        return results

    asyncio.run(exercise())


class _SlowGraph(_CompletedGraph):
    """Completes only after a short real wait, so heartbeat ticks can fire."""

    async def ainvoke(self, state, _config):
        self.initial_state = dict(state)
        await asyncio.sleep(0.03)
        return {**state, "artifact": {"reportType": "CONTRACT_REVIEW"}}


class _HeartbeatRunStore(_RecordingRunStore):
    def __init__(self):
        super().__init__()
        self.heartbeats: list[int] = []
        self.status = "ANALYZING"

    async def heartbeat(self, run_id):
        self.heartbeats.append(run_id)

    async def get_run(self, run_id):
        return {"status": self.status, "id": run_id}


def test_graph_adapter_heartbeats_run_and_stops_when_terminal(monkeypatch):
    """Graph runs must heartbeat (the recovery sweeper flags stale active runs)
    and the loop must self-terminate once the run row leaves active statuses."""
    import app.agent_runtime.runtime as runtime

    monkeypatch.setattr(runtime, "GRAPH_HEARTBEAT_INTERVAL", 0.01)

    async def exercise():
        store = _HeartbeatRunStore()
        adapter = GraphAdapter(
            _SlowGraph(),
            graph_name="contract_review",
            graph_version="v2",
            run_store=store,
        )
        context = AgentTaskContext(
            run_id=901,
            project_id=1,
            task_type="CONTRACT_REVIEW",
            question="",
            subject_type="CONTRACT_CASE",
            subject_id=1,
            project={},
        )
        await adapter.run(context)
        # The graph took 0.03s with 0.01s ticks — at least one beat while active.
        assert store.heartbeats, "heartbeat loop should beat while the run is active"

        store.status = "COMPLETED"
        await asyncio.sleep(0.05)  # give the loop a tick to observe and exit
        snapshot = list(store.heartbeats)
        await asyncio.sleep(0.05)
        assert store.heartbeats == snapshot, "heartbeat loop should exit on terminal status"

    asyncio.run(exercise())


def test_graph_adapter_without_heartbeat_store_skips_loop(monkeypatch):
    """Adapters without a heartbeat-capable store (tests, legacy wiring) must
    not attempt to start the loop."""
    import app.agent_runtime.runtime as runtime

    monkeypatch.setattr(runtime, "GRAPH_HEARTBEAT_INTERVAL", 0.01)

    async def exercise():
        adapter = GraphAdapter(
            _SlowGraph(),
            graph_name="contract_review",
            graph_version="v2",
            run_store=None,
        )
        context = AgentTaskContext(
            run_id=902,
            project_id=1,
            task_type="CONTRACT_REVIEW",
            question="",
            subject_type="CONTRACT_CASE",
            subject_id=1,
            project={},
        )
        result = await adapter.run(context)
        assert result.status == "COMPLETED"

    asyncio.run(exercise())


class _ConfigCapturingGraph(_CompletedGraph):
    """Records the ainvoke config so tests can assert the checkpoint thread."""

    def __init__(self):
        super().__init__()
        self.config = None

    async def ainvoke(self, state, config):
        self.initial_state = dict(state)
        self.config = dict(config)
        return {**state, "artifact": {"reportType": "CONTRACT_REVIEW"}}


class _ShadowRecordingStore(_RecordingRunStore):
    def __init__(self):
        super().__init__()
        self.heartbeats: list[int] = []

    async def heartbeat(self, run_id):
        self.heartbeats.append(run_id)


def test_graph_adapter_shadow_mode_skips_run_writes_and_uses_shadow_thread(monkeypatch):
    """Shadow runs (PRD §26.2) must not write run metadata or heartbeats and
    must checkpoint under a shadow- thread so the primary run's checkpoint
    stream stays clean."""
    import app.agent_runtime.runtime as runtime

    monkeypatch.setattr(runtime, "GRAPH_HEARTBEAT_INTERVAL", 0.01)
    monkeypatch.setattr(
        runtime,
        "_runtime_model_metadata",
        lambda _task_type: ("test-llm", "test-prompt"),
    )

    async def exercise():
        graph = _ConfigCapturingGraph()
        store = _ShadowRecordingStore()
        adapter = GraphAdapter(
            graph,
            graph_name="contract_review",
            graph_version="v2",
            run_store=store,
        )
        context = AgentTaskContext(
            run_id=903,
            project_id=1,
            task_type="CONTRACT_REVIEW",
            question="",
            subject_type="CONTRACT_CASE",
            subject_id=1,
            shadow_mode=True,
        )
        result = await adapter.run(context)
        assert result.status == "COMPLETED"
        assert graph.initial_state["shadow_mode"] is True
        assert graph.config["configurable"]["thread_id"] == "shadow-run-903"
        assert store.runtime_metadata == [], "shadow run must not write start metadata"
        await asyncio.sleep(0.05)  # allow heartbeat ticks if one were started
        assert store.heartbeats == [], "shadow run must not heartbeat"

    asyncio.run(exercise())
