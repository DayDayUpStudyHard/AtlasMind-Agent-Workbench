"""Versioned, file-backed benchmark datasets for ContractOps.

The database records execution history, while a benchmark directory is the
immutable source of truth for the inputs and expected outputs of an experiment.
"""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
from pathlib import Path
import re
from typing import Any

import yaml


_DATASET_ID = re.compile(r"^[a-z0-9][a-z0-9-]*$")
_TASK_TYPES = {
    "CONTRACT_REVIEW",
    "CONTRACT_ELEMENT_EXTRACTION",
    "TIMELINE_EXTRACTION",
    "FULFILLMENT_CHECK",
    "COMPREHENSIVE",
}
_SEVERITIES = {"HIGH", "MEDIUM", "LOW"}


class BenchmarkDatasetError(ValueError):
    """Raised when a benchmark directory cannot be safely executed."""


def canonical_json(value: Any) -> str:
    """Serialize JSON data with stable ordering for content-addressing."""
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


@dataclass(frozen=True)
class BenchmarkCase:
    case_id: str
    source_path: Path
    raw: dict[str, Any]


@dataclass(frozen=True)
class BenchmarkDataset:
    root: Path
    manifest: dict[str, Any]
    cases: tuple[BenchmarkCase, ...]
    dataset_hash: str

    @property
    def dataset_id(self) -> str:
        return str(self.manifest["id"])

    @property
    def task_type(self) -> str:
        return str(self.manifest["taskType"])

    def report(self) -> dict[str, Any]:
        return {
            "datasetId": self.dataset_id,
            "name": self.manifest["name"],
            "version": self.manifest["version"],
            "schemaVersion": self.manifest["schemaVersion"],
            "taskType": self.task_type,
            "caseCount": len(self.cases),
            "datasetHash": self.dataset_hash,
            "cases": [case.case_id for case in self.cases],
        }


def load_benchmark_dataset(path: str | Path) -> BenchmarkDataset:
    """Load and validate a manifest-based benchmark dataset directory."""
    root = Path(path).resolve()
    manifest_path = root / "manifest.yaml"
    if not manifest_path.is_file():
        raise BenchmarkDatasetError(f"missing manifest: {manifest_path}")

    manifest = _load_mapping(manifest_path, "manifest")
    _validate_manifest(manifest)
    case_paths = _case_paths(root, manifest)
    if not case_paths:
        raise BenchmarkDatasetError("dataset contains no case files")

    seen: set[str] = set()
    cases: list[BenchmarkCase] = []
    for case_path in case_paths:
        raw = _load_mapping(case_path, "case")
        case_id = _validate_case(raw, case_path)
        if case_id in seen:
            raise BenchmarkDatasetError(f"duplicate caseId {case_id!r}")
        seen.add(case_id)
        cases.append(BenchmarkCase(case_id=case_id, source_path=case_path, raw=raw))

    cases.sort(key=lambda case: case.case_id)
    canonical = {
        "manifest": manifest,
        "cases": [{"caseId": case.case_id, "data": case.raw} for case in cases],
    }
    return BenchmarkDataset(
        root=root,
        manifest=manifest,
        cases=tuple(cases),
        dataset_hash=sha256(canonical_json(canonical).encode("utf-8")).hexdigest(),
    )


def _load_mapping(path: Path, label: str) -> dict[str, Any]:
    try:
        loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise BenchmarkDatasetError(f"cannot read {label} {path}: {exc}") from exc
    except yaml.YAMLError as exc:
        raise BenchmarkDatasetError(f"invalid YAML in {path}: {exc}") from exc
    if not isinstance(loaded, dict):
        raise BenchmarkDatasetError(f"{label} {path} must be a YAML mapping")
    return loaded


def _validate_manifest(manifest: dict[str, Any]) -> None:
    required = ("schemaVersion", "id", "name", "version", "taskType")
    missing = [key for key in required if not str(manifest.get(key) or "").strip()]
    if missing:
        raise BenchmarkDatasetError(f"manifest missing required fields: {', '.join(missing)}")
    if manifest["schemaVersion"] != 1:
        raise BenchmarkDatasetError("unsupported schemaVersion; expected 1")
    if not _DATASET_ID.fullmatch(str(manifest["id"])):
        raise BenchmarkDatasetError("manifest id must use lowercase letters, digits, and hyphens")
    task_type = str(manifest["taskType"]).upper()
    if task_type not in _TASK_TYPES:
        raise BenchmarkDatasetError(f"unsupported taskType {task_type!r}")
    manifest["taskType"] = task_type


def _case_paths(root: Path, manifest: dict[str, Any]) -> list[Path]:
    configured = manifest.get("caseFiles")
    if configured is not None:
        if not isinstance(configured, list) or not all(isinstance(item, str) for item in configured):
            raise BenchmarkDatasetError("manifest caseFiles must be a list of relative paths")
        paths = []
        for item in configured:
            candidate = (root / item).resolve()
            if root not in candidate.parents or candidate.suffix not in {".yaml", ".yml"}:
                raise BenchmarkDatasetError(f"invalid case path {item!r}")
            paths.append(candidate)
        return paths

    case_dir = (root / str(manifest.get("caseDirectory") or "cases")).resolve()
    if root != case_dir and root not in case_dir.parents:
        raise BenchmarkDatasetError("caseDirectory must stay within the dataset directory")
    if not case_dir.is_dir():
        raise BenchmarkDatasetError(f"case directory does not exist: {case_dir}")
    return sorted([*case_dir.rglob("*.yaml"), *case_dir.rglob("*.yml")])


def _validate_case(case: dict[str, Any], source_path: Path) -> str:
    case_id = str(case.get("caseId") or "").strip()
    if not case_id:
        raise BenchmarkDatasetError(f"case {source_path} is missing caseId")
    if not str(case.get("contractText") or "").strip():
        raise BenchmarkDatasetError(f"case {case_id} has no contractText")
    findings = case.get("expectedFindings")
    if not isinstance(findings, list):
        raise BenchmarkDatasetError(f"case {case_id} expectedFindings must be a list")
    for index, finding in enumerate(findings, start=1):
        if not isinstance(finding, dict) or not str(finding.get("title") or "").strip():
            raise BenchmarkDatasetError(f"case {case_id} finding #{index} needs a title")
        severity = str(finding.get("severity") or "").upper()
        if severity not in _SEVERITIES:
            raise BenchmarkDatasetError(
                f"case {case_id} finding #{index} severity must be HIGH, MEDIUM, or LOW"
            )
        finding["severity"] = severity
    if not isinstance(case.get("shouldNotFind", []), list):
        raise BenchmarkDatasetError(f"case {case_id} shouldNotFind must be a list")
    citation_count = case.get("expectedCitationCount", 0)
    if not isinstance(citation_count, int) or citation_count < 0:
        raise BenchmarkDatasetError(f"case {case_id} expectedCitationCount must be a non-negative integer")
    return case_id
