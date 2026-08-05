"""Focused tests for rich contract-risk graph normalization and report grouping."""

from app.agent_runtime.graph.nodes.artifact import _risk_groups, _risk_summary
from app.agent_runtime.graph.nodes.domain_tasks import _normalize_domain
from app.agent_runtime.graph.nodes.retrieval import _normalize_finding
from app.agent_runtime.graph.nodes.validation import _validate_one


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
