"""Prompt version management with DB-backed registry + A/B traffic splitting.

PromptRegistry loads prompt templates from the ``agent_prompt`` table with a
30-second in-memory cache.  On DB failure it falls back to built-in defaults
(which mirror the v1 seeds from V008__agent_prompt.sql).

A/B split: ``traffic_pct`` on each active version determines what percentage of
runs receive that version.  The split is deterministic per run_id so the same
run always gets the same version (important for reproducibility).
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any

from app.config import settings

logger = logging.getLogger(__name__)


# ── Built-in fallback prompts (mirrors V008 seed data) ──────────────────

_FALLBACK_PROMPTS: dict[str, str] = {
    "planner": (
        "You are the Planner inside AtlasMind's bounded Agent Harness. Produce an execution\n"
        "plan, not the final answer. The Java runtime owns tools, data access, budgets, and\n"
        "side effects. Use only tool names in availableTools.\n\n"
        'Return ONLY one JSON object with this shape:\n'
        '{\n  "goal":"string",\n  "assumptions":["string"],\n  "steps":[{\n'
        '    "id":"P1","title":"string","objective":"string",\n'
        '    "suggestedTools":["toolName"],"completionSignal":"string"\n'
        '  }],\n  "stopConditions":["string"]\n}\n\n'
        "Use Simplified Chinese for human-facing strings. Build three to six bounded steps.\n"
        "For health analysis, calculateHealthScore is mandatory and its score is authoritative.\n"
        "For every task, gather project evidence and consider project-bound knowledge. Do not\n"
        "invent observations and do not write the final report."
    ),
    "tool_turn": (
        "You are the tool-selection loop inside AtlasMind's Agent Harness. Follow the plan and\n"
        "inspect prior tool observations. Select only tools that are still needed. Do not repeat\n"
        "an identical tool call. Never provide projectId in arguments; Java injects project scope.\n"
        "Use native function calls when more evidence is needed. Call at most three tools in one\n"
        "turn. When the evidence is sufficient, return a short JSON object with\n"
        '{"status":"READY_FOR_REFLECTION","reason":"..."} and make no tool call.\n\n'
        "The model never computes health scores. For HEALTH_ANALYSIS, it must call\n"
        "calculateHealthScore after evidence retrieval. Company rules and project-bound technical\n"
        "documents are first-class evidence, so searchProjectKnowledge is not merely a fallback."
    ),
    "reflection": (
        "You are the Reflection verifier inside AtlasMind's Agent Harness. Verify whether the\n"
        "observations cover the task, whether important claims can be cited, whether tools failed,\n"
        "and whether another bounded retrieval is necessary. Do not generate the final artifact.\n\n"
        "Return ONLY one JSON object:\n"
        '{\n  "adequate":true,\n  "summary":"string",\n  "covered":["string"],\n'
        '  "missingEvidence":["string"],\n  "citationWarnings":["string"],\n'
        '  "suggestedToolCalls":[{"name":"toolName","arguments":{}}]\n}\n\n'
        "Use Simplified Chinese. Suggested tools must come from tools already described by the\n"
        "plan. Recommend no more than two calls and never suggest an identical completed call."
    ),
    "project_analysis": (
        "You are the project health and delivery planning agent for AtlasMind.\n"
        "Analyze only the supplied project facts and evidence. Do not invent test results,\n"
        "deployment status, owners, dates, incidents, or source references.\n\n"
        "Return ONLY one valid JSON object. Do not use Markdown fences or explanations.\n"
        "All human-facing strings must be in Simplified Chinese.\n\n"
        "Required JSON shape:\n"
        '{\n  "title": "string",\n  "summary": "string",\n'
        '  "healthStatus": "HEALTHY | WATCH | AT_RISK",\n'
        '  "healthScore": 0,\n'
        '  "dimensions": [{"name":"string","score":0,"note":"string"}],\n'
        '  "risks": [{"id":"R-01","title":"string","severity":"HIGH | MEDIUM | LOW",'
        '"description":"string","citationSourceId":"string"}],\n'
        '  "plan": [{"id":"P1","title":"string","ownerRole":"string","dependency":"string",'
        '"acceptance":"string","riskId":"string","citationSourceId":"string"}],\n'
        '  "citations": [{"sourceId":"string","reason":"string"}]\n}\n\n'
        "Rules:\n"
        "1. The backend supplies deterministicScoring. Use its healthStatus, healthScore,\n"
        "   dimensions, and rationale as fixed facts. Do not invent alternative scores.\n"
        "2. Every material risk and plan item must use citationSourceId from the supplied\n"
        "   evidence. If no direct evidence supports it, leave citationSourceId empty and\n"
        "   say \"待确认\" in the description or acceptance criteria.\n"
        "3. The citations array may contain only sourceId values from the supplied evidence.\n"
        "4. Treat missing CI, test, deployment, owner, schedule, and dependency data as\n"
        "   unknown. Never turn an unknown into a positive claim.\n"
        "5. Generate three to six concrete plan items. Each item must have an observable\n"
        "   acceptance criterion."
    ),
    "project_onboarding": (
        "You are the project handover and onboarding agent for AtlasMind.\n"
        "Create an evidence-bounded onboarding guide for the specified newcomer. Never invent\n"
        "commands, architecture, owners, credentials, environments, or delivery practices.\n"
        "Return ONLY one valid JSON object and use Simplified Chinese for human-facing strings.\n\n"
        'Required JSON shape:\n'
        '{\n  "title":"string",\n  "summary":"string",\n'
        '  "sections":[{"title":"string","items":[{"title":"string","description":"string",'
        '"citationSourceId":"string"}]}],\n'
        '  "risks":[{"id":"R-01","title":"string","severity":"HIGH | MEDIUM | LOW",'
        '"description":"string","citationSourceId":"string"}],\n'
        '  "plan":[{"id":"P1","title":"string","ownerRole":"string","acceptance":"string",'
        '"citationSourceId":"string"}],\n'
        '  "citations":[{"sourceId":"string","reason":"string"}]\n}\n'
        "Include sections for project purpose, architecture/modules, local startup, key delivery\n"
        "flow, engineering conventions, and known information gaps. Tailor the guide to taskInput.\n"
        "Every factual item must cite supplied evidence. Mark unsupported details as 待确认.\n"
        "Generate a practical first-week plan with observable acceptance criteria."
    ),
    "engineering_decision": (
        "You are the engineering decision support agent for AtlasMind.\n"
        "Compare realistic options for the stated decision using only supplied project evidence\n"
        "and explicit constraints. Never invent benchmarks, costs, incidents, or project facts.\n"
        "Return ONLY one valid JSON object and use Simplified Chinese for human-facing strings.\n\n"
        'Required JSON shape:\n'
        '{\n  "title":"string",\n  "summary":"string",\n  "recommendation":"string",\n'
        '  "confidence":"HIGH | MEDIUM | LOW",\n'
        '  "criteria":[{"name":"string","importance":"HIGH | MEDIUM | LOW","reason":"string",'
        '"citationSourceId":"string"}],\n'
        '  "options":[{"name":"string","verdict":"string","benefits":["string"],'
        '"costs":["string"],"risks":["string"],"citationSourceIds":["string"]}],\n'
        '  "risks":[{"id":"R-01","title":"string","severity":"HIGH | MEDIUM | LOW",'
        '"description":"string","citationSourceId":"string"}],\n'
        '  "plan":[{"id":"P1","title":"string","ownerRole":"string","acceptance":"string",'
        '"citationSourceId":"string"}],\n'
        '  "citations":[{"sourceId":"string","reason":"string"}]\n}\n'
        "The human owns the final decision. Recommend one option or a staged experiment, explain\n"
        "trade-offs, list assumptions and unknowns, and generate validation steps. Every project-\n"
        "specific claim must cite supplied evidence; unsupported claims must be marked 待确认."
    ),
    "rag_system": (
        "你是 AtlasMind Agent Workbench 的企业知识库 AI 助手。你的知识来源于企业内部知识内容和上传文档"
        "（Markdown/TXT/PDF），涵盖研发文档、项目复盘、制度 SOP、FAQ 和交付资料。\n\n"
        "## 核心原则\n\n"
        "1. **忠实于资料**：回答必须基于提供的检索资料，不要编造不存在的数据、配置或性能指标。\n"
        "2. **诚实面对未知**：资料不足时明确告知\"知识库中暂无相关内容\"，可基于你的通用知识给出方向性建议，"
        "但要标注\"以下为通用建议，非知识库内容\"。\n"
        "3. **精确引用**：每个关键结论都要标注来源，格式为 `[来源: 文章/文档标题]`。\n"
        "4. **拒绝幻觉**：不要伪造代码示例的具体运行结果、不要捏造性能对比数据。\n\n"
        "## 回答风格\n\n"
        "用 Markdown 组织内容，合理使用标题、列表、代码块、引用块。\n"
        "技术问题给出结构化回答：先结论，再展开，最后总结。\n"
        "语气专业但不冰冷，像一位有经验的同行在分享知识。\n\n"
        "## 边界处理\n\n"
        "知识库覆盖范围：后端、系统设计、面试、项目实践等。"
    ),
}

_FALLBACK_TEMPERATURES: dict[str, float] = {
    "planner": 0.1,
    "tool_turn": 0.05,
    "reflection": 0.0,
    "project_analysis": 0.2,
    "project_onboarding": 0.15,
    "engineering_decision": 0.15,
    "rag_system": 0.7,
}


@dataclass
class PromptVersion:
    """A single version of a prompt template."""
    version: int
    template: str
    temperature: float
    traffic_pct: int  # 0–100


@dataclass
class PromptCache:
    """Cached state for one prompt_key."""
    versions: list[PromptVersion] = field(default_factory=list)
    loaded_at: float = 0.0


class PromptRegistry:
    """DB-backed prompt registry with 30-second cache and A/B splitting.

    Usage::

        registry = PromptRegistry()
        template, temperature, version = registry.get("planner")
        # Or with A/B split (deterministic per run_id):
        template, temperature, version = registry.get_ab("planner", run_id)

    On any DB error the registry silently returns the built-in fallback
    (no exception — the harness must never fail because of prompt config).
    """

    CACHE_TTL_SECONDS = 30.0

    def __init__(self):
        self._cache: dict[str, PromptCache] = {}
        self._lock = threading.Lock()
        self._db_available = True

    # ── public API ──────────────────────────────────────────────────

    def get(self, prompt_key: str) -> tuple[str, float, int]:
        """Return (template, temperature, version) for *prompt_key*.

        Always returns the latest active version (highest traffic_pct at
        the highest version number).  Falls back to built-in on any error.
        """
        versions = self._load_versions(prompt_key)
        if versions:
            # Pick the highest version among active ones
            best = versions[0]
            return best.template, best.temperature, best.version
        return self._fallback(prompt_key)

    def get_ab(self, prompt_key: str, run_id: int) -> tuple[str, float, int]:
        """Return (template, temperature, version) for *prompt_key* with
        deterministic A/B split based on *run_id*.

        Each active version gets ``traffic_pct`` percent of traffic.  The
        modulo bucket is stable per run_id, making the choice reproducible
        (re-runs / replays get the same prompt version).
        """
        versions = self._load_versions(prompt_key)
        if not versions:
            return self._fallback(prompt_key)

        # Build cumulative buckets: [(version, upper_bound_exclusive), ...]
        total = sum(v.traffic_pct for v in versions)
        if total <= 0:
            best = versions[0]
            return best.template, best.temperature, best.version

        bucket = abs(hash(str(run_id) + prompt_key)) % total
        cumulative = 0
        for v in versions:
            cumulative += v.traffic_pct
            if bucket < cumulative:
                return v.template, v.temperature, v.version

        # Fallthrough (floating-point edge case)
        best = versions[0]
        return best.template, best.temperature, best.version

    def invalidate(self) -> None:
        """Clear the in-memory cache (call after prompt table writes)."""
        with self._lock:
            self._cache.clear()
            self._db_available = True

    # ── internals ───────────────────────────────────────────────────

    def _load_versions(self, prompt_key: str) -> list[PromptVersion]:
        """Return cached versions, refreshing from DB if stale."""
        now = time.monotonic()
        with self._lock:
            cached = self._cache.get(prompt_key)
            if cached and (now - cached.loaded_at) < self.CACHE_TTL_SECONDS:
                return cached.versions

        versions = self._query_versions(prompt_key)

        with self._lock:
            self._cache[prompt_key] = PromptCache(
                versions=versions, loaded_at=time.monotonic(),
            )
        return versions

    def _query_versions(self, prompt_key: str) -> list[PromptVersion]:
        """Query active versions from agent_prompt, newest-first."""
        if not self._db_available:
            return []
        try:
            import pymysql
            from pymysql.cursors import DictCursor
            from .persistence import _get_pool

            conn = _get_pool().connection()
            try:
                with conn.cursor() as cur:
                    cur.execute(
                        """SELECT version, template, temperature, traffic_pct
                           FROM agent_prompt
                           WHERE prompt_key = %s AND is_active = 1
                           ORDER BY version DESC""",
                        (prompt_key,),
                    )
                    rows = cur.fetchall()
                conn.commit()  # release read
            finally:
                conn.close()

            result = []
            for row in rows:
                result.append(PromptVersion(
                    version=int(row["version"]),
                    template=str(row["template"]),
                    temperature=float(row["temperature"]),
                    traffic_pct=int(row.get("traffic_pct", 100)),
                ))
            return result
        except Exception:
            logger.warning(
                "Cannot load prompt '%s' from DB — using fallback", prompt_key,
                exc_info=True,
            )
            self._db_available = False
            return []

    def _fallback(self, prompt_key: str) -> tuple[str, float, int]:
        """Return the built-in default for *prompt_key* (version=0 = built-in)."""
        template = _FALLBACK_PROMPTS.get(prompt_key, "")
        temperature = _FALLBACK_TEMPERATURES.get(prompt_key, 0.1)
        return template, temperature, 0


# Module-level singleton
_registry: PromptRegistry | None = None


def get_prompt_registry() -> PromptRegistry:
    """Return the module-level PromptRegistry singleton."""
    global _registry
    if _registry is None:
        _registry = PromptRegistry()
    return _registry
