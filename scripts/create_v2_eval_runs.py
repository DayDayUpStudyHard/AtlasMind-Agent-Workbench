# -*- coding: utf-8 -*-
"""Create the Phase 3 v2 pilot eval run rows (direct DB insert, no HTTP).

run 30: dataset 9  (风险审查回归集, 30 例) langgraph_v2 — v2 pilot vs run 25 (v1)
run 31: dataset 20 (Golden-风险审查回归集, 2 例) langgraph    — v1 golden gate
run 32: dataset 20 (Golden-风险审查回归集, 2 例) langgraph_v2 — v2 golden gate

Idempotent: skips ids that already exist. Rows sit QUEUED until a driver
process (scripts/run_v2_evals.py) consumes them — the in-service queue pump
only runs inside the API server process.
"""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                "tools", "chat-assistant", "backend"))

from app.agent_runtime.persistence import _conn

PLAN = [
    # id, dataset_id, runtime_engine, features
    # caseTimeoutSeconds 2400: v2 runs per-WU analysis (42 WorkUnits/case) —
    # the 900s default would time out slow cases.
    (30, 9, "langgraph_v2", {"targetedRetrievalRetries": 2, "v2AnalysisConcurrency": 4,
                             "v2SkipLlmOnNoEvidence": True, "caseTimeoutSeconds": 2400}),
    (31, 20, "langgraph", {"targetedRetrievalRetries": 2}),
    (32, 20, "langgraph_v2", {"targetedRetrievalRetries": 2, "v2AnalysisConcurrency": 4,
                              "v2SkipLlmOnNoEvidence": True, "caseTimeoutSeconds": 2400}),
]


def main() -> int:
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id, features_json FROM agent_eval_run WHERE id BETWEEN 30 AND 32")
            existing = {row["id"]: row["features_json"] for row in cur.fetchall()}
            for run_id, dataset_id, runtime, features in PLAN:
                features_json = json.dumps(features, ensure_ascii=False)
                if run_id in existing:
                    if existing[run_id] != features_json:
                        cur.execute(
                            "UPDATE agent_eval_run SET features_json=%s WHERE id=%s",
                            (features_json, run_id),
                        )
                        print(f"run {run_id}: features updated → {features}")
                    else:
                        print(f"run {run_id}: exists, features unchanged")
                    continue
                # started_at left NULL while QUEUED — the driver stamps the
                # real start on first touch (see _update_eval_progress).
                cur.execute(
                    "INSERT INTO agent_eval_run "
                    "(id, dataset_id, runtime_engine, status, features_json) "
                    "VALUES (%s, %s, %s, 'QUEUED', %s)",
                    (run_id, dataset_id, runtime, features_json),
                )
                print(f"run {run_id}: created (dataset {dataset_id}, {runtime}, {features})")
            conn.commit()
    return 0


if __name__ == "__main__":
    sys.exit(main())
