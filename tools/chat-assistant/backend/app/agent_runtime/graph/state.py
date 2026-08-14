"""Graph state definitions for contract agent graphs.

Uses LangGraph's StateGraph with TypedDict + reducer annotations.
All fields are serializable for MySQL checkpoint persistence.
"""

from __future__ import annotations

from typing import Annotated, Any, TypedDict


def _add_observations(left: list[dict], right: list[dict]) -> list[dict]:
    """Reducer: append new observations, deduplicate by callId."""
    seen = {o.get("callId") for o in left if o.get("callId")}
    result = list(left)
    for item in right:
        cid = item.get("callId")
        if cid and cid not in seen:
            result.append(item)
            seen.add(cid)
        elif not cid:
            result.append(item)
    return result


def _add_citations(left: list[dict], right: list[dict]) -> list[dict]:
    """Reducer: merge citations, deduplicate by sourceId + sourceType."""
    seen = set()
    result = []
    for item in left + right:
        key = f"{item.get('sourceType','')}:{item.get('sourceId','')}"
        if key not in seen:
            result.append(item)
            seen.add(key)
    return result


def _overwrite_or_keep(_left: Any, right: Any) -> Any:
    """Default overwrite reducer."""
    return right if right is not None else _left


class BaseGraphState(TypedDict, total=False):
    """Common state shared across all contract agent graphs.

    Graph-specific states should extend this with domain-specific fields.
    """

    # ── Run identity ──
    run_id: int
    subject_type: str               # CONTRACT_CASE | PROJECT
    subject_id: int
    task_type: str                  # CONTRACT_REVIEW | FULFILLMENT_CHECK | etc.
    task_input: dict[str, Any]
    graph_name: str
    graph_version: str
    model: str
    prompt_version: str
    # PRD Phase 8 / §10: frozen retrieval/rerank/scorer stack versions —
    # carried in state so composers can stamp them onto the artifact.
    retrieval_version: str
    rerank_version: str
    scorer_version: str
    trigger_type: str               # MANUAL | RESUME | SHADOW | SCHEDULED

    # ── State management ──
    state_revision: int
    current_node: str

    # ── Frozen snapshots ──
    case_snapshot: dict[str, Any]
    analysis_workflow: dict[str, Any]
    document_snapshot: list[dict[str, Any]]
    # Unified evidence snapshot (PRD §19.1): the canonical, hash-addressed
    # evidence view every graph derives its facts from. `clauses` is stripped
    # in the state copy — full clause details live in
    # `contract_evidence_snapshot`, loaded from the same builder call.
    evidence_snapshot: dict[str, Any]
    contract_evidence_snapshot: list[dict[str, Any]]
    knowledge_snapshot: list[dict[str, Any]]
    document_quality: dict[str, Any]

    # -- Versioned contract extraction facts --
    extraction_context: dict[str, Any]
    element_packs: list[dict[str, Any]]
    element_evidence: dict[str, list[dict[str, Any]]]
    extracted_elements: list[dict[str, Any]]
    extraction_validation: dict[str, Any]
    contract_profile: dict[str, Any]
    profile_validation: dict[str, Any]
    extraction_snapshot: dict[str, Any]
    # Phase 5 field-level rerun / coverage channels. These must stay in the
    # schema: LangGraph silently drops node-output keys that are not declared
    # here, which would break carried settled elements and the coverage audit
    # at runtime even though direct node-call tests pass.
    base_identity_fields: list[dict[str, Any]]
    carried_elements: list[dict[str, Any]]
    element_coverage_audit: dict[str, Any]

    # -- Phase 6 timeline DAG (rule → LLM → validation → publish) --
    timeline_scope: dict[str, Any]
    timeline_clauses: list[dict[str, Any]]
    timeline_candidates: list[dict[str, Any]]
    timeline_enrichment: dict[str, Any]
    timeline_validation: dict[str, Any]
    timeline_audit: dict[str, Any]

    # Fulfillment verification context and human decision channels
    fulfillment_context: dict[str, Any]
    fulfillment_requirements: list[dict[str, Any]]
    evidence_snapshot: list[dict[str, Any]]
    manual_result: str
    note: str
    operator_id: str
    # Phase 7 fulfillment verification (evidence rules → LLM suggestion →
    # rerun scope). Declared in the schema for the same reason as the
    # Phase 5/6 channels: LangGraph silently drops undeclared node-output
    # keys, so these must be typed here to survive a compiled run.
    evidence_rules: dict[str, Any]
    rerun_scope: dict[str, Any]
    fulfillment_ai: dict[str, Any]
    fulfillment_validation: dict[str, Any]

    # ── Accumulated data ──
    observations: Annotated[list[dict[str, Any]], _add_observations]
    citations: Annotated[list[dict[str, Any]], _add_citations]

    # ── Plan ──
    plan: dict[str, Any]             # Bounded execution plan
    domain_tasks: list[dict[str, Any]]
    domain_results: dict[str, list[dict[str, Any]]]
    domain_analysis: dict[str, dict[str, Any]]
    retrieval_validation: dict[str, Any]

    # ── Findings & verification ──
    rule_findings: list[dict[str, Any]]
    draft_findings: list[dict[str, Any]]
    validated_findings: list[dict[str, Any]]
    evidence_validation: dict[str, Any]
    coverage: dict[str, Any]         # Domain coverage matrix
    reflection: dict[str, Any]       # Current quality gate result
    scoring: dict[str, Any]

    # ── Budget & errors ──
    budget: dict[str, Any]
    errors: list[dict[str, Any]]
    retry_state: dict[str, Any]
    # §7.2 per-WorkUnit spend ledger: nodes record queries / LLM calls /
    # tokens / retry rounds here in place (harness.budget.record_unit_usage);
    # the schema gate audits it against WorkUnitBudget and can flip the run
    # to LIMITED. Keyed by work unit id (risk v1: domainKey).
    work_unit_usage: dict[str, dict[str, int]]
    # §7.2/§6.4: when a node marks the run scope-limited (over-budget or
    # coverage-limited WorkUnit), it writes the mandatory diagnostics here;
    # the runtime turns the run into LIMITED, never FAILED / false COMPLETED.
    limited_diagnostics: dict[str, Any] | None

    # ── Artifact ──
    artifact: dict[str, Any]
    artifacts: dict[str, Any]
    schema_validation: dict[str, Any]
    human_review: dict[str, Any]

    # ── Human-in-the-loop ──
    wait_state: dict[str, Any] | None

    # ── Contract review v2 pilot (PRD Phase 3, §15) ──
    # Sub-item WorkUnits and their per-unit evidence/analysis structures.
    work_units: list[dict[str, Any]]
    contract_map: dict[str, Any]
    evidence_bundles_by_work_unit: dict[str, dict[str, Any]]
    findings_by_work_unit: dict[str, list[dict[str, Any]]]
    merged_candidates_by_work_unit: dict[str, list[dict[str, Any]]]
    validation_by_work_unit: dict[str, dict[str, Any]]
    counter_analysis_by_work_unit: dict[str, list[dict[str, Any]]]
    coverage_by_work_unit: dict[str, dict[str, Any]]
    evidence_needs: list[dict[str, Any]]
    negative_conclusion_checks: list[dict[str, Any]]
    retry_budget: int
    reanalysis_targets: list[str]
