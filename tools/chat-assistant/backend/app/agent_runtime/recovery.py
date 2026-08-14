"""Run recovery — heartbeat check, timeout detection, startup zombie scan.

Launched as a background asyncio task in FastAPI's lifespan.  Scans:
  1. On startup: marks all non-terminal runs with lost heartbeats as FAILED.
  2. Periodically: detects timed-out runs and heartbeat-lost (zombie) runs.
"""

from __future__ import annotations

import asyncio
import logging

from .persistence import RunStore

logger = logging.getLogger(__name__)

DEFAULT_INTERVAL = 30   # seconds between recovery scans
DEFAULT_TIMEOUT = 900   # multi-domain graph reviews may legitimately take several minutes
CREATED_TIMEOUT = 120   # seconds before a CREATED (unclaimed) run is marked FAILED


class RunRecovery:
    """Background task that monitors run health."""

    def __init__(
        self,
        run_store: RunStore,
        interval: int = DEFAULT_INTERVAL,
        timeout: int = DEFAULT_TIMEOUT,
    ):
        self._run_store = run_store
        self._interval = interval
        self._timeout = timeout

    async def run_forever(self) -> None:
        """Entry point called from FastAPI lifespan. Runs until cancelled."""
        await self._recover_on_startup()
        while True:
            await asyncio.sleep(self._interval)
            await self._recover()

    # -- internal ---------------------------------------------------------

    async def _recover_on_startup(self) -> None:
        """Scan for zombie runs left over from a previous crash."""
        try:
            zombie_ids = await self._run_store.find_zombie_runs(self._interval * 2)
            for run_id in zombie_ids:
                logger.warning("Startup recovery: marking run %s as FAILED (zombie)", run_id)
                await self._run_store.update_run(
                    run_id,
                    status="FAILED",
                    error_message="Agent worker restarted — previous run lost",
                )
            if zombie_ids:
                logger.info("Startup recovery: marked %s zombie run(s) as FAILED", len(zombie_ids))
        except Exception:
            logger.exception("Startup recovery scan failed")

    async def _recover(self) -> None:
        """Periodic scan for timed-out, stuck-CREATED, and heartbeat-lost runs."""
        # 1. Stuck CREATED runs — worker never picked them up
        try:
            stuck = await self._run_store.find_timed_out_runs(
                CREATED_TIMEOUT,
                statuses=("CREATED",),
            )
            for run_id in stuck:
                logger.warning("Recovery: marking run %s as FAILED (stuck CREATED for %ss)",
                              run_id, CREATED_TIMEOUT)
                await self._run_store.update_run(
                    run_id,
                    status="FAILED",
                    error_message=f"Agent worker 未在 {CREATED_TIMEOUT}s 内接取任务 — 请检查 Python 服务是否正常运行",
                )
        except Exception:
            logger.exception("Stuck-CREATED recovery scan failed")

        # 2. Timed-out active runs. Heartbeat-aware: a run that keeps beating
        # is alive even past the timeout (v2 pilot cases legitimately exceed
        # 900s); only runs whose heartbeat is also stale are killed here.
        # Runs without any heartbeat keep the create_time-based judgment.
        try:
            timed_out = await self._run_store.find_timed_out_runs(
                self._timeout,
                statuses=("CONTEXT_BUILDING", "PLANNING", "ANALYZING", "VERIFYING"),
                require_stale_heartbeat=True,
            )
            for run_id in timed_out:
                logger.warning("Recovery: marking run %s as FAILED (timeout %ss)",
                              run_id, self._timeout)
                await self._run_store.update_run(
                    run_id,
                    status="FAILED",
                    error_message=f"Agent 执行超时（{self._timeout}s）— 可能因 LLM 不可达或任务过于复杂",
                )
        except Exception:
            logger.exception("Timeout recovery scan failed")

        # 3. Heartbeat-lost zombie runs
        try:
            zombies = await self._run_store.find_zombie_runs(self._interval * 2)
            for run_id in zombies:
                logger.warning("Recovery: marking run %s as FAILED (heartbeat lost)", run_id)
                await self._run_store.update_run(
                    run_id,
                    status="FAILED",
                    error_message="Agent worker 心跳丢失 — 进程可能已崩溃",
                )
        except Exception:
            logger.exception("Zombie recovery scan failed")
