"""TaskSpec + common graph builder contract tests (PRD Phase 4 / §14-4).

Evidence that §14 item 4 is complete (acceptance review P0-2):

1. Topology freeze — the spec-built risk v1 graph equals a literal
   transcription of the pre-migration inline wiring (same nodes, same
   edges, same conditional gates).
2. Node identity — CONTRACT_REVIEW_SPEC references the real v1 node
   functions by identity, so migrating to the common builder moves the
   wiring and nothing else.
3. Spec validation — build_task_graph fails fast on broken specs.
4. Golden equivalence — a deterministic stub pipeline carrying the real
   v1 routing functions, run end-to-end through GraphAdapter +
   FakePersistence, reproduces the frozen pre-migration artifact bytes
   (tests/golden/contract_review_v1_golden_artifact.json). The golden
   fixture was captured with the pre-migration reference wiring below.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any, Callable

import pytest
from langgraph.graph import END, START, StateGraph

from app.agent_runtime.api_models import AgentTaskContext
from app.agent_runtime.graph.contract_review import CONTRACT_REVIEW_SPEC, _route_after_reflection
from app.agent_runtime.graph.nodes.artifact import _route_after_schema
from app.agent_runtime.graph.state import BaseGraphState
from app.agent_runtime.harness.fakes import FakePersistence
from app.agent_runtime.harness.graph_builder import build_task_graph
from app.agent_runtime.harness.models import TaskSpec
from app.agent_runtime.runtime import GraphAdapter

GOLDEN_PATH = Path(__file__).parent / "golden" / "contract_review_v1_golden_artifact.json"

# ── Deterministic v1-shaped stub pipeline ─────────────────────────────────────

_GOLDEN_ARTIFACT: dict[str, Any] = {
    "reportType": "CONTRACT_REVIEW_REPORT",
    "riskReport": {
        "summary": "共识别 2 项风险：付款节点无验收前置、保密义务不对称",
        "riskLevel": "MEDIUM",
        "items": [
            {
                "id": "risk-1",
                "domain": "PAYMENT",
                "title": "付款节点无验收前置",
                "level": "HIGH",
                "findingKeys": ["finding-1"],
            },
            {
                "id": "risk-2",
                "domain": "CONFIDENTIALITY",
                "title": "保密义务不对称",
                "level": "MEDIUM",
                "findingKeys": ["finding-2"],
            },
        ],
    },
}


def _stage(name: str, **updates: Any) -> Callable:
    """A deterministic node that ticks state_revision and stamps its stage."""

    def node(state: dict[str, Any]) -> dict[str, Any]:
        out: dict[str, Any] = {
            "current_node": name,
            "state_revision": int(state.get("state_revision") or 0) + 1,
        }
        out.update(updates)
        return out

    return node


def _stub_nodes() -> dict[str, Callable]:
    """One deterministic stub per risk v1 stage; each writes the state field
    its real counterpart owns. Nodes off the golden path (targeted_retrieval,
    compose_limited_report, repair_artifact) exist so the wiring compiles but
    are never visited when coverage is CONFIRMED and the schema is valid."""
    return {
        "load_run_context": _stage(
            "load_run_context",
            run_id=7001, task_type="CONTRACT_REVIEW",
            subject_type="CONTRACT_CASE", subject_id=1,
        ),
        "freeze_case_snapshot": _stage(
            "freeze_case_snapshot",
            case_snapshot={"caseId": 1, "title": "Golden 采购合同"},
            evidence_snapshot={"snapshotHash": "sha256:golden-0000", "version": 1},
        ),
        "inventory_clauses": _stage(
            "inventory_clauses",
            analysis_workflow={"clauseCount": 2},
        ),
        "create_domain_tasks": _stage(
            "create_domain_tasks",
            domain_tasks=[
                {"domain": "PAYMENT", "label": "付款节点"},
                {"domain": "CONFIDENTIALITY", "label": "保密义务"},
            ],
        ),
        "retrieve_domain_evidence": _stage(
            "retrieve_domain_evidence",
            domain_results={"PAYMENT": [], "CONFIDENTIALITY": []},
            observations=[{"callId": "obs-1", "toolName": "retrieve_domain_evidence"}],
        ),
        "run_deterministic_rules": _stage(
            "run_deterministic_rules",
            rule_findings=[{"key": "finding-1", "source": "DETERMINISTIC_RULE"}],
        ),
        "draft_domain_findings": _stage(
            "draft_domain_findings",
            draft_findings=[
                {"key": "finding-1", "title": "付款节点无验收前置"},
                {"key": "finding-2", "title": "保密义务不对称"},
            ],
        ),
        "validate_claims": _stage(
            "validate_claims",
            validated_findings=[
                {"key": "finding-1", "verdict": "PASS"},
                {"key": "finding-2", "verdict": "PASS"},
            ],
            evidence_validation={"passed": 2, "rejected": 0},
        ),
        "coverage_reflection": _stage(
            "coverage_reflection",
            coverage={"status": "CONFIRMED", "domains": {"PAYMENT": "COVERED", "CONFIDENTIALITY": "COVERED"}},
        ),
        "targeted_retrieval": _stage(
            "targeted_retrieval",
            retry_state={"reflection_rounds": 1},
        ),
        "compose_report": _stage("compose_report", artifact=_GOLDEN_ARTIFACT),
        "compose_limited_report": _stage(
            "compose_limited_report",
            artifact={"reportType": "LIMITED_REPORT"},
        ),
        "validate_schema": _stage(
            "validate_schema",
            schema_validation={"valid": True, "repair_count": 0},
        ),
        "repair_artifact": _stage(
            "repair_artifact",
            schema_validation={"valid": False, "repair_count": 1},
        ),
        "prepare_human_review": _stage(
            "prepare_human_review",
            human_review={"boundary": "合同风险结论需要负责人或法务人工复核"},
        ),
        "persist_report": _stage(
            "persist_report",
            artifacts={"report": _GOLDEN_ARTIFACT},
            citations=[{"sourceType": "CONTRACT_CLAUSE", "sourceId": "1.1"}],
        ),
    }


def _stub_spec() -> TaskSpec:
    """CONTRACT_REVIEW_SPEC with deterministic stubs in place of the real
    node functions — same stages / edges / routing declaration."""
    return TaskSpec(
        task_type=CONTRACT_REVIEW_SPEC.task_type,
        graph_name=CONTRACT_REVIEW_SPEC.graph_name,
        graph_version=CONTRACT_REVIEW_SPEC.graph_version,
        prompt_version=CONTRACT_REVIEW_SPEC.prompt_version,
        stages=CONTRACT_REVIEW_SPEC.stages,
        nodes=_stub_nodes(),
        edges=CONTRACT_REVIEW_SPEC.edges,
        conditional_routes=CONTRACT_REVIEW_SPEC.conditional_routes,
        human_gate=CONTRACT_REVIEW_SPEC.human_gate,
    )


# ── Frozen pre-migration reference wiring ────────────────────────────────────


def _frozen_reference_graph():
    """Literal transcription of the pre-migration inline v1 builder
    (2026-08-14), kept independent from TaskSpec / build_task_graph so a
    regression in either gets caught by the equivalence assertions."""
    builder = StateGraph(BaseGraphState)
    for name, node in _stub_nodes().items():
        builder.add_node(name, node)

    builder.add_edge(START, "load_run_context")
    builder.add_edge("load_run_context", "freeze_case_snapshot")
    builder.add_edge("freeze_case_snapshot", "inventory_clauses")
    builder.add_edge("inventory_clauses", "create_domain_tasks")
    builder.add_edge("create_domain_tasks", "retrieve_domain_evidence")
    builder.add_edge("retrieve_domain_evidence", "run_deterministic_rules")
    builder.add_edge("run_deterministic_rules", "draft_domain_findings")
    builder.add_edge("draft_domain_findings", "validate_claims")
    builder.add_edge("validate_claims", "coverage_reflection")

    builder.add_conditional_edges(
        "coverage_reflection",
        _route_after_reflection,
        {
            "compose_report": "compose_report",
            "compose_limited_report": "compose_limited_report",
            "targeted_retrieval": "targeted_retrieval",
        },
    )
    builder.add_edge("targeted_retrieval", "draft_domain_findings")

    builder.add_edge("compose_report", "validate_schema")
    builder.add_edge("compose_limited_report", "validate_schema")

    builder.add_conditional_edges(
        "validate_schema",
        _route_after_schema,
        {
            "persist_report": "persist_report",
            "prepare_human_review": "prepare_human_review",
            "repair_artifact": "repair_artifact",
            "compose_limited_report": "compose_limited_report",
        },
    )
    builder.add_edge("repair_artifact", "validate_schema")
    builder.add_edge("prepare_human_review", "persist_report")
    builder.add_edge("persist_report", END)

    return builder.compile()


def _topology(graph) -> tuple[set[str], set[tuple[str, str, bool]]]:
    g = graph.get_graph()
    node_names = set(g.nodes)
    edge_keys = {(e.source, e.target, bool(e.conditional)) for e in g.edges}
    return node_names, edge_keys


# ── 1. Topology freeze ───────────────────────────────────────────────────────


def test_spec_built_graph_matches_frozen_pre_migration_topology():
    spec_nodes, spec_edges = _topology(build_task_graph(_stub_spec()))
    ref_nodes, ref_edges = _topology(_frozen_reference_graph())

    assert spec_nodes == ref_nodes
    assert spec_edges == ref_edges
    # The pre-migration graph had 16 business nodes + START/END and
    # 13 linear edges + 7 conditional targets + 2 terminal edges.
    assert len([n for n in spec_nodes if n not in (START, END)]) == 16
    assert len(spec_edges) == 22


# ── 2. Node identity: the spec wires the real v1 functions ───────────────────


def test_contract_review_spec_references_real_node_functions():
    import app.agent_runtime.graph.nodes.context as context
    import app.agent_runtime.graph.nodes.inventory as inventory
    import app.agent_runtime.graph.nodes.domain_tasks as domain_tasks
    import app.agent_runtime.graph.nodes.retrieval as retrieval
    import app.agent_runtime.graph.nodes.validation as validation
    import app.agent_runtime.graph.nodes.reflection as reflection
    import app.agent_runtime.graph.nodes.artifact as artifact

    expected = {
        "load_run_context": context.load_run_context,
        "freeze_case_snapshot": context.freeze_case_snapshot,
        "inventory_clauses": inventory.inventory_clauses,
        "create_domain_tasks": domain_tasks.create_domain_tasks,
        "retrieve_domain_evidence": retrieval.retrieve_domain_evidence,
        "run_deterministic_rules": retrieval.run_deterministic_rules,
        "draft_domain_findings": retrieval.draft_domain_findings,
        "validate_claims": validation.validate_claims,
        "coverage_reflection": reflection.coverage_reflection,
        "targeted_retrieval": reflection.targeted_retrieval,
        "compose_report": artifact.compose_report,
        "compose_limited_report": artifact.compose_limited_report,
        "validate_schema": artifact.validate_schema,
        "repair_artifact": artifact.repair_artifact,
        "prepare_human_review": artifact.prepare_human_review,
        "persist_report": artifact.persist_report,
    }

    spec = CONTRACT_REVIEW_SPEC
    assert spec.task_type == "CONTRACT_REVIEW"
    assert spec.graph_name == "contract_review"
    assert spec.graph_version == "v1"
    assert spec.human_gate is None  # risk v1 has no interrupt stage
    assert len(spec.stages) == len(expected)
    for name, func in expected.items():
        assert spec.nodes[name] is func, f"{name} is not the real v1 node"
    assert spec.conditional_routes["coverage_reflection"][0] is _route_after_reflection
    assert spec.conditional_routes["validate_schema"][0] is _route_after_schema


def test_contract_review_builder_registers_the_spec_built_graph():
    from app.agent_runtime.graph.contract_review import build_contract_review_graph

    graph = build_contract_review_graph()
    nodes, edges = _topology(graph)
    assert len([n for n in nodes if n not in (START, END)]) == 16
    assert len(edges) == 22


# ── 3. Spec validation ───────────────────────────────────────────────────────


def _tiny_spec(**overrides: Any) -> TaskSpec:
    base = dict(
        task_type="TINY", graph_name="tiny", graph_version="v1", prompt_version="t",
        stages=("a", "b"),
        nodes={"a": _stage("a"), "b": _stage("b")},
        edges=(("a", "b"),),
        conditional_routes={},
    )
    base.update(overrides)
    return TaskSpec(**base)


def test_builder_rejects_route_to_unknown_node():
    spec = _tiny_spec(
        conditional_routes={"a": (lambda s: "ghost", {"ghost": "ghost"})},
        edges=(),
    )
    with pytest.raises(ValueError, match="route a -> unknown node ghost"):
        build_task_graph(spec)


def test_builder_rejects_edge_to_unknown_node():
    spec = _tiny_spec(edges=(("a", "ghost"),))
    with pytest.raises(ValueError, match="edge a->ghost references unknown node"):
        build_task_graph(spec)


def test_builder_rejects_stage_without_node():
    spec = _tiny_spec(nodes={"a": _stage("a")})
    with pytest.raises(ValueError, match="stages without nodes"):
        build_task_graph(spec)


def test_builder_rejects_duplicate_stages():
    spec = _tiny_spec(stages=("a", "a"), nodes={"a": _stage("a")}, edges=())
    with pytest.raises(ValueError, match="duplicate stages"):
        build_task_graph(spec)


def test_builder_rejects_dangling_stage():
    spec = _tiny_spec(stages=("a", "b", "c"), nodes={"a": _stage("a"), "b": _stage("b"), "c": _stage("c")},
                      edges=(("a", "b"),))
    with pytest.raises(ValueError, match="stage c has no incoming edge"):
        build_task_graph(spec)


def test_builder_rejects_linear_edge_out_of_conditional_stage():
    spec = _tiny_spec(
        conditional_routes={"a": (lambda s: "b", {"b": "b"})},
        edges=(("a", "b"),),
    )
    with pytest.raises(ValueError, match="conditional stage a must not declare linear edges"):
        build_task_graph(spec)


# ── 4. Golden end-to-end equivalence ─────────────────────────────────────────


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


def _run_artifact(graph) -> dict[str, Any]:
    store = FakePersistence()
    adapter = GraphAdapter(
        graph, graph_name="contract_review", graph_version="v1", run_store=store
    )
    result = asyncio.run(adapter.run(_context(7001)))
    assert result.status == "COMPLETED", result
    return result.artifact


def _dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def test_spec_built_graph_reproduces_frozen_golden_artifact():
    assert GOLDEN_PATH.exists(), "golden fixture missing — regenerate from the reference wiring"
    golden = GOLDEN_PATH.read_text(encoding="utf-8")

    spec_artifact = _run_artifact(build_task_graph(_stub_spec()))
    ref_artifact = _run_artifact(_frozen_reference_graph())

    assert _dump(spec_artifact) == _dump(ref_artifact)
    assert _dump(spec_artifact) == golden
