from app.agent_runtime.evidence import citation_support, quote_supported, summarize_document_quality
from app.agent_runtime.contract_store import _fuse_contract_retrieval, _fuse_policy_retrieval
from app.agent_runtime.graph.nodes.artifact import prepare_human_review
from app.agent_runtime.graph.nodes.validation import _validate_one


def test_quote_must_be_contiguous_source_text():
    source = "乙方应在合同签订后10日内提交履约保函正本。"
    assert quote_supported("合同签订后10日内提交履约保函", source)
    assert not quote_supported("乙方应在合同签订后30日内提交履约保函", source)


def test_citation_support_rejects_unreturned_or_non_source_quote():
    evidence = {
        "CONTRACT_CLAUSE:1": {
            "sourceId": "CONTRACT_CLAUSE:1",
            "sourceType": "CONTRACT_CLAUSE",
            "clauseText": "甲方应在验收合格后十日内付款。",
            "contentHash": "abc",
        }
    }
    supported = citation_support(
        "CONTRACT_CLAUSE:1",
        {"snippet": "验收合格后十日内付款"},
        evidence,
    )
    unsupported = citation_support(
        "CONTRACT_CLAUSE:1",
        {"snippet": "验收合格后一年内付款"},
        evidence,
    )
    missing = citation_support("CONTRACT_CLAUSE:9", None, evidence)
    assert supported["supported"] is True
    assert unsupported["status"] == "UNSUPPORTED"
    assert missing["status"] == "MISSING_RETRIEVAL"


def test_es_contract_retrieval_fuses_vector_es_keyword_and_mysql():
    hits, stats = _fuse_contract_retrieval(
        [{"clauseId": 1, "content": "向量命中", "score": 0.9}],
        [{"clauseId": 1, "content": "MySQL 命中"}],
        5,
        es_keyword_hits=[{"clauseId": 1, "content": "关键词命中"}],
    )
    assert hits[0]["retrievalType"] == "HYBRID_RRF"
    assert hits[0]["retrievalSources"] == ["ES_KEYWORD", "ES_VECTOR", "MYSQL_KEYWORD"]
    assert hits[0]["crossValidated"] is True
    assert stats["mode"] == "HYBRID_RRF"
    assert stats["esMysqlKeywordOverlap"] == 1


def test_policy_retrieval_preserves_chunk_and_fuses_paths():
    hits = _fuse_policy_retrieval(
        [{"chunkId": 4, "documentId": 2, "content": "向量"}],
        [{"chunkId": 4, "documentId": 2, "content": "关键词"}],
        5,
    )
    assert hits[0]["chunkId"] == 4
    assert hits[0]["crossValidated"] is True
    assert hits[0]["retrievalType"] == "HYBRID_RRF"


def test_low_quality_document_requires_human_review():
    quality = summarize_document_quality([{"id": 7, "parseQuality": "LOW"}])
    finding = {
        "title": "付款条件需要核对",
        "severity": "MEDIUM",
        "clauseType": "PAYMENT",
        "contractCitationIds": ["CONTRACT_CLAUSE:1"],
        "policyCitationIds": [],
    }
    verdict, reasons = _validate_one(
        finding,
        {
            "citations": [{
                "sourceId": "CONTRACT_CLAUSE:1",
                "sourceType": "CONTRACT_CLAUSE",
                "clauseText": "甲方应在验收合格后十日内付款。",
                "crossValidated": False,
            }],
            "document_quality": quality,
        },
    )
    assert verdict == "DOWNGRADE_CONFIDENCE"
    assert finding["humanReviewRequired"] is True
    assert any("document parse quality" in reason for reason in reasons)


def test_contract_report_records_human_review_boundary():
    result = prepare_human_review({
        "artifact": {"content": {}},
        "document_quality": {"requiresHumanReview": True},
        "evidence_validation": {"unsupportedCitationCount": 1},
        "coverage": {"status": "NEED_MORE_EVIDENCE"},
    })
    review = result["artifact"]["content"]["humanReview"]
    assert result["artifact"]["humanReviewRequired"] is True
    assert review["status"] == "PENDING"
    assert len(review["reasons"]) == 4
