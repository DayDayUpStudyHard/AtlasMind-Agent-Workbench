"""LangGraph contract fact extraction.

The graph creates a reusable, versioned fact snapshot. It is intentionally
separate from risk review: parsing/indexing is shared, extraction is rerunnable,
and review consumes the latest confirmed facts plus the original clauses.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from decimal import Decimal, InvalidOperation
from typing import Any, Awaitable

from ..harness.models import Role, TaskSpec
from .element_normalization import validate_base_field, validate_structured_element
from .evidence_snapshot import load_contract_evidence_snapshot, state_copy_of_snapshot
from .versioning import stamp_artifact_versions

logger = logging.getLogger(__name__)

EXTRACTION_SCHEMA_VERSION = "contract-extraction-v2"
PROFILE_SCHEMA_VERSION = "contract-profile-v1"
EXTRACTION_PROMPT_VERSION = "contract-elements-v2-profile"
EXTRACTION_RETRIEVAL_VERSION = "contract-hybrid-retrieval-v2"
PARSER_VERSION = "document-parser-v2"

ELEMENT_PACKS: tuple[dict[str, Any], ...] = (
    {
        "packKey": "financial_terms",
        "packName": "金额、付款与税务",
        "elementKeys": ["payment_terms"],
        "queries": ["付款 支付 发票 税率 结算 付款条件 付款比例"],
    },
    {
        "packKey": "dates_obligations",
        "packName": "日期、期限与履约义务",
        "elementKeys": [
            "termination_conditions", "delivery_obligations",
            "acceptance_criteria", "required_materials",
        ],
        "queries": ["生效 有效期 到期 终止 结束 交付 服务 履约 验收 提交 材料 通知 期限"],
    },
    {
        "packKey": "risk_terms",
        "packName": "责任、知识产权与合规",
        "elementKeys": [
            "liability_terms", "ip_ownership", "confidentiality_terms",
            "data_protection_terms", "compliance_terms", "dispute_resolution", "notice_terms",
        ],
        "queries": ["违约 赔偿 责任上限 知识产权 著作权 保密 数据 个人信息 合规 争议 通知"],
    },
)

# Base identity element keys must never be re-extracted by LLM packs — they
# are deterministic by design (PRD Phase 5, task 1/3).
_BASE_IDENTITY_ELEMENT_KEYS = frozenset({
    "contract_title", "contract_type", "party_a", "party_b", "our_side",
    "contract_amount", "currency", "signed_date", "effective_date", "expiry_date",
})

# The fixed WorkUnit every extraction plan declares first (PRD Phase 5,
# task 1: 基础身份字段单独建立固定 WorkUnit). The unit is fully
# deterministic — no retrieval, no LLM — and its required checks name the
# dedicated normalizers in element_normalization.
_BASE_IDENTITY_WORK_UNIT: dict[str, Any] = {
    "work_unit_id": "base_identity_fields",
    "task_type": "CONTRACT_ELEMENT_EXTRACTION",
    "category": "BASE_IDENTITY",
    "label": "基础身份要素（确定性规范化）",
    "objective": "合同名称、类型、甲乙方、我方角色、金额、币种与签订/生效/到期日期的固定基础事实单元",
    "applicability": "ALWAYS",
    "priority": "CRITICAL",
    "query_intents": [],
    "required_clause_types": [],
    "required_source_types": ["CONFIRMED_INTAKE", "CONFIRMED_CASE"],
    "expected_output_schema": "canonical-base-field",
    "required_checks": [
        "deterministic_money_parse", "currency_enum", "calendar_date_valid",
        "party_name_nonempty", "title_nonempty", "our_side_allowlist",
    ],
    "negative_claim_allowed": False,
    "human_review_policy": "CONFIRMED_VALUES_ONLY",
}

_SNAPSHOT_STATUS_FINISHED = {"READY_FOR_CONFIRMATION", "CONFIRMED"}
_SETTLED_ELEMENT_STATUSES = {"EXTRACTED", "CONFIRMED"}
_SETTLED_CONFIDENCE = 0.75


def _run_async(awaitable: Awaitable[Any]) -> Any:
    """Run an async store call from a synchronous LangGraph node.

    PRD Phase 5: the local third copy converged to the shared harness
    implementation — the harness one wraps the thread-pool call in a
    ``contextvars.copy_context()`` so request-scoped context survives the
    executor hop. The legacy ``_retrieve_pack`` caller keeps this alias.
    """
    from ..harness.retrieval import run_async

    return run_async(awaitable)


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)


def _text_part(value: Any) -> str:
    if value is None or value == "":
        return ""
    if isinstance(value, dict):
        return _profile_display_value(value)
    if isinstance(value, list):
        return "；".join(filter(None, (_text_part(item) for item in value[:3])))
    return re.sub(r"\s+", " ", str(value)).strip()


def _profile_display_value(value: Any) -> str:
    if value is None or value == "":
        return ""
    if not isinstance(value, (dict, list)):
        return _text_part(value)
    if isinstance(value, list):
        return "；".join(filter(None, (_profile_display_value(item) for item in value[:3])))

    for key in ("displayValue", "summary", "value", "name", "fullName", "title"):
        text = _text_part(value.get(key))
        if text:
            return text[:1000]

    type_text = _text_part(value.get("type") or value.get("kind") or value.get("category"))
    condition = _text_part(value.get("condition") or value.get("trigger") or value.get("requirement"))
    timing = _text_part(value.get("timing") or value.get("deadline") or value.get("timeLimit") or value.get("period"))
    action = _text_part(value.get("action") or value.get("obligation") or value.get("task"))
    party = _text_part(value.get("party") or value.get("obligor") or value.get("responsibleParty"))
    amount = _text_part(value.get("amount"))
    currency = _text_part(value.get("currency"))
    cap = _text_part(value.get("cap") or value.get("limit"))
    note = _text_part(value.get("note") or value.get("remark") or value.get("comment"))
    if amount and not (condition or timing or action or note or cap):
        return f"{amount} {currency}".strip()[:1000]
    if condition or timing or action or note or cap:
        first = "，".join(part for part in (party, action or condition, f"{amount} {currency}".strip()) if part)
        tail = "；".join(part for part in (
            f"时限：{timing}" if timing else "",
            f"上限：{cap}" if cap else "",
            f"备注：{note}" if note else "",
        ) if part)
        return f"{type_text + '：' if type_text else ''}{'；'.join(part for part in (first, tail) if part)}"[:1000]

    materials = value.get("materials")
    if isinstance(materials, list) and materials:
        return ("应提交材料：" + "、".join(filter(None, (_text_part(item) for item in materials[:5]))))[:1000]

    parts = [_text_part(value.get(key)) for key in (
        "role", "address", "contact", "phone", "tel", "mobile", "bank", "account",
        "date", "startDate", "endDate", "effectiveCondition", "terminationCondition",
    )]
    return " · ".join(part for part in parts if part)[:1000]


def _clamp_confidence(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = default
    return round(max(0.0, min(1.0, number)), 4)


def _source_id(item: dict[str, Any]) -> str:
    raw = str(item.get("sourceId") or item.get("clauseId") or "").strip()
    if raw.startswith("CONTRACT_CLAUSE:"):
        return raw
    return f"CONTRACT_CLAUSE:{raw}" if raw else ""


def _compact_clause(item: dict[str, Any]) -> dict[str, Any]:
    source_id = _source_id(item)
    content = str(item.get("clauseText") or item.get("content") or "")
    snippet = str(item.get("snippet") or content[:320])
    return {
        **item,
        "sourceId": source_id,
        "clauseText": content[:9000],
        "content": content[:9000],
        "snippet": snippet[:1800],
        "pageNumber": item.get("pageNumber") or item.get("page"),
    }


def _citation_supported(citation: dict[str, Any], evidence_by_id: dict[str, dict[str, Any]]) -> bool:
    source_id = str(citation.get("sourceId") or "")
    quote = str(citation.get("quote") or "").strip()
    source = evidence_by_id.get(source_id)
    if not source or not quote:
        return False
    haystack = str(source.get("clauseText") or source.get("content") or source.get("snippet") or "")
    return quote in haystack


def _load_context(state: dict[str, Any]) -> dict[str, Any]:
    case_id = int(state.get("subject_id") or 0)
    task_input = state.get("task_input") or {}
    requested_document_id = int(task_input.get("documentId") or 0)
    shared_snapshot = load_contract_evidence_snapshot(
        case_id,
        requested_document_id=requested_document_id,
        include_content_text=True,
        clause_limit=240,
    )
    document = dict(shared_snapshot.get("currentDocument") or {})
    if str(document.get("parseStatus") or "").upper() != "READY":
        raise ValueError("Contract document is not ready for element extraction")
    document.pop("contentText", None)
    return {
        "case": shared_snapshot.get("case") or {},
        "document": document,
        "clauseCount": shared_snapshot.get("clauseCount") or 0,
        "clauses": shared_snapshot.get("clauses") or [],
        "clauseCatalog": shared_snapshot.get("clause_catalog") or [],
        "confirmedIntake": shared_snapshot.get("confirmed_intake_fields") or {},
        "contentHash": shared_snapshot.get("content_hash"),
        "documentQuality": shared_snapshot.get("quality_diagnostics") or {"parseQuality": document.get("parseQuality")},
        "evidenceSnapshotHash": shared_snapshot.get("snapshot_hash"),
        # Same unified view as the other three graphs (PRD Phase 1): the
        # extraction graph observes and records the identical snapshot.
        "evidenceSnapshot": state_copy_of_snapshot(shared_snapshot),
    }

def load_extraction_context(state: dict[str, Any]) -> dict[str, Any]:
    context = _load_context(state)
    run_id = state.get("run_id", 0)
    return {
        "state_revision": state.get("state_revision", 0) + 1,
        "current_node": "load_extraction_context",
        "extraction_context": context,
        "evidence_snapshot": context.get("evidenceSnapshot") or {},
        "observations": [{
            "callId": f"extraction-context-{run_id}",
            "planStepId": "load_document_snapshot",
            "toolName": "loadContractDocumentSnapshot",
            "arguments": {"caseId": state.get("subject_id"), "documentId": context["document"].get("id")},
            "output": {
                "documentVersion": context["document"].get("version"),
                "contentHash": context["contentHash"],
                "evidenceSnapshotHash": context.get("evidenceSnapshotHash"),
                "clauseCount": context["clauseCount"],
                "parseQuality": context["documentQuality"],
            },
            "status": "DONE",
        }],
    }


def _pack_key(value: Any) -> str:
    return re.sub(r"[^a-z0-9_]+", "_", str(value or "").strip().strip("_").lower())[:64]


def _normalize_planned_packs(raw: dict[str, Any]) -> list[dict[str, Any]] | None:
    """Validate an LLM-planned pack list (PRD Phase 5, task 2).

    Returns None when the plan is unusable — the caller falls back to the
    static packs instead of running a half-broken plan. Planned packs must
    not re-extract base identity keys (those are deterministic).
    """
    items = raw.get("packs") if isinstance(raw, dict) else None
    if not isinstance(items, list) or not 2 <= len(items) <= 6:
        return None
    result: list[dict[str, Any]] = []
    seen_pack_keys: set[str] = set()
    for item in items:
        if not isinstance(item, dict):
            continue
        key = _pack_key(item.get("packKey"))
        queries = [str(value).strip()[:120] for value in (item.get("queries") or []) if str(value).strip()][:6]
        element_keys = [
            _pack_key(value) for value in (item.get("elementKeys") or [])
            if _pack_key(value)
        ][:8]
        element_keys = [k for k in element_keys if k not in _BASE_IDENTITY_ELEMENT_KEYS]
        if not key or key in seen_pack_keys or not queries or not element_keys:
            continue
        seen_pack_keys.add(key)
        result.append({
            "packKey": key,
            "packName": str(item.get("packName") or key)[:256],
            "elementKeys": element_keys,
            "queries": queries,
        })
    return result if len(result) >= 2 else None


def _plan_element_packs(
    context: dict[str, Any],
    run_id: int,
    llm_service: Any | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Dynamic element-pack planning with the static packs as deterministic
    fallback (PRD Phase 5, task 2: 合同类型、标的和画像要素由 LLM 动态规划)."""
    from ...services.llm_service import LLMService

    if llm_service is None:
        llm_service = LLMService()
    case = context.get("case") or {}
    try:
        raw = llm_service.plan_contract_elements(
            case, context.get("clauses") or [], run_id
        )
        packs = _normalize_planned_packs(raw)
        if packs:
            return packs, {
                "source": "LLM_PLANNED",
                "contractTypeRefined": str(raw.get("contractTypeRefined") or case.get("contractType") or "OTHER")[:64],
                "subjectSummary": str(raw.get("subjectSummary") or "")[:1000],
                "rationale": str(raw.get("rationale") or "")[:1000],
            }
        logger.warning("LLM element plan was unusable; falling back to static packs")
    except Exception as exc:
        logger.warning("LLM element planning failed; falling back to static packs: %s", exc)
    return [dict(pack) for pack in ELEMENT_PACKS], {
        "source": "STATIC_FALLBACK",
        "contractTypeRefined": str(case.get("contractType") or "OTHER")[:64],
        "subjectSummary": "",
        "rationale": "静态要素包（模型规划不可用时的确定性回退）",
    }


def _previous_settled_elements(
    case_id: int, document_id: int,
) -> tuple[list[dict[str, Any]], int | None]:
    """Elements of the latest finished snapshot for this document.

    Settled = human-reviewed (review_status set) or EXTRACTED/CONFIRMED at
    confidence ≥ threshold. A field-level rerun carries these instead of
    re-extracting them (PRD Phase 5, tasks 5/6: 只重跑失败或低置信度字段，
    不静默覆盖人工确认值).
    """
    from ..persistence import _conn, _normalize_value

    if not document_id:
        return [], None
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT s.id AS snapshotId,
                          e.id, e.element_key AS elementKey, e.category,
                          e.value_type AS valueType, e.raw_value AS rawValue,
                          e.normalized_value_json AS normalizedValue,
                          e.status, e.confidence, e.source, e.applicable,
                          e.occurrence_no AS occurrenceNo,
                          e.validation_json AS validation,
                          e.manual_override AS manualOverride,
                          e.review_status AS reviewStatus, e.review_note AS reviewNote,
                          e.reviewed_by AS reviewedBy, e.reviewed_at AS reviewedAt
                   FROM contract_extraction_snapshot s
                   JOIN contract_extracted_element e ON e.snapshot_id = s.id
                   WHERE s.case_id=%s AND s.document_id=%s
                     AND s.status IN ('READY_FOR_CONFIRMATION','CONFIRMED')
                   ORDER BY s.id DESC, e.id""",
                (case_id, document_id),
            )
            rows = cur.fetchall()
    if not rows:
        return [], None
    base_snapshot_id = int(rows[0]["snapshotId"])
    settled: list[dict[str, Any]] = []
    seen_keys: set[str] = set()
    for row in rows:
        if int(row["snapshotId"]) != base_snapshot_id:
            continue
        item = _normalize_value(row)
        for field in ("normalizedValue", "validation"):
            try:
                item[field] = json.loads(item[field]) if isinstance(item.get(field), str) else item.get(field)
            except Exception:
                pass
        key = str(item.get("elementKey") or "")
        if not key or key in seen_keys:
            continue
        reviewed = bool(item.get("reviewStatus"))
        status = str(item.get("status") or "").upper()
        confidence = float(item.get("confidence") or 0)
        if reviewed or (status in _SETTLED_ELEMENT_STATUSES and confidence >= _SETTLED_CONFIDENCE):
            seen_keys.add(key)
            settled.append(item)
    return settled, base_snapshot_id


def select_element_packs(state: dict[str, Any]) -> dict[str, Any]:
    context = state.get("extraction_context") or {}
    case = context.get("case") or {}
    contract_type = str(case.get("contractType") or "OTHER")
    run_id = int(state.get("run_id") or 0)

    packs, plan_meta = _plan_element_packs(context, run_id)

    # Field-level rerun (PRD Phase 5, task 6): settled elements of the
    # previous snapshot are carried, and only packs that still have pending
    # element keys are retrieved/extracted — no repeated OCR, embedding or
    # whole-contract analysis for settled fields.
    try:
        carried, base_snapshot_id = _previous_settled_elements(
            int(state.get("subject_id") or 0),
            int((context.get("document") or {}).get("id") or 0),
        )
    except Exception as exc:
        # A transient lookup failure must not kill the whole run — degrade
        # to a full extraction (the failure strategy keeps the happy path).
        logger.warning("Settled-element lookup failed; running full extraction: %s", exc)
        carried, base_snapshot_id = [], None
    rerun: dict[str, Any] | None = None
    if carried:
        carried_keys = {item.get("elementKey") for item in carried}
        pending_packs = []
        for pack in packs:
            pending_keys = [
                key for key in pack.get("elementKeys") or []
                if key not in carried_keys
            ]
            if pending_keys:
                pending_packs.append({**pack, "elementKeys": pending_keys})
        pending_pack_keys = {pack["packKey"] for pack in pending_packs}
        skipped_packs = [pack["packKey"] for pack in packs if pack["packKey"] not in pending_pack_keys]
        for item in carried:
            item.setdefault("validation", {})
            item["validation"]["carriedFromSnapshotId"] = base_snapshot_id
        rerun = {
            "baseSnapshotId": base_snapshot_id,
            "carriedCount": len(carried),
            "carriedElementKeys": sorted(carried_keys),
            "pendingPacks": [pack["packKey"] for pack in pending_packs],
            "skippedPacks": skipped_packs,
        }
        packs = pending_packs

    return {
        "state_revision": state.get("state_revision", 0) + 1,
        "current_node": "select_element_packs",
        "element_packs": packs,
        "carried_elements": carried,
        "plan": {
            "type": "CONTRACT_ELEMENT_EXTRACTION",
            "contractType": contract_type,
            "packs": [pack["packKey"] for pack in packs],
            "boundedCalls": len(packs) * 2 + 1,
            "baseIdentityWorkUnit": dict(_BASE_IDENTITY_WORK_UNIT),
            "planning": plan_meta,
            "rerun": rerun,
        },
        "observations": [{
            "callId": f"extraction-plan-{run_id}",
            "planStepId": "select_element_packs",
            "toolName": "planContractElementExtraction",
            "arguments": {"contractType": contract_type},
            "output": {
                "packs": [pack["packKey"] for pack in packs],
                "planningSource": plan_meta["source"],
                "contractTypeRefined": plan_meta["contractTypeRefined"],
                "subjectSummary": plan_meta["subjectSummary"],
                "baseIdentityWorkUnit": _BASE_IDENTITY_WORK_UNIT["work_unit_id"],
                "rerun": rerun,
                "maxRetries": 1,
            },
            "status": "DONE",
        }],
    }


def _retrieve_pack(case_id: int, pack: dict[str, Any]) -> list[dict[str, Any]]:
    from ..contract_store import ContractStore

    query = " ".join(str(value) for value in pack.get("queries") or [])[:700]
    hits = _run_async(ContractStore().search_contract_clause(case_id, {"query": query, "topK": 12}))
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for hit in hits or []:
        item = _compact_clause(dict(hit))
        key = item.get("sourceId")
        if not key or key in seen:
            continue
        seen.add(key)
        result.append(item)
    return result[:18]


_extraction_orchestrator_instance = None


def _extraction_orchestrator():
    """Contract-only orchestrator for element extraction (legacy channel set).

    Same RetrievalOrchestrator entry as the risk graph; only the channel set
    differs, because v1 element extraction never consumed policy or historical
    evidence.
    """
    global _extraction_orchestrator_instance
    if _extraction_orchestrator_instance is None:
        from ..harness.retrieval import ContractChannelAdapter, RetrievalOrchestrator

        _extraction_orchestrator_instance = RetrievalOrchestrator(
            adapters=(ContractChannelAdapter(),),
        )
    return _extraction_orchestrator_instance


def retrieve_element_evidence(state: dict[str, Any]) -> dict[str, Any]:
    """Phase 2 (PRD): element evidence goes through the shared orchestrator.

    Same retrieval entry as the risk graph — recall, fusion, dedupe, rerank
    and parent expansion are no longer re-implemented per graph. The element
    graph restricts its channels to contract evidence (knowledge channels are
    not part of its v1 contract), but the bundle shape is identical.
    """
    from ..harness.models import default_retrieval_request
    from ..harness.retrieval import ContractChannelAdapter, empty_bundle, flatten_bundle
    from ..harness.observation import ObservabilityRecorder

    case_id = int(state.get("subject_id") or 0)
    snapshot = state.get("evidence_snapshot") or {}
    clause_texts = state.get("contract_evidence_snapshot") or []
    orchestrator = _extraction_orchestrator()

    evidence_by_pack: dict[str, list[dict[str, Any]]] = {}
    observations: list[dict[str, Any]] = []
    citations: list[dict[str, Any]] = []
    for pack in state.get("element_packs") or []:
        key = str(pack.get("packKey") or "")
        query = " ".join(str(value) for value in pack.get("queries") or [])[:700]
        request = default_retrieval_request(
            case_id, snapshot, key, [query],
            source_quotas={"contract": 12},
            final_limit=12,
        )
        try:
            bundle = orchestrator.retrieve_sync(snapshot, request, clauses=clause_texts)
            status = "DONE"
            error = ""
        except Exception as exc:
            logger.warning("Element evidence retrieval failed for %s: %s", key, exc)
            bundle = empty_bundle(request, [f"orchestrator failed: {exc}"])
            status = "FAILED"
            error = str(exc)[:500]
        evidence = flatten_bundle(bundle)
        evidence_by_pack[key] = evidence
        citations.extend(evidence)
        stats = next((item.get("retrievalStats") for item in evidence if item.get("retrievalStats")), {})
        observations.append({
            "callId": f"extraction-retrieval-{state.get('run_id', 0)}-{key}",
            "planStepId": f"retrieve_{key}",
            "toolName": "retrieveEvidenceBundle",
            "arguments": {"query": pack.get("queries") or [], "topK": 12, "packKey": key},
            "output": {
                "packName": pack.get("packName"),
                "hitCount": len(evidence),
                "sourceIds": [item.get("sourceId") for item in evidence],
                "retrievalStats": stats,
                "crossValidatedCount": sum(1 for item in evidence if item.get("crossValidated")),
                "bundleStats": ObservabilityRecorder.bundle_summary(bundle),
            },
            "status": status,
            "error": error,
        })
    return {
        "state_revision": state.get("state_revision", 0) + 1,
        "current_node": "retrieve_element_evidence",
        "element_evidence": evidence_by_pack,
        "citations": citations,
        "observations": observations,
    }


def extract_base_identity_fields(state: dict[str, Any]) -> dict[str, Any]:
    """Run the fixed base-identity WorkUnit (PRD Phase 5, task 1).

    Deterministic only — confirmed intake/case facts normalized and
    dedicated-validated, with canonical citations restored from the clause
    evidence. No retrieval, no LLM, no rerun needed for this unit.
    """
    context = state.get("extraction_context") or {}
    fields = _canonical_base_fields(context)
    return {
        "state_revision": state.get("state_revision", 0) + 1,
        "current_node": "extract_base_identity_fields",
        "base_identity_fields": fields,
        "observations": [{
            "callId": f"extraction-base-identity-{state.get('run_id', 0)}",
            "planStepId": "extract_base_identity_fields",
            "toolName": "normalizeBaseIdentityFields",
            "arguments": {
                "workUnitId": _BASE_IDENTITY_WORK_UNIT["work_unit_id"],
                "requiredChecks": _BASE_IDENTITY_WORK_UNIT["required_checks"],
            },
            "output": {
                "fieldCount": len(fields),
                "deterministicCount": sum(
                    1 for field in fields if field.get("validation", {}).get("deterministic")
                ),
                "needsDeterministicReview": [
                    field["key"] for field in fields
                    if not field.get("validation", {}).get("deterministic")
                ],
            },
            "status": "DONE",
        }],
    }


def _fallback_elements(context: dict[str, Any], pack: dict[str, Any], evidence: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Conservative fallback: expose existing case facts, never invent text."""
    case = context.get("case") or {}
    our_side = str(case.get("ourSide") or "").upper()
    party_a = case.get("ourEntity") if our_side == "A" else case.get("counterparty")
    party_b = case.get("counterparty") if our_side == "A" else case.get("ourEntity")
    fallback_map = {
        "contract_title": (case.get("title"), "TEXT"),
        "contract_type": (case.get("contractType"), "ENUM"),
        "party_a": (party_a, "PARTY"),
        "party_b": (party_b, "PARTY"),
        "our_side": (case.get("ourSide"), "ENUM"),
        "contract_amount": (case.get("amount"), "MONEY"),
        "effective_date": (case.get("effectiveDate"), "DATE"),
        "expiry_date": (case.get("expiryDate"), "DATE"),
    }
    result = []
    for key in pack.get("elementKeys") or []:
        value, value_type = fallback_map.get(key, (None, "TEXT"))
        if value in (None, ""):
            continue
        result.append({
            "elementKey": key,
            "category": str(pack.get("packKey") or "OTHER").upper(),
            "valueType": value_type,
            "rawValue": str(value),
            "normalizedValue": {"value": value},
            "confidence": 0.35,
            "status": "NEEDS_REVIEW",
            "applicable": True,
            "citations": [],
            "source": "CASE_PROJECTION",
        })
    return result


def _normalize_model_elements(
    raw_items: list[dict[str, Any]],
    pack: dict[str, Any],
    evidence: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    allowed = set(str(key) for key in pack.get("elementKeys") or [])
    evidence_by_id = {str(item.get("sourceId")): item for item in evidence if item.get("sourceId")}
    counters: dict[str, int] = {}
    result = []
    for raw in raw_items:
        if not isinstance(raw, dict):
            continue
        key = str(raw.get("elementKey") or "").strip()
        if key not in allowed:
            continue
        counters[key] = counters.get(key, 0) + 1
        citations = raw.get("citations") if isinstance(raw.get("citations"), list) else []
        verified_citations = []
        for citation in citations[:4]:
            if not isinstance(citation, dict):
                continue
            normalized = dict(citation)
            normalized["sourceId"] = _source_id(normalized)
            if _citation_supported(normalized, evidence_by_id):
                source = evidence_by_id[normalized["sourceId"]]
                normalized["clauseId"] = normalized.get("clauseId") or source.get("clauseId")
                normalized["documentId"] = source.get("documentId")
                normalized["pageNumber"] = source.get("pageNumber")
                verified_citations.append(normalized)
        confidence = _clamp_confidence(raw.get("confidence"), 0.0)
        if not verified_citations:
            confidence = min(confidence, 0.45)
        status = str(raw.get("status") or "EXTRACTED").upper()
        if status not in {"EXTRACTED", "NEEDS_REVIEW", "NOT_FOUND"}:
            status = "NEEDS_REVIEW"
        if not verified_citations and status == "EXTRACTED":
            status = "NEEDS_REVIEW"
        result.append({
            "elementKey": key,
            "category": str(raw.get("category") or pack.get("packKey") or "OTHER").upper(),
            "valueType": str(raw.get("valueType") or "TEXT").upper(),
            "rawValue": str(raw.get("rawValue") or "").strip()[:4000],
            "normalizedValue": raw.get("normalizedValue") if raw.get("normalizedValue") is not None else {},
            "status": status,
            "confidence": confidence,
            "source": str(raw.get("source") or "LLM").upper(),
            "applicable": bool(raw.get("applicable", True)),
            "occurrenceNo": counters[key],
            "citations": verified_citations,
            "validation": {
                "citationCount": len(verified_citations),
                "citationVerified": bool(verified_citations),
                "originalStatus": status,
            },
        })
    return result


def extract_element_batches(state: dict[str, Any]) -> dict[str, Any]:
    from ...services.llm_service import LLMService

    context = state.get("extraction_context") or {}
    llm = LLMService()
    elements: list[dict[str, Any]] = []
    observations: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    for pack in state.get("element_packs") or []:
        pack_key = str(pack.get("packKey") or "")
        evidence = (state.get("element_evidence") or {}).get(pack_key) or []
        try:
            raw = llm.extract_contract_elements(
                context.get("case") or {}, pack, evidence, int(state.get("run_id") or 0)
            )
            normalized = _normalize_model_elements(raw.get("elements") or [], pack, evidence)
            status = "DONE"
            error = ""
            model_used = llm.model
        except Exception as exc:
            normalized = _fallback_elements(context, pack, evidence)
            status = "FALLBACK"
            error = str(exc)[:500]
            model_used = "unavailable"
            errors.append({"node": "extract_element_batches", "packKey": pack_key, "error": error})
            logger.warning("LLM element extraction failed for %s: %s", pack_key, exc)
        elements.extend(normalized)
        observations.append({
            "callId": f"extraction-llm-{state.get('run_id', 0)}-{pack_key}",
            "planStepId": f"extract_{pack_key}",
            "toolName": "extractContractElements",
            "arguments": {
                "packKey": pack_key,
                "elementKeys": pack.get("elementKeys") or [],
                "evidenceCount": len(evidence),
                "promptVersion": EXTRACTION_PROMPT_VERSION,
            },
            "output": {
                "model": model_used,
                "elementCount": len(normalized),
                "verifiedCitationCount": sum(len(item.get("citations") or []) for item in normalized),
                "status": status,
            },
            "status": status,
            "error": error,
        })
    return {
        "state_revision": state.get("state_revision", 0) + 1,
        "current_node": "extract_element_batches",
        "extracted_elements": elements,
        "observations": observations,
        "errors": state.get("errors", []) + errors,
    }


def validate_extracted_elements(state: dict[str, Any]) -> dict[str, Any]:
    context = state.get("extraction_context") or {}
    evidence = [item for values in (state.get("element_evidence") or {}).values() for item in values]
    evidence_by_id = {str(item.get("sourceId")): item for item in evidence if item.get("sourceId")}
    snapshot_hash = str(context.get("evidenceSnapshotHash") or "")
    validated = []
    unsupported = 0
    typed_flagged = 0
    for item in state.get("extracted_elements") or []:
        value = dict(item)
        citations = [c for c in value.get("citations") or [] if _citation_supported(c, evidence_by_id)]
        if len(citations) != len(value.get("citations") or []):
            unsupported += len(value.get("citations") or []) - len(citations)
        value["citations"] = citations
        value["confidence"] = _clamp_confidence(value.get("confidence"))
        value.setdefault("validation", {})
        # PRD Phase 5, task 4: every element and citation binds the evidence
        # snapshot hash it was extracted from.
        if snapshot_hash:
            value["validation"]["evidenceSnapshotHash"] = snapshot_hash
            for citation in value["citations"]:
                citation.setdefault("snapshotHash", snapshot_hash)
        # PRD Phase 5, task 3: dedicated deterministic validation for typed
        # values — a MONEY/DATE/PARTY element whose normalizedValue cannot be
        # parsed deterministically must not stay EXTRACTED.
        typed_ok, typed_issues = validate_structured_element(
            value.get("valueType"), value.get("normalizedValue")
        )
        if not typed_ok:
            typed_flagged += 1
            value["validation"]["typedIssues"] = typed_issues
            value["confidence"] = min(value["confidence"], 0.45)
        if not citations:
            value["status"] = "NEEDS_REVIEW"
            value["confidence"] = min(value["confidence"], 0.45)
        elif value["confidence"] >= 0.75 and value.get("status") != "NOT_FOUND" and typed_ok:
            value["status"] = "EXTRACTED"
        else:
            value["status"] = "NEEDS_REVIEW"
        value["validation"].update({
            "citationVerified": bool(citations),
            "citationCount": len(citations),
            "documentVersion": (context.get("document") or {}).get("version"),
        })
        validated.append(value)
    # PRD Phase 5, task 6: settled elements of the previous snapshot are
    # carried into this run without re-extraction (or re-validation — they
    # cite their own snapshot's evidence).
    carried = state.get("carried_elements") or []
    counts = {
        "total": len(validated) + len(carried),
        "extracted": sum(1 for item in validated if item.get("status") == "EXTRACTED"),
        "needsReview": sum(1 for item in validated if item.get("status") == "NEEDS_REVIEW"),
        "unsupportedCitationCount": unsupported,
        "typedValidationFlaggedCount": typed_flagged,
        "carriedFromPrevious": len(carried),
    }
    return {
        "state_revision": state.get("state_revision", 0) + 1,
        "current_node": "validate_extracted_elements",
        "extracted_elements": validated + carried,
        "extraction_validation": counts,
        "observations": [{
            "callId": f"extraction-validation-{state.get('run_id', 0)}",
            "planStepId": "validate_extracted_elements",
            "toolName": "validateContractElementCitations",
            "arguments": {"elementCount": len(validated), "carriedCount": len(carried)},
            "output": counts,
            "status": "DONE",
        }],
    }


def audit_element_coverage(state: dict[str, Any]) -> dict[str, Any]:
    """Coverage audit for extracted elements (PRD Phase 5).

    Observational only: reports citation support and snapshot-hash binding
    rates so the acceptance metrics (字段级引用支持率 ≥97%, every element
    traceable to the snapshot) are measurable per run, and names the
    uncited elements for the reviewer.
    """
    context = state.get("extraction_context") or {}
    elements = state.get("extracted_elements") or []
    snapshot_hash = str(context.get("evidenceSnapshotHash") or "")
    uncited = [item.get("elementKey") for item in elements if not item.get("citations")]
    if snapshot_hash:
        unbound = [
            item.get("elementKey") for item in elements
            if item.get("validation", {}).get("evidenceSnapshotHash") != snapshot_hash
        ]
    else:
        unbound = uncited
    total = len(elements)
    audit = {
        "totalElements": total,
        "citedElements": total - len(uncited),
        "citationSupportRate": round((total - len(uncited)) / total, 4) if total else 0.0,
        "snapshotHashBoundElements": total - len(unbound),
        "snapshotHashBindingRate": round((total - len(unbound)) / total, 4) if total else 0.0,
        "uncitedElements": uncited,
        "snapshotHashUnboundElements": unbound,
        "carriedElements": sum(
            1 for item in elements
            if item.get("validation", {}).get("carriedFromSnapshotId")
        ),
        "workUnitId": "element_coverage_audit",
    }
    return {
        "state_revision": state.get("state_revision", 0) + 1,
        "current_node": "audit_element_coverage",
        "element_coverage_audit": audit,
        "observations": [{
            "callId": f"extraction-coverage-audit-{state.get('run_id', 0)}",
            "planStepId": "audit_element_coverage",
            "toolName": "auditElementCoverage",
            "arguments": {"elementCount": total},
            "output": audit,
            "status": "DONE",
        }],
    }


def _profile_field_key(value: Any, fallback: str) -> str:
    key = re.sub(r"[^a-zA-Z0-9_]+", "_", str(value or "").strip()).strip("_").lower()
    return key[:128] or fallback


def _normalize_profile_citation(
    citation: dict[str, Any], evidence_by_id: dict[str, dict[str, Any]]
) -> dict[str, Any] | None:
    if not isinstance(citation, dict):
        return None
    normalized = dict(citation)
    normalized["sourceId"] = _source_id(normalized)
    if not _citation_supported(normalized, evidence_by_id):
        return None
    source = evidence_by_id[normalized["sourceId"]]
    normalized["clauseId"] = normalized.get("clauseId") or source.get("clauseId")
    normalized["documentId"] = source.get("documentId")
    normalized["pageNumber"] = normalized.get("pageNumber") or source.get("pageNumber")
    normalized["clauseNumber"] = normalized.get("clauseNumber") or source.get("clauseNumber")
    normalized["clauseTitle"] = normalized.get("clauseTitle") or source.get("title")
    normalized["clauseContent"] = source.get("clauseText") or source.get("content") or source.get("snippet")
    return normalized


def _canonical_value_matches(candidate: Any, confirmed: Any) -> bool:
    if candidate is None or confirmed is None:
        return candidate is confirmed
    try:
        return Decimal(str(candidate)).compare(Decimal(str(confirmed))) == Decimal("0")
    except (InvalidOperation, TypeError, ValueError):
        return str(candidate).strip().casefold() == str(confirmed).strip().casefold()


def _canonical_citations(
    context: dict[str, Any], field_key: str, confirmed_value: Any
) -> list[dict[str, Any]]:
    intake_field = ((context.get("confirmedIntake") or {}).get("fields") or {}).get(field_key) or {}
    if not _canonical_value_matches(intake_field.get("value"), confirmed_value):
        return []
    citations = intake_field.get("citations") if isinstance(intake_field.get("citations"), list) else []
    clauses = context.get("clauses") or []
    result = []
    for citation in citations[:2]:
        if not isinstance(citation, dict):
            continue
        quote = str(citation.get("quote") or "").strip()
        if not quote:
            continue
        normalized = dict(citation)
        for clause in clauses:
            content = str(clause.get("clauseText") or clause.get("content") or "")
            if quote not in content:
                continue
            normalized.update({
                "sourceId": _source_id(clause),
                "clauseId": clause.get("clauseId"),
                "documentId": clause.get("documentId") or (context.get("document") or {}).get("id"),
                "pageNumber": clause.get("pageNumber"),
                "clauseNumber": clause.get("clauseNumber"),
                "clauseTitle": clause.get("title"),
                "clauseContent": content,
            })
            break
        normalized.setdefault("documentId", (context.get("document") or {}).get("id"))
        normalized["contentHash"] = (context.get("document") or {}).get("contentHash")
        normalized["parserVersion"] = PARSER_VERSION
        result.append(normalized)
    return result


def _canonical_base_fields(context: dict[str, Any]) -> list[dict[str, Any]]:
    """Project human-confirmed case facts into the profile without another
    extraction (PRD Phase 5, tasks 1+3: the fixed base-identity WorkUnit).

    Every value additionally passes through the deterministic normalizers and
    the dedicated per-field validation in element_normalization — the
    confirmed value itself is never rewritten, but a normalizedValue and a
    deterministic check result are attached so downstream consumers can trust
    the shape without re-parsing.
    """
    case = context.get("case") or {}
    our_side = str(case.get("ourSide") or "").upper()
    if our_side == "A":
        party_a, party_b = case.get("ourEntity"), case.get("counterparty")
    elif our_side == "B":
        party_a, party_b = case.get("counterparty"), case.get("ourEntity")
    else:
        party_a = party_b = None
    base_map = (
        ("contractTitle", "合同名称", case.get("title"), "TEXT", "contractTitle"),
        ("contractType", "合同类型", case.get("contractType"), "ENUM", "contractType"),
        ("partyA", "甲方主体", party_a, "PARTY", "partyA"),
        ("partyB", "乙方主体", party_b, "PARTY", "partyB"),
        ("ourSide", "我方角色", our_side or None, "ENUM", "ourSide"),
        ("amount", "合同金额", case.get("amount"), "MONEY", "amount"),
        ("currency", "币种", case.get("currency"), "ENUM", "currency"),
        ("signedDate", "签订日期", case.get("signedDate"), "DATE", "signedDate"),
        ("effectiveDate", "生效日期", case.get("effectiveDate"), "DATE", "effectiveDate"),
        ("expiryDate", "到期日期", case.get("expiryDate"), "DATE", "expiryDate"),
    )
    fields = []
    for key, label, value, value_type, intake_key in base_map:
        if value in (None, ""):
            continue
        citations = _canonical_citations(context, intake_key, value)
        check = validate_base_field(key, value)
        fields.append({
            "key": key,
            "label": label,
            "value": value,
            "normalizedValue": check.get("normalized"),
            "valueType": value_type,
            "importance": "CORE",
            "confidence": 1.0,
            "status": "EXTRACTED" if citations else "CONFIRMED",
            "source": "CONFIRMED_INTAKE" if (context.get("confirmedIntake") or {}).get("id") else "CONFIRMED_CASE",
            "citations": citations,
            "validation": {
                "deterministic": check.get("status") == "EXTRACTED",
                "issues": check.get("issues") or [],
            },
            "decision": {
                "intakeId": (context.get("confirmedIntake") or {}).get("id"),
                "confirmedAt": (context.get("confirmedIntake") or {}).get("confirmedAt"),
                "canonical": True,
            },
        })
    return fields


def _fallback_profile(context: dict[str, Any], elements: list[dict[str, Any]]) -> dict[str, Any]:
    """Keep the page useful when the optional profile call is unavailable."""
    case = context.get("case") or {}
    base_fields = _canonical_base_fields(context)
    groups: dict[str, dict[str, Any]] = {}
    for element in elements:
        category = str(element.get("category") or "OTHER").lower()
        group = groups.setdefault(category, {
            "groupKey": category, "label": element.get("category") or "其他合同事实",
            "reason": "由已有可引用合同事实暂时归组，等待画像重新生成。", "fields": [],
        })
        value = element.get("normalizedValue") or element.get("rawValue")
        group["fields"].append({
            "key": element.get("elementKey"), "label": element.get("elementKey"),
            "value": value,
            "displayValue": _profile_display_value(value),
            "valueType": element.get("valueType") or "TEXT",
            "importance": "SUPPORTING", "confidence": element.get("confidence", 0),
            "status": element.get("status") or "NEEDS_REVIEW", "source": element.get("source") or "LLM",
            "citations": element.get("citations") or [],
        })
    return {
        "schemaVersion": PROFILE_SCHEMA_VERSION,
        "title": "合同画像",
        "contractType": case.get("contractType") or "OTHER",
        "typeRationale": "模型不可用，暂由已有合同事实组成。",
        "baseFields": base_fields,
        "groups": list(groups.values()),
        "status": "FALLBACK",
    }


def normalize_contract_profile(
    raw_profile: dict[str, Any],
    context: dict[str, Any],
    elements: list[dict[str, Any]],
    evidence: list[dict[str, Any]],
    base_fields: list[dict[str, Any]] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """``base_fields`` comes from the fixed base-identity WorkUnit node when
    called from the graph; direct callers fall back to recomputing it."""
    evidence_by_id = {str(item.get("sourceId")): item for item in evidence if item.get("sourceId")}
    raw = raw_profile.get("profile") if isinstance(raw_profile, dict) else None
    if not isinstance(raw, dict):
        return _fallback_profile(context, elements), {"status": "FALLBACK", "fieldCount": 0, "verifiedCitationCount": 0}

    def normalize_field(item: Any, fallback_key: str, fallback_label: str) -> dict[str, Any] | None:
        if not isinstance(item, dict):
            return None
        key = _profile_field_key(item.get("key"), fallback_key)
        label = str(item.get("label") or fallback_label or key).strip()[:256]
        citations = []
        for citation in item.get("citations") if isinstance(item.get("citations"), list) else []:
            normalized = _normalize_profile_citation(citation, evidence_by_id)
            if normalized:
                citations.append(normalized)
        status = str(item.get("status") or ("EXTRACTED" if citations else "NEEDS_REVIEW")).upper()
        if status not in {"EXTRACTED", "NEEDS_REVIEW", "NOT_FOUND"}:
            status = "NEEDS_REVIEW"
        confidence = _clamp_confidence(item.get("confidence"), 0.0)
        if not citations:
            status = "NOT_FOUND" if item.get("value") in (None, "") else "NEEDS_REVIEW"
            confidence = min(confidence, 0.45)
        elif confidence < 0.75:
            status = "NEEDS_REVIEW"
        value = item.get("value")
        return {
            "key": key, "label": label, "value": value,
            "displayValue": _profile_display_value(value),
            "valueType": str(item.get("valueType") or "TEXT").upper(),
            "importance": str(item.get("importance") or "SUPPORTING").upper(),
            "confidence": confidence, "status": status,
            "source": "CONTRACT" if citations else str(item.get("source") or "LLM").upper(),
            "citations": citations,
        }

    # Base fields are canonical intake facts. The optional profile model may
    # discover type-specific groups, but it cannot rewrite confirmed identity,
    # party, amount or date values (PRD Phase 5, task 8).
    if base_fields is None:
        base_fields = _canonical_base_fields(context)
    base_keys = {field["key"] for field in base_fields}
    groups = []
    field_count = len(base_fields)
    citation_count = sum(len(field["citations"]) for field in base_fields)
    for group_index, group in enumerate(raw.get("groups") or []):
        if not isinstance(group, dict):
            continue
        group_key = _profile_field_key(group.get("groupKey"), f"group_{group_index + 1}")
        fields = []
        for field_index, item in enumerate(group.get("fields") or []):
            field = normalize_field(item, f"{group_key}_{field_index + 1}", "合同专属要素")
            if not field or field["status"] == "NOT_FOUND":
                continue
            if field["key"] in base_keys:
                # A group field reusing a base fact key would let a later
                # profile overwrite a confirmed fact — silently dropped.
                continue
            fields.append(field)
            field_count += 1
            citation_count += len(field["citations"])
        if fields:
            groups.append({
                "groupKey": group_key,
                "label": str(group.get("label") or "合同专属要素").strip()[:256],
                "reason": str(group.get("reason") or "基于本合同内容发现的业务字段").strip()[:1000],
                "fields": fields,
            })
    profile = {
        "schemaVersion": PROFILE_SCHEMA_VERSION,
        "title": str(raw.get("title") or "合同画像"),
        "contractType": str(raw.get("contractType") or (context.get("case") or {}).get("contractType") or "OTHER"),
        "typeRationale": str(raw.get("typeRationale") or "").strip()[:1000],
        "baseFields": base_fields,
        "groups": groups,
        "status": "READY" if citation_count else "NEEDS_REVIEW",
    }
    return profile, {
        "status": profile["status"],
        "fieldCount": field_count,
        "verifiedCitationCount": citation_count,
        "groupCount": len(groups),
        "canonicalBaseFieldCount": len(base_fields),
    }


def build_contract_profile(state: dict[str, Any]) -> dict[str, Any]:
    from ...services.llm_service import LLMService

    context = state.get("extraction_context") or {}
    evidence = [item for values in (state.get("element_evidence") or {}).values() for item in values]
    elements = state.get("extracted_elements") or []
    base_fields = state.get("base_identity_fields") or _canonical_base_fields(context)
    # The dynamic plan's refined contract type and subject are hints for the
    # profile model (PRD Phase 5, task 2) — never authoritative over the
    # canonical base facts.
    plan_meta = (state.get("plan") or {}).get("planning") or {}
    case_hint = dict(context.get("case") or {})
    if plan_meta.get("contractTypeRefined"):
        case_hint["plannedContractType"] = plan_meta["contractTypeRefined"]
    if plan_meta.get("subjectSummary"):
        case_hint["plannedSubjectSummary"] = plan_meta["subjectSummary"]
    try:
        raw = LLMService().extract_contract_profile(
            case_hint, evidence, elements, int(state.get("run_id") or 0)
        )
        profile, validation = normalize_contract_profile(
            raw, context, elements, evidence, base_fields=base_fields
        )
        status = "DONE"
        error = ""
        model = LLMService().model
    except Exception as exc:
        profile = _fallback_profile(context, elements)
        validation = {"status": "FALLBACK", "fieldCount": len(profile.get("baseFields") or []), "verifiedCitationCount": 0}
        status = "FALLBACK"
        error = str(exc)[:500]
        model = "unavailable"
        logger.warning("Contract profile extraction failed: %s", exc)
    return {
        "state_revision": state.get("state_revision", 0) + 1,
        "current_node": "build_contract_profile",
        "contract_profile": profile,
        "profile_validation": validation,
        "observations": [{
            "callId": f"contract-profile-{state.get('run_id', 0)}",
            "planStepId": "build_contract_profile",
            "toolName": "extractContractProfile",
            "arguments": {"evidenceCount": len(evidence), "schemaVersion": PROFILE_SCHEMA_VERSION},
            "output": {"model": model, **validation},
            "status": status,
            "error": error,
        }],
        "errors": state.get("errors", []) + ([{"node": "build_contract_profile", "error": error}] if error else []),
    }


def _find_evidence_for_citation(citation: dict[str, Any], evidence_by_id: dict[str, dict[str, Any]]) -> dict[str, Any]:
    source_id = str(citation.get("sourceId") or "")
    return evidence_by_id.get(source_id) or {}


def _link_snapshot_to_workflow(
    cur: Any,
    *,
    case_id: int,
    document_id: int,
    run_id: int,
    snapshot_id: int,
) -> None:
    """Attach the current document's fact snapshot to downstream consumers."""
    # A re-extraction replaces the provenance for the current document. Older
    # snapshots remain immutable and are still reachable through their run.
    cur.execute(
        """UPDATE contract_timeline_node
           SET extraction_snapshot_id=%s
           WHERE case_id=%s AND document_id=%s""",
        (snapshot_id, case_id, document_id),
    )
    cur.execute(
        """UPDATE contract_analysis_workflow
           SET extraction_snapshot_id=%s, extraction_run_id=%s,
               extraction_status='READY_FOR_CONFIRMATION',
               current_stage=CASE
                   WHEN current_stage='FACT_EXTRACTION' THEN 'TIMELINE_EXTRACTION'
                   ELSE current_stage
               END,
               last_error=NULL
           WHERE case_id=%s AND document_id=%s""",
        (snapshot_id, run_id, case_id, document_id),
    )


def mark_extraction_workflow_failed(case_id: int, run_id: int, error_message: str) -> None:
    """Keep the contract workflow honest when a graph run terminates early."""
    from ..persistence import _conn

    message = str(error_message or "合同要素提取失败")[:4000]
    try:
        with _conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT workflow_id FROM agent_run WHERE id=%s", (run_id,))
                run = cur.fetchone() or {}
                workflow_id = run.get("workflow_id")
                if workflow_id:
                    cur.execute(
                        """UPDATE contract_analysis_workflow
                           SET extraction_status='FAILED',
                               current_stage=CASE
                                   WHEN current_stage='FACT_EXTRACTION' THEN 'FACT_EXTRACTION'
                                   ELSE current_stage
                               END,
                               last_error=%s
                           WHERE id=%s AND case_id=%s""",
                        (message, workflow_id, case_id),
                    )
                else:
                    cur.execute(
                        """UPDATE contract_analysis_workflow
                           SET extraction_status='FAILED', last_error=%s
                           WHERE case_id=%s AND extraction_run_id=%s""",
                        (message, case_id, run_id),
                    )
            conn.commit()
    except Exception as exc:
        logger.warning("Failed to mark extraction workflow %s as failed: %s", run_id, exc)


def _top_candidates_by_key(elements: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """PRD Phase 5, task 5: when several versions of the same element key
    exist (occurrences, LLM vs fallback), every version stays a candidate —
    only the highest-confidence one is pre-selected, the rest are kept for
    human confirmation instead of being silently overwritten."""
    best_by_key: dict[str, dict[str, Any]] = {}
    for element in elements:
        key = str(element.get("elementKey") or "")
        best = best_by_key.get(key)
        if best is None or float(element.get("confidence") or 0) > float(best.get("confidence") or 0):
            best_by_key[key] = element
    return best_by_key


def _persist_snapshot(state: dict[str, Any]) -> dict[str, Any]:
    from ..persistence import _conn, _json_dumps, _normalize_value

    context = state.get("extraction_context") or {}
    document = context.get("document") or {}
    case_id = int(state.get("subject_id") or 0)
    run_id = int(state.get("run_id") or 0)
    content_hash = str(context.get("contentHash") or "")
    elements = state.get("extracted_elements") or []
    evidence = [item for values in (state.get("element_evidence") or {}).values() for item in values]
    evidence_by_id = {str(item.get("sourceId")): item for item in evidence if item.get("sourceId")}
    profile = state.get("contract_profile") or {}
    canonical = json.dumps(
        {"elements": elements, "profile": profile},
        ensure_ascii=False,
        sort_keys=True,
        default=str,
    )
    snapshot_hash = hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT id, snapshot_hash AS snapshotHash, status,
                          profile_schema_version AS profileSchemaVersion,
                          profile_json AS profileJson, profile_hash AS profileHash,
                          profile_status AS profileStatus
                   FROM contract_extraction_snapshot
                   WHERE source_run_id=%s
                   ORDER BY id DESC LIMIT 1""",
                (run_id,),
            )
            existing = cur.fetchone()
            if existing and str(existing.get("status") or "").upper() in {"READY_FOR_CONFIRMATION", "CONFIRMED"}:
                snapshot_id = int(existing["id"])
                cur.execute(
                    """SELECT id, element_key AS elementKey, category, value_type AS valueType,
                              raw_value AS rawValue, normalized_value_json AS normalizedValue,
                              status, confidence, source, applicable, occurrence_no AS occurrenceNo,
                              validation_json AS validation,
                              manual_override AS manualOverride,
                              review_status AS reviewStatus, review_note AS reviewNote,
                              reviewed_by AS reviewedBy, reviewed_at AS reviewedAt
                       FROM contract_extracted_element WHERE snapshot_id=%s ORDER BY id""",
                    (snapshot_id,),
                )
                persisted = [_normalize_value(row) for row in cur.fetchall()]
                for item in persisted:
                    for field in ("normalizedValue", "validation"):
                        try:
                            item[field] = json.loads(item[field]) if isinstance(item.get(field), str) else item.get(field)
                        except Exception:
                            pass
                    # Human review / correction state is surfaced in the
                    # reused artifact (PRD Phase 5, task 7: 保存确认、修正).
                    for field in ("manualOverride", "reviewStatus", "reviewNote", "reviewedBy", "reviewedAt"):
                        if item.get(field) is None:
                            item.pop(field, None)
                try:
                    persisted_profile = json.loads(existing.get("profileJson") or "{}")
                except Exception:
                    persisted_profile = {}
                _link_snapshot_to_workflow(
                    cur,
                    case_id=case_id,
                    document_id=int(document.get("id") or 0),
                    run_id=run_id,
                    snapshot_id=snapshot_id,
                )
                conn.commit()
                return {
                    "id": snapshot_id,
                    "snapshotHash": existing.get("snapshotHash") or snapshot_hash,
                    "status": existing.get("status"),
                    "reused": True,
                    "elements": persisted,
                    "profile": persisted_profile,
                }

            if existing:
                snapshot_id = int(existing["id"])
                # Replaying the same run after a failed checkpoint must remain
                # idempotent, but a later user-triggered extraction receives a
                # distinct snapshot and preserves this run as history.
                cur.execute(
                    """DELETE l FROM contract_element_evidence_link l
                       INNER JOIN contract_extracted_element e ON e.id=l.element_id
                       WHERE e.snapshot_id=%s""",
                    (snapshot_id,),
                )
                cur.execute(
                    """DELETE c FROM contract_element_candidate c
                       INNER JOIN contract_extracted_element e ON e.id=c.element_id
                       WHERE e.snapshot_id=%s""",
                    (snapshot_id,),
                )
                cur.execute("DELETE FROM contract_extracted_element WHERE snapshot_id=%s", (snapshot_id,))
                cur.execute(
                    """UPDATE contract_extraction_snapshot
                       SET status='RUNNING', source_run_id=%s, error_message=NULL,
                           snapshot_hash=NULL, profile_json=NULL, profile_hash=NULL,
                           profile_status='RUNNING', update_time=NOW()
                       WHERE id=%s""",
                    (run_id, snapshot_id),
                )
            else:
                # Field-level rerun provenance (PRD Phase 5, task 7): the new
                # snapshot chains to its ancestor and records exactly which
                # packs/elements were carried vs re-extracted.
                rerun = (state.get("plan") or {}).get("rerun")
                cur.execute(
                    """INSERT INTO contract_extraction_snapshot
                       (case_id, document_id, document_version, content_hash,
                        parser_version, schema_version, prompt_version, llm_model,
                       retrieval_version, profile_schema_version, profile_status,
                       status, source_run_id, base_snapshot_id, rerun_scope_json)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'RUNNING',%s,%s,%s)""",
                    (case_id, document.get("id"), document.get("version"), content_hash,
                     PARSER_VERSION, EXTRACTION_SCHEMA_VERSION, EXTRACTION_PROMPT_VERSION,
                     str(getattr(__import__("app.config", fromlist=["settings"]), "settings").llm_model or ""),
                     EXTRACTION_RETRIEVAL_VERSION, PROFILE_SCHEMA_VERSION, "RUNNING", run_id,
                     (rerun or {}).get("baseSnapshotId"),
                     _json(rerun) if rerun else None),
                )
                snapshot_id = int(cur.lastrowid)
            best_by_key = _top_candidates_by_key(elements)

            for element in elements:
                cur.execute(
                    """INSERT INTO contract_extracted_element
                       (snapshot_id, element_key, category, value_type, raw_value,
                        normalized_value_json, status, confidence, source, applicable,
                        occurrence_no, validation_json)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                    (snapshot_id, element.get("elementKey"), element.get("category"),
                     element.get("valueType"), element.get("rawValue"),
                     _json_dumps(element.get("normalizedValue") or {}),
                     element.get("status") or "NEEDS_REVIEW", element.get("confidence"),
                     element.get("source") or "LLM", 1 if element.get("applicable", True) else 0,
                     int(element.get("occurrenceNo") or 1), _json_dumps(element.get("validation") or {})),
                )
                element_id = int(cur.lastrowid)
                citations = element.get("citations") or []
                for citation in citations:
                    source = _find_evidence_for_citation(citation, evidence_by_id)
                    quote = str(citation.get("quote") or "").strip()
                    if not quote:
                        continue
                    cur.execute(
                        """INSERT INTO contract_element_evidence_link
                           (element_id, document_id, clause_id, chunk_id, page_number,
                            paragraph_index, quote, start_offset, end_offset,
                            bbox_json, retrieval_method, score)
                           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                        (element_id, source.get("documentId") or document.get("id"),
                         citation.get("clauseId") or source.get("clauseId"),
                         source.get("chunkId"), citation.get("pageNumber") or source.get("pageNumber"),
                         citation.get("paragraphIndex"), quote, citation.get("startOffset"),
                         citation.get("endOffset"), _json_dumps(citation.get("bbox")) if citation.get("bbox") else None,
                         ",".join(source.get("retrievalSources") or []) or source.get("retrievalType"),
                         source.get("fusionScore") or source.get("score")),
                    )
                carried_from = (element.get("validation") or {}).get("carriedFromSnapshotId")
                if carried_from:
                    selected = 0
                    reason = f"沿用上一版本已确认要素（字段级重跑未重提取，来源快照 #{carried_from}）"
                elif best_by_key.get(element.get("elementKey")) is element:
                    selected = 1
                    reason = "当前最高置信度候选；最终以人工确认结果为准"
                else:
                    selected = 0
                    reason = "与同键其他版本冲突，保留候选供人工确认"
                cur.execute(
                    """INSERT INTO contract_element_candidate
                       (element_id, raw_value, normalized_value_json, source, confidence, selected, reason)
                       VALUES (%s,%s,%s,%s,%s,%s,%s)""",
                    (element_id, element.get("rawValue"), _json_dumps(element.get("normalizedValue") or {}),
                     element.get("source") or "LLM", element.get("confidence"),
                     selected, reason),
                )

            profile_hash = hashlib.sha256(
                json.dumps(profile, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
            ).hexdigest() if profile else None
            profile_status = str((state.get("profile_validation") or {}).get("status") or "NEEDS_REVIEW")
            cur.execute(
                """UPDATE contract_extraction_snapshot
                   SET status='READY_FOR_CONFIRMATION', snapshot_hash=%s,
                       profile_schema_version=%s, profile_json=%s, profile_hash=%s,
                       profile_status=%s, error_message=NULL,
                       source_run_id=%s, update_time=NOW()
                   WHERE id=%s""",
                (snapshot_hash, PROFILE_SCHEMA_VERSION, _json(profile), profile_hash,
                 profile_status, run_id, snapshot_id),
            )
            _link_snapshot_to_workflow(
                cur,
                case_id=case_id,
                document_id=int(document.get("id") or 0),
                run_id=run_id,
                snapshot_id=snapshot_id,
            )
        conn.commit()

    return {
        "id": snapshot_id,
        "snapshotHash": snapshot_hash,
        "status": "READY_FOR_CONFIRMATION",
        "reused": False,
        "elements": elements,
        "profile": profile,
    }


def persist_extraction_snapshot(state: dict[str, Any]) -> dict[str, Any]:
    snapshot = _persist_snapshot(state)
    context = state.get("extraction_context") or {}
    validation = state.get("extraction_validation") or {}
    artifact = {
        "reportType": "CONTRACT_ELEMENT_EXTRACTION",
        "title": "合同要素提取结果",
        "summary": (
            f"已从 {context.get('clauseCount', 0)} 条合同条款中整理 "
            f"{validation.get('total', 0)} 个合同要素，其中 "
            f"{validation.get('needsReview', 0)} 个需要人工确认。"
        ),
        "analysisMode": "EXTRACTION_WITH_CITATION_VALIDATION",
        "extractionSnapshotId": snapshot.get("id"),
        "extractionSnapshotHash": snapshot.get("snapshotHash"),
        "documentId": (context.get("document") or {}).get("id"),
        "documentVersion": (context.get("document") or {}).get("version"),
        "contentHash": context.get("contentHash"),
        "requiresHumanConfirmation": True,
        "elements": snapshot.get("elements") or state.get("extracted_elements") or [],
        "contractProfile": snapshot.get("profile") or state.get("contract_profile") or {},
        "elementSummary": validation,
        "baseIdentity": state.get("base_identity_fields") or [],
        "coverageAudit": state.get("element_coverage_audit") or {},
        "rerun": (state.get("plan") or {}).get("rerun"),
        "planning": (state.get("plan") or {}).get("planning"),
        "citations": state.get("citations") or [],
        "retrievalVersion": EXTRACTION_RETRIEVAL_VERSION,
        "promptVersion": EXTRACTION_PROMPT_VERSION,
        "model": str(state.get("model") or ""),
        "content": {
            "case": context.get("case") or {},
            "document": context.get("document") or {},
            "validation": validation,
            "humanConfirmationRequired": True,
        },
    }

    stamp_artifact_versions(state, artifact)

    return {
        "state_revision": state.get("state_revision", 0) + 1,
        "current_node": "persist_extraction_snapshot",
        "extraction_snapshot": snapshot,
        "artifact": artifact,
        "observations": [{
            "callId": f"extraction-persist-{state.get('run_id', 0)}",
            "planStepId": "persist_extraction_snapshot",
            "toolName": "persistContractExtractionSnapshot",
            "arguments": {"caseId": state.get("subject_id"), "documentId": artifact.get("documentId")},
            "output": {
                "snapshotId": snapshot.get("id"),
                "snapshotHash": snapshot.get("snapshotHash"),
                "reused": snapshot.get("reused", False),
                "elementCount": len(artifact.get("elements") or []),
                "profileFieldCount": sum(
                    len(group.get("fields") or []) for group in (artifact.get("contractProfile") or {}).get("groups") or []
                ) + len((artifact.get("contractProfile") or {}).get("baseFields") or []),
            },
            "status": "DONE",
        }],
    }


# §4.2 role → skeleton stage mapping for element extraction (PRD Phase 5):
#   context          = load_extraction_context
#   planner          = select_element_packs (base identity WorkUnit + dynamic
#                      LLM pack planning + field-level rerun scope)
#   retriever        = retrieve_element_evidence
#   analyzer         = extract_base_identity_fields (deterministic) +
#                      extract_element_batches (LLM)
#   validator        = validate_extracted_elements
#   coverage_auditor = audit_element_coverage
#   composer         = build_contract_profile
#   persistence      = persist_extraction_snapshot
# Extraction has no interrupt stage (confirmation happens on the Java side),
# so human_gate is None.
CONTRACT_EXTRACTION_SPEC = TaskSpec(
    task_type="CONTRACT_ELEMENT_EXTRACTION",
    graph_name="contract_extraction",
    graph_version="v1",
    prompt_version=EXTRACTION_PROMPT_VERSION,
    context=Role((
        ("load_extraction_context", load_extraction_context),
    )),
    planner=Role((
        ("select_element_packs", select_element_packs),
    )),
    retriever=Role((
        ("retrieve_element_evidence", retrieve_element_evidence),
    )),
    analyzer=Role((
        ("extract_base_identity_fields", extract_base_identity_fields),
        ("extract_element_batches", extract_element_batches),
    )),
    validator=Role((
        ("validate_extracted_elements", validate_extracted_elements),
    )),
    coverage_auditor=Role((
        ("audit_element_coverage", audit_element_coverage),
    )),
    composer=Role((
        ("build_contract_profile", build_contract_profile),
    )),
    persistence=Role((
        ("persist_extraction_snapshot", persist_extraction_snapshot),
    )),
    edges=(
        ("select_element_packs", "retrieve_element_evidence"),
        ("retrieve_element_evidence", "extract_base_identity_fields"),
        ("extract_base_identity_fields", "extract_element_batches"),
        ("extract_element_batches", "validate_extracted_elements"),
        ("validate_extracted_elements", "audit_element_coverage"),
        ("audit_element_coverage", "build_contract_profile"),
        ("build_contract_profile", "persist_extraction_snapshot"),
    ),
)


def build_contract_extraction_graph(checkpointer: Any = None) -> Any:
    """Build and compile the ContractExtractionGraph from its TaskSpec."""
    from ..harness.graph_builder import build_task_graph

    return build_task_graph(CONTRACT_EXTRACTION_SPEC, checkpointer)


def register(registry=None) -> None:
    if registry is None:
        from .registry import get_graph_registry
        registry = get_graph_registry()
    registry.register(
        name="contract_extraction",
        version="v1",
        builder=build_contract_extraction_graph,
    )
    logger.info("Registered ContractExtractionGraph v1")
