"""Focused tests for rich contract-risk graph normalization and report grouping."""

from app.agent_runtime.graph.nodes.artifact import _risk_groups, _risk_summary
from app.agent_runtime.graph.nodes.domain_tasks import _normalize_domain
from app.agent_runtime.graph.nodes.retrieval import _fallback_rule_findings, _normalize_finding
from app.agent_runtime.graph.nodes.validation import _validate_one
from app.agent_runtime.graph.contract_review import _route_after_reflection


def _task():
    return {
        "domainKey": "environmental_compliance",
        "domainName": "环境与许可合规",
        "requiredClauseTypes": ["OTHER"],
    }


def _evidence():
    return [
        {
            "sourceType": "CONTRACT_CLAUSE",
            "sourceId": "CONTRACT_CLAUSE:11",
            "title": "环保责任",
            "snippet": "乙方应遵守项目所在地环境保护要求。",
        },
        {
            "sourceType": "KB_CHUNK",
            "sourceId": "KB_CHUNK:22",
            "title": "供应商环保管理制度",
            "snippet": "高风险项目应明确环境许可和事故报告义务。",
        },
    ]


def test_dynamic_domain_is_bounded_and_normalized():
    domain = _normalize_domain({
        "domainKey": "Environmental Compliance!",
        "domainName": "环境与许可合规",
        "objective": "检查环保许可、污染处置和事故报告义务",
        "requiredClauseTypes": ["OTHER", "NOT_A_TYPE"],
        "queries": ["环境许可 污染处置"],
        "priority": "HIGH",
    }, 0)

    assert domain is not None
    assert domain["domainKey"] == "environmental_compliance"
    assert domain["requiredClauseTypes"] == ["OTHER"]
    assert domain["source"] == "LLM_DYNAMIC"


def test_finding_keeps_only_retrieved_citation_ids():
    finding = _normalize_finding({
        "title": "环保责任范围不完整",
        "severity": "HIGH",
        "contractCitationIds": ["CONTRACT_CLAUSE:11", "CONTRACT_CLAUSE:999"],
        "policyCitationIds": ["KB_CHUNK:22", "KB_CHUNK:999"],
        "riskExplanation": "合同仅原则性要求遵守环保规定，未明确许可和事故报告义务。",
        "businessImpact": "可能导致责任边界不清。",
        "revisionAdvice": "补充许可、处置和报告条款。",
    }, _task(), _evidence(), 0)

    assert finding is not None
    assert finding["contractCitationIds"] == ["CONTRACT_CLAUSE:11"]
    assert finding["policyCitationIds"] == ["KB_CHUNK:22"]
    assert finding["evidenceStatus"] == "DUAL_CITED"


def test_high_risk_without_contract_evidence_is_downgraded():
    finding = _normalize_finding({
        "title": "环保许可材料缺失",
        "severity": "HIGH",
        "policyCitationIds": ["KB_CHUNK:22"],
        "riskExplanation": "知识库要求提供许可，但当前合同证据不足。",
    }, _task(), [_evidence()[1]], 0)

    assert finding is not None
    assert finding["severity"] == "MEDIUM"
    assert finding["confidenceLevel"] == "LOW"
    assert finding["sourceBasis"] == "POLICY_ONLY"


def test_missing_clause_rule_does_not_borrow_unrelated_contract_citation():
    findings = _fallback_rule_findings(
        _task(),
        _evidence(),
        [{
            "ruleKey": "MISSING_ACCEPTANCE",
            "ruleTitle": "缺少验收条款",
            "clauseType": "OTHER",
            "severity": "HIGH",
            "detail": "未找到验收条款",
        }],
    )
    assert len(findings) == 1
    assert findings[0]["contractCitationIds"] == []


def test_missing_clause_rule_has_actionable_fallback_guidance():
    findings = _fallback_rule_findings(
        {
            "domainKey": "term_change_termination",
            "domainName": "期限、变更与终止",
            "requiredClauseTypes": ["TERMINATION"],
        },
        [{
            "sourceType": "KB_CHUNK",
            "sourceId": "KB_CHUNK:77",
            "title": "终止管理标准",
            "snippet": "应明确终止条件、通知期限、结算和资料交接。",
        }],
        [{
            "ruleKey": "PROC-TERM-002",
            "ruleTitle": "合同到期处理",
            "clauseType": "TERMINATION",
            "checkType": "MISSING",
            "checkConfig": {"fields": ["transitionService", "dataMigration"]},
            "severity": "MEDIUM",
            "detail": "未找到TERMINATION类型条款",
            "description": "应明确合同到期后的过渡服务安排和数据迁移义务",
        }],
    )
    finding = findings[0]
    assert finding["ruleKey"] == "PROC-TERM-002"
    assert "终止条件、通知方式" in finding["riskExplanation"]
    assert "过渡服务" in finding["revisionAdvice"]
    assert len(finding["negotiationAdvice"]) > 20
    assert len(finding["reviewQuestions"]) >= 2
    assert len(finding["verificationPoints"]) >= 2


def test_successful_llm_result_cannot_drop_deterministic_rule_finding(monkeypatch):
    import app.agent_runtime.graph.nodes.retrieval as retrieval

    class FakeService:
        def analyze_contract_risk_domain(self, *args):
            return {"domainConclusion": "存在终止条款缺口", "findings": []}

    monkeypatch.setattr("app.services.llm_service.LLMService", FakeService)
    state = {
        "domain_results": {"term_change_termination": [{
            "sourceType": "KB_CHUNK", "sourceId": "KB_CHUNK:77", "snippet": "应明确终止条件和交接。",
        }]},
        "rule_findings": [{
            "ruleKey": "PROC-TERM-002", "ruleTitle": "合同到期处理", "clauseType": "TERMINATION",
            "checkType": "MISSING", "checkConfig": {"fields": ["transitionService"]},
            "severity": "MEDIUM", "detail": "未找到TERMINATION类型条款",
        }],
        "domain_tasks": [{
            "domainKey": "term_change_termination", "domainName": "期限、变更与终止",
            "requiredClauseTypes": ["TERMINATION"],
        }],
        "case_snapshot": {}, "run_id": 1, "subject_id": 1,
    }
    result = retrieval.draft_domain_findings(state)
    assert result["draft_findings"][0]["ruleKey"] == "PROC-TERM-002"


def test_validator_rejects_citation_not_returned_by_retrieval():
    finding = {
        "title": "引用不存在",
        "severity": "MEDIUM",
        "clauseType": "OTHER",
        "contractCitationIds": ["CONTRACT_CLAUSE:999"],
        "policyCitationIds": [],
    }
    verdict, reasons = _validate_one(finding, {"citations": _evidence()})

    assert verdict == "REJECT_FINDING"
    assert any("not returned by retrieval" in reason for reason in reasons)


def test_report_summary_and_groups_are_deterministic():
    findings = [
        {"domainKey": "payment", "domainName": "付款", "severity": "HIGH"},
        {"domainKey": "payment", "domainName": "付款", "severity": "MEDIUM"},
        {"domainKey": "ip", "domainName": "知识产权", "severity": "LOW"},
    ]
    summary = _risk_summary(findings, {"domains": {"payment": {}, "ip": {}}})
    groups = _risk_groups(findings)

    assert summary == {
        "total": 3,
        "high": 1,
        "medium": 1,
        "low": 1,
        "reviewedDomainCount": 2,
        "primaryMessage": "优先处理 1 项高风险问题",
    }
    assert groups[0]["domainKey"] == "payment"


def test_reflection_uses_limited_report_after_one_targeted_retry():
    assert _route_after_reflection({
        "coverage": {"status": "NEED_MORE_EVIDENCE"},
        "retry_state": {"reflection_rounds": 1},
    }) == "compose_limited_report"
