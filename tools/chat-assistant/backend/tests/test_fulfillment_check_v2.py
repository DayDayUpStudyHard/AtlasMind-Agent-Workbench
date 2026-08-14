"""PRD Phase 7: 迁移履约核验 — requirement definition (task 2), evidence
rules (task 4), advisory LLM suggestions (task 5), AI-never-writes-final
(task 6), rerun scope (task 8) and append-only history (task 9)."""

import pytest

from app.agent_runtime.graph import fulfillment_check as fc
from app.agent_runtime.graph.nodes import evidence_rules as er
from app.agent_runtime.graph.nodes import fulfillment_judge as fj
from app.agent_runtime.graph.nodes import requirements as reqs
from app.agent_runtime.graph.nodes import human_confirm as hc
from app.agent_runtime.graph.nodes.retrieval import compute_rerun_scope


# ── spec / architecture ──────────────────────────────────────────────────────

def test_fulfillment_spec_compiles_via_common_builder():
    from app.agent_runtime.harness.graph_builder import build_task_graph

    graph = build_task_graph(fc.FULFILLMENT_SPEC)

    nodes = set(graph.get_graph().nodes.keys())
    for expected in (
        "decompose_requirements", "retrieve_fulfillment_evidence",
        "check_evidence_rules", "judge_each_requirement",
        "validate_fulfillment_judgement", "audit_fulfillment_coverage",
        "prepare_human_confirmation", "wait_human_confirmation",
        "apply_human_result", "persist_report",
    ):
        assert expected in nodes


def test_fulfillment_spec_stage_order_and_human_gate():
    spec = fc.FULFILLMENT_SPEC
    stages = spec.stages
    assert stages[:2] == ("load_run_context", "freeze_case_snapshot")
    assert stages.index("check_evidence_rules") < stages.index("judge_each_requirement")
    assert stages.index("judge_each_requirement") < stages.index("validate_fulfillment_judgement")
    assert stages.index("validate_fulfillment_judgement") < stages.index("audit_fulfillment_coverage")
    assert stages.index("prepare_human_confirmation") < stages.index("wait_human_confirmation")
    assert stages.index("wait_human_confirmation") < stages.index("apply_human_result")
    assert stages[-1] == "persist_report"
    # Task 7: the interrupt stage is declared as the §6.1 human_gate, and the
    # gate object IS the stage node (identity contract).
    assert spec.human_gate is not None
    assert spec.human_gate.stage == "wait_human_confirmation"
    assert spec.nodes["wait_human_confirmation"] is spec.human_gate


# ── task 2: requirement definition (deadline / consequence) ─────────────────

def test_extract_contract_consequence_rules():
    liquidated = reqs.extract_contract_consequence(
        "乙方逾期交付的，每逾期一日按合同总价的万分之五支付违约金。"
    )
    assert liquidated["ruleKey"] == "LIQUIDATED_DAMAGES"
    assert "万分之五" in liquidated["sentence"]

    rescission = reqs.extract_contract_consequence(
        "乙方逾期超过30日的，甲方有权解除本合同并追偿损失。"
    )
    assert rescission["ruleKey"] == "RESCISSION"

    deemed = reqs.extract_contract_consequence(
        "甲方收到验收申请后15日内未提出异议的，视为验收通过。"
    )
    assert deemed["ruleKey"] == "DEEMED_PASSED"

    unspecified = reqs.extract_contract_consequence("双方应友好协商。")
    assert unspecified == {"ruleKey": "NOT_SPECIFIED", "sentence": "", "source": "NOT_FOUND"}


def test_decompose_adds_deadline_and_consequence(monkeypatch):
    import app.agent_runtime.persistence as persistence

    class _FakeCursor:
        def execute(self, sql, params=None):
            pass

        def fetchone(self):
            return {
                "id": 9, "clauseId": 1, "nodeType": "PAYMENT", "label": "支付首付款",
                "businessMeaning": "支付首付款", "responsibleParty": "COUNTERPARTY",
                "nodeDate": "2026-03-01", "conditionText": None, "citationJson": "{}",
                "clauseNumber": "5",
                "clauseContent": "甲方应于2026年3月1日前支付首付款。甲方逾期付款的，"
                                 "每逾期一日按未付款项的万分之一支付违约金。",
            }

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    class _FakeConn:
        def cursor(self):
            return _FakeCursor()

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    monkeypatch.setattr(persistence, "_conn", lambda: _FakeConn())

    result = reqs.decompose_requirements({
        "subject_id": 1, "run_id": 9, "state_revision": 0,
        "task_input": {"timelineNodeId": 9},
        "extraction_snapshot": {},
        "errors": [],
    })

    items = result["fulfillment_requirements"]
    assert items
    for item in items:
        assert item["requirementId"].startswith("req-")
        assert item["deadline"] == "2026-03-01"
        assert item["deadlineCondition"] is None
        assert item["contractConsequence"]["ruleKey"] == "LIQUIDATED_DAMAGES"
        assert "违约金" in item["contractConsequence"]["sentence"]


# ── task 4: evidence rules (file type / date / amount / seal / content) ──────

def test_file_type_rule():
    assert er.file_type_rule({"fileName": "验收单.pdf"}, "ACCEPTANCE")["status"] == "PASS"
    flagged = er.file_type_rule({"fileName": "材料.exe"}, "ACCEPTANCE")
    assert flagged["status"] == "FLAG" and flagged["code"] == "UNSUPPORTED_FILE_TYPE"
    unrecognized = er.file_type_rule({"fileName": "扫描件"}, "ACCEPTANCE")
    assert unrecognized["code"] == "UNRECOGNIZED_FILE_TYPE"
    hint = er.file_type_rule({"fileName": "回单.docx"}, "PAYMENT")
    assert hint["status"] == "HINT" and hint["code"] == "TYPE_MISMATCH_HINT"


def test_date_rule():
    after = er.date_rule({"date": "2026-04-01"}, deadline="2026-03-01",
                         effective_date="2025-08-15")
    assert after["code"] == "DATE_AFTER_DEADLINE" and after["status"] == "FLAG"
    before = er.date_rule({"date": "2025-01-01"}, deadline="2026-03-01",
                          effective_date="2025-08-15")
    assert before["code"] == "DATE_BEFORE_EFFECTIVE"
    missing = er.date_rule({}, deadline="2026-03-01", effective_date="2025-08-15")
    assert missing["code"] == "DATE_MISSING"
    ok = er.date_rule({"documentDate": "2026-02-15"}, deadline="2026-03-01",
                      effective_date="2025-08-15")
    assert ok["status"] == "PASS"


def test_amount_rule():
    mismatch = er.amount_rule({"content": "付款人民币1000元整"}, "PAYMENT", expected_amount=2000.0)
    assert mismatch["code"] == "AMOUNT_MISMATCH" and mismatch["status"] == "FLAG"
    missing = er.amount_rule({"content": "已完成付款"}, "PAYMENT", expected_amount=2000.0)
    assert missing["code"] == "AMOUNT_MISSING"
    ok = er.amount_rule({"content": "付款金额 2000 元"}, "PAYMENT", expected_amount=2000.0)
    assert ok["status"] == "PASS"
    skipped = er.amount_rule({"content": "x"}, "ACCEPTANCE", expected_amount=2000.0)
    assert skipped["status"] == "SKIPPED"


def test_seal_rule():
    missing = er.seal_rule({"content": "验收完成"}, "ACCEPTANCE")
    assert missing["code"] == "SEAL_MISSING" and missing["status"] == "FLAG"
    ok = er.seal_rule({"content": "双方签字盖章确认"}, "ACCEPTANCE")
    assert ok["status"] == "PASS"
    skipped = er.seal_rule({"content": "回单"}, "PAYMENT")
    assert skipped["status"] == "SKIPPED"


def test_run_evidence_rules_rollup_and_compliance():
    docs = [{
        "documentId": 11, "fileName": "验收单.pdf", "date": "2026-02-15",
        "content": "2026年2月完成验收，设备调试通过，验收通过，出具报告，"
                   "签字确认，双方盖章确认。",
    }]
    requirements = [
        {
            "requirementId": "req-1", "requirement": "完成验收：设备调试",
            "acceptanceCriteria": "验收单、验收会议纪要或测试报告",
        },
        {
            "requirementId": "req-2",
            "requirement": "设备调试 验收通过 出具报告 签字确认",
        },
    ]
    rules = er.run_evidence_rules(
        docs, node_type="ACCEPTANCE", deadline="2026-03-01",
        effective_date="2025-08-15", expected_amount=None, requirements=requirements,
    )
    assert rules["documentCount"] == 1
    by_id = {item["requirementId"]: item for item in rules["requirementCompliance"]}
    # req-1: clean file/date/seal, but only a 2-term content match — a soft
    # HINT (weak content match), never a hard contradiction.
    assert by_id["req-1"]["compliance"] == "HINT"
    assert not by_id["req-1"]["hardFlags"]
    assert [flag["code"] for flag in by_id["req-1"]["softFlags"]] == ["CONTENT_WEAK_MATCH"]
    # req-2: all four terms present in the evidence content → full PASS.
    assert by_id["req-2"]["compliance"] == "PASS"
    assert rules["hardFlagCount"] == 0
    assert rules["softFlagCount"] == 1

    bad_docs = [{
        "documentId": 12, "fileName": "材料.exe", "date": "2026-04-01",
        "content": "无关内容",
    }]
    flagged = er.run_evidence_rules(
        bad_docs, node_type="ACCEPTANCE", deadline="2026-03-01",
        effective_date="2025-08-15", expected_amount=None, requirements=requirements,
    )
    compliance = flagged["requirementCompliance"][0]
    assert compliance["compliance"] == "FLAG"
    codes = {flag["code"] for flag in compliance["hardFlags"]}
    assert "DATE_AFTER_DEADLINE" in codes and "SEAL_MISSING" in codes
    assert "CONTENT_NO_MATCH" in codes


def test_check_evidence_rules_node_stamps_channel(monkeypatch):
    state = {
        "subject_id": 1, "run_id": 9, "state_revision": 0,
        "case_snapshot": {"effectiveDate": "2025-08-15"},
        "fulfillment_requirements": [{
            "requirementId": "req-1", "requirement": "完成付款：首付款",
            "acceptanceCriteria": "付款记录、银行回单", "deadline": "2026-03-01",
            "supportingFacts": [{"elementKey": "contract_amount", "rawValue": "2000元"}],
        }],
        "fulfillment_context": {
            "timelineNode": {"nodeType": "PAYMENT", "label": "首付款"},
            "evidenceDocuments": [{
                "documentId": 11, "fileName": "回单.pdf", "date": "2026-02-15",
                "content": "已完成付款，首付款金额 2000 元，附银行回单与发票。",
            }],
        },
    }
    result = er.check_evidence_rules(state)

    rules = result["evidence_rules"]
    assert rules["ruleVersion"] == er.EVIDENCE_RULE_VERSION
    compliance = rules["requirementCompliance"][0]
    # Amount parses from the contract element and matches the evidence
    # (2000 == 2000), date is inside the period — no hard flags. The 2-term
    # content match is a soft HINT, not a contradiction.
    assert compliance["compliance"] == "HINT"
    assert not compliance["hardFlags"]
    doc_codes = {rule["code"] for rule in rules["documents"][0]["rules"]}
    assert "AMOUNT_OK" in doc_codes and "DATE_OK" in doc_codes
    assert result["observations"][0]["toolName"] == "runEvidenceRules"
    assert rules["durationMs"] >= 0


# ── task 5 / 6: advisory LLM suggestions, never the final state ─────────────

def _evidence_state(**overrides):
    state = {
        "run_id": 9, "subject_id": 1, "state_revision": 0,
        "case_snapshot": {"ourSide": "A"},
        "task_input": {"timelineNodeId": 9},
        "observations": [],
        "citations": [],
        "fulfillment_requirements": [{
            "requirementId": "req-1", "requirement": "完成付款：首付款",
            "required": True, "sourceCitationIds": ["CONTRACT_CLAUSE:1"],
            "acceptanceCriteria": "付款记录、银行回单、发票或收据",
            "deadline": "2026-03-01", "deadlineCondition": None,
            "contractConsequence": {"ruleKey": "NOT_SPECIFIED"},
        }],
        "fulfillment_context": {
            "timelineNode": {"label": "首付款", "businessMeaning": "支付首付款",
                             "nodeType": "PAYMENT", "clauseContent": ""},
            "verification": {},
            "evidenceDocuments": [{
                "documentId": 11, "fileName": "回单.pdf",
                "snippet": "付款 首付款 银行回单 发票 收据 金额一致",
                "content": "付款 首付款 银行回单 发票 收据 金额一致",
            }],
            "contractEvidence": [],
        },
        "evidence_rules": {},
        "rerun_scope": {},
    }
    state.update(overrides)
    return state


def test_judge_attaches_ai_suggestion_without_writing_final(monkeypatch):
    from app.services.llm_service import LLMService

    def fake_llm(self, case, verification, citations, task_input, run_id=0):
        return {
            "reportType": "FULFILLMENT_REPORT",
            "conclusion": "BASICALLY_SATISFIED",
            "riskLevel": "LOW",
            "confidenceLevel": "HIGH",
            "requirements": [{
                "requirement": "完成付款：首付款", "judgement": "满足",
                "evidence": "银行回单", "gap": "", "required": True,
            }],
            "missingEvidence": [],
            "suggestedActions": [],
        }

    # LLMService() raises without an API key in this env — stub construction
    # so the advisory call path (task 5) is what's exercised here.
    monkeypatch.setattr(LLMService, "__init__", lambda self: None)
    monkeypatch.setattr(LLMService, "contract_fulfillment_check", fake_llm)

    result = fj.judge_each_requirement(_evidence_state())

    row = result["artifacts"]["judgements"][0]
    assert row["requirementId"] == "req-1"
    assert row["aiSuggestion"]["conclusion"] == "BASICALLY_SATISFIED"
    # Task 6: the rule judgement stays conservative — the AI suggestion is a
    # separate field and never replaces the human-decided final state.
    assert row["judgement"] in ("NEEDS_REVIEW", "UNCLEAR_TERMS", "EVIDENCE_INSUFFICIENT")
    assert result["fulfillment_ai"]["status"] == "LLM_ENRICHED"
    assessment = result["artifacts"]["fulfillmentAssessment"]
    assert assessment["aiSuggestion"]["conclusion"] == "BASICALLY_SATISFIED"


def test_judge_falls_back_to_rule_layer_when_llm_fails(monkeypatch):
    from app.services.llm_service import LLMService

    def boom(self, *args, **kwargs):
        raise RuntimeError("llm down")

    monkeypatch.setattr(LLMService, "contract_fulfillment_check", boom)

    result = fj.judge_each_requirement(_evidence_state())

    assert result["fulfillment_ai"]["status"] == "FALLBACK_RULE"
    row = result["artifacts"]["judgements"][0]
    assert row["aiSuggestion"]["status"] == "FALLBACK_RULE"
    assert row["aiSuggestion"]["conclusion"] is None
    # The rule layer still produced a conservative, human-confirmable row.
    assert row["judgement"] in ("NEEDS_REVIEW", "UNCLEAR_TERMS", "EVIDENCE_INSUFFICIENT")


def test_normalize_ai_suggestion_demotes_forbidden_conclusions():
    normalized = fj.normalize_ai_suggestion({
        "reportType": "FULFILLMENT_REPORT",
        "conclusion": "COMPLETED",  # forbidden final (task 6)
        "requirements": [{"requirement": "x", "judgement": "ACCEPTED", "required": True}],
        "missingEvidence": [], "suggestedActions": [],
    })
    assert normalized["conclusion"] == "NEEDS_REVIEW"
    assert normalized["requirements"][0]["conclusion"] == "NEEDS_REVIEW"
    assert any("禁止" in error for error in normalized["schemaErrors"])

    bad_shape = fj.normalize_ai_suggestion("not json")
    assert bad_shape["status"] == "FALLBACK_RULE"

    wrong_type = fj.normalize_ai_suggestion({
        "reportType": "OTHER_REPORT", "conclusion": "BASICALLY_SATISFIED",
        "requirements": [], "missingEvidence": [],
    })
    assert any("reportType" in error for error in wrong_type["schemaErrors"])


def test_judge_downgrades_supported_proof_on_hard_rule_flag(monkeypatch):
    from app.services.llm_service import LLMService

    monkeypatch.setattr(
        LLMService, "contract_fulfillment_check",
        lambda self, *a, **kw: {
            "reportType": "FULFILLMENT_REPORT", "conclusion": "BASICALLY_SATISFIED",
            "requirements": [], "missingEvidence": [],
        },
    )
    state = _evidence_state(evidence_rules={
        "requirementCompliance": [{
            "requirementId": "req-1",
            "hardFlags": [{"rule": "DATE", "code": "DATE_AFTER_DEADLINE",
                           "detail": "证据日期晚于节点截止时间"}],
            "softFlags": [],
        }],
    })

    result = fj.judge_each_requirement(state)

    row = result["artifacts"]["judgements"][0]
    # Strong content match would normally be SUPPORTED; the hard flag must
    # stop a "supported" claim from reaching the human gate.
    assert row["proofStatus"] == "PARTIAL"
    assert row["nodeUsability"] == "LIMITED"
    assert "证据规则检查" in row["gap"]


# ── task 8: rerun scope — new material only re-runs affected requirements ────

def _prev_judgements():
    return [
        {
            "requirementId": "req-1", "requirement": "完成付款：首付款",
            "judgement": "NEEDS_REVIEW", "proofStatus": "PARTIAL",
            "evidenceSnapshot": [{
                "documentId": 11, "version": 1, "contentHash": "hash-11",
            }],
            "aiSuggestion": {"status": "LLM_ENRICHED",
                             "conclusion": "BASICALLY_SATISFIED"},
        },
        {
            "requirementId": "req-2", "requirement": "完成验收：设备调试",
            "judgement": "EVIDENCE_INSUFFICIENT", "proofStatus": "INSUFFICIENT",
            "evidenceSnapshot": [],
            "aiSuggestion": {"status": "LLM_ENRICHED",
                             "conclusion": "INSUFFICIENT_EVIDENCE"},
        },
    ]


def test_rerun_scope_first_run_is_all():
    scope = compute_rerun_scope([], [])
    assert scope["mode"] == "ALL"


def test_rerun_scope_unchanged_is_unchanged():
    scope = compute_rerun_scope(
        _prev_judgements(),
        [{"documentId": 11, "version": 1, "contentHash": "hash-11"}],
    )
    assert scope["mode"] == "UNCHANGED"
    assert scope["previousJudgements"] == _prev_judgements()


def test_rerun_scope_new_matching_document_affects_only_matching_requirement():
    scope = compute_rerun_scope(
        _prev_judgements(),
        [
            {"documentId": 11, "version": 1, "contentHash": "hash-11"},
            # New payment receipt — both of req-1's terms appear in it,
            # none of req-2's, so only req-1 is re-judged.
            {"documentId": 22, "version": 1, "contentHash": "hash-22",
             "fileName": "回单.pdf",
             "content": "完成付款 首付款 银行回单 发票 收据"},
        ],
    )
    assert scope["mode"] == "AFFECTED_ONLY"
    assert scope["affectedRequirementIds"] == ["req-1"]
    assert scope["newEvidence"] == ["22"]


def test_rerun_scope_changed_document_affects_citing_requirements():
    scope = compute_rerun_scope(
        _prev_judgements(),
        [{"documentId": 11, "version": 2, "contentHash": "hash-11-v2"}],
    )
    assert scope["mode"] == "AFFECTED_ONLY"
    assert scope["affectedRequirementIds"] == ["req-1"]
    assert scope["changedEvidence"] == ["11"]


def test_rerun_scope_unmapped_new_document_degrades_to_all():
    scope = compute_rerun_scope(
        _prev_judgements(),
        [
            {"documentId": 11, "version": 1, "contentHash": "hash-11"},
            {"documentId": 33, "version": 1, "contentHash": "hash-33",
             "fileName": "会议纪要.pdf", "content": "会议纪要 时间 地点 参会人"},
        ],
    )
    # Conservative: an unattributable new document may matter to anything.
    assert scope["mode"] == "ALL"


def test_judge_carries_forward_unaffected_requirements(monkeypatch):
    from app.services.llm_service import LLMService

    monkeypatch.setattr(LLMService, "__init__", lambda self: None)
    monkeypatch.setattr(
        LLMService, "contract_fulfillment_check",
        lambda self, *a, **kw: {
            "reportType": "FULFILLMENT_REPORT",
            "conclusion": "BASICALLY_SATISFIED",
            "requirements": [], "missingEvidence": [],
        },
    )
    state = _evidence_state()
    # Both requirements are in the current decomposition; the previous run
    # judged both, but only req-1 is affected by the new material.
    state["fulfillment_requirements"] = [
        state["fulfillment_requirements"][0],
        {
            "requirementId": "req-2", "requirement": "完成验收：设备调试",
            "required": True, "sourceCitationIds": ["CONTRACT_CLAUSE:2"],
            "acceptanceCriteria": "验收单", "deadline": "2026-04-01",
            "deadlineCondition": None,
            "contractConsequence": {"ruleKey": "NOT_SPECIFIED"},
        },
    ]
    state["rerun_scope"] = {
        "mode": "AFFECTED_ONLY",
        "affectedRequirementIds": ["req-1"],
        "previousJudgements": [
            {
                "requirementId": "req-2", "requirement": "完成验收：设备调试",
                "judgement": "EVIDENCE_INSUFFICIENT", "proofStatus": "INSUFFICIENT",
                "evidenceSnapshot": [],
                "aiSuggestion": {"status": "LLM_ENRICHED",
                                 "conclusion": "INSUFFICIENT_EVIDENCE"},
            },
        ],
    }

    result = fj.judge_each_requirement(state)

    rows = {row["requirementId"]: row for row in result["artifacts"]["judgements"]}
    assert rows["req-1"].get("carriedForward") is not True   # affected → re-judged
    assert rows["req-2"]["carriedForward"] is True           # unaffected → carried
    assert rows["req-2"]["aiSuggestion"]["conclusion"] == "INSUFFICIENT_EVIDENCE"
    assessment = result["artifacts"]["fulfillmentAssessment"]
    assert assessment["carriedForwardCount"] == 1
    assert assessment["rerunMode"] == "AFFECTED_ONLY"


# ── task 6: validator backstop over the AI suggestion layer ─────────────────

def test_validate_demotes_forbidden_ai_suggestion(monkeypatch):
    from app.agent_runtime.graph.nodes import fulfillment_validate as fv

    state = {
        "state_revision": 0, "errors": [],
        "artifacts": {"judgements": [{
            "requirement": "x", "judgement": "NEEDS_REVIEW",
            "aiSuggestion": {"conclusion": "ACCEPTED"},
        }]},
    }
    result = fv.validate_fulfillment_judgement(state)

    row = state["artifacts"]["judgements"][0]
    assert row["aiSuggestion"]["conclusion"] == "NEEDS_REVIEW"
    assert row["aiSuggestion"]["demotedByValidator"] is True
    assert any("AI suggestion must not carry final result" in err["error"]
               for err in result["errors"])
    assert result["fulfillment_validation"]["durationMs"] >= 0


# ── task 7 / 9: human gate payload and append-only persistence ──────────────

def test_wait_state_exposes_ai_suggestion_and_requirement_fields():
    state = {
        "artifacts": {
            "judgements": [{
                "requirementId": "req-1", "requirement": "完成付款：首付款",
                "judgement": "NEEDS_REVIEW", "proofStatus": "PARTIAL",
                "nodeUsability": "LIMITED", "gap": "x", "reason": "y",
                "nextStep": "z", "carriedForward": False,
                "deadline": "2026-03-01", "deadlineCondition": None,
                "contractConsequence": {"ruleKey": "NOT_SPECIFIED"},
                "aiSuggestion": {"status": "LLM_ENRICHED",
                                 "conclusion": "BASICALLY_SATISFIED"},
            }],
            "fulfillmentAssessment": {"evidenceCount": 1, "rerunMode": "ALL"},
        },
        "observations": [],
    }
    wait_state, _ = hc._build_wait_state(state)

    judgement = wait_state["judgements"][0]
    assert judgement["aiSuggestion"]["conclusion"] == "BASICALLY_SATISFIED"
    assert judgement["deadline"] == "2026-03-01"
    assert judgement["carriedForward"] is False
    assert wait_state["summary"]["rerunMode"] == "ALL"


def test_apply_human_result_conclusion_comes_only_from_manual_result():
    state = {
        "state_revision": 0, "manual_result": "SATISFIED", "note": "n",
        "operator_id": "op-1", "task_input": {"timelineNodeId": 9},
        "artifacts": {
            "judgements": [{
                "requirementId": "req-1", "requirement": "完成付款",
                "judgement": "NEEDS_REVIEW",
                "aiSuggestion": {"conclusion": "BASICALLY_SATISFIED"},
                "evidenceSnapshot": [{"documentId": 11, "contentHash": "hash-11"}],
            }],
            "fulfillmentAssessment": {"evidenceCount": 1},
        },
        "evidence_snapshot": [],
        "citations": [],
        "wait_state": {},
    }
    result = hc.apply_human_result(state)

    artifact = result["artifact"]
    assert artifact["conclusion"] == "BASICALLY_SATISFIED"  # from manual_result
    # Task 8/9: the persisted content carries the judgement baseline (with
    # evidenceSnapshot) for the next run's diff, plus the node identity.
    assert artifact["content"]["timelineNodeId"] == 9
    assert artifact["content"]["requirements"][0]["evidenceSnapshot"][0]["documentId"] == 11


def test_report_store_inserts_fulfillment_rows_without_overwriting(monkeypatch):
    """Task 9: 人工结论追加保存 — each run INSERTs its own agent_report row;
    no UPDATE / DELETE touches report history."""
    import app.agent_runtime.persistence as persistence

    queries = []

    class _FakeCursor:
        lastrowid = 1

        def execute(self, sql, params=None):
            queries.append(sql)

        def fetchone(self):
            return {"subjectType": "CONTRACT_CASE", "subjectId": 1, "workflowId": None}

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    class _FakeConn:
        def cursor(self):
            return _FakeCursor()

        def commit(self):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    monkeypatch.setattr(persistence, "_conn", lambda: _FakeConn())

    artifact = {
        "reportType": "FULFILLMENT_REPORT",
        "title": "履约核验报告", "summary": "s",
        "conclusion": "BASICALLY_SATISFIED",
        "requirements": [{"requirementId": "req-1", "requirement": "完成付款"}],
        "content": {
            "manualConfirmationRequired": False, "manualResult": "SATISFIED",
            "timelineNodeId": 9, "requirements": [{"requirementId": "req-1"}],
        },
    }
    first_id = persistence.MySqlReportStore._save_sync(1, 500, "FULFILLMENT_CHECK", artifact)
    second_id = persistence.MySqlReportStore._save_sync(1, 501, "FULFILLMENT_CHECK", artifact)

    assert first_id == 1 and second_id == 1
    inserts = [sql for sql in queries if "INSERT INTO agent_report" in sql]
    assert len(inserts) == 2  # one row per run — history appended, never replaced
    assert not any("UPDATE agent_report" in sql for sql in queries)
    assert not any("DELETE FROM agent_report" in sql for sql in queries)


def test_fulfillment_channels_declared_on_state_schema():
    from app.agent_runtime.graph.state import BaseGraphState

    for channel in ("evidence_rules", "rerun_scope", "fulfillment_ai",
                    "fulfillment_validation"):
        assert channel in BaseGraphState.__annotations__, (
            f"{channel} must be declared on BaseGraphState — LangGraph silently "
            "drops undeclared node-output keys at runtime"
        )


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
