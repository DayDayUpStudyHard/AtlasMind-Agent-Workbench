"""Redis Stream consumer for Agent Run dispatch.

Architecture::

    Java ──XADD──→ agent:run:stream  ──→  AgentRunWorker (consumer group)
                      │                          │
                      │  (fire-and-forget)        │  asyncio.create_task()
                      │                          ▼
                      │                    RunDispatcher.dispatch()
                      │                          │
                      ▼                          ▼
              (fallback) HTTP POST        AgentRunner.execute()
              /internal/agent/run         (6-phase harness)

Crash recovery: pending (PEL) messages claimed on startup + periodically.
"""

from __future__ import annotations

import asyncio
import json
import logging
import socket
from typing import Any

import redis.asyncio as aioredis

from .api_models import StartRunRequest

logger = logging.getLogger(__name__)

STREAM_KEY = "agent:run:stream"
GROUP = "agent-runners"
BATCH_SIZE = 3
POLL_TIMEOUT_MS = 2_000
PEL_CLAIM_MIN_IDLE_MS = 120_000  # 2 min — claim if idle longer


class AgentRunWorker:
    """Consumes ``agent:run:stream`` via Redis consumer group.

    Spawns each run as a background task so the consumer loop never blocks.
    On startup, claims any pending (PEL) messages left by a crashed worker.
    """

    def __init__(self, dispatcher, redis_url: str = "redis://localhost:6379/0"):
        self._dispatcher = dispatcher
        self._redis_url = redis_url
        self._redis: aioredis.Redis | None = None
        self._consumer_name = f"worker-{socket.gethostname()}"
        self._running = False
        self._active_tasks: set[asyncio.Task] = set()

    # -- public API -------------------------------------------------------

    async def run_forever(self) -> None:
        """Main consumer loop.  Blocks until :meth:`stop` is called."""
        r = await self._get_redis()

        # Ensure consumer group exists (mkstream creates the stream too)
        try:
            await r.xgroup_create(STREAM_KEY, GROUP, id="0", mkstream=True)
            logger.info("Created consumer group %s on %s", GROUP, STREAM_KEY)
        except Exception as exc:
            if "BUSYGROUP" in str(exc):
                logger.debug("Consumer group %s already exists", GROUP)
            else:
                logger.warning("xgroup_create failed: %s", exc)

        # Claim any pending messages from a previous crashed worker
        await self._claim_pending(r, min_idle_ms=0)

        self._running = True
        logger.info("AgentRunWorker %s listening on %s",
                     self._consumer_name, STREAM_KEY)

        while self._running:
            try:
                messages = await r.xreadgroup(
                    GROUP, self._consumer_name,
                    {STREAM_KEY: ">"},          # ">" = new (undelivered) messages
                    count=BATCH_SIZE,
                    block=POLL_TIMEOUT_MS,
                )

                if messages:
                    for _stream_name, entries in messages:
                        for msg_id, fields in entries:
                            task = asyncio.create_task(
                                self._dispatch_and_ack(r, msg_id, fields))
                            self._active_tasks.add(task)
                            task.add_done_callback(self._active_tasks.discard)

                # Periodically reclaim stale PEL messages (crashed workers)
                await self._claim_pending(r, min_idle_ms=PEL_CLAIM_MIN_IDLE_MS)

            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("Worker loop error — retrying in 1s")
                await asyncio.sleep(1)

    async def stop(self) -> None:
        """Signal the consumer loop to exit, wait for in-flight tasks, close."""
        self._running = False
        # Wait for active dispatches to finish (max 30s)
        if self._active_tasks:
            logger.info("Waiting for %d in-flight dispatch(es) to finish...",
                         len(self._active_tasks))
            try:
                await asyncio.wait_for(
                    asyncio.gather(*self._active_tasks, return_exceptions=True),
                    timeout=30,
                )
            except asyncio.TimeoutError:
                logger.warning("Timed out waiting for dispatch tasks")
        if self._redis:
            await self._redis.close()
            self._redis = None
            logger.info("AgentRunWorker stopped")

    # -- internals --------------------------------------------------------

    async def _get_redis(self) -> aioredis.Redis:
        if self._redis is None:
            self._redis = aioredis.from_url(
                self._redis_url,
                decode_responses=True,
                socket_connect_timeout=5,
                socket_timeout=10,        # must exceed XREADGROUP block (2s)
                socket_keepalive=True,
            )
        return self._redis

    async def _dispatch_and_ack(
        self, r: aioredis.Redis, msg_id: str, fields: dict,
    ) -> None:
        """Parse payload, spawn background harness task, ACK on completion."""
        try:
            payload_str = str(fields.get("payload", "{}"))
            payload = json.loads(payload_str)
            request = StartRunRequest(payload)

            logger.info("Worker dispatching run %s (msg %s)",
                         request.run_id, msg_id)

            # Run the harness and ACK when done (at-least-once).
            # If we crash before ACK, the message stays in PEL and is
            # reclaimed by the next worker instance.
            try:
                await self._dispatcher.dispatch(request.run_id, request)
            except Exception:
                logger.exception("Run %s dispatch failed", request.run_id)
        except Exception:
            logger.exception("Malformed stream message %s — ACKing to skip", msg_id)
        finally:
            try:
                await r.xack(STREAM_KEY, GROUP, msg_id)
            except Exception:
                logger.warning("Failed to ACK %s", msg_id)

    async def _claim_pending(
        self, r: aioredis.Redis, min_idle_ms: int = PEL_CLAIM_MIN_IDLE_MS,
    ) -> None:
        """Reclaim PEL messages idle longer than *min_idle_ms*.

        A min_idle_ms of 0 (used on startup) claims **all** pending messages.
        """
        try:
            result = await r.xautoclaim(
                STREAM_KEY, GROUP, self._consumer_name,
                min_idle_time=min_idle_ms,
                count=10,
            )
            if not result:
                return

            # xautoclaim returns [next_id, [(msg_id, fields), ...]]
            entries = result[1] if isinstance(result, (list, tuple)) else []
            for msg_id, fields in entries:
                logger.warning(
                    "Reclaimed pending message %s (idle > %dms)",
                    msg_id, min_idle_ms,
                )
                asyncio.create_task(self._dispatch_and_ack(r, msg_id, fields))
        except Exception:
            # Redis < 6.2 or no pending messages — safe to ignore
            pass
