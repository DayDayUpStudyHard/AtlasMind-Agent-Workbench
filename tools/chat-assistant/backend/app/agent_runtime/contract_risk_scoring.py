"""Deterministic contract risk scoring engine — Phase 3.

Five dimensions with rule-based signals, weighted average, and one-vote
veto rules.  Mirrors the design of HealthScoringEngine but operates on
contract review rules and clause structures instead of GitHub evidence.
"""

from __future__ import annotations

import hashlib
import logging
from typing import Any

logger = logging.getLogger(__name__)

SCORING_VERSION = "v1-contract"
ANALYSIS_MODE = "rule-based-contract-risk"


class ContractRiskScoringEngine:
    """Rule-based contract risk scorer with veto support."""

    # Dimension weights (must sum to 1.0)
    DIMENSIONS = [
        ("主体与授权", 0.15),
        ("商务与付款", 0.20),
        ("责任与违约", 0.25),
        ("合规与保密", 0.20),
        ("履约可执行性", 0.20),
    ]

    # Map clause types to dimensions
    CLAUSE_TO_DIMENSION = {
        "LIABILITY":       "责任与违约",
        "PAYMENT":         "商务与付款",
        "CONFIDENTIALITY": "合规与保密",
        "ACCEPTANCE":      "履约可执行性",
        "TERMINATION":     "责任与违约",
        "IP":              "合规与保密",
        "DATA_PROTECTION": "合规与保密",
        "OTHER":           "履约可执行性",
    }

    def score(
        self,
        case: dict[str, Any],
        rules: list[dict[str, Any]],
        findings: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Compute risk score from rules and findings.

        Args:
            case: contract_case row dict
            rules: list of active contract_review_rule rows
            findings: list of contract_review_finding rows (from agent or manual)

        Returns:
            {riskScore, riskStatus, dimensions, findings, vetoTriggered, ...}
        """
        # Group findings by dimension
        dim_findings: dict[str, list[dict]] = {d[0]: [] for d in self.DIMENSIONS}
        for f in findings:
            clause_type = str(f.get("clause_type", "OTHER"))
            dim = self.CLAUSE_TO_DIMENSION.get(clause_type, "履约可执行性")
            dim_findings.setdefault(dim, []).append(f)

        # Score each dimension (base 100, subtract penalties)
        dimension_scores = {}
        veto_triggered = False
        veto_details = []

        for dim_name, weight in self.DIMENSIONS:
            base = 100
            dim_rules = [r for r in rules
                         if self.CLAUSE_TO_DIMENSION.get(str(r.get("clause_type", "")), "") == dim_name]
            dim_f = dim_findings.get(dim_name, [])

            for rule in dim_rules:
                if int(rule.get("is_veto", 0)) == 1:
                    # Check if any finding matches this rule and is still OPEN
                    for f in dim_f:
                        if str(f.get("rule_key", "")) == str(rule.get("rule_key", "")) \
                                and str(f.get("status", "")) == "OPEN":
                            veto_triggered = True
                            veto_details.append({
                                "rule": str(rule.get("title", "")),
                                "finding": str(f.get("title", "")),
                                "dimension": dim_name,
                            })
                            base = 0  # Veto zeroes the dimension
                            break

                if base > 0:
                    severity = str(rule.get("severity", "MEDIUM"))
                    weight_penalty = int(rule.get("weight", 10))
                    # Check if this rule has been violated (finding exists and is OPEN)
                    violated = any(
                        str(f.get("rule_key", "")) == str(rule.get("rule_key", ""))
                        and str(f.get("status", "")) == "OPEN"
                        for f in dim_f
                    )
                    if violated:
                        penalty = {"HIGH": weight_penalty, "MEDIUM": weight_penalty // 2, "LOW": weight_penalty // 4}.get(severity, weight_penalty // 2)
                        base = max(0, base - penalty)

            dimension_scores[dim_name] = base

        # Weighted total
        total = sum(dimension_scores[d[0]] * d[1] for d in self.DIMENSIONS)
        total = max(0, min(100, round(total)))

        # Status
        if veto_triggered:
            status = "HIGH_RISK"
        elif total >= 80:
            status = "LOW_RISK"
        elif total >= 60:
            status = "MEDIUM_RISK"
        else:
            status = "HIGH_RISK"

        # Evidence hash
        evidence_hash = self._hash(case, rules, findings)

        return {
            "riskScore": total,
            "riskStatus": status,
            "dimensions": [
                {"name": name, "score": dimension_scores[name], "weight": int(w * 100)}
                for name, w in self.DIMENSIONS
            ],
            "findings": findings,
            "vetoTriggered": veto_triggered,
            "vetoDetails": veto_details,
            "scoringVersion": SCORING_VERSION,
            "evidenceHash": evidence_hash,
            "analysisMode": ANALYSIS_MODE,
        }

    def _hash(self, case: dict, rules: list[dict], findings: list[dict]) -> str:
        buf = f"case:{case.get('id','')}\n"
        for r in sorted(rules, key=lambda x: str(x.get("rule_key", ""))):
            buf += f"rule:{r.get('rule_key','')}:v{r.get('version','')}\n"
        for f in sorted(findings, key=lambda x: str(x.get("id", ""))):
            buf += f"finding:{f.get('id','')}:{f.get('status','')}\n"
        return hashlib.sha256(buf.encode()).hexdigest()
