from app.agent_runtime.contract_store import (
    _build_key_evidence_bundle,
    _evaluate_review_rules,
)
from app.agent_runtime.contract_tools import ContractToolRegistry
from app.agent_runtime.persistence import _report_risk_items
from app.agent_runtime.prompts import _FALLBACK_PROMPTS


def test_contains_rule_checks_every_clause_of_the_same_type():
    rules = [{
        "id": 1,
        "ruleKey": "PAYMENT_INVOICE",
        "clauseType": "PAYMENT",
        "title": "付款应以合规发票为前提",
        "description": "付款前必须收到合规发票",
        "checkType": "CONTAINS",
        "checkConfig": {"keywords": ["发票"]},
        "severity": "MEDIUM",
    }]
    clauses = [
        {"id": 71, "clauseType": "PAYMENT", "title": "合同价款", "content": "服务总价为十万元。"},
        {"id": 88, "clauseType": "PAYMENT", "title": "报酬及支付方式", "content": "甲方收到合规发票后付款。"},
    ]

    assert _evaluate_review_rules(rules, clauses) == []


def test_semantic_rule_cites_the_clause_that_contains_forbidden_wording():
    rules = [{
        "id": 2,
        "ruleKey": "LIABILITY_INDIRECT_LOSS",
        "clauseType": "LIABILITY",
        "title": "不得排除间接损失责任",
        "description": "检查责任限制条款",
        "checkType": "SEMANTIC",
        "checkConfig": {"forbidden": ["不承担任何间接损失"]},
        "severity": "HIGH",
    }]
    clauses = [
        {"id": 83, "clauseType": "LIABILITY", "title": "资料提供责任", "content": "甲方应按时提供技术资料。"},
        {"id": 109, "clauseType": "LIABILITY", "title": "违约责任", "content": "乙方不承担任何间接损失。"},
    ]

    findings = _evaluate_review_rules(rules, clauses)

    assert len(findings) == 1
    assert findings[0]["contractCitationIds"] == ["CONTRACT_CLAUSE:109"]
    assert findings[0]["contractCitation"]["clause"] == "违约责任"


def test_missing_rule_checks_configured_fields_not_only_clause_type():
    rules = [{
        "id": 8,
        "ruleKey": "PROC-ACC-002",
        "clauseType": "ACCEPTANCE",
        "title": "验收期限明确",
        "description": "合同应约定明确的验收期限",
        "checkType": "MISSING",
        "checkConfig": {"fields": ["acceptancePeriod"]},
        "severity": "MEDIUM",
    }]
    clauses = [{
        "id": 103,
        "clauseType": "ACCEPTANCE",
        "title": "验收标准",
        "content": "技术服务成果应符合国家相关标准要求。",
        "semanticElements": None,
    }]

    findings = _evaluate_review_rules(rules, clauses)

    assert len(findings) == 1
    assert "acceptancePeriod" in findings[0]["detail"]
    assert findings[0]["contractCitationIds"] == ["CONTRACT_CLAUSE:103"]


def test_threshold_rule_treats_unavailable_required_value_as_review_gap():
    rules = [{
        "id": 10,
        "ruleKey": "PROC-LIAB-001",
        "clauseType": "LIABILITY",
        "title": "责任上限合理性",
        "description": "合同应明确责任上限",
        "checkType": "THRESHOLD",
        "checkConfig": {"field": "liabilityCapPct", "operator": "gte", "value": 100},
        "severity": "HIGH",
    }]
    clauses = [{
        "id": 111,
        "clauseType": "LIABILITY",
        "title": "逾期违约责任",
        "content": "乙方每逾期一天按技术服务费的0.5%支付违约金。",
        "semanticElements": None,
    }]

    findings = _evaluate_review_rules(rules, clauses)

    assert len(findings) == 1
    assert "liabilityCapPct" in findings[0]["detail"]


def test_indirect_loss_rule_is_not_satisfied_by_unrelated_force_majeure_wording():
    rules = [{
        "id": 11,
        "ruleKey": "PROC-LIAB-002",
        "clauseType": "LIABILITY",
        "title": "间接损失排除",
        "description": "合同应明确排除间接损失",
        "checkType": "CONTAINS",
        "checkConfig": {"keywords": ["间接损失", "利润损失", "排除", "不承担"]},
        "severity": "HIGH",
    }]
    clauses = [{
        "id": 109,
        "clauseType": "LIABILITY",
        "title": "违约责任",
        "content": "乙方未按期交付的，应支付合同金额10%的违约金。",
    }, {
        "id": 122,
        "clauseType": "LIABILITY",
        "title": "不可抗力",
        "content": "不可抗力导致合同无法履行的，双方互不承担违约责任。",
    }]

    findings = _evaluate_review_rules(rules, clauses)

    assert len(findings) == 1
    assert findings[0]["ruleKey"] == "PROC-LIAB-002"
    assert findings[0]["contractCitationIds"] == ["CONTRACT_CLAUSE:109"]


def test_inventory_bundles_deduplicated_key_clause_content_for_reflection():
    clauses = [
        {"id": 1, "clauseType": "PAYMENT", "title": "付款", "content": "验收后付款。"},
        {"id": 2, "clauseType": "PAYMENT", "title": "付款副本", "content": "验收后付款。"},
        {"id": 3, "clauseType": "IP", "title": "成果归属", "content": "技术成果归双方所有。"},
        {"id": 4, "clauseType": "OTHER", "title": "定义", "content": "一般定义。"},
    ]

    evidence = _build_key_evidence_bundle(clauses, "SERVICE_PROCUREMENT")

    assert [item["id"] for item in evidence] == [1, 3]
    assert all(item["sourceType"] == "CONTRACT_CLAUSE" for item in evidence)


def test_inventory_key_evidence_is_promoted_to_contract_citations():
    observations = [{
        "output": {
            "inventory": {
                "keyEvidenceClauses": [{
                    "id": 107,
                    "clauseType": "IP",
                    "title": "技术成果归属",
                    "content": "技术成果归双方所有。",
                    "sourceType": "CONTRACT_CLAUSE",
                }],
            },
        },
    }]

    citations = ContractToolRegistry.citations_from(observations)

    assert [item["id"] for item in citations] == [107]


def test_citations_keep_same_numeric_id_from_different_source_types():
    observations = [{
        "output": {
            "inventory": {
                "keyEvidenceClauses": [{
                    "id": 3,
                    "clauseType": "ACCEPTANCE",
                    "title": "合同验收条款",
                    "content": "符合国家相关标准。",
                    "sourceType": "CONTRACT_CLAUSE",
                }],
            },
        },
    }, {
        "output": {
            "items": [{
                "id": 3,
                "clauseType": "ACCEPTANCE",
                "title": "标准验收条款",
                "content": "15个工作日内按量化指标验收。",
                "sourceType": "CONTRACT_STANDARD_CLAUSE",
            }],
        },
    }]

    citations = ContractToolRegistry.citations_from(observations)

    assert len(citations) == 2
    assert {item["sourceType"] for item in citations} == {
        "CONTRACT_CLAUSE", "CONTRACT_STANDARD_CLAUSE",
    }


def test_reflection_prompt_distinguishes_contract_risk_from_evidence_gap():
    prompt = _FALLBACK_PROMPTS["reflection"]

    assert "已证实的条款缺失或约定模糊属于风险发现" in prompt
    assert "不等于证据覆盖不足" in prompt
    assert "合同审查不得要求实际交付、验收或付款凭证" in prompt


def test_contract_report_risks_use_the_structured_findings():
    findings = [{"ruleKey": "PROC-IP-002", "title": "背景知识产权保护缺失"}]

    risks = _report_risk_items(
        "CONTRACT_REVIEW",
        {"findings": findings, "risks": [{"title": "旧风险摘要"}]},
    )

    assert risks == findings
