"""Report artifact nodes — compose, validate schema, persist."""

from __future__ import annotations

import logging
from typing import Any

from ...harness.budget import (
    audit_work_unit_budgets,
    coverage_limited_diagnostics,
    merge_limited_diagnostics,
)
from ..versioning import stamp_artifact_versions

logger = logging.getLogger(__name__)


def _risk_groups(findings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[str, dict[str, Any]] = {}
    for finding in findings:
        key = str(finding.get("domainKey") or finding.get("clauseType") or "other")
        group = groups.setdefault(key, {
            "domainKey": key,
            "domainName": finding.get("domainName") or "其他风险",
            "findingCount": 0,
            "highCount": 0,
            "mediumCount": 0,
            "lowCount": 0,
        })
        group["findingCount"] += 1
        severity_key = f"{str(finding.get('severity') or 'LOW').lower()}Count"
        if severity_key in group:
            group[severity_key] += 1
    return sorted(
        groups.values(),
        key=lambda item: (-item["highCount"], -item["mediumCount"], item["domainName"]),
    )


def _risk_summary(findings: list[dict[str, Any]], coverage: dict[str, Any]) -> dict[str, Any]:
    counts = {"HIGH": 0, "MEDIUM": 0, "LOW": 0}
    for finding in findings:
        severity = str(finding.get("severity") or "LOW").upper()
        if severity in counts:
            counts[severity] += 1
    return {
        "total": len(findings),
        "high": counts["HIGH"],
        "medium": counts["MEDIUM"],
        "low": counts["LOW"],
        "reviewedDomainCount": len(coverage.get("domains") or {}),
        "primaryMessage": (
            f"优先处理 {counts['HIGH']} 项高风险问题"
            if counts["HIGH"] else
            f"重点复核 {counts['MEDIUM']} 项中风险问题"
            if counts["MEDIUM"] else "未发现需要立即处理的重大风险"
        ),
    }


def compose_report(state: dict[str, Any]) -> dict[str, Any]:
    """Compose the final contract review report from validated findings."""
    validated = state.get("validated_findings") or []
    case_snapshot = state.get("case_snapshot") or {}
    coverage = state.get("coverage") or {}
    scoring = state.get("scoring") or {}
    analysis_workflow = state.get("analysis_workflow") or {}
    risk_summary = _risk_summary(validated, coverage)
    risk_groups = _risk_groups(validated)
    inferred_status = (
        "HIGH_RISK" if risk_summary["high"] else
        "MEDIUM_RISK" if risk_summary["medium"] else "LOW_RISK"
    )

    # Build deterministic artifact (LLM enrichment can come later)
    artifact = {
        "reportType": "CONTRACT_REVIEW_REPORT",
        "title": f"合同审查报告 — {case_snapshot.get('title') or case_snapshot.get('caseKey', '')}",
        "summary": (
            f"完成 {risk_summary['reviewedDomainCount']} 个风险领域审查，"
            f"识别 {len(validated)} 项需关注事项，其中高风险 {risk_summary['high']} 项、"
            f"中风险 {risk_summary['medium']} 项。"
        ),
        "riskStatus": scoring.get("riskStatus") or inferred_status,
        "riskScore": scoring.get("riskScore") or 0,
        "analysisMode": "FULL",
        "findings": validated,
        "risks": validated,
        "riskSummary": risk_summary,
        "riskGroups": risk_groups,
        "analysisWorkflow": analysis_workflow,
        "documentQuality": state.get("document_quality") or {},
        "evidenceValidation": state.get("evidence_validation") or {},
        "retrievalValidation": state.get("retrieval_validation") or {},
        "evidenceHash": analysis_workflow.get("evidenceSnapshotHash"),
        "actionProposals": [
            {
                "type": "REQUEST_LEGAL_REVIEW",
                "title": "法务复核审查发现",
                "description": f"共 {len(validated)} 条审查发现需要法务逐项复核确认",
                "priority": "HIGH",
            }
        ],
        "citations": state.get("citations") or [],
        "content": {
            "case": case_snapshot,
            "coverage": coverage,
            "scoring": scoring,
            "riskSummary": risk_summary,
            "riskGroups": risk_groups,
            "findings": validated,
            "analysisWorkflow": analysis_workflow,
            "documentQuality": state.get("document_quality") or {},
            "evidenceValidation": state.get("evidence_validation") or {},
            "retrievalValidation": state.get("retrieval_validation") or {},
        },
    }

    stamp_artifact_versions(state, artifact)

    return {
        "state_revision": state.get("state_revision", 0) + 1,
        "current_node": "compose_report",
        "artifact": artifact,
    }


def _coverage_missing_details(
    state: dict[str, Any],
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """§6.4 disclosure for the uncovered domains: which check items
    (domain names) are missing, and which evidence source types the run
    could source elsewhere but did not get for those domains."""
    coverage = state.get("coverage") or {}
    missing_domains = coverage.get("missingDomains") or []
    domains = coverage.get("domains") or {}
    expected_types = {
        str(source_type)
        for info in domains.values()
        for source_type in (info.get("sourceCounts") or {})
    }
    missing_names: list[str] = []
    missing_sources: set[str] = set()
    for key in missing_domains:
        info = domains.get(key) or {}
        missing_names.append(str(info.get("domainName") or key))
        missing_sources.update(expected_types - set(info.get("sourceCounts") or {}))
    schema_errors = (state.get("schema_validation") or {}).get("errors") or []
    if schema_errors:
        # The repair path also lands here with a failed schema — surface
        # the concrete validation errors as missing check items.
        missing_names.extend(
            f"报告结构校验未通过: {str(error)[:120]}" for error in schema_errors[:3]
        )
    return tuple(missing_names), tuple(sorted(missing_sources))


def compose_limited_report(state: dict[str, Any]) -> dict[str, Any]:
    """Compose a scope-limited report when coverage is incomplete (or the
    §7.2 budget audit flagged the run mid-compose)."""
    validated = state.get("validated_findings") or []
    case_snapshot = state.get("case_snapshot") or {}
    analysis_workflow = state.get("analysis_workflow") or {}
    # A prior limited_diagnostics carrying BUDGET reasons means the schema
    # gate re-routed us here for budget, not coverage — the limitation text
    # and diagnostics must say so instead of blaming the quality gate.
    prior = state.get("limited_diagnostics")
    budget_limited = bool(prior and "BUDGET" in (prior.get("reasons") or []))

    artifact = {
        "reportType": "CONTRACT_REVIEW_REPORT",
        "title": f"[范围受限] 合同审查报告 — {case_snapshot.get('title', '')}",
        "summary": (
            "本次审查因工作单元预算超限未能完成全部风险维度。"
            if budget_limited else
            "本次审查因证据不足未能覆盖全部风险维度。"
        )
        + f"已验证发现 {len(validated)} 条。"
        + ("建议补充预算或精简审查范围后重新发起审查。"
           if budget_limited else "建议补充缺失材料后重新发起完整审查。"),
        "riskStatus": "HIGH_RISK",
        "riskScore": 0,
        "analysisMode": "LIMITED",
        "coverageLimitation": (
            "工作单元预算超限：部分风险维度的查询或分析超出单工作单元预算"
            if budget_limited else
            "质量门禁未通过：部分风险维度缺少充分证据"
        ),
        "findings": validated,
        "risks": validated,
        "riskSummary": _risk_summary(validated, state.get("coverage") or {}),
        "riskGroups": _risk_groups(validated),
        "analysisWorkflow": analysis_workflow,
        "documentQuality": state.get("document_quality") or {},
        "evidenceValidation": state.get("evidence_validation") or {},
        "retrievalValidation": state.get("retrieval_validation") or {},
        "evidenceHash": analysis_workflow.get("evidenceSnapshotHash"),
        "actionProposals": [
            {
                "type": "REQUEST_MATERIAL",
                "title": "补充审查材料",
                "description": "建议补充合同全文、适用政策文档后重新审查",
                "priority": "HIGH",
            }
        ],
        "citations": state.get("citations") or [],
        "content": {
            "case": case_snapshot,
            "limitedReport": True,
            "qualityGatePassed": False,
            "analysisWorkflow": analysis_workflow,
            "documentQuality": state.get("document_quality") or {},
            "evidenceValidation": state.get("evidence_validation") or {},
            "retrievalValidation": state.get("retrieval_validation") or {},
        },
    }

    stamp_artifact_versions(state, artifact)

    # §7.2/§6.4: the limited report carries the mandatory diagnostics —
    # the runtime turns the run into LIMITED, and the route layer persists
    # them with the run row. Written here (not just in validate_schema) so
    # every limited-report path discloses what the gate cut. A budget
    # re-route keeps the existing budget diagnostics untouched.
    if budget_limited:
        return {
            "state_revision": state.get("state_revision", 0) + 1,
            "current_node": "compose_limited_report",
            "artifact": artifact,
        }
    missing_names, missing_sources = _coverage_missing_details(state)
    return {
        "state_revision": state.get("state_revision", 0) + 1,
        "current_node": "compose_limited_report",
        "artifact": artifact,
        "limited_diagnostics": coverage_limited_diagnostics(
            work_unit_id=f"run-{state.get('run_id', 0)}",
            missing_check_items=missing_names,
            missing_source_types=missing_sources,
            retried=bool((state.get("retry_state") or {}).get("reflection_rounds", 0) > 0),
        ),
    }


def validate_schema(state: dict[str, Any]) -> dict[str, Any]:
    """Pydantic validation — HARD gate. Writes result to state for conditional routing.

    §7.2 budget audit runs on every pass (both compose paths flow through
    here): each domain's accumulated ledger is checked against its
    WorkUnitBudget; an over-budget unit merges its §6.4 diagnostics into
    ``limited_diagnostics``, which the runtime turns into LIMITED.
    """
    artifact = state.get("artifact") or {}
    repair_count = state.get("retry_state", {}).get("schema_repair_count", 0)

    try:
        from ...schemas.validators import validate_report
        result = validate_report(artifact)
        valid = result.valid
        errors = result.schema_errors
        warnings = result.business_warnings
    except Exception as exc:
        valid = False
        errors = [str(exc)]
        warnings = []

    # ── §7.2 budget audit ──────────────────────────────────────────────
    usage = state.get("work_unit_usage") or {}
    domain_tasks = state.get("domain_tasks") or []
    coverage_domains = (state.get("coverage") or {}).get("domains") or {}
    expected_types = {
        str(source_type)
        for info in coverage_domains.values()
        for source_type in (info.get("sourceCounts") or {})
    }
    check_items: dict[str, tuple[str, ...]] = {}
    missing_sources: dict[str, tuple[str, ...]] = {}
    for task in domain_tasks:
        key = str(task.get("domainKey") or task.get("domain") or "")
        check_items[key] = tuple(str(value) for value in task.get("requiredClauseTypes") or [])
        present = set((coverage_domains.get(key) or {}).get("sourceCounts") or {})
        missing_sources[key] = tuple(sorted(expected_types - present))
    over_units = audit_work_unit_budgets(
        usage, missing_check_items=check_items, missing_source_types=missing_sources,
    )
    limited_diagnostics = merge_limited_diagnostics(
        state.get("limited_diagnostics"), over_units,
    )

    return {
        "state_revision": state.get("state_revision", 0) + 1,
        "current_node": "validate_schema",
        "schema_validation": {
            "valid": valid,
            "errors": errors,
            "warnings": warnings,
            "repair_count": repair_count,
        },
        "limited_diagnostics": limited_diagnostics,
    }


def repair_artifact(state: dict[str, Any]) -> dict[str, Any]:
    """One-shot LLM repair of schema validation errors."""
    artifact = state.get("artifact") or {}
    validation = state.get("schema_validation") or {}
    errors = validation.get("errors", [])

    # Try basic field fixes without LLM
    if artifact:
        # Ensure required fields exist
        artifact.setdefault("reportType", "CONTRACT_REVIEW_REPORT")
        artifact.setdefault("analysisMode", artifact.get("analysisMode") or "LIMITED")
        if not artifact.get("title"):
            artifact["title"] = "[范围受限] 合同审查报告"

        # Fix missing findings
        if not artifact.get("findings"):
            artifact["findings"] = []

        # Fix aiRisk disclaimer
        ai_risk = str(artifact.get("aiRisk", ""))
        if ai_risk and "仅供参考" not in ai_risk:
            artifact["aiRisk"] = f"AI 推断，仅供参考：{ai_risk}"

    retry_state = state.get("retry_state") or {}
    retry_state["schema_repair_count"] = validation.get("repair_count", 0) + 1

    return {
        "state_revision": state.get("state_revision", 0) + 1,
        "current_node": "repair_artifact",
        "artifact": artifact,
        "retry_state": retry_state,
        "errors": state.get("errors", []) + [{
            "node": "repair_artifact",
            "error": f"Repaired {len(errors)} schema errors: {'; '.join(errors[:3])}",
        }],
    }


def _route_after_schema(state: dict[str, Any]) -> str:
    """Route based on schema validation result and the §7.2 budget audit."""
    sv = state.get("schema_validation") or {}
    if not sv.get("valid"):
        repair_count = sv.get("repair_count", 0)
        return "repair_artifact" if repair_count < 1 else "compose_limited_report"
    artifact = state.get("artifact") or {}
    if artifact.get("analysisMode") == "LIMITED":
        # Already the limited report (coverage / repair path) — its next
        # schema pass must not recompose, or the loop never exits.
        return "prepare_human_review"
    if state.get("limited_diagnostics"):
        # The budget audit flagged the run mid-compose: recompose as the
        # limited report, whose own pass then routes on analysisMode.
        return "compose_limited_report"
    return "prepare_human_review"


def prepare_human_review(state: dict[str, Any]) -> dict[str, Any]:
    """Attach an explicit legal-review handoff before persisting the report.

    Contract review can finish asynchronously, but the Agent never treats a
    generated risk conclusion as a final legal decision. Fulfillment uses a
    real LangGraph interrupt; contract review records this review boundary in
    the persisted artifact and action queue.
    """
    artifact = state.get("artifact") or {}
    quality = state.get("document_quality") or {}
    validation = state.get("evidence_validation") or {}
    reasons = ["合同风险结论需要负责人或法务人工复核"]
    if quality.get("requiresHumanReview"):
        reasons.append("文档解析质量需要核对原页")
    if validation.get("unsupportedCitationCount"):
        reasons.append("存在无法由原文连续片段支持的引用")
    if (state.get("coverage") or {}).get("status") != "CONFIRMED":
        reasons.append("部分风险领域证据覆盖不足")

    content = artifact.get("content") if isinstance(artifact.get("content"), dict) else {}
    human_review = {
        "required": True,
        "status": "PENDING",
        "reasons": list(dict.fromkeys(reasons)),
        "finalDecisionOwner": "HUMAN_REVIEWER",
    }
    content["humanReview"] = human_review
    content["documentQuality"] = quality
    content["evidenceValidation"] = validation
    artifact["content"] = content
    artifact["humanReviewRequired"] = True

    return {
        "state_revision": state.get("state_revision", 0) + 1,
        "current_node": "prepare_human_review",
        "artifact": artifact,
        "human_review": human_review,
    }


def persist_report(state: dict[str, Any]) -> dict[str, Any]:
    """Persist report via MySqlReportStore."""
    artifact = state.get("artifact") or {}
    run_id = state.get("run_id", 0)
    subject_id = state.get("subject_id", 0)

    if state.get("shadow_mode"):
        # PRD §26.2: a shadow run must not overwrite the official report. Its
        # artifact is only consumed for the SHADOW_DIFF comparison.
        logger.info("Shadow run %s: report not persisted (shadow_mode)", run_id)
        return {
            "state_revision": state.get("state_revision", 0) + 1,
            "current_node": "persist_report",
            "observations": state.get("observations", []) + [{
                "callId": f"shadow-skip-persist-{run_id}",
                "planStepId": "persist_report",
                "toolName": "persistReport",
                "arguments": {"shadowMode": True},
                "output": {"skipped": True},
                "status": "DONE",
            }],
        }

    try:
        from ...persistence import MySqlReportStore

        report_id = MySqlReportStore._save_sync(
            subject_id, run_id, "CONTRACT_REVIEW", artifact,
        )
        logger.info("Report %s persisted for run %s", report_id, run_id)
    except Exception as exc:
        logger.error("Report persist failed: %s", exc)
        return {
            "state_revision": state.get("state_revision", 0) + 1,
            "current_node": "persist_report",
            "errors": state.get("errors", []) + [{"node": "persist_report", "error": str(exc)}],
        }

    return {
        "state_revision": state.get("state_revision", 0) + 1,
        "current_node": "persist_report",
    }
