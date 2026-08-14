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


# ── State ledger (PRD §7.2 production metering) ──────────────────────────────


def record_unit_usage(
    usage: dict[str, dict[str, int]],
    work_unit_id: str,
    *,
    queries: int = 0,
    llm_calls: int = 0,
    tokens: int = 0,
    retry_rounds: int = 0,
) -> None:
    """Accumulate one WorkUnit's spend in the shared state ledger.

    Business nodes call this in place on ``state["work_unit_usage"]`` — the
    dict is mutated, not replaced, so concurrent accumulations across nodes
    survive the graph-state overwrite reducer. Ledger keys mirror the §6.2
    budget shape.
    """
    unit = usage.setdefault(work_unit_id, {})
    unit["queries"] = int(unit.get("queries") or 0) + int(queries)
    unit["llmCalls"] = int(unit.get("llmCalls") or 0) + int(llm_calls)
    unit["tokens"] = int(unit.get("tokens") or 0) + int(tokens)
    unit["retryRounds"] = int(unit.get("retryRounds") or 0) + int(retry_rounds)


def unit_usage_from_ledger(
    usage: dict[str, dict[str, int]], work_unit_id: str
) -> UnitUsage:
    """Read one WorkUnit's accumulated ledger entry back as a UnitUsage."""
    unit = usage.get(work_unit_id) or {}
    return UnitUsage(
        queries=int(unit.get("queries") or 0),
        llm_calls=int(unit.get("llmCalls") or 0),
        tokens=int(unit.get("tokens") or 0),
        retry_rounds=int(unit.get("retryRounds") or 0),
    )


def audit_work_unit_budgets(
    usage: dict[str, dict[str, int]],
    *,
    budgets: dict[str, WorkUnitBudget] | None = None,
    missing_check_items: dict[str, tuple[str, ...]] | None = None,
    missing_source_types: dict[str, tuple[str, ...]] | None = None,
) -> list[dict[str, Any]]:
    """§7.2 audit over the whole ledger: every WorkUnit with accumulated
    spend is checked against its budget (the conservative default, or a
    per-unit tightening via ``budgets``). Returns one §6.4 diagnostics dict
    per over-budget unit, sorted by workUnitId. A unit is ``retried`` when
    its ledger shows at least one retry round."""
    if not usage:
        return []
    diagnostics: list[dict[str, Any]] = []
    for unit_id in sorted(usage):
        unit_budget = (budgets or {}).get(unit_id) or WorkUnitBudget()
        verdict = check_work_unit_budget(
            unit_budget,
            unit_usage_from_ledger(usage, unit_id),
            work_unit_id=unit_id,
            missing_check_items=(missing_check_items or {}).get(unit_id, ()),
            missing_source_types=(missing_source_types or {}).get(unit_id, ()),
            retried=unit_usage_from_ledger(usage, unit_id).retry_rounds > 0,
        )
        if not verdict.within_budget:
            unit_diagnostics = dict(verdict.diagnostics)
            unit_diagnostics["reasons"] = ["BUDGET"]
            diagnostics.append(unit_diagnostics)
    return diagnostics


def coverage_limited_diagnostics(
    *,
    work_unit_id: str,
    missing_check_items: tuple[str, ...] = (),
    missing_source_types: tuple[str, ...] = (),
    retried: bool = False,
) -> dict[str, Any]:
    """§6.4 disclosure for a coverage-limited run: the scope was cut by the
    quality gate, not by per-unit spend. ``reasons`` tags the source so the
    route layer can tell coverage-limited from budget-limited."""
    diagnostics = build_limited_diagnostics(
        work_unit_id=work_unit_id,
        missing_check_items=missing_check_items,
        missing_source_types=missing_source_types,
        retried=retried,
    )
    diagnostics["reasons"] = ["COVERAGE"]
    return diagnostics


def merge_limited_diagnostics(
    base: dict[str, Any] | None,
    budget_units: list[dict[str, Any]],
) -> dict[str, Any] | None:
    """Merge the coverage source (``base``) with per-unit budget audit
    results into the canonical run-level diagnostics: the §6.4 keys are
    unioned at the top level (what the runtime / route layer / UI read),
    ``reasons`` carries the union of the sources' own reason tags, and
    ``workUnits`` carries the per-unit detail. Idempotent — the schema
    gate audits on every pass, and each source declares its own reasons."""
    if not base and not budget_units:
        return None
    merged = dict(base or {})
    merged["missingCheckItems"] = sorted({
        *(merged.get("missingCheckItems") or []),
        *(item for unit in budget_units for item in unit.get("missingCheckItems") or []),
    })
    merged["missingSourceTypes"] = sorted({
        *(merged.get("missingSourceTypes") or []),
        *(item for unit in budget_units for item in unit.get("missingSourceTypes") or []),
    })
    merged["retried"] = bool(merged.get("retried")) or any(
        unit.get("retried") for unit in budget_units
    )
    merged["exceeded"] = sorted({
        *(merged.get("exceeded") or []),
        *(item for unit in budget_units for item in unit.get("exceeded") or []),
    })
    reasons = list(merged.get("reasons") or [])
    for unit in budget_units:
        reasons.extend(unit.get("reasons") or [])
    merged["reasons"] = list(dict.fromkeys(reasons))
    merged["workUnits"] = budget_units
    return merged
