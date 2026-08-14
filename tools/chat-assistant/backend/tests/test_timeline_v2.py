"""PRD Phase 6: 迁移履约日程 — the timeline as an observable DAG with
separate rule / LLM / validation layers, complete citations, risk flags and
a FINAL-only publish contract."""

import pytest

from app.agent_runtime.graph import timeline_extraction as te


def _clause(clause_id, number, title, content, clause_type="DELIVERY"):
    return {
        "id": clause_id,
        "clauseNumber": number,
        "title": title,
        "content": content,
        "clauseType": clause_type,
        "pageNumber": 1,
        "startOffset": 0,
        "endOffset": len(content),
        "documentId": 50,
    }


def _timeline_state(**overrides):
    state = {
        "run_id": 9,
        "subject_id": 1,
        "state_revision": 0,
        "timeline_scope": {
            "caseId": 1,
            "documentId": 50,
            "documentVersion": 1,
            "effectiveDate": "2025-08-15",
            "inferredYear": 2025,
            "quality": {},
            "requireLlm": True,
        },
        "timeline_clauses": [
            _clause(
                1, "3", "交付期限",
                "技术服务有效期：2025年8月15日至2026年12月31日。"
                "乙方应在验收通过后30日内提交竣工图。",
            )
        ],
        "timeline_candidates": [],
    }
    state.update(overrides)
    return state


# ── spec / architecture ──────────────────────────────────────────────────────

def test_timeline_spec_compiles_via_common_builder():
    from app.agent_runtime.harness.graph_builder import build_task_graph

    graph = build_task_graph(te.TIMELINE_SPEC)

    nodes = set(graph.get_graph().nodes.keys())
    assert "select_timeline_scope" in nodes
    assert "extract_rule_timeline_candidates" in nodes
    assert "enrich_timeline_candidates" in nodes
    assert "validate_timeline_nodes" in nodes
    assert "audit_timeline_coverage" in nodes
    assert "persist_final_timeline_nodes" in nodes
    assert te.TIMELINE_SPEC.human_gate is None


def test_timeline_spec_stage_order_follows_lifecycle():
    stages = te.TIMELINE_SPEC.stages
    assert stages[:2] == ("load_run_context", "freeze_case_snapshot")
    assert stages.index("extract_rule_timeline_candidates") < stages.index("enrich_timeline_candidates")
    assert stages.index("enrich_timeline_candidates") < stages.index("validate_timeline_nodes")
    assert stages.index("validate_timeline_nodes") < stages.index("audit_timeline_coverage")
    assert stages[-1] == "persist_final_timeline_nodes"


# ── planner / retriever ──────────────────────────────────────────────────────

def test_select_timeline_scope_builds_date_basis(monkeypatch):
    monkeypatch.setattr(te, "_select_timeline_document", lambda case_id, document_id: {
        "id": 50, "version": 2, "parseDiagnostics": '{"quality": {"level": "LOW"}}',
    })
    monkeypatch.setattr(te, "_load_case_effective_date", lambda case_id: "2025-08-15")

    result = te.select_timeline_scope({
        "subject_id": 1, "run_id": 9, "state_revision": 0,
        "analysis_workflow": {"documentId": 50},
    })

    scope = result["timeline_scope"]
    assert scope["caseId"] == 1
    assert scope["documentId"] == 50
    assert scope["documentVersion"] == 2
    assert scope["effectiveDate"] == "2025-08-15"
    assert scope["inferredYear"] == 2025
    assert scope["requireLlm"] is True
    assert scope["quality"]["level"] == "LOW"
    assert result["observations"][0]["toolName"] == "selectTimelineScope"


def test_select_timeline_scope_fails_without_ready_document(monkeypatch):
    monkeypatch.setattr(te, "_select_timeline_document", lambda case_id, document_id: None)

    with pytest.raises(ValueError, match="尚未解析完成"):
        te.select_timeline_scope({
            "subject_id": 1, "run_id": 9, "state_revision": 0,
            "analysis_workflow": {},
        })


def test_load_timeline_clause_evidence_requires_clauses(monkeypatch):
    monkeypatch.setattr(te, "_load_timeline_clause_rows", lambda case_id, document_id: [])

    with pytest.raises(ValueError, match="条款证据为空"):
        te.load_timeline_clause_evidence(_timeline_state())


# ── rule layer (task 1 / 4 / 5 / 7) ──────────────────────────────────────────

def test_rule_layer_resolves_dates_and_keeps_conditionals():
    result = te.extract_rule_timeline_candidates(_timeline_state())

    nodes = result["timeline_candidates"]
    dates = sorted(node.get("date") for node in nodes if node.get("date"))
    assert "2025-08-15" in dates and "2026-12-31" in dates
    conditionals = [node for node in nodes if node.get("date") is None]
    assert conditionals and all(node["condition"] for node in conditionals)
    assert all(node["citation"]["extractionMode"] for node in nodes)
    obs = result["observations"][0]
    assert obs["output"]["candidateCount"] == len(nodes)
    assert obs["output"]["durationMs"] >= 0


def test_rule_layer_flags_mojibake_without_rewriting_text():
    content = "技术服务有效期：2026年3月1日至2026年12月31日。ä¸åŒçš„æ˜¯"
    state = _timeline_state(timeline_clauses=[_clause(2, "5", "付款", content)])

    result = te.extract_rule_timeline_candidates(state)

    nodes = result["timeline_candidates"]
    assert nodes
    assert all(
        node["citation"]["textQuality"].get("mojibakeRisk") for node in nodes
    )
    assert all(node["status"] == "NEEDS_REVIEW" for node in nodes)
    # 原文未被篡改 — the clause text stored on the citation is untouched
    assert all(node["citation"]["fullQuote"] == content for node in nodes)
    assert result["observations"][0]["output"]["mojibakeFlaggedCount"] == len(nodes)


def test_rule_layer_flags_missing_effective_date_basis():
    state = _timeline_state()
    state["timeline_scope"]["effectiveDate"] = None
    state["timeline_clauses"] = [_clause(3, "7", "进度款", "乙方应在3月15日前完成交付。")]

    result = te.extract_rule_timeline_candidates(state)

    nodes = result["timeline_candidates"]
    assert nodes
    assert all(
        node["citation"]["dateBasis"].get("effectiveDateMissing") for node in nodes
    )
    assert result["observations"][0]["output"]["dateBasisUncertainCount"] == len(nodes)


def test_rule_layer_downgrades_low_quality_document():
    state = _timeline_state()
    state["timeline_scope"]["quality"] = {"level": "LOW"}

    result = te.extract_rule_timeline_candidates(state)

    nodes = result["timeline_candidates"]
    assert nodes
    assert all(node["status"] == "NEEDS_REVIEW" for node in nodes)
    assert all(
        node["citation"]["textQuality"]["documentQuality"]["level"] == "LOW"
        for node in nodes
    )


# ── LLM layer (task 2 / 6 / 8) ───────────────────────────────────────────────

def test_enrich_layer_stamps_status_and_duration(monkeypatch):
    state = _timeline_state(timeline_candidates=[{
        "clauseId": 1, "nodeType": "SERVICE_END", "label": "服务结束",
        "date": "2026-12-31", "condition": None, "responsibleParty": "BOTH",
        "businessMeaning": "服务结束", "confidence": 0.95, "status": "EXTRACTED",
        "source": "RULE_CANDIDATE",
        "citation": {"quote": "2026年12月31日", "extractionMode": "TEXT_DATE_RANGE"},
    }])
    monkeypatch.setattr(te, "_enrich_timeline_nodes", lambda nodes, clauses, strict: (
        nodes, {"status": "LLM_ENRICHED", "requested": 1, "returned": 1,
                "missing": 0, "dropped": 0, "retryCount": 0},
    ))

    result = te.enrich_timeline_candidates(state)

    assert result["timeline_enrichment"]["status"] == "LLM_ENRICHED"
    assert result["timeline_enrichment"]["durationMs"] >= 0
    assert result["observations"][0]["toolName"] == "enrichTimelineCandidates"


def test_enrich_layer_refuses_to_publish_without_llm_review(monkeypatch):
    state = _timeline_state(timeline_candidates=[{
        "clauseId": 1, "nodeType": "SERVICE_END", "label": "服务结束",
        "date": "2026-12-31", "condition": None,
        "citation": {"quote": "x"},
    }])
    monkeypatch.setattr(te, "_enrich_timeline_nodes", lambda nodes, clauses, strict: (
        nodes, {"status": "FALLBACK_RULE"},
    ))

    with pytest.raises(RuntimeError, match="语义复核暂不可用"):
        te.enrich_timeline_candidates(state)


# ── validation layer (task 3 / 6 / 7) ────────────────────────────────────────

def _candidate(**overrides):
    node = {
        "clauseId": 1,
        "nodeType": "PAYMENT",
        "label": "支付首付款",
        "date": "2026-03-01",
        "condition": None,
        "responsibleParty": "COUNTERPARTY",
        "businessMeaning": "支付首付款",
        "confidence": 0.9,
        "status": "EXTRACTED",
        "source": "LLM_ENRICHED",
        "citation": {
            "quote": "2026年3月1日前支付首付款",
            "extractionMode": "TEXT_DATE",
            "timelineEnrichment": {"reason": "ok"},
        },
    }
    node.update(overrides)
    return node


def _grounded_clauses():
    """Clause evidence whose content contains the default candidate quote."""
    return [_clause(1, "5", "付款", "甲方应于2026年3月1日前支付首付款。")]


def test_validation_dedups_and_stamps_source_lineage():
    state = _timeline_state(
        timeline_clauses=_grounded_clauses(),
        timeline_candidates=[_candidate(), _candidate()],  # exact duplicate
    )

    result = te.validate_timeline_nodes(state)

    validation = result["timeline_validation"]
    assert validation["nodeCount"] == 1
    assert validation["droppedDuplicateCount"] == 1
    node = result["timeline_candidates"][0]
    assert node["citation"]["sourceLineage"] == ["RULE_CANDIDATE", "LLM_ENRICHED"]


def test_validation_repairs_complete_citation():
    node = _candidate()  # no fullQuote key — must be repaired from the clause
    state = _timeline_state(
        timeline_clauses=_grounded_clauses(),
        timeline_candidates=[node],
    )

    result = te.validate_timeline_nodes(state)

    repaired = result["timeline_candidates"][0]
    full_text = state["timeline_clauses"][0]["content"]
    assert repaired["citation"]["fullQuote"] == full_text
    assert result["timeline_validation"]["repairedCitationCount"] == 1


def test_validation_flags_ungrounded_quote_without_rewriting():
    node = _candidate()
    node["citation"]["quote"] = "这句话不在原文里"
    state = _timeline_state(
        timeline_clauses=_grounded_clauses(),
        timeline_candidates=[node],
    )

    result = te.validate_timeline_nodes(state)

    repaired = result["timeline_candidates"][0]
    assert repaired["citation"]["quoteUngrounded"] is True
    assert repaired["citation"]["quote"] == "这句话不在原文里"  # untouched
    assert repaired["status"] == "NEEDS_REVIEW"
    assert result["timeline_validation"]["ungroundedQuoteCount"] == 1


def test_validation_keeps_conditional_nodes_and_checks_consistency():
    conditional = _candidate(date=None, condition="两台机组通过168小时试运后45天内",
                             confidence=0.84)
    low_conf = _candidate(clauseId=2, confidence=0.5, label="另一节点")
    state = _timeline_state(
        timeline_clauses=_grounded_clauses(),
        timeline_candidates=[conditional, low_conf],
    )

    result = te.validate_timeline_nodes(state)

    validation = result["timeline_validation"]
    assert validation["conditionalNodeCount"] == 1
    assert validation["needsReviewCount"] == 1  # low confidence → NEEDS_REVIEW


# ── coverage audit (acceptance: per-layer durations) ─────────────────────────

def test_audit_aggregates_citation_support_and_layer_durations():
    state = _timeline_state(
        timeline_candidates=[_candidate(), _candidate(clauseId=2)],
        timeline_enrichment={"returned": 2, "dropped": 1, "durationMs": 34},
        timeline_validation={"needsReviewCount": 1, "conditionalNodeCount": 0,
                             "durationMs": 56},
    )
    state["timeline_scope"]["ruleDurationMs"] = 12

    result = te.audit_timeline_coverage(state)

    audit = result["timeline_audit"]
    assert audit["totalNodes"] == 2
    assert audit["citationSupportRate"] == 1.0
    assert audit["stageDurationsMs"] == {
        "ruleLayer": 12, "llmLayer": 34, "validationLayer": 56,
    }


# ── composer (task 8) ────────────────────────────────────────────────────────

def test_compose_produces_final_only_artifact():
    state = _timeline_state(timeline_candidates=[_candidate()])
    state["timeline_audit"] = {"stageDurationsMs": {"ruleLayer": 1, "llmLayer": 2, "validationLayer": 3}}

    result = te.compose_final_timeline(state)

    artifact = result["artifact"]
    assert artifact["reportType"] == "TIMELINE_EXTRACTION_REPORT"
    assert artifact["analysisMode"] == "LLM_REVIEWED_TIMELINE"
    assert artifact["content"]["publicationStatus"] == "FINAL"
    assert artifact["content"]["ruleOnlyFallbackPublished"] is False
    assert artifact["content"]["stageDurationsMs"]["llmLayer"] == 2
    assert artifact["timelineNodeCount"] == 1


# ── persistence (task 8 / 9) ─────────────────────────────────────────────────

class _FakeCursor:
    def __init__(self):
        self.queries = []
        self.lastrowid = 100

    def execute(self, sql, params=None):
        self.queries.append((sql, params))

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class _FakeConn:
    def __init__(self):
        self._cur = _FakeCursor()
        self.committed = False

    def cursor(self):
        return self._cur

    def commit(self):
        self.committed = True

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def test_persist_replaces_non_manual_nodes_and_marks_workflow(monkeypatch):
    fake_conn = _FakeConn()
    monkeypatch.setattr(te, "new_connection", lambda: fake_conn)
    state = _timeline_state(timeline_candidates=[_candidate()])
    state["timeline_scope"].update({"caseId": 7, "documentId": 50})

    result = te.persist_final_timeline_nodes(state)

    queries = fake_conn._cur.queries
    assert "DELETE FROM contract_timeline_node" in queries[0][0]
    assert queries[0][1] == (7, 50)
    insert_sql = queries[1][0]
    insert_params = queries[1][1]
    assert "INSERT INTO contract_timeline_node" in insert_sql
    assert insert_sql.rstrip().endswith(",0)")    # manual_override literal
    assert insert_params[-2] == "AGENT_FINAL"     # source
    assert insert_params[-1] == "EXTRACTED"       # status
    assert "UPDATE contract_analysis_workflow" in queries[-1][0]
    assert queries[-1][1] == (9, 7, 50)         # run_id, case_id, document_id
    assert fake_conn.committed is True
    assert result["observations"][0]["output"]["timelineNodeCount"] == 1


def test_persist_rows_fails_fast_on_missing_required_fields():
    bad = _candidate()
    del bad["label"]
    with pytest.raises(ValueError, match="缺少必需字段"):
        te._persist_final_timeline_rows(_FakeCursor(), 1, 50, [bad])
