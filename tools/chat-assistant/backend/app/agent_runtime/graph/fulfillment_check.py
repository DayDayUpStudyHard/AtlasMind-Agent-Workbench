"""FulfillmentCheckGraph — state machine for fulfillment verification with human-in-the-loop.

PRD Section 12 / Phase 7 — decomposes requirements, checks evidence rules,
judges each item (rule layer + advisory LLM suggestions), validates, audits,
and waits for human confirmation via LangGraph interrupt.

The graph is declared as the §6.1 role contract (TaskSpec) and compiled by
the common harness builder — same as risk v1 (Phase 4) and timeline v1
(Phase 6). It is the one graph with a real interrupt stage, which the spec
declares as its human_gate.
"""

from __future__ import annotations

import logging
from typing import Any

from ..harness.graph_builder import build_task_graph
from ..harness.models import HumanGate, Role, TaskSpec
from .state import BaseGraphState
from .nodes.context import load_run_context, freeze_case_snapshot
from .nodes.requirements import decompose_requirements
from .nodes.retrieval import retrieve_fulfillment_evidence
from .nodes.evidence_rules import check_evidence_rules
from .nodes.fulfillment_judge import judge_each_requirement
from .nodes.fulfillment_validate import validate_fulfillment_judgement
from .nodes.fulfillment_audit import audit_fulfillment_coverage
from .nodes.human_confirm import (
    prepare_human_confirmation,
    wait_human_confirmation,
    apply_human_result,
)
from .nodes.artifact import persist_report

logger = logging.getLogger(__name__)


class _FulfillmentHumanGate(HumanGate):
    """PRD Phase 7, task 7: the single interrupt stage. ``HumanGate`` is the
    §6.1 spec hook — this subclass binds the spec's gate to the real
    interrupt node (``wait_human_confirmation`` calls LangGraph interrupt)."""

    def __call__(self, state: dict[str, Any]) -> dict[str, Any]:
        return wait_human_confirmation(state)


_FULFILLMENT_GATE = _FulfillmentHumanGate(stage="wait_human_confirmation")


# §4.2 role → skeleton stage mapping for fulfillment v1:
#   context          = load_run_context + freeze_case_snapshot
#   planner          = decompose_requirements (timeline node → sub-items)
#   retriever        = retrieve_fulfillment_evidence (+ rerun scope, task 8)
#   analyzer         = check_evidence_rules (task 4) + judge_each_requirement
#                      (rule layer + advisory LLM suggestions, task 5)
#   validator        = validate_fulfillment_judgement (task 6 enforcement)
#   coverage_auditor = audit_fulfillment_coverage
#   composer         = prepare_human_confirmation (materializes the HITL payload)
#   persistence      = wait_human_confirmation (the gate) + apply_human_result
#                      + persist_report (INSERT per run — history never overwritten)
FULFILLMENT_SPEC = TaskSpec(
    task_type="FULFILLMENT_CHECK",
    graph_name="fulfillment_check",
    graph_version="v1",
    prompt_version="contract-fulfillment-check-v1",
    context=Role((
        ("load_run_context", load_run_context),
        ("freeze_case_snapshot", freeze_case_snapshot),
    )),
    planner=Role((
        ("decompose_requirements", decompose_requirements),
    )),
    retriever=Role((
        ("retrieve_fulfillment_evidence", retrieve_fulfillment_evidence),
    )),
    analyzer=Role((
        ("check_evidence_rules", check_evidence_rules),
        ("judge_each_requirement", judge_each_requirement),
    )),
    validator=Role((
        ("validate_fulfillment_judgement", validate_fulfillment_judgement),
    )),
    coverage_auditor=Role((
        ("audit_fulfillment_coverage", audit_fulfillment_coverage),
    )),
    composer=Role((
        ("prepare_human_confirmation", prepare_human_confirmation),
    )),
    persistence=Role((
        (_FULFILLMENT_GATE.stage, _FULFILLMENT_GATE),
        ("apply_human_result", apply_human_result),
        ("persist_report", persist_report),
    )),
    human_gate=_FULFILLMENT_GATE,
    edges=(
        ("decompose_requirements", "retrieve_fulfillment_evidence"),
        ("retrieve_fulfillment_evidence", "check_evidence_rules"),
        ("check_evidence_rules", "judge_each_requirement"),
        ("judge_each_requirement", "validate_fulfillment_judgement"),
        ("validate_fulfillment_judgement", "audit_fulfillment_coverage"),
        ("audit_fulfillment_coverage", "prepare_human_confirmation"),
        ("prepare_human_confirmation", "wait_human_confirmation"),
        ("wait_human_confirmation", "apply_human_result"),
        ("apply_human_result", "persist_report"),
    ),
)


def build_fulfillment_check_graph(checkpointer: Any = None) -> Any:
    """Build and compile the FulfillmentCheckGraph from its TaskSpec.

    Args:
        checkpointer: Optional LangGraph checkpointer for state persistence.
    """
    return build_task_graph(FULFILLMENT_SPEC, checkpointer=checkpointer)


def register(registry=None) -> None:
    """Register FulfillmentCheckGraph with the graph registry."""
    if registry is None:
        from .registry import get_graph_registry
        registry = get_graph_registry()

    registry.register(
        name="fulfillment_check",
        version="v1",
        builder=build_fulfillment_check_graph,
    )
    logger.info("Registered FulfillmentCheckGraph v1")


# BaseGraphState is re-exported for compatibility with code that imports the
# state from this module (the pre-migration public surface).
__all__ = [
    "FULFILLMENT_SPEC",
    "build_fulfillment_check_graph",
    "register",
    "BaseGraphState",
]
