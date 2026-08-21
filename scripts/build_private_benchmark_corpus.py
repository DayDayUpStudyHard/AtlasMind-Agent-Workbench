"""Build the local-only ContractOps core benchmark corpus.

The generated directory is intentionally ignored by Git. It contains source
contract text and candidate labels, therefore it must remain on the local
machine. Existing contracts are selected by ID/hash; the controlled synthetic
extension fills coverage gaps and is marked as such in every case.
"""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import date, timedelta
from hashlib import sha256
import json
import os
from pathlib import Path
import re
from typing import Any

import yaml


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ROOT = ROOT / "benchmark-private" / "core-v1"
TARGETS = {
    "ENGINEERING_EPC": 18,
    "SERVICE_PROCUREMENT": 7,
    "GOODS_PURCHASE": 5,
    "SOFTWARE_IT": 4,
    "OTHER": 2,
}
TASKS = (
    ("CONTRACT_INTAKE", "intake-v1", "首次合同识别"),
    ("CONTRACT_ELEMENT_EXTRACTION", "elements-v1", "合同要素提取"),
    ("TIMELINE_EXTRACTION", "timeline-v1", "履约日程提取"),
    ("CONTRACT_REVIEW", "risk-v1", "风险审查"),
    ("FULFILLMENT_CHECK", "fulfillment-v1", "履约核验"),
)
LABEL_PROMPT_VERSION = "benchmark-gold-candidate-v1"


def _canonical_type(value: str) -> str:
    raw = str(value or "OTHER").upper()
    return {
        "GOODS_PROCUREMENT": "GOODS_PURCHASE",
        "MIXED": "OTHER",
        "NDA": "OTHER",
        "OPS_MAINTENANCE": "OTHER",
    }.get(raw, raw if raw in TARGETS else "OTHER")


def _source_contracts() -> list[dict[str, Any]]:
    # Import only after PYTHONPATH is available; no credentials are printed.
    from app.agent_runtime.persistence import _conn

    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT c.id AS case_id, d.id AS document_id,
                          c.contract_type, c.title AS case_title, d.file_name,
                          d.content_text
                   FROM contract_document d
                   JOIN contract_case c ON c.id=d.case_id
                   WHERE COALESCE(c.deleted,0)=0 AND COALESCE(d.deleted,0)=0
                     AND CHAR_LENGTH(COALESCE(d.content_text,'')) >= 800
                   ORDER BY CHAR_LENGTH(d.content_text) DESC, d.id"""
            )
            rows = cur.fetchall()
    selected: list[dict[str, Any]] = []
    seen_case_ids: set[int] = set()
    for row in rows:
        case_id = int(row["case_id"])
        if case_id in seen_case_ids:
            continue
        seen_case_ids.add(case_id)
        text = str(row.get("content_text") or "").strip()
        selected.append({
            "kind": "LOCAL_SOURCE",
            "sourceCaseId": case_id,
            "sourceDocumentId": int(row["document_id"]),
            "sourceHash": sha256(text.encode("utf-8")).hexdigest(),
            "contractType": _canonical_type(str(row.get("contract_type") or "OTHER")),
            "title": str(row.get("case_title") or row.get("file_name") or f"Contract {case_id}"),
            "contractText": text,
        })
    return selected


def _synthetic_contract(contract_type: str, sequence: int) -> dict[str, Any]:
    start = date(2026, 1, 1) + timedelta(days=sequence * 3)
    delivery = start + timedelta(days=60 + sequence)
    amount = 8_000_000 + sequence * 370_000
    names = {
        "ENGINEERING_EPC": ("华东清洁能源建设有限公司", "中原工程设计有限公司", "新能源机组扩建工程勘察设计合同"),
        "SERVICE_PROCUREMENT": ("启航数字科技有限公司", "锐思技术服务有限公司", "企业数据平台技术服务合同"),
        "GOODS_PURCHASE": ("华联制造有限公司", "智造设备供应有限公司", "自动化生产线设备采购合同"),
        "SOFTWARE_IT": ("远见信息管理有限公司", "云帆软件有限公司", "合同管理系统开发实施合同"),
        "OTHER": ("恒泰实业有限公司", "协同商务有限公司", "商业合作及保密协议"),
    }
    party_a, party_b, title = names[contract_type]
    extra = {
        "ENGINEERING_EPC": "乙方完成初步设计、施工图、竣工图及现场设计服务，工程地点为华东产业园。",
        "SERVICE_PROCUREMENT": "乙方提供系统建设、运行维护、培训及驻场服务，服务成果应符合验收清单。",
        "GOODS_PURCHASE": "乙方供应自动化设备、安装调试并提供十二个月质量保证，设备应符合技术附件。",
        "SOFTWARE_IT": "乙方完成需求分析、软件开发、部署、数据迁移和运维支持，源代码按约定交付。",
        "OTHER": "双方对合作资料承担保密义务，未经书面同意不得向第三方披露。",
    }[contract_type]
    risk = {
        "ENGINEERING_EPC": "验收标准仅约定为达到甲方满意，未约定客观技术指标。",
        "SERVICE_PROCUREMENT": "预付款比例为50%，但未约定履约保函或阶段性交付条件。",
        "GOODS_PURCHASE": "乙方违约责任未约定累计赔偿上限。",
        "SOFTWARE_IT": "数据安全责任约定笼统，未明确数据泄露处置时限。",
        "OTHER": "保密条款未约定违约金或损失计算方式。",
    }[contract_type]
    text = f"""{title}

甲方：{party_a}
乙方：{party_b}

第一条 合同标的
{extra}

第二条 合同价款与支付
合同总价为人民币{amount:,}元。合同生效后，甲方在收到乙方合法发票后10日内支付合同价款的50%作为预付款；乙方完成交付并经甲方验收后支付剩余50%。

第三条 工期与交付
合同自{start.isoformat()}起生效。乙方应于{delivery.isoformat()}前完成约定交付，并提交交付清单、电子文件及验收申请。甲方收到申请后10个工作日内组织验收。

第四条 质量与验收
{risk}

第五条 保密与违约
双方应对履行中知悉的商业信息保密。乙方逾期交付的，每日按合同总价万分之五支付违约金。
"""
    return {
        "kind": "SYNTHETIC_EXTENSION",
        "sourceCaseId": None,
        "sourceDocumentId": None,
        "sourceHash": sha256(text.encode("utf-8")).hexdigest(),
        "contractType": contract_type,
        "title": f"合成扩展-{contract_type}-{sequence:02d}",
        "contractText": text,
        "synthetic": {
            "partyA": party_a,
            "partyB": party_b,
            "contractTitle": title,
            "amount": amount,
            "start": start.isoformat(),
            "delivery": delivery.isoformat(),
        },
    }


def _synthetic_labels(record: dict[str, Any]) -> dict[str, Any]:
    data = record["synthetic"]
    contract_type = record["contractType"]
    risk_by_type = {
        "ENGINEERING_EPC": ("验收标准不明确", "ACCEPTANCE", ["甲方满意", "验收", "客观指标"]),
        "SERVICE_PROCUREMENT": ("预付款缺少保障条件", "PAYMENT", ["预付款", "50%", "履约保函"]),
        "GOODS_PURCHASE": ("缺少责任上限条款", "LIABILITY", ["责任上限", "赔偿"]),
        "SOFTWARE_IT": ("数据安全责任不明确", "COMPLIANCE", ["数据安全", "泄露", "处置"]),
        "OTHER": ("保密违约责任不明确", "CONFIDENTIALITY", ["保密", "违约金", "损失"]),
    }
    risk_title, dimension, terms = risk_by_type[contract_type]
    intake = [
        {"title": f"合同名称:{data['contractTitle']}", "key": "contractName", "value": data["contractTitle"], "kind": "title"},
        {"title": f"甲方:{data['partyA']}", "key": "partyA", "value": data["partyA"], "kind": "partyRole"},
        {"title": f"乙方:{data['partyB']}", "key": "partyB", "value": data["partyB"], "kind": "partyRole"},
        {"title": f"合同金额:{data['amount']}元", "key": "contractAmount", "value": str(data["amount"]), "kind": "amount"},
        {"title": f"生效日期:{data['start']}", "key": "effectiveDate", "value": data["start"], "kind": "date"},
    ]
    elements = intake + [
        {"title": "预付款:合同价款50%", "elementKey": "advancePayment", "category": "价款支付", "value": "50%"},
        {"title": f"交付期限:{data['delivery']}", "elementKey": "deliveryDeadline", "category": "履约日程", "value": data["delivery"]},
    ]
    timeline = [
        {"title": f"合同生效:{data['start']}", "nodeType": "EFFECTIVE", "responsibleParty": "双方", "condition": "合同生效"},
        {"title": "预付款:合同生效后收到发票10日内", "nodeType": "PAYMENT", "responsibleParty": "甲方", "condition": "收到合法发票"},
        {"title": f"交付:{data['delivery']}", "nodeType": "DELIVERY", "responsibleParty": "乙方", "condition": "提交交付清单、电子文件及验收申请"},
        {"title": "验收:收到申请后10个工作日内", "nodeType": "ACCEPTANCE", "responsibleParty": "甲方", "condition": "收到验收申请"},
    ]
    risks = [{
        "title": risk_title, "severity": "HIGH", "riskDimension": dimension,
        "keyTerms": terms, "mustHaveContractCitation": True,
        "mustHavePolicyCitation": True,
    }]
    fulfillment = {
        "requirements": [{"title": f"交付:{data['delivery']}", "requirement": "提交交付清单、电子文件及验收申请"}],
        "judgements": [{"requirementContains": "交付", "proofStatus": "SUPPORTED"}],
        "manualResult": "SATISFIED",
    }
    return {"intakeFields": intake, "elements": elements, "timelineNodes": timeline, "risks": risks, "fulfillment": fulfillment}


def _extract_json(text: str) -> dict[str, Any] | None:
    fenced = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.DOTALL | re.IGNORECASE)
    raw = fenced.group(1) if fenced else text[text.find("{"):text.rfind("}") + 1]
    try:
        value = json.loads(raw)
    except (ValueError, TypeError):
        return None
    return value if isinstance(value, dict) else None


def _llm_candidate_labels(record: dict[str, Any], model: str, timeout_seconds: int) -> dict[str, Any] | None:
    from app.services.llm_service import LLMService

    prompt = f"""你是合同 Benchmark 的独立标注模型，不是被评测的 Agent。只依据合同原文生成严格 JSON，不要补造信息。
合同场景：{record['contractType']}
输出对象必须有 intakeFields、elements、timelineNodes、risks、fulfillment 五个键。
intakeFields/elements/timelineNodes/risks 都是数组；每项必须有 title。timeline 标题格式为 节点:日期或条件。risks 必须有 title、severity(HIGH/MEDIUM/LOW)、riskDimension、keyTerms。fulfillment 是对象，含 requirements 数组、judgements 数组、manualResult(SATISFIED/NOT_SATISFIED/PENDING)。
对未出现的信息不要推测；缺少关键条款可作为风险，但只在该合同场景确实适用时标出。

合同原文：
{record['contractText'][:24000]}
"""
    try:
        service = LLMService()
        response = service.analysis_client.with_options(timeout=timeout_seconds).chat.completions.create(
            model=model,
            temperature=0,
            messages=[
                {"role": "system", "content": "Return JSON only."},
                {"role": "user", "content": prompt},
            ],
        )
        return _extract_json(str(response.choices[0].message.content or ""))
    except Exception as exc:
        print(f"label candidate failed for source {record.get('sourceDocumentId')}: {exc}")
        return None


def _fallback_labels_from_text(record: dict[str, Any]) -> dict[str, Any]:
    """Conservative fallback when the independent label model is unavailable."""
    text = record["contractText"]
    first_line = next((line.strip() for line in text.splitlines() if line.strip()), record["title"])
    intake = [{"title": f"合同名称:{first_line[:120]}", "key": "contractName", "value": first_line[:120], "kind": "title"}]
    for role in ("甲方", "乙方"):
        match = re.search(rf"{role}[：:]\s*([^\n，,。；;]{{2,80}})", text)
        if match:
            value = match.group(1).strip()
            intake.append({"title": f"{role}:{value}", "key": "partyA" if role == "甲方" else "partyB", "value": value, "kind": "partyRole"})
    amount = re.search(r"(?:合同总价|合同金额|总价款)[^\n。；;]{0,30}?([\d,]+(?:\.\d+)?)\s*(万元|元)", text)
    if amount:
        value = amount.group(1).replace(",", "")
        if amount.group(2) == "万元":
            value = str(float(value) * 10000)
        intake.append({"title": f"合同金额:{value}元", "key": "contractAmount", "value": value, "kind": "amount"})
    dates = re.findall(r"20\d{2}[年\-/]\d{1,2}[月\-/]\d{1,2}日?", text)
    timeline = [
        {"title": f"合同日期:{value}", "nodeType": "OTHER", "responsibleParty": "待确认", "condition": "原文日期"}
        for value in dates[:4]
    ]
    return {
        "intakeFields": intake,
        "elements": intake,
        "timelineNodes": timeline,
        "risks": [],
        "fulfillment": {"requirements": [], "judgements": [], "manualResult": "PENDING"},
    }


def _normalise_labels(record: dict[str, Any], candidate: dict[str, Any] | None) -> dict[str, Any]:
    """Ensure every task has structurally valid candidate labels."""
    labels = candidate or {}
    fallback = _fallback_labels_from_text(record)
    result: dict[str, Any] = {}
    for key in ("intakeFields", "elements", "timelineNodes", "risks"):
        rows = labels.get(key)
        result[key] = rows if isinstance(rows, list) else fallback[key]
    fulfillment = labels.get("fulfillment")
    if not isinstance(fulfillment, dict):
        fulfillment = fallback["fulfillment"]
    fulfillment.setdefault("requirements", [])
    fulfillment.setdefault("judgements", [])
    fulfillment.setdefault("manualResult", "PENDING")
    result["fulfillment"] = fulfillment
    return result


def _task_expected(labels: dict[str, Any], task_type: str) -> dict[str, Any]:
    if task_type == "CONTRACT_INTAKE":
        return {"intakeFields": labels["intakeFields"]}
    if task_type == "CONTRACT_ELEMENT_EXTRACTION":
        return {"elements": labels["elements"]}
    if task_type == "TIMELINE_EXTRACTION":
        return {"timelineNodes": labels["timelineNodes"]}
    if task_type == "CONTRACT_REVIEW":
        return {"risks": labels["risks"]}
    if task_type == "FULFILLMENT_CHECK":
        return {"timelineNodes": labels["timelineNodes"], "fulfillment": labels["fulfillment"]}
    raise ValueError(task_type)


def _case_payload(record: dict[str, Any], labels: dict[str, Any], task_type: str, index: int, label_model: str) -> dict[str, Any]:
    expected = _task_expected(labels, task_type)
    payload: dict[str, Any] = {
        "schemaVersion": 2,
        "taskType": task_type,
        "caseId": f"{task_type[:3]}-{index:03d}",
        "title": f"{task_type} · {record['title']}",
        "contractType": record["contractType"],
        "contractText": record["contractText"],
        "annotationStatus": "CANDIDATE",
        "source": {
            "kind": record["kind"],
            "caseId": record.get("sourceCaseId"),
            "documentId": record.get("sourceDocumentId"),
            "contentHash": record["sourceHash"],
        },
        "labelSource": {"provider": "benchmark-generator", "model": label_model, "promptVersion": LABEL_PROMPT_VERSION},
        "candidateLabel": expected,
        "expected": expected,
        "shouldNotFind": [],
    }
    if task_type == "FULFILLMENT_CHECK":
        timeline = labels["timelineNodes"]
        delivery = next((node for node in timeline if str(node.get("nodeType", "")).upper() == "DELIVERY"), timeline[0] if timeline else {})
        requirement = next(
            (
                str(item.get("requirement") or "").strip()
                for item in (labels.get("fulfillment", {}).get("requirements") or [])
                if isinstance(item, dict) and str(item.get("requirement") or "").strip()
            ),
            "交付",
        )
        payload["targetTimelineSelectorJson"] = {
            "nodeType": delivery.get("nodeType", "DELIVERY"),
            # Labels are normalized differently by timeline extraction. The
            # obligation phrase is the stable semantic anchor for fulfillment.
            "businessMeaningContains": requirement[:80],
        }
        delivery_date_match = re.search(
            r"(20\d{2})[-年](\d{1,2})[-月](\d{1,2})",
            str(delivery.get("title") or ""),
        )
        if delivery_date_match:
            deadline = date(
                int(delivery_date_match.group(1)),
                int(delivery_date_match.group(2)),
                int(delivery_date_match.group(3)),
            )
            proof_date = (deadline - timedelta(days=1)).isoformat()
        else:
            proof_date = "2026-01-01"
        payload["fulfillmentEvidenceJson"] = [{
            "fileName": f"proof-{index:03d}.pdf",
            "date": proof_date,
            "content": (
                f"已完成；{requirement}；于 {proof_date} 提交，"
                "甲方已签收并加盖签章。"
            ),
        }]
        payload["expectedJudgementsJson"] = labels["fulfillment"].get("judgements", [])
        payload["expectedManualResult"] = labels["fulfillment"].get("manualResult", "PENDING")
    return payload


def _write_dataset(root: Path, task_type: str, directory_name: str, label: str, records: list[dict[str, Any]], labels: list[dict[str, Any]], label_model: str) -> None:
    directory = root / directory_name
    cases_dir = directory / "cases"
    cases_dir.mkdir(parents=True, exist_ok=True)
    manifest = {
        "schemaVersion": 2,
        "id": directory_name,
        "name": f"私有核心集 · {label}",
        "version": "v1-candidate",
        "taskType": task_type,
        "labelStatus": "CANDIDATE",
        "privateCorpus": True,
        "targetCaseCount": len(records),
        "description": "本地私有候选金标。人工确认前仅用于观察评测，禁止设为生产基线。",
        "profile": {"engineeringTargetRatio": 0.5, "labelPromptVersion": LABEL_PROMPT_VERSION},
        "caseDirectory": "cases",
    }
    (directory / "manifest.yaml").write_text(yaml.safe_dump(manifest, allow_unicode=True, sort_keys=False), encoding="utf-8")
    for index, (record, label_data) in enumerate(zip(records, labels), 1):
        payload = _case_payload(record, label_data, task_type, index, label_model)
        (cases_dir / f"{payload['caseId']}.yaml").write_text(
            yaml.safe_dump(payload, allow_unicode=True, sort_keys=False), encoding="utf-8"
        )


def build_corpus(
    root: Path, *, total: int, label_model: str, generate_labels: bool, label_timeout_seconds: int
) -> dict[str, Any]:
    sources = _source_contracts()
    chosen: list[dict[str, Any]] = []
    counts: Counter[str] = Counter()
    for source in sources:
        contract_type = source["contractType"]
        if counts[contract_type] >= TARGETS[contract_type]:
            continue
        chosen.append(source)
        counts[contract_type] += 1
        if len(chosen) >= total:
            break
    sequence = 1
    while len(chosen) < total:
        needed = max(TARGETS, key=lambda kind: TARGETS[kind] - counts[kind])
        chosen.append(_synthetic_contract(needed, sequence))
        counts[needed] += 1
        sequence += 1

    label_sets: list[dict[str, Any]] = []
    for index, record in enumerate(chosen, 1):
        candidate = None
        if record["kind"] == "LOCAL_SOURCE" and generate_labels:
            candidate = _llm_candidate_labels(record, label_model, label_timeout_seconds)
        label_sets.append(_normalise_labels(record, candidate) if record["kind"] == "LOCAL_SOURCE" else _synthetic_labels(record))
        print(f"prepared {index}/{len(chosen)}: {record['kind']} {record['contractType']}", flush=True)

    for task_type, directory_name, label in TASKS:
        if task_type == "FULFILLMENT_CHECK":
            # Proof/evidence cases need a unique, deterministic selector.
            # Prefer controlled extensions so the case remains honest even
            # when a local source lacks a clearly extractable delivery node.
            pairs = list(zip(chosen, label_sets))
            pairs.sort(key=lambda pair: pair[0]["kind"] != "SYNTHETIC_EXTENSION")
            records_for_task = [pair[0] for pair in pairs[:24]]
            labels_for_task = [pair[1] for pair in pairs[:24]]
        else:
            records_for_task = chosen
            labels_for_task = label_sets
        _write_dataset(root, task_type, directory_name, label, records_for_task, labels_for_task, label_model)
    index = {
        "schemaVersion": 1,
        "generatedAt": date.today().isoformat(),
        "totalContracts": len(chosen),
        "distribution": dict(counts),
        "sourceContracts": sum(1 for row in chosen if row["kind"] == "LOCAL_SOURCE"),
        "syntheticExtensions": sum(1 for row in chosen if row["kind"] == "SYNTHETIC_EXTENSION"),
        "labelModel": label_model,
        "status": "CANDIDATE",
    }
    root.mkdir(parents=True, exist_ok=True)
    (root / "corpus-index.json").write_text(json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8")
    return index


def main() -> int:
    parser = argparse.ArgumentParser(description="Build local private ContractOps core benchmark corpus")
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    parser.add_argument("--total", type=int, default=36)
    parser.add_argument("--label-model", default=os.getenv("BENCHMARK_LABEL_MODEL", "deepseek-chat"))
    parser.add_argument("--label-timeout-seconds", type=int, default=30)
    parser.add_argument("--skip-llm", action="store_true", help="use structural fallback labels for local sources")
    args = parser.parse_args()
    if args.total != sum(TARGETS.values()):
        raise SystemExit(f"--total must equal configured distribution total {sum(TARGETS.values())}")
    result = build_corpus(
        args.root.resolve(), total=args.total, label_model=args.label_model,
        generate_labels=not args.skip_llm, label_timeout_seconds=max(5, args.label_timeout_seconds),
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
