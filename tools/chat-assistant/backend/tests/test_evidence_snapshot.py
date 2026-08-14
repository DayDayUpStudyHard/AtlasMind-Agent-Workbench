"""Tests for the unified contract evidence snapshot (PRD Phase 1, 2026-08-14).

Invariants under test (user Phase 1 spec):

* same case + version → same snapshot_hash across the four graphs (single entry)
* document version / clause content / intake / knowledge scope change → hash changes
* clause row ORDER change with same content → hash does NOT drift
* include_content_text does NOT change the hash (extraction loads with it, the
  other three graphs without it)
* missing intake / extraction → explainable ``missing_inputs`` + stable shape,
  never a silently different structure
* EvidenceContextBuilder TTL cache: same object within TTL, evict() drops it
* requested_document_id that is not a READY MAIN → ValueError, no silent fallback
* human-confirmed values enter ``fields`` via fact decisions (PRD §14-3):
  EDITED/USER_SUPPLIED override, CLEARED empties, ACCEPTED keeps value and
  hash, decision metadata never moves the hash, legacy confirmed_json
  direct-key values overlay when no decisions exist
"""

import asyncio

import pytest


class ScriptedCursor:
    """Serves one scripted result set per execute() call, in call order.

    The previous positional cursor broke when an optional query (elements) was
    skipped. A queue is faithful to real DB behavior: each execute() consumes
    the next result set, so optional queries never shift the mapping.
    """

    def __init__(self, resultsets):
        # A bare dict is a single-row result set; a list is the rows themselves.
        self._queue = [
            [r] if isinstance(r, dict) else list(r)
            for r in resultsets
        ]
        self._current = []
        self._last_sql = ""

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return None

    def execute(self, sql, params=None):
        if not self._queue:
            raise AssertionError(f"Unexpected query beyond scripted result sets: {sql}")
        self._last_sql = sql
        self._current = self._queue.pop(0)

    def fetchone(self):
        return self._current[0] if self._current else None

    def fetchall(self):
        return self._current


class ScriptedConnection:
    def __init__(self, resultsets, call_counter=None):
        self._cursor = ScriptedCursor(resultsets)
        self._call_counter = call_counter

    def __enter__(self):
        if self._call_counter is not None:
            self._call_counter[0] += 1
        return self

    def __exit__(self, *_):
        return None

    def cursor(self):
        return self._cursor


def _case_row():
    return {
        "id": 1,
        "caseKey": "C-1",
        "title": "测试合同",
        "contractType": "SERVICE_PROCUREMENT",
        "status": "ACTIVE",
        "ourEntity": "我方",
        "counterparty": "对方",
        "ourSide": "BUYER",
        "amount": 100,
        "currency": "CNY",
        "signedDate": "2025-01-01",
        "effectiveDate": None,
        "expiryDate": None,
        "department": "d",
        "updateTime": None,
    }


def _document(doc_id, *, doc_type="MAIN", status="READY", version=1, chash="h1"):
    return {
        "id": doc_id,
        "documentType": doc_type,
        "fileName": f"f{doc_id}",
        "version": version,
        "parseStatus": status,
        "parseQuality": "HIGH",
        "contentHash": chash,
        "parseDiagnostics": "{}",
        "contentText": "full text",
    }


def _clause(clause_id=1, doc_id=1, *, number=None, title=None, content="条款内容"):
    return {
        "clauseId": clause_id,
        "documentId": doc_id,
        "clauseNumber": number if number is not None else f"{clause_id}.1",
        "title": title if title is not None else f"条款{clause_id}",
        "content": content,
        "clauseType": "PAYMENT",
        "pageNumber": 1,
        "startOffset": 0,
        "endOffset": 10,
    }


def _knowledge_row(max_version=3, count=40):
    return {"maxVersion": max_version, "cnt": count}


def _intake_row(fields=None):
    payload = {"fields": fields or {"party": "A"}}
    return {
        "id": 9,
        "contentHash": "h1",
        "schemaVersion": "s1",
        "promptVersion": "p1",
        "model": "m",
        "confirmedAt": "2025-01-01T00:00:00",
        "validatedJson": _dump(payload),
        "confirmedJson": _dump(payload),
    }


def _validated_intake_row(validated_fields, confirmed_payload=None):
    """Intake row shaped like the real extractor output: validated_json has
    {fieldKey: {value, ...}} entries, confirmed_json is the flat confirmation
    payload (empty unless given — the Java side stores the caseRequest map)."""
    payload = {
        "fields": {
            key: {"value": value, "confidence": 0.9, "citations": []}
            for key, value in validated_fields.items()
        }
    }
    return {
        "id": 9,
        "contentHash": "h1",
        "schemaVersion": "s1",
        "promptVersion": "p1",
        "model": "m",
        "confirmedAt": "2025-01-01T00:00:00",
        "validatedJson": _dump(payload),
        "confirmedJson": _dump(confirmed_payload if confirmed_payload is not None else {}),
    }


def _decision(field_key, decision_type, value):
    """One contract_intake_fact_decision row (Java recordIntakeFactDecisions)."""
    return {
        "fieldKey": field_key,
        "confirmedValue": _dump({"value": value}),
        "decisionType": decision_type,
    }


def _extraction_row():
    return {
        "id": 7, "documentId": 1, "documentVersion": 1, "contentHash": "h1",
        "status": "CONFIRMED", "snapshotHash": "sh1", "schemaVersion": "s1",
        "promptVersion": "p1", "retrievalVersion": "r1",
        "profileJson": '{"baseFields": []}', "profileHash": "ph1",
    }


def _element_row():
    return {
        "id": 11, "elementKey": "party_a", "category": "PARTY",
        "rawValue": "A公司", "normalizedValue": '{"name": "A公司"}',
        "status": "CONFIRMED", "confidence": 0.9, "source": "LLM",
        "applicable": 1, "occurrenceNo": 1, "validation": '{"ok": true}',
    }


def _dump(obj):
    import json

    return json.dumps(obj, ensure_ascii=False)


# Canonical execute() order inside EvidenceContextBuilder._build:
#   case, documents, clauses, intake, fact-decisions (only when an intake row
#   exists), extraction-snapshot, elements (only when a snapshot row exists),
#   knowledge-scope.
def _base_resultsets(*, with_intake=False, with_extraction=False, with_elements=False):
    sets = [_case_row(), [_document(1)], [_clause()]]
    if with_intake:
        sets.append([_intake_row()])
        sets.append([])  # fact decisions — none
    else:
        sets.append([])
    if with_extraction:
        sets.append([_extraction_row()])
        sets.append([_element_row()] if with_elements else [])
    else:
        sets.append([])
    sets.append([_knowledge_row()])
    return sets


def _intake_resultsets(intake_row, decisions, *, with_extraction=False):
    """Resultsets for the human-confirmation contract tests (real-shaped
    intake row + explicit fact-decision rows)."""
    sets = [_case_row(), [_document(1)], [_clause()], [intake_row], list(decisions)]
    if with_extraction:
        sets.append([_extraction_row()])
        sets.append([])  # elements
    else:
        sets.append([])
    sets.append([_knowledge_row()])
    return sets


def _load_snapshot(monkeypatch, resultsets, **kwargs):
    from app.agent_runtime.graph.evidence_snapshot import load_contract_evidence_snapshot
    from app.agent_runtime import persistence

    monkeypatch.setattr(persistence, "_conn", lambda: ScriptedConnection(resultsets))
    return load_contract_evidence_snapshot(1, **kwargs)


def _builder_with_db(monkeypatch, resultsets, ttl_seconds=60.0):
    from app.agent_runtime.graph.evidence_snapshot import EvidenceContextBuilder
    from app.agent_runtime import persistence

    calls = [0]

    def _conn():
        return ScriptedConnection(resultsets, call_counter=calls)

    monkeypatch.setattr(persistence, "_conn", _conn)
    return EvidenceContextBuilder(ttl_seconds=ttl_seconds), calls


def _copied(resultsets):
    return [r.copy() if isinstance(r, list) else dict(r) for r in resultsets]


# ────────────────────────── compact_clause normalization ────────────────────


def test_compact_clause_normalizes_camel_and_snake_rows():
    from app.agent_runtime.graph.evidence_snapshot import compact_clause

    camel = compact_clause({
        "sourceId": "X", "clauseId": 3, "documentId": 1, "clauseNumber": "1.2",
        "title": "标题", "clauseType": "PAYMENT", "content": "c" * 2000,
        "pageNumber": 2, "startOffset": 0, "endOffset": 100,
    })
    assert camel["clauseId"] == 3
    assert camel["clauseText"] == "c" * 2000
    assert len(camel["snippet"]) == 1800

    snake = compact_clause({
        "id": 5, "document_id": 2, "clause_number": "3", "content": "x",
        "title": "snake", "page_number": 4,
    })
    assert snake["sourceId"] == "CONTRACT_CLAUSE:5"
    assert snake["clauseId"] == 5
    assert snake["documentId"] == 2
    assert snake["clauseType"] == "OTHER"


# ────────────────────────── main-document selection ─────────────────────────


def test_load_snapshot_selects_requested_ready_main_document(monkeypatch):
    docs = [
        _document(2, version=2, chash="h2"),          # newest MAIN READY
        _document(1, version=1, chash="h1"),          # older MAIN READY
        _document(3, doc_type="ATTACHMENT", chash="h3"),
        _document(4, status="PARSING", chash="h4"),
    ]
    snap = _load_snapshot(
        monkeypatch,
        [_case_row(), docs, [_clause()], [], [], [_knowledge_row()]],
        requested_document_id=1,
    )
    assert snap["currentDocument"]["id"] == 1
    assert snap["clauseCount"] == 1
    assert snap["clauses"][0]["clauseId"] == 1


def test_load_snapshot_prefers_newest_ready_main_without_request(monkeypatch):
    docs = [
        _document(2, version=2, chash="h2"),
        _document(1, version=1, chash="h1"),
    ]
    snap = _load_snapshot(monkeypatch, [_case_row(), docs, [], [], [], [_knowledge_row()]])
    assert snap["currentDocument"]["id"] == 2
    assert snap["clauseCount"] == 0
    # contentText must never leak into graph state by default
    assert "contentText" not in snap["currentDocument"]


def test_load_snapshot_raises_when_requested_document_not_ready_main(monkeypatch):
    docs = [
        _document(1, version=1, chash="h1"),
        _document(3, doc_type="ATTACHMENT", chash="h3"),
        _document(4, status="PARSING", chash="h4"),
    ]
    with pytest.raises(ValueError, match="not a READY main document"):
        _load_snapshot(monkeypatch, [_case_row(), docs, [], [], [], [_knowledge_row()]],
                       requested_document_id=4)


def test_load_snapshot_raises_without_ready_main_document(monkeypatch):
    docs = [_document(3, doc_type="ATTACHMENT"), _document(4, status="PARSING")]
    with pytest.raises(ValueError):
        _load_snapshot(monkeypatch, [_case_row(), docs])


def test_load_snapshot_raises_when_case_missing(monkeypatch):
    with pytest.raises(ValueError):
        _load_snapshot(monkeypatch, [[]])


# ────────────────────────── hash invariants ─────────────────────────────────


def test_hash_stable_across_calls_and_include_content_text(monkeypatch):
    """Same case+version → same hash: across calls AND across the loading
    modes the four graphs actually use (review/timeline/fulfillment load
    without content text; extraction loads with it)."""
    base = _base_resultsets(with_intake=True, with_extraction=True, with_elements=True)
    a = _load_snapshot(monkeypatch, _copied(base))
    b = _load_snapshot(monkeypatch, _copied(base))
    c = _load_snapshot(monkeypatch, _copied(base), include_content_text=True)
    assert a["snapshot_hash"] == b["snapshot_hash"] == c["snapshot_hash"]
    assert a["snapshot_hash"]


def test_hash_sensitive_to_document_version(monkeypatch):
    a = _load_snapshot(monkeypatch, _base_resultsets())
    docs_v2 = [_case_row(), [_document(1, version=2, chash="h1")], [_clause()], [], [], [_knowledge_row()]]
    b = _load_snapshot(monkeypatch, docs_v2)
    assert a["snapshot_hash"] != b["snapshot_hash"]


def test_hash_insensitive_to_clause_row_order(monkeypatch):
    """Clause row order changes with the same content → hash must NOT drift."""
    ordered = [_clause(1, number="1.1", content="a"), _clause(2, number="2.1", content="b")]
    shuffled = [_clause(2, number="2.1", content="b"), _clause(1, number="1.1", content="a")]
    a = _load_snapshot(monkeypatch, [_case_row(), [_document(1)], ordered, [], [], [_knowledge_row()]])
    b = _load_snapshot(monkeypatch, [_case_row(), [_document(1)], shuffled, [], [], [_knowledge_row()]])
    assert a["snapshot_hash"] == b["snapshot_hash"]


def test_hash_sensitive_to_clause_content(monkeypatch):
    a = _load_snapshot(monkeypatch, _base_resultsets())
    b = _load_snapshot(monkeypatch,
                       [_case_row(), [_document(1)], [_clause(content="改了内容")], [], [], [_knowledge_row()]])
    assert a["snapshot_hash"] != b["snapshot_hash"]


def test_hash_sensitive_to_confirmed_intake(monkeypatch):
    a = _load_snapshot(monkeypatch, _base_resultsets(with_intake=True))
    changed = _base_resultsets(with_intake=True)
    changed[3] = [_intake_row(fields={"party": "B"})]
    b = _load_snapshot(monkeypatch, changed)
    assert a["snapshot_hash"] != b["snapshot_hash"]


def test_hash_sensitive_to_knowledge_scope(monkeypatch):
    a = _load_snapshot(monkeypatch, _base_resultsets())
    changed = _base_resultsets()
    changed[-1] = [_knowledge_row(max_version=4, count=41)]
    b = _load_snapshot(monkeypatch, changed)
    assert a["snapshot_hash"] != b["snapshot_hash"]


def test_hash_sensitive_to_extraction_snapshot(monkeypatch):
    a = _load_snapshot(monkeypatch, _base_resultsets())
    b = _load_snapshot(monkeypatch, _base_resultsets(with_extraction=True))
    assert a["snapshot_hash"] != b["snapshot_hash"]


# ────────────────── missing inputs are explainable, shape stable ────────────


def test_missing_intake_and_extraction_are_explicit(monkeypatch):
    """No intake / no extraction snapshot → canonical keys stay present with
    empty shape and ``missing_inputs`` names exactly what is absent — no
    silent structural degradation (user Phase 1 test requirement)."""
    snap = _load_snapshot(monkeypatch, _base_resultsets())
    assert snap["missing_inputs"] == [
        "confirmed_intake_fields",
        "latest_confirmed_extraction_snapshot",
    ]
    assert snap["confirmed_intake_fields"] == {}
    assert snap["latest_confirmed_extraction_snapshot"] == {}
    assert snap["clause_catalog"] == [_clause_catalog_entry(_clause())]
    assert snap["knowledge_scope"]["standardClauseVersion"] == 3
    # every canonical key exists even in the degraded case
    for key in (
        "snapshot_hash", "case_id", "document_id", "document_version",
        "content_hash", "main_document_parser", "quality_diagnostics",
        "confirmed_intake_fields", "latest_confirmed_extraction_snapshot",
        "clause_catalog", "clauses", "knowledge_scope", "missing_inputs",
    ):
        assert key in snap, f"canonical key {key} missing"


def _clause_catalog_entry(clause):
    return {
        "clauseId": clause["clauseId"],
        "documentId": clause["documentId"],
        "clauseNumber": clause["clauseNumber"],
        "title": clause["title"],
        "clauseType": clause["clauseType"],
        "pageNumber": clause["pageNumber"],
        "charCount": len(clause["content"]),
    }


def test_missing_inputs_partial_when_intake_exists(monkeypatch):
    snap = _load_snapshot(monkeypatch, _base_resultsets(with_intake=True))
    assert snap["missing_inputs"] == ["latest_confirmed_extraction_snapshot"]
    assert snap["confirmed_intake_fields"]["fields"] == {"party": "A"}


# ─────────────── the four graphs all enter through the same loader ──────────


def test_four_graphs_observe_same_snapshot_hash(monkeypatch):
    """Review / timeline / fulfillment run load_run_context (no content text);
    extraction runs load_extraction_context (with content text). All four must
    observe the same snapshot_hash for the same case + version."""
    from app.agent_runtime.graph.contract_extraction import load_extraction_context
    from app.agent_runtime.graph.nodes import context as context_nodes

    base = _base_resultsets(with_intake=True, with_extraction=True, with_elements=True)
    expected = _load_snapshot(monkeypatch, _copied(base))["snapshot_hash"]

    def reset_db():
        from app.agent_runtime import persistence

        monkeypatch.setattr(
            persistence, "_conn",
            lambda: ScriptedConnection(_copied(base)),
        )

    # review / timeline / fulfillment: same node, no content text
    reset_db()
    review_state = asyncio.run(context_nodes.load_run_context({
        "run_id": 1, "subject_id": 1, "task_input": {}, "state_revision": 0,
    }))
    assert review_state["evidence_snapshot"]["snapshot_hash"] == expected
    assert review_state["analysis_workflow"]["evidenceSnapshotHash"] == expected
    assert review_state["analysis_workflow"]["documentVersion"] == 1

    # extraction: loads with include_content_text=True, must still agree
    reset_db()
    extraction_state = load_extraction_context({
        "run_id": 2, "subject_id": 1, "task_input": {}, "state_revision": 0,
    })
    assert extraction_state["evidence_snapshot"]["snapshot_hash"] == expected
    assert extraction_state["extraction_context"]["evidenceSnapshotHash"] == expected


def test_state_copy_drops_bulk_clauses_but_keeps_identity(monkeypatch):
    from app.agent_runtime.graph.evidence_snapshot import state_copy_of_snapshot

    snap = _load_snapshot(monkeypatch, _base_resultsets(with_intake=True))
    state_view = state_copy_of_snapshot(snap)
    # bulk fields are stripped to keep checkpoints small
    assert "clauses" not in state_view
    assert "case" not in state_view
    assert "documents" not in state_view
    assert "currentDocument" not in state_view
    # identity and evidence metadata survive
    assert state_view["snapshot_hash"] == snap["snapshot_hash"]
    assert state_view["document_version"] == 1
    assert state_view["clause_catalog"]
    assert state_view["confirmed_intake_fields"]["fields"] == {"party": "A"}


# ────────────────────────── builder TTL cache ───────────────────────────────


def test_builder_cache_serves_same_object_within_ttl(monkeypatch):
    resultsets = _base_resultsets()
    builder, calls = _builder_with_db(monkeypatch, resultsets, ttl_seconds=60.0)
    first = builder.build(1)
    second = builder.build(1)
    assert first is second
    assert calls[0] == 1  # DB touched exactly once


def test_builder_cache_evict_drops_one_case(monkeypatch):
    resultsets = _base_resultsets()
    builder, calls = _builder_with_db(monkeypatch, resultsets, ttl_seconds=60.0)
    first = builder.build(1)
    builder.evict(1)
    second = builder.build(1)
    assert first is not second
    assert calls[0] == 2


def test_builder_cache_clear_drops_everything(monkeypatch):
    resultsets = _base_resultsets()
    builder, calls = _builder_with_db(monkeypatch, resultsets, ttl_seconds=60.0)
    builder.build(1)
    builder.clear()
    builder.build(1)
    assert calls[0] == 2


def test_builder_cache_disabled_by_default(monkeypatch):
    from app.agent_runtime.graph.evidence_snapshot import EvidenceContextBuilder

    resultsets = _base_resultsets()
    builder = EvidenceContextBuilder()  # ttl_seconds=0 → caching OFF
    from app.agent_runtime import persistence

    calls = [0]
    monkeypatch.setattr(
        persistence, "_conn",
        lambda: ScriptedConnection(resultsets, call_counter=calls),
    )
    a = builder.build(1)
    b = builder.build(1)
    assert a is not b
    assert calls[0] == 2


# ────────────────────────── intake / extraction parsing ─────────────────────


def test_load_snapshot_parses_intake_and_extraction_json(monkeypatch):
    resultsets = [
        _case_row(),
        [_document(1)],
        [_clause()],
        [_intake_row()],
        [],  # fact decisions — none
        [_extraction_row()],
        [_element_row()],
        [_knowledge_row()],
    ]
    snap = _load_snapshot(monkeypatch, resultsets)
    assert snap["confirmedIntake"]["fields"] == {"party": "A"}
    assert snap["confirmedIntake"]["confirmed"] == {"fields": {"party": "A"}}
    extracted = snap["extractionSnapshot"]
    assert extracted["id"] == 7
    assert extracted["profile"] == {"baseFields": []}
    assert extracted["elements"][0]["normalizedValue"] == {"name": "A公司"}
    assert extracted["elements"][0]["validation"] == {"ok": True}
    # canonical keys mirror the aliases from the same load
    assert snap["confirmed_intake_fields"]["fields"] == {"party": "A"}
    assert snap["latest_confirmed_extraction_snapshot"]["id"] == 7
    assert snap["missing_inputs"] == []


# ───────────── human-confirmed values enter the snapshot (PRD §14-3) ────────


def test_edited_decision_overrides_field_and_moves_hash(monkeypatch):
    """A human EDITED value replaces the AI-proposed value in the canonical
    ``fields`` view and changes the snapshot hash (证据内容变了)."""
    validated = {"amount": 100, "currency": "CNY"}
    before = _load_snapshot(monkeypatch, _intake_resultsets(_validated_intake_row(validated), []))
    after = _load_snapshot(monkeypatch, _intake_resultsets(
        _validated_intake_row(validated), [_decision("amount", "EDITED", 999)]))

    assert before["confirmed_intake_fields"]["fields"]["amount"]["value"] == 100
    edited = after["confirmed_intake_fields"]["fields"]["amount"]
    assert edited["value"] == 999
    assert edited["decisionType"] == "EDITED"
    assert edited["humanConfirmed"] is True
    assert edited["confidence"] == 0.9  # proposal metadata survives the overlay
    assert after["confirmed_intake_fields"]["fields"]["currency"]["value"] == "CNY"
    assert before["snapshot_hash"] != after["snapshot_hash"]


def test_accepted_decision_stamps_without_moving_hash(monkeypatch):
    """ACCEPTED confirmation keeps the proposed value; the decision stamp is
    metadata only and must not churn the hash (hash = evidence content, not
    the event stream)."""
    validated = {"amount": 100}
    before = _load_snapshot(monkeypatch, _intake_resultsets(_validated_intake_row(validated), []))
    after = _load_snapshot(monkeypatch, _intake_resultsets(
        _validated_intake_row(validated), [_decision("amount", "ACCEPTED", 100)]))

    accepted = after["confirmed_intake_fields"]["fields"]["amount"]
    assert accepted["value"] == 100
    assert accepted["decisionType"] == "ACCEPTED"
    assert accepted["humanConfirmed"] is True
    assert before["snapshot_hash"] == after["snapshot_hash"]


def test_user_supplied_decision_fills_empty_field(monkeypatch):
    """USER_SUPPLIED fills a field the model left empty; the new value enters
    the hash."""
    before = _load_snapshot(monkeypatch, _intake_resultsets(_validated_intake_row({"amount": None}), []))
    after = _load_snapshot(monkeypatch, _intake_resultsets(
        _validated_intake_row({"amount": None}), [_decision("amount", "USER_SUPPLIED", 500)]))

    assert before["confirmed_intake_fields"]["fields"]["amount"]["value"] is None
    supplied = after["confirmed_intake_fields"]["fields"]["amount"]
    assert supplied["value"] == 500
    assert supplied["decisionType"] == "USER_SUPPLIED"
    assert before["snapshot_hash"] != after["snapshot_hash"]


def test_cleared_decision_empties_field(monkeypatch):
    """CLEARED is the human's explicit 'this is empty' — value becomes None
    (not silently dropped, not kept as the proposal)."""
    validated = {"amount": 100}
    before = _load_snapshot(monkeypatch, _intake_resultsets(_validated_intake_row(validated), []))
    after = _load_snapshot(monkeypatch, _intake_resultsets(
        _validated_intake_row(validated), [_decision("amount", "CLEARED", None)]))

    cleared = after["confirmed_intake_fields"]["fields"]["amount"]
    assert cleared["value"] is None
    assert cleared["decisionType"] == "CLEARED"
    assert cleared["humanConfirmed"] is True
    assert before["snapshot_hash"] != after["snapshot_hash"]


def test_legacy_confirmed_json_overlays_matching_field_keys(monkeypatch):
    """A CONFIRMED intake without fact-decision rows (legacy) takes direct-key
    values from the flat confirmed_json payload — but only for keys already in
    the field space (title ≠ contractTitle, so no fragile mapping)."""
    intake = _validated_intake_row(
        {"amount": None, "currency": None, "contractTitle": "AI提的标题"},
        confirmed_payload={"amount": 888, "currency": "USD", "title": "人工标题"},
    )
    snap = _load_snapshot(monkeypatch, _intake_resultsets(intake, []))
    fields = snap["confirmed_intake_fields"]["fields"]
    assert fields["amount"]["value"] == 888
    assert fields["amount"]["decisionType"] == "LEGACY_CONFIRMED"
    assert fields["currency"]["value"] == "USD"
    assert fields["contractTitle"]["value"] == "AI提的标题"  # 无同键可回退，保留提议值
    assert "title" not in fields
    # raw confirmed payload stays available under its own key, unmangled
    assert snap["confirmed_intake_fields"]["confirmed"] == {
        "amount": 888, "currency": "USD", "title": "人工标题",
    }


def test_confirmed_payload_passthrough_alongside_decisions(monkeypatch):
    """``confirmed`` keeps the raw confirmed_json payload even when per-field
    decisions exist — consumers needing the whole confirmation record find it
    unmangled next to the merged ``fields``."""
    snap = _load_snapshot(monkeypatch, _intake_resultsets(
        _validated_intake_row({"amount": 100}, confirmed_payload={"amount": 999}),
        [_decision("amount", "EDITED", 999)]))
    assert snap["confirmed_intake_fields"]["confirmed"] == {"amount": 999}
    assert snap["confirmed_intake_fields"]["fields"]["amount"]["value"] == 999
