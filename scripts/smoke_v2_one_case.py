# -*- coding: utf-8 -*-
"""Pre-flight: run ONE dataset-9 case through the v2 graph via the eval path.

Uses the same helpers as _run_evaluation_background (temp fixture case,
feature overrides, dispatch_with_mode("langgraph_v2")). Writes only to temp
case tables + one agent_run row. De-risks the full 30-case eval run.
"""
import asyncio
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                "tools", "chat-assistant", "backend"))

from app.agent_runtime.persistence import _conn

# Neutralize the recovery sweeper in THIS process (see run_v2_evals.py —
# a standalone worker's sweep must not flag other processes' in-flight runs).
from app.agent_runtime import recovery as _recovery_mod


async def _noop_run_forever(self) -> None:
    return


_recovery_mod.RunRecovery.run_forever = _noop_run_forever


async def main() -> int:
    import app.api.routes as routes_mod

    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, case_key, title, contract_type, contract_text, "
                "expected_findings_json, should_not_find_json, scenario, industry, "
                "difficulty, noise_level, must_have_contract_citation, "
                "must_have_policy_citation FROM agent_eval_case "
                "WHERE dataset_id=9 AND status='ACTIVE' ORDER BY id LIMIT 1"
            )
            case = cur.fetchone()
    if not case:
        print("FAIL: no active case in dataset 9")
        return 1
    print(f"case: {case['id']} {case['case_key']} — {case['title']}")

    features = {"targetedRetrievalRetries": 2, "v2AnalysisConcurrency": 4,
                "v2SkipLlmOnNoEvidence": True}
    routes_mod._set_eval_feature_overrides(features)
    temp_ids: list[int] = []
    temp_case_id = routes_mod._create_eval_temp_case(-900, case, 0, temp_ids)
    print(f"temp case id: {temp_case_id}")

    started = time.time()
    run_id, result = await routes_mod._dispatch_eval_task(
        eval_run_id=-900,
        case=case,
        idx=0,
        temp_case_id=temp_case_id,
        task_type="CONTRACT_REVIEW",
        features=features,
        runtime="langgraph_v2",
        timeout_seconds=1500,
    )
    elapsed = time.time() - started
    artifact = result.artifact or {}
    print(f"agent_run {run_id}: status={result.status} elapsed={elapsed:.0f}s")
    print(f"artifact: analysisMode={artifact.get('analysisMode')} "
          f"reportType={artifact.get('reportType')} findings={len(artifact.get('findings') or [])}")
    if artifact.get("artifactError"):
        print(f"artifactError: {artifact['artifactError']}")
        return 1
    coverage = (artifact.get("content") or {}).get("coverage") or {}
    summary = coverage.get("summary") or {}
    print(f"coverage: status={coverage.get('status')} summary={summary}")
    retrieval_validation = artifact.get("retrievalValidation") or {}
    for domain_key, info in list(retrieval_validation.items())[:6]:
        print(f"  retrieval[{domain_key}]: {info}")
    if result.status != "COMPLETED":
        print("FAIL: non-completed result")
        return 1
    print("OK: v2 graph completed end-to-end on a real case")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
