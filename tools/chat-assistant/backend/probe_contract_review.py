"""Diagnostic probe: reproduce the legacy contract_review failure (no code changes)."""
import json
import traceback

from app.config import settings
from app.services.llm_service import LLMService

llm = LLMService()
print("model:", llm.model)
print("base_url:", settings.llm_base_url)
print("deepseek_reasoning:", llm._uses_deepseek_reasoning_model())

case = {
    "caseKey": "EVAL-17-0",
    "title": "软件采购合同",
    "counterparty": "测试公司",
    "amount": 500000,
    "contractType": "SOFTWARE_IT",
}
findings = [
    {
        "ruleId": 7,
        "ruleKey": "PROC-ACC-001",
        "ruleTitle": "验收标准明确",
        "title": "验收标准明确",
        "riskDimension": "ACCEPTANCE",
        "severity": "HIGH",
        "description": "验收标准不得由甲方单方决定",
        "contractCitation": {"snippet": "以甲方满意为准"},
        "contractCitationIds": ["CONTRACT_CLAUSE:1"],
    }
]
citations = [
    {"sourceType": "CONTRACT_CLAUSE", "snippet": "以甲方满意为准", "sourceId": "CONTRACT_CLAUSE:1"},
]
scoring = {"riskScore": 75, "riskStatus": "HIGH_RISK"}

template, temperature = llm._prompt("contract_review", 0)
print("temperature:", temperature)
print("chat_max_tokens:", settings.chat_max_tokens)

# Variant A: exactly what contract_review now sends (guard + response_format)
print("\n=== Variant A: guard + response_format (current production path) ===")
try:
    result = llm.contract_review(case, findings, citations, scoring, run_id=0)
    print("SUCCESS keys:", list(result.keys())[:10])
    print("analysisMode:", result.get("analysisMode"))
except Exception as exc:
    print("EXCEPTION:", type(exc).__name__, str(exc)[:400])
    traceback.print_exc(limit=4)

# Variant B: raw call WITHOUT the reasoning guard, old parse path (run-14 behavior)
print("\n=== Variant B: no guard, parse visible content only ===")
try:
    payload = {
        "case": {
            "caseKey": case.get("caseKey", ""),
            "title": case.get("title", ""),
            "counterparty": case.get("counterparty", ""),
            "amount": case.get("amount"),
            "contractType": case.get("contractType", ""),
        },
        "findings": findings,
        "ruleEngineFindings": findings,
        "citations": citations,
        "deterministicScoring": scoring,
        "analysisMode": "FULL",
        "coverageLimitation": "",
        "missingDomains": [],
    }
    response = llm._call_llm_with_retry(
        lambda: llm.analysis_client.chat.completions.create(
            model=llm.model,
            messages=[
                {"role": "system", "content": template},
                {"role": "user", "content": json.dumps(payload, ensure_ascii=False, default=str)},
            ],
            temperature=temperature,
            max_tokens=max(8192, settings.chat_max_tokens),
            response_format={"type": "json_object"},
            stream=False,
        ),
        max_retries=1,
        backoff_base=2.0,
    )
    content = response.choices[0].message.content if response.choices else ""
    reasoning = getattr(response.choices[0].message, "reasoning_content", None)
    finish = getattr(response.choices[0], "finish_reason", None)
    print(f"SUCCESS: content_len={len(content or '')} reasoning_len={len(reasoning or '')} finish={finish}")
    parsed = llm._parse_json_object(content or "")
    print("parsed keys:", list(parsed.keys())[:8])
except Exception as exc:
    print("EXCEPTION:", type(exc).__name__, str(exc)[:400])
