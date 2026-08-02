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
DEFAULT_TIMEOUT = 300   # seconds before a run is considered timed out


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
        """Periodic scan for timed-out and heartbeat-lost runs."""
        try:
            timed_out = await self._run_store.find_timed_out_runs(self._timeout)
            for run_id in timed_out:
                logger.warning("Recovery: marking run %s as FAILED (timeout)", run_id)
                await self._run_store.update_run(
                    run_id,
                    status="FAILED",
                    error_message=f"Agent execution timed out after {self._timeout}s",
                )
        except Exception:
            logger.exception("Timeout recovery scan failed")

        try:
            zombies = await self._run_store.find_zombie_runs(self._interval * 2)
            for run_id in zombies:
                logger.warning("Recovery: marking run %s as FAILED (heartbeat lost)", run_id)
                await self._run_store.update_run(
                    run_id,
                    status="FAILED",
                    error_message="Agent worker heartbeat lost — possible crash",
                )
        except Exception:
            logger.exception("Zombie recovery scan failed")
