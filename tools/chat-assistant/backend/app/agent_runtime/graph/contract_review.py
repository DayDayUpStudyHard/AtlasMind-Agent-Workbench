"""ContractReviewGraph — domain fan-out/fan-in DAG for contract review.

PRD Section 11 — full graph with clause inventory, domain tasks,
parallel retrieval, claim validation, coverage reflection, and report generation.
"""

from __future__ import annotations

import logging
from typing import Any

from langgraph.graph import StateGraph, START, END

from .state import BaseGraphState
from .nodes.context import load_run_context, freeze_case_snapshot
from .nodes.inventory import inventory_clauses
from .nodes.domain_tasks import create_domain_tasks
from .nodes.retrieval import retrieve_domain_evidence, run_deterministic_rules, draft_domain_findings
from .nodes.validation import validate_claims
from .nodes.reflection import coverage_reflection, targeted_retrieval
from .nodes.artifact import (
    compose_report,
    compose_limited_report,
    validate_schema,
    repair_artifact,
    _route_after_schema,
    persist_report,
)

logger = logging.getLogger(__name__)


def _route_after_reflection(state: dict[str, Any]) -> str:
    """Route based on coverage reflection status."""
    coverage = state.get("coverage") or {}
    status = coverage.get("status", "NEED_MORE_EVIDENCE")
    if status == "CONFIRMED":
        return "compose_report"
    if status == "CANNOT_RESOLVE":
        return "compose_limited_report"
    return "targeted_retrieval"


def _route_after_targeted(state: dict[str, Any]) -> str:
    """After targeted retrieval, go back to validation then reflection."""
    return "validate_claims"


def build_contract_review_graph(checkpointer: Any = None) -> Any:
    """Build and compile the ContractReviewGraph.

    Args:
        checkpointer: Optional LangGraph checkpointer for state persistence.
    """

    builder = StateGraph(BaseGraphState)

    # ── Context & snapshot ──
    builder.add_node("load_run_context", load_run_context)
    builder.add_node("freeze_case_snapshot", freeze_case_snapshot)

    # ── Clause inventory ──
    builder.add_node("inventory_clauses", inventory_clauses)

    # ── Domain tasks ──
    builder.add_node("create_domain_tasks", create_domain_tasks)

    # ── Real retrieval & rules ──
    builder.add_node("retrieve_domain_evidence", retrieve_domain_evidence)
    builder.add_node("run_deterministic_rules", run_deterministic_rules)
    builder.add_node("draft_domain_findings", draft_domain_findings)

    # ── Validation & reflection ──
    builder.add_node("validate_claims", validate_claims)
    builder.add_node("coverage_reflection", coverage_reflection)
    builder.add_node("targeted_retrieval", targeted_retrieval)

    # ── Report generation ──
    builder.add_node("compose_report", compose_report)
    builder.add_node("compose_limited_report", compose_limited_report)
    builder.add_node("validate_schema", validate_schema)
    builder.add_node("repair_artifact", repair_artifact)
    builder.add_node("persist_report", persist_report)

    # ── Edges ──
    builder.add_edge(START, "load_run_context")
    builder.add_edge("load_run_context", "freeze_case_snapshot")
    builder.add_edge("freeze_case_snapshot", "inventory_clauses")
    builder.add_edge("inventory_clauses", "create_domain_tasks")
    builder.add_edge("create_domain_tasks", "retrieve_domain_evidence")
    builder.add_edge("retrieve_domain_evidence", "run_deterministic_rules")
    builder.add_edge("run_deterministic_rules", "draft_domain_findings")
    builder.add_edge("draft_domain_findings", "validate_claims")
    builder.add_edge("validate_claims", "coverage_reflection")

    # Conditional routing from reflection
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

    # Report paths with quality gate
    builder.add_edge("compose_report", "validate_schema")
    builder.add_edge("compose_limited_report", "validate_schema")

    # validate_schema → persist | repair | limited (conditional gate)
    builder.add_conditional_edges(
        "validate_schema",
        _route_after_schema,
        {
            "persist_report": "persist_report",
            "repair_artifact": "repair_artifact",
            "compose_limited_report": "compose_limited_report",
        },
    )
    builder.add_edge("repair_artifact", "validate_schema")
    builder.add_edge("persist_report", END)

    return builder.compile(checkpointer=checkpointer) if checkpointer else builder.compile()


def register(registry=None) -> None:
    """Register ContractReviewGraph with the graph registry."""
    if registry is None:
        from .registry import get_graph_registry
        registry = get_graph_registry()

    registry.register(
        name="contract_review",
        version="v1",
        builder=build_contract_review_graph,
    )
    logger.info("Registered ContractReviewGraph v1")
