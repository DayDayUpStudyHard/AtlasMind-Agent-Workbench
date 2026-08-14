"""GroundingValidator — deterministic grounding checks shared by fixed graphs (PRD §11.3).

Phase 2 scope (the user's five mandatory checks):

1. citation exists — ids non-empty, valid prefixes, ids present in the bundle;
2. citation from current snapshot — contract citations must point at the
   snapshot's document and a clause in its catalog;
3. claim supported — cited text really supports the claim (reuses
   ``agent_runtime/evidence.py:citation_support``);
4. amount / date / party consistency — structured values must not contradict
   the confirmed intake fields or the extraction snapshot elements;
5. negative-conclusion minimum retrieval bar — "未约定"-type claims are only
   acceptable when the retrieval round actually searched the relevant pools
   and counter evidence was attempted.

Business artifact assembly, risk scoring and fulfillment persistence stay out.
The v1 review graph keeps its own tuned 10-check node until Phase 3's v2 graph
switches to this validator.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from .models import (
    EvidenceBundle,
    NEGATIVE_CLAIM_MARKERS,
    VALID_CITATION_PREFIXES,
    CandidateResult,
    EvidenceNeed,
    ValidationOutcome,
)

logger = logging.getLogger(__name__)

DEFAULT_POLICY = {
    # negative-conclusion minimum retrieval bar
    "min_negative_contract_evidence": 5,
    "negative_requires_counter_search": True,
    # value-consistency conflicts with CONFIRMED intake are fatal
    "confirmed_intake_conflict": "REJECT",
    # schema key of the expected output, when work units declare one
    "expected_output_schema": None,
}

_POLICY_KEYS = (
    "confirmed_intake_conflict", "expected_output_schema",
    "min_negative_contract_evidence", "negative_requires_counter_search",
)

# structured_value keys compared against snapshot intake/extraction values
_MONEY_KEYS = ("amount", "total_amount", "totalAmount", "currency")
_DATE_KEYS = ("effective_date", "effectiveDate", "expiry_date", "expiryDate", "signed_date", "signedDate")
_PARTY_KEYS = ("party_a", "partyA", "party_b", "partyB", "counterparty", "our_entity", "ourEntity")

_MONEY_RE = re.compile(r"[\d][\d,.]*")
_DATE_RE = re.compile(r"\d{4}[-/年.]\d{1,2}([-/月.]\d{1,2}日?)?")


class GroundingValidator:
    """Deterministic grounding gate for candidate results (PRD §11.3)."""

    def __init__(self, *, policy: dict[str, Any] | None = None) -> None:
        self._policy = {**DEFAULT_POLICY, **(policy or {})}
        unknown = set(self._policy) - set(DEFAULT_POLICY)
        if unknown:
            logger.warning("GroundingValidator policy keys ignored: %s", sorted(unknown))

    def validate(
        self,
        candidates: list[dict[str, Any]],
        bundle: EvidenceBundle,
        snapshot: dict[str, Any],
        *,
        policy: dict[str, Any] | None = None,
    ) -> list[ValidationOutcome]:
        active_policy = {**self._policy, **({key: value for key, value in (policy or {}).items() if key in _POLICY_KEYS})}
        evidence_by_id = self._evidence_index(bundle)
        outcomes: list[ValidationOutcome] = []
        for candidate in candidates:
            outcomes.append(self._validate_one(
                dict(candidate), bundle, snapshot, evidence_by_id, active_policy,
            ))
        return outcomes

    # ── internals ──

    @staticmethod
    def _evidence_index(bundle: EvidenceBundle) -> dict[str, dict]:
        index: dict[str, dict] = {}
        for pool in (
            "contract_evidence", "policy_evidence",
            "historical_evidence", "counter_evidence",
        ):
            for item in bundle.get(pool) or []:
                source_id = str(item.get("sourceId") or "")
                if source_id:
                    index.setdefault(source_id, item)
        return index

    def _validate_one(
        self,
        candidate: dict[str, Any],
        bundle: EvidenceBundle,
        snapshot: dict[str, Any],
        evidence_by_id: dict[str, dict],
        policy: dict[str, Any],
    ) -> ValidationOutcome:
        checks: list[dict] = []
        needs: list[EvidenceNeed] = []
        fatal = False
        downgrade = False
        needs_more = False

        contract_ids = [str(value) for value in (candidate.get("contract_citation_ids") or candidate.get("contractCitationIds") or [])]
        policy_ids = [str(value) for value in (candidate.get("policy_citation_ids") or candidate.get("policyCitationIds") or [])]
        all_ids = contract_ids + policy_ids
        work_unit_id = str(candidate.get("work_unit_id") or bundle.get("work_unit_id") or "")
        candidate_id = str(candidate.get("candidate_id") or candidate.get("findingKey") or candidate.get("title") or f"candidate-{len(checks)}")

        # ── 1. citation exists ──
        if not all_ids:
            checks.append({"check": "CITATION_EXISTS", "ok": False, "detail": "no citation ids"})
            needs.append(self._need(work_unit_id, "NO_CONTRACT_EVIDENCE", "候选没有任何证据引用", retryable=True))
            fatal = True
        else:
            for cid in all_ids:
                if not cid.startswith(VALID_CITATION_PREFIXES):
                    checks.append({"check": "CITATION_EXISTS", "ok": False, "detail": f"missing source prefix: {cid}"})
                    fatal = True
                elif cid not in evidence_by_id:
                    checks.append({"check": "CITATION_EXISTS", "ok": False, "detail": f"citation not in bundle: {cid}"})
                    needs.append(self._need(work_unit_id, "UNSUPPORTED_CLAIM", f"引用 {cid} 不在本次检索结果中", retryable=True))
                    fatal = True

        # ── 2. citation from current snapshot ──
        snapshot_doc = int(snapshot.get("document_id") or snapshot.get("currentDocument", {}).get("id") or 0)
        catalog_ids = {
            str(item.get("clauseId") or "")
            for item in (snapshot.get("clause_catalog") or snapshot.get("clauseCatalog") or [])
        }
        for cid in contract_ids:
            item = evidence_by_id.get(cid)
            if not item:
                continue
            if item.get("documentId") and snapshot_doc and int(item.get("documentId")) != snapshot_doc:
                checks.append({
                    "check": "CITATION_FROM_SNAPSHOT", "ok": False,
                    "detail": f"{cid} belongs to document {item.get('documentId')}, snapshot is {snapshot_doc}",
                })
                needs.append(self._need(
                    work_unit_id, "UNSUPPORTED_CLAIM",
                    f"引用 {cid} 来自文档版本 {item.get('documentId')}，与当前快照 {snapshot_doc} 不一致",
                    retryable=False,
                ))
                fatal = True
            elif cid.startswith("CONTRACT_CLAUSE:") and catalog_ids:
                raw = cid.split(":", 1)[1] if ":" in cid else cid
                clause_id = str(item.get("clauseId") or raw)
                if clause_id not in catalog_ids:
                    checks.append({
                        "check": "CITATION_FROM_SNAPSHOT", "ok": False,
                        "detail": f"{cid} not in snapshot clause catalog",
                    })
                    needs.append(self._need(
                        work_unit_id, "UNSUPPORTED_CLAIM",
                        f"引用 {cid} 不在当前快照条款目录中",
                        retryable=False,
                    ))
                    fatal = True

        # ── 3. claim supported ──
        try:
            from ..evidence import citation_support

            supported = True
            for index, cid in enumerate(all_ids):
                result = citation_support(cid, None, evidence_by_id)
                checks.append({"check": "CLAIM_SUPPORTED", "citationId": cid, **result})
                if not result.get("supported"):
                    supported = False
                    needs.append(self._need(
                        work_unit_id, "UNSUPPORTED_CLAIM",
                        f"引用 {cid} 无法被原文支持: {'; '.join(result.get('reasons') or [])}",
                        retryable=True,
                    ))
            if not supported:
                downgrade = True
        except Exception as exc:  # validator itself must not crash the graph
            logger.warning("citation_support unavailable: %s", exc)
            checks.append({"check": "CLAIM_SUPPORTED", "ok": False, "detail": f"validator unavailable: {exc}"})
            downgrade = True

        # ── 4. amount / date / party consistency ──
        consistency_checks, consistency_needs = self._value_consistency(
            candidate, snapshot, work_unit_id, policy,
        )
        checks.extend(consistency_checks)
        needs.extend(consistency_needs)
        for check in consistency_checks:
            if check.get("verdict") == "fatal":
                fatal = True
            elif check.get("verdict") == "downgrade":
                downgrade = True

        # ── 5. negative-conclusion minimum retrieval bar ──
        claim = str(candidate.get("claim") or candidate.get("description") or candidate.get("title") or "")
        negative = bool(candidate.get("negative_claim")) or any(
            marker in claim for marker in NEGATIVE_CLAIM_MARKERS
        )
        if negative:
            contract_count = len(bundle.get("contract_evidence") or [])
            minimum = int(policy.get("min_negative_contract_evidence") or 5)
            counter_searched = bool(
                (bundle.get("retrieval_stats") or {}).get("counterQueryCount")
                or (bundle.get("counter_evidence") or [])
            )
            if contract_count < minimum:
                checks.append({
                    "check": "NEGATIVE_CLAIM_BAR", "ok": False,
                    "detail": f"negative claim with only {contract_count} contract hits (minimum {minimum})",
                    "verdict": "needs_more",
                })
                needs.append(self._need(
                    work_unit_id, "NEGATIVE_CLAIM_NOT_PROVEN",
                    f"负向结论需要至少 {minimum} 条合同证据支撑，当前仅 {contract_count} 条",
                    retryable=True,
                    must_expand_neighbors=True,
                ))
                needs_more = True
            if policy.get("negative_requires_counter_search") and not counter_searched:
                checks.append({
                    "check": "NEGATIVE_CLAIM_BAR", "ok": False,
                    "detail": "negative claim without counter-evidence search",
                    "verdict": "needs_more",
                })
                needs.append(self._need(
                    work_unit_id, "POSSIBLE_COUNTER_EVIDENCE",
                    "负向结论必须经过反证检索（除外/但书/限制/豁免）",
                    retryable=True,
                    must_expand_neighbors=True,
                ))
                needs_more = True
        else:
            checks.append({"check": "NEGATIVE_CLAIM_BAR", "ok": True, "detail": "not a negative claim"})

        # ── verdict ──
        if fatal:
            verdict = "REJECT"
        elif needs_more:
            verdict = "NEED_MORE_EVIDENCE"
        elif downgrade:
            verdict = "DOWNGRADE_CONFIDENCE"
        elif any(not check.get("ok") for check in checks if check.get("verdict") == "warn"):
            verdict = "DOWNGRADE_CONFIDENCE"
        else:
            verdict = "PASS"

        return ValidationOutcome(
            candidate_id=candidate_id,
            verdict=verdict,
            checks=checks,
            evidence_needs=needs,
            normalized_candidate=None if verdict == "REJECT" else dict(candidate),
        )

    def _value_consistency(
        self,
        candidate: dict[str, Any],
        snapshot: dict[str, Any],
        work_unit_id: str,
        policy: dict[str, Any],
    ) -> tuple[list[dict], list[EvidenceNeed]]:
        """Deterministic amount/date/party comparison against confirmed facts.

        CONFIRMED intake / extraction values are the ground truth; a candidate
        that contradicts them is rejected or downgraded, never silently kept.
        """
        structured = candidate.get("structured_value") or {}
        if not isinstance(structured, dict) or not structured:
            return [], []
        confirmed = self._confirmed_values(snapshot)
        checks: list[dict] = []
        needs: list[EvidenceNeed] = []
        for key, candidate_value in structured.items():
            expected = confirmed.get(key)
            if expected is None or candidate_value in (None, ""):
                continue
            if self._values_conflict(key, candidate_value, expected):
                conflict_verdict = str(policy.get("confirmed_intake_conflict") or "REJECT")
                verdict = "fatal" if conflict_verdict == "REJECT" else "downgrade"
                detail = f"{key}: candidate {candidate_value!r} conflicts with confirmed {expected!r}"
                checks.append({"check": "VALUE_CONSISTENCY", "ok": False, "detail": detail, "verdict": verdict})
                reason = "CONFLICTING_VALUES"
                needs.append(self._need(
                    work_unit_id, reason,
                    f"候选值 {candidate_value} 与已确认值 {expected} 冲突（字段 {key}）",
                    retryable=False,
                ))
            else:
                checks.append({"check": "VALUE_CONSISTENCY", "ok": True, "detail": f"{key} matches confirmed value"})
        return checks, needs

    @staticmethod
    def _confirmed_values(snapshot: dict[str, Any]) -> dict[str, Any]:
        """Flatten confirmed intake fields + extraction elements into {key: value}."""
        values: dict[str, Any] = {}
        intake = snapshot.get("confirmed_intake_fields") or snapshot.get("confirmedIntake") or {}
        fields = intake.get("fields") if isinstance(intake, dict) else None
        if isinstance(fields, dict):
            values.update(fields)
        for element in (snapshot.get("latest_confirmed_extraction_snapshot") or {}).get("elements") or []:
            if str(element.get("status") or "").upper() not in ("CONFIRMED", "READY"):
                continue
            key = str(element.get("elementKey") or "")
            if not key:
                continue
            normalized = element.get("normalizedValue")
            if isinstance(normalized, dict) and "value" in normalized:
                values[key] = normalized["value"]
            elif normalized:
                values[key] = normalized
        return values

    def _values_conflict(self, key: str, candidate_value: Any, expected: Any) -> bool:
        key_str = str(key)
        if key_str in _PARTY_KEYS or "party" in key_str.lower():
            return self._party_conflict(candidate_value, expected)
        if key_str in _DATE_KEYS or "date" in key_str.lower():
            return self._date_conflict(candidate_value, expected)
        if key_str in _MONEY_KEYS or "amount" in key_str.lower() or "currency" in key_str.lower():
            return self._money_conflict(candidate_value, expected)
        return str(candidate_value).strip().lower() != str(expected).strip().lower()

    @staticmethod
    def _money_conflict(candidate: Any, expected: Any) -> bool:
        candidate_number = _first_number(candidate)
        expected_number = _first_number(expected)
        if candidate_number is None or expected_number is None:
            return str(candidate).strip().lower() != str(expected).strip().lower()
        # >2% relative difference = conflict (rounding tolerance)
        return abs(candidate_number - expected_number) > max(0.01, expected_number * 0.02)

    @staticmethod
    def _date_conflict(candidate: Any, expected: Any) -> bool:
        candidate_date = _first_date(candidate)
        expected_date = _first_date(expected)
        if candidate_date is None or expected_date is None:
            return str(candidate).strip().lower() != str(expected).strip().lower()
        return candidate_date != expected_date

    @staticmethod
    def _party_conflict(candidate: Any, expected: Any) -> bool:
        candidate_names = _normalized_names(candidate)
        expected_names = _normalized_names(expected)
        if not candidate_names or not expected_names:
            return str(candidate).strip().lower() != str(expected).strip().lower()
        # Conflict only when BOTH sides name exactly one party and they differ.
        return (
            len(candidate_names) == 1 and len(expected_names) == 1
            and candidate_names != expected_names
        )

    @staticmethod
    def _need(
        work_unit_id: str,
        reason_code: str,
        description: str,
        *,
        retryable: bool,
        must_expand_neighbors: bool = False,
    ) -> EvidenceNeed:
        return EvidenceNeed(
            need_id=f"need-{work_unit_id}-{reason_code}",
            work_unit_id=work_unit_id,
            reason_code=reason_code,
            description=description[:300],
            missing_source_types=[],
            missing_fields=[],
            query_hints=[],
            clause_type_hints=[],
            must_expand_neighbors=must_expand_neighbors,
            must_search_attachments=False,
            retryable=retryable,
        )


def _first_number(value: Any) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)
    match = _MONEY_RE.search(str(value))
    if not match:
        return None
    try:
        return float(match.group(0).replace(",", ""))
    except ValueError:
        return None


def _first_date(value: Any) -> tuple[str, str, str] | None:
    match = _DATE_RE.search(str(value))
    if not match:
        return None
    text = match.group(0)
    parts = re.split(r"[-/年.月日]", text)
    parts = [part for part in parts if part]
    year = parts[0] if len(parts) > 0 else ""
    month = parts[1] if len(parts) > 1 else ""
    day = parts[2] if len(parts) > 2 else ""
    return (year, month, day)


def _normalized_names(value: Any) -> set[str]:
    """Extract normalized party names from dict/list/scalar candidates."""
    if isinstance(value, dict):
        texts = [
            str(value.get(key) or "") for key in ("name", "entityName", "partyName", "value")
            if value.get(key)
        ]
    elif isinstance(value, list):
        texts = [str(item) for item in value]
    else:
        texts = [str(value)]
    normalized: set[str] = set()
    for text in texts:
        compact = re.sub(r"\s+", "", text).strip(" ()（）")
        if compact:
            normalized.add(compact)
    return normalized


# Module-level shared validator (graphs may also construct their own with a
# tuned policy — the default is the common grounding gate).
_default_validator = GroundingValidator()


def get_validator() -> GroundingValidator:
    return _default_validator
