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


_CONTRACT_SEARCH_TERMS = (
    "付款", "支付", "发票", "工作日", "自然日", "验收", "交付", "续签", "终止",
    "到期", "通知", "逾期", "违约", "赔偿", "保密", "个人信息", "数据",
)


def _rerank_contract_hits(query: str, hits: list[dict]) -> list[dict]:
    terms = [term for term in _CONTRACT_SEARCH_TERMS if term in query]
    if not terms:
        return hits

    def score(hit: dict) -> float:
        text = " ".join([
            str(hit.get("title") or ""),
            str(hit.get("clauseNumber") or ""),
            str(hit.get("snippet") or ""),
            str(hit.get("content") or ""),
            str(hit.get("clauseType") or ""),
        ])
        bonus = sum(1 for term in terms if term in text)
        return bonus * 1000 + float(hit.get("score") or 0)

    return sorted(hits, key=score, reverse=True)


def _has_contract_terms(query: str) -> bool:
    return any(term in query for term in _CONTRACT_SEARCH_TERMS)


def _contract_query_terms(query: str) -> list[str]:
    terms = [term for term in _CONTRACT_SEARCH_TERMS if term in query]
    return terms or [query]


def _merge_contract_hits(primary: list[dict], secondary: list[dict]) -> list[dict]:
    merged: list[dict] = []
    seen: set[str] = set()
    for hit in [*secondary, *primary]:
        key = str(hit.get("clauseId") or hit.get("chunkId") or id(hit))
        if key in seen:
            continue
        seen.add(key)
        merged.append(hit)
    return merged


def _merge_policy_items(*groups: list[dict], limit: int) -> list[dict]:
    """Merge standard clauses and KB chunks without losing source identity."""
    merged: list[dict] = []
    seen: set[str] = set()
    for group in groups:
        for item in group:
            key = "%s:%s:%s" % (
                item.get("sourceType") or "POLICY",
                item.get("sourceId") or item.get("id") or "",
                item.get("chunkId") or "",
            )
            if key in seen:
                continue
            seen.add(key)
            merged.append(item)
            if len(merged) >= limit:
                return merged
    return merged


class ContractStore:
    """Read-only contract data access for Agent tools."""

    # ── Case ───────────────────────────────────────────────────────

    async def get_case(self, case_id: int) -> dict:
        def _get():
            with _conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """SELECT id, case_key AS caseKey, title, contract_type AS contractType,
                                  status, our_entity AS ourEntity, counterparty,
                                  our_side AS ourSide, amount, currency, department,
                                  signed_date AS signedDate,
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

    async def search_contract_clause(self, case_id: int, arguments: dict) -> list[dict]:
        query = str(arguments.get("query", "")).strip()
        top_k = max(1, min(12, int(arguments.get("topK", arguments.get("limit", 5)))))
        if not query:
            return []

        def _fallback_keyword():
            terms = _contract_query_terms(query)
            likes = [f"%{term}%" for term in terms]
            conditions = " OR ".join([
                "(c.title LIKE %s OR c.content LIKE %s OR c.clause_number LIKE %s)"
                for _ in likes
            ])
            with _conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        f"""SELECT c.id AS clauseId, c.document_id AS documentId,
                                  c.clause_number AS clauseNumber, c.title, c.content,
                                  c.clause_type AS clauseType, c.page_number AS pageNumber
                           FROM contract_clause c
                           WHERE c.case_id=%s
                             AND ({conditions})
                           ORDER BY c.id ASC LIMIT %s""",
                        [case_id] + [like for like in likes for _ in range(3)] + [max(top_k, 20)],
                    )
                    rows = [_normalize_value(r) for r in cur.fetchall()]
            return [
                {
                    **row,
                    "sourceType": "CONTRACT_CLAUSE",
                    "snippet": str(row.get("content") or "")[:220],
                    "score": 0,
                    "retrievalType": "MYSQL_KEYWORD_FALLBACK",
                }
                for row in rows
            ]

        try:
            from app.services.embedding_service import EmbeddingService
            from app.services.es_service import ESService
            embedding = EmbeddingService()
            es = ESService()
            candidate_k = max(top_k * 4, 20)
            vector = embedding.embed(query) if embedding.configured else None
            hits = es.search_contract_by_embedding(vector, case_id, candidate_k) if vector else []
            retrieval_type = "VECTOR" if hits else ""
            if not hits:
                hits = es.search_contract_by_keyword(query, case_id, candidate_k)
                retrieval_type = "KEYWORD" if hits else ""
        except Exception as exc:
            logger.warning("contract ES search failed, fallback to MySQL: %s", exc)
            hits = []
            retrieval_type = ""

        keyword_hits = await _run_sync(_fallback_keyword) if _has_contract_terms(query) else []
        if keyword_hits:
            hits = _merge_contract_hits(hits, keyword_hits)

        if not hits:
            return keyword_hits or await _run_sync(_fallback_keyword)
        hits = _rerank_contract_hits(query, hits)[:top_k]

        clause_ids = [h.get("clauseId") for h in hits if h.get("clauseId")]
        if not clause_ids:
            return hits

        def _enrich():
            placeholders = ",".join(["%s"] * len(clause_ids))
            with _conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        f"""SELECT id AS clauseId, document_id AS documentId,
                                   clause_number AS clauseNumber, title, content,
                                   clause_type AS clauseType, page_number AS pageNumber
                            FROM contract_clause
                            WHERE case_id=%s AND id IN ({placeholders})""",
                        [case_id] + clause_ids,
                    )
                    rows = {r["clauseId"]: _normalize_value(r) for r in cur.fetchall()}
            enriched = []
            for hit in hits:
                parent = rows.get(hit.get("clauseId"), {})
                enriched.append({
                    **hit,
                    **parent,
                    "snippet": hit.get("snippet") or str(parent.get("content") or "")[:220],
                    "retrievalType": retrieval_type,
                })
            return enriched
        return await _run_sync(_enrich)

    async def get_clause_detail(self, case_id: int, arguments: dict) -> dict:
        clause_id = int(arguments.get("clauseId", 0))
        def _get():
            with _conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """SELECT id AS clauseId, document_id AS documentId,
                                  clause_number AS clauseNumber, title, content,
                                  clause_type AS clauseType, page_number AS pageNumber,
                                  semantic_elements AS semanticElements
                           FROM contract_clause
                           WHERE case_id=%s AND id=%s
                           LIMIT 1""",
                        (case_id, clause_id),
                    )
                    row = _normalize_value(cur.fetchone() or {})
                    if isinstance(row.get("semanticElements"), str):
                        try:
                            row["semanticElements"] = json.loads(row["semanticElements"])
                        except Exception:
                            pass
                    return row
        return await _run_sync(_get)

    async def list_timeline(self, case_id: int, arguments: dict) -> list[dict]:
        limit = max(1, min(80, int(arguments.get("limit", 30))))
        return await self._timeline(case_id, "", limit)

    async def search_timeline(self, case_id: int, arguments: dict) -> list[dict]:
        query = str(arguments.get("query", "")).strip()
        limit = max(1, min(50, int(arguments.get("limit", 20))))
        return await self._timeline(case_id, query, limit)

    async def _timeline(self, case_id: int, query: str, limit: int) -> list[dict]:
        def _get():
            params: list[Any] = [case_id]
            where = "n.case_id=%s"
            if query:
                like = f"%{query}%"
                where += """ AND (
                    n.label LIKE %s OR n.node_type LIKE %s OR n.condition_text LIKE %s
                    OR n.business_meaning LIKE %s OR c.title LIKE %s OR c.content LIKE %s
                )"""
                params.extend([like, like, like, like, like, like])
            params.append(limit)
            with _conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        f"""SELECT n.id, n.document_id AS documentId, n.clause_id AS clauseId,
                                   n.node_type AS nodeType, n.label, n.node_date AS nodeDate,
                                   n.condition_text AS conditionText,
                                   n.responsible_party AS responsibleParty,
                                   n.business_meaning AS businessMeaning,
                                   n.citation_json AS citationJson, n.confidence,
                                   n.source, n.status,
                                   c.clause_number AS clauseNumber, c.title AS clauseTitle
                            FROM contract_timeline_node n
                            LEFT JOIN contract_clause c ON c.id=n.clause_id
                            WHERE {where}
                            ORDER BY COALESCE(n.node_date, '9999-12-31'), n.id
                            LIMIT %s""",
                        params,
                    )
                    rows = [_normalize_value(r) for r in cur.fetchall()]
                    for row in rows:
                        if isinstance(row.get("citationJson"), str):
                            try:
                                row["citationJson"] = json.loads(row["citationJson"])
                            except Exception:
                                pass
                    return rows
        return await _run_sync(_get)

    # ── Policy knowledge search ────────────────────────────────────

    async def search_policy(self, case_id: int, arguments: dict) -> list[dict]:
        query = str(arguments.get("query", "")).strip()
        clause_type = str(arguments.get("clauseType", ""))
        limit = max(1, min(10, int(arguments.get("limit", 5))))
        standard_limit = max(1, min(3, limit // 2 or 1))
        kb_limit = max(1, limit - standard_limit)

        def _standard():
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
                q = query.lower()
                rows = [
                    r for r in rows
                    if q in (str(r.get("title") or "") + " " + str(r.get("content") or "")).lower()
                ]
            result = []
            for row in rows[:standard_limit]:
                result.append({
                    **row,
                    "sourceType": "CONTRACT_STANDARD_CLAUSE",
                    "sourceId": row.get("id"),
                    "snippet": str(row.get("content") or "")[:220],
                    "retrievalType": "MYSQL_STANDARD_CLAUSE",
                })
            return result

        async def _kb_es_search() -> list[dict]:
            if not query:
                return []
            try:
                from app.services.embedding_service import EmbeddingService
                from app.services.es_service import ESService
                embedding = EmbeddingService()
                es = ESService()
                vector = embedding.embed(query) if embedding.configured else None
                hits = es.search_kb_by_embedding(vector, kb_limit) if vector else []
                retrieval_type = "KB_VECTOR" if hits else ""
                if not hits:
                    hits = es.search_kb_by_keyword(query, kb_limit)
                    retrieval_type = "KB_KEYWORD" if hits else ""
                return [
                    {
                        **hit,
                        "sourceType": "KB_DOCUMENT",
                        "sourceId": hit.get("sourceId") or hit.get("documentId"),
                        "retrievalType": retrieval_type,
                    }
                    for hit in await _filter_allowed_kb_hits(hits, case_id, kb_limit)
                ]
            except Exception as exc:
                logger.warning("policy KB ES search failed, fallback to MySQL: %s", exc)
                return []

        async def _filter_allowed_kb_hits(hits: list[dict], current_case_id: int, max_items: int) -> list[dict]:
            document_ids = []
            for hit in hits:
                doc_id = hit.get("sourceId") or hit.get("documentId")
                if doc_id is None:
                    continue
                try:
                    document_ids.append(int(doc_id))
                except Exception:
                    continue
            document_ids = list(dict.fromkeys(document_ids))
            if not document_ids:
                return []

            def _allowed_ids() -> set[int]:
                placeholders = ",".join(["%s"] * len(document_ids))
                with _conn() as conn:
                    with conn.cursor() as cur:
                        cur.execute(
                            f"""SELECT d.id
                                FROM kb_document d
                                WHERE d.id IN ({placeholders})
                                  AND COALESCE(d.deleted,0)=0
                                  AND d.status='READY'
                                  AND (
                                    d.contract_usage_scope='GLOBAL'
                                    OR (
                                      d.contract_usage_scope='SPECIFIC_CASES'
                                      AND EXISTS (
                                        SELECT 1 FROM contract_kb_document ckd
                                        WHERE ckd.document_id=d.id AND ckd.case_id=%s
                                      )
                                    )
                                  )""",
                            document_ids + [current_case_id],
                        )
                        return {int(row["id"]) for row in cur.fetchall()}
            allowed = await _run_sync(_allowed_ids)
            result = []
            for hit in hits:
                doc_id = hit.get("sourceId") or hit.get("documentId")
                try:
                    normalized = int(doc_id)
                except Exception:
                    continue
                if normalized in allowed:
                    result.append(hit)
                if len(result) >= max_items:
                    break
            return result

        def _kb_mysql_fallback() -> list[dict]:
            if not query:
                return []
            terms = _contract_query_terms(query)
            likes = [f"%{term}%" for term in terms if term]
            if not likes:
                likes = [f"%{query}%"]
            conditions = " OR ".join([
                "(d.title LIKE %s OR c.section_title LIKE %s OR c.chunk_text LIKE %s)"
                for _ in likes
            ])
            with _conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        f"""SELECT c.id AS chunkId, c.document_id AS sourceId,
                                  c.space_id AS spaceId, d.title,
                                  c.section_title AS sectionTitle,
                                  c.source_page AS page, c.chunk_text AS content
                           FROM kb_document_chunk c
                           JOIN kb_document d ON d.id=c.document_id
                           WHERE COALESCE(c.deleted,0)=0
                             AND COALESCE(d.deleted,0)=0
                             AND d.status='READY'
                             AND (
                               d.contract_usage_scope='GLOBAL'
                               OR (
                                 d.contract_usage_scope='SPECIFIC_CASES'
                                 AND EXISTS (
                                   SELECT 1 FROM contract_kb_document ckd
                                   WHERE ckd.document_id=d.id AND ckd.case_id=%s
                                 )
                               )
                             )
                             AND ({conditions})
                           ORDER BY c.document_id DESC, c.chunk_index ASC
                           LIMIT %s""",
                        [case_id] + [like for like in likes for _ in range(3)] + [kb_limit],
                    )
                    rows = [_normalize_value(r) for r in cur.fetchall()]
            return [
                {
                    **row,
                    "sourceType": "KB_DOCUMENT",
                    "documentId": row.get("sourceId"),
                    "snippet": str(row.get("content") or "")[:220],
                    "score": 0,
                    "retrievalType": "MYSQL_KB_KEYWORD_FALLBACK",
                }
                for row in rows
            ]

        standard = await _run_sync(_standard)
        kb_hits = await _kb_es_search()
        if not kb_hits:
            kb_hits = await _run_sync(_kb_mysql_fallback)
        return _merge_policy_items(standard, kb_hits, limit=limit)

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
                        """SELECT f.id, r.rule_key AS ruleKey, f.title, f.severity,
                                  f.status, r.clause_type AS clauseType
                           FROM contract_review_finding f
                           LEFT JOIN contract_review_rule r ON r.id=f.rule_id
                           WHERE f.case_id=%s AND f.status='OPEN'""",
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

    async def verify_evidence(
        self, case_id: int, obligation_id: int = 0, timeline_node_id: int = 0
    ) -> dict:
        def _get():
            with _conn() as conn:
                with conn.cursor() as cur:
                    if timeline_node_id:
                        cur.execute(
                            """SELECT n.id, n.case_id AS caseId, n.node_type AS nodeType,
                                      n.label, n.node_date AS nodeDate,
                                      n.condition_text AS conditionText,
                                      n.business_meaning AS businessMeaning,
                                      n.responsible_party AS responsibleParty,
                                      n.citation_json AS citationJson,
                                      c.clause_number AS clauseNumber,
                                      c.title AS clauseTitle, c.content AS clauseContent
                               FROM contract_timeline_node n
                               LEFT JOIN contract_clause c ON c.id=n.clause_id
                               WHERE n.id=%s AND n.case_id=%s
                               LIMIT 1""",
                            (timeline_node_id, case_id),
                        )
                        node = _normalize_value(cur.fetchone() or {})
                        if not node:
                            return {"error": "Timeline node not found", "timelineNodeId": timeline_node_id}
                        if isinstance(node.get("citationJson"), str):
                            try:
                                node["citationJson"] = json.loads(node["citationJson"])
                            except Exception:
                                pass
                        cur.execute(
                            """SELECT d.id AS documentId, d.document_type AS documentType,
                                      file_name AS fileName, file_size AS fileSize,
                                      d.version, d.parse_status AS parseStatus,
                                      d.content_hash AS contentHash,
                                      LEFT(COALESCE(d.content_text,''), 700) AS contentSnippet,
                                      d.create_time AS createTime,
                                      CASE WHEN l.id IS NULL THEN 0 ELSE 1 END AS manuallyLinked
                               FROM contract_document d
                               LEFT JOIN contract_timeline_evidence_link l
                                 ON l.case_id=d.case_id
                                AND l.timeline_node_id=%s
                                AND l.document_id=d.id
                                AND l.check_id IS NULL
                                AND COALESCE(l.deleted,0)=0
                               WHERE d.case_id=%s
                                 AND d.document_type IN ('FULFILLMENT_EVIDENCE','ATTACHMENT','CERTIFICATE','PRICING')
                                 AND COALESCE(d.deleted,0)=0
                                 AND d.parse_status <> 'FAILED'
                               ORDER BY manuallyLinked DESC,
                                        FIELD(d.document_type,'FULFILLMENT_EVIDENCE','ATTACHMENT','CERTIFICATE','PRICING'),
                                        d.version DESC, d.id DESC
                               LIMIT 30""",
                            (timeline_node_id, case_id),
                        )
                        evidence = [_normalize_value(r) for r in cur.fetchall()]
                        linked_evidence = [item for item in evidence if item.get("manuallyLinked")]
                        if linked_evidence:
                            evidence = linked_evidence + [item for item in evidence if not item.get("manuallyLinked")]
                        missing = []
                        node_text = " ".join([
                            str(node.get("label") or ""),
                            str(node.get("businessMeaning") or ""),
                            str(node.get("conditionText") or ""),
                            str(node.get("clauseContent") or ""),
                        ])
                        required_by_type = {
                            "PAYMENT": ["付款记录或银行回单", "发票或结算凭证"],
                            "DELIVERY": ["交付报告或成果物", "签收/接收记录"],
                            "ACCEPTANCE": ["验收单或验收会议纪要", "测试数据或验收标准对照"],
                            "NOTICE": ["书面通知记录"],
                            "RENEWAL": ["续签商谈记录或审批意见"],
                            "TERMINATION": ["解除/终止通知或双方确认"],
                        }
                        node_type = str(node.get("nodeType") or "OTHER").upper()
                        missing.extend(required_by_type.get(node_type, []))
                        if "验收" in node_text and "验收单或验收会议纪要" not in missing:
                            missing.append("验收单或验收会议纪要")
                        if ("付款" in node_text or "支付" in node_text or "发票" in node_text) and "付款记录或银行回单" not in missing:
                            missing.append("付款记录或银行回单")
                        if ("交付" in node_text or "完成" in node_text or "服务" in node_text) and "交付报告或成果物" not in missing:
                            missing.append("交付报告或成果物")
                        if evidence:
                            conclusion = "NEEDS_REVIEW"
                            summary = "已找到履约证据，需按合同要求逐项人工复核。"
                            missing_after = missing
                        else:
                            conclusion = "INSUFFICIENT_EVIDENCE"
                            summary = "当前未找到可用于该节点的履约证据，无法判断是否满足合同要求。"
                            missing_after = missing or ["履约证据文件"]
                        return {
                            "timelineNodeId": timeline_node_id,
                            "node": node,
                            "requirementItems": [
                                {
                                    "requirement": node.get("businessMeaning") or node.get("label") or "合同时间节点要求",
                                    "sourceQuote": (node.get("citationJson") or {}).get("quote")
                                        if isinstance(node.get("citationJson"), dict) else "",
                                    "required": True,
                                }
                            ],
                            "evidenceDocuments": evidence,
                            "missingEvidence": missing_after,
                            "conclusion": conclusion,
                            "riskLevel": "MEDIUM" if evidence else "HIGH",
                            "confidenceLevel": "LOW" if not evidence else "MEDIUM",
                            "summary": summary,
                            "explicitConsequence": "",
                            "aiRisk": "证据不足或证据未核验时，可能导致验收延期、付款延迟或争议升级；该风险为 AI 提示，不代表合同明确约定。",
                            "suggestedActions": [
                                {"title": item, "type": "REQUEST_MATERIAL"} for item in (missing_after or [])
                            ][:5],
                        }

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
