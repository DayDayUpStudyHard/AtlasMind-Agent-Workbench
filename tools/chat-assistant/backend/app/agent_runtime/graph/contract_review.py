"""ContractReviewGraph — domain fan-out/fan-in DAG for contract review.

PRD Section 11 — full graph with clause inventory, domain tasks,
parallel retrieval, claim validation, coverage reflection, and report generation.
"""

from __future__ import annotations

import logging
from typing import Any

from ..harness.graph_builder import build_task_graph
from ..harness.models import Role, TaskSpec
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
    prepare_human_review,
    _route_after_schema,
    persist_report,
)

logger = logging.getLogger(__name__)


def _route_after_reflection(state: dict[str, Any]) -> str:
    """Route based on coverage reflection status."""
    coverage = state.get("coverage") or {}
    status = coverage.get("status", "NEED_MORE_EVIDENCE")
    retry_count = int((state.get("retry_state") or {}).get("reflection_rounds", 0))

    # Per-run override for max retries (default 1, 0 = no targeted retrieval)
    from app.agent_runtime.runtime import _retry_limit_override
    max_retries = _retry_limit_override.get()
    if max_retries < 0:
        max_retries = 1  # default: one targeted retrieval pass

    if status == "CONFIRMED":
        return "compose_report"
    if status == "CANNOT_RESOLVE":
        return "compose_limited_report"
    if retry_count >= max_retries:
        return "compose_limited_report"
    return "targeted_retrieval"


def _route_after_targeted(state: dict[str, Any]) -> str:
    """After targeted retrieval, re-analyze gap domains with the new evidence.

    Supplementary evidence found during targeted_retrieval must flow back into
    domain analysis and claim validation before a report is composed.  The
    coverage_reflection → _route_after_reflection gate enforces at most one
    retry, so this cannot loop.
    """
    return "draft_domain_findings"


# Frozen pre-migration wiring: the same nodes, linear / loop-back edges and
# conditional gates the v1 builder hardcoded before Phase 4, re-declared as
# the §6.1 role contract. The common builder compiles this spec; output
# fields are untouched because the node functions are referenced by
# identity.

# §4.2 role → skeleton stage mapping for risk v1:
#   context          = load_snapshot + build_task_context
#   planner          = plan_work_units (inventory + domain tasks)
#   retriever        = retrieve_evidence
#   analyzer         = analyze_units (rules + LLM findings)
#   validator        = validate_candidates
#   coverage_auditor = audit_coverage (+ one bounded targeted retry)
#   composer         = compose_artifact (full / limited / schema gate / repair)
#   persistence      = persist_or_human_gate (review boundary record + persist)
# Risk v1 has no interrupt stage, so human_gate is None.
CONTRACT_REVIEW_SPEC = TaskSpec(
    task_type="CONTRACT_REVIEW",
    graph_name="contract_review",
    graph_version="v1",
    prompt_version="contract-review-graph-v1",
    context=Role((
        ("load_run_context", load_run_context),
        ("freeze_case_snapshot", freeze_case_snapshot),
    )),
    planner=Role((
        ("inventory_clauses", inventory_clauses),
        ("create_domain_tasks", create_domain_tasks),
    )),
    retriever=Role((
        ("retrieve_domain_evidence", retrieve_domain_evidence),
    )),
    analyzer=Role((
        ("run_deterministic_rules", run_deterministic_rules),
        ("draft_domain_findings", draft_domain_findings),
    )),
    validator=Role((
        ("validate_claims", validate_claims),
    )),
    coverage_auditor=Role((
        ("coverage_reflection", coverage_reflection),
        ("targeted_retrieval", targeted_retrieval),
    )),
    composer=Role((
        ("compose_report", compose_report),
        ("compose_limited_report", compose_limited_report),
        ("validate_schema", validate_schema),
        ("repair_artifact", repair_artifact),
    )),
    persistence=Role((
        ("prepare_human_review", prepare_human_review),
        ("persist_report", persist_report),
    )),
    edges=(
        ("inventory_clauses", "create_domain_tasks"),
        ("create_domain_tasks", "retrieve_domain_evidence"),
        ("retrieve_domain_evidence", "run_deterministic_rules"),
        ("run_deterministic_rules", "draft_domain_findings"),
        ("draft_domain_findings", "validate_claims"),
        ("validate_claims", "coverage_reflection"),
        # Targeted retrieval feeds supplementary evidence back into domain
        # analysis so gap domains get a second LLM pass before the report is
        # composed. The coverage_reflection retry gate prevents unbounded loops.
        ("targeted_retrieval", "draft_domain_findings"),
        ("compose_report", "validate_schema"),
        ("compose_limited_report", "validate_schema"),
        ("repair_artifact", "validate_schema"),
        ("prepare_human_review", "persist_report"),
    ),
    conditional_routes={
        "coverage_reflection": (
            _route_after_reflection,
            {
                "compose_report": "compose_report",
                "compose_limited_report": "compose_limited_report",
                "targeted_retrieval": "targeted_retrieval",
            },
        ),
        "validate_schema": (
            _route_after_schema,
            {
                "persist_report": "persist_report",
                "prepare_human_review": "prepare_human_review",
                "repair_artifact": "repair_artifact",
                "compose_limited_report": "compose_limited_report",
            },
        ),
    },
)


def build_contract_review_graph(checkpointer: Any = None) -> Any:
    """Build and compile the ContractReviewGraph from its TaskSpec.

    Args:
        checkpointer: Optional LangGraph checkpointer for state persistence.
    """
    return build_task_graph(CONTRACT_REVIEW_SPEC, checkpointer)


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
