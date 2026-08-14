"""RunRecovery sweeper rules — deterministic, no DB.

* stuck-CREATED scan keeps create_time-based judgment;
* the active-run timeout scan must be heartbeat-aware (require_stale_heartbeat)
  so long-running graph cases with a live heartbeat are not killed at 900s;
* zombie scan keeps the heartbeat-lost judgment.
"""
import asyncio

from app.agent_runtime.recovery import RunRecovery


class _ScriptedRunStore:
    def __init__(self):
        self.timed_out_calls: list[tuple] = []
        self.zombie_calls: list[int] = []
        self.updates: list[tuple] = []

    async def find_timed_out_runs(
        self,
        timeout_seconds: int,
        statuses=None,
        require_stale_heartbeat: bool = False,
    ) -> list[int]:
        self.timed_out_calls.append(
            (timeout_seconds, tuple(statuses or ()), require_stale_heartbeat)
        )
        return [101] if timeout_seconds >= 900 else []

    async def find_zombie_runs(self, max_heartbeat_age_seconds: int) -> list[int]:
        self.zombie_calls.append(max_heartbeat_age_seconds)
        return []

    async def update_run(self, run_id, **kwargs):
        self.updates.append((run_id, kwargs))


def test_recovery_timeout_scan_requires_stale_heartbeat():
    """Rule #2 (900s active-run timeout) must only kill runs whose heartbeat
    is also lost — alive-but-slow graph runs are not "timed out"."""

    async def exercise():
        store = _ScriptedRunStore()
        recovery = RunRecovery(store)
        await recovery._recover()

        # Rule #1: stuck CREATED, no heartbeat requirement
        assert store.timed_out_calls[0] == (120, ("CREATED",), False)
        # Rule #2: active statuses, heartbeat-aware
        assert store.timed_out_calls[1] == (
            900,
            ("CONTEXT_BUILDING", "PLANNING", "ANALYZING", "VERIFYING"),
            True,
        )
        # Rule #3 zombie scan still runs
        assert store.zombie_calls == [60]

    asyncio.run(exercise())
