"""Common evidence harness — the shared spine for contract graphs.

PRD (contract-agent-harness-v1-migration, 2026-08-14) Phase 4 / §14-4: the
harness is extracted from risk v1 and stays the single implementation of
shared lifecycle pieces, without changing v1 output fields.

* ``models``       — WorkUnit / EvidenceNeed / RetrievalRequest / EvidenceBundle /
                     CandidateResult / ValidationOutcome (PRD §10) and
                     TaskSpec with the §6.1 role hooks (Role / HumanGate,
                     Phase 4) — ``stages`` / ``nodes`` derive from the roles
* ``graph_builder``— build_task_graph: compiles a TaskSpec into a LangGraph
                     (PRD §4.2 lifecycle skeleton + spec-declared routing +
                     reachability validation)
* ``budget``       — WorkUnitBudget / UnitUsage / check_work_unit_budget +
                     LIMITED diagnostics (PRD §7.2 / §6.4)
* ``retrieval``    — RetrievalOrchestrator (PRD §11.2) — risk v1, 要素提取 and
                     review v2 all retrieve through this; v1 nodes re-import
                     the public ``run_async`` / ``normalize_hit`` /
                     ``dedupe_pool`` (underscore aliases exist only for
                     pre-publicization internal callers)
* ``validation``   — GroundingValidator (PRD §11.3) — used by 要素提取 / review v2
* ``observation``  — ObservabilityRecorder (PRD §11.6, minimal dict form)
* ``fakes``        — fake adapters / reranker / snapshot for pure unit tests

Deliberately NOT in the harness (v1-local business behavior — moving them
would change risk v1 output fields, which Phase 4 forbids):

* ``validate_claims`` / ``_validate_one`` (10-check gate, REJECT_FINDING
  vocabulary, findingKey dedup-merge, severity gate, document-quality
  downgrade) — a different gate from GroundingValidator; the harness one
  would flip unsupported-citation REJECT → downgrade and lose six checks
* ``draft_domain_findings`` + finding normalization (``_normalize_finding`` /
  ``_fallback_rule_findings``) — shared with review v2 but v1-semantics-bound
* ``run_deterministic_rules`` / ``retrieve_fulfillment_evidence``
* dead legacy ``_retrieve_one_domain`` / ``_load_type_clauses`` (kept per
  project rule: legacy code is not deleted)
* ``contract_extraction.py:_run_async`` — a third copy that lacks the
  contextvars wrapper (re-pointing it is a Phase 5 item, not a zero-change
  alias)

TaskSpec with the §6.1 role hooks, the common graph builder and the
per-WorkUnit budget contract are in the harness (Phase 4 / §14-4); business
artifact composition, risk scoring, date calculation and fulfillment
persistence stay OUT until the interfaces prove stable across the graphs
(PRD §14.4).
"""

from .budget import (  # noqa: F401
    BudgetVerdict,
    UnitUsage,
    WorkUnitBudget,
    build_limited_diagnostics,
    check_work_unit_budget,
)
from .graph_builder import build_task_graph  # noqa: F401
from .models import (  # noqa: F401
    CandidateResult,
    EvidenceBundle,
    EvidenceNeed,
    HumanGate,
    RetrievalRequest,
    Role,
    TaskSpec,
    ValidationOutcome,
    WorkUnit,
)
from .retrieval import (  # noqa: F401
    RetrievalOrchestrator,
    dedupe_pool,
    get_orchestrator,
    normalize_hit,
    run_async,
)
from .validation import GroundingValidator  # noqa: F401
