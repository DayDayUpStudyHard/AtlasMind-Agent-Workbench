"""Core domain models for the common evidence harness (PRD §10).

TypedDicts only — no runtime dependency on the DB, LLM or graph layers, so
they can be imported by graph nodes, harness modules and tests alike.

TaskSpec arrives in Phase 4 (PRD §14-4): after the shared retrieval /
validation / lifecycle modules proved stable, the harness now also carries
the declarative graph contract and its common builder.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Mapping, TypedDict


class WorkUnit(TypedDict):
    """The shared scheduling granularity of the harness (PRD §10.2).

    A WorkUnit is not bound to one task type. Risk review uses bounded domain
    units with an internal sub-check list, extraction uses element packs, and
    fulfillment uses requirements.
    """

    work_unit_id: str
    task_type: str
    category: str
    label: str
    objective: str
    applicability: str
    priority: str
    query_intents: list[str]
    required_clause_types: list[str]
    required_source_types: list[str]
    expected_output_schema: str
    required_checks: list[str]
    negative_claim_allowed: bool
    human_review_policy: str


class EvidenceNeed(TypedDict):
    """A concrete evidence gap found by validation or omission audit (PRD §10.3).

    EvidenceNeeds drive targeted retrieval; they never write into the report
    directly.
    """

    need_id: str
    work_unit_id: str
    reason_code: str
    description: str
    missing_source_types: list[str]
    missing_fields: list[str]
    query_hints: list[str]
    clause_type_hints: list[str]
    must_expand_neighbors: bool
    must_search_attachments: bool
    retryable: bool


# reason_code vocabulary (PRD §10.3)
REASON_CODES = (
    "NO_CONTRACT_EVIDENCE",
    "NO_POLICY_EVIDENCE",
    "UNSUPPORTED_CLAIM",
    "MISSING_SUBCHECK",
    "POSSIBLE_COUNTER_EVIDENCE",
    "AMBIGUOUS_PARTY",
    "AMBIGUOUS_DATE_ANCHOR",
    "CONFLICTING_VALUES",
    "LOW_PARSE_QUALITY",
    "NEGATIVE_CLAIM_NOT_PROVEN",
    "MISSING_FULFILLMENT_PROOF",
    "SCHEMA_INVALID",
)


class RetrievalRequest(TypedDict, total=False):
    """One retrieval task bound to one WorkUnit (PRD §10.4)."""

    case_id: int
    snapshot_hash: str
    work_unit_id: str
    query_variants: list[str]
    clause_types: list[str]
    source_quotas: dict[str, int]
    candidate_limit: int
    final_limit: int
    expand_parent_clause: bool
    expand_neighbors: bool
    search_attachments: bool
    require_counter_evidence: bool
    cache_policy: str


class EvidenceBundle(TypedDict):
    """Unified evidence result for one WorkUnit (PRD §10.5).

    Contract / policy / historical evidence stays in separate pools — they
    must not compete for one TopK during rerank (§12.4).
    """

    work_unit_id: str
    request_hash: str
    contract_evidence: list[dict]
    policy_evidence: list[dict]
    historical_evidence: list[dict]
    counter_evidence: list[dict]
    retrieval_stats: dict
    warnings: list[dict]


class CandidateResult(TypedDict):
    """Minimal shared shape of any analysis output (PRD §10.6)."""

    candidate_id: str
    work_unit_id: str
    result_type: str
    claim: str
    structured_value: dict
    contract_citation_ids: list[str]
    policy_citation_ids: list[str]
    confidence: float
    source: str
    uncertainty: list[str]


class ValidationOutcome(TypedDict):
    """One validated candidate (PRD §10.7)."""

    candidate_id: str
    verdict: str
    checks: list[dict]
    evidence_needs: list[EvidenceNeed]
    normalized_candidate: dict | None


# verdict vocabulary (PRD §10.7)
VERDICTS = (
    "PASS",
    "DOWNGRADE_CONFIDENCE",
    "NEED_MORE_EVIDENCE",
    "REJECT",
    "WAIT_HUMAN",
)

# Valid citation source-type prefixes shared with graph/nodes/validation.py.
VALID_CITATION_PREFIXES = (
    "CONTRACT_CLAUSE:", "KB_CHUNK:", "KB_DOCUMENT:",
    "STANDARD_CLAUSE:", "FULFILLMENT_DOCUMENT:",
)

# Negative-claim surface markers (a candidate whose claim contains any of
# these must pass the negative-conclusion minimum retrieval bar).
NEGATIVE_CLAIM_MARKERS = ("未约定", "未发现", "未约定且未检索到", "缺少", "不存在", "无相关条款", "未明确")


def default_retrieval_request(
    case_id: int,
    snapshot: dict[str, Any],
    work_unit_id: str,
    query_variants: list[str],
    *,
    clause_types: list[str] | None = None,
    source_quotas: dict[str, int] | None = None,
    final_limit: int = 8,
    require_counter_evidence: bool = False,
) -> RetrievalRequest:
    """Build a RetrievalRequest with the orchestrator's default quotas."""
    return {
        "case_id": int(case_id),
        "snapshot_hash": str(snapshot.get("snapshot_hash") or snapshot.get("snapshotHash") or ""),
        "work_unit_id": str(work_unit_id),
        "query_variants": [str(value) for value in query_variants if str(value).strip()],
        "clause_types": [str(value).upper() for value in (clause_types or [])],
        "source_quotas": {
            "contract": 8, "clause_type": 8, "policy": 8, "historical": 3,
            **(source_quotas or {}),
        },
        "candidate_limit": 30,
        "final_limit": int(final_limit),
        "expand_parent_clause": True,
        "expand_neighbors": False,
        "search_attachments": False,
        "require_counter_evidence": bool(require_counter_evidence),
        "cache_policy": "NONE",  # caching is owned by PRD Phase 9
    }


@dataclass(frozen=True)
class Role:
    """One PRD §6.1 role hook — an ordered chain of named node functions
    that implements one skeleton stage (§4.2) for this task.

    A role may span several graph nodes when the business graph splits its
    skeleton stage into multiple nodes (risk v1's analyzer =
    run_deterministic_rules + draft_domain_findings; its composer =
    compose_report + compose_limited_report + validate_schema +
    repair_artifact). The stage order inside a role is declaration order;
    the wiring between them is fully explicit via TaskSpec.edges /
    conditional_routes, never inferred.

    §6.1 names the role hooks by their policy type — WorkUnitPlanner,
    RetrievalPolicy, UnitAnalyzer, ArtifactValidator, CoverageAuditor,
    ArtifactComposer, PersistencePolicy — all of which are state→update
    node chains in this implementation.
    """

    stages: tuple[tuple[str, Callable], ...] = ()


@dataclass(frozen=True)
class HumanGate:
    """PRD §6.1 — the single stage allowed to pause a run for human input
    (a LangGraph interrupt inside the node). The role hooks declare the gate
    as the node function for ``stage`` (the builder validates that identity
    and wires it like any other stage); the spec's edges / conditional
    routes decide where the gate sits in the wiring."""

    stage: str

    def __call__(self, state: dict[str, Any]) -> dict[str, Any]:  # pragma: no cover
        raise NotImplementedError("HumanGate must be implemented by the business graph")


@dataclass
class TaskSpec:
    """Declarative description of one task graph (PRD Phase 4 / §6.1).

    The spec declares how a task differs from the shared lifecycle through
    the §6.1 role hooks plus the explicit wiring (edges / conditional
    routes). ``harness.graph_builder.build_task_graph`` turns a spec into a
    compiled LangGraph — business modules declare a spec instead of
    re-implementing that wiring.

    The spec holds no contract content and no DB / LLM clients: the node
    functions it references do the work, and they come from the business
    module (``graph/*.py``), never from the harness.

    Field contract:

    * ``context`` — the shared lifecycle base (§4.2 load_snapshot +
      build_task_context): risk v1 = load_run_context + freeze_case_snapshot.
    * ``planner`` / ``retriever`` / ``analyzer`` / ``validator`` /
      ``coverage_auditor`` / ``composer`` / ``persistence`` — the §6.1
      role hooks. Every role stage must have a unique name (roles
      partition the stage space); the builder rejects collisions.
    * ``human_gate`` — optional interrupt stage; when declared, its stage
      must be one of the role stages and the builder registers the gate
      function as that stage's node.
    * ``edges`` — explicit linear / loop-back edges, excluding START / END
      and the implicit context chain (START → context… → first role stage
      and the last stage → END are wired by the builder).
    * ``conditional_routes`` — stage name → (router, route_map). The route
      targets must be declared stages.

    ``stages`` and ``nodes`` are derived properties: the stage sequence is
    the §6.1 field order flattened, so the role contract is the single
    source of truth — not a comment.
    """

    task_type: str
    graph_name: str
    graph_version: str
    prompt_version: str
    context: Role
    planner: Role
    retriever: Role
    analyzer: Role
    validator: Role
    coverage_auditor: Role
    composer: Role
    persistence: Role
    human_gate: HumanGate | None = None
    edges: tuple[tuple[str, str], ...] = ()
    conditional_routes: Mapping[str, tuple[Callable, Mapping[str, str]]] = field(default_factory=dict)

    @property
    def stages(self) -> tuple[str, ...]:
        """Node names in lifecycle order (§6.1 field order flattened)."""
        roles = (
            self.context, self.planner, self.retriever, self.analyzer,
            self.validator, self.coverage_auditor, self.composer, self.persistence,
        )
        return tuple(name for role in roles for name, _fn in role.stages)

    @property
    def nodes(self) -> dict[str, Callable]:
        """Stage name → node function (derived from the role declaration)."""
        roles = (
            self.context, self.planner, self.retriever, self.analyzer,
            self.validator, self.coverage_auditor, self.composer, self.persistence,
        )
        return {name: fn for role in roles for name, fn in role.stages}
