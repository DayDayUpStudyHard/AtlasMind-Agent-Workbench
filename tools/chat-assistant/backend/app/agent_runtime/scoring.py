"""Deterministic health scoring engine — Python port of Java DeterministicHealthScoringEngine.

Five dimensions with fixed keyword-detection signals, weighted average, SHA-256
evidence hashing for snapshot dedup. The scoring_version is bumped to "v3-python"
to distinguish from the Java "v2-harness" output.
"""

from __future__ import annotations

import hashlib
import logging
from typing import Any

logger = logging.getLogger(__name__)

SCORING_VERSION = "v3-python"
ANALYSIS_MODE = "deterministic-score + agent-harness-explanation"


class HealthScoringEngine:
    """Rule-based five-dimension project health scorer."""

    # Keywords matched against the lower-cased concatenation of project metadata
    # and all evidence snippets.
    _DEPENDENCY_KEYWORDS = (
        "pom.xml", "package.json", "pyproject.toml", "build.gradle",
        "requirements.txt", "pnpm-lock", "yarn.lock", "package-lock",
    )
    _TEST_KEYWORDS = (
        "test", "tests", "pytest", "junit", "vitest", "jest",
        "coverage", "单元测试", "测试",
    )
    _CI_KEYWORDS = (
        ".github/workflows", "github actions", "ci.yml", "ci.yaml",
        "jenkins", "gitlab-ci", "pipeline", "流水线", "持续集成",
    )

    def score(
        self, project: dict[str, Any], citations: list[dict[str, Any]]
    ) -> dict[str, Any]:
        """Return {healthScore, healthStatus, dimensions, rationale, evidenceHash, ...}."""
        counts = self._count_by_type(citations)
        evidence_text = self._normalized_evidence_text(project, citations)

        has_github = any(
            str(c.get("sourceType", "")).upper() == "GITHUB" for c in citations
        )
        has_readme = counts.get("README", 0) > 0
        has_file_tree = counts.get("FILE_TREE", 0) > 0
        has_file = counts.get("FILE", 0) > 0
        has_source_code = counts.get("SOURCE", 0) > 0 or counts.get("FILE", 0) > 1
        has_commit = counts.get("COMMIT", 0) > 0
        has_issue = counts.get("ISSUE", 0) > 0
        has_pr = counts.get("PR", 0) > 0
        has_deps = self._contains_any(evidence_text, *self._DEPENDENCY_KEYWORDS)
        has_tests = self._contains_any(evidence_text, *self._TEST_KEYWORDS)
        has_ci = self._contains_any(evidence_text, *self._CI_KEYWORDS)
        has_milestone = bool(str(project.get("currentMilestone", "")).strip())
        has_release = bool(str(project.get("releaseTarget", "")).strip())
        has_tech_stack = bool(str(project.get("techStack", "")).strip())
        has_team = int(project.get("teamSize") or 0) > 0

        rationale: list[dict] = []

        # ---- dimensions --------------------------------------------------
        delivery = 45
        delivery += self._signal(rationale, "交付进展", has_issue or has_pr, 25, "Issue/PR 数据")
        delivery += self._signal(rationale, "交付进展", has_milestone, 15, "当前里程碑")
        delivery += self._signal(rationale, "交付进展", has_release, 10, "目标版本")
        delivery += self._signal(rationale, "交付进展", has_commit, 5, "近期提交")

        quality = 35
        quality += self._signal(rationale, "工程质量", has_tests, 25, "测试证据")
        quality += self._signal(rationale, "工程质量", has_ci, 25, "CI/CD 证据")
        quality += self._signal(rationale, "工程质量", has_deps, 10, "依赖配置")
        quality += self._signal(rationale, "工程质量", has_pr, 5, "PR 评审")

        architecture = 45
        architecture += self._signal(rationale, "架构可维护性", has_readme, 12, "README")
        architecture += self._signal(rationale, "架构可维护性", has_file_tree, 10, "目录结构")
        architecture += self._signal(rationale, "架构可维护性", has_deps, 10, "构建配置")
        architecture += self._signal(rationale, "架构可维护性", has_source_code, 15, "源码可检索")
        architecture += self._signal(rationale, "架构可维护性", has_tech_stack, 8, "技术栈")

        risk = 45
        risk += self._signal(rationale, "风险暴露", has_github, 15, "真实仓库证据")
        risk += self._signal(rationale, "风险暴露", has_ci, 10, "构建信号")
        risk += self._signal(rationale, "风险暴露", has_tests, 10, "质量信号")
        risk += self._signal(rationale, "风险暴露", has_issue or has_pr, 10, "协作风险信号")
        risk += self._signal(rationale, "风险暴露", has_readme or has_file, 10, "代码/文档证据")

        collaboration = 40
        collaboration += self._signal(rationale, "协作活跃度", has_commit, 25, "提交活跃")
        collaboration += self._signal(rationale, "协作活跃度", has_pr, 20, "PR 协作")
        collaboration += self._signal(rationale, "协作活跃度", has_issue, 10, "Issue 协作")
        collaboration += self._signal(rationale, "协作活跃度", has_team, 5, "团队规模")

        dimensions = [
            self._dimension("交付进展", delivery, 25),
            self._dimension("工程质量", quality, 25),
            self._dimension("架构可维护性", architecture, 20),
            self._dimension("风险暴露", risk, 15),
            self._dimension("协作活跃度", collaboration, 15),
        ]

        health_score = self._clamp(round(
            delivery * 0.25 + quality * 0.25 + architecture * 0.20
            + risk * 0.15 + collaboration * 0.15
        ))
        health_status = (
            "HEALTHY" if health_score >= 80 else "WATCH" if health_score >= 65 else "AT_RISK"
        )
        evidence_hash = self.evidence_hash(project, citations)

        return {
            "healthScore": health_score,
            "healthStatus": health_status,
            "dimensions": dimensions,
            "rationale": rationale,
            "citations": citations,
            "scoringVersion": SCORING_VERSION,
            "evidenceHash": evidence_hash,
            "analysisMode": ANALYSIS_MODE,
            "snapshotReused": False,
        }

    # -- evidence hash ----------------------------------------------------

    def evidence_hash(
        self, project: dict[str, Any], citations: list[dict[str, Any]]
    ) -> str:
        """SHA-256 of project metadata + sorted citation identities."""
        buf = (
            f"project:{project.get('id', '')}\n"
            f"repo:{project.get('repositoryUrl', '')}\n"
            f"milestone:{project.get('currentMilestone', '')}\n"
            f"release:{project.get('releaseTarget', '')}\n"
        )
        lines = []
        for c in citations:
            lines.append(
                "|".join(
                    str(c.get(k, ""))
                    for k in ("sourceType", "objectType", "sourceId", "sourceRef", "title", "snippet")
                )
            )
        for line in sorted(lines):
            buf += line + "\n"
        return hashlib.sha256(buf.encode("utf-8")).hexdigest()

    # -- helpers ----------------------------------------------------------

    @staticmethod
    def _count_by_type(citations: list[dict]) -> dict[str, int]:
        counts: dict[str, int] = {}
        for c in citations:
            key = str(c.get("objectType", "")).upper()
            counts[key] = counts.get(key, 0) + 1
        return counts

    @staticmethod
    def _normalized_evidence_text(
        project: dict[str, Any], citations: list[dict[str, Any]]
    ) -> str:
        parts = [
            str(project.get(k, ""))
            for k in ("description", "businessScope", "currentMilestone", "releaseTarget", "techStack")
        ]
        for c in citations:
            parts.append(str(c.get("objectType", "")))
            parts.append(str(c.get("title", "")))
            parts.append(str(c.get("sourceRef", "")))
            parts.append(str(c.get("snippet", "")))
        return "\n".join(parts).lower()

    @staticmethod
    def _contains_any(haystack: str, *needles: str) -> bool:
        for needle in needles:
            if needle.lower() in haystack:
                return True
        return False

    @staticmethod
    def _signal(
        rationale: list[dict], dimension: str, present: bool, points: int, title: str
    ) -> int:
        rationale.append({
            "dimension": dimension,
            "title": title,
            "type": "POSITIVE" if present else "MISSING",
            "impact": points if present else -points,
            "note": (
                "已找到可验证证据" if present else "当前证据快照中未找到，按缺失项处理"
            ),
        })
        return points if present else 0

    @staticmethod
    def _dimension(name: str, score: int, weight: int) -> dict:
        normalized = max(0, min(100, score))
        return {
            "name": name,
            "score": normalized,
            "weight": weight,
            "note": f"由 {SCORING_VERSION} 固定信号规则计算，当前为 {normalized}/100",
        }

    @staticmethod
    def _clamp(value: int) -> int:
        return max(0, min(100, value))
