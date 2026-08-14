"""Domain evidence retrieval, deterministic rules, and bounded LLM analysis."""

from __future__ import annotations

import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

from ...harness.budget import record_unit_usage
from ...harness.retrieval import dedupe_pool, normalize_hit, run_async
from .fulfillment_judge import _match_score

logger = logging.getLogger(__name__)

# PRD §14-4: the shared spine lives in the harness — these were exact mirror
# copies here. Single implementation now; behavior identical.
_normalize_evidence = normalize_hit


def _deduplicate_evidence(items: list[dict[str, Any]], limit: int = 18) -> list[dict[str, Any]]:
    """Normalize + dedupe by ``sourceId`` (harness ``dedupe_pool`` dedupes
    already-normalized hits, so the normalize step stays here)."""
    return dedupe_pool([normalize_hit(item) for item in items], limit)


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
    """Retrieve contract, knowledge, standard-clause, and historical evidence per domain.

    Phase 2 (PRD): the risk graph no longer assembles retrieval itself — every
    domain task becomes one ``RetrievalRequest`` and goes through the shared
    ``RetrievalOrchestrator`` (the same entry the element-extraction graph
    uses). Legacy helpers below stay in place for compatibility.
    """
    domain_tasks = state.get("domain_tasks") or []
    case_id = int(state.get("subject_id") or 0)
    snapshot = state.get("evidence_snapshot") or {}
    clause_texts = state.get("contract_evidence_snapshot") or []

    from ...harness.models import default_retrieval_request
    from ...harness.retrieval import empty_bundle, flatten_bundle, get_orchestrator
    from ...harness.observation import ObservabilityRecorder

    orchestrator = get_orchestrator()

    domain_results: dict[str, list[dict[str, Any]]] = {}
    retrieval_validation: dict[str, dict[str, Any]] = {}
    observations: list[dict[str, Any]] = []
    citations: list[dict[str, Any]] = []
    # §7.2: one joined query per domain per invocation. The ledger is
    # copied, recorded in place, and returned with the node result — the
    # overwrite reducer needs the full accumulated ledger in one value.
    usage = dict(state.get("work_unit_usage") or {})
    for task in domain_tasks:
        key = str(task.get("domainKey") or task.get("domain") or "")
        record_unit_usage(usage, key, queries=1)
        queries = task.get("queries") or task.get("queryTemplates") or [task.get("objective", "")]
        # v1 keeps one joined query per domain (per-intent fan-out is the
        # Phase 3 v2 behavior); the orchestrator already supports variants.
        joined_query = " ".join(str(value) for value in queries if value)[:600]
        clause_types = [str(value).upper() for value in task.get("requiredClauseTypes") or []]
        request = default_retrieval_request(
            case_id, snapshot, key, [joined_query],
            clause_types=clause_types,
        )
        try:
            bundle = orchestrator.retrieve_sync(snapshot, request, clauses=clause_texts)
            status = "DONE"
            error = ""
        except Exception as exc:
            logger.exception("Orchestrated domain retrieval failed for %s: %s", key, exc)
            bundle = empty_bundle(request, [f"orchestrator failed: {exc}"])
            status = "FAILED"
            error = str(exc)[:500]

        evidence = flatten_bundle(bundle)
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
            "mode": stats.get("mode") or "MULTI_CHANNEL",
            "crossValidatedCount": sum(
                1 for item in evidence if item.get("crossValidated")
            ),
            "evidenceCount": len(evidence),
            "rerankMethods": sorted({
                str(item.get("rerankerMethod"))
                for item in evidence if item.get("rerankerMethod")
            }),
            "stats": stats,
        }
        observations.append({
            "callId": f"graph-retrieval-{key}-{case_id}",
            "planStepId": f"retrieve_{key}",
            "toolName": "retrieveEvidenceBundle",
            "arguments": {
                "domainKey": key,
                "domainName": task.get("domainName"),
                "queries": task.get("queries") or [],
                "clauseTypes": task.get("requiredClauseTypes") or [],
            },
            "output": {
                **ObservabilityRecorder.bundle_summary(bundle),
                "sourceCounts": type_counts,
                "retrievalValidation": retrieval_validation[key],
            },
            "status": status,
            "error": error,
        })

    return {
        "state_revision": state.get("state_revision", 0) + 1,
        "current_node": "retrieve_domain_evidence",
        "domain_results": domain_results,
        "retrieval_validation": retrieval_validation,
        "citations": citations,
        "observations": observations,
        "work_unit_usage": usage,
    }


def run_deterministic_rules(state: dict[str, Any]) -> dict[str, Any]:
    """Execute active deterministic rules and keep only actual violations."""
    case_id = int(state.get("subject_id") or 0)
    case_snapshot = state.get("case_snapshot") or {}
    extracted_facts = (state.get("extraction_snapshot") or {}).get("elements") or []
    contract_type = str(case_snapshot.get("contractType") or "SERVICE_PROCUREMENT")
    try:
        from ...contract_store import ContractStore

        findings = run_async(ContractStore().evaluate_rules(case_id, {
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


def compute_rerun_scope(
    previous_judgements: list[dict[str, Any]],
    current_documents: list[dict[str, Any]],
) -> dict[str, Any]:
    """PRD Phase 7, task 8: derive which requirements a new evidence set
    actually changes, so a rerun only re-judges the affected ones.

    Pure and conservative: whenever attribution fails (unmapped new/changed
    documents), the scope degrades to ALL instead of silently skipping
    requirements that may be affected.
    """
    if not previous_judgements:
        return {
            "mode": "ALL", "affectedRequirementIds": [], "changedEvidence": [],
            "newEvidence": [], "removedEvidence": [], "previousJudgements": [],
        }

    prev_docs: dict[str, dict[str, Any]] = {}
    for req in previous_judgements:
        if not isinstance(req, dict):
            continue
        for snap in req.get("evidenceSnapshot") or []:
            if not isinstance(snap, dict):
                continue
            doc_id = str(snap.get("documentId") or "")
            if doc_id:
                prev_docs.setdefault(doc_id, {
                    "version": snap.get("version"),
                    "contentHash": snap.get("contentHash"),
                })

    current_docs: dict[str, dict[str, Any]] = {}
    for doc in current_documents:
        if not isinstance(doc, dict):
            continue
        doc_id = str(doc.get("documentId") or doc.get("id") or "")
        if doc_id:
            current_docs[doc_id] = doc

    def _changed(prev: dict[str, Any] | None, cur: dict[str, Any]) -> bool:
        if not prev:
            return False
        if prev.get("contentHash") and cur.get("contentHash") and prev["contentHash"] != cur["contentHash"]:
            return True
        if prev.get("version") is not None and cur.get("version") is not None and prev["version"] != cur["version"]:
            return True
        return False

    changed = [did for did, meta in prev_docs.items()
               if did in current_docs and _changed(meta, current_docs[did])]
    new_docs = [did for did in current_docs if did not in prev_docs]
    removed = [did for did in prev_docs if did not in current_docs]

    if not changed and not new_docs and not removed:
        return {
            "mode": "UNCHANGED", "affectedRequirementIds": [], "changedEvidence": [],
            "newEvidence": [], "removedEvidence": [],
            "previousJudgements": previous_judgements,
        }

    affected: set[str] = set()
    for req in previous_judgements:
        if not isinstance(req, dict):
            continue
        cited = {
            str(snap.get("documentId") or "")
            for snap in (req.get("evidenceSnapshot") or [])
            if isinstance(snap, dict) and snap.get("documentId")
        }
        if cited & (set(changed) | set(removed)):
            affected.add(str(req.get("requirementId") or req.get("requirement") or ""))

    unmapped_new = 0
    for did in new_docs:
        doc = current_docs[did]
        matched = [
            req for req in previous_judgements
            if isinstance(req, dict)
            and _match_score(str(req.get("requirement") or ""), doc)[0] >= 2
        ]
        if matched:
            for req in matched:
                affected.add(str(req.get("requirementId") or req.get("requirement") or ""))
        else:
            unmapped_new += 1

    # Conservative degradation: evidence changed but attribution failed —
    # re-judge everything rather than silently skip affected requirements.
    if unmapped_new or ((changed or removed) and not affected):
        mode = "ALL"
    else:
        mode = "AFFECTED_ONLY"

    return {
        "mode": mode,
        "affectedRequirementIds": sorted(affected),
        "changedEvidence": changed,
        "newEvidence": new_docs,
        "removedEvidence": removed,
        "previousJudgements": previous_judgements,
    }


def _load_previous_fulfillment_judgements(case_id: int, timeline_node_id: int) -> list[dict[str, Any]]:
    """Load the latest previous FULFILLMENT_REPORT requirements for this
    timeline node (task 8's diff baseline). Missing history → empty list."""
    try:
        from ...persistence import _conn, _json_object, _normalize_value

        with _conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """SELECT content_json FROM agent_report
                       WHERE subject_type='CONTRACT_CASE' AND subject_id=%s
                         AND report_type='FULFILLMENT_REPORT'
                       ORDER BY id DESC LIMIT 3""",
                    (case_id,),
                )
                rows = cur.fetchall() or []
        for row in rows:
            content = _json_object(_normalize_value(row.get("content_json")))
            if int(content.get("timelineNodeId") or 0) == timeline_node_id:
                requirements = content.get("requirements")
                return requirements if isinstance(requirements, list) else []
        return []
    except Exception as exc:
        logger.warning("Previous fulfillment report load failed: %s", exc)
        return []


def retrieve_fulfillment_evidence(state: dict[str, Any]) -> dict[str, Any]:
    """Retrieve the timeline clause and uploaded proof before judging it."""
    case_id = int(state.get("subject_id") or 0)
    task_input = state.get("task_input") or {}
    timeline_node_id = int(task_input.get("timelineNodeId") or 0)
    node: dict[str, Any] = {}

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
        verification, contract_hits = run_async(_retrieve())
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

    # PRD Phase 7, task 8: diff the uploaded evidence against the previous
    # run's snapshot — new material only re-runs the requirements it affects.
    previous_judgements = _load_previous_fulfillment_judgements(case_id, timeline_node_id)
    rerun_scope = compute_rerun_scope(previous_judgements, evidence_documents)

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
            "fulfillmentContext": {
                "timelineNode": node,
                "verification": verification,
            },
            "rerunScope": {
                "mode": rerun_scope["mode"],
                "affectedRequirementIds": rerun_scope["affectedRequirementIds"],
                "changedEvidence": rerun_scope["changedEvidence"],
                "newEvidence": rerun_scope["newEvidence"],
                "removedEvidence": rerun_scope["removedEvidence"],
            },
        },
        "status": "DONE" if not verification.get("error") else "FAILED",
    }
    return {
        "state_revision": state.get("state_revision", 0) + 1,
        "current_node": "retrieve_fulfillment_evidence",
        "fulfillment_context": {
            "timelineNode": node,
            "verification": verification,
            "evidenceDocuments": evidence_documents,
            "contractEvidence": normalized_contract_hits,
        },
        "citations": citations,
        "rerun_scope": rerun_scope,
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
        "ruleKey": str(raw.get("ruleKey") or "").strip() or None,
        "ruleTitle": str(raw.get("ruleTitle") or "").strip() or None,
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


_RULE_GUIDANCE: dict[str, dict[str, str]] = {
    "ACCEPTANCE": {
        "impact": "缺少客观验收标准会使交付是否合格、整改是否完成和付款是否到期都难以举证；发生争议时，双方可能只能依赖单方解释或事后补充材料。",
        "revision": "补充可核验的验收对象、指标和通过阈值，明确交付后的验收期限、验收材料、异议方式、整改期限以及整改后仍不合格时的扣款、重做或解除后果；避免只写“甲方满意”“按甲方要求”等不可操作表述。",
        "negotiation": "底线是验收标准和异议期限必须写入合同或附件。可以协商指标数值和整改次数，但不能接受无限期验收或以单方满意作为唯一标准。",
        "questions": "请确认是否已有技术规格书、验收单模板或项目负责人认可的量化指标，并确认验收未通过是否影响付款。",
        "verification": "核对合同正文与技术附件是否包含指标、验收期限、异议及整改后果。",
    },
    "TERMINATION": {
        "impact": "终止条件、通知方式或终止后的结算与交接不清，会导致解除是否生效、已完成工作如何结算、资料和数据如何返还等问题无法快速判断，并放大持续履约和争议风险。",
        "revision": "明确到期、任意解除和违约解除的触发条件，写明通知形式、提前通知期限、生效时间、费用结算、未完成交付、资料/数据返还、保密和知识产权存续义务；如涉及迁移或过渡服务，应列出期限、责任方和交接清单。",
        "negotiation": "终止权应与对方的补救机会和已发生费用结算绑定。可协商通知期限和过渡期，但不能接受只赋予一方无限制解除权或终止后责任全部空缺。",
        "questions": "请确认当前交易是否需要任意解除、过渡服务、数据迁移或终止后的持续保密义务。",
        "verification": "核对终止通知、解除生效、结算、交接、数据返还和存续条款是否分别有明确文字依据。",
    },
    "PAYMENT": {
        "impact": "付款前提、发票要求或逾期责任不清，会造成付款时点争议、现金流安排失真和税务凭证风险，也可能在交付质量存在争议时缺少扣款依据。",
        "revision": "明确合同价款、计价口径、付款里程碑、验收或发票作为付款前提的关系、发票类型和税率、付款期限、账户变更核验方式以及逾期付款责任；将付款节点与可验证的交付或验收结果绑定。",
        "negotiation": "底线是付款条件、发票和结算期限可执行且可举证。付款比例和周期可以协商，但不能接受付款触发条件完全由一方单方决定。",
        "questions": "请确认金额、税率、付款比例、发票类型、验收与付款的先后关系及逾期责任是否已有附件或补充协议。",
        "verification": "核对价款、付款节点、发票、税费、结算和逾期责任是否相互一致。",
    },
    "LIABILITY": {
        "impact": "责任边界、赔偿范围或补救期限不清，会增加损失认定和追偿成本；责任上限、免责或第三方索赔缺失时，暴露的财务和经营风险难以预估。",
        "revision": "按违约类型明确责任主体、损失范围、违约金或赔偿计算方式、责任上限及其例外，补充第三方索赔、数据损失、知识产权侵权和补救期限的处理机制，并避免免责条款覆盖故意或重大过失。",
        "negotiation": "责任上限、重大违约例外和第三方索赔责任是核心底线。可协商一般违约金和补救期限，但应保留对故意、重大过失、保密和侵权的追责。",
        "questions": "请确认本合同是否涉及第三方索赔、数据损失、知识产权侵权或需要保险覆盖的高风险履约活动。",
        "verification": "核对违约类型、赔偿范围、责任上限、免责例外、补救期限和索赔流程是否完整。",
    },
    "CONFIDENTIALITY": {
        "impact": "保密信息范围、例外或存续期限不清，可能导致商业秘密保护不足，终止后泄露难以追责，也会增加数据共享和返还风险。",
        "revision": "明确保密信息范围、允许披露的法定或必要例外、接收方人员和分包商责任、保护措施、泄露通知、资料返还/删除以及合同终止后的存续期限。",
        "negotiation": "可以协商保密期限和例外范围，但应保留对法定披露、最小必要披露和泄露通知的控制，并确保分包方承担同等义务。",
        "questions": "请确认是否会接触源代码、个人信息、生产数据、商业秘密或第三方保密资料。",
        "verification": "核对保密定义、例外、保护措施、泄露处理、返还删除和存续期限。",
    },
    "IP": {
        "impact": "成果归属、背景知识产权和第三方授权不清，可能导致交付成果无法使用、重复授权或侵权索赔，后续改造和商业化也可能受限。",
        "revision": "区分背景知识产权、履约中新产生的成果和第三方材料，明确归属、许可范围、付款与权利转移的关系、交付源文件/文档的义务，以及第三方侵权担保和替换方案。",
        "negotiation": "核心成果的使用权、源文件交付和第三方侵权责任必须可执行。可协商独占/非独占许可和地域期限，但不能让背景成果被无意转让。",
        "questions": "请确认交付物是否包含软件、设计文件、专利、论文、数据集或第三方组件，以及我方需要永久使用还是仅限本项目使用。",
        "verification": "核对成果归属、背景权利保留、第三方授权、源文件交付和侵权赔偿安排。",
    },
    "DATA_PROTECTION": {
        "impact": "数据处理目的、范围、存储位置和删除义务不清，会造成个人信息或重要数据合规风险，发生泄露时也难以确定责任和通知路径。",
        "revision": "明确处理目的、数据类别、最小化范围、存储和跨境位置、访问控制、保留期限、删除返还、分包处理、事件通知和监管配合义务，并约定审计与整改机制。",
        "negotiation": "数据处理范围和安全事件通知时限是底线。可以协商审计频次和技术标准，但不能接受无限制复用数据或不设泄露通知责任。",
        "questions": "请确认合同是否涉及个人信息、生产经营数据、跨境传输、云服务或分包商处理。",
        "verification": "核对数据类型、处理目的、存储位置、保留删除、分包、安全事件和审计条款。",
    },
}


def _rule_requirement_text(rule: dict[str, Any]) -> str:
    config = rule.get("checkConfig") or {}
    if isinstance(config, str):
        try:
            import json
            config = json.loads(config)
        except (TypeError, ValueError):
            config = {}
    if not isinstance(config, dict):
        config = {}
    check_type = str(rule.get("checkType") or "MISSING").upper()
    if check_type == "CONTAINS" and config.get("keywords"):
        return "应包含：" + "、".join(str(value) for value in config["keywords"][:8])
    if check_type == "SEMANTIC" and config.get("forbidden"):
        return "不得使用或不得仅使用：" + "、".join(str(value) for value in config["forbidden"][:5])
    if check_type == "THRESHOLD" and config.get("field"):
        return f"{config['field']} 应满足 {config.get('operator', 'gte')} {config.get('value')}"
    if config.get("fields"):
        return "应明确：" + "、".join(str(value) for value in config["fields"][:8])
    return str(rule.get("description") or "应有可执行、可核验的条款约定").strip()


def _rule_fallback_guidance(rule: dict[str, Any]) -> dict[str, Any]:
    clause_type = str(rule.get("clauseType") or "OTHER").upper()
    guidance = _RULE_GUIDANCE.get(clause_type, {
        "impact": "关键合同义务或控制要求缺少明确依据，可能导致履约边界、责任认定和后续复核出现争议。",
        "revision": "根据适用业务补充责任主体、履行动作、完成标准、期限、证据要求和未履行后果，并与合同附件保持一致。",
        "negotiation": "先确认该要求是否适用于当前交易；适用时应形成可核验的书面条款，不要只保留原则性表述。",
        "questions": "请业务负责人和法务确认该要求是否适用于当前交易，以及需要哪些材料证明已经满足。",
        "verification": "核对合同正文、附件和补充协议中是否已有同一要求的明确约定。",
    })
    requirement = _rule_requirement_text(rule)
    detail = str(rule.get("detail") or "确定性规则未通过").strip()
    check_type = str(rule.get("checkType") or "MISSING").upper()
    rule_name = rule.get("ruleTitle") or rule.get("title") or rule.get("ruleKey") or "未命名规则"
    explanation = (
        f"确定性规则“{rule_name}”检查的是：{requirement}。本次结果为：{detail}。"
        "这表示当前检索到的合同条款不足以证明该要求已被明确约定，不能仅凭条款类型存在就视为已满足。"
    )
    if check_type == "MISSING":
        explanation += "当前属于缺失型发现，合同原文引用为空；需要补充条款或确认其他附件是否已经承担同一义务。"
    else:
        explanation += "当前属于条款内容校验未通过，仍需结合命中的合同原文确认是完全缺失、表述不足还是仅字段未结构化提取。"
    explanation += f"业务影响：{guidance['impact']}"
    return {
        "riskExplanation": explanation,
        "businessImpact": guidance["impact"],
        "revisionAdvice": guidance["revision"] + f"本条规则的最低补充重点是：{requirement}。",
        "negotiationAdvice": guidance["negotiation"],
        "reviewQuestions": [guidance["questions"], f"规则“{rule_name}”是否适用当前交易？"],
        "verificationPoints": [guidance["verification"], f"复核规则结果：{detail}"],
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
        guidance = _rule_fallback_guidance(rule)
        rule_key = str(rule.get("ruleKey") or rule.get("rule_key") or "").strip()
        rule_title = str(rule.get("ruleTitle") or rule.get("title") or "规则检查发现").strip()
        raw = {
            "findingKey": f"{task.get('domainKey')}:{rule_key or index}",
            "ruleKey": rule_key,
            "ruleTitle": rule_title,
            "clauseType": rule.get("clauseType") or "OTHER",
            "severity": rule.get("severity") or "MEDIUM",
            "title": rule_title,
            **guidance,
            "oneLineSummary": f"{rule_title}：{rule.get('detail') or rule.get('description') or '规则要求未被合同明确满足'}",
            "keyPoint": f"先核对并补足：{_rule_requirement_text(rule)}",
            "contractCitationIds": contract_ids,
            "policyCitationIds": policy_ids,
            "confidenceLevel": "LOW",
            "suggestedAction": "REQUEST_LEGAL_REVIEW",
        }
        normalized = _normalize_finding(raw, task, evidence, index)
        if normalized:
            if not normalized.get("policyCitation") and rule_key:
                # The fired rule itself is the policy basis (mirrors the legacy
                # pipeline, where rule findings cite the rule as 制度依据).
                normalized["policyCitation"] = {
                    "ruleKey": rule_key,
                    "ruleTitle": rule_title,
                    "snippet": str(rule.get("description") or _rule_requirement_text(rule))[:220],
                }
                normalized["policyCitationIds"] = [f"RULE:{rule_key}"]
                if normalized.get("contractCitation"):
                    normalized["evidenceStatus"] = "DUAL_CITED"
                    normalized["sourceBasis"] = "CONTRACT_AND_POLICY"
                else:
                    normalized["evidenceStatus"] = "POLICY_ONLY"
                    normalized["sourceBasis"] = "POLICY_ONLY"
            result.append(normalized)
    return result


def draft_domain_findings(state: dict[str, Any]) -> dict[str, Any]:
    """Analyze each domain with the LLM and normalize all findings against real evidence.

    When ``gap_domains`` is present in state (set by targeted_retrieval), only
    the listed domains are re-analysed; existing findings for already-covered
    domains are preserved.  This implements the "只重新分析缺失领域" constraint.
    """
    domain_results = state.get("domain_results") or {}
    rule_findings = state.get("rule_findings") or []
    domain_tasks = state.get("domain_tasks") or []
    case_snapshot = state.get("case_snapshot") or {}
    run_id = int(state.get("run_id") or 0)
    extracted_facts = (state.get("extraction_snapshot") or {}).get("elements") or []
    gap_domains: set[str] = set(state.get("gap_domains") or [])
    existing_draft: list[dict[str, Any]] = state.get("draft_findings") or []
    existing_analysis: dict[str, dict[str, Any]] = state.get("domain_analysis") or {}

    # When re-running after targeted retrieval, only re-analyze gap domains.
    # Preserve findings from previously-covered domains.
    if gap_domains:
        domain_tasks = [t for t in domain_tasks if str(t.get("domainKey") or t.get("domain") or "") in gap_domains]
        if not domain_tasks:
            # No gap domains to re-analyze — keep existing state.
            return {
                "state_revision": state.get("state_revision", 0) + 1,
                "current_node": "draft_domain_findings",
            }

    def _analyze(task: dict[str, Any]) -> tuple[str, list[dict[str, Any]], str, str, dict[str, int]]:
        key = str(task.get("domainKey") or task.get("domain") or "")
        evidence = domain_results.get(key) or []
        allowed = {str(value).upper() for value in task.get("requiredClauseTypes") or []}
        matched_rules = [
            rule for rule in rule_findings
            if str(rule.get("clauseType") or "OTHER").upper() in allowed
        ]
        # §7.2: the LLM surfaces its real consumption through this dict —
        # `calls` counts every API attempt (retries + the structured→
        # unstructured fallback) and `tokens` sums across all responses;
        # the caller records them in the per-WorkUnit ledger.
        usage_out: dict[str, int] = {}
        try:
            from app.services.llm_service import LLMService

            response = LLMService().analyze_contract_risk_domain(
                case_snapshot, task, evidence, matched_rules, run_id, extracted_facts,
                usage_out=usage_out,
            )
            findings = []
            for index, raw in enumerate((response or {}).get("findings") or []):
                if not isinstance(raw, dict):
                    continue
                normalized = _normalize_finding(raw, task, evidence, index)
                if normalized:
                    findings.append(normalized)
            # Keep up to six model findings, then append every uncovered
            # deterministic rule so the quality gate cannot hide a rule result.
            findings = findings[:6]
            seen_rule_keys = {
                str(item.get("ruleKey") or "").strip()
                for item in findings
                if str(item.get("ruleKey") or "").strip()
            }
            findings.extend([
                item for item in _fallback_rule_findings(task, evidence, matched_rules)
                if str(item.get("ruleKey") or "").strip() not in seen_rule_keys
            ])
            return key, findings, "COMPLETED", str((response or {}).get("domainConclusion") or ""), usage_out
        except Exception as exc:
            logger.warning("LLM domain analysis failed for %s: %s", task.get("domainName"), exc)
            fallback = _fallback_rule_findings(task, evidence, matched_rules)
            return key, fallback, "FALLBACK", str(exc), usage_out

    usage = dict(state.get("work_unit_usage") or {})
    results: dict[str, tuple[list[dict[str, Any]], str, str]] = {}
    with ThreadPoolExecutor(max_workers=min(3, max(1, len(domain_tasks)))) as executor:
        future_map = {executor.submit(_analyze, task): task for task in domain_tasks}
        for future in as_completed(future_map):
            key, findings, status, conclusion, call_usage = future.result()
            results[key] = (findings, status, conclusion)
            record_unit_usage(
                usage, key,
                llm_calls=int(call_usage.get("calls") or 0),
                tokens=int(call_usage.get("tokens") or 0),
            )

    draft: list[dict[str, Any]] = []
    domain_analysis: dict[str, dict[str, Any]] = {}
    observations: list[dict[str, Any]] = []

    # When re-analysing only gap domains, start from the existing findings
    # and analysis, then replace entries for re-analysed domains.
    if gap_domains:
        # Keep findings for non-gap domains.
        for finding in existing_draft:
            domain_key = str(finding.get("domainKey") or "")
            # Drop previous findings for domains that are being re-analysed
            # so we don't double-count after the LLM re-run.
            if domain_key not in gap_domains:
                draft.append(finding)
        # Keep analysis for non-gap domains.
        for key, value in existing_analysis.items():
            if key not in gap_domains:
                domain_analysis[key] = value

    all_tasks = state.get("domain_tasks") or []
    for task in all_tasks:
        key = str(task.get("domainKey") or task.get("domain") or "")
        # In gap-only mode, skip domains that were not re-analysed —
        # their findings and analysis were already preserved above.
        if gap_domains and key not in gap_domains:
            observations.append({
                "callId": f"graph-domain-analysis-{key}-{state.get('subject_id', 0)}",
                "planStepId": f"analyze_{key}",
                "toolName": "analyzeContractRiskDomain",
                "arguments": {
                    "domainKey": key,
                    "domainName": task.get("domainName"),
                    "rerun": False,
                },
                "output": domain_analysis.get(key, {}),
                "status": domain_analysis.get(key, {}).get("status", "PRESERVED"),
            })
            continue
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
                "extractedFactCount": len(extracted_facts),
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
        "work_unit_usage": usage,
    }
