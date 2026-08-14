"""PRD Phase 5: 迁移合同要素提取 — dynamic pack planning, fixed
base-identity WorkUnit, deterministic normalization, snapshot-hash binding,
conflict candidates, field-level rerun scope and profile override guard."""

from app.agent_runtime.graph import contract_extraction as ce


def _extraction_context(**overrides):
    context = {
        "case": {
            "title": "勘察设计合同",
            "contractType": "SERVICE_PROCUREMENT",
            "ourEntity": "江西省电力设计院",
            "counterparty": "华能安源发电有限责任公司",
            "ourSide": "B",
            "amount": 18600000,
            "currency": "CNY",
            "signedDate": "2012-12-12",
            "effectiveDate": "2013-01-01",
            "expiryDate": "2013-12-31",
        },
        "document": {"id": 50, "version": 1, "contentHash": "abc"},
        "clauses": [
            {
                "clauseId": 7,
                "clauseNumber": "1.2",
                "title": "合同价款",
                "clauseText": "本合同总价为人民币壹仟捌佰陆拾万元整（¥1860万元）。",
                "sourceId": "CONTRACT_CLAUSE:7",
                "documentId": 50,
                "pageNumber": 12,
            }
        ],
        "confirmedIntake": {
            "id": 28,
            "fields": {
                "amount": {
                    "value": 18600000,
                    "source": "LLM",
                    "confidence": 0.95,
                    "citations": [{"quote": "本合同总价为人民币壹仟捌佰陆拾万元整（¥1860万元）"}],
                }
            },
        },
        "contentHash": "abc",
        "evidenceSnapshotHash": "snap-abc123",
        "clauseCount": 1,
    }
    context.update(overrides)
    return context


# ── dynamic pack planning (task 2) ───────────────────────────────────────────

class _PlanningLLM:
    def __init__(self, raw):
        self._raw = raw
        self.model = "test-planning-model"

    def plan_contract_elements(self, case, clauses, run_id=0):
        return self._raw


class _FailingLLM:
    def plan_contract_elements(self, case, clauses, run_id=0):
        raise RuntimeError("planning unavailable")


def test_planned_packs_normalized_and_base_keys_excluded():
    raw = {
        "contractTypeRefined": "ENGINEERING_DESIGN",
        "subjectSummary": "为某电厂提供勘察设计服务",
        "rationale": "本合同为勘察设计服务合同",
        "packs": [
            {"packKey": "design_scope", "packName": "设计范围",
             "elementKeys": ["scope_items", "design_standards", "effective_date"],
             "queries": ["设计范围 设计标准"]},
            {"packKey": "delivery_acceptance", "packName": "交付与验收",
             "elementKeys": ["deliverables", "acceptance_criteria"],
             "queries": ["交付成果 验收标准"]},
        ],
    }
    packs = ce._normalize_planned_packs(raw)

    assert len(packs) == 2
    assert packs[0]["packKey"] == "design_scope"
    assert "effective_date" not in packs[0]["elementKeys"]  # base identity key excluded


def test_planned_packs_rejected_when_too_few_or_duplicated():
    assert ce._normalize_planned_packs({"packs": [{"packKey": "only", "packName": "x",
                                                   "elementKeys": ["a"], "queries": ["q"]}]}) is None
    assert ce._normalize_planned_packs({"packs": [
        {"packKey": "dup", "packName": "x", "elementKeys": ["a"], "queries": ["q"]},
        {"packKey": "dup", "packName": "y", "elementKeys": ["b"], "queries": ["r"]},
    ]}) is None
    assert ce._normalize_planned_packs({"packs": "not-a-list"}) is None


def test_plan_element_packs_llm_failure_falls_back_to_static(monkeypatch):
    packs, meta = ce._plan_element_packs(_extraction_context(), 9, llm_service=_FailingLLM())

    assert meta["source"] == "STATIC_FALLBACK"
    assert [pack["packKey"] for pack in packs] == [pack["packKey"] for pack in ce.ELEMENT_PACKS]


def test_plan_element_packs_valid_llm_plan_used(monkeypatch):
    raw = {
        "contractTypeRefined": "ENGINEERING_DESIGN",
        "subjectSummary": "勘察设计",
        "rationale": "服务类合同",
        "packs": [
            {"packKey": "design_scope", "packName": "设计范围",
             "elementKeys": ["scope_items"], "queries": ["设计范围"]},
            {"packKey": "delivery_acceptance", "packName": "交付与验收",
             "elementKeys": ["deliverables"], "queries": ["交付成果"]},
        ],
    }
    packs, meta = ce._plan_element_packs(_extraction_context(), 9, llm_service=_PlanningLLM(raw))

    assert meta["source"] == "LLM_PLANNED"
    assert meta["contractTypeRefined"] == "ENGINEERING_DESIGN"
    assert [pack["packKey"] for pack in packs] == ["design_scope", "delivery_acceptance"]


def test_select_element_packs_declares_base_identity_work_unit(monkeypatch):
    monkeypatch.setattr(ce, "_previous_settled_elements", lambda case_id, document_id: ([], None))
    # Force static planning without hitting LLMService by monkeypatching the planner.
    monkeypatch.setattr(ce, "_plan_element_packs", lambda context, run_id, llm_service=None: (
        [dict(pack) for pack in ce.ELEMENT_PACKS], {"source": "STATIC_FALLBACK", "contractTypeRefined": "X", "subjectSummary": "", "rationale": ""},
    ))

    result = ce.select_element_packs({
        "subject_id": 1, "run_id": 9, "state_revision": 0,
        "extraction_context": _extraction_context(),
    })

    unit = result["plan"]["baseIdentityWorkUnit"]
    assert unit["work_unit_id"] == "base_identity_fields"
    assert unit["applicability"] == "ALWAYS"
    assert "deterministic_money_parse" in unit["required_checks"]
    assert result["plan"]["rerun"] is None


# ── field-level rerun scope (task 6) ─────────────────────────────────────────

def test_select_element_packs_carries_settled_and_filters_packs(monkeypatch):
    settled = [{
        "elementKey": "payment_terms", "status": "CONFIRMED", "confidence": 1.0,
        "validation": {},
    }]
    monkeypatch.setattr(ce, "_previous_settled_elements", lambda case_id, document_id: (settled, 42))
    monkeypatch.setattr(ce, "_plan_element_packs", lambda context, run_id: (
        [dict(pack) for pack in ce.ELEMENT_PACKS], {"source": "STATIC_FALLBACK", "contractTypeRefined": "X", "subjectSummary": "", "rationale": ""},
    ))

    result = ce.select_element_packs({
        "subject_id": 1, "run_id": 9, "state_revision": 0,
        "extraction_context": _extraction_context(),
    })

    rerun = result["plan"]["rerun"]
    assert rerun["baseSnapshotId"] == 42
    assert "payment_terms" in rerun["carriedElementKeys"]
    assert "financial_terms" in rerun["skippedPacks"]
    assert result["carried_elements"][0]["validation"]["carriedFromSnapshotId"] == 42
    # financial_terms only contained payment_terms → fully settled → skipped.
    assert "financial_terms" not in {pack["packKey"] for pack in result["element_packs"]}


def test_validate_extracted_elements_merges_carried_without_revalidation():
    carried = [{
        "elementKey": "payment_terms", "status": "CONFIRMED", "confidence": 1.0,
        "citations": [{"sourceId": "CONTRACT_CLAUSE:999", "quote": "旧快照引用"}],
        "validation": {"carriedFromSnapshotId": 42},
    }]
    state = {
        "run_id": 9, "state_revision": 0,
        "extraction_context": _extraction_context(),
        "element_evidence": {},
        "extracted_elements": [{
            "elementKey": "delivery_obligations", "status": "EXTRACTED", "confidence": 0.9,
            "valueType": "TEXT", "normalizedValue": {},
            "citations": [{"sourceId": "CONTRACT_CLAUSE:7", "quote": "本合同总价"}],
        }],
        "carried_elements": carried,
    }

    result = ce.validate_extracted_elements(state)

    assert len(result["extracted_elements"]) == 2
    carried_item = result["extracted_elements"][1]
    assert carried_item["citations"][0]["quote"] == "旧快照引用"  # not dropped
    assert result["extraction_validation"]["carriedFromPrevious"] == 1
    assert result["extraction_validation"]["total"] == 2


# ── snapshot-hash binding + typed validation (tasks 3/4) ─────────────────────

def test_validate_binds_snapshot_hash_and_flags_bad_money(monkeypatch):
    state = {
        "run_id": 9, "state_revision": 0,
        "extraction_context": _extraction_context(),
        "element_evidence": {"financial_terms": [{
            "sourceId": "CONTRACT_CLAUSE:7", "clauseId": 7, "documentId": 50, "pageNumber": 12,
            "clauseText": "本合同总价为人民币壹仟捌佰陆拾万元整（¥1860万元）。",
        }]},
        "extracted_elements": [
            {
                "elementKey": "payment_terms", "status": "EXTRACTED", "confidence": 0.9,
                "valueType": "MONEY",
                "normalizedValue": {"amount": "按时支付", "currency": "CNY"},
                "citations": [{"sourceId": "CONTRACT_CLAUSE:7", "quote": "本合同总价"}],
            },
            {
                "elementKey": "delivery_obligations", "status": "EXTRACTED", "confidence": 0.9,
                "valueType": "TEXT", "normalizedValue": {},
                "citations": [{"sourceId": "CONTRACT_CLAUSE:7", "quote": "本合同总价"}],
            },
        ],
    }

    result = ce.validate_extracted_elements(state)
    money, text = result["extracted_elements"]

    assert money["status"] == "NEEDS_REVIEW"
    assert "typedIssues" in money["validation"]
    assert money["validation"]["evidenceSnapshotHash"] == "snap-abc123"
    assert money["citations"][0]["snapshotHash"] == "snap-abc123"
    assert text["status"] == "EXTRACTED"
    assert result["extraction_validation"]["typedValidationFlaggedCount"] == 1


# ── base identity WorkUnit (task 1) ──────────────────────────────────────────

def test_base_identity_node_runs_deterministic_normalization():
    result = ce.extract_base_identity_fields({
        "run_id": 9, "state_revision": 0,
        "extraction_context": _extraction_context(),
    })

    fields = {field["key"]: field for field in result["base_identity_fields"]}
    assert fields["amount"]["value"] == 18600000
    assert fields["amount"]["normalizedValue"]["amount"] is not None
    assert fields["amount"]["validation"]["deterministic"] is True
    assert fields["expiryDate"]["normalizedValue"]["date"] == "2013-12-31"
    assert fields["partyA"]["value"] == "华能安源发电有限责任公司"
    assert fields["ourSide"]["value"] == "B"
    observation = result["observations"][0]
    assert observation["arguments"]["workUnitId"] == "base_identity_fields"
    assert observation["output"]["fieldCount"] == len(fields)


def test_base_identity_flags_deterministically_unparseable_values():
    context = _extraction_context()
    context["case"]["expiryDate"] = "项目结束时"
    context["case"]["amount"] = "按实结算"

    fields = {field["key"]: field for field in ce._canonical_base_fields(context)}

    assert fields["expiryDate"]["validation"]["deterministic"] is False
    assert "确定性解析失败" in fields["expiryDate"]["validation"]["issues"][0]
    assert fields["amount"]["validation"]["deterministic"] is False


# ── coverage auditor ─────────────────────────────────────────────────────────

def test_coverage_audit_reports_support_and_binding():
    result = ce.audit_element_coverage({
        "run_id": 9, "state_revision": 0,
        "extraction_context": _extraction_context(),
        "extracted_elements": [
            {"elementKey": "a", "citations": [{"x": 1}], "validation": {"evidenceSnapshotHash": "snap-abc123"}},
            {"elementKey": "b", "citations": [], "validation": {"evidenceSnapshotHash": "snap-abc123"}},
            {"elementKey": "c", "citations": [{"x": 1}], "validation": {"evidenceSnapshotHash": "snap-abc123"}, "foo": 1},
        ],
    })

    audit = result["element_coverage_audit"]
    assert audit["totalElements"] == 3
    assert audit["citedElements"] == 2
    assert audit["uncitedElements"] == ["b"]
    assert audit["citationSupportRate"] == round(2 / 3, 4)
    assert audit["snapshotHashBoundElements"] == 3


# ── profile guard (task 8) ───────────────────────────────────────────────────

def test_profile_group_field_colliding_with_base_key_is_dropped():
    context = _extraction_context()
    raw = {
        "profile": {
            "title": "合同画像",
            "contractType": "SERVICE_PROCUREMENT",
            "groups": [
                {
                    "groupKey": "financial",
                    "label": "价款",
                    "fields": [
                        {"key": "amount", "label": "合同金额", "value": 1,
                         "valueType": "MONEY", "confidence": 0.99,
                         "citations": [{"sourceId": "CONTRACT_CLAUSE:7", "quote": "本合同总价"}]},
                        {"key": "payment_stage", "label": "付款节点", "value": "验收后30日",
                         "valueType": "TEXT", "confidence": 0.9,
                         "citations": [{"sourceId": "CONTRACT_CLAUSE:7", "quote": "本合同总价"}]},
                    ],
                }
            ],
        }
    }

    profile, validation = ce.normalize_contract_profile(raw, context, [], context["clauses"])

    group_keys = [field["key"] for field in profile["groups"][0]["fields"]]
    assert "amount" not in group_keys  # base fact key cannot be rewritten
    assert "payment_stage" in group_keys
    base_amount = {field["key"]: field for field in profile["baseFields"]}["amount"]
    assert base_amount["value"] == 18600000


def test_profile_accepts_precomputed_base_fields():
    context = _extraction_context()
    base_fields = ce._canonical_base_fields(context)
    raw = {"profile": {"title": "x", "contractType": "OTHER", "groups": []}}

    profile, validation = ce.normalize_contract_profile(
        raw, context, [], context["clauses"], base_fields=base_fields
    )

    assert validation["canonicalBaseFieldCount"] == len(base_fields)
    assert profile["baseFields"] == base_fields


# ── conflict candidates (task 5) ─────────────────────────────────────────────

def test_top_candidate_by_key_picks_highest_confidence():
    elements = [
        {"elementKey": "payment_terms", "confidence": 0.4, "occurrenceNo": 1},
        {"elementKey": "payment_terms", "confidence": 0.95, "occurrenceNo": 2},
        {"elementKey": "liability_terms", "confidence": 0.8, "occurrenceNo": 1},
    ]

    best = ce._top_candidates_by_key(elements)

    assert best["payment_terms"] is elements[1]
    assert best["liability_terms"] is elements[2]


def test_top_candidate_by_key_distinct_keys_all_selected():
    elements = [
        {"elementKey": "a", "confidence": 0.3},
        {"elementKey": "b", "confidence": 0.2},
    ]

    best = ce._top_candidates_by_key(elements)

    assert best["a"] is elements[0]
    assert best["b"] is elements[1]


# ── TaskSpec (architecture migration) ───────────────────────────────────────

def test_extraction_spec_compiles_via_common_builder():
    from app.agent_runtime.harness.graph_builder import build_task_graph

    graph = build_task_graph(ce.CONTRACT_EXTRACTION_SPEC)

    nodes = set(graph.get_graph().nodes.keys())
    assert "load_extraction_context" in nodes
    assert "select_element_packs" in nodes
    assert "extract_base_identity_fields" in nodes
    assert "audit_element_coverage" in nodes
    assert "persist_extraction_snapshot" in nodes
    assert ce.CONTRACT_EXTRACTION_SPEC.human_gate is None


def test_extraction_spec_stage_order_follows_lifecycle():
    stages = ce.CONTRACT_EXTRACTION_SPEC.stages
    assert stages.index("extract_base_identity_fields") < stages.index("extract_element_batches")
    assert stages.index("validate_extracted_elements") < stages.index("audit_element_coverage")
    assert stages[-1] == "persist_extraction_snapshot"


# ── legacy async entry converged ─────────────────────────────────────────────

def test_legacy_run_async_delegates_to_harness(monkeypatch):
    captured = {}
    monkeypatch.setattr(
        "app.agent_runtime.harness.retrieval.run_async",
        lambda awaitable: captured.update({"called": True}) or "harness-result",
    )

    result = ce._run_async(object())

    assert result == "harness-result"
    assert captured["called"] is True


# ── graph state schema (regression: LangGraph drops undeclared keys) ─────────

def test_graph_state_schema_keeps_cross_node_channels():
    """LangGraph silently drops node-output keys that are not declared on the
    state schema — direct node-call tests cannot catch that. Every channel the
    Phase 5/6 nodes emit must be declared, and must survive a compiled run."""
    from langgraph.graph import END, START, StateGraph

    from app.agent_runtime.graph.state import BaseGraphState

    emitted_keys = {
        "base_identity_fields", "carried_elements", "element_coverage_audit",
        "timeline_scope", "timeline_clauses", "timeline_candidates",
        "timeline_enrichment", "timeline_validation", "timeline_audit",
    }
    assert emitted_keys <= set(BaseGraphState.__annotations__)

    builder = StateGraph(BaseGraphState)

    def emit(state):
        return {
            "base_identity_fields": [{"key": "partyA"}],
            "carried_elements": [{"elementKey": "payment_terms"}],
            "element_coverage_audit": {"totalElements": 1},
            "timeline_candidates": [{"label": "验收"}],
        }

    def read(state):
        assert state.get("carried_elements") == [{"elementKey": "payment_terms"}]
        assert state.get("base_identity_fields") == [{"key": "partyA"}]
        assert state.get("element_coverage_audit") == {"totalElements": 1}
        assert state.get("timeline_candidates") == [{"label": "验收"}]
        return {}

    builder.add_node("emit", emit)
    builder.add_node("read", read)
    builder.add_edge(START, "emit")
    builder.add_edge("emit", "read")
    builder.add_edge("read", END)
    builder.compile().invoke({})
