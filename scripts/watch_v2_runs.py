# -*- coding: utf-8 -*-
"""Watch Phase 3 v2 eval runs 30-32: print one line per status change, exit
when all three reach a terminal state (with a final metrics dump). Poll loop
for the Monitor tool — no credentials read or printed; backend's own pool.
"""
import json
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                "tools", "chat-assistant", "backend"))

from app.agent_runtime.persistence import _conn

RUN_IDS = (30, 31, 32)
TERMINAL = {"COMPLETED", "FAILED", "CANCELED", "CRASHED", "DEGRADED"}


def snapshot() -> dict:
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, status, current_case_index, case_count, passed_count, "
                "high_risk_recall, dual_citation_rate, false_positive_rate, schema_valid_rate "
                "FROM agent_eval_run WHERE id BETWEEN 30 AND 32 ORDER BY id"
            )
            return {row["id"]: row for row in cur.fetchall()}


def main() -> int:
    seen: dict[int, str] = {run_id: "" for run_id in RUN_IDS}
    last_progress: dict[int, int] = {}
    while True:
        try:
            rows = snapshot()
        except Exception as exc:
            print(f"poll error: {exc!r}", flush=True)
            time.sleep(30)
            continue
        all_terminal = True
        for run_id in RUN_IDS:
            row = rows.get(run_id) or {}
            status = str(row.get("status") or "MISSING")
            if status not in TERMINAL:
                all_terminal = False
            if status != seen[run_id]:
                print(f"run {run_id}: {status} (case {row.get('current_case_index')}/"
                      f"{row.get('case_count')}, passed {row.get('passed_count')})", flush=True)
                seen[run_id] = status
            elif status == "RUNNING":
                progress = int(row.get("current_case_index") or 0)
                if progress != last_progress.get(run_id, -1):
                    print(f"run {run_id}: RUNNING case {progress}/{row.get('case_count')}", flush=True)
                    last_progress[run_id] = progress
        if all_terminal:
            print("all v2 eval runs terminal — final metrics:", flush=True)
            for run_id in RUN_IDS:
                row = rows.get(run_id) or {}
                print(f"run {run_id}: {row.get('status')} recall={row.get('high_risk_recall')} "
                      f"dual={row.get('dual_citation_rate')} fp={row.get('false_positive_rate')} "
                      f"schema={row.get('schema_valid_rate')} passed={row.get('passed_count')}/"
                      f"{row.get('case_count')}", flush=True)
            return 0
        time.sleep(30)


if __name__ == "__main__":
    sys.exit(main())
