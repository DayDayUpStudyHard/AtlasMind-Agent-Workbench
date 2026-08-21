"""Import and queue the local ContractOps core benchmark suites.

This deliberately uses the running Python service's single evaluation queue.
It does not run several expensive live suites in parallel or expose the
internal token in console output.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ROOT = ROOT / "benchmark-private" / "core-v1"
DIRECTORIES = ("intake-v1", "elements-v1", "timeline-v1", "risk-v1", "fulfillment-v1")
DEFAULT_FEATURES = {
    "temperature": 0,
    "rerank": True,
    "requireElasticsearch": True,
    "allowMysqlRetrievalFallback": False,
    "targetedRetrievalRetries": 1,
    "coverageReflection": True,
    "caseTimeoutSeconds": 900,
}


def main() -> int:
    parser = argparse.ArgumentParser(description="Queue local private ContractOps benchmark suites")
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    parser.add_argument(
        "--only",
        nargs="+",
        choices=DIRECTORIES,
        help="queue only the named suites; defaults to all five suites",
    )
    args = parser.parse_args()

    from app.api.routes import run_migrations
    from app.config import settings
    from app.agent_runtime.evaluation.benchmark import load_benchmark_dataset
    from app.agent_runtime.evaluation.cli import (
        _create_eval_run,
        _import_dataset_snapshot,
        build_experiment_snapshot,
    )

    asyncio.run(run_migrations())
    if not settings.internal_token:
        raise SystemExit("CHAT_ASSISTANT_TOKEN is required to queue benchmark runs")

    queued: list[dict[str, object]] = []
    for directory in (tuple(args.only) if args.only else DIRECTORIES):
        dataset = load_benchmark_dataset(args.root / directory)
        dataset_id = _import_dataset_snapshot(dataset)
        snapshot = build_experiment_snapshot(
            dataset, engine="langgraph", profile="live",
            features=DEFAULT_FEATURES, baseline_run_id=None,
        )
        run_id = _create_eval_run(dataset_id, snapshot)
        body = json.dumps({"evalRunId": run_id}).encode("utf-8")
        request = Request(
            "http://localhost:18088/internal/agent/evaluations/run",
            data=body,
            headers={
                "Content-Type": "application/json",
                "X-Internal-Token": settings.internal_token,
            },
            method="POST",
        )
        with urlopen(request, timeout=15) as response:
            response_body = json.loads(response.read().decode("utf-8"))
        queued.append({
            "dataset": dataset.dataset_id,
            "datasetId": dataset_id,
            "runId": run_id,
            "status": response_body.get("status"),
            "caseCount": len(dataset.cases),
        })
    print(json.dumps({"queued": queued}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
