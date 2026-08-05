"""Domain evidence retrieval, deterministic rules, and bounded LLM analysis."""

from __future__ import annotations

import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Awaitable

logger = logging.getLogger(__name__)


def _run_async(awaitable: Awaitable[Any]) -> Any:
    """Run an async ContractStore call from a synchronous LangGraph node."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(awaitable)
    with ThreadPoolExecutor(max_workers=1) as executor:
        return executor.submit(lambda: asyncio.run(awaitable)).result()


def _normalize_evidence(item: dict[str, Any]) -> dict[str, Any]:
    value = dict(item)
    source_type = str(value.get("sourceType") or "").upper()
    if source_type == "CONTRACT_CLAUSE" or value.get("clauseId"):
        source_type = "CONTRACT_CLAUSE"
        raw_id = value.get("clauseId") or value.get("id") or value.get("sourceId")
    elif source_type in {"CONTRACT_STANDARD_CLAUSE", "STANDARD_CLAUSE"}:
        source_type = "STANDARD_CLAUSE"
        raw_id = value.get("id") or value.get("sourceId")
    elif source_type in {"KB_CHUNK", "KB_DOCUMENT"} or value.get("chunkId"):
        source_type = "KB_CHUNK" if value.get("chunkId") else "KB_DOCUMENT"
        raw_id = value.get("chunkId") or value.get("sourceId") or value.get("documentId")
    elif source_type == "HISTORICAL_FINDING":
        raw_id = value.get("id") or value.get("sourceId")
    else:
        source_type = source_type or "UNKNOWN"
        raw_id = value.get("id") or value.get("sourceId")

    prefixed = str(raw_id or "")
    if prefixed and ":" not in prefixed:
        prefixed = f"{source_type}:{prefixed}"
    value["sourceType"] = source_type
    value["sourceId"] = prefixed
    value["clauseText"] = str(
        value.get("clauseText")
        or value.get("content")
        or value.get("fullText")
        or value.get("snippet")
        or ""
    )[:12000]
    value["snippet"] = str(
        value.get("snippet") or value.get("content") or value.get("description") or ""
    )[:1800]
    if value.get("pageNumber") is not None and value.get("page") is None:
        value["page"] = value.get("pageNumber")
    return value


def _deduplicate_evidence(items: list[dict[str, Any]], limit: int = 18) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in items:
        item = _normalize_evidence(raw)
        key = str(item.get("sourceId") or "")
        if not key or key in seen:
            continue
        seen.add(key)
        result.append(item)
        if len(result) >= limit:
            break
    return result


def _load_type_clauses(case_id: int, clause_types: list[str]) -> list[dict[str, Any]]:
    if not clause_types:
        return []
    try:
        from ...persistence import _conn, _normalize_value

        placeholders = ",".join(["%s"] * len(clause_types))
        with _conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"""SELECT id AS clauseId, document_id AS documentId,
                               clause_type AS clauseType, clause_number AS clauseNumber,
                               title, page_number AS page, LEFT(content, 1800) AS snippet
                        FROM contract_clause
                        WHERE case_id=%s AND clause_type IN ({placeholders})
                        ORDER BY id LIMIT 8""",
                    [case_id] + clause_types,
                )
                return [_normalize_value(row) for row in cur.fetchall()]
    except Exception as exc:
        logger.warning("Direct clause retrieval failed: %s", exc)
        return []


async def _retrieve_one_domain(case_id: int, task: dict[str, Any]) -> list[dict[str, Any]]:
    from ...contract_store import ContractStore

    store = ContractStore()
    queries = task.get("queries") or task.get("queryTemplates") or [task.get("objective", "")]
    query = " ".join(str(value) for value in queries if value)[:600]
    clause_types = [str(value).upper() for value in task.get("requiredClauseTypes") or []]
    evidence = _load_type_clauses(case_id, clause_types)

    contract_task = store.search_contract_clause(case_id, {"query": query, "topK": 8})
    policy_task = store.search_policy(
        case_id,
        {"query": query, "clauseType": clause_types[0] if clause_types else "", "limit": 8},
    )
    history_task = store.search_historical(case_id, {"query": str(task.get("domainName") or ""), "limit": 3})
    contract_hits, policy_hits, historical_hits = await asyncio.gather(
        contract_task, policy_task, history_task, return_exceptions=True,
    )
    for hits, source_type in (
        (contract_hits, "CONTRACT_CLAUSE"),
        (policy_hits, "KB_DOCUMENT"),
        (historical_hits, "HISTORICAL_FINDING"),
    ):
        if isinstance(hits, Exception):
            logger.warning("Domain retrieval component failed for %s: %s", task.get("domainName"), hits)
            continue
        for hit in hits or []:
            value = dict(hit)
            value.setdefault("sourceType", source_type)
            evidence.append(value)
    return _deduplicate_evidence(evidence)


def retrieve_domain_evidence(state: dict[str, Any]) -> dict[str, Any]:
    """Retrieve contract, knowledge, standard-clause, and historical evidence per domain."""
    domain_tasks = state.get("domain_tasks") or []
    case_id = int(state.get("subject_id") or 0)

    async def _retrieve_all() -> list[list[dict[str, Any]]]:
        return await asyncio.gather(*[_retrieve_one_domain(case_id, task) for task in domain_tasks])

    try:
        result_sets = _run_async(_retrieve_all())
    except Exception as exc:
        logger.exception("Domain retrieval failed: %s", exc)
        result_sets = [[] for _ in domain_tasks]

    domain_results: dict[str, list[dict[str, Any]]] = {}
    retrieval_validation: dict[str, dict[str, Any]] = {}
    observations: list[dict[str, Any]] = []
    citations: list[dict[str, Any]] = []
    for task, evidence in zip(domain_tasks, result_sets):
        key = str(task.get("domainKey") or task.get("domain") or "")
        domain_results[key] = evidence
        citations.extend(evidence)
        type_counts: dict[str, int] = {}
        for item in evidence:
            source_type = str(item.get("sourceType") or "UNKNOWN")
            type_counts[source_type] = type_counts.get(source_type, 0) + 1
        stats = next(
            (item.get("retrievalStats") for item in evidence
             if isinstance(item.get("retrievalStats"), dict)),
            {},
        )
        retrieval_validation[key] = {
            "mode": stats.get("mode") or "UNKNOWN",
            "crossValidatedCount": sum(
                1 for item in evidence if item.get("crossValidated")
            ),
            "evidenceCount": len(evidence),
            "stats": stats,
        }
        observations.append({
            "callId": f"graph-retrieval-{key}-{case_id}",
            "planStepId": f"retrieve_{key}",
            "toolName": "searchContractClause/searchPolicyKnowledge/searchHistoricalDecision",
            "arguments": {
                "domainKey": key,
                "domainName": task.get("domainName"),
                "queries": task.get("queries") or [],
                "clauseTypes": task.get("requiredClauseTypes") or [],
            },
            "output": {
                "evidenceCount": len(evidence),
                "sourceCounts": type_counts,
                "retrievalValidation": retrieval_validation[key],
            },
            "status": "DONE",
        })

    return {
        "state_revision": state.get("state_revision", 0) + 1,
        "current_node": "retrieve_domain_evidence",
        "domain_results": domain_results,
        "retrieval_validation": retrieval_validation,
        "citations": citations,
        "observations": observations,
    }


def run_deterministic_rules(state: dict[str, Any]) -> dict[str, Any]:
    """Execute active deterministic rules and keep only actual violations."""
    case_id = int(state.get("subject_id") or 0)
    case_snapshot = state.get("case_snapshot") or {}
    contract_type = str(case_snapshot.get("contractType") or "SERVICE_PROCUREMENT")
    try:
        from ...contract_store import ContractStore

        findings = _run_async(ContractStore().evaluate_rules(case_id, {
            "ruleSet": f"{contract_type}_V1",
        }))
    except Exception as exc:
        logger.error("Deterministic rule evaluation failed: %s", exc)
        findings = []

    return {
        "state_revision": state.get("state_revision", 0) + 1,
        "current_node": "run_deterministic_rules",
        "rule_findings": findings,
        "observations": [{
            "callId": f"graph-rules-{case_id}",
            "planStepId": "run_rules",
            "toolName": "evaluateReviewRules",
            "arguments": {"ruleSet": f"{contract_type}_V1"},
            "output": {"violationCount": len(findings), "findings": findings},
            "status": "DONE",
        }],
    }


def retrieve_fulfillment_evidence(state: dict[str, Any]) -> dict[str, Any]:
    """Retrieve the timeline clause and uploaded proof before judging it."""
    case_id = int(state.get("subject_id") or 0)
    task_input = state.get("task_input") or {}
    timeline_node_id = int(task_input.get("timelineNodeId") or 0)

    async def _retrieve() -> tuple[dict[str, Any], list[dict[str, Any]]]:
        from ...contract_store import ContractStore

        store = ContractStore()
        verification = await store.verify_evidence(
            case_id,
            timeline_node_id=timeline_node_id,
        )
        node = verification.get("node") or {}
        query = " ".join(
            str(value) for value in (
                node.get("label"), node.get("businessMeaning"),
                node.get("conditionText"), node.get("clauseContent"),
            ) if value
        )[:600]
        contract_hits = await store.search_contract_clause(
            case_id, {"query": query, "topK": 6}
        ) if query else []
        return verification, contract_hits

    try:
        verification, contract_hits = _run_async(_retrieve())
    except Exception as exc:
        logger.exception("Fulfillment evidence retrieval failed: %s", exc)
        verification, contract_hits = {"error": str(exc), "evidenceDocuments": []}, []

    evidence_documents = []
    for raw in verification.get("evidenceDocuments") or []:
        item = dict(raw)
        document_id = item.get("documentId") or item.get("id")
        item["sourceType"] = "FULFILLMENT_DOCUMENT"
        item["sourceId"] = f"FULFILLMENT_DOCUMENT:{document_id}" if document_id else ""
        item["content"] = item.get("contentText") or item.get("snippet") or ""
        evidence_documents.append(item)

    normalized_contract_hits = _deduplicate_evidence(contract_hits, limit=8)
    citations = evidence_documents + normalized_contract_hits
    observation = {
        "callId": f"graph-fulfillment-retrieval-{case_id}-{timeline_node_id}",
        "planStepId": "retrieve_fulfillment_evidence",
        "toolName": "verifyFulfillmentEvidence/searchContractClause",
        "arguments": {"timelineNodeId": timeline_node_id},
        "output": {
            "evidenceDocuments": evidence_documents,
            "contractEvidence": normalized_contract_hits,
            "missingEvidence": verification.get("missingEvidence") or [],
            "conclusion": verification.get("conclusion"),
        },
        "status": "DONE" if not verification.get("error") else "FAILED",
    }
    return {
        "state_revision": state.get("state_revision", 0) + 1,
        "current_node": "retrieve_fulfillment_evidence",
        "citations": citations,
        "retrieval_validation": {
            "fulfillment": {
                "mode": "CONTRACT_CLAUSE_PLUS_UPLOADED_EVIDENCE",
                "contractEvidenceCount": len(normalized_contract_hits),
                "uploadedEvidenceCount": len(evidence_documents),
            }
        },
        "observations": [observation],
    }


def _citation_fields(evidence: list[dict[str, Any]], ids: list[str]) -> tuple[list[str], list[str]]:
    valid = {str(item.get("sourceId") or ""): item for item in evidence}
    selected = [value for value in ids if value in valid]
    contract = [value for value in selected if value.startswith("CONTRACT_CLAUSE:")]
    policy = [
        value for value in selected
        if value.startswith(("KB_CHUNK:", "KB_DOCUMENT:", "STANDARD_CLAUSE:"))
    ]
    return contract[:6], policy[:6]


def _legacy_citation(evidence: list[dict[str, Any]], source_id: str, policy: bool = False) -> dict[str, Any] | None:
    item = next((value for value in evidence if value.get("sourceId") == source_id), None)
    if not item:
        return None
    if policy:
        return {
            "ruleKey": source_id,
            "ruleTitle": item.get("title") or item.get("sectionTitle") or item.get("docTitle") or "知识依据",
            "snippet": item.get("snippet") or "",
        }
    return {
        "page": item.get("page"),
        "clause": item.get("title") or item.get("clauseNumber") or "合同条款",
        "clauseNumber": item.get("clauseNumber"),
        "snippet": item.get("snippet") or "",
    }


def _normalize_finding(raw: dict[str, Any], task: dict[str, Any],
                       evidence: list[dict[str, Any]], index: int) -> dict[str, Any] | None:
    title = str(raw.get("title") or "").strip()[:512]
    if not title:
        return None
    contract_basis = raw.get("contractBasis") if isinstance(raw.get("contractBasis"), dict) else {}
    knowledge_basis = raw.get("knowledgeBasis") if isinstance(raw.get("knowledgeBasis"), dict) else {}
    all_ids = [str(value) for value in (
        (raw.get("contractCitationIds") or [])
        + (raw.get("policyCitationIds") or [])
        + (contract_basis.get("citations") or [])
        + (knowledge_basis.get("citations") or [])
    )]
    contract_ids, policy_ids = _citation_fields(evidence, all_ids)
    contract_basis = {**contract_basis, "citations": contract_ids}
    knowledge_basis = {**knowledge_basis, "citations": policy_ids}
    has_contract = bool(contract_ids)
    has_policy = bool(policy_ids)
    evidence_status = (
        "DUAL_CITED" if has_contract and has_policy else
        "CONTRACT_ONLY" if has_contract else
        "POLICY_ONLY" if has_policy else "MISSING"
    )
    severity = str(raw.get("severity") or "MEDIUM").upper()
    confidence = str(raw.get("confidenceLevel") or "MEDIUM").upper()
    review_questions = [str(value) for value in raw.get("reviewQuestions") or [] if str(value).strip()]
    if severity == "HIGH" and not has_contract:
        severity = "MEDIUM"
        confidence = "LOW"
        review_questions.append("当前证据不足以支持高风险结论，请补充合同条款或由法务复核。")

    domain_key = str(task.get("domainKey") or task.get("domain") or "other")
    domain_name = str(task.get("domainName") or task.get("domain") or "其他风险")
    explanation = str(raw.get("riskExplanation") or raw.get("description") or "").strip()
    impact = str(raw.get("businessImpact") or raw.get("impact") or "").strip()
    revision = str(raw.get("revisionAdvice") or raw.get("remediationAdvice") or "").strip()
    inferred = str(raw.get("inferredConsequence") or "").strip()
    disclaimer = "AI 推断，仅供参考，不代表合同约定" if inferred else ""
    source_basis = (
        "CONTRACT_AND_POLICY" if has_contract and has_policy else
        "CONTRACT_ONLY" if has_contract else
        "POLICY_ONLY" if has_policy else "INSUFFICIENT_EVIDENCE"
    )
    clause_type = str(raw.get("clauseType") or "OTHER").upper()
    if clause_type not in {
        "LIABILITY", "PAYMENT", "CONFIDENTIALITY", "ACCEPTANCE",
        "TERMINATION", "IP", "DATA_PROTECTION", "OTHER",
    }:
        clause_type = "OTHER"
    suggested_action = str(raw.get("suggestedAction") or "REQUEST_LEGAL_REVIEW").upper()
    if suggested_action not in {
        "CREATE_NEGOTIATION_TASK", "REQUEST_MATERIAL",
        "REQUEST_LEGAL_REVIEW", "SCHEDULE_REMINDER",
    }:
        suggested_action = "REQUEST_LEGAL_REVIEW"
    return {
        "findingKey": str(raw.get("findingKey") or f"{domain_key}:llm_{index + 1}")[:160],
        "clauseType": clause_type,
        "severity": severity if severity in {"HIGH", "MEDIUM", "LOW"} else "MEDIUM",
        "domainKey": domain_key,
        "domainName": domain_name,
        "sourceBasis": source_basis,
        "title": title,
        "oneLineSummary": str(raw.get("oneLineSummary") or explanation or title).strip()[:240],
        "keyPoint": str(raw.get("keyPoint") or revision or title).strip()[:240],
        "description": explanation,
        "riskExplanation": explanation,
        "impact": impact,
        "businessImpact": impact,
        "contractBasis": contract_basis,
        "knowledgeBasis": knowledge_basis,
        "explicitConsequence": str(raw.get("explicitConsequence") or "").strip(),
        "inferredConsequence": inferred,
        "inferredConsequenceDisclaimer": disclaimer,
        "remediationAdvice": revision,
        "revisionAdvice": revision,
        "negotiationAdvice": str(raw.get("negotiationAdvice") or "").strip(),
        "reviewQuestions": list(dict.fromkeys(review_questions))[:8],
        "verificationPoints": [
            str(value) for value in raw.get("verificationPoints") or [] if str(value).strip()
        ][:8],
        "suggestedAction": suggested_action,
        "contractCitationIds": contract_ids,
        "policyCitationIds": policy_ids,
        "contractCitation": _legacy_citation(evidence, contract_ids[0]) if contract_ids else None,
        "policyCitation": _legacy_citation(evidence, policy_ids[0], policy=True) if policy_ids else None,
        "evidenceStatus": evidence_status,
        "confidenceLevel": confidence if confidence in {"HIGH", "MEDIUM", "LOW"} else "LOW",
        "frontendDisplay": raw.get("frontendDisplay") if isinstance(raw.get("frontendDisplay"), dict) else {},
    }


def _fallback_rule_findings(task: dict[str, Any], evidence: list[dict[str, Any]],
                            rules: list[dict[str, Any]]) -> list[dict[str, Any]]:
    allowed_types = {str(value).upper() for value in task.get("requiredClauseTypes") or []}
    result: list[dict[str, Any]] = []
    for index, rule in enumerate(rules):
        if str(rule.get("clauseType") or "OTHER").upper() not in allowed_types:
            continue
        contract_ids = [
            str(value) for value in rule.get("contractCitationIds") or []
            if str(value).startswith("CONTRACT_CLAUSE:")
        ][:3]
        policy_ids = [
            str(item.get("sourceId")) for item in evidence
            if str(item.get("sourceType")) in {"KB_CHUNK", "KB_DOCUMENT", "STANDARD_CLAUSE"}
        ][:3]
        raw = {
            "findingKey": f"{task.get('domainKey')}:{rule.get('ruleKey') or index}",
            "clauseType": rule.get("clauseType") or "OTHER",
            "severity": rule.get("severity") or "MEDIUM",
            "title": rule.get("ruleTitle") or "规则检查发现",
            "riskExplanation": f"规则检查发现：{rule.get('detail') or rule.get('description') or '需要人工复核'}",
            "businessImpact": "模型分析未完成，当前仅保留确定性规则发现，具体影响需要法务结合合同全文复核。",
            "revisionAdvice": "根据规则要求补充或修改对应条款，并在完成后重新发起合同审查。",
            "reviewQuestions": ["请确认该规则发现是否适用于当前交易背景。"],
            "contractCitationIds": contract_ids,
            "policyCitationIds": policy_ids,
            "confidenceLevel": "LOW",
            "suggestedAction": "REQUEST_LEGAL_REVIEW",
        }
        normalized = _normalize_finding(raw, task, evidence, index)
        if normalized:
            result.append(normalized)
    return result


def draft_domain_findings(state: dict[str, Any]) -> dict[str, Any]:
    """Analyze each domain with the LLM and normalize all findings against real evidence."""
    domain_results = state.get("domain_results") or {}
    rule_findings = state.get("rule_findings") or []
    domain_tasks = state.get("domain_tasks") or []
    case_snapshot = state.get("case_snapshot") or {}
    run_id = int(state.get("run_id") or 0)

    def _analyze(task: dict[str, Any]) -> tuple[str, list[dict[str, Any]], str, str]:
        key = str(task.get("domainKey") or task.get("domain") or "")
        evidence = domain_results.get(key) or []
        allowed = {str(value).upper() for value in task.get("requiredClauseTypes") or []}
        matched_rules = [
            rule for rule in rule_findings
            if str(rule.get("clauseType") or "OTHER").upper() in allowed
        ]
        try:
            from app.services.llm_service import LLMService

            response = LLMService().analyze_contract_risk_domain(
                case_snapshot, task, evidence, matched_rules, run_id,
            )
            findings = []
            for index, raw in enumerate((response or {}).get("findings") or []):
                if not isinstance(raw, dict):
                    continue
                normalized = _normalize_finding(raw, task, evidence, index)
                if normalized:
                    findings.append(normalized)
            return key, findings[:3], "COMPLETED", str((response or {}).get("domainConclusion") or "")
        except Exception as exc:
            logger.warning("LLM domain analysis failed for %s: %s", task.get("domainName"), exc)
            fallback = _fallback_rule_findings(task, evidence, matched_rules)
            return key, fallback, "FALLBACK", str(exc)

    results: dict[str, tuple[list[dict[str, Any]], str, str]] = {}
    with ThreadPoolExecutor(max_workers=min(3, max(1, len(domain_tasks)))) as executor:
        future_map = {executor.submit(_analyze, task): task for task in domain_tasks}
        for future in as_completed(future_map):
            key, findings, status, conclusion = future.result()
            results[key] = (findings, status, conclusion)

    draft: list[dict[str, Any]] = []
    domain_analysis: dict[str, dict[str, Any]] = {}
    observations: list[dict[str, Any]] = []
    for task in domain_tasks:
        key = str(task.get("domainKey") or task.get("domain") or "")
        findings, status, conclusion = results.get(key, ([], "FALLBACK", "分析结果缺失"))
        draft.extend(findings)
        domain_analysis[key] = {
            "domainName": task.get("domainName"),
            "status": status,
            "findingCount": len(findings),
            "conclusion": conclusion[:500],
        }
        observations.append({
            "callId": f"graph-domain-analysis-{key}-{state.get('subject_id', 0)}",
            "planStepId": f"analyze_{key}",
            "toolName": "analyzeContractRiskDomain",
            "arguments": {
                "domainKey": key,
                "domainName": task.get("domainName"),
                "evidenceCount": len(domain_results.get(key) or []),
            },
            "output": {"status": status, "findingCount": len(findings), "conclusion": conclusion[:300]},
            "status": status,
        })

    return {
        "state_revision": state.get("state_revision", 0) + 1,
        "current_node": "draft_domain_findings",
        "draft_findings": draft,
        "domain_analysis": domain_analysis,
        "observations": observations,
    }
