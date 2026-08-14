# -*- coding: utf-8 -*-
"""Phase 0 wrap-up helper: pull baseline eval run status + metrics (runs 25-29).

Uses the backend's own connection pool (app.agent_runtime.persistence) so no
credentials are read or printed here — run from tools/chat-assistant/backend.
"""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                "tools", "chat-assistant", "backend"))

from app.agent_runtime.persistence import _conn

COLUMNS = (
    "id, dataset_id, status, runtime_engine, graph_name, graph_version, "
    "high_risk_recall, dual_citation_rate, false_positive_rate, schema_valid_rate, "
    "case_count, passed_count, current_case_index, started_at, finished_at"
)


def main() -> int:
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(f"SELECT {COLUMNS} FROM agent_eval_run WHERE id BETWEEN 25 AND 29 ORDER BY id")
            for row in cur.fetchall():
                print(row)

            print("\n-- summary_json keys per run --")
            cur.execute("SELECT id, summary_json FROM agent_eval_run WHERE id BETWEEN 25 AND 29 ORDER BY id")
            for row in cur.fetchall():
                raw = row["summary_json"]
                keys = []
                if raw:
                    try:
                        keys = sorted(json.loads(raw).keys())
                    except Exception:
                        keys = ["<unparseable>"]
                print(row["id"], keys)
    return 0


if __name__ == "__main__":
    sys.exit(main())
