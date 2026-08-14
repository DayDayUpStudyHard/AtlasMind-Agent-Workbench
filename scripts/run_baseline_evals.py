"""Phase 0 baseline: run frozen Graph v1 eval runs sequentially, in-process.

Runs the production evaluation worker `_run_evaluation_background` for the
pre-created agent_eval_run rows 25..29, in order, mirroring the in-service
sequential queue. Results are written to MySQL exactly as the eval center
worker would (progress + results visible in the admin UI).
"""

import asyncio
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent / "tools" / "chat-assistant" / "backend"
sys.path.insert(0, str(BACKEND))

from app.api.routes import _run_evaluation_background  # noqa: E402

RUN_IDS = [25, 26, 27, 28, 29]


async def main() -> None:
    for run_id in RUN_IDS:
        print(f"=== START baseline eval run {run_id} ===", flush=True)
        try:
            await _run_evaluation_background(run_id)
        except Exception as exc:
            print(f"=== RUN {run_id} CRASHED: {exc!r} ===", flush=True)
        print(f"=== DONE baseline eval run {run_id} ===", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
