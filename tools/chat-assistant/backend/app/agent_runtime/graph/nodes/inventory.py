"""Clause inventory node — derives the inventory from the unified evidence snapshot.

PRD Phase 1: the inventory must come from the same clause source every graph
sees (the current main document's clause catalog), not from a separate
case-wide query. A DB fallback keeps old-checkpoint resumes working.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def _inventory_from_snapshot(evidence_snapshot: dict[str, Any]) -> dict[str, Any]:
    catalog = evidence_snapshot.get("clause_catalog") or []
    clause_types: dict[str, int] = {}
    for entry in catalog:
        clause_type = str(entry.get("clauseType") or "OTHER")
        clause_types[clause_type] = clause_types.get(clause_type, 0) + 1
    clauses = [
        {
            "id": entry.get("clauseId"),
            "clauseType": entry.get("clauseType") or "OTHER",
            "clauseNumber": entry.get("clauseNumber"),
            "title": entry.get("title"),
            "charCount": entry.get("charCount") or 0,
            "page": entry.get("pageNumber"),
        }
        for entry in catalog
    ]
    return {
        "totalCount": int(evidence_snapshot.get("clauseCount") or len(catalog)),
        "clauseTypes": clause_types,
        "unclassifiedCount": clause_types.get("OTHER", 0),
        "clauses": clauses,
        "documentId": evidence_snapshot.get("document_id"),
        "documentVersion": evidence_snapshot.get("document_version"),
        "snapshotHash": evidence_snapshot.get("snapshot_hash"),
    }


def _inventory_from_db(case_id: int) -> dict[str, Any]:
    """Legacy fallback for checkpoints created before the unified snapshot."""
    from ...persistence import _conn, _normalize_value

    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT COUNT(*) AS total FROM contract_clause WHERE case_id=%s",
                (case_id,),
            )
            total = int((cur.fetchone() or {}).get("total", 0))

            cur.execute(
                """SELECT clause_type, COUNT(*) AS cnt
                   FROM contract_clause WHERE case_id=%s
                   GROUP BY clause_type""",
                (case_id,),
            )
            type_rows = [_normalize_value(r) for r in cur.fetchall()]
            clause_types = {
                str(r.get("clause_type") or "OTHER"): int(r.get("cnt", 0))
                for r in type_rows
            }

            cur.execute(
                """SELECT id, clause_type AS clauseType,
                          clause_number AS clauseNumber, title,
                          COALESCE(CHAR_LENGTH(content), 0) AS charCount,
                          page_number AS page
                   FROM contract_clause WHERE case_id=%s
                   ORDER BY clause_number, id LIMIT 200""",
                (case_id,),
            )
            clauses = [_normalize_value(r) for r in cur.fetchall()]

    return {
        "totalCount": total,
        "clauseTypes": clause_types,
        "unclassifiedCount": clause_types.get("OTHER", 0),
        "clauses": clauses,
    }


def inventory_clauses(state: dict[str, Any]) -> dict[str, Any]:
    """Build the clause inventory from the run's unified evidence snapshot.

    Writes clause_inventory to state with: totalCount, clauseTypes,
    missingKeyTypes, and per-clause metadata.
    """
    case_id = state.get("subject_id", 0)
    case_snapshot = state.get("case_snapshot") or {}
    contract_type = str(case_snapshot.get("contractType") or "SERVICE_PROCUREMENT")

    try:
        evidence_snapshot = state.get("evidence_snapshot") or {}
        if evidence_snapshot.get("clause_catalog") is not None:
            inventory = _inventory_from_snapshot(evidence_snapshot)
        else:
            logger.warning("No unified evidence snapshot in state; using legacy clause query")
            inventory = _inventory_from_db(int(case_id))

        _MANDATORY = {
            "SERVICE_PROCUREMENT": [
                "PAYMENT", "LIABILITY", "ACCEPTANCE", "CONFIDENTIALITY", "TERMINATION",
            ],
            "GOODS_PURCHASE": [
                "PAYMENT", "LIABILITY", "ACCEPTANCE", "DELIVERY", "TERMINATION",
            ],
            "NDA": ["CONFIDENTIALITY", "LIABILITY", "TERMINATION"],
        }
        mandatory = _MANDATORY.get(contract_type, _MANDATORY["SERVICE_PROCUREMENT"])
        missing = [t for t in mandatory if t not in inventory["clauseTypes"]]
        inventory["missingKeyTypes"] = missing
        inventory["contractType"] = contract_type

        return {
            "state_revision": state.get("state_revision", 0) + 1,
            "current_node": "inventory_clauses",
            "observations": state.get("observations", []) + [{
                "callId": f"graph-inventory-{case_id}",
                "planStepId": "clause_inventory",
                "toolName": "listClauseInventory",
                "arguments": {"contractType": contract_type},
                "output": {"inventory": inventory},
                "status": "DONE",
            }],
        }
    except Exception as exc:
        logger.error("Clause inventory failed: %s", exc)
        return {
            "state_revision": state.get("state_revision", 0) + 1,
            "current_node": "inventory_clauses",
            "errors": state.get("errors", []) + [{
                "node": "inventory_clauses",
                "error": str(exc),
            }],
        }
