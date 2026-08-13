"""Shared contract evidence snapshot loading for all contract graphs."""

from __future__ import annotations

import hashlib
import json
from typing import Any


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


def load_contract_evidence_snapshot(
    case_id: int,
    *,
    requested_document_id: int = 0,
    include_content_text: bool = False,
    clause_limit: int = 240,
) -> dict[str, Any]:
    """Load one immutable view of parsed contract evidence for graph tasks.

    The snapshot is intentionally DB-backed and side-effect free. It prevents
    extraction, timeline, review, and fulfillment graphs from each selecting
    different documents or rebuilding their own evidence context.
    """
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

            current_document = next(
                (
                    item for item in documents
                    if str(item.get("documentType") or "").upper() == "MAIN"
                    and str(item.get("parseStatus") or "").upper() == "READY"
                    and (not requested_document_id or int(item.get("id") or 0) == requested_document_id)
                ),
                None,
            )
            if current_document is None and not requested_document_id:
                current_document = next(
                    (
                        item for item in documents
                        if str(item.get("documentType") or "").upper() == "MAIN"
                        and str(item.get("parseStatus") or "").upper() == "READY"
                    ),
                    None,
                )
            if not current_document:
                raise ValueError("No ready main contract document")

            content_hash = str(current_document.get("contentHash") or "").strip()
            if not content_hash and include_content_text:
                content_hash = hashlib.sha256(
                    str(current_document.get("contentText") or "").encode("utf-8")
                ).hexdigest()
                current_document["contentHash"] = content_hash

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

            confirmed_intake = _load_confirmed_intake(cur, case_id)
            extraction_snapshot = _load_extraction_snapshot(cur, case_id, int(current_document.get("id") or 0))

    if not include_content_text:
        current_document.pop("contentText", None)
        for document in documents:
            document.pop("contentText", None)

    document_quality = summarize_document_quality(documents)
    snapshot_payload = {
        "caseId": case_id,
        "documentId": current_document.get("id"),
        "documentVersion": current_document.get("version"),
        "contentHash": current_document.get("contentHash"),
        "clauseCount": len(clauses),
        "extractionSnapshotId": extraction_snapshot.get("id"),
        "extractionSnapshotHash": extraction_snapshot.get("snapshotHash"),
    }
    snapshot_hash = hashlib.sha256(
        json.dumps(snapshot_payload, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()
    return {
        "case": case,
        "documents": documents,
        "currentDocument": current_document,
        "clauses": clauses,
        "clauseCount": len(clauses),
        "confirmedIntake": confirmed_intake,
        "extractionSnapshot": extraction_snapshot,
        "documentQuality": document_quality,
        "contentHash": current_document.get("contentHash"),
        "snapshotHash": snapshot_hash,
    }
