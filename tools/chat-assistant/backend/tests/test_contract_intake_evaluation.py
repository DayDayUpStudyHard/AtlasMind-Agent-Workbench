from pathlib import Path

from app.agent_runtime.contract_intake_evaluation import evaluate_file


def test_first_pass_contract_intake_evaluation_dataset():
    dataset = Path(__file__).parent / "fixtures" / "contract_intake_eval_cases.json"

    report = evaluate_file(dataset)

    assert report["caseCount"] == 3
    assert report["passedCaseCount"] == 3
    assert report["fieldExactMatchRate"] == 1.0
    assert report["amountAccuracy"] == 1.0
    assert report["titleLabelErrorCount"] == 0
    assert report["percentageAmountErrorCount"] == 0
    assert report["partySwapCount"] == 0
