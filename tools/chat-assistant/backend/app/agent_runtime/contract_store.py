"""Contract data access layer — Phase 4.

Provides read access to contract_case, contract_clause, contract_review_rule,
contract_standard_clause, and historical data for Agent tools.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from .persistence import _conn, _run_sync, _normalize_value

logger = logging.getLogger(__name__)


class ContractStore:
    """Read-only contract data access for Agent tools."""

    # ── Case ───────────────────────────────────────────────────────

    async def get_case(self, case_id: int) -> dict:
        def _get():
            with _conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """SELECT id, case_key AS caseKey, title, contract_type AS contractType,
                                  status, counterparty, amount, currency, department,
                                  effective_date AS effectiveDate, expiry_date AS expiryDate
                           FROM contract_case WHERE id=%s AND deleted=0""",
                        (case_id,),
                    )
                    return _normalize_value(cur.fetchone() or {})
        return await _run_sync(_get)

    async def get_parties(self, case_id: int) -> list[dict]:
        def _get():
            with _conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """SELECT party_name AS partyName, party_role AS partyRole,
                                  risk_score AS riskScore
                           FROM contract_party WHERE case_id=%s""",
                        (case_id,),
                    )
                    return [_normalize_value(r) for r in cur.fetchall()]
        return await _run_sync(_get)

    # ── Documents ──────────────────────────────────────────────────

    async def list_documents(self, case_id: int, arguments: dict) -> list[dict]:
        doc_type = str(arguments.get("documentType", ""))
        def _get():
            with _conn() as conn:
                with conn.cursor() as cur:
                    sql = """SELECT id, document_type AS documentType, file_name AS fileName,
                                    version, parse_status AS parseStatus, page_count AS pageCount
                             FROM contract_document WHERE case_id=%s"""
                    params = [case_id]
                    if doc_type:
                        sql += " AND document_type=%s"; params.append(doc_type)
                    sql += " ORDER BY version DESC LIMIT 10"
                    cur.execute(sql, params)
                    return [_normalize_value(r) for r in cur.fetchall()]
        return await _run_sync(_get)

    # ── Clauses ────────────────────────────────────────────────────

    async def read_clauses(self, case_id: int, arguments: dict) -> list[dict]:
        clause_type = str(arguments.get("clauseType", ""))
        limit = max(1, min(20, int(arguments.get("limit", 10))))
        def _get():
            with _conn() as conn:
                with conn.cursor() as cur:
                    sql = """SELECT id, clause_number AS clauseNumber, title, content,
                                    clause_type AS clauseType, page_number AS pageNumber,
                                    semantic_elements AS semanticElements
                             FROM contract_clause WHERE case_id=%s"""
                    params = [case_id]
                    if clause_type:
                        sql += " AND clause_type=%s"; params.append(clause_type)
                    sql += " LIMIT %s"; params.append(limit)
                    cur.execute(sql, params)
                    rows = [_normalize_value(r) for r in cur.fetchall()]
                    # Parse semantic_elements JSON
                    for r in rows:
                        if isinstance(r.get("semanticElements"), str):
                            try: r["semanticElements"] = json.loads(r["semanticElements"])
                            except: pass
                    return rows
        return await _run_sync(_get)

    # ── Policy knowledge search ────────────────────────────────────

    async def search_policy(self, case_id: int, arguments: dict) -> list[dict]:
        query = str(arguments.get("query", "")).lower()
        clause_type = str(arguments.get("clauseType", ""))
        limit = max(1, min(10, int(arguments.get("limit", 5))))
        def _get():
            with _conn() as conn:
                with conn.cursor() as cur:
                    sql = """SELECT id, clause_type AS clauseType, title, content,
                                    is_mandatory AS isMandatory, version
                             FROM contract_standard_clause
                             WHERE is_active=1"""
                    params = []
                    if clause_type:
                        sql += " AND clause_type=%s"; params.append(clause_type)
                    sql += " ORDER BY version DESC LIMIT 20"
                    cur.execute(sql, params)
                    rows = [_normalize_value(r) for r in cur.fetchall()]
            if query:
                rows = [r for r in rows if query in str(r.get("title","") + str(r.get("content","")).lower())]
            return rows[:limit]
        return await _run_sync(_get)

    # ── Standard clause matching ───────────────────────────────────

    async def find_standard_clause(self, arguments: dict) -> list[dict]:
        clause_type = str(arguments.get("clauseType", ""))
        clause_text = str(arguments.get("clauseText", ""))
        def _get():
            with _conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """SELECT id, clause_type AS clauseType, title, content,
                                  semantic_elements AS semanticElements,
                                  is_mandatory AS isMandatory,
                                  negotiation_bottom_line AS negotiationBottomLine, version
                           FROM contract_standard_clause
                           WHERE is_active=1 AND clause_type=%s
                           ORDER BY version DESC LIMIT 5""",
                        (clause_type,),
                    )
                    rows = [_normalize_value(r) for r in cur.fetchall()]
                    for r in rows:
                        if isinstance(r.get("semanticElements"), str):
                            try: r["semanticElements"] = json.loads(r["semanticElements"])
                            except: pass
                    return rows
        return await _run_sync(_get)

    # ── Historical decisions ───────────────────────────────────────

    async def search_historical(self, case_id: int, arguments: dict) -> list[dict]:
        query = str(arguments.get("query", "")).lower()
        limit = max(1, min(10, int(arguments.get("limit", 5))))
        def _get():
            with _conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """SELECT f.id, f.title, f.severity, f.status, f.contract_citation AS contractCitation,
                                  f.policy_citation AS policyCitation, c.case_key AS caseKey
                           FROM contract_review_finding f
                           JOIN contract_case c ON c.id = f.case_id
                           WHERE f.case_id != %s
                           ORDER BY f.update_time DESC LIMIT 50""",
                        (case_id,),
                    )
                    rows = [_normalize_value(r) for r in cur.fetchall()]
            if query:
                rows = [r for r in rows if query in str(r.get("title","") + str(r.get("description","")).lower())]
            return rows[:limit]
        return await _run_sync(_get)

    # ── Rule evaluation ────────────────────────────────────────────

    async def evaluate_rules(self, case_id: int, arguments: dict) -> list[dict]:
        """Run all active rules for the case's contract type and return findings."""
        rule_set = str(arguments.get("ruleSet", "SERVICE_PROCUREMENT_V1"))
        clause_type_filter = str(arguments.get("clauseType", ""))
        def _get():
            with _conn() as conn:
                with conn.cursor() as cur:
                    # Get case info
                    cur.execute("SELECT contract_type FROM contract_case WHERE id=%s", (case_id,))
                    case_row = cur.fetchone()
                    ct = case_row["contract_type"] if case_row else "SERVICE_PROCUREMENT"

                    # Determine rule set
                    if not rule_set or rule_set == "SERVICE_PROCUREMENT_V1":
                        rule_set_name = "SERVICE_PROCUREMENT_V1"
                    else:
                        rule_set_name = rule_set

                    # Load active rules
                    sql = """SELECT id, rule_key AS ruleKey, rule_set AS ruleSet,
                                    clause_type AS clauseType, title, description,
                                    check_type AS checkType, check_config AS checkConfig,
                                    severity, weight, is_veto AS isVeto
                             FROM contract_review_rule
                             WHERE rule_set=%s AND is_active=1"""
                    params = [rule_set_name]
                    if clause_type_filter:
                        sql += " AND clause_type=%s"; params.append(clause_type_filter)
                    cur.execute(sql, params)
                    rules = [_normalize_value(r) for r in cur.fetchall()]

                    # Load case clauses
                    cur.execute("""SELECT id, clause_type AS clauseType, title, content,
                                          semantic_elements AS semanticElements
                                   FROM contract_clause WHERE case_id=%s""", (case_id,))
                    clauses = [_normalize_value(r) for r in cur.fetchall()]

            # Evaluate each rule against clauses (simple keyword/field checks)
            findings = []
            for rule in rules:
                check_type = str(rule.get("checkType", "MISSING"))
                check_config = rule.get("checkConfig")
                if isinstance(check_config, str):
                    try: check_config = json.loads(check_config)
                    except: check_config = {}

                violated = False
                detail = ""

                if check_type == "MISSING":
                    # Check if any clause of this type exists
                    matching = [c for c in clauses if str(c.get("clauseType","")) == str(rule.get("clauseType",""))]
                    if not matching:
                        violated = True
                        detail = f"未找到{rule.get('clauseType','')}类型条款"

                elif check_type == "CONTAINS" and isinstance(check_config, dict):
                    keywords = check_config.get("keywords", [])
                    matching = [c for c in clauses if str(c.get("clauseType","")) == str(rule.get("clauseType",""))]
                    if matching:
                        content = str(matching[0].get("content", "")).lower()
                        if not any(kw.lower() in content for kw in keywords):
                            violated = True
                            detail = f"条款中未包含必要关键词: {keywords}"

                elif check_type == "THRESHOLD" and isinstance(check_config, dict):
                    matching = [c for c in clauses if str(c.get("clauseType","")) == str(rule.get("clauseType",""))]
                    if matching:
                        sem = matching[0].get("semanticElements")
                        if isinstance(sem, str):
                            try: sem = json.loads(sem)
                            except: sem = {}
                        field_val = sem.get(check_config.get("field", "")) if sem else None
                        if field_val is not None:
                            op = check_config.get("operator", "gte")
                            target = check_config.get("value", 0)
                            if op == "gte" and float(field_val) < target:
                                violated = True
                                detail = f"{check_config.get('field')}={field_val} 低于要求 {target}"
                            elif op == "lte" and float(field_val) > target:
                                violated = True
                                detail = f"{check_config.get('field')}={field_val} 超出上限 {target}"

                elif check_type == "SEMANTIC" and isinstance(check_config, dict):
                    forbidden = check_config.get("forbidden", [])
                    matching = [c for c in clauses if str(c.get("clauseType","")) == str(rule.get("clauseType",""))]
                    if matching:
                        content = str(matching[0].get("content", ""))
                        for fw in forbidden:
                            if fw in content:
                                violated = True
                                detail = f"发现禁止措辞: '{fw}'"
                                break

                if violated:
                    findings.append({
                        "ruleId": rule.get("id"),
                        "ruleKey": rule.get("ruleKey"),
                        "ruleTitle": rule.get("title"),
                        "severity": rule.get("severity"),
                        "isVeto": rule.get("isVeto"),
                        "clauseType": rule.get("clauseType"),
                        "detail": detail,
                        "description": rule.get("description"),
                    })

            return findings
        return await _run_sync(_get)

    async def get_active_rules(self, rule_set: str) -> list[dict]:
        def _get():
            with _conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """SELECT id, rule_key AS ruleKey, rule_set AS ruleSet,
                                  clause_type AS clauseType, title, severity, weight, is_veto AS isVeto
                           FROM contract_review_rule WHERE is_active=1 AND rule_set=%s""",
                        (rule_set or "SERVICE_PROCUREMENT_V1",),
                    )
                    return [_normalize_value(r) for r in cur.fetchall()]
        return await _run_sync(_get)

    async def get_open_findings(self, case_id: int) -> list[dict]:
        def _get():
            with _conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """SELECT id, rule_key AS ruleKey, title, severity, status,
                                  clause_type AS clauseType
                           FROM contract_review_finding
                           WHERE case_id=%s AND status='OPEN'""",
                        (case_id,),
                    )
                    return [_normalize_value(r) for r in cur.fetchall()]
        return await _run_sync(_get)


    # ── Obligation extraction (Phase 6) ────────────────────────────

    async def extract_obligations(self, case_id: int, arguments: dict) -> list[dict]:
        import json
        clause_types = arguments.get("clauseTypes") or ["PAYMENT","DELIVERY","ACCEPTANCE","NOTICE","RENEWAL"]
        if isinstance(clause_types, str):
            clause_types = json.loads(clause_types)
        def _get():
            with _conn() as conn:
                with conn.cursor() as cur:
                    ph = ",".join(["%s"]*len(clause_types))
                    cur.execute(
                        f"""SELECT id, clause_type AS clauseType, title, content,
                                   semantic_elements AS semanticElements, clause_number AS clauseNumber
                            FROM contract_clause WHERE case_id=%s AND clause_type IN ({ph}) LIMIT 20""",
                        [case_id] + list(clause_types))
                    clauses = [_normalize_value(r) for r in cur.fetchall()]
                    for c in clauses:
                        if isinstance(c.get("semanticElements"), str):
                            try: c["semanticElements"] = json.loads(c["semanticElements"])
                            except: pass
            ob_map = {
                "PAYMENT": [("付款义务","按合同约定支付款项"),("发票义务","按时开具合规发票")],
                "DELIVERY": [("交付义务","按时交付约定的产品或服务")],
                "ACCEPTANCE": [("验收义务","在约定时间内完成验收")],
                "NOTICE": [("通知义务","按合同约定发送通知"),("续签通知","在规定时间内发出续签或终止通知")],
                "RENEWAL": [("续签评估","在合同到期前完成续签评估")],
            }
            obs = []
            for c in clauses:
                ct = str(c.get("clauseType",""))
                for t,d in ob_map.get(ct,[]):
                    obs.append({"title":f"{t} — {c.get("clauseNumber",c.get("title",""))}",
                        "obligationType":ct,"description":d,"sourceClauseId":c.get("id"),
                        "evidenceRequired":1 if ct in ("PAYMENT","DELIVERY") else 0})
            return obs
        return await _run_sync(_get)

    async def verify_evidence(self, obligation_id: int) -> dict:
        def _get():
            with _conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """SELECT o.id, o.title, o.status, o.evidence_required,
                                  d.id AS docId, d.file_name AS docFileName
                           FROM contract_obligation o LEFT JOIN contract_document d
                           ON d.case_id=o.case_id AND d.document_type='FULFILLMENT_EVIDENCE'
                           WHERE o.id=%s""", (obligation_id,))
                    rows = [_normalize_value(r) for r in cur.fetchall()]
                    if not rows: return {"error":"Obligation not found"}
                    o = rows[0]; has = any(r.get("docId") for r in rows)
                    return {"obligationId":o.get("id"),"title":o.get("title"),
                        "status":o.get("status"),"evidenceRequired":bool(o.get("evidenceRequired")),
                        "hasEvidence":has,"verified":has}
        return await _run_sync(_get)

    # ── Version comparison (Phase 7) ───────────────────────────────

    async def compare_versions(self, case_id: int, base_v: int, new_v: int) -> dict:
        def _get():
            with _conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """SELECT id, version, file_name AS fileName, content_hash AS contentHash
                           FROM contract_document WHERE case_id=%s AND version IN (%s,%s) ORDER BY version""",
                        (case_id, base_v, new_v))
                    docs = [_normalize_value(r) for r in cur.fetchall()]
                    if len(docs)<2: return {"error":"Both versions must exist","docs":docs}
                    dids = [d["id"] for d in docs]
                    cur.execute(
                        """SELECT document_id, clause_type AS clauseType, clause_number AS clauseNumber,
                                  title, content FROM contract_clause WHERE document_id IN (%s,%s)
                                  ORDER BY clause_type, clause_number""",
                        (dids[0], dids[1]))
                    all_c = [_normalize_value(r) for r in cur.fetchall()]
            base_c = {f"{c.get("clauseType")}:{c.get("clauseNumber")}":c for c in all_c if c.get("document_id")==dids[0]}
            new_c = {f"{c.get("clauseType")}:{c.get("clauseNumber")}":c for c in all_c if c.get("document_id")==dids[1]}
            added = [c for k,c in new_c.items() if k not in base_c]
            removed = [c for k,c in base_c.items() if k not in new_c]
            changed = []
            for k in set(base_c)&set(new_c):
                if base_c[k].get("content","") != new_c[k].get("content",""):
                    changed.append({"clauseKey":k,"base":base_c[k],"new":new_c[k]})
            return {"baseVersion":base_v,"newVersion":new_v,"added":len(added),"removed":len(removed),
                "changed":len(changed),"addedClauses":added,"removedClauses":removed,
                "changedClauses":changed,"summary":f"Add {len(added)} del {len(removed)} mod {len(changed)}"}
        return await _run_sync(_get)
