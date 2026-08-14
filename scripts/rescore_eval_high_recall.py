# -*- coding: utf-8 -*-
"""Rescore stored eval high_recall with the fixed dimension-normalization
matcher — no re-runs, artifacts come from existing agent_eval_result rows.

The 2026-08-14 scorer fix (routes.py _risk_dimension/_risk_finding_matches):
domainKey-before-clauseType normalization + dimension bucket map + strong
text-evidence bypass. Official values are preserved in summary_json under
`officialHighRiskRecall` before rewriting.

Usage:
  python scripts/rescore_eval_high_recall.py --dry-run   # preview only
  python scripts/rescore_eval_high_recall.py             # apply
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                "tools", "chat-assistant", "backend"))

from app.agent_runtime.persistence import _conn  # noqa: E402
from app.api.routes import _score_eval_artifact  # noqa: E402

RUN_IDS = (25, 30, 36)

RESCORE_NOTE = (
    "highRiskRecall 已于 2026-08-14 用修复后的评分器重算（维度规范化："
    "domainKey 优先 + 维度桶映射 + 强文本旁路，见 scripts/rescore_eval_high_recall.py）。"
    "官方原值保留在 officialHighRiskRecall；未重跑任何用例，"
    "artifact 全部来自存量 result_json。"
)


def rescore(dry_run: bool) -> None:
    for run_id in RUN_IDS:
        with _conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT summary_json, high_risk_recall, status "
                            "FROM agent_eval_run WHERE id=%s", (run_id,))
                run_row = cur.fetchone()
                if not run_row:
                    print(f"[run {run_id}] missing, skip", flush=True)
                    continue
                summary = json.loads(run_row["summary_json"] or "{}")
                old_run_recall = run_row["high_risk_recall"]

                cur.execute("SELECT case_id, high_recall, dual_citation_rate, "
                            "false_positives, result_json FROM agent_eval_result "
                            "WHERE run_id=%s ORDER BY case_id", (run_id,))
                result_rows = cur.fetchall()

                case_recalls: dict[int, float] = {}
                changed = []
                abort = False
                for rr in result_rows:
                    cur.execute("SELECT expected_findings_json FROM agent_eval_case WHERE id=%s",
                                (rr["case_id"],))
                    case_row = cur.fetchone()
                    case = {"expected_findings_json": case_row["expected_findings_json"]}
                    artifact = json.loads(rr["result_json"] or "{}")
                    score = _score_eval_artifact(case, artifact, "CONTRACT_REVIEW")
                    new_recall = score["highRecall"]
                    # the matcher change must not move these: verify before writing
                    if (abs(score["dualCitationRate"] - float(rr["dual_citation_rate"] or 0)) > 1e-9
                            or score["falsePositives"] != int(rr["false_positives"] or 0)):
                        print(f"[run {run_id} case {rr['case_id']}] ABORT: dc/fp recomputed "
                              f"({score['dualCitationRate']:.6f}/{score['falsePositives']}) "
                              f"!= stored ({rr['dual_citation_rate']}/{rr['false_positives']})",
                              flush=True)
                        abort = True
                        break
                    case_recalls[rr["case_id"]] = new_recall
                    if abs(new_recall - float(rr["high_recall"] or 0)) > 1e-9:
                        changed.append((rr["case_id"], rr["high_recall"], new_recall))
                if abort:
                    continue

                n = len(case_recalls)
                new_avg = sum(case_recalls.values()) / n if n else 0.0
                print(f"\n[run {run_id}] cases={n} per-case changed={len(changed)}", flush=True)
                for cid, old, new in changed:
                    print(f"    case {cid}: {old} -> {new}", flush=True)
                print(f"    run recall: official={old_run_recall} -> rescaled={new_avg:.4f}",
                      flush=True)

                if dry_run:
                    continue

                # 1) per-case high_recall
                for cid, old, new in changed:
                    cur.execute("UPDATE agent_eval_result SET high_recall=%s "
                                "WHERE run_id=%s AND case_id=%s", (new, run_id, cid))

                # 2) summary_json: preserve official value + add rescore note
                if run_id == 30:
                    # manually finalized partial run: recall lives in
                    # partialMetrics; official == rescaled (no per-case change)
                    pm = summary.get("partialMetrics") or {}
                    if "officialHighRiskRecall" not in pm:
                        pm["officialHighRiskRecall"] = pm.get("highRiskRecall")
                    pm["highRiskRecall"] = round(new_avg, 4)
                    summary["partialMetrics"] = pm
                else:
                    if "officialHighRiskRecall" not in summary:
                        summary["officialHighRiskRecall"] = (
                            round(old_run_recall, 4) if old_run_recall is not None
                            else summary.get("highRiskRecall"))
                    summary["highRiskRecall"] = round(new_avg, 4)
                summary["rescore"] = {
                    "appliedAt": "2026-08-14",
                    "note": RESCORE_NOTE,
                    "runsRescored": list(RUN_IDS),
                    "casesChanged": [{"caseId": c, "from": o, "to": new} for c, o, new in changed],
                }
                cur.execute("UPDATE agent_eval_run SET summary_json=%s WHERE id=%s",
                            (json.dumps(summary, ensure_ascii=False), run_id))

                # 3) run-level recall column (run 30 stays manually finalized)
                if run_id != 30:
                    cur.execute("UPDATE agent_eval_run SET high_risk_recall=%s WHERE id=%s",
                                (new_avg, run_id))
                conn.commit()
                print(f"    applied: high_risk_recall={new_avg:.4f}", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="preview only, no writes")
    args = parser.parse_args()
    rescore(dry_run=args.dry_run)
