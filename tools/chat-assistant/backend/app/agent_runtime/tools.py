"""Agent tool registry — 7 tools with OpenAI function-calling schemas.

All data access goes through EvidenceStore / ReportStore; no raw SQL here.
"""

from __future__ import annotations

from typing import Any

from .persistence import EvidenceStore, ReportStore
from .scoring import HealthScoringEngine

# ------------------------------------------------------------
# OpenAI function-calling tool definitions (Chinese descriptions)
# ------------------------------------------------------------

_TOOL_DEFINITIONS: list[dict] = [
    {
        "type": "function",
        "function": {
            "name": "getProjectProfile",
            "description": "读取当前项目的目标、仓库、里程碑和技术栈",
            "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "searchProjectEvidence",
            "description": "按关键词和类型检索当前项目真实 GitHub 证据",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "检索词，可为空"},
                    "objectTypes": {
                        "type": "array",
                        "description": "README/FILE_TREE/FILE/ISSUE/PR/COMMIT",
                        "items": {"type": "string"},
                    },
                    "limit": {"type": "integer", "description": "返回条数，1 到 20", "minimum": 1},
                },
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "searchProjectKnowledge",
            "description": "检索管理端绑定到当前项目的公司规范和技术文档",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "与任务相关的检索问题"},
                    "limit": {"type": "integer", "description": "返回条数，1 到 10", "minimum": 1},
                },
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "getProjectMemory",
            "description": "读取当前项目已确认事实和历史 Agent 情节记忆",
            "parameters": {
                "type": "object",
                "properties": {
                    "limit": {"type": "integer", "description": "返回条数，1 到 20", "minimum": 1},
                },
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "getRecentRuns",
            "description": "读取当前项目近期 Agent 运行及状态，避免重复工作",
            "parameters": {
                "type": "object",
                "properties": {
                    "limit": {"type": "integer", "description": "返回条数，1 到 10", "minimum": 1},
                },
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "getLatestReport",
            "description": "读取当前项目最近一份指定类型产物",
            "parameters": {
                "type": "object",
                "properties": {
                    "reportType": {
                        "type": "string",
                        "description": "HEALTH_REPORT、ONBOARDING_GUIDE 或 DECISION_MEMO",
                    },
                },
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "calculateHealthScore",
            "description": "用固定规则和当前证据快照计算项目健康分；LLM 不得自行评分",
            "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
        },
    },
]

_TOOL_NAMES = {t["function"]["name"] for t in _TOOL_DEFINITIONS}

_CITATION_SOURCE_TOOLS = {"searchProjectEvidence", "searchProjectKnowledge"}


class AgentToolRegistry:
    """Registry of allowlisted tools. Executes against store interfaces."""

    def __init__(
        self,
        evidence_store: EvidenceStore,
        report_store: ReportStore,
        scoring_engine: HealthScoringEngine,
    ):
        self.evidence = evidence_store
        self.report = report_store
        self.scoring = scoring_engine

    # -- definitions ------------------------------------------------------

    def definitions(self) -> list[dict]:
        """Return OpenAI function-calling tool schemas."""
        return _TOOL_DEFINITIONS

    def supports(self, tool_name: str) -> bool:
        return tool_name in _TOOL_NAMES

    # -- execution --------------------------------------------------------

    async def execute(
        self,
        ctx,  # AgentTaskContext
        tool_name: str,
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        """Execute a tool and return its output dict."""
        if not self.supports(tool_name):
            raise ValueError(f"Tool is not allowlisted: {tool_name}")

        if tool_name == "getProjectProfile":
            return {"project": ctx.project}

        if tool_name == "searchProjectEvidence":
            return {"items": await self.evidence.search_evidence(ctx.project_id, arguments)}

        if tool_name == "searchProjectKnowledge":
            return {"items": await self.evidence.search_knowledge(ctx.project_id, ctx.question, arguments)}

        if tool_name == "getProjectMemory":
            return {"items": await self.evidence.project_memory(ctx.project_id, arguments)}

        if tool_name == "getRecentRuns":
            return {"items": await self.evidence.recent_runs(ctx.project_id, ctx.run_id, arguments)}

        if tool_name == "getLatestReport":
            return {"report": await self.report.latest_report(ctx.project_id, arguments)}

        if tool_name == "calculateHealthScore":
            evidence = await self.evidence.canonical_evidence(ctx.project_id)
            return {
                "scoring": self.scoring.score(ctx.project, evidence),
                "canonicalEvidenceCount": len(evidence),
            }

        raise ValueError(f"Tool is not allowlisted: {tool_name}")

    # -- citation / scoring extraction ------------------------------------

    @staticmethod
    def citations_from(observations: list[dict]) -> list[dict]:
        """Extract unique citations from search-tool observations."""
        seen: dict[str, dict] = {}
        for obs in observations:
            tool_name = str(obs.get("toolName", ""))
            if tool_name not in _CITATION_SOURCE_TOOLS:
                continue
            output = obs.get("output")
            if not isinstance(output, dict):
                continue
            items = output.get("items")
            if not isinstance(items, list):
                continue
            for item in items:
                if not isinstance(item, dict):
                    continue
                source_id = item.get("sourceId")
                if source_id is None:
                    continue
                key = f"{item.get('sourceType', '')}:{source_id}"
                if key not in seen:
                    seen[key] = dict(item)
        return list(seen.values())

    @staticmethod
    def scoring_from(observations: list[dict]) -> dict[str, Any]:
        """Extract the latest scoring result from observations (reverse scan)."""
        for obs in reversed(observations):
            output = obs.get("output")
            if isinstance(output, dict) and "scoring" in output:
                scoring = output["scoring"]
                if isinstance(scoring, dict):
                    return dict(scoring)
        return {}
