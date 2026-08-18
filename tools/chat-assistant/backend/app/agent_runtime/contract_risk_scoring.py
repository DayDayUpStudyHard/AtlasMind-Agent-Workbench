"""Deterministic contract risk scoring engine — Phase 3.

Five dimensions with rule-based signals, weighted average, and one-vote
veto rules.  Mirrors the design of HealthScoringEngine but operates on
contract review rules and clause structures instead of GitHub evidence.
"""

from __future__ import annotations

import hashlib
import json
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

    FALLBACK_PENALTY = {"HIGH": 25, "MEDIUM": 12, "LOW": 5}

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
        rules_by_key = {
            self._rule_key(rule): rule
            for rule in rules
            if self._rule_key(rule)
        }

        normalized_findings = [
            self._normalize_finding(finding, rules_by_key)
            for finding in findings
            if isinstance(finding, dict)
        ]

        # Group findings by dimension
        dim_findings: dict[str, list[dict]] = {d[0]: [] for d in self.DIMENSIONS}
        for f in normalized_findings:
            clause_type = str(f.get("clauseType") or "OTHER")
            dim = self.CLAUSE_TO_DIMENSION.get(clause_type, "履约可执行性")
            dim_findings.setdefault(dim, []).append(f)

        # Score each dimension (base 100, subtract penalties)
        dimension_scores = {}
        veto_triggered = False
        veto_details = []

        for dim_name, weight in self.DIMENSIONS:
            base = 100
            matched_rule_keys = set()
            dim_rules = [r for r in rules
                         if self.CLAUSE_TO_DIMENSION.get(
                             str(r.get("clauseType") or r.get("clause_type") or ""), ""
                         ) == dim_name]
            dim_f = dim_findings.get(dim_name, [])

            for rule in dim_rules:
                rule_key = self._rule_key(rule)
                if int(rule.get("isVeto") or rule.get("is_veto") or 0) == 1:
                    # Check if any finding matches this rule and is still OPEN
                    for f in dim_f:
                        if self._finding_rule_key(f) == rule_key \
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
                        self._finding_rule_key(f) == rule_key
                        and str(f.get("status", "")) == "OPEN"
                        for f in dim_f
                    )
                    if violated:
                        matched_rule_keys.add(rule_key)
                        penalty = {"HIGH": weight_penalty, "MEDIUM": weight_penalty // 2, "LOW": weight_penalty // 4}.get(severity, weight_penalty // 2)
                        base = max(0, base - penalty)

            for f in dim_f:
                if str(f.get("status", "")) != "OPEN":
                    continue
                finding_key = self._finding_rule_key(f)
                if finding_key and finding_key in matched_rule_keys:
                    continue
                severity = str(f.get("severity") or "MEDIUM").upper()
                base = max(0, base - self.FALLBACK_PENALTY.get(severity, 12))

            dimension_scores[dim_name] = base

        # Weighted total
        total = sum(dimension_scores[d[0]] * d[1] for d in self.DIMENSIONS)
        total = max(0, min(100, round(total)))

        # Status
        open_high_findings = [
            f for f in normalized_findings
            if str(f.get("status", "")) == "OPEN"
            and str(f.get("severity", "")).upper() == "HIGH"
        ]

        if veto_triggered:
            status = "HIGH_RISK"
        elif open_high_findings and total >= 80:
            status = "MEDIUM_RISK"
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
            "findings": normalized_findings,
            "vetoTriggered": veto_triggered,
            "vetoDetails": veto_details,
            "ruleBasis": [
                {
                    "ruleId": rule.get("id"),
                    "ruleKey": self._rule_key(rule),
                    "clauseType": str(
                        rule.get("clauseType") or rule.get("clause_type") or "OTHER"
                    ).upper(),
                    "title": str(rule.get("title") or ""),
                    "severity": str(rule.get("severity") or "MEDIUM").upper(),
                }
                for rule in rules
            ],
            "scoringVersion": SCORING_VERSION,
            "evidenceHash": evidence_hash,
            "analysisMode": ANALYSIS_MODE,
        }

    def _hash(self, case: dict, rules: list[dict], findings: list[dict]) -> str:
        buf = f"case:{case.get('id','')}\n"
        for r in sorted(rules, key=lambda x: str(x.get("ruleKey") or x.get("rule_key") or "")):
            rule_key = r.get("ruleKey") or r.get("rule_key") or ""
            buf += f"rule:{rule_key}:v{r.get('version','')}\n"
        for f in sorted(findings, key=lambda x: str(x.get("id", ""))):
            buf += (
                f"finding:{f.get('id','')}:{self._finding_rule_key(f)}:"
                f"{f.get('severity','')}:{f.get('status','')}\n"
            )
        return hashlib.sha256(buf.encode()).hexdigest()

    def _normalize_finding(
        self,
        finding: dict[str, Any],
        rules_by_key: dict[str, dict[str, Any]],
    ) -> dict[str, Any]:
        normalized = dict(finding)
        rule_key = self._finding_rule_key(normalized)
        if rule_key:
            normalized["ruleKey"] = rule_key
        clause_type = (
            normalized.get("clauseType")
            or normalized.get("clause_type")
            or self._nested(normalized, "policyCitation", "clauseType")
            or self._nested(normalized, "policy_citation", "clauseType")
        )
        if not clause_type and rule_key in rules_by_key:
            rule = rules_by_key[rule_key]
            clause_type = rule.get("clauseType") or rule.get("clause_type")
        normalized["clauseType"] = str(clause_type or "OTHER").upper()
        normalized["severity"] = str(normalized.get("severity") or "MEDIUM").upper()
        normalized["status"] = str(normalized.get("status") or "OPEN").upper()
        return normalized

    def _rule_key(self, rule: dict[str, Any]) -> str:
        return str(rule.get("ruleKey") or rule.get("rule_key") or "").strip()

    def _finding_rule_key(self, finding: dict[str, Any]) -> str:
        return str(
            finding.get("ruleKey")
            or finding.get("rule_key")
            or self._nested(finding, "policyCitation", "ruleKey")
            or self._nested(finding, "policyCitation", "rule_key")
            or self._nested(finding, "policy_citation", "ruleKey")
            or self._nested(finding, "policy_citation", "rule_key")
            or ""
        ).strip()

    def _nested(self, source: dict[str, Any], field: str, key: str) -> Any:
        value = source.get(field)
        if isinstance(value, str):
            try:
                value = json.loads(value)
            except Exception:
                return None
        if not isinstance(value, dict):
            return None
        return value.get(key)
