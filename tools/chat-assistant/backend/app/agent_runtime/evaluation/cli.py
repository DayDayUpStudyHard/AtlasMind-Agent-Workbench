"""Command-line interface for reproducible ContractOps benchmarks.

Examples:
    python -m app.agent_runtime.evaluation.cli validate --dataset benchmarks/contract-review-v1
    python -m app.agent_runtime.evaluation.cli run --dataset benchmarks/contract-review-v1 --engine langgraph
    python -m app.agent_runtime.evaluation.cli compare --left-run 101 --right-run 102
"""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
import subprocess
import sys
from typing import Any

from .benchmark import BenchmarkDataset, BenchmarkDatasetError, canonical_json, load_benchmark_dataset
from .metrics import build_release_gate
from .specs import legacy_expected_findings
from .versioning import EVAL_SCORER_VERSION


def build_experiment_snapshot(
    dataset: BenchmarkDataset,
    *,
    engine: str,
    profile: str,
    features: dict[str, Any],
    baseline_run_id: int | None,
) -> dict[str, Any]:
    """Build the immutable config recorded before an evaluation starts."""
    snapshot = {
        "datasetId": dataset.dataset_id,
        "datasetHash": dataset.dataset_hash,
        "engine": engine,
        "profile": profile,
        "features": features,
        "baselineRunId": baseline_run_id,
        "gitCommit": _git_commit(),
        "scorerVersion": EVAL_SCORER_VERSION,
    }
    snapshot["configHash"] = _sha256(snapshot)
    return snapshot


def compare_snapshots(
    left: dict[str, Any], right: dict[str, Any], *, allow_incompatible: bool = False
) -> dict[str, Any]:
    """Compare two completed runs without silently mixing benchmark contracts."""
    compatibility = {
        "datasetHash": left.get("datasetHash") == right.get("datasetHash"),
        "scorerVersion": left.get("scorerVersion") == right.get("scorerVersion"),
    }
    if not allow_incompatible and not all(compatibility.values()):
        failed = ", ".join(key for key, matches in compatibility.items() if not matches)
        raise BenchmarkDatasetError(f"runs are not comparable: {failed} differs")

    left_summary = left.get("summary") or {}
    right_summary = right.get("summary") or {}
    left_task_metrics = left_summary.get("taskMetrics") if isinstance(left_summary.get("taskMetrics"), dict) else {}
    right_task_metrics = right_summary.get("taskMetrics") if isinstance(right_summary.get("taskMetrics"), dict) else {}
    metric_keys = tuple(sorted(set(left_task_metrics) | set(right_task_metrics))) or (
        "highRiskRecall", "dualCitationRate", "falsePositiveRate", "schemaValidRate",
    )
    left_metrics = left_task_metrics or left_summary
    right_metrics = right_task_metrics or right_summary
    return {
        "leftRunId": left.get("runId"),
        "rightRunId": right.get("runId"),
        "compatible": all(compatibility.values()),
        "compatibility": compatibility,
        "metrics": {
            key: {
                "left": left_metrics.get(key),
                "right": right_metrics.get(key),
                "delta": _metric_delta(left_metrics.get(key), right_metrics.get(key)),
            }
            for key in metric_keys
        },
        "operations": _compare_operations(left_summary.get("operations") or {}, right_summary.get("operations") or {}),
    }


def _compare_operations(left: dict[str, Any], right: dict[str, Any]) -> dict[str, Any]:
    keys = (
        "latencyP50Ms", "latencyP95Ms", "latencyTotalMs", "nodeLatencyTotalMs",
        "tokenInputTotal", "tokenOutputTotal", "estimatedCost",
    )
    return {
        key: {
            "left": left.get(key),
            "right": right.get(key),
            "delta": _metric_delta(left.get(key), right.get(key)),
        }
        for key in keys
    } | {
        "costStatus": {"left": left.get("costStatus"), "right": right.get("costStatus")},
        "latencyStatus": {"left": left.get("latencyStatus"), "right": right.get("latencyStatus")},
        "tokenStatus": {"left": left.get("tokenStatus"), "right": right.get("tokenStatus")},
    }


def _metric_delta(left: Any, right: Any) -> float | None:
    if left is None or right is None:
        return None
    return round(float(right) - float(left), 4)


def _sha256(value: Any) -> str:
    from hashlib import sha256

    return sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _git_commit() -> str:
    workspace = Path(__file__).resolve().parents[6]
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=workspace, text=True, stderr=subprocess.DEVNULL
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def _parse_features(raw: str) -> dict[str, Any]:
    try:
        features = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise BenchmarkDatasetError(f"--features must be valid JSON: {exc.msg}") from exc
    if not isinstance(features, dict):
        raise BenchmarkDatasetError("--features must be a JSON object")
    return features


async def _run(args: argparse.Namespace, dataset: BenchmarkDataset) -> dict[str, Any]:
    # Keep command-line runs compatible with a clean local database.
    from app.api.routes import _run_evaluation_background, run_migrations

    await run_migrations()
    snapshot = build_experiment_snapshot(
        dataset,
        engine=args.engine,
        profile=args.profile,
        features=_parse_features(args.features),
        baseline_run_id=args.baseline_run,
    )
    dataset_row_id = _import_dataset_snapshot(dataset)
    eval_run_id = _create_eval_run(dataset_row_id, snapshot)
    await _run_evaluation_background(eval_run_id)
    result = _fetch_run_snapshot(eval_run_id)
    result["experiment"] = snapshot
    return result


def _import_dataset_snapshot(dataset: BenchmarkDataset) -> int:
    from app.agent_runtime.persistence import _conn

    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id FROM agent_eval_dataset WHERE dataset_hash=%s ORDER BY id DESC LIMIT 1",
                (dataset.dataset_hash,),
            )
            existing = cur.fetchone()
            if existing:
                # Repair snapshots imported before the fulfillment-specific
                # columns were wired into the importer. Keep the dataset
                # identity stable while restoring its declared case inputs.
                dataset_id = int(existing["id"])
                for case in dataset.cases:
                    raw = case.raw
                    if not any(
                        raw.get(key) is not None
                        for key in (
                            "targetTimelineSelectorJson",
                            "fulfillmentEvidenceJson",
                            "expectedJudgementsJson",
                            "expectedManualResult",
                        )
                    ):
                        continue
                    cur.execute(
                        """UPDATE agent_eval_case
                           SET fulfillment_evidence_json=%s,
                               target_timeline_selector_json=%s,
                               expected_judgements_json=%s,
                               expected_manual_result=%s
                           WHERE dataset_id=%s AND case_key=%s""",
                        (
                            canonical_json(raw.get("fulfillmentEvidenceJson") or []),
                            canonical_json(raw.get("targetTimelineSelectorJson") or {}),
                            canonical_json(raw.get("expectedJudgementsJson") or []),
                            str(raw.get("expectedManualResult") or "").upper(),
                            dataset_id,
                            case.case_id,
                        ),
                    )
                conn.commit()
                return dataset_id

            cur.execute(
                """INSERT INTO agent_eval_dataset
                   (name, version, description, contract_type, task_purpose, case_count, status,
                    dataset_hash, schema_version, source_uri, published_at, benchmark_profile_json,
                    label_status, private_corpus, target_case_count)
                   VALUES (%s,%s,%s,%s,%s,%s,'FROZEN',%s,%s,%s,NOW(),%s,%s,%s,%s)""",
                (
                    dataset.manifest["name"],
                    dataset.manifest["version"],
                    str(dataset.manifest.get("description") or ""),
                    dataset.task_type,
                    dataset.task_type,
                    len(dataset.cases),
                    dataset.dataset_hash,
                    int(dataset.manifest["schemaVersion"]),
                    dataset.root.as_posix(),
                    canonical_json(dataset.manifest.get("profile") or {}),
                    str(dataset.manifest.get("labelStatus") or "APPROVED").upper(),
                    int(bool(dataset.manifest.get("privateCorpus", False))),
                    int(dataset.manifest.get("targetCaseCount") or len(dataset.cases)),
                ),
            )
            dataset_id = int(cur.lastrowid)
            for case in dataset.cases:
                raw = case.raw
                cur.execute(
                    """INSERT INTO agent_eval_case
                       (dataset_id, case_key, title, contract_type, contract_text,
                        expected_findings_json, should_not_find_json, expected_citation_count,
                        scenario, industry, difficulty, noise_level,
                        must_have_contract_citation, must_have_policy_citation,
                        expected_output_json, annotation_status, candidate_label_json,
                        label_provider, label_model, label_prompt_version,
                        fulfillment_evidence_json, target_timeline_selector_json,
                        expected_judgements_json, expected_manual_result, status)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'ACTIVE')""",
                    (
                        dataset_id,
                        case.case_id,
                        str(raw.get("title") or case.case_id),
                        str(raw.get("contractType") or "SERVICE_PROCUREMENT"),
                        str(raw["contractText"]),
                        canonical_json(raw.get("expectedFindings") or legacy_expected_findings(
                            {"expected_output_json": canonical_json(raw.get("expected") or {})}, dataset.task_type
                        )),
                        canonical_json(raw.get("shouldNotFind") or []),
                        int(raw.get("expectedCitationCount") or 0),
                        str(raw.get("scenario") or ""),
                        str(raw.get("industry") or ""),
                        str(raw.get("difficulty") or ""),
                        str(raw.get("noiseLevel") or ""),
                        int(bool(raw.get("mustHaveContractCitation", False))),
                        int(bool(raw.get("mustHavePolicyCitation", False))),
                        canonical_json(raw.get("expected") or {}),
                        str(raw.get("annotationStatus") or dataset.manifest.get("labelStatus") or "APPROVED").upper(),
                        canonical_json(raw.get("candidateLabel") or {}),
                        str((raw.get("labelSource") or {}).get("provider") or ""),
                        str((raw.get("labelSource") or {}).get("model") or ""),
                        str((raw.get("labelSource") or {}).get("promptVersion") or ""),
                        canonical_json(raw.get("fulfillmentEvidenceJson") or []),
                        canonical_json(raw.get("targetTimelineSelectorJson") or {}),
                        canonical_json(raw.get("expectedJudgementsJson") or []),
                        str(raw.get("expectedManualResult") or "").upper(),
                    ),
                )
            conn.commit()
            return dataset_id


def _create_eval_run(dataset_id: int, snapshot: dict[str, Any]) -> int:
    from app.agent_runtime.persistence import _conn

    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO agent_eval_run
                   (dataset_id, runtime_engine, features_json, status, started_at,
                    dataset_hash, config_hash, profile, git_commit, baseline_run_id, scorer_version)
                   VALUES (%s,%s,%s,'QUEUED',NOW(),%s,%s,%s,%s,%s,%s)""",
                (
                    dataset_id,
                    snapshot["engine"],
                    canonical_json(snapshot["features"]),
                    snapshot["datasetHash"],
                    snapshot["configHash"],
                    snapshot["profile"],
                    snapshot["gitCommit"],
                    snapshot["baselineRunId"],
                    snapshot["scorerVersion"],
                ),
            )
            run_id = int(cur.lastrowid)
            conn.commit()
            return run_id


def _fetch_run_snapshot(run_id: int) -> dict[str, Any]:
    from app.agent_runtime.persistence import _conn

    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT id, dataset_hash, config_hash, profile, git_commit, scorer_version,
                          status, summary_json, started_at, finished_at,
                          latency_p50_ms, latency_p95_ms, token_input_total,
                          token_output_total, estimated_cost, cost_currency, cost_status,
                          execution_stack_json
                   FROM agent_eval_run WHERE id=%s""",
                (run_id,),
            )
            row = cur.fetchone()
    if not row:
        raise BenchmarkDatasetError(f"evaluation run {run_id} not found")
    try:
        summary = json.loads(row.get("summary_json") or "{}")
    except json.JSONDecodeError:
        summary = {"rawSummary": row.get("summary_json")}
    operations = summary.get("operations")
    if not isinstance(operations, dict):
        operations = {}
    operations.setdefault("latencyP50Ms", row.get("latency_p50_ms"))
    operations.setdefault("latencyP95Ms", row.get("latency_p95_ms"))
    operations.setdefault("tokenInputTotal", row.get("token_input_total"))
    operations.setdefault("tokenOutputTotal", row.get("token_output_total"))
    operations.setdefault("estimatedCost", row.get("estimated_cost"))
    operations.setdefault("costCurrency", row.get("cost_currency"))
    operations.setdefault("costStatus", row.get("cost_status"))
    try:
        operations.setdefault("executionStack", json.loads(row.get("execution_stack_json") or "{}"))
    except (TypeError, json.JSONDecodeError):
        operations.setdefault("executionStack", {})
    summary["operations"] = operations
    # Older database rows predate the release gate. Derive it on read so CLI
    # output remains stable across historical and newly-created runs.
    if not isinstance(summary.get("releaseGate"), dict):
        summary["releaseGate"] = build_release_gate(summary, status=str(row.get("status") or ""))
    return {
        "runId": int(row["id"]),
        "datasetHash": str(row.get("dataset_hash") or ""),
        "configHash": str(row.get("config_hash") or ""),
        "profile": str(row.get("profile") or ""),
        "gitCommit": str(row.get("git_commit") or ""),
        "scorerVersion": str(row.get("scorer_version") or EVAL_SCORER_VERSION),
        "status": str(row.get("status") or ""),
        "startedAt": str(row.get("started_at") or ""),
        "finishedAt": str(row.get("finished_at") or ""),
        "summary": summary,
        "operations": operations,
    }


def _markdown(value: dict[str, Any]) -> str:
    lines = [f"# Benchmark report\n", f"- Left run: `{value.get('leftRunId', value.get('runId', ''))}`"]
    if "rightRunId" in value:
        lines.append(f"- Right run: `{value['rightRunId']}`")
    if "compatible" in value:
        lines.append(f"- Comparable: `{value['compatible']}`")
    for section in ("metrics", "operations"):
        data = value.get(section)
        if not isinstance(data, dict):
            continue
        lines.extend([f"\n## {section.title()}", "", "| Metric | Left | Right | Delta |", "|---|---:|---:|---:|"])
        for key, item in data.items():
            if not isinstance(item, dict):
                continue
            lines.append(f"| `{key}` | {item.get('left', '')} | {item.get('right', '')} | {item.get('delta', '')} |")
    if "summary" in value:
        lines.extend(["\n## Summary", "", "```json", json.dumps(value["summary"], ensure_ascii=False, indent=2, default=str), "```"])
    return "\n".join(lines) + "\n"


def _write_output(value: dict[str, Any], output: str | None, output_format: str = "json") -> None:
    serialized = _markdown(value) if output_format == "markdown" else json.dumps(value, ensure_ascii=False, indent=2, default=str) + "\n"
    if output:
        path = Path(output)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(serialized, encoding="utf-8")
    print(serialized, end="")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run reproducible ContractOps benchmarks")
    commands = parser.add_subparsers(dest="command", required=True)

    validate = commands.add_parser("validate", help="validate a file-backed benchmark dataset")
    validate.add_argument("--dataset", required=True)
    validate.add_argument("--output")

    run = commands.add_parser("run", help="freeze, run, and report an evaluation")
    run.add_argument("--dataset", required=True)
    run.add_argument("--engine", choices=("legacy", "langgraph", "langgraph_v2"), default="langgraph")
    run.add_argument("--profile", choices=("live",), default="live")
    run.add_argument("--features", default="{}", help="JSON object passed to the production evaluator")
    run.add_argument("--baseline-run", type=int)
    run.add_argument("--output")
    run.add_argument("--format", choices=("json", "markdown"), default="json")

    compare = commands.add_parser("compare", help="compare completed evaluation runs")
    compare.add_argument("--left-run", required=True, type=int)
    compare.add_argument("--right-run", required=True, type=int)
    compare.add_argument("--allow-incompatible", action="store_true")
    compare.add_argument("--output")
    compare.add_argument("--format", choices=("json", "markdown"), default="json")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        if args.command == "validate":
            _write_output(load_benchmark_dataset(args.dataset).report(), args.output)
            return 0
        if args.command == "run":
            dataset = load_benchmark_dataset(args.dataset)
            _write_output(asyncio.run(_run(args, dataset)), args.output, args.format)
            return 0
        if args.command == "compare":
            left = _fetch_run_snapshot(args.left_run)
            right = _fetch_run_snapshot(args.right_run)
            _write_output(compare_snapshots(left, right, allow_incompatible=args.allow_incompatible), args.output, args.format)
            return 0
    except BenchmarkDatasetError as exc:
        print(f"benchmark error: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:
        print(f"benchmark failed: {exc}", file=sys.stderr)
        return 1
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
