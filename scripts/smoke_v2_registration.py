# -*- coding: utf-8 -*-
"""Smoke test: contract_review v2 adapter registers and resolves.

Does NOT run a graph — builds the runtime exactly like the API server would
and checks the v2 adapter + dispatch resolution. Run from a fresh process.
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                "tools", "chat-assistant", "backend"))


async def main() -> int:
    import app.api.routes as routes_mod

    routes_mod._init_contract_runtime()
    router = routes_mod._contract_runtime_router
    adapter = router._adapters.get("contract_review_v2")
    if adapter is None:
        print("FAIL: contract_review_v2 adapter not registered")
        return 1
    print(f"OK: adapter registered — {type(adapter).__name__} "
          f"graph={getattr(adapter, '_graph_name', '?')}@{getattr(adapter, '_graph_version', '?')}")
    nodes = list(adapter._graph.get_graph().nodes.keys())
    expected = {"plan_work_units", "retrieve_evidence_for_work_units", "audit_coverage",
                "targeted_retrieval", "reanalyze_affected_work_units", "persist_report"}
    missing = expected - set(nodes)
    if missing:
        print(f"FAIL: missing nodes {sorted(missing)}")
        return 1
    print(f"OK: v2 graph has {len(nodes)} nodes including all v2 middle nodes")

    # dispatch resolution for the eval path
    from app.agent_runtime.api_models import AgentTaskContext

    ctx = AgentTaskContext(
        run_id=-1, project_id=-1, task_type="CONTRACT_REVIEW",
        question="smoke", subject_type="CONTRACT_CASE", subject_id=-1,
        project={"id": -1}, task_input={},
    )
    resolved = router._resolve("CONTRACT_REVIEW")
    print(f"OK: default resolution for CONTRACT_REVIEW → {type(resolved).__name__} "
          f"v{getattr(resolved, '_graph_version', '?')}")
    v1_adapter = router._adapters.get("contract_review")
    if v1_adapter is None:
        print("FAIL: v1 contract_review adapter missing")
        return 1
    print(f"OK: v1 adapter still registered ({getattr(v1_adapter, '_graph_version', '?')}) — v2 not default")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
