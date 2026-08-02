"""Contract Agent tool registry — Phase 4.

Read-only tools execute directly. Write tools generate PENDING_APPROVAL actions.
"""

from __future__ import annotations

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)

# ── OpenAI function-calling definitions ────────────────────────────

CONTRACT_TOOL_DEFINITIONS: list[dict] = [
    {
        "type": "function",
        "function": {
            "name": "getContractCase",
            "description": "读取合同案件基本信息、主体、金额和状态",
            "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "listContractDocuments",
            "description": "列出合同正文、附件和版本",
            "parameters": {
                "type": "object",
                "properties": {
                    "documentType": {"type": "string", "description": "MAIN|ATTACHMENT|PRICING|CERTIFICATE"},
                },
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "readContractClause",
            "description": "按条款类型读取合同条款原文和语义要素",
            "parameters": {
                "type": "object",
                "properties": {
                    "clauseType": {"type": "string", "description": "LIABILITY|PAYMENT|CONFIDENTIALITY|ACCEPTANCE|TERMINATION|IP|DATA_PROTECTION"},
                    "limit": {"type": "integer", "description": "返回条数", "minimum": 1},
                },
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "searchPolicyKnowledge",
            "description": "检索适用的企业采购制度和标准条款",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "与当前条款相关的检索问题"},
                    "clauseType": {"type": "string", "description": "条款类型过滤"},
                    "limit": {"type": "integer", "description": "返回条数", "minimum": 1},
                },
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "findStandardClause",
            "description": "检索与给定条款最匹配的企业标准条款（语义匹配）",
            "parameters": {
                "type": "object",
                "properties": {
                    "clauseType": {"type": "string", "description": "条款类型"},
                    "clauseText": {"type": "string", "description": "待匹配的条款原文"},
                },
                "required": ["clauseType"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "searchHistoricalDecisions",
            "description": "检索历史合同中的类似条款、协商结果和已批准例外",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "检索词"},
                    "clauseType": {"type": "string", "description": "条款类型"},
                    "limit": {"type": "integer", "description": "返回条数", "minimum": 1},
                },
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "evaluateReviewRules",
            "description": "按合同类型和条款执行确定性审查规则，返回违规发现",
            "parameters": {
                "type": "object",
                "properties": {
                    "ruleSet": {"type": "string", "description": "规则集版本，如 SERVICE_PROCUREMENT_V1"},
                    "clauseType": {"type": "string", "description": "仅评估指定类型的规则"},
                },
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "calculateContractRisk",
            "description": "用固定规则和当前发现快照计算合同风险分；LLM 不得自行评分",
            "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "getContractParties",
            "description": "读取合同主体信息及风险评分",
            "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
        },
    },
]

CONTRACT_TOOL_NAMES = {t["function"]["name"] for t in CONTRACT_TOOL_DEFINITIONS}

# Concurrency groups (same pattern as project tools — F5)
_CONCURRENT_GROUP = {
    "getContractCase":          "read",
    "getContractParties":       "read",
    "listContractDocuments":    "read",
    "readContractClause":       "read",
    "searchPolicyKnowledge":    "search",
    "findStandardClause":       "search",
    "searchHistoricalDecisions": "search",
    "evaluateReviewRules":      "compute",
    "calculateContractRisk":    "compute",
}
_GROUP_ORDER = ["read", "search", "compute"]


class ContractToolRegistry:
    """Registry of allowlisted contract tools."""

    def __init__(self, store):  # ContractStore
        self.store = store

    def definitions(self) -> list[dict]:
        return CONTRACT_TOOL_DEFINITIONS

    def supports(self, tool_name: str) -> bool:
        return tool_name in CONTRACT_TOOL_NAMES

    @staticmethod
    def concurrency_group(tool_name: str) -> str:
        return _CONCURRENT_GROUP.get(tool_name, "read")

    @staticmethod
    def group_order() -> list[str]:
        return list(_GROUP_ORDER)

    async def execute(self, ctx, tool_name: str, arguments: dict) -> dict:
        if not self.supports(tool_name):
            raise ValueError(f"Tool not allowlisted: {tool_name}")

        case_id = ctx.project_id  # subject_id mapped to project_id in StartRunRequest

        if tool_name == "getContractCase":
            return {"case": await self.store.get_case(case_id)}

        if tool_name == "getContractParties":
            return {"parties": await self.store.get_parties(case_id)}

        if tool_name == "listContractDocuments":
            return {"documents": await self.store.list_documents(case_id, arguments)}

        if tool_name == "readContractClause":
            return {"clauses": await self.store.read_clauses(case_id, arguments)}

        if tool_name == "searchPolicyKnowledge":
            return {"items": await self.store.search_policy(case_id, arguments)}

        if tool_name == "findStandardClause":
            return {"matches": await self.store.find_standard_clause(arguments)}

        if tool_name == "searchHistoricalDecisions":
            return {"items": await self.store.search_historical(case_id, arguments)}

        if tool_name == "evaluateReviewRules":
            return {"findings": await self.store.evaluate_rules(case_id, arguments)}

        if tool_name == "calculateContractRisk":
            findings = await self.store.get_open_findings(case_id)
            rules = await self.store.get_active_rules(arguments.get("ruleSet", ""))
            case = await self.store.get_case(case_id)
            from .contract_risk_scoring import ContractRiskScoringEngine
            engine = ContractRiskScoringEngine()
            return {"scoring": engine.score(
                case.get("case", {}), rules, findings)}

        raise ValueError(f"Tool not allowlisted: {tool_name}")

    @staticmethod
    def citations_from(observations: list[dict]) -> list[dict]:
        """Extract unique citations from search-tool observations."""
        seen: dict[str, dict] = {}
        for obs in observations:
            output = obs.get("output")
            if not isinstance(output, dict):
                continue
            for key in ("items", "clauses", "matches", "documents"):
                items = output.get(key)
                if isinstance(items, list):
                    for item in items:
                        if isinstance(item, dict):
                            sid = item.get("id") or item.get("title", "")
                            if sid and sid not in seen:
                                seen[sid] = dict(item)
        return list(seen.values())

    @staticmethod
    def scoring_from(observations: list[dict]) -> dict[str, Any]:
        for obs in reversed(observations):
            output = obs.get("output")
            if isinstance(output, dict) and "scoring" in output:
                return dict(output["scoring"])
        return {}
