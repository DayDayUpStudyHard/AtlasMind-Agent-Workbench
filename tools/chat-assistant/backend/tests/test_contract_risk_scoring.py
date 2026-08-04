import unittest

from app.agent_runtime.contract_risk_scoring import ContractRiskScoringEngine


class ContractRiskScoringTest(unittest.TestCase):
    def setUp(self):
        self.engine = ContractRiskScoringEngine()

    def test_scores_camel_case_store_rows(self):
        rules = [{
            "ruleKey": "PAYMENT_01", "clauseType": "PAYMENT",
            "severity": "HIGH", "weight": 20, "isVeto": 0,
        }]
        findings = [{
            "id": 1, "ruleKey": "PAYMENT_01", "clauseType": "PAYMENT",
            "severity": "HIGH", "status": "OPEN", "title": "付款风险",
        }]

        result = self.engine.score({"id": 7}, rules, findings)

        payment = next(item for item in result["dimensions"] if item["name"] == "商务与付款")
        self.assertEqual(80, payment["score"])
        self.assertEqual(96, result["riskScore"])

    def test_veto_rule_forces_high_risk(self):
        rules = [{
            "ruleKey": "LIABILITY_VETO", "clauseType": "LIABILITY",
            "title": "责任上限缺失", "severity": "HIGH", "weight": 30, "isVeto": 1,
        }]
        findings = [{
            "id": 2, "ruleKey": "LIABILITY_VETO", "clauseType": "LIABILITY",
            "status": "OPEN", "title": "责任上限缺失",
        }]

        result = self.engine.score({"id": 7}, rules, findings)

        self.assertTrue(result["vetoTriggered"])
        self.assertEqual("HIGH_RISK", result["riskStatus"])

    def test_policy_citation_rule_key_is_scored(self):
        rules = [{
            "ruleKey": "PROC-PAY-001", "clauseType": "PAYMENT",
            "severity": "HIGH", "weight": 20, "isVeto": 0,
        }]
        findings = [{
            "id": 3, "clauseType": "PAYMENT", "severity": "HIGH", "status": "OPEN",
            "title": "预付款比例过高",
            "policyCitation": {"ruleKey": "PROC-PAY-001"},
        }]

        result = self.engine.score({"id": 7}, rules, findings)

        payment = next(item for item in result["dimensions"] if item["name"] == "商务与付款")
        self.assertEqual(80, payment["score"])
        self.assertEqual("MEDIUM_RISK", result["riskStatus"])

    def test_unmatched_high_finding_gets_fallback_penalty(self):
        result = self.engine.score(
            {"id": 7},
            [],
            [{"id": 4, "clauseType": "LIABILITY", "severity": "HIGH",
              "status": "OPEN", "title": "责任限制异常"}],
        )

        liability = next(item for item in result["dimensions"] if item["name"] == "责任与违约")
        self.assertEqual(75, liability["score"])
        self.assertLess(result["riskScore"], 100)
        self.assertEqual("MEDIUM_RISK", result["riskStatus"])


if __name__ == "__main__":
    unittest.main()
