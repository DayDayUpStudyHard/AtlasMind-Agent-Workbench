"""Risk-domain planning: mandatory baseline plus contract-specific LLM domains."""

from __future__ import annotations

import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

VALID_CLAUSE_TYPES = {
    "LIABILITY", "PAYMENT", "CONFIDENTIALITY", "ACCEPTANCE",
    "TERMINATION", "IP", "DATA_PROTECTION", "OTHER",
}

# These domains are always reviewed. The planner may add relevant domains but cannot
# remove this baseline, which protects recall when the model overlooks a common risk.
MANDATORY_DOMAINS: list[dict[str, Any]] = [
    {
        "domainKey": "party_authority",
        "domainName": "主体资格与授权",
        "objective": "核验签约主体、资质、授权链、签署权限及主体信息一致性",
        "requiredClauseTypes": ["LIABILITY", "OTHER"],
        "queries": ["签约主体 资质 授权 签署权限 法定代表人"],
        "priority": "HIGH",
        "source": "SYSTEM_BASELINE",
    },
    {
        "domainKey": "scope_delivery_acceptance",
        "domainName": "范围、交付与验收",
        "objective": "检查工作范围、交付物、里程碑、验收标准、异议期和视为验收机制",
        "requiredClauseTypes": ["ACCEPTANCE", "OTHER"],
        "queries": ["服务范围 交付物 里程碑 验收标准 异议期限 视为验收"],
        "priority": "HIGH",
        "source": "SYSTEM_BASELINE",
    },
    {
        "domainKey": "price_payment_tax",
        "domainName": "价款、付款与税务",
        "objective": "检查金额、计价、付款条件、发票、税费、扣款、结算和付款前提",
        "requiredClauseTypes": ["PAYMENT", "ACCEPTANCE"],
        "queries": ["合同金额 付款条件 发票 税费 结算 扣款 付款前提"],
        "priority": "HIGH",
        "source": "SYSTEM_BASELINE",
    },
    {
        "domainKey": "liability_remedies",
        "domainName": "责任、违约与救济",
        "objective": "检查违约责任、责任上限、赔偿范围、免责、违约金、补救期和争议救济",
        "requiredClauseTypes": ["LIABILITY", "TERMINATION"],
        "queries": ["违约责任 责任上限 赔偿 间接损失 免责 违约金 补救期"],
        "priority": "HIGH",
        "source": "SYSTEM_BASELINE",
    },
    {
        "domainKey": "term_change_termination",
        "domainName": "期限、变更与终止",
        "objective": "检查生效期限、变更程序、解除条件、终止后义务、续签和通知期限",
        "requiredClauseTypes": ["TERMINATION", "OTHER"],
        "queries": ["生效 期限 变更 解除 终止 续签 通知期限 终止后义务"],
        "priority": "MEDIUM",
        "source": "SYSTEM_BASELINE",
    },
    {
        "domainKey": "confidentiality_data_ip",
        "domainName": "保密、数据与知识产权",
        "objective": "检查保密范围和期限、数据处理、个人信息、成果归属、许可与第三方权利",
        "requiredClauseTypes": ["CONFIDENTIALITY", "DATA_PROTECTION", "IP"],
        "queries": ["保密 数据处理 个人信息 成果归属 知识产权 许可 第三方权利"],
        "priority": "HIGH",
        "source": "SYSTEM_BASELINE",
    },
]


def _inventory_from_state(state: dict[str, Any]) -> dict[str, Any]:
    for observation in state.get("observations") or []:
        output = observation.get("output") or {}
        if isinstance(output, dict) and isinstance(output.get("inventory"), dict):
            return output["inventory"]
    return {}


def _load_clause_signals(case_id: int) -> list[dict[str, Any]]:
    """Load short clause excerpts for domain applicability planning."""
    try:
        from ...persistence import _conn, _normalize_value

        with _conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """SELECT id, clause_number AS clauseNumber, title,
                              clause_type AS clauseType, LEFT(content, 260) AS snippet
                       FROM contract_clause WHERE case_id=%s
                       ORDER BY id LIMIT 80""",
                    (case_id,),
                )
                return [_normalize_value(row) for row in cur.fetchall()]
    except Exception as exc:
        logger.warning("Unable to load clause signals for domain planner: %s", exc)
        return []


def _normalize_domain(raw: dict[str, Any], index: int) -> dict[str, Any] | None:
    name = str(raw.get("domainName") or raw.get("domain") or "").strip()[:80]
    objective = str(raw.get("objective") or "").strip()[:500]
    if not name or not objective:
        return None

    key = re.sub(r"[^a-z0-9_]+", "_", str(raw.get("domainKey") or "").lower()).strip("_")
    if not key:
        key = f"dynamic_domain_{index + 1}"
    clause_types = [
        str(value).upper() for value in (raw.get("requiredClauseTypes") or ["OTHER"])
        if str(value).upper() in VALID_CLAUSE_TYPES
    ] or ["OTHER"]
    queries = [str(value).strip()[:240] for value in (raw.get("queries") or []) if str(value).strip()]
    if not queries:
        queries = [f"{name} {objective}"[:240]]
    priority = str(raw.get("priority") or "MEDIUM").upper()
    if priority not in {"HIGH", "MEDIUM", "LOW"}:
        priority = "MEDIUM"

    return {
        "domainKey": key[:64],
        "domainName": name,
        "objective": objective,
        "whyApplicable": str(raw.get("whyApplicable") or "").strip()[:500],
        "requiredClauseTypes": list(dict.fromkeys(clause_types)),
        "queries": queries[:3],
        "priority": priority,
        "source": "LLM_DYNAMIC",
    }


def create_domain_tasks(state: dict[str, Any]) -> dict[str, Any]:
    """Merge the fixed recall baseline with bounded LLM-selected domains."""
    inventory = _inventory_from_state(state)
    planner_inventory = {
        **inventory,
        "clauses": _load_clause_signals(int(state.get("subject_id") or 0)),
    }
    baseline = [dict(item) for item in MANDATORY_DOMAINS]
    dynamic: list[dict[str, Any]] = []
    planner_error = ""

    try:
        from app.services.llm_service import LLMService

        result = LLMService().plan_contract_risk_domains(
            state.get("case_snapshot") or {},
            planner_inventory,
            baseline,
            int(state.get("run_id") or 0),
        )
        for index, raw in enumerate((result or {}).get("domains") or []):
            if not isinstance(raw, dict):
                continue
            normalized = _normalize_domain(raw, index)
            if normalized:
                dynamic.append(normalized)
            if len(dynamic) >= 4:
                break
    except Exception as exc:
        planner_error = str(exc)
        logger.warning("Contract risk domain planner unavailable; baseline remains active: %s", exc)

    seen_keys = {item["domainKey"] for item in baseline}
    domain_tasks = baseline[:]
    for item in dynamic:
        if item["domainKey"] in seen_keys:
            continue
        seen_keys.add(item["domainKey"])
        domain_tasks.append(item)

    observation = {
        "callId": f"graph-domain-planner-{state.get('subject_id', 0)}",
        "planStepId": "plan_risk_domains",
        "toolName": "planContractRiskDomains",
        "arguments": {"baselineCount": len(baseline), "maxDynamicDomains": 4},
        "output": {
            "baselineCount": len(baseline),
            "dynamicCount": len(domain_tasks) - len(baseline),
            "domains": [item["domainName"] for item in domain_tasks],
            "fallback": bool(planner_error),
            "error": planner_error[:300],
        },
        "status": "DONE" if not planner_error else "FALLBACK",
    }

    return {
        "state_revision": state.get("state_revision", 0) + 1,
        "current_node": "create_domain_tasks",
        "domain_tasks": domain_tasks,
        "observations": [observation],
    }
