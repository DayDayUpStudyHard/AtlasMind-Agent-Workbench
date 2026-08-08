"""Context loading and snapshot nodes for contract review graph."""

from __future__ import annotations

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)


async def load_run_context(state: dict[str, Any]) -> dict[str, Any]:
    """Phase 1: Load contract case and freeze identity."""
    run_id = state.get("run_id", 0)
    case_id = state.get("subject_id", 0)
    case_snapshot = state.get("case_snapshot") or {}
    task_input = state.get("task_input") or {}
    analysis_workflow = task_input.get("analysisWorkflow") if isinstance(task_input, dict) else {}
    analysis_workflow = analysis_workflow if isinstance(analysis_workflow, dict) else {}

    if not case_snapshot:
        try:
            from ...persistence import _conn

            def _load():
                with _conn() as conn:
                    with conn.cursor() as cur:
                        cur.execute(
                            """SELECT id, case_key AS caseKey, title, contract_type AS contractType,
                                      status, our_entity AS ourEntity, counterparty,
                                      our_side AS ourSide, amount, currency,
                                      signed_date AS signedDate, effective_date AS effectiveDate,
                                      expiry_date AS expiryDate, department
                               FROM contract_case WHERE id=%s AND deleted=0""",
                            (case_id,),
                        )
                        row = cur.fetchone()
                        if row:
                            from ...persistence import _normalize_value
                            return _normalize_value(row)
                        return {}

            case_snapshot = await _load() if False else {}
            # For sync simplicity in graph nodes, use sync _conn directly
            from ...persistence import _conn
            with _conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """SELECT id, case_key AS caseKey, title, contract_type AS contractType,
                                  status, our_entity AS ourEntity, counterparty,
                                  our_side AS ourSide, amount, currency,
                                  signed_date AS signedDate, effective_date AS effectiveDate,
                                  expiry_date AS expiryDate, department
                           FROM contract_case WHERE id=%s AND deleted=0""",
                        (case_id,),
                    )
                    row = cur.fetchone()
                    if row:
                        from ...persistence import _normalize_value
                        case_snapshot = _normalize_value(row)
        except Exception as exc:
            logger.warning("Failed to load case snapshot: %s", exc)

    document_snapshot: list[dict[str, Any]] = []
    extraction_snapshot: dict[str, Any] = {}
    try:
        from ...persistence import _conn, _normalize_value
        with _conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """SELECT id, document_type AS documentType, file_name AS fileName,
                              version, parse_status AS parseStatus, parse_quality AS parseQuality,
                              content_hash AS contentHash
                       FROM contract_document
                       WHERE case_id=%s AND COALESCE(deleted,0)=0
                       ORDER BY version DESC, id DESC""",
                    (case_id,),
                )
                document_snapshot = [_normalize_value(row) for row in cur.fetchall()]
    except Exception as exc:
        logger.warning("Failed to load contract evidence snapshot: %s", exc)

    requested_document_id = analysis_workflow.get("documentId")
    current_main_document = next(
        (
            item for item in document_snapshot
            if str(item.get("documentType") or "").upper() == "MAIN"
            and str(item.get("parseStatus") or "").upper() == "READY"
            and (not requested_document_id or str(item.get("id")) == str(requested_document_id))
        ),
        None,
    )
    if current_main_document is None and not requested_document_id:
        current_main_document = next(
            (
                item for item in document_snapshot
                if str(item.get("documentType") or "").upper() == "MAIN"
                and str(item.get("parseStatus") or "").upper() == "READY"
            ),
            None,
        )

    # Contract facts are a shared, versioned layer. Review and fulfillment
    # consume them as context but still cite the original clauses for every
    # claim, so an unconfirmed model value never becomes standalone evidence.
    try:
        if not current_main_document:
            raise LookupError("No ready main contract document for extraction snapshot")
        from ...persistence import _conn, _normalize_value
        with _conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """SELECT id, document_id AS documentId, document_version AS documentVersion,
                              content_hash AS contentHash, status, snapshot_hash AS snapshotHash,
                              schema_version AS schemaVersion, prompt_version AS promptVersion,
                              retrieval_version AS retrievalVersion
                       FROM contract_extraction_snapshot
                       WHERE case_id=%s
                         AND document_id=%s
                         AND status IN ('CONFIRMED','READY_FOR_CONFIRMATION')
                       ORDER BY (status='CONFIRMED') DESC, id DESC
                       LIMIT 1""",
                    (case_id, current_main_document.get("id")),
                )
                snapshot_row = cur.fetchone()
                if snapshot_row:
                    extraction_snapshot = _normalize_value(snapshot_row)
                    cur.execute(
                        """SELECT id, element_key AS elementKey, category,
                                  raw_value AS rawValue, normalized_value_json AS normalizedValue,
                                  status, confidence, source, applicable, occurrence_no AS occurrenceNo,
                                  validation_json AS validation
                           FROM contract_extracted_element
                           WHERE snapshot_id=%s
                           ORDER BY id ASC""",
                        (extraction_snapshot.get("id"),),
                    )
                    elements = [_normalize_value(row) for row in cur.fetchall()]
                    for element in elements:
                        for key in ("normalizedValue", "validation"):
                            if isinstance(element.get(key), str):
                                try:
                                    element[key] = json.loads(element[key])
                                except Exception:
                                    pass
                    extraction_snapshot["elements"] = elements
                    # Give the LLM a compact fact index while keeping the full
                    # source clauses in domain retrieval as the citation base.
                    case_snapshot = dict(case_snapshot or {})
                    case_snapshot["extractedFacts"] = [
                        {
                            "elementKey": item.get("elementKey"),
                            "rawValue": item.get("rawValue"),
                            "normalizedValue": item.get("normalizedValue"),
                            "status": item.get("status"),
                            "confidence": item.get("confidence"),
                        }
                        for item in elements[:40]
                    ]
    except Exception as exc:
        logger.info("No reusable contract extraction snapshot available: %s", exc)

    from ...evidence import summarize_document_quality
    document_quality = summarize_document_quality(document_snapshot)

    workflow_observation = {
        "callId": f"graph-analysis-snapshot-{run_id}",
        "planStepId": "load_analysis_snapshot",
        "toolName": "loadContractAnalysisSnapshot",
        "arguments": {
            "workflowId": analysis_workflow.get("workflowId"),
            "documentId": analysis_workflow.get("documentId"),
            "documentVersion": analysis_workflow.get("documentVersion"),
        },
        "output": {
            "evidenceSnapshotHash": analysis_workflow.get("evidenceSnapshotHash"),
            "documentCount": len(document_snapshot),
            "selectedDocumentId": current_main_document.get("id") if current_main_document else None,
            "documentQuality": document_quality,
            "reuseParsedEvidence": True,
            "extractionSnapshotId": extraction_snapshot.get("id"),
            "extractionStatus": extraction_snapshot.get("status"),
            "extractedElementCount": len(extraction_snapshot.get("elements") or []),
        },
        "status": "DONE",
    }

    return {
        "state_revision": state.get("state_revision", 0) + 1,
        "current_node": "load_run_context",
        "case_snapshot": case_snapshot,
        "analysis_workflow": analysis_workflow,
        "document_snapshot": document_snapshot,
        "document_quality": document_quality,
        "extraction_snapshot": extraction_snapshot,
        "observations": [workflow_observation],
    }


def freeze_case_snapshot(state: dict[str, Any]) -> dict[str, Any]:
    """Freeze immutable run facts: case ID, document version, ourSide, scoring version."""
    snapshot = state.get("case_snapshot") or {}
    analysis_workflow = state.get("analysis_workflow") or {}
    document_snapshot = state.get("document_snapshot") or []
    evidence_hash = analysis_workflow.get("evidenceSnapshotHash")
    return {
        "state_revision": state.get("state_revision", 0) + 1,
        "current_node": "freeze_case_snapshot",
        "analysis_workflow": analysis_workflow,
        "document_snapshot": document_snapshot,
        "knowledge_snapshot": [],
        "plan": {
            "caseId": snapshot.get("id"),
            "contractType": snapshot.get("contractType", "SERVICE_PROCUREMENT"),
            "ourSide": snapshot.get("ourSide", ""),
            "frozenAt": str(snapshot.get("updateTime", "")),
            "evidenceSnapshotHash": evidence_hash,
            "documentVersion": analysis_workflow.get("documentVersion"),
            "documentQuality": state.get("document_quality") or {},
            "reuseParsedEvidence": True,
            "extractionSnapshotId": (state.get("extraction_snapshot") or {}).get("id"),
            "extractionStatus": (state.get("extraction_snapshot") or {}).get("status"),
        },
    }
