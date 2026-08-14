"""Contract Review Graph v2 — PRD Phase 3 pilot (§15, 2026-08-14).

Five changes over v1:

1. Each review domain is one bounded WorkUnit. Detailed checks (总价/调价/
   开票条件/…) stay inside the WorkUnit as a checklist and share one evidence
   bundle instead of multiplying retrieval calls.
2. First-round and targeted evidence are UNIONed per WorkUnit; a limited
   report is only composed when the retry budget is exhausted, never as an
   immediate reaction to one retrieval round.
3. Counter-evidence / exception analysis runs for every WorkUnit (反证池).
4. OmissionAuditor covers 没审到 / 审到了但没风险 / 证据不足 as EvidenceNeeds.
5. Negative-conclusion gate (§15.3): "未约定"-type claims must satisfy all
   eight preconditions or are softened to "当前证据范围内暂未确认".

v1 stays registered and untouched; this graph reuses v1's context, inventory,
rules and artifact nodes — only the review-specific middle is v2.
"""

from __future__ import annotations

import logging
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

from langgraph.graph import StateGraph, START, END

from .state import BaseGraphState
from .nodes.context import load_run_context, freeze_case_snapshot
from .nodes.inventory import inventory_clauses
from .nodes.retrieval import (
    run_deterministic_rules,
    _normalize_finding,
    _fallback_rule_findings,
)
from .nodes.artifact import (
    compose_report,
    compose_limited_report,
    validate_schema,
    repair_artifact,
    prepare_human_review,
    _route_after_schema,
    persist_report,
)

logger = logging.getLogger(__name__)

MAX_TARGETED_ROUNDS = 2   # PRD §15.4: 默认最多 2 轮回补
MAX_REANALYSIS_TARGETS = 8
MAX_DYNAMIC_WORK_UNITS = 4
MAX_TOTAL_WORK_UNITS = 10
MAX_QUERY_INTENTS_PER_WORK_UNIT = 2

# ─────────────────────────── fixed domain baseline ───────────────────────────
# PRD §15.2 provides the detailed review checklist. The fast runtime keeps each
# domain as one WorkUnit and carries these items inside that unit, so the checks
# remain visible to the model while retrieval and analysis are shared.

_SUB_ITEM_BASELINE: list[dict[str, Any]] = [
    {
        "domainKey": "party_authority",
        "domainName": "主体资格与授权",
        "requiredClauseTypes": ["OTHER"],
        "priority": "HIGH",
        "items": [
            {"itemKey": "signing_party", "label": "签约主体", "intents": ["签约主体 甲方 乙方 名称", "合同当事人 盖章主体"], "priority": "HIGH"},
            {"itemKey": "authority", "label": "授权与签署权限", "intents": ["授权 签署权限 授权代表", "法定代表人 授权书 代理"], "priority": "HIGH"},
        ],
    },
    {
        "domainKey": "price_payment_tax",
        "domainName": "价款、付款与税务",
        "requiredClauseTypes": ["PAYMENT"],
        "priority": "HIGH",
        "items": [
            {"itemKey": "total_price", "label": "总价", "intents": ["合同总价 金额", "合同价格 价款"], "priority": "HIGH"},
            {"itemKey": "currency", "label": "币种", "intents": ["币种 计价货币", "人民币 美元 结算币种"], "priority": "HIGH"},
            {"itemKey": "price_adjustment", "label": "调价", "intents": ["调价机制 价格调整", "涨价 降价 价格变更"], "priority": "MEDIUM"},
            {"itemKey": "payment_stages", "label": "付款阶段", "intents": ["付款比例 分期付款", "付款节点 里程碑付款"], "priority": "HIGH"},
            {"itemKey": "payment_conditions", "label": "付款条件", "intents": ["付款前提 付款条件", "付款触发 先票后款 验收后付款"], "priority": "HIGH"},
            {"itemKey": "invoice", "label": "票据", "intents": ["发票 开票要求", "发票类型 税率"], "priority": "MEDIUM"},
            {"itemKey": "tax", "label": "税费", "intents": ["税费承担 含税 不含税", "增值税 税金"], "priority": "MEDIUM"},
            {"itemKey": "settlement", "label": "结算", "intents": ["结算方式 结算周期", "对账 结算单"], "priority": "MEDIUM"},
            {"itemKey": "deduction", "label": "扣款", "intents": ["扣款 扣减 抵扣", "违约金抵扣 质量扣款"], "priority": "MEDIUM"},
            {"itemKey": "late_payment", "label": "逾期责任", "intents": ["逾期付款责任 滞纳金", "逾期利息 逾期违约金"], "priority": "HIGH"},
        ],
    },
    {
        "domainKey": "scope_delivery_acceptance",
        "domainName": "范围、交付与验收",
        "requiredClauseTypes": ["ACCEPTANCE"],
        "priority": "HIGH",
        "items": [
            {"itemKey": "deliverables", "label": "交付物", "intents": ["交付物 交付成果", "交付清单 交付范围"], "priority": "HIGH"},
            {"itemKey": "quantity", "label": "数量", "intents": ["数量 规模", "交付数量"], "priority": "MEDIUM"},
            {"itemKey": "format", "label": "格式", "intents": ["交付格式 规格", "格式要求"], "priority": "MEDIUM"},
            {"itemKey": "delivery_time", "label": "交付时间", "intents": ["交付时间 交付期限", "交付周期 进度安排"], "priority": "HIGH"},
            {"itemKey": "acceptance_criteria", "label": "验收标准", "intents": ["验收标准 验收指标", "验收条件 合格标准"], "priority": "HIGH"},
            {"itemKey": "acceptance_procedure", "label": "验收程序", "intents": ["验收程序 验收流程", "验收方式 验收组织"], "priority": "MEDIUM"},
            {"itemKey": "objection_period", "label": "异议期", "intents": ["异议期 异议期限", "提出异议 验收异议"], "priority": "MEDIUM"},
            {"itemKey": "deemed_acceptance", "label": "视为验收", "intents": ["视为验收 默认验收", "期满未异议视为合格"], "priority": "MEDIUM"},
            {"itemKey": "rectification", "label": "整改", "intents": ["整改 返工 修复", "整改期限 整改后验收"], "priority": "HIGH"},
        ],
    },
    {
        "domainKey": "liability_remedies",
        "domainName": "责任、违约与救济",
        "requiredClauseTypes": ["LIABILITY"],
        "priority": "HIGH",
        "items": [
            {"itemKey": "breach_damages", "label": "违约金", "intents": ["违约金 违约赔偿", "违约金比例 违约计算"], "priority": "HIGH"},
            {"itemKey": "loss_scope", "label": "损失范围", "intents": ["损失范围 赔偿范围", "直接损失 间接损失 预期利益"], "priority": "HIGH"},
            {"itemKey": "liability_cap", "label": "责任上限", "intents": ["责任上限 赔偿限额", "最高赔偿 累计限额"], "priority": "HIGH"},
            {"itemKey": "exemption", "label": "免责", "intents": ["免责事由 不可抗力", "免责条款 豁免"], "priority": "HIGH"},
            {"itemKey": "indirect_loss", "label": "间接损失", "intents": ["间接损失 利润损失", "数据损失 商誉损失"], "priority": "MEDIUM"},
            {"itemKey": "third_party", "label": "第三方责任", "intents": ["第三方索赔 第三方责任", "分包商责任 侵权"], "priority": "MEDIUM"},
            {"itemKey": "cure_period", "label": "补救期", "intents": ["补救期 补救期限", "限期整改 宽限期"], "priority": "MEDIUM"},
        ],
    },
    {
        "domainKey": "term_change_termination",
        "domainName": "期限、变更与终止",
        "requiredClauseTypes": ["TERMINATION"],
        "priority": "MEDIUM",
        "items": [
            {"itemKey": "effective", "label": "生效", "intents": ["生效日期 合同生效", "生效条件"], "priority": "HIGH"},
            {"itemKey": "termination", "label": "结束条件", "intents": ["合同解除 终止条件", "任意解除 到期终止"], "priority": "HIGH"},
            {"itemKey": "renewal", "label": "续期", "intents": ["续期 续签 自动顺延", "到期续约"], "priority": "MEDIUM"},
            {"itemKey": "early_termination", "label": "提前解除", "intents": ["提前解除 提前终止", "单方解除权"], "priority": "HIGH"},
            {"itemKey": "notice", "label": "通知", "intents": ["通知方式 通知期限", "书面通知 送达"], "priority": "MEDIUM"},
            {"itemKey": "post_termination", "label": "终止后义务", "intents": ["终止后义务 结算 返还", "交接 数据返还"], "priority": "MEDIUM"},
            {"itemKey": "survival", "label": "存续条款", "intents": ["存续条款 继续有效", "终止后保密 知识产权存续"], "priority": "MEDIUM"},
        ],
    },
    {
        "domainKey": "confidentiality_data_ip",
        "domainName": "保密、数据与知识产权",
        "requiredClauseTypes": ["CONFIDENTIALITY"],
        "priority": "HIGH",
        "items": [
            {"itemKey": "ip_ownership", "label": "成果归属", "intents": ["成果归属 知识产权归属", "著作权 所有权"], "priority": "HIGH"},
            {"itemKey": "license_scope", "label": "许可范围", "intents": ["许可范围 授权使用", "授权期限 使用限制"], "priority": "MEDIUM"},
            {"itemKey": "background_ip", "label": "背景知识产权", "intents": ["背景知识产权 既有技术", "背景资料 在先权利"], "priority": "MEDIUM"},
            {"itemKey": "third_party_ip", "label": "第三方侵权", "intents": ["第三方侵权 知识产权侵权", "侵权责任 担保不侵权"], "priority": "MEDIUM"},
            {"itemKey": "confidentiality", "label": "保密", "intents": ["保密义务 保密范围", "保密期限 保密例外"], "priority": "HIGH"},
            {"itemKey": "personal_info", "label": "个人信息", "intents": ["个人信息 隐私", "个人信息保护 出境"], "priority": "MEDIUM"},
            {"itemKey": "data_security", "label": "数据安全", "intents": ["数据安全 安全措施", "数据泄露 等保 网络安全"], "priority": "MEDIUM"},
        ],
    },
]

# Dynamic LLM-selected domains become one extra WorkUnit each (bounded, PRD
# §15.2 动态领域). Kept in the planner node, not here.


# ─────────────────────────── helpers ───────────────────────────


def _expand_adjacent_clauses(hits: list[dict], snapshot: dict[str, Any]) -> int:
    """Attach adjacent sibling clauses (same parent number) from the catalog.

    Deterministic, snapshot-only — no DB access (PRD §15.3(5) 相邻条款检查).
    Returns the number of hits that received neighbour entries.
    """
    catalog = list(snapshot.get("clause_catalog") or snapshot.get("clauseCatalog") or [])
    if not catalog:
        return 0
    ordered = sorted(
        catalog, key=lambda entry: (len(str(entry.get("clauseNumber") or "")), str(entry.get("clauseNumber") or ""))
    )
    by_number = {str(entry.get("clauseNumber") or ""): entry for entry in ordered}
    siblings: dict[str, list[str]] = {}
    for entry in ordered:
        number = str(entry.get("clauseNumber") or "")
        if "." not in number:
            continue
        parent = number.rsplit(".", 1)[0]
        siblings.setdefault(parent, []).append(number)

    attached = 0
    for hit in hits:
        if hit.get("adjacentClauses"):
            continue
        number = str(hit.get("clauseNumber") or "")
        if "." not in number:
            continue
        parent = number.rsplit(".", 1)[0]
        group = siblings.get(parent) or []
        try:
            index = group.index(number)
        except ValueError:
            continue
        neighbours = []
        for neighbour_number in group[max(0, index - 2):index] + group[index + 1:index + 3]:
            entry = by_number.get(neighbour_number)
            if not entry:
                continue
            neighbours.append({
                "clauseNumber": neighbour_number,
                "clauseId": entry.get("clauseId"),
                "title": entry.get("title"),
            })
        if neighbours:
            hit["adjacentClauses"] = neighbours
            attached += 1
    return attached


_COUNTER_MARKERS: tuple[tuple[str, str], ...] = (
    ("EXCEPTION", ("除外", "但书", "例外", "另有约定", "特别约定", "以双方确认为准")),
    ("LIMITATION", ("责任上限", "限额", "不超过", "最高赔偿", "上限", "封顶")),
    ("EXEMPTION", ("豁免", "免责", "不承担", "不负责")),
    ("CONFLICT", ("冲突", "不一致", "优先适用", "替代", "以本合同为准")),
)


def _classify_counter_hit(hit: dict[str, Any]) -> str:
    text = " ".join(str(hit.get(key) or "") for key in ("title", "clauseNumber", "snippet", "clauseText"))
    for classification, markers in _COUNTER_MARKERS:
        if any(marker in text for marker in markers):
            return classification
    return "OTHER"


def _wu_bundle(state: dict[str, Any], work_unit_id: str) -> dict[str, Any]:
    return (state.get("evidence_bundles_by_work_unit") or {}).get(work_unit_id) or {}


def _flat_bundle(bundle: dict[str, Any]) -> list[dict]:
    from app.agent_runtime.harness.retrieval import flatten_bundle
    return flatten_bundle(bundle)


# ─────────────────────────── 4. build contract map ───────────────────────────


def build_contract_map(state: dict[str, Any]) -> dict[str, Any]:
    """Hierarchical contract map from the inventory + snapshot (PRD §15.2).

    Supplies the facts the negative gate and the omission audit need:
    domain → clause-type counts, clause-type coverage, attachment coverage.
    """
    snapshot = state.get("evidence_snapshot") or {}
    catalog = snapshot.get("clause_catalog") or []
    inventory = {}
    for observation in state.get("observations") or []:
        output = observation.get("output") or {}
        if isinstance(output, dict) and isinstance(output.get("inventory"), dict):
            inventory = output["inventory"]
            break
    documents = state.get("document_snapshot") or []
    # The contract retrieval channel is case-scoped (verified against
    # ContractStore): clauses sourced from attachments live in the same case,
    # so a successful case-wide retrieval round covers attachment text.
    attachments_checked = bool(catalog) and bool(documents)

    domain_types: dict[str, list[str]] = {}
    for entry in _SUB_ITEM_BASELINE:
        domain_types[entry["domainKey"]] = list(entry["requiredClauseTypes"])

    contract_map = {
        "domains": {
            domain_key: {
                "domainName": entry["domainName"],
                "requiredClauseTypes": list(entry["requiredClauseTypes"]),
                "clauseCount": int((inventory.get("clauseTypes") or {}).get(
                    entry["requiredClauseTypes"][0] if entry["requiredClauseTypes"] else "", 0
                )),
            }
            for domain_key, entry in ((item["domainKey"], item) for item in _SUB_ITEM_BASELINE)
        },
        "clauseCatalogCount": len(catalog),
        "documentCount": len(documents),
        "attachmentsChecked": attachments_checked,
        "inventory": inventory,
    }
    return {
        "state_revision": state.get("state_revision", 0) + 1,
        "current_node": "build_contract_map",
        "contract_map": contract_map,
    }


# ─────────────────────────── 5. plan work units ───────────────────────────


def _domain_query_intents(domain: dict[str, Any]) -> list[str]:
    explicit = [
        str(value).strip()[:240]
        for value in domain.get("queryIntents") or []
        if str(value).strip()
    ]
    if explicit:
        return list(dict.fromkeys(explicit))[:MAX_QUERY_INTENTS_PER_WORK_UNIT]

    items = list(domain.get("items") or [])
    labels = [str(item.get("label") or "").strip() for item in items]
    labels = [label for label in labels if label]
    primary = f"{domain.get('domainName') or ''} {' '.join(labels)}".strip()[:240]

    high_priority_terms: list[str] = []
    for item in items:
        if str(item.get("priority") or "MEDIUM").upper() != "HIGH":
            continue
        intents = [str(value).strip() for value in item.get("intents") or [] if str(value).strip()]
        if intents:
            high_priority_terms.append(intents[0])
    secondary = " ".join(high_priority_terms).strip()[:240]

    return list(dict.fromkeys(
        value for value in (primary, secondary) if value
    ))[:MAX_QUERY_INTENTS_PER_WORK_UNIT]


def _normalize_domain_work_unit(
    domain: dict[str, Any],
    *,
    work_unit_id: str | None = None,
) -> dict[str, Any]:
    domain_key = str(domain["domainKey"])
    items = list(domain.get("items") or [])
    sub_checks = [
        {
            "itemKey": str(item.get("itemKey") or "")[:64],
            "label": str(item.get("label") or "")[:80],
            "priority": str(item.get("priority") or domain.get("priority") or "MEDIUM"),
        }
        for item in items
        if str(item.get("label") or "").strip()
    ]
    labels = "、".join(item["label"] for item in sub_checks)
    return {
        "work_unit_id": str(work_unit_id or domain_key)[:100],
        "task_type": "CONTRACT_REVIEW",
        "category": "risk_domain",
        "label": str(domain["domainName"]),
        "objective": str(domain.get("objective") or f"综合检查：{labels}")[:800],
        "applicability": "ALWAYS",
        "priority": str(domain.get("priority") or "MEDIUM"),
        "query_intents": _domain_query_intents(domain),
        "required_clause_types": list(domain["requiredClauseTypes"]),
        "required_source_types": ["CONTRACT_CLAUSE"],
        "expected_output_schema": "",
        "required_checks": [
            "CITATION_EXISTS", "CITATION_FROM_SNAPSHOT", "CLAIM_SUPPORTED",
            "VALUE_CONSISTENCY", "NEGATIVE_CLAIM_BAR",
        ],
        "negative_claim_allowed": True,
        "human_review_policy": "STANDARD",
        "domainKey": domain_key,
        "domainName": str(domain["domainName"]),
        "sub_check_items": sub_checks,
    }


def plan_work_units(state: dict[str, Any]) -> dict[str, Any]:
    """Build a fast, domain-level WorkUnit plan from the detailed checklist.

    The six fixed domains are always retained. Dynamic LLM-selected domains
    may add at most four units, and the total plan is hard-capped at ten.
    """
    work_units = [_normalize_domain_work_unit(domain) for domain in _SUB_ITEM_BASELINE]

    # v1-compatible domain_tasks so reused nodes and the report keep working.
    domain_tasks: list[dict[str, Any]] = []
    for domain in _SUB_ITEM_BASELINE:
        domain_items = [item for item in domain["items"]]
        domain_tasks.append({
            "domainKey": domain["domainKey"],
            "domainName": domain["domainName"],
            "objective": f"逐子项检查：{'、'.join(item['label'] for item in domain_items)}",
            "requiredClauseTypes": list(domain["requiredClauseTypes"]),
            "queries": list(dict.fromkeys(
                intent for item in domain_items for intent in item["intents"]
            ))[:6],
            "priority": domain["priority"],
            "source": "V2_WORK_UNITS",
            "subCheckCount": len(domain_items),
        })

    planner_error = ""
    try:
        from app.services.llm_service import LLMService

        inventory = {}
        for observation in state.get("observations") or []:
            output = observation.get("output") or {}
            if isinstance(output, dict) and isinstance(output.get("inventory"), dict):
                inventory = output["inventory"]
                break
        result = LLMService().plan_contract_risk_domains(
            state.get("case_snapshot") or {},
            inventory,
            [dict(item) for item in domain_tasks],
            int(state.get("run_id") or 0),
        )
        seen = {str(unit["domainKey"]) for unit in work_units}
        added = 0
        for index, raw in enumerate((result or {}).get("domains") or []):
            if not isinstance(raw, dict):
                continue
            key = re.sub(r"[^a-z0-9_]+", "_", str(raw.get("domainKey") or "").lower()).strip("_")
            name = str(raw.get("domainName") or "").strip()[:80]
            if not name or key in seen or not str(raw.get("objective") or "").strip():
                continue
            queries = [str(value).strip()[:240] for value in (raw.get("queries") or []) if str(value).strip()]
            if not queries:
                continue
            dynamic_domain = {
                "domainKey": key,
                "domainName": name,
                "objective": str(raw.get("objective") or "")[:800],
                "requiredClauseTypes": ["OTHER"],
                "priority": str(raw.get("priority") or "MEDIUM").upper(),
                "queryIntents": queries,
                "items": [{
                    "itemKey": "dynamic",
                    "label": name,
                    "intents": queries[:MAX_QUERY_INTENTS_PER_WORK_UNIT],
                    "priority": str(raw.get("priority") or "MEDIUM").upper(),
                }],
            }
            work_units.append(_normalize_domain_work_unit(
                dynamic_domain,
                work_unit_id=f"{key}.dynamic",
            ))
            seen.add(key)
            added += 1
            if added >= MAX_DYNAMIC_WORK_UNITS or len(work_units) >= MAX_TOTAL_WORK_UNITS:
                break
    except Exception as exc:
        planner_error = str(exc)
        logger.warning("v2 dynamic WorkUnit planner unavailable; fixed baseline active: %s", exc)

    from app.agent_runtime.runtime import _retry_limit_override

    max_retries = _retry_limit_override.get()
    if max_retries < 0:
        max_retries = MAX_TARGETED_ROUNDS
    fixed_check_count = sum(len(domain["items"]) for domain in _SUB_ITEM_BASELINE)
    baseline_work_unit_count = len(_SUB_ITEM_BASELINE)
    return {
        "state_revision": state.get("state_revision", 0) + 1,
        "current_node": "plan_work_units",
        "work_units": work_units,
        "domain_tasks": domain_tasks,
        "retry_budget": int(max_retries),
        "reanalysis_targets": [],
        "evidence_needs": [],
        "negative_conclusion_checks": [],
        "observations": [{
            "callId": f"v2-plan-work-units-{state.get('subject_id', 0)}",
            "planStepId": "plan_work_units",
            "toolName": "planWorkUnits",
            "arguments": {"baselineDomainCount": len(_SUB_ITEM_BASELINE)},
            "output": {
                "workUnitCount": len(work_units),
                "baselineWorkUnitCount": baseline_work_unit_count,
                "fixedItemCount": fixed_check_count,
                "dynamicCount": len(work_units) - baseline_work_unit_count,
                "maxWorkUnitCount": MAX_TOTAL_WORK_UNITS,
                "compressionRatio": round(len(work_units) / max(1, fixed_check_count), 3),
                "retryBudget": int(max_retries),
                "plannerFallback": bool(planner_error),
            },
            "status": "DONE" if not planner_error else "PARTIAL",
        }],
    }


# ─────────────────────── 6. retrieve per work unit ───────────────────────────


def retrieve_evidence_for_work_units(state: dict[str, Any]) -> dict[str, Any]:
    """Per-WorkUnit multi-query retrieval through the shared orchestrator.

    PRD §12.1: each intent is its own query variant — no joined long query.
    Counter-evidence queries run for every WorkUnit (反证池, §12.5). Bundles
    are stored per WorkUnit; v1-compatible flat domain_results are aggregated
    from the same bundles (single evidence entry, both views).
    """
    from app.agent_runtime.harness.models import default_retrieval_request
    from app.agent_runtime.harness.retrieval import get_orchestrator
    from app.agent_runtime.harness.observation import ObservabilityRecorder

    case_id = int(state.get("subject_id") or 0)
    snapshot = state.get("evidence_snapshot") or {}
    clause_texts = state.get("contract_evidence_snapshot") or []
    orchestrator = get_orchestrator()
    work_units = state.get("work_units") or []
    round_no = int((state.get("retry_state") or {}).get("reflection_rounds", 0)) + 1

    def _retrieve_one(work_unit: dict[str, Any]) -> tuple[str, dict[str, Any], str]:
        work_unit_id = str(work_unit["work_unit_id"])
        request = default_retrieval_request(
            case_id, snapshot, work_unit_id,
            list(work_unit.get("query_intents") or []),
            clause_types=list(work_unit.get("required_clause_types") or []),
            final_limit=10,
            require_counter_evidence=True,
        )
        try:
            bundle = orchestrator.retrieve_sync(snapshot, request, clauses=clause_texts)
            parent_count = len([
                hit for hit in bundle.get("contract_evidence") or [] if hit.get("parentClause")
            ])
            adjacent_count = _expand_adjacent_clauses(bundle.get("contract_evidence") or [], snapshot)
            adjacent_count += _expand_adjacent_clauses(bundle.get("counter_evidence") or [], snapshot)
            stats = dict(bundle.get("retrieval_stats") or {})
            stats["round"] = round_no
            stats["parentExpansionCount"] = parent_count
            stats["adjacentExpansionCount"] = adjacent_count
            bundle["retrieval_stats"] = stats
            return work_unit_id, bundle, ""
        except Exception as exc:
            logger.exception("v2 retrieval failed for %s: %s", work_unit_id, exc)
            from app.agent_runtime.harness.retrieval import empty_bundle
            return work_unit_id, empty_bundle(request, [f"orchestrator failed: {exc}"]), str(exc)[:500]

    bundles: dict[str, dict[str, Any]] = {}
    retrieval_errors: dict[str, str] = {}
    if len(work_units) <= 3:
        results = [_retrieve_one(work_unit) for work_unit in work_units]
    else:
        with ThreadPoolExecutor(max_workers=4) as executor:
            results = [future.result() for future in
                       [executor.submit(_retrieve_one, work_unit) for work_unit in work_units]]
    for work_unit_id, bundle, error in results:
        bundles[work_unit_id] = bundle
        if error:
            retrieval_errors[work_unit_id] = error

    domain_results: dict[str, list[dict]] = {}
    retrieval_validation: dict[str, dict[str, Any]] = {}
    observations: list[dict[str, Any]] = []
    by_domain: dict[str, list[dict[str, Any]]] = {}
    for work_unit in work_units:
        by_domain.setdefault(str(work_unit["domainKey"]), []).append(work_unit)

    for domain_key, units in by_domain.items():
        seen: set[str] = set()
        flat: list[dict] = []
        rerank_methods: set[str] = set()
        for work_unit in units:
            bundle = bundles.get(str(work_unit["work_unit_id"])) or {}
            for item in _flat_bundle(bundle):
                source_id = str(item.get("sourceId") or "")
                if source_id and source_id not in seen:
                    seen.add(source_id)
                    flat.append(item)
                if item.get("rerankerMethod"):
                    rerank_methods.add(str(item["rerankerMethod"]))
        domain_results[domain_key] = flat
        retrieval_validation[domain_key] = {
            "mode": "MULTI_CHANNEL",
            "evidenceCount": len(flat),
            "rerankMethods": sorted(rerank_methods),
            "crossValidatedCount": sum(1 for item in flat if item.get("crossValidated")),
            "workUnitCount": len(units),
        }
        observations.append({
            "callId": f"v2-retrieve-{domain_key}-{case_id}-r{round_no}",
            "planStepId": f"retrieve_{domain_key}",
            "toolName": "retrieveEvidenceBundle",
            "arguments": {"domainKey": domain_key, "workUnitCount": len(units), "round": round_no},
            "output": {
                "workUnitCount": len(units),
                "evidenceCount": len(flat),
                "rerankMethods": sorted(rerank_methods),
                "bundleSummaries": [
                    ObservabilityRecorder.bundle_summary(bundles.get(str(unit["work_unit_id"])) or {})
                    for unit in units
                ],
            },
            "status": "DONE" if not retrieval_errors else "PARTIAL",
        })

    return {
        "state_revision": state.get("state_revision", 0) + 1,
        "current_node": "retrieve_evidence_for_work_units",
        "evidence_bundles_by_work_unit": bundles,
        "domain_results": domain_results,
        "retrieval_validation": retrieval_validation,
        "observations": observations,
    }


# ─────────────────────── 8. per-work-unit risk analysis ─────────────────────


def _analyze_one_work_unit(
    state: dict[str, Any],
    work_unit: dict[str, Any],
    bundle: dict[str, Any],
    rule_findings: list[dict],
) -> tuple[str, list[dict], str, list[dict]]:
    """LLM risk analysis for one WorkUnit; deterministic fallback on failure."""
    work_unit_id = str(work_unit["work_unit_id"])
    evidence = _flat_bundle(bundle)
    contract_hits = list(bundle.get("contract_evidence") or [])
    from app.agent_runtime.runtime import _v2_skip_llm_on_no_evidence

    if not evidence and not work_unit.get("negative_claim_allowed"):
        return work_unit_id, [], "SKIPPED_NO_EVIDENCE", []
    if not evidence and _v2_skip_llm_on_no_evidence.get():
        # Deterministic absence finding — no LLM call for an empty evidence
        # pool. The negative gate (§15.3) qualifies this conclusion later;
        # gate-only validation applies because there is nothing to cite.
        label = str(work_unit.get("label") or work_unit.get("objective") or "该检查项")
        return work_unit_id, [{
            "findingKey": f"{work_unit_id}:no_evidence",
            "clauseType": (work_unit.get("required_clause_types") or ["OTHER"])[0],
            "severity": "LOW",
            "domainKey": work_unit_id,
            "domainName": label,
            "sourceBasis": "INSUFFICIENT_EVIDENCE",
            "title": f"{label}未约定",
            "oneLineSummary": f"当前证据范围内未检索到{label}相关条款",
            "keyPoint": f"经多查询变体与反证检索后，暂未确认{label}的约定",
            "description": f"在本次检索的证据范围内未找到与{label}直接相关的合同条款。"
                          f"该结论需满足负向结论门禁的全部前置条件后才可作为“未约定”陈述。",
            "contractCitationIds": [],
            "policyCitationIds": [],
            "evidenceStatus": "MISSING",
            "confidenceLevel": "LOW",
            "suggestedAction": "REQUEST_LEGAL_REVIEW",
        }], "DETERMINISTIC_NO_EVIDENCE", []

    allowed_types = {str(value).upper() for value in work_unit.get("required_clause_types") or []}
    matched_rules = [
        rule for rule in rule_findings
        if str(rule.get("clauseType") or "OTHER").upper() in allowed_types
    ]
    wu_task = {
        "domainKey": work_unit["domainKey"],
        "domainName": work_unit.get("label") or work_unit.get("objective") or "",
        "objective": work_unit.get("objective") or "",
        "queries": list(work_unit.get("query_intents") or []),
        "subItemKey": work_unit.get("label") or "",
        "subCheckItems": list(work_unit.get("sub_check_items") or []),
        "requiredClauseTypes": list(work_unit.get("required_clause_types") or []),
    }
    needs: list[dict] = []
    try:
        from app.services.llm_service import LLMService

        response = LLMService().analyze_contract_risk_domain(
            state.get("case_snapshot") or {},
            wu_task,
            evidence[:18],
            matched_rules[:10],
            int(state.get("run_id") or 0),
            (state.get("extraction_snapshot") or {}).get("elements") or [],
        )
        findings = []
        for index, raw in enumerate((response or {}).get("findings") or []):
            if not isinstance(raw, dict):
                continue
            normalized = _normalize_finding(raw, wu_task, evidence, index)
            if normalized:
                findings.append(normalized)
        findings = findings[:6]
        seen_rule_keys = {
            str(item.get("ruleKey") or "").strip()
            for item in findings if str(item.get("ruleKey") or "").strip()
        }
        findings.extend([
            item for item in _fallback_rule_findings(wu_task, evidence, matched_rules)
            if str(item.get("ruleKey") or "").strip() not in seen_rule_keys
        ])
        return work_unit_id, findings, "COMPLETED", needs
    except Exception as exc:
        logger.warning("v2 LLM analysis failed for %s: %s", work_unit_id, exc)
        findings = _fallback_rule_findings(wu_task, evidence, matched_rules)
        return work_unit_id, findings, "FALLBACK", needs


def _annotate_finding(finding: dict, work_unit: dict[str, Any]) -> dict:
    finding = dict(finding)
    finding["workUnitId"] = str(work_unit["work_unit_id"])
    finding["subItemKey"] = str(work_unit.get("label") or "")
    from app.agent_runtime.harness.models import NEGATIVE_CLAIM_MARKERS
    claim_text = " ".join(str(finding.get(key) or "") for key in ("title", "oneLineSummary", "description"))
    finding["negativeClaim"] = any(marker in claim_text for marker in NEGATIVE_CLAIM_MARKERS)
    return finding


def analyze_work_unit_risks(state: dict[str, Any]) -> dict[str, Any]:
    """Per-WorkUnit risk analysis (parallel, bounded)."""
    from app.agent_runtime.runtime import _v2_analysis_concurrency

    work_units = state.get("work_units") or []
    rule_findings = state.get("rule_findings") or []
    bundles = state.get("evidence_bundles_by_work_unit") or {}

    results: dict[str, tuple[list[dict], str, list[dict]]] = {}
    if len(work_units) <= 3:
        for work_unit in work_units:
            wid, findings, status, needs = _analyze_one_work_unit(
                state, work_unit, bundles.get(str(work_unit["work_unit_id"])) or {}, rule_findings)
            results[wid] = (findings, status, needs)
    else:
        with ThreadPoolExecutor(max_workers=_v2_analysis_concurrency.get()) as executor:
            futures = {
                executor.submit(_analyze_one_work_unit, state, work_unit,
                                bundles.get(str(work_unit["work_unit_id"])) or {}, rule_findings): work_unit
                for work_unit in work_units
            }
            for future in as_completed(futures):
                wid, findings, status, needs = future.result()
                results[wid] = (findings, status, needs)

    findings_by_work_unit: dict[str, list[dict]] = {}
    draft: list[dict] = []
    domain_analysis: dict[str, dict[str, Any]] = {}
    evidence_needs: list[dict] = []
    observations: list[dict[str, Any]] = []
    for work_unit in work_units:
        work_unit_id = str(work_unit["work_unit_id"])
        findings, status, needs = results.get(work_unit_id, ([], "MISSING", []))
        annotated = [_annotate_finding(finding, work_unit) for finding in findings]
        findings_by_work_unit[work_unit_id] = annotated
        draft.extend(annotated)
        evidence_needs.extend(needs)
        domain_key = str(work_unit["domainKey"])
        entry = domain_analysis.setdefault(domain_key, {
            "domainName": work_unit.get("domainName"),
            "status": "COMPLETED",
            "findingCount": 0,
            "workUnits": {},
        })
        entry["findingCount"] += len(annotated)
        entry["workUnits"][work_unit_id] = {
            "status": status, "findingCount": len(annotated), "label": work_unit.get("label"),
        }
        if status != "COMPLETED":
            entry["status"] = "PARTIAL" if entry["status"] == "COMPLETED" else entry["status"]
        observations.append({
            "callId": f"v2-analyze-{work_unit_id}-{state.get('subject_id', 0)}",
            "planStepId": f"analyze_{work_unit_id}",
            "toolName": "analyzeContractRiskDomain",
            "arguments": {
                "workUnitId": work_unit_id, "label": work_unit.get("label"),
                "queryVariantCount": len(work_unit.get("query_intents") or []),
            },
            "output": {"status": status, "findingCount": len(annotated)},
            "status": status,
        })

    return {
        "state_revision": state.get("state_revision", 0) + 1,
        "current_node": "analyze_work_unit_risks",
        "findings_by_work_unit": findings_by_work_unit,
        "draft_findings": draft,
        "domain_analysis": domain_analysis,
        "evidence_needs": (state.get("evidence_needs") or []) + evidence_needs,
        "observations": observations,
    }


# ─────────────────────── 9. counter-evidence analysis ───────────────────────


def analyze_counter_evidence(state: dict[str, Any]) -> dict[str, Any]:
    """Deterministic exception/limitation classification of the 反证池.

    Every counter hit gets a relation class (EXCEPTION / LIMITATION /
    EXEMPTION / CONFLICT / OTHER). Findings in the same WorkUnit are annotated
    with the counter evidence that may qualify them — the negative gate and
    the omission audit consume this analysis.
    """
    work_units = state.get("work_units") or []
    bundles = state.get("evidence_bundles_by_work_unit") or {}
    findings_by_work_unit = state.get("findings_by_work_unit") or {}
    counter_analysis: dict[str, list[dict]] = {}
    updated_findings: dict[str, list[dict]] = {}
    observations: list[dict[str, Any]] = []

    for work_unit in work_units:
        work_unit_id = str(work_unit["work_unit_id"])
        bundle = bundles.get(work_unit_id) or {}
        counter_hits = list(bundle.get("counter_evidence") or [])
        entries = []
        for hit in counter_hits:
            classification = _classify_counter_hit(hit)
            entries.append({
                "sourceId": hit.get("sourceId"),
                "clauseNumber": hit.get("clauseNumber"),
                "title": hit.get("title"),
                "classification": classification,
                "snippet": str(hit.get("snippet") or "")[:220],
            })
        counter_analysis[work_unit_id] = entries

        findings = list(findings_by_work_unit.get(work_unit_id) or [])
        if findings:
            significant = [entry for entry in entries if entry["classification"] != "OTHER"]
            for finding in findings:
                finding = dict(finding)
                finding["counterEvidence"] = significant
                finding["counterEvidenceCount"] = len(significant)
                updated_findings[work_unit_id] = updated_findings.get(work_unit_id, []) + [finding]
        observations.append({
            "callId": f"v2-counter-{work_unit_id}-{state.get('subject_id', 0)}",
            "planStepId": f"counter_{work_unit_id}",
            "toolName": "analyzeCounterEvidence",
            "arguments": {"workUnitId": work_unit_id},
            "output": {
                "counterHitCount": len(entries),
                "classifications": {
                    classification: sum(1 for entry in entries if entry["classification"] == classification)
                    for classification in ("EXCEPTION", "LIMITATION", "EXEMPTION", "CONFLICT", "OTHER")
                },
            },
            "status": "DONE",
        })

    return {
        "state_revision": state.get("state_revision", 0) + 1,
        "current_node": "analyze_counter_evidence",
        "counter_analysis_by_work_unit": counter_analysis,
        "findings_by_work_unit": updated_findings or findings_by_work_unit,
        "observations": observations,
    }


# ─────────────────────────── 10. merge candidates ───────────────────────────


def merge_candidates(state: dict[str, Any]) -> dict[str, Any]:
    """Merge LLM findings + deterministic rules into candidates per WorkUnit.

    Rules never silently disappear: a rule finding that the LLM did not echo
    becomes its own candidate (v1 behaviour kept at sub-item granularity).
    """
    work_units = state.get("work_units") or []
    rule_findings = state.get("rule_findings") or []
    findings_by_work_unit = state.get("findings_by_work_unit") or {}

    merged: dict[str, list[dict]] = {}
    draft: list[dict] = []
    for work_unit in work_units:
        work_unit_id = str(work_unit["work_unit_id"])
        allowed_types = {str(value).upper() for value in work_unit.get("required_clause_types") or []}
        findings = list(findings_by_work_unit.get(work_unit_id) or [])
        candidates: list[dict] = []
        seen_rule_keys: set[str] = set()
        for index, finding in enumerate(findings, 1):
            from app.agent_runtime.harness.models import NEGATIVE_CLAIM_MARKERS
            claim_text = " ".join(str(finding.get(key) or "") for key in ("title", "oneLineSummary", "description"))
            candidates.append({
                "candidate_id": f"{work_unit_id}:f{index}",
                "work_unit_id": work_unit_id,
                "result_type": "RISK_FINDING",
                "claim": claim_text[:400],
                "structured_value": finding.get("structuredValue") or {},
                "contract_citation_ids": list(finding.get("contractCitationIds") or []),
                "policy_citation_ids": list(finding.get("policyCitationIds") or []),
                "confidence": 0.0,
                "source": "LLM" if not finding.get("ruleKey") else "RULE",
                "uncertainty": [],
                "negative_claim": bool(finding.get("negativeClaim"))
                    or any(marker in claim_text for marker in NEGATIVE_CLAIM_MARKERS),
                "finding": finding,
            })
            if finding.get("ruleKey"):
                seen_rule_keys.add(str(finding["ruleKey"]))
        for rule in rule_findings:
            rule_key = str(rule.get("ruleKey") or "")
            if (str(rule.get("clauseType") or "OTHER").upper() not in allowed_types) or rule_key in seen_rule_keys:
                continue
            candidates.append({
                "candidate_id": f"{work_unit_id}:r{rule_key or len(candidates) + 1}",
                "work_unit_id": work_unit_id,
                "result_type": "RULE_FINDING",
                "claim": str(rule.get("title") or rule.get("description") or rule_key)[:400],
                "structured_value": rule.get("structuredValue") or {},
                "contract_citation_ids": list(rule.get("contractCitationIds") or []),
                "policy_citation_ids": list(rule.get("policyCitationIds") or []),
                "confidence": 0.0,
                "source": "RULE",
                "uncertainty": [],
                "negative_claim": False,
                "finding": rule,
            })
        merged[work_unit_id] = candidates
        draft.extend(candidates)

    return {
        "state_revision": state.get("state_revision", 0) + 1,
        "current_node": "merge_candidates",
        "merged_candidates_by_work_unit": merged,
    }


# ─────────────────────────── 11. grounding validation ───────────────────────


def _negative_gate(
    work_unit: dict[str, Any],
    bundle: dict[str, Any],
    contract_map: dict[str, Any],
    counter_entries: list[dict],
    snapshot: dict[str, Any],
) -> tuple[bool, list[dict]]:
    """PRD §15.3 — the eight preconditions for a "未约定"-type conclusion."""
    stats = bundle.get("retrieval_stats") or {}
    catalog_loaded = bool(snapshot.get("clause_catalog") or snapshot.get("clauseCatalog"))
    synonyms = len(work_unit.get("query_intents") or []) >= 2
    reverse_searched = int(stats.get("counterQueryCount") or 0) >= 2
    type_filtered = bool(work_unit.get("required_clause_types"))
    parent_checked = int(stats.get("parentExpansionCount") or 0) > 0
    adjacent_checked = int(stats.get("adjacentExpansionCount") or 0) > 0
    attachments_checked = bool(contract_map.get("attachmentsChecked"))
    contract_hits = bundle.get("contract_evidence") or []
    critical_failure = any(
        str(warning.get("channel")) in {"contract", "counter"}
        for warning in (bundle.get("warnings") or [])
    )
    auditor_counter_found = any(
        entry.get("classification") in {"EXCEPTION", "LIMITATION", "EXEMPTION", "CONFLICT"}
        for entry in counter_entries
    )
    checks = [
        {"check": "CATALOG_LOADED", "ok": catalog_loaded, "detail": f"{len(snapshot.get('clause_catalog') or [])} 条目录"},
        {"check": "SYNONYM_QUERIES", "ok": synonyms, "detail": f"{len(work_unit.get('query_intents') or [])} 个查询变体"},
        {"check": "REVERSE_EXPRESSION_QUERIES", "ok": reverse_searched, "detail": f"反证查询 {stats.get('counterQueryCount', 0)} 次"},
        {"check": "CLAUSE_TYPE_FILTER", "ok": type_filtered, "detail": f"条款类型 {work_unit.get('required_clause_types')}"},
        {"check": "PARENT_CLAUSE_CHECKED", "ok": parent_checked, "detail": f"父条款扩展 {stats.get('parentExpansionCount', 0)} 条"},
        {"check": "ADJACENT_CLAUSE_CHECKED", "ok": adjacent_checked, "detail": f"相邻条款扩展 {stats.get('adjacentExpansionCount', 0)} 条"},
        {"check": "ATTACHMENTS_CHECKED", "ok": attachments_checked, "detail": f"文档数 {contract_map.get('documentCount', 0)}"},
        {"check": "NO_CRITICAL_CHANNEL_FAILURE", "ok": not critical_failure, "detail": "合同/反证通道无关键失败"},
        {"check": "AUDITOR_NO_COUNTER_EVIDENCE", "ok": not auditor_counter_found, "detail": "未发现反证命中"},
    ]
    passed = all(check["ok"] for check in checks)
    return passed, checks


def validate_grounding(state: dict[str, Any]) -> dict[str, Any]:
    """GroundingValidator per WorkUnit + negative-conclusion gate.

    REJECT → candidate dropped with its EvidenceNeeds recorded. Candidates
    that fail the §15.3 gate are softened to "当前证据范围内暂未确认" instead
    of being silently dropped — the review stays honest about evidence limits.
    """
    from app.agent_runtime.harness.validation import GroundingValidator
    from app.agent_runtime.harness.models import REASON_CODES  # noqa: F401 (vocabulary reference)

    snapshot = state.get("evidence_snapshot") or {}
    contract_map = state.get("contract_map") or {}
    work_units = state.get("work_units") or []
    bundles = state.get("evidence_bundles_by_work_unit") or {}
    counter_analysis = state.get("counter_analysis_by_work_unit") or {}
    merged_candidates = state.get("merged_candidates_by_work_unit") or {}

    validator = GroundingValidator()
    validated_by_unit: dict[str, list[dict]] = {}
    validation_by_work_unit: dict[str, dict[str, Any]] = {}
    evidence_needs: list[dict] = list(state.get("evidence_needs") or [])
    negative_checks: list[dict] = list(state.get("negative_conclusion_checks") or [])
    observations: list[dict[str, Any]] = []

    def _gate_need(work_unit_id: str, reason_code: str, description: str) -> dict:
        return {
            "need_id": f"need-{work_unit_id}-{reason_code}",
            "work_unit_id": work_unit_id,
            "reason_code": reason_code,
            "description": description,
            "query_hints": [],
            "retryable": True,
            "must_expand_neighbors": reason_code == "NEGATIVE_CLAIM_NOT_PROVEN",
        }

    for work_unit in work_units:
        work_unit_id = str(work_unit["work_unit_id"])
        bundle = bundles.get(work_unit_id) or {}
        candidates = list(merged_candidates.get(work_unit_id) or [])
        accepted: list[dict] = []
        unit_verdicts: dict[str, int] = {}
        if not candidates:
            validation_by_work_unit[work_unit_id] = {
                "candidateCount": 0, "verdictCounts": {}, "acceptedCount": 0,
            }
            continue
        contract_empty = not (bundle.get("contract_evidence") or [])
        for candidate in candidates:
            finding = dict(candidate.get("finding") or {})
            no_citations = not (
                candidate.get("contract_citation_ids") or candidate.get("policy_citation_ids")
            )
            # Absence conclusion with an empty contract pool: there is nothing
            # to cite, so the §15.3 gate replaces citation checks entirely.
            if candidate.get("negative_claim") and no_citations and contract_empty:
                gate_passed, gate_checks = _negative_gate(
                    work_unit, bundle, contract_map,
                    counter_analysis.get(work_unit_id) or [], snapshot,
                )
                negative_checks.append({
                    "workUnitId": work_unit_id,
                    "candidateId": candidate.get("candidate_id"),
                    "passed": gate_passed,
                    "checks": gate_checks,
                    "validationPath": "GATE_ONLY",
                })
                finding["negativeGateChecks"] = gate_checks
                if gate_passed:
                    verdict = "PASS"
                    finding["validationVerdict"] = verdict
                    finding["validationChecks"] = gate_checks
                    finding["needsMoreEvidence"] = False
                else:
                    # §15.3: only "当前证据范围内暂未确认" may be stated.
                    verdict = "NEED_MORE_EVIDENCE"
                    original = str(candidate.get("claim") or "")
                    finding["claim"] = f"当前证据范围内暂未确认：{original[:200]}"
                    finding["title"] = finding.get("title") or original[:200]
                    finding["negativeConclusionSoftened"] = True
                    finding["validationVerdict"] = verdict
                    finding["validationChecks"] = gate_checks
                    finding["needsMoreEvidence"] = True
                    evidence_needs.append(_gate_need(
                        work_unit_id, "NEGATIVE_CLAIM_NOT_PROVEN",
                        f"负向结论门禁未通过，{len([c for c in gate_checks if not c['ok']])} 项前置条件不满足",
                    ))
                    evidence_needs.append(_gate_need(
                        work_unit_id, "POSSIBLE_COUNTER_EVIDENCE",
                        "未完成反证检索或相邻条款检查，可能存在例外约定",
                    ))
                unit_verdicts[verdict] = unit_verdicts.get(verdict, 0) + 1
                accepted.append(finding)
                continue
            outcome = validator.validate([candidate], bundle, snapshot)[0]
            verdict = str(outcome.get("verdict") or "UNKNOWN")
            unit_verdicts[verdict] = unit_verdicts.get(verdict, 0) + 1
            for need in outcome.get("evidence_needs") or []:
                evidence_needs.append(dict(need))
            if verdict == "REJECT":
                continue  # dropped — needs already recorded above
            finding["validationVerdict"] = verdict
            finding["validationChecks"] = outcome.get("checks") or []
            finding["needsMoreEvidence"] = verdict == "NEED_MORE_EVIDENCE"
            gate_checks: list[dict] = []
            gate_passed = True
            if candidate.get("negative_claim"):
                gate_passed, gate_checks = _negative_gate(
                    work_unit, bundle, contract_map,
                    counter_analysis.get(work_unit_id) or [], snapshot,
                )
                negative_checks.append({
                    "workUnitId": work_unit_id,
                    "candidateId": candidate.get("candidate_id"),
                    "passed": gate_passed,
                    "checks": gate_checks,
                    "validationPath": "VALIDATOR_PLUS_GATE",
                })
                if not gate_passed:
                    # §15.3: only "当前证据范围内暂未确认" may be stated.
                    original = str(candidate.get("claim") or "")
                    finding["claim"] = f"当前证据范围内暂未确认：{original[:200]}"
                    finding["title"] = finding.get("title") or original[:200]
                    finding["negativeConclusionSoftened"] = True
                    finding["negativeGateChecks"] = gate_checks
                    if verdict not in {"NEED_MORE_EVIDENCE", "DOWNGRADE_CONFIDENCE"}:
                        finding["validationVerdict"] = "DOWNGRADE_CONFIDENCE"
                    finding["needsMoreEvidence"] = True
            accepted.append(finding)
        validated_by_unit[work_unit_id] = accepted
        validation_by_work_unit[work_unit_id] = {
            "candidateCount": len(candidates),
            "verdictCounts": unit_verdicts,
            "acceptedCount": len(accepted),
        }
        observations.append({
            "callId": f"v2-validate-{work_unit_id}-{state.get('subject_id', 0)}",
            "planStepId": f"validate_{work_unit_id}",
            "toolName": "groundingValidate",
            "arguments": {"workUnitId": work_unit_id, "candidateCount": len(candidates)},
            "output": validation_by_work_unit[work_unit_id],
            "status": "DONE",
        })

    # v1-compatible validated findings: accepted candidates, evidence-status
    # preserved so the reused composer and eval scorer see normal shapes.
    validated_findings: list[dict] = []
    for work_unit in work_units:
        validated_findings.extend(validated_by_unit.get(str(work_unit["work_unit_id"])) or [])
    # Drop v1 domainKey overrides: work units carry their own domain key.
    for finding in validated_findings:
        finding.setdefault("domainKey", finding.get("workUnitId", "").split(".", 1)[0])
        finding.setdefault("domainName", "工作项")

    seen_need_ids: set[str] = set()
    deduped_needs: list[dict] = []
    for need in evidence_needs:
        need_id = str(need.get("need_id") or "")
        if need_id and need_id in seen_need_ids:
            continue
        seen_need_ids.add(need_id)
        deduped_needs.append(need)

    return {
        "state_revision": state.get("state_revision", 0) + 1,
        "current_node": "validate_grounding",
        "validated_findings": validated_findings,
        "validation_by_work_unit": validation_by_work_unit,
        "evidence_needs": deduped_needs,
        "negative_conclusion_checks": negative_checks,
        "observations": observations,
    }


# ─────────────────────────── 12. omission audit ─────────────────────────────


def audit_coverage(state: dict[str, Any]) -> dict[str, Any]:
    """OmissionAuditor — three failure classes (PRD §11.4):

    * 没审到 (never retrieved): catalog clause types absent from every bundle,
      and planned items that never produced a candidate;
    * 审到了但没风险 (evidence without findings): WorkUnit has evidence but
      zero accepted findings — a silent miss;
    * 证据不足: accepted findings flagged NEED_MORE_EVIDENCE / negative gate
      failures.

    Outputs EvidenceNeed[] and drives the retry loop; nothing is written into
    the report from here.
    """
    from .nodes.reflection import _eval_required_domain_keys

    work_units = state.get("work_units") or []
    bundles = state.get("evidence_bundles_by_work_unit") or {}
    validation_by_unit = state.get("validation_by_work_unit") or {}
    counter_analysis = state.get("counter_analysis_by_work_unit") or {}
    snapshot = state.get("evidence_snapshot") or {}
    retry_budget = int(state.get("retry_budget") or 0)
    needs: list[dict] = list(state.get("evidence_needs") or [])

    def _need(work_unit_id: str, reason_code: str, description: str, *, query_hints=None, retryable=True) -> dict:
        need = {
            "need_id": f"need-{work_unit_id}-{reason_code}",
            "work_unit_id": work_unit_id,
            "reason_code": reason_code,
            "description": description[:300],
            "missing_source_types": [],
            "missing_fields": [],
            "query_hints": list(query_hints or []),
            "clause_type_hints": [],
            "must_expand_neighbors": reason_code == "NEGATIVE_CLAIM_NOT_PROVEN",
            "must_search_attachments": False,
            "retryable": retryable,
        }
        return need

    coverage_by_work_unit: dict[str, dict[str, Any]] = {}
    checklist: list[dict] = []
    per_domain: dict[str, list[str]] = {}

    # clause ids used anywhere — 没审到 evidence detection
    used_clause_ids: set[str] = set()
    used_clause_types: set[str] = set()
    for bundle in bundles.values():
        for hit in bundle.get("contract_evidence") or []:
            if hit.get("sourceId"):
                used_clause_ids.add(str(hit["sourceId"]))
            if hit.get("clauseType"):
                used_clause_types.add(str(hit["clauseType"]).upper())

    catalog = snapshot.get("clause_catalog") or []
    unused_types = sorted({
        str(entry.get("clauseType") or "OTHER").upper()
        for entry in catalog
        if str(entry.get("clauseType") or "OTHER").upper() not in used_clause_types
    })
    unused_clauses = [
        entry for entry in catalog
        if f"CONTRACT_CLAUSE:{entry.get('clauseId')}" not in used_clause_ids
        and str(entry.get("clauseType") or "OTHER").upper() not in used_clause_types
    ]

    for work_unit in work_units:
        work_unit_id = str(work_unit["work_unit_id"])
        bundle = bundles.get(work_unit_id) or {}
        unit_validation = validation_by_unit.get(work_unit_id) or {}
        evidence_count = len(bundle.get("contract_evidence") or []) + len(bundle.get("policy_evidence") or [])
        accepted_count = int(unit_validation.get("acceptedCount") or 0)
        unit_needs = [need for need in needs if str(need.get("work_unit_id")) == work_unit_id]
        retryable_unit_needs = [need for need in unit_needs if need.get("retryable")]
        counter_entries = counter_analysis.get(work_unit_id) or []
        significant_counter = [entry for entry in counter_entries if entry["classification"] != "OTHER"]

        status = "COVERED"
        reasons: list[str] = []
        if not evidence_count:
            status = "NO_EVIDENCE"
            reasons.append("未检索到合同证据")
            if not any(need.get("reason_code") == "NO_CONTRACT_EVIDENCE" for need in unit_needs):
                needs.append(_need(work_unit_id, "NO_CONTRACT_EVIDENCE", "未检索到任何合同条款证据",
                                   query_hints=list(work_unit.get("query_intents") or [])[:3]))
        elif accepted_count == 0:
            status = "ANALYZED_NO_FINDINGS"
            reasons.append("有证据但未形成可落地发现")
            if not any(need.get("reason_code") == "MISSING_SUBCHECK" for need in unit_needs):
                needs.append(_need(work_unit_id, "MISSING_SUBCHECK", "子检查项有证据但未形成风险发现",
                                   query_hints=["检查 " + work_unit.get("label", "")]))
        elif retryable_unit_needs:
            status = "NEEDS_MORE"
            reasons.extend(str(need.get("description"))[:120] for need in retryable_unit_needs[:2])
        if significant_counter:
            reasons.append(f"反证命中 {len(significant_counter)} 条（{significant_counter[0]['classification']}）")

        coverage_by_work_unit[work_unit_id] = {
            "status": status,
            "label": work_unit.get("label"),
            "domainKey": work_unit.get("domainKey"),
            "priority": work_unit.get("priority"),
            "evidenceCount": evidence_count,
            "acceptedCount": accepted_count,
            "needCount": len(unit_needs),
            "reasons": reasons,
            "negativeGateFailures": sum(
                1 for check in (state.get("negative_conclusion_checks") or [])
                if check.get("workUnitId") == work_unit_id and not check.get("passed")
            ),
        }
        per_domain.setdefault(str(work_unit["domainKey"]), []).append(work_unit_id)
        checklist.append({
            "workUnitId": work_unit_id,
            "domainKey": work_unit.get("domainKey"),
            "label": work_unit.get("label"),
            "coverageState": status,
            "evidenceCount": evidence_count,
            "findingCount": accepted_count,
            "reasons": reasons,
        })

    if unused_clauses:
        for entry in unused_clauses[:3]:
            work_unit_id = "unused_evidence"
            if not any(need.get("need_id") == f"need-{work_unit_id}-MISSING_SUBCHECK" for need in needs):
                needs.append(_need(
                    work_unit_id, "MISSING_SUBCHECK",
                    f"条款 {entry.get('clauseNumber')}（{entry.get('title') or '未命名'}）未被任何工作项检索到",
                    query_hints=[str(entry.get("title") or entry.get("clauseNumber"))][:1],
                ))

    # Domain-level v1-compatible coverage for the reused composer + eval gating.
    eval_required = _eval_required_domain_keys(state)
    domains: dict[str, dict[str, Any]] = {}
    domain_tasks = state.get("domain_tasks") or []
    for task in domain_tasks:
        domain_key = str(task.get("domainKey") or "")
        unit_ids = per_domain.get(domain_key) or []
        unit_states = [coverage_by_work_unit.get(uid, {}) for uid in unit_ids]
        gated = eval_required is None or domain_key in eval_required
        covered_units = sum(
            1 for unit_state in unit_states if unit_state.get("status") == "COVERED"
        )
        domains[domain_key] = {
            "domainName": task.get("domainName") or domain_key,
            "covered": bool(unit_ids) and covered_units == len(unit_ids) and gated,
            "coverageState": "COVERED" if covered_units == len(unit_ids) else "PARTIAL",
            "workUnitCount": len(unit_ids),
            "coveredWorkUnitCount": covered_units,
            "findingCount": sum(int(unit_state.get("acceptedCount") or 0) for unit_state in unit_states),
            "evidenceCount": sum(int(unit_state.get("evidenceCount") or 0) for unit_state in unit_states),
            "gated": gated,
            "highlights": [
                str(unit_state.get("label") or "")
                for unit_state in unit_states if unit_state.get("status") != "COVERED"
            ][:3],
        }

    uncovered = [
        work_unit_id for work_unit_id, entry in coverage_by_work_unit.items()
        if entry.get("status") != "COVERED" and entry.get("domainKey") and (
            eval_required is None or entry.get("domainKey") in eval_required
        )
    ]
    if not uncovered:
        coverage_status = "CONFIRMED"
    elif retry_budget > 0 and any(
        any(need.get("retryable") for need in needs if need.get("work_unit_id") == work_unit_id)
        for work_unit_id in uncovered
    ):
        coverage_status = "NEED_MORE_EVIDENCE"
    else:
        coverage_status = "CANNOT_RESOLVE"

    # Retry targets: negative-gate failures and no-evidence items first,
    # priority-ordered, bounded (§15.4 每轮只处理高优先级缺口).
    def _target_sort_key(work_unit_id: str) -> tuple[int, int, str]:
        entry = coverage_by_work_unit.get(work_unit_id) or {}
        priority_rank = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}.get(str(entry.get("priority")), 1)
        gate_failures = int(entry.get("negativeGateFailures") or 0)
        return (priority_rank, -gate_failures, work_unit_id)

    reanalysis_targets = sorted(uncovered, key=_target_sort_key)[:MAX_REANALYSIS_TARGETS]
    if coverage_status == "CANNOT_RESOLVE":
        reanalysis_targets = []  # budget exhausted or needs are non-retryable

    seen_need_ids: set[str] = set()
    deduped_needs: list[dict] = []
    for need in needs:
        need_id = str(need.get("need_id") or "")
        if need_id and need_id in seen_need_ids:
            continue
        seen_need_ids.add(need_id)
        deduped_needs.append(need)

    summary = {
        "workUnitCount": len(work_units),
        "coveredWorkUnits": sum(1 for entry in coverage_by_work_unit.values() if entry.get("status") == "COVERED"),
        "noEvidenceWorkUnits": sum(1 for entry in coverage_by_work_unit.values() if entry.get("status") == "NO_EVIDENCE"),
        "analyzedNoFindingsWorkUnits": sum(1 for entry in coverage_by_work_unit.values() if entry.get("status") == "ANALYZED_NO_FINDINGS"),
        "needsMoreWorkUnits": sum(1 for entry in coverage_by_work_unit.values() if entry.get("status") == "NEEDS_MORE"),
        "unusedClauseCount": len(unused_clauses),
        "unusedClauseTypes": unused_types,
        "retryBudget": retry_budget,
        "evalFocusDomains": sorted(eval_required) if eval_required is not None else None,
    }
    coverage = {
        "status": coverage_status,
        "domains": domains,
        "summary": summary,
        "checklist": checklist,
        "missingDomains": [
            domain_key for domain_key, info in domains.items()
            if info.get("gated") and not info.get("covered")
        ],
        "retryable": coverage_status == "NEED_MORE_EVIDENCE",
    }
    return {
        "state_revision": state.get("state_revision", 0) + 1,
        "current_node": "audit_coverage",
        "coverage_by_work_unit": coverage_by_work_unit,
        "coverage": coverage,
        "reflection": {
            "adequate": coverage_status == "CONFIRMED",
            "status": coverage_status,
            "summary": summary,
            "checklist": checklist,
            "retryable": coverage_status == "NEED_MORE_EVIDENCE",
        },
        "evidence_needs": deduped_needs,
        "reanalysis_targets": reanalysis_targets,
        "observations": [{
            "callId": f"v2-audit-{state.get('subject_id', 0)}",
            "planStepId": "audit_coverage",
            "toolName": "omissionAudit",
            "arguments": {"workUnitCount": len(work_units)},
            "output": summary,
            "status": "DONE",
        }],
    }


def _route_after_audit(state: dict[str, Any]) -> str:
    coverage = state.get("coverage") or {}
    if coverage.get("status") == "CONFIRMED":
        return "compose_report"
    if int(state.get("retry_budget") or 0) <= 0 or not state.get("reanalysis_targets"):
        return "compose_limited_report"
    return "targeted_retrieval"


# ─────────────────────── 13/14. targeted retrieval + reanalysis ─────────────


def targeted_retrieval(state: dict[str, Any]) -> dict[str, Any]:
    """Round-2 retrieval for reanalysis targets only (PRD §15.4).

    New evidence is UNIONed with the first round via merge_bundles — the old
    bundle is never dropped, and only affected WorkUnits are touched.
    """
    from app.agent_runtime.harness.models import default_retrieval_request
    from app.agent_runtime.harness.retrieval import get_orchestrator, merge_bundles
    from app.agent_runtime.harness.observation import ObservabilityRecorder

    case_id = int(state.get("subject_id") or 0)
    snapshot = state.get("evidence_snapshot") or {}
    clause_texts = state.get("contract_evidence_snapshot") or []
    orchestrator = get_orchestrator()
    bundles = dict(state.get("evidence_bundles_by_work_unit") or {})
    needs = state.get("evidence_needs") or []
    targets = list(state.get("reanalysis_targets") or [])
    work_unit_by_id = {str(unit["work_unit_id"]): unit for unit in state.get("work_units") or []}
    round_no = int((state.get("retry_state") or {}).get("reflection_rounds", 0)) + 2

    domain_results: dict[str, list[dict]] = {}
    observations: list[dict[str, Any]] = []
    merged_count = 0
    for work_unit_id in targets:
        work_unit = work_unit_by_id.get(work_unit_id)
        if not work_unit:
            continue
        unit_needs = [need for need in needs if str(need.get("work_unit_id")) == work_unit_id]
        hints: list[str] = []
        for need in unit_needs:
            hints.extend(need.get("query_hints") or [])
        if not hints:
            hints = list(work_unit.get("query_intents") or [])[:2]
        hints = list(dict.fromkeys(str(value).strip() for value in hints if str(value).strip()))[:4]
        hints = [hint for hint in hints if hint]
        hints = hints or [str(work_unit.get("label") or "")]
        request = default_retrieval_request(
            case_id, snapshot, work_unit_id, hints,
            clause_types=list(work_unit.get("required_clause_types") or []),
            final_limit=12,
            require_counter_evidence=True,
        )
        try:
            targeted_bundle = orchestrator.retrieve_sync(snapshot, request, clauses=clause_texts)
        except Exception as exc:
            logger.exception("v2 targeted retrieval failed for %s: %s", work_unit_id, exc)
            from app.agent_runtime.harness.retrieval import empty_bundle
            targeted_bundle = empty_bundle(request, [f"orchestrator failed: {exc}"])
        primary = bundles.get(work_unit_id) or {"work_unit_id": work_unit_id}
        merged = merge_bundles(primary, targeted_bundle)
        _expand_adjacent_clauses(merged.get("contract_evidence") or [], snapshot)
        _expand_adjacent_clauses(merged.get("counter_evidence") or [], snapshot)
        stats = dict(merged.get("retrieval_stats") or {})
        stats["adjacentExpansionCount"] = int(stats.get("adjacentExpansionCount") or 0) + sum(
            1 for hit in (merged.get("contract_evidence") or []) + (merged.get("counter_evidence") or [])
            if hit.get("adjacentClauses")
        )
        merged["retrieval_stats"] = stats
        bundles[work_unit_id] = merged
        merged_count += 1
        observations.append({
            "callId": f"v2-targeted-{work_unit_id}-{case_id}-r{round_no}",
            "planStepId": f"targeted_{work_unit_id}",
            "toolName": "retrieveEvidenceBundle",
            "arguments": {"workUnitId": work_unit_id, "queryVariants": hints, "round": round_no},
            "output": ObservabilityRecorder.bundle_summary(merged),
            "status": "DONE",
        })

    # refresh the aggregated domain view for affected domains only
    affected_domains = {
        str(work_unit_by_id[work_unit_id]["domainKey"])
        for work_unit_id in targets if work_unit_id in work_unit_by_id
    }
    existing_domain_results = dict(state.get("domain_results") or {})
    for domain_key in affected_domains:
        seen: set[str] = set()
        flat: list[dict] = []
        for work_unit in state.get("work_units") or []:
            if str(work_unit["domainKey"]) != domain_key:
                continue
            bundle = bundles.get(str(work_unit["work_unit_id"])) or {}
            for item in _flat_bundle(bundle):
                source_id = str(item.get("sourceId") or "")
                if source_id and source_id not in seen:
                    seen.add(source_id)
                    flat.append(item)
        existing_domain_results[domain_key] = flat

    retry_state = dict(state.get("retry_state") or {})
    retry_state["reflection_rounds"] = int(retry_state.get("reflection_rounds", 0)) + 1
    return {
        "state_revision": state.get("state_revision", 0) + 1,
        "current_node": "targeted_retrieval",
        "evidence_bundles_by_work_unit": bundles,
        "domain_results": existing_domain_results,
        "retry_state": retry_state,
        "retry_budget": int(state.get("retry_budget") or 0) - 1,
        "observations": observations,
    }


def reanalyze_affected_work_units(state: dict[str, Any]) -> dict[str, Any]:
    """Re-run analysis → counter → merge → validation for reanalysis targets.

    Everything else is preserved untouched; the audit runs again after this
    node (targeted_retrieval → reanalyze → audit_coverage).
    """
    targets = set(state.get("reanalysis_targets") or [])
    if not targets:
        return {
            "state_revision": state.get("state_revision", 0) + 1,
            "current_node": "reanalyze_affected_work_units",
        }
    work_units = [unit for unit in state.get("work_units") or []
                  if str(unit["work_unit_id"]) in targets]
    rule_findings = state.get("rule_findings") or []
    bundles = state.get("evidence_bundles_by_work_unit") or {}

    # analysis for targets only
    from app.agent_runtime.runtime import _v2_analysis_concurrency

    results: dict[str, tuple[list[dict], str, list[dict]]] = {}
    if len(work_units) <= 3:
        for work_unit in work_units:
            wid, findings, status, needs = _analyze_one_work_unit(
                state, work_unit, bundles.get(str(work_unit["work_unit_id"])) or {}, rule_findings)
            results[wid] = (findings, status, needs)
    else:
        with ThreadPoolExecutor(max_workers=_v2_analysis_concurrency.get()) as executor:
            futures = {
                executor.submit(_analyze_one_work_unit, state, work_unit,
                                bundles.get(str(work_unit["work_unit_id"])) or {}, rule_findings): work_unit
                for work_unit in work_units
            }
            for future in as_completed(futures):
                wid, findings, status, needs = future.result()
                results[wid] = (findings, status, needs)

    findings_by_work_unit = dict(state.get("findings_by_work_unit") or {})
    for work_unit in work_units:
        work_unit_id = str(work_unit["work_unit_id"])
        findings, _status, _needs = results.get(work_unit_id, ([], "MISSING", []))
        findings_by_work_unit[work_unit_id] = [
            _annotate_finding(finding, work_unit) for finding in findings
        ]

    # counter re-analysis for targets (deterministic)
    counter_analysis = dict(state.get("counter_analysis_by_work_unit") or {})
    for work_unit in work_units:
        work_unit_id = str(work_unit["work_unit_id"])
        bundle = bundles.get(work_unit_id) or {}
        counter_analysis[work_unit_id] = [
            {
                "sourceId": hit.get("sourceId"),
                "clauseNumber": hit.get("clauseNumber"),
                "title": hit.get("title"),
                "classification": _classify_counter_hit(hit),
                "snippet": str(hit.get("snippet") or "")[:220],
            }
            for hit in (bundle.get("counter_evidence") or [])
        ]

    # merge + validate for targets — reuse the shared nodes on a narrowed state
    narrowed_state = {
        **state,
        "work_units": work_units,
        "findings_by_work_unit": findings_by_work_unit,
        "counter_analysis_by_work_unit": counter_analysis,
    }
    narrowed_state = {**narrowed_state, **merge_candidates(narrowed_state)}
    validated_update = validate_grounding(narrowed_state)

    # preserve untouched units' validated findings
    kept_findings = [
        finding for finding in (state.get("validated_findings") or [])
        if str(finding.get("workUnitId") or "").split(".", 1)[0] not in targets
        and str(finding.get("workUnitId") or "") not in targets
    ]
    validated_by_unit = dict(state.get("validation_by_work_unit") or {})
    for work_unit_id, unit_findings in findings_by_work_unit.items():
        if work_unit_id in targets:
            validated_by_unit[work_unit_id] = {
                "candidateCount": len((state.get("merged_candidates_by_work_unit") or {}).get(work_unit_id) or []),
                "verdictCounts": {}, "acceptedCount": len(unit_findings),
            }

    return {
        "state_revision": state.get("state_revision", 0) + 1,
        "current_node": "reanalyze_affected_work_units",
        "findings_by_work_unit": findings_by_work_unit,
        "counter_analysis_by_work_unit": counter_analysis,
        "merged_candidates_by_work_unit": {
            **state.get("merged_candidates_by_work_unit", {}),
            **(narrowed_state.get("merged_candidates_by_work_unit") or {}),
        },
        "validated_findings": kept_findings + validated_update.get("validated_findings", []),
        "validation_by_work_unit": validated_by_unit,
        "evidence_needs": validated_update.get("evidence_needs"),
        "negative_conclusion_checks": validated_update.get("negative_conclusion_checks"),
        "observations": validated_update.get("observations") or [],
    }


# ─────────────────────────── graph assembly ───────────────────────────


def build_contract_review_v2_graph(checkpointer: Any = None) -> Any:
    builder = StateGraph(BaseGraphState)

    # shared with v1: context, inventory, rules, artifact tail
    builder.add_node("load_run_context", load_run_context)
    builder.add_node("freeze_case_snapshot", freeze_case_snapshot)
    builder.add_node("inventory_clauses", inventory_clauses)
    builder.add_node("run_deterministic_rules", run_deterministic_rules)
    builder.add_node("compose_report", compose_report)
    builder.add_node("compose_limited_report", compose_limited_report)
    builder.add_node("validate_schema", validate_schema)
    builder.add_node("repair_artifact", repair_artifact)
    builder.add_node("prepare_human_review", prepare_human_review)
    builder.add_node("persist_report", persist_report)

    # v2 middle
    builder.add_node("build_contract_map", build_contract_map)
    builder.add_node("plan_work_units", plan_work_units)
    builder.add_node("retrieve_evidence_for_work_units", retrieve_evidence_for_work_units)
    builder.add_node("analyze_work_unit_risks", analyze_work_unit_risks)
    builder.add_node("analyze_counter_evidence", analyze_counter_evidence)
    builder.add_node("merge_candidates", merge_candidates)
    builder.add_node("validate_grounding", validate_grounding)
    builder.add_node("audit_coverage", audit_coverage)
    builder.add_node("targeted_retrieval", targeted_retrieval)
    builder.add_node("reanalyze_affected_work_units", reanalyze_affected_work_units)

    builder.add_edge(START, "load_run_context")
    builder.add_edge("load_run_context", "freeze_case_snapshot")
    builder.add_edge("freeze_case_snapshot", "inventory_clauses")
    builder.add_edge("inventory_clauses", "build_contract_map")
    builder.add_edge("build_contract_map", "plan_work_units")
    builder.add_edge("plan_work_units", "retrieve_evidence_for_work_units")
    builder.add_edge("retrieve_evidence_for_work_units", "run_deterministic_rules")
    builder.add_edge("run_deterministic_rules", "analyze_work_unit_risks")
    builder.add_edge("analyze_work_unit_risks", "analyze_counter_evidence")
    builder.add_edge("analyze_counter_evidence", "merge_candidates")
    builder.add_edge("merge_candidates", "validate_grounding")
    builder.add_edge("validate_grounding", "audit_coverage")

    builder.add_conditional_edges(
        "audit_coverage",
        _route_after_audit,
        {
            "compose_report": "compose_report",
            "compose_limited_report": "compose_limited_report",
            "targeted_retrieval": "targeted_retrieval",
        },
    )
    builder.add_edge("targeted_retrieval", "reanalyze_affected_work_units")
    builder.add_edge("reanalyze_affected_work_units", "audit_coverage")

    builder.add_edge("compose_report", "validate_schema")
    builder.add_edge("compose_limited_report", "validate_schema")
    builder.add_conditional_edges(
        "validate_schema",
        _route_after_schema,
        {
            "persist_report": "persist_report",
            "prepare_human_review": "prepare_human_review",
            "repair_artifact": "repair_artifact",
            "compose_limited_report": "compose_limited_report",
        },
    )
    builder.add_edge("repair_artifact", "validate_schema")
    builder.add_edge("prepare_human_review", "persist_report")
    builder.add_edge("persist_report", END)

    return builder.compile(checkpointer=checkpointer) if checkpointer else builder.compile()


def register(registry=None) -> None:
    """Register contract_review v2 alongside v1 — v2 is NOT the default."""
    if registry is None:
        from .registry import get_graph_registry
        registry = get_graph_registry()

    registry.register(
        name="contract_review",
        version="v2",
        builder=build_contract_review_v2_graph,
    )
    logger.info("Registered ContractReviewGraph v2 (pilot, not default)")
