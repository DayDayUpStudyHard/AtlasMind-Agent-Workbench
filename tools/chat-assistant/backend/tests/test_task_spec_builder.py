"""TaskSpec + common graph builder contract tests (PRD Phase 4 / §14-4).

Evidence that §14 item 4 is complete (second acceptance review findings):

1. Role contract — CONTRACT_REVIEW_SPEC declares the PRD §6.1 role hooks
   (context / planner / retriever / analyzer / validator / coverage_auditor /
   composer / persistence / human_gate) as real fields; ``stages`` /
   ``nodes`` are derived from them, and every stage references the real v1
   node function by identity.
2. Topology freeze — the spec-built risk v1 graph equals a literal
   transcription of the pre-migration inline wiring (same nodes, same
   edges, same conditional gates).
3. Spec validation — build_task_graph fails fast on broken specs: role
   partition violations, human_gate mistakes, context-chain re-wiring, and
   true START→END reachability (a disconnected b↔c cycle must be rejected,
   not silently dropped).
4. Real golden — the real v1 node chain (stubs only for the five DB / LLM /
   orchestrator I/O nodes) reproduces the frozen artifact and per-node
   input/output samples captured independently by
   scripts/capture_contract_review_v1_golden.py. No constant is shared
   between the pipeline and the fixture.
"""

from __future__ import annotations

import asyncio
import copy
import json
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable, Iterator
from unittest import mock

import pytest
from langgraph.graph import END, START, StateGraph

from app.agent_runtime.api_models import AgentTaskContext
from app.agent_runtime.contract_store import ContractStore
from app.agent_runtime.graph.contract_review import (
    CONTRACT_REVIEW_SPEC,
    _route_after_reflection,
)
from app.agent_runtime.graph.nodes import domain_tasks as domain_tasks_mod
from app.agent_runtime.graph.nodes.artifact import (
    _route_after_schema,
    compose_limited_report,
    repair_artifact,
)
from app.agent_runtime.graph.state import BaseGraphState
from app.agent_runtime.harness.fakes import FakePersistence, fake_clause, fake_snapshot
from app.agent_runtime.harness.graph_builder import build_task_graph
from app.agent_runtime.harness.models import HumanGate, Role, TaskSpec
from app.agent_runtime.persistence import MySqlReportStore
from app.agent_runtime.runtime import GraphAdapter
from app.services.llm_service import LLMService

GOLDEN_PATH = Path(__file__).parent / "golden" / "contract_review_v1_golden_artifact.json"

# ── Deterministic v1-shaped stub pipeline (topology tests only) ────────────────


def _stage(name: str) -> Callable:
    """A deterministic node that ticks state_revision and stamps its stage."""

    def node(state: dict[str, Any]) -> dict[str, Any]:
        return {
            "current_node": name,
            "state_revision": int(state.get("state_revision") or 0) + 1,
        }

    return node


def _stub_nodes() -> dict[str, Callable]:
    """One deterministic stub per risk v1 stage. The stub graph is never
    executed — it only exists to freeze the wiring topology."""
    return {
        name: _stage(name)
        for name in (
            "load_run_context", "freeze_case_snapshot", "inventory_clauses",
            "create_domain_tasks", "retrieve_domain_evidence",
            "run_deterministic_rules", "draft_domain_findings",
            "validate_claims", "coverage_reflection", "targeted_retrieval",
            "compose_report", "compose_limited_report", "validate_schema",
            "repair_artifact", "prepare_human_review", "persist_report",
        )
    }


def _role_stages(role: Role, nodes: dict[str, Callable]) -> tuple[tuple[str, Callable], ...]:
    """Re-declare one role with ``nodes`` in place of the real functions."""
    return tuple((name, nodes[name]) for name, _fn in role.stages)


def _stub_spec() -> TaskSpec:
    """CONTRACT_REVIEW_SPEC with deterministic stubs in place of the real
    node functions — same roles / edges / routing declaration."""
    nodes = _stub_nodes()
    return TaskSpec(
        task_type=CONTRACT_REVIEW_SPEC.task_type,
        graph_name=CONTRACT_REVIEW_SPEC.graph_name,
        graph_version=CONTRACT_REVIEW_SPEC.graph_version,
        prompt_version=CONTRACT_REVIEW_SPEC.prompt_version,
        context=Role(_role_stages(CONTRACT_REVIEW_SPEC.context, nodes)),
        planner=Role(_role_stages(CONTRACT_REVIEW_SPEC.planner, nodes)),
        retriever=Role(_role_stages(CONTRACT_REVIEW_SPEC.retriever, nodes)),
        analyzer=Role(_role_stages(CONTRACT_REVIEW_SPEC.analyzer, nodes)),
        validator=Role(_role_stages(CONTRACT_REVIEW_SPEC.validator, nodes)),
        coverage_auditor=Role(_role_stages(CONTRACT_REVIEW_SPEC.coverage_auditor, nodes)),
        composer=Role(_role_stages(CONTRACT_REVIEW_SPEC.composer, nodes)),
        persistence=Role(_role_stages(CONTRACT_REVIEW_SPEC.persistence, nodes)),
        human_gate=CONTRACT_REVIEW_SPEC.human_gate,
        edges=CONTRACT_REVIEW_SPEC.edges,
        conditional_routes=CONTRACT_REVIEW_SPEC.conditional_routes,
    )


# ── Frozen pre-migration reference wiring ────────────────────────────────────


def _frozen_reference_graph(nodes: dict[str, Callable] | None = None) -> Any:
    """Literal transcription of the pre-migration inline v1 builder
    (2026-08-14), kept independent from TaskSpec / build_task_graph so a
    regression in either gets caught by the equivalence assertions.

    ``nodes`` may carry the real v1 functions (golden behavioral
    equivalence) or deterministic stubs (topology freeze).
    """
    if nodes is None:
        nodes = _stub_nodes()
    builder = StateGraph(BaseGraphState)
    for name, node in nodes.items():
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


# ── 1. §6.1 role contract ────────────────────────────────────────────────────


def test_contract_review_spec_declares_prd_61_role_contract():
    """The eight §6.1 role hooks are real fields; stages derive from them
    in the pre-migration v1 order (flattening the field order)."""
    spec = CONTRACT_REVIEW_SPEC
    assert [name for name, _fn in spec.context.stages] == [
        "load_run_context", "freeze_case_snapshot",
    ]
    assert [name for name, _fn in spec.planner.stages] == [
        "inventory_clauses", "create_domain_tasks",
    ]
    assert [name for name, _fn in spec.retriever.stages] == ["retrieve_domain_evidence"]
    assert [name for name, _fn in spec.analyzer.stages] == [
        "run_deterministic_rules", "draft_domain_findings",
    ]
    assert [name for name, _fn in spec.validator.stages] == ["validate_claims"]
    assert [name for name, _fn in spec.coverage_auditor.stages] == [
        "coverage_reflection", "targeted_retrieval",
    ]
    assert [name for name, _fn in spec.composer.stages] == [
        "compose_report", "compose_limited_report", "validate_schema", "repair_artifact",
    ]
    assert [name for name, _fn in spec.persistence.stages] == [
        "prepare_human_review", "persist_report",
    ]
    assert spec.human_gate is None  # risk v1 has no interrupt stage
    assert spec.stages == (
        "load_run_context", "freeze_case_snapshot", "inventory_clauses",
        "create_domain_tasks", "retrieve_domain_evidence",
        "run_deterministic_rules", "draft_domain_findings",
        "validate_claims", "coverage_reflection", "targeted_retrieval",
        "compose_report", "compose_limited_report", "validate_schema",
        "repair_artifact", "prepare_human_review", "persist_report",
    )


def test_contract_review_spec_references_real_node_functions():
    """Every stage is wired to the real v1 node by identity — migrating to
    the common builder moves the wiring and nothing else."""
    import app.agent_runtime.graph.nodes.artifact as artifact
    import app.agent_runtime.graph.nodes.context as context
    import app.agent_runtime.graph.nodes.domain_tasks as domain_tasks
    import app.agent_runtime.graph.nodes.inventory as inventory
    import app.agent_runtime.graph.nodes.reflection as reflection
    import app.agent_runtime.graph.nodes.retrieval as retrieval
    import app.agent_runtime.graph.nodes.validation as validation

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
    assert len(spec.stages) == len(expected)
    assert set(spec.nodes) == set(expected)
    for name, func in expected.items():
        assert spec.nodes[name] is func, f"{name} is not the real v1 node"
    assert spec.conditional_routes["coverage_reflection"][0] is _route_after_reflection
    assert spec.conditional_routes["validate_schema"][0] is _route_after_schema


# ── 2. Topology freeze ───────────────────────────────────────────────────────


def test_spec_built_graph_matches_frozen_pre_migration_topology():
    spec_nodes, spec_edges = _topology(build_task_graph(_stub_spec()))
    ref_nodes, ref_edges = _topology(_frozen_reference_graph())

    assert spec_nodes == ref_nodes
    assert spec_edges == ref_edges
    # The pre-migration graph had 16 business nodes + START/END and
    # 22 edges (11 explicit + 3 context-chain + 7 conditional targets + END).
    assert len([n for n in spec_nodes if n not in (START, END)]) == 16
    assert len(spec_edges) == 22


def test_contract_review_builder_registers_the_spec_built_graph():
    from app.agent_runtime.graph.contract_review import build_contract_review_graph

    nodes, edges = _topology(build_contract_review_graph())
    assert len([n for n in nodes if n not in (START, END)]) == 16
    assert len(edges) == 22


# ── 3. Spec validation ───────────────────────────────────────────────────────


def _tiny_spec(**overrides: Any) -> TaskSpec:
    """Tiny valid spec: context ctx, planner a, analyzer b, composer c.

    Implicit wiring (ctx→a) plus explicit edges a→b, b→c; c→END."""
    base: dict[str, Any] = dict(
        task_type="TINY",
        graph_name="tiny",
        graph_version="v1",
        prompt_version="t",
        context=Role((("ctx", _stage("ctx")),)),
        planner=Role((("a", _stage("a")),)),
        retriever=Role(),
        analyzer=Role((("b", _stage("b")),)),
        validator=Role(),
        coverage_auditor=Role(),
        composer=Role((("c", _stage("c")),)),
        persistence=Role(),
        edges=(("a", "b"), ("b", "c")),
        conditional_routes={},
    )
    base.update(overrides)
    return TaskSpec(**base)


def test_builder_rejects_stage_declared_by_two_roles():
    spec = _tiny_spec(
        planner=Role((("a", _stage("a")), ("shared", _stage("shared")))),
        analyzer=Role((("shared", _stage("shared")), ("b", _stage("b")))),
    )
    with pytest.raises(ValueError, match="stage shared declared by two roles"):
        build_task_graph(spec)


def test_builder_rejects_role_repeating_its_own_stage():
    spec = _tiny_spec(
        analyzer=Role((("b", _stage("b")), ("b", _stage("b")))),
    )
    with pytest.raises(ValueError, match="role analyzer declares stage b more than once"):
        build_task_graph(spec)


def test_builder_rejects_empty_context_role():
    spec = _tiny_spec(context=Role())
    with pytest.raises(ValueError, match="context role must declare at least one stage"):
        build_task_graph(spec)


def test_builder_rejects_human_gate_on_unknown_stage():
    spec = _tiny_spec(human_gate=HumanGate(stage="ghost"))
    with pytest.raises(ValueError, match="human_gate stage ghost is not a declared stage"):
        build_task_graph(spec)


def test_builder_rejects_human_gate_not_being_the_stage_node():
    # The gate declares stage "a", but "a" is still the planner stub — the
    # spec must register the gate as that stage's node itself.
    spec = _tiny_spec(human_gate=HumanGate(stage="a"))
    with pytest.raises(ValueError, match="human_gate must be the node of stage a"):
        build_task_graph(spec)


def test_builder_registers_human_gate_as_its_stage_node():
    gate = HumanGate(stage="gate")
    spec = _tiny_spec(
        planner=Role((("gate", gate),)),
        human_gate=gate,  # the §6.1 hook — role declaration + gate field agree
        edges=(("gate", "b"), ("b", "c")),
    )
    graph = build_task_graph(spec)
    assert "gate" in graph.get_graph().nodes
    # Invoking the graph reaches the gate stage and calls the gate function
    # itself — identity proof that the gate IS the stage node (registered
    # exactly once through the role declaration).
    with pytest.raises(NotImplementedError):
        graph.invoke({})


def test_builder_rejects_edge_from_context_stage():
    spec = _tiny_spec(edges=(("ctx", "a"), ("a", "b"), ("b", "c")))
    with pytest.raises(ValueError, match="context stage ctx is wired by the builder"):
        build_task_graph(spec)


def test_builder_rejects_conditional_route_on_context_stage():
    spec = _tiny_spec(
        conditional_routes={"ctx": (lambda s: "a", {"a": "a"})},
        edges=(("a", "b"), ("b", "c")),
    )
    with pytest.raises(ValueError, match="context stage ctx is wired by the builder"):
        build_task_graph(spec)


def test_builder_rejects_disconnected_cycle_unreachable_from_start():
    """Second-review repro: a b↔c cycle with no path from the start must be
    rejected — compiling it silently drops both nodes."""
    spec = _tiny_spec(edges=(("b", "c"), ("c", "b")))
    with pytest.raises(ValueError, match="stages unreachable from START: \\['b', 'c'\\]"):
        build_task_graph(spec)


def test_builder_rejects_stage_that_can_never_reach_end():
    # a is reachable from START, b is a dead end: no path b → … → c.
    spec = _tiny_spec(edges=(("a", "b"), ("a", "c")))
    with pytest.raises(ValueError, match="stages that can never reach END: \\['b'\\]"):
        build_task_graph(spec)


def test_builder_rejects_dangling_stage():
    spec = _tiny_spec(edges=(("a", "b"),))
    with pytest.raises(ValueError, match="stages unreachable from START: \\['c'\\]"):
        build_task_graph(spec)


def test_builder_rejects_route_to_unknown_node():
    spec = _tiny_spec(
        conditional_routes={"a": (lambda s: "ghost", {"ghost": "ghost"})},
        edges=(("b", "c"),),
    )
    with pytest.raises(ValueError, match="route a -> unknown node ghost"):
        build_task_graph(spec)


def test_builder_rejects_edge_to_unknown_node():
    spec = _tiny_spec(edges=(("a", "b"), ("b", "ghost")))
    with pytest.raises(ValueError, match="edge b->ghost references unknown node"):
        build_task_graph(spec)


def test_builder_rejects_linear_edge_out_of_conditional_stage():
    spec = _tiny_spec(
        conditional_routes={"a": (lambda s: "b", {"b": "b"})},
        edges=(("a", "b"), ("b", "c")),
    )
    with pytest.raises(ValueError, match="conditional stage a must not declare linear edges"):
        build_task_graph(spec)


def test_builder_rejects_conditional_route_on_last_stage():
    spec = _tiny_spec(
        conditional_routes={"c": (lambda s: "a", {"a": "a"})},
        edges=(("a", "b"), ("b", "c")),
    )
    with pytest.raises(ValueError, match="last stage c cannot route conditionally"):
        build_task_graph(spec)


# ── 4. Real golden: real v1 nodes against an independent frozen fixture ──────

_GOLDEN_RUN_ID = 7001
_GOLDEN_CASE_ID = 1
_GOLDEN_HASH = "sha256:golden-0000"

# Real v1 stages exercised on the golden path (everything except the five
# I/O stubs and the off-path branches).
_GOLDEN_REAL_STAGES = (
    "freeze_case_snapshot", "inventory_clauses", "create_domain_tasks",
    "run_deterministic_rules", "validate_claims", "coverage_reflection",
    "compose_report", "validate_schema", "prepare_human_review",
    "persist_report",
)


def _golden_evidence() -> dict[str, list[dict[str, Any]]]:
    """Frozen retrieval evidence: one contract clause per baseline domain.

    ``fake_clause`` builds the canonical hit shape (sourceType / sourceId /
    clauseText), so the real citation_support check in validate_claims can
    verify findings against canonical text like in production."""
    def clause(cid: int, number: str, title: str, content: str, clause_type: str) -> dict[str, Any]:
        return fake_clause(
            cid, number=number, title=title, content=content,
            clause_type=clause_type, document_id=11,
        )

    return {
        "party_authority": [clause(
            101, "1.1", "签约主体与授权",
            "乙方保证其具备签署并履行本合同的合法主体资格，已获得签署本合同所必需的全部内部授权，且签署人员系有权代表乙方签字的人员。",
            "OTHER",
        )],
        "scope_delivery_acceptance": [clause(
            102, "5.1", "交付与验收",
            "乙方应在每个里程碑完成后五个工作日内向甲方提交交付物，甲方应在收到交付物后十个工作日内完成验收并书面确认；甲方逾期未提出书面异议的，视为验收通过。",
            "ACCEPTANCE",
        )],
        "price_payment_tax": [clause(
            103, "3.1", "付款条款",
            "合同总价为人民币伍拾万元整，甲方应于收到乙方开具的等额增值税专用发票后十五个工作日内支付对应款项。",
            "PAYMENT",
        )],
        "liability_remedies": [clause(
            104, "8.2", "违约责任",
            "任何一方违反本合同约定的，应赔偿守约方因此遭受的直接损失，且累计赔偿金额不超过合同总价的百分之二十。",
            "LIABILITY",
        )],
        "term_change_termination": [clause(
            105, "10.1", "终止条款",
            "本合同自双方签字盖章之日起生效，有效期一年；任何一方提前终止的，应提前三十日书面通知对方，并完成已交付工作结算。",
            "TERMINATION",
        )],
        "confidentiality_data_ip": [clause(
            106, "9.3", "保密条款",
            "双方对因履行本合同而知悉的对方商业秘密承担保密义务，保密期限自合同终止之日起持续两年。",
            "CONFIDENTIALITY",
        )],
    }


# One realistic finding per baseline domain. Wording deliberately avoids the
# negative-claim markers (未约定 / 未发现 / 缺少) and advice-as-contract-fact
# markers (合同约定) so validate_claims passes them cleanly — the golden path
# must not depend on validation warnings.
_GOLDEN_FINDINGS: dict[str, dict[str, Any]] = {
    "party_authority": {
        "title": "签约主体授权链路需补充证明文件",
        "explanation": "合同正文载明乙方具备签约资格与授权，但授权书与资质证明未随正文归档，实际签署权限依赖事后补证。",
        "impact": "授权链不完整时，合同效力与签章责任可能被质疑，追责对象难以锁定。",
        "advice": "建议收集乙方法定代表人授权书及资质证明，并在签约时归档核验。",
        "negotiation": "签约前取得授权文件原件或经核验的复印件。",
        "question": "请确认乙方授权书与资质证明是否已归档。",
        "verification": "核对授权文件载明的签署权限范围是否覆盖本合同。",
        "clause_type": "OTHER",
    },
    "scope_delivery_acceptance": {
        "title": "视为验收通过机制需要补充异议处理安排",
        "explanation": "条款约定了验收异议期限，但异议提出后的整改与复核流程留白，逾期视为验收通过后难以主张返工。",
        "impact": "异议处理缺失时，验收结论可能被单方锁定，交付质量问题在付款节点集中爆发。",
        "advice": "建议补充验收异议流程与整改期限，明确逾期验收与付款的联动。",
        "negotiation": "验收异议期与整改次数可协商，异议处理机制不可省略。",
        "question": "请确认验收异议由哪个角色复核，整改后是否重新计期。",
        "verification": "核对验收条款是否包含异议提出、复核与整改后的验收安排。",
        "clause_type": "ACCEPTANCE",
    },
    "price_payment_tax": {
        "title": "付款条件未与验收结果挂钩",
        "explanation": "付款条件仅以发票为触发点，验收结果与付款之间没有联动，交付质量存在争议时甲方难以主张扣款。",
        "impact": "付款与验收脱钩会削弱对交付质量的控制，现金流与质量保障失衡。",
        "advice": "建议将付款节点与可验证的验收或交付结果绑定，并明确逾期付款责任。",
        "negotiation": "付款比例与周期可协商，验收作为付款前提需保留。",
        "question": "请确认付款节点是否已有对应的验收里程碑。",
        "verification": "核对付款条款与验收条款的触发关系是否一致。",
        "clause_type": "PAYMENT",
    },
    "liability_remedies": {
        "title": "责任上限未涵盖间接损失与第三方索赔",
        "explanation": "违约责任条款仅覆盖直接损失，间接损失、第三方索赔及知识产权侵权的处理方式留白，发生复合型违约时追偿范围存在争议。",
        "impact": "复合型违约的追偿范围不明确，责任上限可能被解读为全面豁免。",
        "advice": "建议按违约类型明确损失范围，并补充第三方索赔与知识产权侵权的处理机制。",
        "negotiation": "责任上限与一般违约金可协商，故意、重大过失与侵权例外需保留。",
        "question": "请确认本合同是否涉及第三方索赔、数据损失或知识产权侵权。",
        "verification": "核对违约类型、赔偿范围、责任上限与免责例外是否完整。",
        "clause_type": "LIABILITY",
    },
    "term_change_termination": {
        "title": "终止后的资料返还与数据交接未明确",
        "explanation": "条款约定了提前终止的通知与结算，但对终止后的资料返还、数据交接和存续义务未作安排，退出成本难以预估。",
        "impact": "退出安排缺失时，资料与数据交接拖延会放大持续履约和争议风险。",
        "advice": "建议明确终止后的资料返还、数据交接期限与存续义务，并约定过渡服务。",
        "negotiation": "通知期限与过渡期可协商，终止后的交接与存续义务不可空缺。",
        "question": "请确认终止后是否需要数据迁移或过渡服务。",
        "verification": "核对终止通知、结算、交接、数据返还和存续条款是否分别有文字依据。",
        "clause_type": "TERMINATION",
    },
    "confidentiality_data_ip": {
        "title": "保密期限较短且例外情形未列明",
        "explanation": "保密条款仅约定两年存续期，法定披露等必要例外未列明，涉及源代码与客户数据共享时保护边界不清。",
        "impact": "保密边界不清会削弱商业秘密保护，终止后泄露难以追责。",
        "advice": "建议明确保密信息范围、例外与泄露通知，并约定分包方承担同等义务。",
        "negotiation": "保密期限与例外范围可协商，泄露通知与分包方义务需保留。",
        "question": "请确认是否会接触源代码、个人信息或第三方保密资料。",
        "verification": "核对保密定义、例外、保护措施、泄露处理与存续期限。",
        "clause_type": "CONFIDENTIALITY",
    },
}


def _golden_load_run_context(state: dict[str, Any]) -> dict[str, Any]:
    """I/O stub — freezes the unified snapshot inputs the real loader would
    read from the shared EvidenceSnapshot store."""
    clauses = [item for items in _golden_evidence().values() for item in items]
    snapshot = fake_snapshot(
        _GOLDEN_CASE_ID, document_id=11, document_version=3,
        clauses=clauses, snapshot_hash=_GOLDEN_HASH,
    )
    return {
        "state_revision": state.get("state_revision", 0) + 1,
        "current_node": "load_run_context",
        "case_snapshot": {
            "id": _GOLDEN_CASE_ID,
            "title": "Golden 软件采购合同",
            "contractType": "SERVICE_PROCUREMENT",
            "ourSide": "BUYER",
            "updateTime": "2026-08-01 10:00:00",
        },
        "analysis_workflow": {
            "workflowId": 101,
            "documentId": 11,
            "documentVersion": "v3",
            "evidenceSnapshotHash": _GOLDEN_HASH,
        },
        "document_snapshot": [{"id": 11, "version": "v3", "parseQuality": "HIGH"}],
        "document_quality": {
            "status": "PASS", "documentCount": 1,
            "lowQualityDocumentIds": [], "reviewDocumentIds": [],
            "requiresHumanReview": False,
        },
        "evidence_snapshot": snapshot,
        "contract_evidence_snapshot": snapshot.get("clauses") or [],
        "extraction_snapshot": {"id": None, "status": None, "elements": []},
        "observations": [{
            "callId": f"graph-analysis-snapshot-{state.get('run_id', 0)}",
            "planStepId": "load_shared_evidence_snapshot",
            "toolName": "loadContractAnalysisSnapshot",
            "arguments": {"workflowId": 101, "documentId": 11, "documentVersion": "v3"},
            "output": {
                "evidenceSnapshotHash": _GOLDEN_HASH,
                "documentCount": 1,
                "clauseCount": len(clauses),
            },
            "status": "DONE",
        }],
    }


def _golden_retrieve_domain_evidence(state: dict[str, Any]) -> dict[str, Any]:
    """I/O stub — deterministic per-domain evidence derived from the planned
    domain tasks, so every baseline domain has retrievable support."""
    domain_tasks = state.get("domain_tasks") or []
    case_id = int(state.get("subject_id") or 0)
    evidence_map = _golden_evidence()

    domain_results: dict[str, list[dict[str, Any]]] = {}
    retrieval_validation: dict[str, dict[str, Any]] = {}
    citations: list[dict[str, Any]] = []
    observations: list[dict[str, Any]] = []
    for task in domain_tasks:
        key = str(task.get("domainKey") or task.get("domain") or "")
        evidence = evidence_map.get(key) or []
        domain_results[key] = evidence
        citations.extend(evidence)
        type_counts: dict[str, int] = {}
        for item in evidence:
            source_type = str(item.get("sourceType") or "UNKNOWN")
            type_counts[source_type] = type_counts.get(source_type, 0) + 1
        retrieval_validation[key] = {
            "mode": "GOLDEN_STUB",
            "crossValidatedCount": 0,
            "evidenceCount": len(evidence),
            "rerankMethods": [],
            "stats": {},
        }
        observations.append({
            "callId": f"graph-retrieval-{key}-{case_id}",
            "planStepId": f"retrieve_{key}",
            "toolName": "retrieveEvidenceBundle",
            "arguments": {
                "domainKey": key,
                "domainName": task.get("domainName"),
                "queries": task.get("queries") or [],
                "clauseTypes": task.get("requiredClauseTypes") or [],
            },
            "output": {
                "sourceCounts": type_counts,
                "retrievalValidation": retrieval_validation[key],
            },
            "status": "DONE",
        })

    return {
        "state_revision": state.get("state_revision", 0) + 1,
        "current_node": "retrieve_domain_evidence",
        "domain_results": domain_results,
        "retrieval_validation": retrieval_validation,
        "citations": citations,
        "observations": observations,
    }


def _golden_finding(
    domain_key: str,
    domain_name: str,
    fixture: dict[str, Any],
    evidence: list[dict[str, Any]],
) -> dict[str, Any]:
    """One realistic finding in the production ``_normalize_finding`` shape.

    Citation IDs and the contract citation snippet are derived from the
    actual retrieval evidence, so the real 10-check gate verifies them
    against canonical text (citation_support)."""
    item = evidence[0] if evidence else {}
    source_id = str(item.get("sourceId") or f"CONTRACT_CLAUSE:{domain_key}")
    text = str(item.get("clauseText") or "")
    return {
        "findingKey": f"{domain_key}:golden_1",
        "ruleKey": None,
        "ruleTitle": None,
        "clauseType": fixture["clause_type"],
        "severity": "MEDIUM",
        "domainKey": domain_key,
        "domainName": domain_name,
        "sourceBasis": "CONTRACT_ONLY",
        "title": fixture["title"],
        "oneLineSummary": fixture["title"],
        "keyPoint": fixture["advice"],
        "description": fixture["explanation"],
        "riskExplanation": fixture["explanation"],
        "impact": fixture["impact"],
        "businessImpact": fixture["impact"],
        "contractBasis": {"citations": [source_id]},
        "knowledgeBasis": {"citations": []},
        "explicitConsequence": "",
        "inferredConsequence": "",
        "inferredConsequenceDisclaimer": "",
        "remediationAdvice": fixture["advice"],
        "revisionAdvice": fixture["advice"],
        "negotiationAdvice": fixture["negotiation"],
        "reviewQuestions": [fixture["question"]],
        "verificationPoints": [fixture["verification"]],
        "suggestedAction": "REQUEST_LEGAL_REVIEW",
        "contractCitationIds": [source_id],
        "policyCitationIds": [],
        "contractCitation": {
            "page": item.get("page"),
            "clause": item.get("title") or "",
            "clauseNumber": item.get("clauseNumber"),
            "snippet": text[:40],
        },
        "policyCitation": None,
        "evidenceStatus": "CONTRACT_ONLY",
        "confidenceLevel": "MEDIUM",
        "frontendDisplay": {},
    }


def _golden_draft_domain_findings(state: dict[str, Any]) -> dict[str, Any]:
    """I/O stub — replaces the LLM analysis with the frozen findings fixture
    and marks every domain COMPLETED so coverage reaches CONFIRMED."""
    domain_results = state.get("domain_results") or {}
    domain_tasks = state.get("domain_tasks") or []
    subject_id = state.get("subject_id", 0)

    draft: list[dict[str, Any]] = []
    domain_analysis: dict[str, dict[str, Any]] = {}
    observations: list[dict[str, Any]] = []
    for task in domain_tasks:
        key = str(task.get("domainKey") or task.get("domain") or "")
        fixture = _GOLDEN_FINDINGS[key]
        finding = _golden_finding(key, task.get("domainName"), fixture, domain_results.get(key) or [])
        draft.append(finding)
        domain_analysis[key] = {
            "domainName": task.get("domainName"),
            "status": "COMPLETED",
            "findingCount": 1,
            "conclusion": fixture["explanation"][:300],
        }
        observations.append({
            "callId": f"graph-domain-analysis-{key}-{subject_id}",
            "planStepId": f"analyze_{key}",
            "toolName": "analyzeContractRiskDomain",
            "arguments": {
                "domainKey": key,
                "domainName": task.get("domainName"),
                "evidenceCount": len(domain_results.get(key) or []),
                "extractedFactCount": 0,
            },
            "output": {
                "status": "COMPLETED",
                "findingCount": 1,
                "conclusion": fixture["explanation"][:300],
            },
            "status": "COMPLETED",
        })

    return {
        "state_revision": state.get("state_revision", 0) + 1,
        "current_node": "draft_domain_findings",
        "draft_findings": draft,
        "domain_analysis": domain_analysis,
        "observations": observations,
    }


def _golden_targeted_retrieval(state: dict[str, Any]) -> dict[str, Any]:
    """Loud guard: the golden path has CONFIRMED coverage, so the retry
    branch must never be visited — a regression here fails the run."""
    raise RuntimeError("targeted_retrieval must not be visited on the golden path")


def _golden_nodes() -> dict[str, Callable]:
    """The golden pipeline: real v1 nodes everywhere except the five
    DB / LLM / orchestrator I/O nodes (load_run_context,
    retrieve_domain_evidence, draft_domain_findings, targeted_retrieval)."""
    nodes = dict(CONTRACT_REVIEW_SPEC.nodes)
    nodes.update({
        "load_run_context": _golden_load_run_context,
        "retrieve_domain_evidence": _golden_retrieve_domain_evidence,
        "draft_domain_findings": _golden_draft_domain_findings,
        "targeted_retrieval": _golden_targeted_retrieval,
    })
    return nodes


def _golden_spec() -> TaskSpec:
    """CONTRACT_REVIEW_SPEC with the golden node set — same roles / wiring."""
    nodes = _golden_nodes()
    return TaskSpec(
        task_type=CONTRACT_REVIEW_SPEC.task_type,
        graph_name=CONTRACT_REVIEW_SPEC.graph_name,
        graph_version=CONTRACT_REVIEW_SPEC.graph_version,
        prompt_version=CONTRACT_REVIEW_SPEC.prompt_version,
        context=Role(_role_stages(CONTRACT_REVIEW_SPEC.context, nodes)),
        planner=Role(_role_stages(CONTRACT_REVIEW_SPEC.planner, nodes)),
        retriever=Role(_role_stages(CONTRACT_REVIEW_SPEC.retriever, nodes)),
        analyzer=Role(_role_stages(CONTRACT_REVIEW_SPEC.analyzer, nodes)),
        validator=Role(_role_stages(CONTRACT_REVIEW_SPEC.validator, nodes)),
        coverage_auditor=Role(_role_stages(CONTRACT_REVIEW_SPEC.coverage_auditor, nodes)),
        composer=Role(_role_stages(CONTRACT_REVIEW_SPEC.composer, nodes)),
        persistence=Role(_role_stages(CONTRACT_REVIEW_SPEC.persistence, nodes)),
        human_gate=CONTRACT_REVIEW_SPEC.human_gate,
        edges=CONTRACT_REVIEW_SPEC.edges,
        conditional_routes=CONTRACT_REVIEW_SPEC.conditional_routes,
    )


@contextmanager
def _golden_environment() -> Iterator[None]:
    """Patch only the external boundaries the golden run touches:

    * clause-signal DB load → [] (create_domain_tasks calls it outside its
      try, like production would on a DB miss);
    * domain planner LLM → no dynamic domains (baseline-only plan);
    * deterministic rule store → unavailable (the real node's try/except
      must degrade to rule_findings=[]);
    * report store → scripted report id (the real persist_report logic
      still runs).
    """

    async def _rules_down(*args: Any, **kwargs: Any) -> list[dict]:
        raise RuntimeError("deterministic rule store unavailable (golden fixture)")

    with (
        mock.patch.object(domain_tasks_mod, "_load_clause_signals", return_value=[]),
        mock.patch.object(LLMService, "plan_contract_risk_domains", return_value={"domains": []}),
        mock.patch.object(ContractStore, "evaluate_rules", _rules_down),
        mock.patch.object(MySqlReportStore, "_save_sync", return_value=501),
    ):
        yield


def _golden_initial_state() -> dict[str, Any]:
    """The run seeding the golden capture and every golden test reuses —
    byte-stable so streamed states compare equal across capture and test."""
    return {
        "run_id": _GOLDEN_RUN_ID,
        "subject_type": "CONTRACT_CASE",
        "subject_id": _GOLDEN_CASE_ID,
        "task_type": "CONTRACT_REVIEW",
        "task_input": {},
        "graph_name": "contract_review",
        "graph_version": "v1",
        "model": "",
        "prompt_version": "contract-review-graph-v1",
        "trigger_type": "MANUAL",
        "state_revision": 0,
        "case_snapshot": {},
        "observations": [],
        "citations": [],
        "errors": [],
        "shadow_mode": False,
    }


def _stream_run(graph) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    """Run the golden graph once and return (stage → input state) plus the
    final accumulated state. stream_mode="values" emits the merged state
    after each node, so ``inputs[stage]`` is exactly what that node received
    from the graph plumbing.

    Each input is deep-copied at emission time: downstream nodes
    (prepare_human_review) mutate the artifact dict in place, which would
    otherwise leak into the frozen inputs of earlier stages through shared
    references."""
    previous = _golden_initial_state()
    stage_inputs: dict[str, dict[str, Any]] = {}
    final_state: dict[str, Any] = previous
    for state in graph.stream(_golden_initial_state(), stream_mode="values"):
        stage = state.get("current_node")
        if stage:
            stage_inputs[stage] = copy.deepcopy(previous)
        previous = state
        final_state = state
    return stage_inputs, final_state


def _collect_golden() -> dict[str, Any]:
    """Drive the spec-built golden graph once; record every real node's
    (input, output) pair and the final artifact for the frozen fixture.

    The whole collection stays inside the patched environment — the node
    replay calls persist_report directly, and an unpatched run would touch
    the real report store."""
    node_samples: dict[str, dict[str, Any]] = {}
    with _golden_environment():
        graph = build_task_graph(_golden_spec())
        stage_inputs, final_state = _stream_run(graph)

        for stage in _GOLDEN_REAL_STAGES:
            input_state = stage_inputs[stage]
            node_samples[stage] = {
                "input": input_state,
                "output": _golden_nodes()[stage](input_state),
            }

        # Off-path real nodes: pin them against deterministic synthetic
        # inputs (the state the routers would have produced on their
        # branch). Taken from the state right after compose_report — a
        # snapshot captured before any human-review mutation — so the
        # samples stay branch-faithful.
        post_compose = dict(stage_inputs["validate_schema"])
        limited_state = {
            **post_compose,
            "coverage": {**post_compose["coverage"], "status": "CANNOT_RESOLVE"},
        }
        node_samples["compose_limited_report"] = {
            "input": limited_state,
            "output": compose_limited_report(limited_state),
        }
        broken_artifact = {**post_compose["artifact"], "title": ""}
        repair_state = {
            **post_compose,
            "artifact": broken_artifact,
            "schema_validation": {
                "valid": False,
                "errors": ["title: Field required"],
                "warnings": [],
                "repair_count": 0,
            },
        }
        node_samples["repair_artifact"] = {
            "input": repair_state,
            "output": repair_artifact(repair_state),
        }

    return {
        "artifact": final_state.get("artifact") or {},
        "node_samples": node_samples,
    }


def capture_golden() -> None:
    """Regenerate the frozen golden fixture from the real-node pipeline.

    Called by scripts/capture_contract_review_v1_golden.py — never from
    within the tests themselves."""
    payload = _collect_golden()
    GOLDEN_PATH.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _context(run_id: int) -> AgentTaskContext:
    return AgentTaskContext(
        run_id=run_id,
        project_id=1,
        task_type="CONTRACT_REVIEW",
        question="",
        subject_type="CONTRACT_CASE",
        subject_id=_GOLDEN_CASE_ID,
        project={},
        task_input={},
    )


def _dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _run_artifact(graph) -> dict[str, Any]:
    with _golden_environment():
        store = FakePersistence()
        adapter = GraphAdapter(
            graph, graph_name="contract_review", graph_version="v1", run_store=store
        )
        result = asyncio.run(adapter.run(_context(_GOLDEN_RUN_ID)))
    assert result.status == "COMPLETED", result
    return result.artifact


def _load_golden() -> dict[str, Any]:
    assert GOLDEN_PATH.exists(), "golden fixture missing — run scripts/capture_contract_review_v1_golden.py"
    return json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))


def test_golden_spec_built_graph_reproduces_frozen_artifact():
    """The spec-built graph running the real v1 node chain reproduces the
    independently captured artifact byte-for-byte."""
    golden = _load_golden()
    artifact = _run_artifact(build_task_graph(_golden_spec()))
    assert _dump(artifact) == _dump(golden["artifact"])


def test_golden_reference_wiring_reproduces_frozen_artifact():
    """The pre-migration inline wiring running the same real nodes produces
    the same artifact — behavioral equivalence of the two wirings."""
    golden = _load_golden()
    artifact = _run_artifact(_frozen_reference_graph(_golden_nodes()))
    assert _dump(artifact) == _dump(golden["artifact"])


def test_golden_node_samples_reproduce_frozen_behavior():
    """Every real v1 node replays against its frozen input sample and must
    produce the frozen output; the live graph must also feed each real node
    exactly the frozen input (ties the samples to the real wiring). The
    replay stays inside the patched environment — persist_report's sample
    was captured under it, and an unpatched call would touch the real
    report store."""
    golden = _load_golden()
    node_samples = golden["node_samples"]

    with _golden_environment():
        graph = build_task_graph(_golden_spec())
        stage_inputs, _final_state = _stream_run(graph)

        for stage in _GOLDEN_REAL_STAGES:
            sample = node_samples[stage]
            assert _dump(stage_inputs[stage]) == _dump(sample["input"]), (
                f"{stage} live input drifted from the frozen sample"
            )
            assert _dump(_golden_nodes()[stage](sample["input"])) == _dump(sample["output"]), (
                f"{stage} output drifted from the frozen sample"
            )

        for stage in ("compose_limited_report", "repair_artifact"):
            sample = node_samples[stage]
            assert _dump(_golden_nodes()[stage](sample["input"])) == _dump(sample["output"]), (
                f"{stage} output drifted from the frozen sample"
            )


def test_golden_fixture_samples_come_from_real_v1_nodes():
    """Guard against circularity creeping back in: the frozen samples must
    have been produced by the real v1 functions, not by test stubs."""
    golden = _load_golden()
    real = CONTRACT_REVIEW_SPEC.nodes

    assert set(golden["node_samples"]) == set(_GOLDEN_REAL_STAGES) | {
        "compose_limited_report", "repair_artifact",
    }
    for stage in _GOLDEN_REAL_STAGES:
        assert _golden_nodes()[stage] is real[stage], f"{stage} is stubbed in the golden pipeline"

    artifact = golden["artifact"]
    assert artifact["reportType"] == "CONTRACT_REVIEW_REPORT"
    assert artifact["analysisMode"] == "FULL"
    assert artifact["humanReviewRequired"] is True
    assert len(artifact["findings"]) == len(_GOLDEN_FINDINGS)
