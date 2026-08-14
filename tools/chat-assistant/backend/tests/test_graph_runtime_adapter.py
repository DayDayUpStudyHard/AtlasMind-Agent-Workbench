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
        },
    )]
    assert result.graph_info == {
        "runtimeEngine": "langgraph",
        "graphName": "contract_extraction",
        "graphVersion": "v1",
        "model": "test-llm",
        "promptVersion": "test-contract-prompt-v1",
        "stateRevision": 0,
    }


def test_fulfillment_graph_resume_preserves_human_result(monkeypatch):
    """The real HITL graph must carry manual_result through checkpoint resume."""
    import app.agent_runtime.graph.fulfillment_check as fulfillment_graph

    def load_context(state):
        return {"state_revision": state.get("state_revision", 0) + 1}

    def freeze_snapshot(state):
        return {"state_revision": state.get("state_revision", 0) + 1}

    def decompose(state):
        return {
            "state_revision": state.get("state_revision", 0) + 1,
            "fulfillment_requirements": [{
                "requirement": "Submit acceptance record",
                "required": True,
                "sourceCitationIds": ["CONTRACT_CLAUSE:1"],
                "acceptanceCriteria": "Signed acceptance record",
            }],
        }

    def retrieve(state):
        return {
            "state_revision": state.get("state_revision", 0) + 1,
            "fulfillment_context": {
                "timelineNode": {"id": 9, "label": "Acceptance"},
                "evidenceDocuments": [],
                "contractEvidence": [],
            },
        }

    def judge(state):
        return {
            "state_revision": state.get("state_revision", 0) + 1,
            "artifacts": {
                "judgements": [{
                    "requirement": "Submit acceptance record",
                    "required": True,
                    "judgement": "EVIDENCE_INSUFFICIENT",
                    "proofStatus": "INSUFFICIENT",
                    "gap": "Signed acceptance record",
                    "reason": "No evidence uploaded",
                }],
                "fulfillmentAssessment": {
                    "requirementCount": 1,
                    "evidenceCount": 0,
                    "supportedCount": 0,
                    "partialCount": 0,
                    "insufficientCount": 1,
                },
            },
        }

    def validate(state):
        return {"state_revision": state.get("state_revision", 0) + 1}

    def persist(state):
        return {"state_revision": state.get("state_revision", 0) + 1}

    monkeypatch.setattr(fulfillment_graph, "load_run_context", load_context)
    monkeypatch.setattr(fulfillment_graph, "freeze_case_snapshot", freeze_snapshot)
    monkeypatch.setattr(fulfillment_graph, "decompose_requirements", decompose)
    monkeypatch.setattr(fulfillment_graph, "retrieve_fulfillment_evidence", retrieve)
    monkeypatch.setattr(fulfillment_graph, "judge_each_requirement", judge)
    monkeypatch.setattr(fulfillment_graph, "validate_fulfillment_judgement", validate)
    monkeypatch.setattr(fulfillment_graph, "persist_report", persist)

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
