"""Per-WorkUnit budgets and LIMITED diagnostics (PRD §7.2 / §6.4).

The shared budget contract: one WorkUnit is one bounded analysis unit, and
its budget travels with it (PRD §6.2 ``budget`` field). Enforcing budgets
inside business nodes is the caller's job — this module is the single
implementation of the limits, the verdict and the diagnostics, so every
graph reports an over-budget WorkUnit the same way.

LIMITED diagnostics carry the §6.4 mandatory disclosure: which WorkUnits /
checklist items / evidence source types are missing and whether a targeted
retry was executed. Infrastructural failure must never be dressed up as
business "no evidence" — that is exactly what these diagnostics record.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class WorkUnitBudget:
    """§7.2 conservative production defaults for one WorkUnit.

    PRD §6.2 shows ``budget: {"maxQueries": 2, "maxRetryRounds": 1}`` as the
    shape; LLM-call and token caps complete the same unit scope. A task may
    tighten these per spec — never loosen them silently.
    """

    max_queries: int = 2
    max_llm_calls: int = 3
    max_tokens: int = 16384
    max_retry_rounds: int = 1


@dataclass(frozen=True)
class UnitUsage:
    """Accumulated spend of one WorkUnit during this run."""

    queries: int = 0
    llm_calls: int = 0
    tokens: int = 0
    retry_rounds: int = 0


@dataclass(frozen=True)
class BudgetVerdict:
    """Outcome of checking a WorkUnit against its budget."""

    within_budget: bool
    exceeded: tuple[str, ...] = ()
    diagnostics: dict[str, Any] = field(default_factory=dict)


def check_work_unit_budget(
    budget: WorkUnitBudget,
    usage: UnitUsage,
    *,
    work_unit_id: str,
    missing_check_items: tuple[str, ...] = (),
    missing_source_types: tuple[str, ...] = (),
    retried: bool = False,
) -> BudgetVerdict:
    """Verdict + §6.4 LIMITED diagnostics for one WorkUnit.

    ``missing_check_items`` / ``missing_source_types`` / ``retried`` are
    filled in by the caller (validation / coverage audit know what is
    missing); the budget module only owns the limit comparison.
    """
    exceeded: list[str] = []
    if usage.queries > budget.max_queries:
        exceeded.append("maxQueries")
    if usage.llm_calls > budget.max_llm_calls:
        exceeded.append("maxLlmCalls")
    if usage.tokens > budget.max_tokens:
        exceeded.append("maxTokens")
    if usage.retry_rounds > budget.max_retry_rounds:
        exceeded.append("maxRetryRounds")

    if not exceeded:
        return BudgetVerdict(within_budget=True)

    diagnostics = build_limited_diagnostics(
        work_unit_id=work_unit_id,
        missing_check_items=missing_check_items,
        missing_source_types=missing_source_types,
        retried=retried,
        exceeded=tuple(exceeded),
    )
    return BudgetVerdict(within_budget=False, exceeded=tuple(exceeded), diagnostics=diagnostics)


def build_limited_diagnostics(
    *,
    work_unit_id: str,
    missing_check_items: tuple[str, ...] = (),
    missing_source_types: tuple[str, ...] = (),
    retried: bool = False,
    exceeded: tuple[str, ...] = (),
) -> dict[str, Any]:
    """§6.4 disclosure for a LIMITED WorkUnit — stable shape for the UI /
    eval center to render."""
    return {
        "workUnitId": work_unit_id,
        "missingCheckItems": sorted(set(missing_check_items)),
        "missingSourceTypes": sorted(set(missing_source_types)),
        "retried": bool(retried),
        "exceeded": list(exceeded),
    }
