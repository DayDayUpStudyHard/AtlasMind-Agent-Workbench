"""Clause inventory node — full clause catalogue, not limited to 20."""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def inventory_clauses(state: dict[str, Any]) -> dict[str, Any]:
    """Build full clause inventory by querying contract_store directly.

    Writes clause_inventory to state with: totalCount, clauseTypes,
    missingKeyTypes, and per-clause metadata.
    """
    case_id = state.get("subject_id", 0)
    case_snapshot = state.get("case_snapshot") or {}
    contract_type = str(case_snapshot.get("contractType") or "SERVICE_PROCUREMENT")

    try:
        from ...persistence import _conn

        with _conn() as conn:
            with conn.cursor() as cur:
                from ...persistence import _normalize_value

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
        missing = [t for t in mandatory if t not in clause_types]

        inventory = {
            "totalCount": total,
            "clauseTypes": clause_types,
            "unclassifiedCount": clause_types.get("OTHER", 0),
            "missingKeyTypes": missing,
            "clauses": clauses,
            "contractType": contract_type,
        }

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
