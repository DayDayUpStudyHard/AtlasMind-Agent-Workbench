"""Report artifact nodes — compose, validate schema, persist."""

from __future__ import annotations

import logging
from typing import Any

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

    return {
        "state_revision": state.get("state_revision", 0) + 1,
        "current_node": "compose_report",
        "artifact": artifact,
    }


def compose_limited_report(state: dict[str, Any]) -> dict[str, Any]:
    """Compose a scope-limited report when coverage is incomplete."""
    validated = state.get("validated_findings") or []
    case_snapshot = state.get("case_snapshot") or {}
    analysis_workflow = state.get("analysis_workflow") or {}

    artifact = {
        "reportType": "CONTRACT_REVIEW_REPORT",
        "title": f"[范围受限] 合同审查报告 — {case_snapshot.get('title', '')}",
        "summary": (
            "本次审查因证据不足未能覆盖全部风险维度。"
            f"已验证发现 {len(validated)} 条。"
            "建议补充缺失材料后重新发起完整审查。"
        ),
        "riskStatus": "HIGH_RISK",
        "riskScore": 0,
        "analysisMode": "LIMITED",
        "coverageLimitation": "质量门禁未通过：部分风险维度缺少充分证据",
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

    return {
        "state_revision": state.get("state_revision", 0) + 1,
        "current_node": "compose_limited_report",
        "artifact": artifact,
    }


def validate_schema(state: dict[str, Any]) -> dict[str, Any]:
    """Pydantic validation — HARD gate. Writes result to state for conditional routing."""
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

    return {
        "state_revision": state.get("state_revision", 0) + 1,
        "current_node": "validate_schema",
        "schema_validation": {
            "valid": valid,
            "errors": errors,
            "warnings": warnings,
            "repair_count": repair_count,
        },
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
    """Route based on schema validation result."""
    sv = state.get("schema_validation") or {}
    if sv.get("valid"):
        return "prepare_human_review"
    repair_count = sv.get("repair_count", 0)
    if repair_count < 1:
        return "repair_artifact"
    return "compose_limited_report"


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
