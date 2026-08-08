"""Deterministic evaluation for first-pass contract intake facts."""

from __future__ import annotations

import argparse
import json
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from .contract_intake_extractor import deterministic_hints, validate_extraction


def _equivalent(actual: Any, expected: Any) -> bool:
    if actual is None or expected is None:
        return actual is expected
    try:
        return Decimal(str(actual)).compare(Decimal(str(expected))) == Decimal("0")
    except (InvalidOperation, ValueError):
        return str(actual).strip().casefold() == str(expected).strip().casefold()


def evaluate_cases(cases: list[dict[str, Any]]) -> dict[str, Any]:
    field_total = 0
    field_correct = 0
    amount_total = amount_correct = 0
    title_total = title_correct = 0
    party_total = party_correct = 0
    percentage_amount_errors = 0
    title_label_errors = 0
    party_swaps = 0
    results = []

    for case in cases:
        text = str(case.get("text") or "")
        hints = deterministic_hints(text, str(case.get("fileName") or ""))
        validated = validate_extraction(case.get("modelOutput") or {}, text, hints)
        fields = validated.get("fields") or {}
        expected = case.get("expected") or {}
        mismatches = []
        for key, expected_value in expected.items():
            actual_value = (fields.get(key) or {}).get("value")
            matched = _equivalent(actual_value, expected_value)
            field_total += 1
            field_correct += int(matched)
            if not matched:
                mismatches.append({"field": key, "expected": expected_value, "actual": actual_value})
            if key == "amount":
                amount_total += 1
                amount_correct += int(matched)
                if not matched and "%" in text:
                    percentage_amount_errors += 1
            elif key == "contractTitle":
                title_total += 1
                title_correct += int(matched)
                if str(actual_value or "").startswith(("合同编号", "编号", "填写说明", "目录")):
                    title_label_errors += 1
            elif key in {"partyA", "partyB"}:
                party_total += 1
                party_correct += int(matched)

        actual_a = (fields.get("partyA") or {}).get("value")
        actual_b = (fields.get("partyB") or {}).get("value")
        if expected.get("partyA") is not None and expected.get("partyB") is not None:
            if _equivalent(actual_a, expected.get("partyB")) and _equivalent(actual_b, expected.get("partyA")):
                party_swaps += 1
        results.append({
            "caseId": case.get("id"),
            "passed": not mismatches,
            "mismatches": mismatches,
            "needsConfirmation": validated.get("needsConfirmation") or [],
        })

    def rate(correct: int, total: int) -> float:
        return round(correct / total, 4) if total else 1.0

    return {
        "caseCount": len(cases),
        "passedCaseCount": sum(1 for item in results if item["passed"]),
        "fieldExactMatchRate": rate(field_correct, field_total),
        "amountAccuracy": rate(amount_correct, amount_total),
        "titleAccuracy": rate(title_correct, title_total),
        "partyAccuracy": rate(party_correct, party_total),
        "percentageAmountErrorCount": percentage_amount_errors,
        "titleLabelErrorCount": title_label_errors,
        "partySwapCount": party_swaps,
        "results": results,
    }


def evaluate_file(path: str | Path) -> dict[str, Any]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    cases = data.get("cases") if isinstance(data, dict) else data
    if not isinstance(cases, list):
        raise ValueError("Evaluation dataset must contain a cases array")
    return evaluate_cases(cases)


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate contract intake fact extraction")
    parser.add_argument("dataset", type=Path)
    args = parser.parse_args()
    print(json.dumps(evaluate_file(args.dataset), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
