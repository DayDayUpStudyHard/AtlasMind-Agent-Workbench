"""Phase 3 pilot: run the v2 eval runs sequentially, in-process.

Runs the production evaluation worker `_run_evaluation_background` for the
pre-created agent_eval_run rows 30..32, in order. Must be launched in a fresh
process AFTER the Phase 0 baseline worker finishes (the baseline process has
pre-Phase-3 module code frozen in memory; this process loads the v2 pilot).

  30: dataset 9  langgraph_v2 — v2 pilot vs baseline run 25 (v1)
  31: dataset 20 langgraph    — v1 golden gate
  32: dataset 20 langgraph_v2 — v2 golden gate
"""

import asyncio
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent / "tools" / "chat-assistant" / "backend"
sys.path.insert(0, str(BACKEND))

from app.api.routes import _run_evaluation_background  # noqa: E402

# Neutralize the recovery sweeper in THIS process. _init_contract_runtime()
# starts a RunRecovery background task that marks any run row in an active
# status with a stale heartbeat as FAILED — in a standalone eval worker that
# sweep would flag the API server's in-flight runs (the graph dispatch path
# does not heartbeat) and vice versa. The eval runs' own rows are protected
# by GraphAdapter's heartbeat loop; this patch only stops the worker from
# harming other processes' rows. See the 2026-08-14 pre-flight incident.
from app.agent_runtime import recovery as _recovery_mod  # noqa: E402


async def _noop_run_forever(self) -> None:
    return


_recovery_mod.RunRecovery.run_forever = _noop_run_forever

RUN_IDS = [30, 31, 32]


async def main() -> None:
    for run_id in RUN_IDS:
        print(f"=== START v2 pilot eval run {run_id} ===", flush=True)
        try:
            await _run_evaluation_background(run_id)
        except Exception as exc:
            print(f"=== RUN {run_id} CRASHED: {exc!r} ===", flush=True)
        print(f"=== DONE v2 pilot eval run {run_id} ===", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
