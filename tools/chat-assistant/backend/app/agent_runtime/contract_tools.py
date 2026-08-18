"""Contract Agent tool registry — Phase 4.

Read-only tools execute directly. Write tools generate PENDING_APPROVAL actions.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from app.integrations.mcp.regulation import (
    RegulationQuery,
    RegulationResearchGateway,
    get_regulation_gateway,
)

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
            "name": "searchContractClause",
            "description": "在当前合同案件的私有条款切片中检索相关原文；命中子切片后返回完整父条款和相似度分数",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "检索问题或风险点"},
                    "topK": {"type": "integer", "description": "返回条数", "minimum": 1},
                },
                "required": ["query"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "getContractClauseDetail",
            "description": "按条款 ID 读取完整合同条款详情",
            "parameters": {
                "type": "object",
                "properties": {
                    "clauseId": {"type": "integer", "description": "合同条款 ID"},
                },
                "required": ["clauseId"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "searchContractTimeline",
            "description": "检索当前合同案件中的时间节点、相对期限和履约节点",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "如付款、验收、到期、续签"},
                    "limit": {"type": "integer", "description": "返回条数", "minimum": 1},
                },
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "listContractTimeline",
            "description": "列出当前合同案件已提取的全部时间节点",
            "parameters": {
                "type": "object",
                "properties": {
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
            "description": "检索适用的企业知识库文档、采购制度、验收标准和标准条款",
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
            "name": "searchExternalRegulation",
            "description": "仅在内部合同与制度证据不足时，检索已配置的官方法规 MCP；返回外部参考来源，不得替代合同原文或内部制度证据",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "待核验的法规问题"},
                    "jurisdiction": {"type": "string", "enum": ["CN"]},
                    "effectiveDate": {"type": "string", "description": "法规生效日期截点，ISO 日期"},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 5},
                },
                "required": ["query"],
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
    {
        "type": "function",
        "function": {
            "name": "extractObligations",
            "description": "从已批准合同条款中提取履约义务候选项（付款、交付、验收、通知、续签）",
            "parameters": {
                "type": "object",
                "properties": {
                    "clauseTypes": {"type": "array", "items": {"type": "string"},
                        "description": "PAYMENT|DELIVERY|ACCEPTANCE|NOTICE|RENEWAL"},
                },
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "verifyFulfillmentEvidence",
            "description": "验证已上传的履约证据是否覆盖某个履约义务或时间节点要求",
            "parameters": {
                "type": "object",
                "properties": {
                    "obligationId": {"type": "integer", "description": "履约义务 ID"},
                    "timelineNodeId": {"type": "integer", "description": "合同时间节点 ID"},
                },
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "compareContractVersions",
            "description": "比较两个合同版本的条款变化并标记受影响规则",
            "parameters": {
                "type": "object",
                "properties": {
                    "baseVersion": {"type": "integer", "description": "基线版本号"},
                    "newVersion": {"type": "integer", "description": "新版本号"},
                },
                "required": ["baseVersion", "newVersion"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "listClauseInventory",
            "description": "返回完整条款目录：总数、类型分布、每条ID/编号/标题/页数/字符数、缺失的关键条款类型。不受20条限制",
            "parameters": {
                "type": "object",
                "properties": {
                    "contractType": {"type": "string", "description": "合同类型：SERVICE_PROCUREMENT|GOODS_PURCHASE|NDA"},
                },
                "additionalProperties": False,
            },
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
    "getContractClauseDetail":  "read",
    "listClauseInventory":      "read",
    "listContractTimeline":     "read",
    "searchContractClause":     "search",
    "searchContractTimeline":   "search",
    "searchPolicyKnowledge":    "search",
    "findStandardClause":       "search",
    "searchHistoricalDecisions": "search",
    "searchExternalRegulation": "external",
    "evaluateReviewRules":      "compute",
    "calculateContractRisk":    "compute",
}
_GROUP_ORDER = ["read", "search", "external", "compute"]


class ContractToolRegistry:
    """Registry of allowlisted contract tools."""

    def __init__(self, store, regulation_gateway: RegulationResearchGateway | None = None):  # ContractStore
        self.store = store
        self.regulation_gateway = regulation_gateway or get_regulation_gateway()

    def definitions(self) -> list[dict]:
        return [
            definition for definition in CONTRACT_TOOL_DEFINITIONS
            if definition["function"]["name"] != "searchExternalRegulation"
            or self.regulation_gateway.available
        ]

    def supports(self, tool_name: str) -> bool:
        return tool_name in CONTRACT_TOOL_NAMES and (
            tool_name != "searchExternalRegulation" or self.regulation_gateway.available
        )

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

        if tool_name == "searchContractClause":
            return {"hits": await self.store.search_contract_clause(case_id, arguments)}

        if tool_name == "getContractClauseDetail":
            return {"clause": await self.store.get_clause_detail(case_id, arguments)}

        if tool_name == "listClauseInventory":
            return {"inventory": await self.store.list_clause_inventory(case_id, arguments)}

        if tool_name == "searchContractTimeline":
            return {"nodes": await self.store.search_timeline(case_id, arguments)}

        if tool_name == "listContractTimeline":
            return {"nodes": await self.store.list_timeline(case_id, arguments)}

        if tool_name == "searchPolicyKnowledge":
            return {"items": await self.store.search_policy(case_id, arguments)}

        if tool_name == "findStandardClause":
            return {"matches": await self.store.find_standard_clause(arguments)}

        if tool_name == "searchHistoricalDecisions":
            return {"items": await self.store.search_historical(case_id, arguments)}

        if tool_name == "searchExternalRegulation":
            query = RegulationQuery.from_arguments(arguments, max_results=5)
            return (await self.regulation_gateway.search(query, ctx.run_id)).payload()

        if tool_name == "evaluateReviewRules":
            return {"findings": await self.store.evaluate_rules(case_id, arguments)}

        if tool_name == "calculateContractRisk":
            rule_set = str(arguments.get("ruleSet", ""))
            findings = await self.store.evaluate_rules(
                case_id, {"ruleSet": rule_set or "SERVICE_PROCUREMENT_V1"}
            )
            rules = await self.store.get_active_rules(rule_set)
            case = await self.store.get_case(case_id)
            from .contract_risk_scoring import ContractRiskScoringEngine
            engine = ContractRiskScoringEngine()
            return {"scoring": engine.score(
                case, rules, findings)}

        if tool_name == "extractObligations":
            return {"obligations": await self.store.extract_obligations(case_id, arguments)}

        if tool_name == "verifyFulfillmentEvidence":
            return await self.store.verify_evidence(
                case_id,
                int(arguments.get("obligationId", 0) or 0),
                int(arguments.get("timelineNodeId", 0) or 0),
            )

        if tool_name == "compareContractVersions":
            return await self.store.compare_versions(
                case_id,
                int(arguments.get("baseVersion", 0)),
                int(arguments.get("newVersion", 0)))

        raise ValueError(f"Tool not allowlisted: {tool_name}")

    @staticmethod
    def citations_from(observations: list[dict]) -> list[dict]:
        """Extract unique citations from search-tool observations."""
        seen: dict[str, dict] = {}
        for obs in observations:
            output = obs.get("output")
            if not isinstance(output, dict):
                continue
            candidate_lists = [
                output.get(key)
                for key in ("items", "clauses", "matches", "documents", "sources")
            ]
            inventory = output.get("inventory")
            if isinstance(inventory, dict):
                candidate_lists.append(inventory.get("keyEvidenceClauses"))
            for items in candidate_lists:
                if isinstance(items, list):
                    for item in items:
                        if isinstance(item, dict):
                            source_type = str(item.get("sourceType") or item.get("retrievalType") or "UNKNOWN")
                            source_id = item.get("id") or item.get("sourceId") or item.get("title", "")
                            sid = f"{source_type}:{source_id}"
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
