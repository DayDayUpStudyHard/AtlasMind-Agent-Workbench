"""FulfillmentCheckGraph — state machine for fulfillment verification with human-in-the-loop.

PRD Section 12 — decomposes requirements, matches evidence, judges each item,
validates, and waits for human confirmation via LangGraph interrupt.
"""

from __future__ import annotations

import logging
from typing import Any

from langgraph.graph import StateGraph, START, END

from .state import BaseGraphState
from .nodes.requirements import decompose_requirements
from .nodes.fulfillment_judge import judge_each_requirement
from .nodes.fulfillment_validate import validate_fulfillment_judgement
from .nodes.human_confirm import wait_human_confirmation, apply_human_result
from .nodes.artifact import persist_report

logger = logging.getLogger(__name__)


def build_fulfillment_check_graph(checkpointer: Any = None) -> Any:
    """Build and compile the FulfillmentCheckGraph.

    Args:
        checkpointer: Optional LangGraph checkpointer for state persistence.
    """

    builder = StateGraph(BaseGraphState)

    # ── Nodes ──
    builder.add_node("decompose_requirements", decompose_requirements)
    builder.add_node("judge_each_requirement", judge_each_requirement)
    builder.add_node("validate_fulfillment_judgement", validate_fulfillment_judgement)
    builder.add_node("wait_human_confirmation", wait_human_confirmation)
    builder.add_node("apply_human_result", apply_human_result)
    builder.add_node("persist_report", persist_report)

    # ── Edges ──
    builder.add_edge(START, "decompose_requirements")
    builder.add_edge("decompose_requirements", "judge_each_requirement")
    builder.add_edge("judge_each_requirement", "validate_fulfillment_judgement")
    builder.add_edge("validate_fulfillment_judgement", "wait_human_confirmation")

    # Human confirmation → apply result → persist
    builder.add_edge("wait_human_confirmation", "apply_human_result")
    builder.add_edge("apply_human_result", "persist_report")
    builder.add_edge("persist_report", END)

    # Compile with interrupt before human confirmation
    kwargs = {"interrupt_before": ["wait_human_confirmation"]}
    if checkpointer:
        kwargs["checkpointer"] = checkpointer
    return builder.compile(**kwargs)


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
