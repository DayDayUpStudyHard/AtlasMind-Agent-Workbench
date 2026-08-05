"""Evaluation dataset — loads YAML/JSON test cases with ground truth.

Each test case includes contract text, expected findings, expected citations,
and optional fulfillment requirements.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)


@dataclass
class ExpectedFinding:
    """A finding that the agent SHOULD produce for a test case."""

    title: str = ""
    severity: str = "HIGH"  # HIGH | MEDIUM | LOW
    clause_type: str = "OTHER"
    must_have_contract_citation: bool = True
    must_have_policy_citation: bool = True
    key_terms: list[str] = field(default_factory=list)


@dataclass
class EvalCase:
    """One test case in the evaluation dataset."""

    case_id: str
    contract_type: str = "SERVICE_PROCUREMENT"
    contract_text: str = ""
    title: str = ""
    description: str = ""
    expected_findings: list[ExpectedFinding] = field(default_factory=list)
    expected_citation_count: int = 0
    should_not_find: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


class EvaluationDataset:
    """Loads evaluation test cases from a directory of YAML or JSON files."""

    def __init__(self, dataset_path: str | Path):
        self.path = Path(dataset_path)
        self.cases: list[EvalCase] = []

    def load(self) -> list[EvalCase]:
        """Load all test cases from the dataset directory."""
        if not self.path.exists():
            logger.warning("Dataset path does not exist: %s", self.path)
            return []

        self.cases = []
        for file_path in sorted(self.path.glob("*.yaml")):
            self._load_file(file_path)
        for file_path in sorted(self.path.glob("*.yml")):
            if file_path.suffix == ".yml":
                self._load_file(file_path)
        for file_path in sorted(self.path.glob("*.json")):
            self._load_file(file_path)

        logger.info("Loaded %d eval cases from %s", len(self.cases), self.path)
        return self.cases

    def _load_file(self, file_path: Path) -> None:
        try:
            with open(file_path, encoding="utf-8") as fh:
                if file_path.suffix == ".json":
                    data = json.load(fh)
                else:
                    data = yaml.safe_load(fh)
        except Exception as exc:
            logger.warning("Failed to load %s: %s", file_path, exc)
            return

        cases_data = data if isinstance(data, list) else [data]
        for item in cases_data:
            if not isinstance(item, dict):
                continue
            try:
                case = self._parse_case(item, file_path.stem)
                self.cases.append(case)
            except Exception as exc:
                logger.warning("Failed to parse case in %s: %s", file_path, exc)

    @staticmethod
    def _parse_case(data: dict[str, Any], default_id: str) -> EvalCase:
        findings = []
        for f in data.get("expectedFindings") or []:
            findings.append(ExpectedFinding(
                title=str(f.get("title", "")),
                severity=str(f.get("severity", "HIGH")).upper(),
                clause_type=str(f.get("clauseType", "OTHER")).upper(),
                must_have_contract_citation=bool(f.get("mustHaveContractCitation", True)),
                must_have_policy_citation=bool(f.get("mustHavePolicyCitation", True)),
                key_terms=[str(t) for t in (f.get("keyTerms") or [])],
            ))

        return EvalCase(
            case_id=str(data.get("caseId", default_id)),
            contract_type=str(data.get("contractType", "SERVICE_PROCUREMENT")),
            contract_text=str(data.get("contractText", "")),
            title=str(data.get("title", "")),
            description=str(data.get("description", "")),
            expected_findings=findings,
            expected_citation_count=int(data.get("expectedCitationCount", 0)),
            should_not_find=[str(s) for s in (data.get("shouldNotFind") or [])],
            metadata=data.get("metadata") or {},
        )

    def by_type(self, contract_type: str) -> list[EvalCase]:
        """Filter cases by contract type."""
        return [c for c in self.cases if c.contract_type == contract_type]

    def high_risk_cases(self) -> list[EvalCase]:
        """Cases with at least one expected HIGH severity finding."""
        return [
            c for c in self.cases
            if any(f.severity == "HIGH" for f in c.expected_findings)
        ]
