# -*- coding: utf-8 -*-
"""Rescore stored eval high_recall for EVERY run that has stored artifacts
with the fixed dimension-normalization matcher — no re-runs, artifacts come
from existing agent_eval_result rows.

The 2026-08-14 scorer fix (routes.py _risk_dimension/_risk_finding_matches):
domainKey-before-clauseType normalization + dimension bucket map + strong
text-evidence bypass. Official values are preserved in summary_json under
`officialHighRiskRecall` before rewriting. Idempotent: runs whose per-case
recall does not change (incl. already-rescored ones) are left untouched.

Safety guards: dual_citation_rate / false_positives are recomputed with the
same scorer and must equal stored values, otherwise the run is skipped and
reported (the matcher fix must not move dc/fp).

Usage:
  python scripts/rescore_eval_high_recall.py --dry-run   # preview only
  python scripts/rescore_eval_high_recall.py             # apply
"""
import argparse
import json
import os
import sys
import traceback

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                "tools", "chat-assistant", "backend"))

from app.agent_runtime.persistence import _conn  # noqa: E402
from app.api.routes import _score_eval_artifact  # noqa: E402

RESCORE_NOTE = (
    "highRiskRecall 已于 2026-08-14 用修复后的评分器全量重算（维度规范化："
    "domainKey 优先 + 维度桶映射 + 强文本旁路，见 scripts/rescore_eval_high_recall.py）。"
    "官方原值保留在 officialHighRiskRecall；未重跑任何用例，"
    "artifact 全部来自存量 result_json。"
)

# Only contract-review datasets: 9=风险审查回归集, 20=Golden-风险审查回归集,
# 23=v1 丢分难例复测集. Other datasets (要素提取/履约日程/履约核验/压力测试)
# have non-risk-review artifacts where this scorer does not apply.
RISK_REVIEW_DATASETS = (9, 20, 23)


def _runs_with_artifacts(cur) -> list[int]:
    cur.execute(
        "SELECT DISTINCT run_id FROM agent_eval_result "
        "WHERE result_json IS NOT NULL AND result_json <> '' AND result_json <> '{}' "
        "ORDER BY run_id"
    )
    return [r["run_id"] for r in cur.fetchall()]


def _compute_run(cur, run_id: int):
    """Read one run's stored results and recompute per-case scores.

    Returns None when the run must be skipped (missing rows / dc-fp guard
    failure / scorer exception); otherwise a dict with the recomputed state.
    """
    cur.execute("SELECT summary_json, high_risk_recall, status, dataset_id "
                "FROM agent_eval_run WHERE id=%s", (run_id,))
    run_row = cur.fetchone()
    if not run_row:
        print(f"[run {run_id}] missing run row, skip", flush=True)
        return None
    if run_row["dataset_id"] not in RISK_REVIEW_DATASETS:
        print(f"[run {run_id}] skip: dataset {run_row['dataset_id']} is not contract review",
              flush=True)
        return None
    summary = json.loads(run_row["summary_json"] or "{}")
    partial = run_row["high_risk_recall"] is None and bool(summary.get("partialMetrics"))

    cur.execute(
        "SELECT case_id, high_recall, dual_citation_rate, false_positives, result_json "
        "FROM agent_eval_result WHERE run_id=%s "
        "AND result_json IS NOT NULL AND result_json <> '' AND result_json <> '{}' "
        "ORDER BY case_id", (run_id,))
    result_rows = cur.fetchall()

    case_recalls: dict[int, float] = {}
    changed: list[tuple[int, object, float]] = []
    excluded: list[dict] = []
    for rr in result_rows:
        cur.execute("SELECT expected_findings_json, should_not_find_json "
                    "FROM agent_eval_case WHERE id=%s", (rr["case_id"],))
        case_row = cur.fetchone()
        if not case_row:
            print(f"[run {run_id} case {rr['case_id']}] skip: case row missing", flush=True)
            return None
        case = {
            "expected_findings_json": case_row["expected_findings_json"],
            "should_not_find_json": case_row["should_not_find_json"],
        }
        artifact = json.loads(rr["result_json"] or "{}")

        # Unscoreable rows are kept at their stored value inside the average
        # (same denominator as the official recall) instead of being scored
        # vacuous 1.0s: an empty findings list (infra-failed shell artifacts)
        # or an empty expected-HIGH list make recall meaningless.
        findings = artifact.get("findings") or []
        if not isinstance(findings, list) or not findings:
            excluded.append({"caseId": rr["case_id"], "reason": "artifact has no findings"})
            case_recalls[rr["case_id"]] = float(rr["high_recall"] or 0)
            continue
        try:
            expected = json.loads(case_row["expected_findings_json"] or "[]")
        except Exception:
            expected = []
        expected_high = [
            f for f in (expected if isinstance(expected, list) else [])
            if str((f or {}).get("severity", "")).upper() == "HIGH"
        ]
        if not expected_high:
            excluded.append({"caseId": rr["case_id"], "reason": "no expected HIGH findings"})
            case_recalls[rr["case_id"]] = float(rr["high_recall"] or 0)
            continue

        try:
            score = _score_eval_artifact(case, artifact, "CONTRACT_REVIEW")
        except Exception:
            print(f"[run {run_id} case {rr['case_id']}] skip: scorer raised:", flush=True)
            traceback.print_exc()
            return None
        new_recall = score["highRecall"]
        # the matcher change must not move these: verify before writing
        if (abs(score["dualCitationRate"] - float(rr["dual_citation_rate"] or 0)) > 1e-9
                or score["falsePositives"] != int(rr["false_positives"] or 0)):
            print(f"[run {run_id} case {rr['case_id']}] skip: dc/fp recomputed "
                  f"({score['dualCitationRate']:.6f}/{score['falsePositives']}) "
                  f"!= stored ({rr['dual_citation_rate']}/{rr['false_positives']})",
                  flush=True)
            return None
        case_recalls[rr["case_id"]] = new_recall
        if abs(new_recall - float(rr["high_recall"] or 0)) > 1e-9:
            changed.append((rr["case_id"], rr["high_recall"], new_recall))

    n = len(case_recalls)
    new_avg = sum(case_recalls.values()) / n if n else 0.0
    old_avg = run_row["high_risk_recall"]
    if partial:
        old_avg = (summary.get("partialMetrics") or {}).get("highRiskRecall")
    return {
        "run_id": run_id,
        "summary": summary,
        "partial": partial,
        "old_avg": old_avg,
        "new_avg": new_avg,
        "changed": changed,
        "case_recalls": case_recalls,
        "excluded": excluded,
    }


def rescore(dry_run: bool) -> None:
    with _conn() as conn:
        with conn.cursor() as cur:
            run_ids = _runs_with_artifacts(cur)
            print(f"runs with artifacts: {run_ids}", flush=True)

            # phase A: recompute everything read-only
            computed = {}
            for run_id in run_ids:
                state = _compute_run(cur, run_id)
                if state is None:
                    continue
                changed = state["changed"]
                new_avg = state["new_avg"]
                old_avg = state["old_avg"]
                print(f"\n[run {run_id}] cases={len(state['case_recalls'])} "
                      f"per-case changed={len(changed)} excluded={len(state['excluded'])}",
                      flush=True)
                for exc in state["excluded"]:
                    print(f"    excluded case {exc['caseId']}: {exc['reason']}", flush=True)
                for cid, old, new in changed:
                    print(f"    case {cid}: {old} -> {new}", flush=True)
                print(f"    run recall: official={old_avg} -> rescaled={new_avg:.4f}",
                      flush=True)
                if not changed:
                    print("    unchanged, skip", flush=True)
                    continue
                computed[run_id] = state

            if dry_run:
                print(f"\ndry-run: {len(computed)} run(s) would be rewritten", flush=True)
                return

            # phase B: apply with the full pass list in every note
            rescored_ids = sorted(computed)
            for run_id in rescored_ids:
                state = computed[run_id]
                summary = state["summary"]
                new_avg = state["new_avg"]

                # 1) per-case high_recall
                for cid, old, new in state["changed"]:
                    cur.execute("UPDATE agent_eval_result SET high_recall=%s "
                                "WHERE run_id=%s AND case_id=%s", (new, run_id, cid))

                # 2) summary_json: preserve official value + add rescore note
                if state["partial"]:
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
                            round(state["old_avg"], 4) if state["old_avg"] is not None
                            else summary.get("highRiskRecall"))
                    summary["highRiskRecall"] = round(new_avg, 4)
                summary["rescore"] = {
                    "appliedAt": "2026-08-14",
                    "note": RESCORE_NOTE,
                    "runsRescored": rescored_ids,
                    "casesChanged": [{"caseId": c, "from": o, "to": new}
                                     for c, o, new in state["changed"]],
                    "casesExcluded": state["excluded"],
                }
                cur.execute("UPDATE agent_eval_run SET summary_json=%s WHERE id=%s",
                            (json.dumps(summary, ensure_ascii=False), run_id))

                # 3) run-level recall column (partial runs stay manually finalized)
                if not state["partial"]:
                    cur.execute("UPDATE agent_eval_run SET high_risk_recall=%s WHERE id=%s",
                                (new_avg, run_id))
                conn.commit()
                print(f"[run {run_id}] applied: high_risk_recall={new_avg:.4f}", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="preview only, no writes")
    args = parser.parse_args()
    rescore(dry_run=args.dry_run)
