"""Context loading and snapshot nodes for contract graphs.

Phase 1 (PRD 2026-08-14): this module no longer assembles evidence itself —
it only injects the unified EvidenceSnapshot into graph state. All four graphs
(risk review, element extraction, timeline, fulfillment) enter through the
same builder in ``graph/evidence_snapshot.py``.
"""

from __future__ import annotations

import logging
from typing import Any

from ..evidence_snapshot import load_contract_evidence_snapshot, state_copy_of_snapshot

logger = logging.getLogger(__name__)


async def load_run_context(state: dict[str, Any]) -> dict[str, Any]:
    """Phase 1: load the unified contract evidence snapshot and freeze identity."""
    run_id = state.get("run_id", 0)
    case_id = state.get("subject_id", 0)
    task_input = state.get("task_input") or {}
    analysis_workflow = task_input.get("analysisWorkflow") if isinstance(task_input, dict) else {}
    analysis_workflow = analysis_workflow if isinstance(analysis_workflow, dict) else {}
    requested_document_id = int(analysis_workflow.get("documentId") or task_input.get("documentId") or 0)
    try:
        shared_snapshot = load_contract_evidence_snapshot(
            int(case_id),
            requested_document_id=requested_document_id,
            include_content_text=False,
        )
    except Exception as exc:
        logger.warning("Failed to load shared contract evidence snapshot: %s", exc)
        shared_snapshot = {
            "case": state.get("case_snapshot") or {},
            "documents": [],
            "currentDocument": {},
            "clauses": [],
            "clauseCount": 0,
            "confirmedIntake": {},
            "extractionSnapshot": {},
            "documentQuality": {},
            "snapshotHash": "",
            "snapshot_hash": "",
        }

    case_snapshot = dict(shared_snapshot.get("case") or {})
    extraction_snapshot = shared_snapshot.get("extractionSnapshot") or {}
    elements = extraction_snapshot.get("elements") or []
    if elements:
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
    document_snapshot = shared_snapshot.get("documents") or []
    current_main_document = shared_snapshot.get("currentDocument") or {}
    document_quality = shared_snapshot.get("documentQuality") or {}
    snapshot_hash = str(
        shared_snapshot.get("snapshot_hash")
        or shared_snapshot.get("snapshotHash")
        or ""
    )
    analysis_workflow = {
        **analysis_workflow,
        "documentId": current_main_document.get("id") or analysis_workflow.get("documentId"),
        "documentVersion": current_main_document.get("version") or analysis_workflow.get("documentVersion"),
        "evidenceSnapshotHash": snapshot_hash or analysis_workflow.get("evidenceSnapshotHash"),
    }

    workflow_observation = {
        "callId": f"graph-analysis-snapshot-{run_id}",
        "planStepId": "load_shared_evidence_snapshot",
        "toolName": "loadContractAnalysisSnapshot",
        "arguments": {
            "workflowId": analysis_workflow.get("workflowId"),
            "documentId": analysis_workflow.get("documentId"),
            "documentVersion": analysis_workflow.get("documentVersion"),
        },
        "output": {
            "evidenceSnapshotHash": analysis_workflow.get("evidenceSnapshotHash"),
            "documentCount": len(document_snapshot),
            "selectedDocumentId": current_main_document.get("id"),
            "clauseCount": shared_snapshot.get("clauseCount"),
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
        "evidence_snapshot": state_copy_of_snapshot(shared_snapshot),
        "contract_evidence_snapshot": shared_snapshot.get("clauses") or [],
        "document_quality": document_quality,
        "extraction_snapshot": extraction_snapshot,
        "observations": [workflow_observation],
    }


def freeze_case_snapshot(state: dict[str, Any]) -> dict[str, Any]:
    """Freeze immutable run facts: case ID, document version, ourSide, scoring version."""
    snapshot = state.get("case_snapshot") or {}
    analysis_workflow = state.get("analysis_workflow") or {}
    document_snapshot = state.get("document_snapshot") or []
    evidence_snapshot = state.get("evidence_snapshot") or {}
    evidence_hash = (
        analysis_workflow.get("evidenceSnapshotHash")
        or evidence_snapshot.get("snapshot_hash")
        or evidence_snapshot.get("snapshotHash")
    )
    document_version = (
        analysis_workflow.get("documentVersion")
        or evidence_snapshot.get("document_version")
    )
    return {
        "state_revision": state.get("state_revision", 0) + 1,
        "current_node": "freeze_case_snapshot",
        "analysis_workflow": {
            **analysis_workflow,
            "evidenceSnapshotHash": evidence_hash or analysis_workflow.get("evidenceSnapshotHash"),
            "documentVersion": document_version or analysis_workflow.get("documentVersion"),
        },
        "document_snapshot": document_snapshot,
        "knowledge_snapshot": [],
        "plan": {
            "caseId": snapshot.get("id"),
            "contractType": snapshot.get("contractType", "SERVICE_PROCUREMENT"),
            "ourSide": snapshot.get("ourSide", ""),
            "frozenAt": str(snapshot.get("updateTime", "")),
            "evidenceSnapshotHash": evidence_hash,
            "documentVersion": document_version or analysis_workflow.get("documentVersion"),
            "documentQuality": state.get("document_quality") or {},
            "reuseParsedEvidence": True,
            "extractionSnapshotId": (state.get("extraction_snapshot") or {}).get("id"),
            "extractionStatus": (state.get("extraction_snapshot") or {}).get("status"),
        },
    }
