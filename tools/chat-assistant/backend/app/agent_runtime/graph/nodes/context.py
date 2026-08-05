"""Context loading and snapshot nodes for contract review graph."""

from __future__ import annotations

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
            "reuseParsedEvidence": True,
        },
        "status": "DONE",
    }

    return {
        "state_revision": state.get("state_revision", 0) + 1,
        "current_node": "load_run_context",
        "case_snapshot": case_snapshot,
        "analysis_workflow": analysis_workflow,
        "document_snapshot": document_snapshot,
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
            "reuseParsedEvidence": True,
        },
    }
