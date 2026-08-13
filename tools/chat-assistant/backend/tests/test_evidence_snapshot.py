"""Tests for the shared contract evidence snapshot loader (Phase 0, PRD §29.1)."""

import pytest


class ScriptedCursor:
    """Cursor that serves pre-scripted result sets, one per execute() call."""

    def __init__(self, resultsets):
        self._rs = [list(r) for r in resultsets]
        self._i = -1

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return None

    def execute(self, sql, params=None):
        self._i += 1

    def fetchone(self):
        rs = self._rs[self._i]
        return rs[0] if rs else None

    def fetchall(self):
        return self._rs[self._i]


class ScriptedConnection:
    def __init__(self, resultsets):
        self._cursor = ScriptedCursor(resultsets)

    def __enter__(self):
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


def _clause(clause_id=1, doc_id=1):
    return {
        "clauseId": clause_id,
        "documentId": doc_id,
        "clauseNumber": f"{clause_id}.1",
        "title": f"条款{clause_id}",
        "content": "条款内容",
        "clauseType": "PAYMENT",
        "pageNumber": 1,
        "startOffset": 0,
        "endOffset": 10,
    }


def _load_snapshot(monkeypatch, resultsets, **kwargs):
    from app.agent_runtime.graph.evidence_snapshot import load_contract_evidence_snapshot
    from app.agent_runtime import persistence

    monkeypatch.setattr(persistence, "_conn", lambda: ScriptedConnection(resultsets))
    return load_contract_evidence_snapshot(1, **kwargs)


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


def test_load_snapshot_selects_requested_ready_main_document(monkeypatch):
    docs = [
        _document(2, version=2, chash="h2"),          # newest MAIN READY
        _document(1, version=1, chash="h1"),          # older MAIN READY
        _document(3, doc_type="ATTACHMENT", chash="h3"),
        _document(4, status="PARSING", chash="h4"),
    ]
    snap = _load_snapshot(
        monkeypatch,
        [_case_row(), docs, [_clause()], {}, {}, []],
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
    snap = _load_snapshot(monkeypatch, [_case_row(), docs, [], {}, {}, []])
    assert snap["currentDocument"]["id"] == 2
    assert snap["clauseCount"] == 0
    # contentText must never leak into graph state by default
    assert "contentText" not in snap["currentDocument"]


def test_load_snapshot_hash_stable_and_version_sensitive(monkeypatch):
    docs = [_document(1, version=1, chash="h1")]
    base = [_case_row(), docs, [_clause()], {}, {}, []]
    a = _load_snapshot(monkeypatch, [r.copy() if isinstance(r, list) else dict(r) for r in base])
    b = _load_snapshot(monkeypatch, [r.copy() if isinstance(r, list) else dict(r) for r in base])
    assert a["snapshotHash"] == b["snapshotHash"]
    assert a["snapshotHash"]

    docs_v2 = [_document(1, version=2, chash="h1")]
    c = _load_snapshot(monkeypatch, [_case_row(), docs_v2, [_clause()], {}, {}, []])
    assert c["snapshotHash"] != a["snapshotHash"]


def test_load_snapshot_parses_intake_and_extraction_json(monkeypatch):
    intake_row = {
        "id": 9,
        "contentHash": "h1",
        "schemaVersion": "s1",
        "promptVersion": "p1",
        "model": "m",
        "confirmedAt": "2025-01-01T00:00:00",
        "validatedJson": '{"fields": {"party": "A"}}',
        "confirmedJson": '{"fields": {"party": "A"}}',
    }
    snapshot_row = {
        "id": 7, "documentId": 1, "documentVersion": 1, "contentHash": "h1",
        "status": "CONFIRMED", "snapshotHash": "sh1", "schemaVersion": "s1",
        "promptVersion": "p1", "retrievalVersion": "r1",
        "profileJson": '{"baseFields": []}', "profileHash": "ph1",
    }
    element_row = {
        "id": 11, "elementKey": "party_a", "category": "PARTY",
        "rawValue": "A公司", "normalizedValue": '{"name": "A公司"}',
        "status": "CONFIRMED", "confidence": 0.9, "source": "LLM",
        "applicable": 1, "occurrenceNo": 1, "validation": '{"ok": true}',
    }
    snap = _load_snapshot(
        monkeypatch,
        [_case_row(), [_document(1)], [_clause()], [intake_row], [snapshot_row], [element_row]],
    )
    assert snap["confirmedIntake"]["fields"] == {"party": "A"}
    assert snap["confirmedIntake"]["confirmed"] == {"fields": {"party": "A"}}
    extracted = snap["extractionSnapshot"]
    assert extracted["id"] == 7
    assert extracted["profile"] == {"baseFields": []}
    assert extracted["elements"][0]["normalizedValue"] == {"name": "A公司"}
    assert extracted["elements"][0]["validation"] == {"ok": True}


def test_load_snapshot_raises_without_ready_main_document(monkeypatch):
    docs = [_document(3, doc_type="ATTACHMENT"), _document(4, status="PARSING")]
    with pytest.raises(ValueError):
        _load_snapshot(monkeypatch, [_case_row(), docs, [], {}, {}, []])


def test_load_snapshot_raises_when_case_missing(monkeypatch):
    with pytest.raises(ValueError):
        _load_snapshot(monkeypatch, [[], [], [], {}, {}, []])
