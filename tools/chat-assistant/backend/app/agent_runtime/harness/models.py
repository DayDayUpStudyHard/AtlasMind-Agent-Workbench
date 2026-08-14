"""Core domain models for the common evidence harness (PRD §10).

TypedDicts only — no runtime dependency on the DB, LLM or graph layers, so
they can be imported by graph nodes, harness modules and tests alike.

TaskSpec is deliberately absent: PRD §10.8 says the first stage must NOT
freeze a full TaskSpec before the common modules prove stable (Phase 4).
"""

from __future__ import annotations

from typing import Any, TypedDict


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
