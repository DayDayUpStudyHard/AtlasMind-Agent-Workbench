from app.agent_runtime.graph.contract_extraction import (
    ELEMENT_PACKS,
    _canonical_base_fields,
    normalize_contract_profile,
)


def _context():
    return {
        "case": {
            "title": "勘察设计合同",
            "contractType": "SERVICE_PROCUREMENT",
            "ourEntity": "江西省电力设计院",
            "counterparty": "华能安源发电有限责任公司",
            "ourSide": "B",
            "amount": 18600000,
            "currency": "CNY",
            "signedDate": "2012-12-12",
        },
        "document": {"id": 50, "version": 1, "contentHash": "abc"},
        "clauses": [
            {
                "sourceId": "CONTRACT_CLAUSE:7",
                "clauseId": 7,
                "documentId": 50,
                "pageNumber": 12,
                "clauseText": "本合同总价为人民币壹仟捌佰陆拾万元整（¥1860万元）。",
            }
        ],
        "confirmedIntake": {
            "id": 28,
            "schemaVersion": "contract-intake-v2",
            "promptVersion": "contract-intake-v2",
            "model": "deepseek-v4-flash",
            "fields": {
                "amount": {
                    "value": 18600000,
                    "source": "LLM",
                    "confidence": 0.95,
                    "citations": [{"quote": "本合同总价为人民币壹仟捌佰陆拾万元整（¥1860万元）"}],
                }
            },
        },
    }


def test_llm_element_packs_do_not_repeat_canonical_base_fact_extraction():
    requested = {
        key
        for pack in ELEMENT_PACKS
        for key in pack.get("elementKeys") or []
    }

    assert "contract_title" not in requested
    assert "party_a" not in requested
    assert "party_b" not in requested
    assert "contract_amount" not in requested
    assert "effective_date" not in requested
    assert "expiry_date" not in requested


def test_canonical_base_fields_restore_legal_party_roles_and_intake_evidence():
    fields = {item["key"]: item for item in _canonical_base_fields(_context())}

    assert fields["partyA"]["value"] == "华能安源发电有限责任公司"
    assert fields["partyB"]["value"] == "江西省电力设计院"
    assert fields["amount"]["value"] == 18600000
    assert fields["amount"]["source"] == "CONFIRMED_INTAKE"
    assert fields["amount"]["citations"][0]["pageNumber"] == 12


def test_profile_cannot_override_confirmed_base_amount():
    raw = {
        "profile": {
            "title": "合同画像",
            "contractType": "SERVICE_PROCUREMENT",
            "baseFields": [
                {
                    "key": "amount",
                    "label": "合同金额",
                    "value": 10,
                    "confidence": 0.99,
                    "citations": [],
                }
            ],
            "groups": [],
        }
    }

    profile, validation = normalize_contract_profile(raw, _context(), [], _context()["clauses"])
    fields = {item["key"]: item for item in profile["baseFields"]}

    assert fields["amount"]["value"] == 18600000
    assert fields["amount"]["source"] == "CONFIRMED_INTAKE"
    assert validation["canonicalBaseFieldCount"] >= 1


def test_structured_profile_field_gets_business_display_value():
    context = _context()
    evidence = context["clauses"]
    raw = {
        "profile": {
            "title": "合同画像",
            "contractType": "SERVICE_PROCUREMENT",
            "groups": [
                {
                    "groupKey": "financial",
                    "label": "价款、支付与结算",
                    "fields": [
                        {
                            "key": "settlement_payment",
                            "label": "结算款",
                            "valueType": "STRUCTURED",
                            "value": {
                                "type": "结算款",
                                "condition": "根据发包人确认的工程结算报告，承包人向发包人申请支付工程结算款",
                                "amount": None,
                                "currency": None,
                                "timing": "收到申请后30天内",
                                "note": "除质量保证金以外的结算款",
                            },
                            "confidence": 0.92,
                            "citations": [{"sourceId": "CONTRACT_CLAUSE:7", "quote": "本合同总价"}],
                        }
                    ],
                }
            ],
        }
    }

    profile, validation = normalize_contract_profile(raw, context, [], evidence)
    field = profile["groups"][0]["fields"][0]

    assert field["value"]["type"] == "结算款"
    assert field["displayValue"].startswith("结算款：")
    assert "工程结算报告" in field["displayValue"]
    assert "30天内" in field["displayValue"]
    assert "质量保证金" in field["displayValue"]
    assert validation["fieldCount"] >= 1


def test_human_edited_canonical_value_does_not_reuse_candidate_citation():
    context = _context()
    context["case"]["amount"] = 20000000

    fields = {item["key"]: item for item in _canonical_base_fields(context)}

    assert fields["amount"]["value"] == 20000000
    assert fields["amount"]["citations"] == []
    assert fields["amount"]["status"] == "CONFIRMED"
