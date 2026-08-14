"""Unified contract evidence snapshot — the single evidence entry for all contract graphs.

PRD (evidence-agent-harness-high-recall-dag, 2026-08-14) Phase 1: every graph
must observe the same contract facts for the same case + document version.

This module provides:

* ``EvidenceSnapshot``              — canonical, hash-addressed evidence view
* ``EvidenceContextBuilder``        — hides main-document selection, intake /
                                       extraction load order, clause sources,
                                       quality diagnostics and hash computation
* ``load_contract_evidence_snapshot()`` — thin module-level entry point

The snapshot is DB-backed and side-effect free. Graphs must not re-select
documents or re-query clauses on their own; anything a task needs to see about
a contract at run start comes from here.
"""

from __future__ import annotations

import hashlib
import json
import time
from typing import Any, TypedDict

_SNAPSHOT_SCHEMA_VERSION = "evidence-snapshot-v1"


class EvidenceSnapshot(TypedDict, total=False):
    """One immutable evidence view bound to a single main-document version."""

    # ── Identity & address ──
    snapshot_hash: str
    case_id: int
    document_id: int
    document_version: int
    content_hash: str

    # ── Evidence inputs shared by all four graphs ──
    main_document_parser: dict            # parse facts of the selected MAIN document
    quality_diagnostics: dict             # document-quality diagnosis (all documents)
    confirmed_intake_fields: dict         # latest CONFIRMED intake view ({} if none)
    latest_confirmed_extraction_snapshot: dict  # latest confirmed/ready extraction snapshot ({} if none)
    clause_catalog: list[dict]            # lightweight clause inventory (no content)
    clauses: list[dict]                   # full clause details for analysis
    knowledge_scope: dict                 # standard-clause / KB scope, incl. its own hash

    # ── Explainability: optional inputs that were absent ──
    # Empty dicts/lists are the *shape*; this list is the *reason*. Consumers
    # can distinguish "no intake exists" from "intake exists but has no fields".
    missing_inputs: list[str]

    # ── Back-compat aliases (derived from the same load, not extra queries) ──
    case: dict
    documents: list[dict]
    currentDocument: dict
    clauseCount: int
    confirmedIntake: dict
    extractionSnapshot: dict
    documentQuality: dict


def _parse_json(value: Any, fallback: Any) -> Any:
    if isinstance(value, (dict, list)):
        return value
    if not value:
        return fallback
    try:
        return json.loads(value)
    except Exception:
        return fallback


def compact_clause(item: dict[str, Any]) -> dict[str, Any]:
    content = str(item.get("content") or item.get("clauseText") or "")
    snippet = content[:1800]
    return {
        "sourceId": item.get("sourceId") or f"CONTRACT_CLAUSE:{item.get('clauseId') or item.get('id')}",
        "clauseId": item.get("clauseId") or item.get("id"),
        "documentId": item.get("documentId") or item.get("document_id"),
        "clauseNumber": item.get("clauseNumber") or item.get("clause_number"),
        "title": item.get("title") or (snippet[:80] if snippet else ""),
        "clauseType": item.get("clauseType") or item.get("clause_type") or "OTHER",
        "content": content,
        "clauseText": content,
        "snippet": snippet,
        "pageNumber": item.get("pageNumber") or item.get("page_number") or item.get("page"),
        "startOffset": item.get("startOffset") or item.get("start_offset"),
        "endOffset": item.get("endOffset") or item.get("end_offset"),
    }


def _clause_catalog_entry(clause: dict[str, Any]) -> dict[str, Any]:
    """Lightweight inventory entry (no content) for planning and type filtering."""
    return {
        "clauseId": clause.get("clauseId"),
        "documentId": clause.get("documentId"),
        "clauseNumber": clause.get("clauseNumber"),
        "title": clause.get("title"),
        "clauseType": clause.get("clauseType"),
        "pageNumber": clause.get("pageNumber"),
        "charCount": len(str(clause.get("clauseText") or clause.get("content") or "")),
    }


def _select_main_document(documents: list[dict[str, Any]], requested_document_id: int) -> dict[str, Any]:
    """The one shared main-document selection rule (PRD Phase 1).

    The main document must be a READY MAIN document of the case. An explicit
    ``requested_document_id`` must itself satisfy this rule — a request never
    silently falls back to a different document; unsatisfiable requests raise
    with a precise reason instead.
    """
    ready_mains = [
        item for item in documents
        if str(item.get("documentType") or "").upper() == "MAIN"
        and str(item.get("parseStatus") or "").upper() == "READY"
    ]
    if requested_document_id:
        for item in ready_mains:
            if int(item.get("id") or 0) == int(requested_document_id):
                return item
        raise ValueError(
            f"Requested document {requested_document_id} is not a READY main document of the case"
        )
    if not ready_mains:
        raise ValueError("No ready main contract document")
    return max(ready_mains, key=lambda item: (int(item.get("version") or 0), int(item.get("id") or 0)))


def _load_confirmed_intake(cur, case_id: int) -> dict[str, Any]:
    from ..persistence import _normalize_value

    cur.execute(
        """SELECT id, validated_json AS validatedJson,
                  confirmed_json AS confirmedJson, content_hash AS contentHash,
                  schema_version AS schemaVersion, prompt_version AS promptVersion,
                  model, update_time AS confirmedAt
           FROM contract_intake
           WHERE case_id=%s AND status='CONFIRMED'
           ORDER BY id DESC LIMIT 1""",
        (case_id,),
    )
    row = _normalize_value(cur.fetchone() or {})
    if not row:
        return {}
    validated = _parse_json(row.get("validatedJson"), {})
    confirmed = _parse_json(row.get("confirmedJson"), {})
    return {
        "id": row.get("id"),
        "contentHash": row.get("contentHash"),
        "schemaVersion": row.get("schemaVersion"),
        "promptVersion": row.get("promptVersion"),
        "model": row.get("model"),
        "confirmedAt": row.get("confirmedAt"),
        "fields": validated.get("fields") if isinstance(validated, dict) else {},
        "confirmed": confirmed,
    }


def _load_extraction_snapshot(cur, case_id: int, document_id: int) -> dict[str, Any]:
    from ..persistence import _normalize_value

    cur.execute(
        """SELECT id, document_id AS documentId, document_version AS documentVersion,
                  content_hash AS contentHash, status, snapshot_hash AS snapshotHash,
                  schema_version AS schemaVersion, prompt_version AS promptVersion,
                  retrieval_version AS retrievalVersion, profile_json AS profileJson,
                  profile_hash AS profileHash
           FROM contract_extraction_snapshot
           WHERE case_id=%s
             AND document_id=%s
             AND status IN ('CONFIRMED','READY_FOR_CONFIRMATION')
           ORDER BY (status='CONFIRMED') DESC, id DESC
           LIMIT 1""",
        (case_id, document_id),
    )
    snapshot = _normalize_value(cur.fetchone() or {})
    if not snapshot:
        return {}
    cur.execute(
        """SELECT id, element_key AS elementKey, category,
                  raw_value AS rawValue, normalized_value_json AS normalizedValue,
                  status, confidence, source, applicable, occurrence_no AS occurrenceNo,
                  validation_json AS validation
           FROM contract_extracted_element
           WHERE snapshot_id=%s
           ORDER BY id ASC""",
        (snapshot.get("id"),),
    )
    elements = [_normalize_value(row) for row in cur.fetchall()]
    for element in elements:
        element["normalizedValue"] = _parse_json(element.get("normalizedValue"), element.get("normalizedValue"))
        element["validation"] = _parse_json(element.get("validation"), {})
    snapshot["elements"] = elements
    snapshot["profile"] = _parse_json(snapshot.pop("profileJson", None), {})
    return snapshot


def _load_knowledge_scope(cur) -> tuple[dict[str, Any], str]:
    """Load the knowledge scope version and its own stable hash.

    The scope covers the deterministic knowledge channels a graph may cite:
    active standard clauses (versioned table) and the KB index identifier.
    A change in either changes the snapshot hash (PRD Phase 1 invariant).
    """
    from ..persistence import _normalize_value

    cur.execute(
        """SELECT COALESCE(MAX(version),0) AS maxVersion, COUNT(*) AS cnt
           FROM contract_standard_clause WHERE is_active=1""",
    )
    row = _normalize_value(cur.fetchone() or {})
    kb_index = ""
    try:
        from app.config import settings

        kb_index = str(getattr(settings, "kb_index", "") or "")
    except Exception:
        kb_index = ""
    scope = {
        "standardClauseVersion": row.get("maxVersion", 0),
        "standardClauseCount": int(row.get("cnt", 0)),
        "kbIndex": kb_index,
    }
    scope_hash = hashlib.sha256(
        json.dumps(scope, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()
    return {**scope, "knowledgeScopeHash": scope_hash}, scope_hash


def _clause_identity(clauses: list[dict[str, Any]]) -> list[tuple[str, str, str]]:
    """Order-insensitive, content-sensitive clause identity for hashing.

    Sorting by (clauseNumber, title, contentHash) means reordering rows in the
    database does not drift the snapshot hash, while any content change does.
    """
    entries = []
    for item in clauses:
        content = str(item.get("clauseText") or item.get("content") or "")
        entries.append((
            str(item.get("clauseNumber") or ""),
            str(item.get("title") or ""),
            hashlib.sha256(content.encode("utf-8")).hexdigest(),
        ))
    return sorted(entries)


def _compute_snapshot_hash(
    case_id: int,
    current_document: dict[str, Any],
    clauses: list[dict[str, Any]],
    confirmed_intake: dict[str, Any],
    extraction_snapshot: dict[str, Any],
    knowledge_scope_hash: str,
) -> str:
    """Stable snapshot hash (PRD Phase 1 invariants).

    Changes the hash: document version / content, clause content, confirmed
    intake, extraction snapshot, knowledge scope.
    Does NOT change the hash: clause row order, ``include_content_text``,
    parse diagnostics.
    """
    payload = {
        "schema": _SNAPSHOT_SCHEMA_VERSION,
        "case_id": int(case_id),
        "document_id": int(current_document.get("id") or 0),
        "document_version": current_document.get("version"),
        "content_hash": str(current_document.get("contentHash") or ""),
        "clause_identity": _clause_identity(clauses),
        "confirmed_intake": {
            "id": confirmed_intake.get("id"),
            "content_hash": confirmed_intake.get("contentHash"),
            "fields": json.dumps(
                confirmed_intake.get("fields") or {},
                ensure_ascii=False, sort_keys=True, default=str,
            ),
        },
        "extraction_snapshot": {
            "id": extraction_snapshot.get("id"),
            "snapshot_hash": extraction_snapshot.get("snapshotHash"),
        },
        "knowledge_scope_hash": knowledge_scope_hash,
    }
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()


class EvidenceContextBuilder:
    """Builds one immutable evidence snapshot per (case, document version).

    Internal responsibilities (PRD §11.1): main-document selection, intake and
    extraction load order, clause catalog + clause details, quality
    diagnostics, knowledge scope and the stable snapshot hash. Also supports a
    TTL cache; the module-level loader keeps caching OFF (``ttl_seconds=0``)
    until retrieval/evidence caching is designed as a whole (PRD Phase 9) —
    intake/extraction confirmations are written by the Java side and cannot
    evict a Python-side cache today.
    """

    def __init__(self, *, ttl_seconds: float = 0.0) -> None:
        self._ttl = max(0.0, float(ttl_seconds))
        self._cache: dict[tuple[Any, ...], tuple[float, dict[str, Any]]] = {}

    @staticmethod
    def _cache_key(
        case_id: int,
        requested_document_id: int,
        include_content_text: bool,
        clause_limit: int,
    ) -> tuple[Any, ...]:
        return (int(case_id), int(requested_document_id or 0), bool(include_content_text), int(clause_limit))

    def build(
        self,
        case_id: int,
        *,
        requested_document_id: int = 0,
        include_content_text: bool = False,
        clause_limit: int = 240,
    ) -> dict[str, Any]:
        """Build (or return a fresh cached copy of) the evidence snapshot."""
        key = self._cache_key(case_id, requested_document_id, include_content_text, clause_limit)
        if self._ttl > 0:
            cached = self._cache.get(key)
            if cached and cached[0] > time.monotonic():
                return cached[1]
        snapshot = self._build(
            int(case_id),
            requested_document_id=int(requested_document_id or 0),
            include_content_text=include_content_text,
            clause_limit=clause_limit,
        )
        if self._ttl > 0:
            self._cache[key] = (time.monotonic() + self._ttl, snapshot)
        return snapshot

    def evict(self, case_id: int) -> None:
        """Drop all cached snapshots for one case (e.g. after re-parse/confirm)."""
        self._cache = {
            key: entry for key, entry in self._cache.items() if key[0] != int(case_id)
        }

    def clear(self) -> None:
        self._cache.clear()

    @staticmethod
    def _build(
        case_id: int,
        *,
        requested_document_id: int = 0,
        include_content_text: bool = False,
        clause_limit: int = 240,
    ) -> dict[str, Any]:
        from ..evidence import summarize_document_quality
        from ..persistence import _conn, _normalize_value

        with _conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """SELECT id, case_key AS caseKey, title, contract_type AS contractType,
                              status, our_entity AS ourEntity, counterparty,
                              our_side AS ourSide, amount, currency,
                              signed_date AS signedDate, effective_date AS effectiveDate,
                              expiry_date AS expiryDate, department, update_time AS updateTime
                       FROM contract_case WHERE id=%s AND deleted=0""",
                    (case_id,),
                )
                case = _normalize_value(cur.fetchone() or {})
                if not case:
                    raise ValueError(f"Contract case {case_id} not found")

                content_select = ", content_text AS contentText" if include_content_text else ""
                cur.execute(
                    f"""SELECT id, document_type AS documentType, file_name AS fileName,
                              version, parse_status AS parseStatus, parse_quality AS parseQuality,
                              content_hash AS contentHash, parse_diagnostics_json AS parseDiagnostics
                              {content_select}
                       FROM contract_document
                       WHERE case_id=%s AND COALESCE(deleted,0)=0
                       ORDER BY version DESC, id DESC""",
                    (case_id,),
                )
                documents = [_normalize_value(row) for row in cur.fetchall()]

                # ── 1. Main document selection (shared rule) ──
                current_document = _select_main_document(documents, requested_document_id)

                content_hash = str(current_document.get("contentHash") or "").strip()
                if not content_hash and include_content_text:
                    content_hash = hashlib.sha256(
                        str(current_document.get("contentText") or "").encode("utf-8")
                    ).hexdigest()
                    current_document["contentHash"] = content_hash

                # ── 2. Clauses: one source for catalog AND details ──
                cur.execute(
                    """SELECT id AS clauseId, document_id AS documentId,
                              clause_number AS clauseNumber, title, content,
                              clause_type AS clauseType, page_number AS pageNumber,
                              start_offset AS startOffset, end_offset AS endOffset
                       FROM contract_clause
                       WHERE case_id=%s AND document_id=%s
                       ORDER BY id ASC LIMIT %s""",
                    (case_id, current_document.get("id"), clause_limit),
                )
                clauses = [compact_clause(_normalize_value(row)) for row in cur.fetchall()]
                clause_catalog = [_clause_catalog_entry(clause) for clause in clauses]

                # ── 3. Confirmed intake first, then the extraction snapshot ──
                # (fixed load order — every graph sees the same pairing)
                confirmed_intake = _load_confirmed_intake(cur, case_id)
                extraction_snapshot = _load_extraction_snapshot(
                    cur, case_id, int(current_document.get("id") or 0)
                )

                # ── 4. Knowledge scope version ──
                knowledge_scope, knowledge_scope_hash = _load_knowledge_scope(cur)

        if not include_content_text:
            current_document.pop("contentText", None)
            for document in documents:
                document.pop("contentText", None)

        document_quality = summarize_document_quality(documents)

        # Optional inputs are never silently reshaped: the canonical key stays
        # present (empty), and the absence is recorded explicitly.
        missing_inputs = []
        if not confirmed_intake:
            missing_inputs.append("confirmed_intake_fields")
        if not extraction_snapshot:
            missing_inputs.append("latest_confirmed_extraction_snapshot")

        snapshot_hash = _compute_snapshot_hash(
            case_id, current_document, clauses,
            confirmed_intake, extraction_snapshot, knowledge_scope_hash,
        )

        return {
            # Canonical identity & address
            "snapshot_hash": snapshot_hash,
            "case_id": case_id,
            "document_id": current_document.get("id"),
            "document_version": current_document.get("version"),
            "content_hash": current_document.get("contentHash"),
            # Evidence inputs
            "main_document_parser": {
                key: current_document.get(key)
                for key in ("parseStatus", "parseQuality", "parseDiagnostics", "fileName")
            },
            "quality_diagnostics": document_quality,
            "confirmed_intake_fields": confirmed_intake,
            "latest_confirmed_extraction_snapshot": extraction_snapshot,
            "clause_catalog": clause_catalog,
            "clauses": clauses,
            "knowledge_scope": knowledge_scope,
            "missing_inputs": missing_inputs,
            # Back-compat aliases — derived from the same load, never re-queried
            "case": case,
            "documents": documents,
            "currentDocument": current_document,
            "clauseCount": len(clauses),
            "confirmedIntake": confirmed_intake,
            "extractionSnapshot": extraction_snapshot,
            "documentQuality": document_quality,
            "contentHash": current_document.get("contentHash"),
        }


def state_copy_of_snapshot(shared_snapshot: dict[str, Any]) -> dict[str, Any]:
    """State-safe copy of the canonical snapshot for graph-state injection.

    Full clause details are dropped: they live in the graph state's clause
    list loaded from the same builder call, and duplicating them would double
    every checkpoint payload.
    """
    return {
        key: value
        for key, value in shared_snapshot.items()
        if key not in ("clauses", "case", "documents", "currentDocument")
    }


# Module-level entry point. Caching stays off here on purpose: intake and
# extraction confirmations are written by the Java side, which cannot evict a
# Python-side cache; retrieval caching is designed in PRD Phase 9 instead.
_default_builder = EvidenceContextBuilder(ttl_seconds=0.0)


def load_contract_evidence_snapshot(
    case_id: int,
    *,
    requested_document_id: int = 0,
    include_content_text: bool = False,
    clause_limit: int = 240,
) -> dict[str, Any]:
    """Load one immutable view of parsed contract evidence for graph tasks.

    All four contract graphs obtain their evidence through this entry point so
    that a run for the same case + document version always sees the same facts
    and produces the same ``snapshot_hash`` (PRD Phase 1 acceptance).
    """
    return _default_builder.build(
        case_id,
        requested_document_id=requested_document_id,
        include_content_text=include_content_text,
        clause_limit=clause_limit,
    )
