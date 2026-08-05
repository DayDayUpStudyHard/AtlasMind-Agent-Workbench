"""MySQL-based LangGraph checkpoint saver — implements BaseCheckpointSaver protocol.

Matches LangGraph 0.4.10 signatures exactly:
  get_tuple(config) -> CheckpointTuple | None
  put(config, checkpoint, metadata, new_versions) -> RunnableConfig
  list(config, *, filter, before, limit) -> Iterator[CheckpointTuple]
  put_writes(config, writes, task_id, task_path='') -> None
  delete_thread(thread_id) -> None
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from typing import Any, Iterator, Sequence

logger = logging.getLogger(__name__)

_NODE_PROGRESS: dict[str, tuple[str, int, str]] = {
    "load_run_context": ("CONTEXT_BUILDING", 8, "正在加载合同与运行上下文"),
    "freeze_case_snapshot": ("CONTEXT_BUILDING", 12, "正在固化合同证据快照"),
    "inventory_clauses": ("CONTEXT_BUILDING", 20, "正在盘点合同条款"),
    "create_domain_tasks": ("PLANNING", 30, "Planner 正在规划风险领域"),
    "retrieve_domain_evidence": ("ANALYZING", 45, "正在检索合同与知识库证据"),
    "run_deterministic_rules": ("ANALYZING", 55, "正在执行确定性规则"),
    "draft_domain_findings": ("ANALYZING", 70, "LLM 正在生成逐领域风险发现"),
    "validate_claims": ("VERIFYING", 78, "正在核验风险主张与引用"),
    "coverage_reflection": ("VERIFYING", 84, "Reflection 正在检查证据覆盖"),
    "targeted_retrieval": ("VERIFYING", 87, "正在补充检索缺失证据"),
    "compose_report": ("VERIFYING", 91, "正在组装完整审查报告"),
    "compose_limited_report": ("VERIFYING", 91, "正在生成范围受限报告"),
    "validate_schema": ("VERIFYING", 95, "正在执行报告质量门禁"),
    "repair_artifact": ("VERIFYING", 96, "正在修复报告结构"),
    "persist_report": ("VERIFYING", 98, "正在保存报告与风险发现"),
}

# LangGraph Checkpoint type (TypedDict, but we use dict at runtime)
# Checkpoint: {v, id, ts, channel_values, channel_versions, versions_seen, updated_channels}
# CheckpointMetadata: {source, step, parents}
# ChannelVersions: dict[str, str|int|float]
# RunnableConfig: {"configurable": {"thread_id": str, ...}}


class MySqlCheckpointSaver:
    """Persists LangGraph checkpoints to MySQL via pymysql pool."""

    def __init__(self):
        self._serde = _CheckpointSerde()

    # ── BaseCheckpointSaver protocol ────────────────────────────────────

    def get_tuple(self, config: dict) -> Any | None:
        """Load the latest ACTIVE checkpoint.

        Args:
            config: {"configurable": {"thread_id": "run-123", ...}}
        Returns:
            CheckpointTuple | None
        """
        thread_id = _thread_id(config)
        try:
            from ..persistence import _conn

            with _conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """SELECT run_id, thread_id, checkpoint_id, state_revision,
                                  node_name, state_json, state_hash, status, create_time
                           FROM agent_graph_checkpoint
                           WHERE thread_id=%s AND status='ACTIVE'
                           ORDER BY state_revision DESC LIMIT 1""",
                        (thread_id,),
                    )
                    row = cur.fetchone()
                    if not row:
                        return None

                    channel_values = self._serde.loads(row["state_json"] or "{}")

                    # Build Checkpoint
                    checkpoint: dict = {
                        "v": 1,
                        "id": row["checkpoint_id"],
                        "ts": str(row["create_time"]),
                        "channel_values": channel_values,
                        "channel_versions": {},
                        "versions_seen": {},
                        "updated_channels": None,
                    }

                    # Build CheckpointMetadata
                    metadata: dict = {
                        "source": "input",
                        "step": row["state_revision"],
                        "parents": {},
                    }

                    # Build and return CheckpointTuple-like object
                    return _make_tuple(config, checkpoint, metadata)
        except Exception as exc:
            logger.error("Checkpoint get_tuple failed for %s: %s", thread_id, exc)
            return None

    def put(
        self,
        config: dict,
        checkpoint: dict,
        metadata: dict,
        new_versions: dict,
    ) -> dict:
        """Save a new checkpoint, supersede the previous ACTIVE one.

        Returns updated config (same as input for MySQL adapter).
        """
        thread_id = _thread_id(config)
        checkpoint_id = str(checkpoint.get("id") or _gen_ckpt_id())
        channel_values = checkpoint.get("channel_values") or {}
        state_json = self._serde.dumps(channel_values)
        state_hash = hashlib.sha256(state_json.encode()).hexdigest()
        state_revision = int(metadata.get("step", 0))
        node_name = str(channel_values.get("current_node") or metadata.get("source") or "checkpoint")[:128]
        graph_name = str(channel_values.get("graph_name") or "")[:64]
        graph_version = str(channel_values.get("graph_version") or "v1")[:32]

        # Extract run_id from config if present
        run_id = 0
        if isinstance(config.get("configurable"), dict):
            run_id_str = str(config["configurable"].get("run_id", "0"))
            try:
                run_id = int(run_id_str)
            except ValueError:
                pass

        try:
            from ..persistence import _conn

            with _conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """UPDATE agent_graph_checkpoint
                           SET status='SUPERSEDED'
                           WHERE thread_id=%s AND status='ACTIVE'""",
                        (thread_id,),
                    )
                    cur.execute(
                        """INSERT INTO agent_graph_checkpoint
                           (run_id, graph_name, graph_version, thread_id,
                            checkpoint_id, state_revision, node_name,
                            state_json, state_hash, status)
                           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,'ACTIVE')""",
                        (
                            run_id, graph_name, graph_version, thread_id,
                            checkpoint_id, state_revision, node_name,
                            state_json, state_hash,
                        ),
                    )
                    if run_id > 0 and node_name in _NODE_PROGRESS:
                        run_status, progress, step_label = _NODE_PROGRESS[node_name]
                        cur.execute(
                            """UPDATE agent_run
                               SET status=%s,
                                   progress=GREATEST(COALESCE(progress, 0), %s),
                                   current_step=%s,
                                   last_heartbeat_at=NOW()
                               WHERE id=%s
                                 AND status IN ('CREATED','CONTEXT_BUILDING','PLANNING','ANALYZING','VERIFYING')""",
                            (run_status, progress, step_label, run_id),
                        )
                    conn.commit()
        except Exception as exc:
            logger.error("Checkpoint put failed: %s", exc)

        return config

    def list(
        self,
        config: dict | None = None,
        *,
        filter: dict | None = None,
        before: dict | None = None,
        limit: int | None = None,
    ) -> Iterator[Any]:
        """List checkpoints, optionally filtered."""
        thread_id = _thread_id(config) if config else None
        try:
            from ..persistence import _conn

            with _conn() as conn:
                with conn.cursor() as cur:
                    if thread_id:
                        cur.execute(
                            """SELECT run_id, thread_id, checkpoint_id, state_revision,
                                      node_name, state_json, state_hash, status, create_time
                               FROM agent_graph_checkpoint
                               WHERE thread_id=%s
                               ORDER BY state_revision DESC
                               LIMIT %s""",
                            (thread_id, limit or 50),
                        )
                    else:
                        cur.execute(
                            """SELECT run_id, thread_id, checkpoint_id, state_revision,
                                      node_name, state_json, state_hash, status, create_time
                               FROM agent_graph_checkpoint
                               WHERE status='ACTIVE'
                               ORDER BY state_revision DESC
                               LIMIT %s""",
                            (limit or 50,),
                        )
                    rows = cur.fetchall()
                    for row in rows:
                        channel_values = self._serde.loads(row["state_json"] or "{}")
                        checkpoint: dict = {
                            "v": 1, "id": row["checkpoint_id"],
                            "ts": str(row["create_time"]),
                            "channel_values": channel_values,
                            "channel_versions": {}, "versions_seen": {},
                            "updated_channels": None,
                        }
                        metadata: dict = {
                            "source": "input", "step": row["state_revision"],
                            "parents": {},
                        }
                        yield _make_tuple(
                            {"configurable": {"thread_id": row["thread_id"]}},
                            checkpoint, metadata,
                        )
        except Exception as exc:
            logger.error("Checkpoint list failed: %s", exc)

    def put_writes(
        self,
        config: dict,
        writes: Sequence[tuple[str, Any]],
        task_id: str,
        task_path: str = "",
    ) -> None:
        """Store pending writes for crash recovery. MVP: no-op (writes in checkpoint)."""
        pass

    def get_next_version(self, current: dict | None, channel: str) -> int:
        """Return the next version number for a channel. MVP: monotonic counter."""
        if current is None:
            return 1
        return int(current.get(channel, 0)) + 1 if isinstance(current, dict) else 1

    # Async wrappers — LangGraph 0.4.x calls async methods internally
    async def aget_tuple(self, config: dict) -> Any | None:
        import asyncio
        return await asyncio.to_thread(self.get_tuple, config)

    async def aput(self, config: dict, checkpoint: dict, metadata: dict, new_versions: dict) -> dict:
        import asyncio
        return await asyncio.to_thread(self.put, config, checkpoint, metadata, new_versions)

    async def aput_writes(self, config: dict, writes, task_id: str, task_path: str = "") -> None:
        import asyncio
        return await asyncio.to_thread(self.put_writes, config, writes, task_id, task_path)

    def delete_thread(self, thread_id: str) -> None:
        """Mark all checkpoints for a thread as CONSUMED."""
        try:
            from ..persistence import _conn

            with _conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """UPDATE agent_graph_checkpoint
                           SET status='CONSUMED'
                           WHERE thread_id=%s""",
                        (thread_id,),
                    )
                    conn.commit()
        except Exception as exc:
            logger.error("Checkpoint delete_thread failed: %s", exc)


# ── Helpers ───────────────────────────────────────────────────────────

def _thread_id(config: dict) -> str:
    if isinstance(config.get("configurable"), dict):
        return str(config["configurable"].get("thread_id", "default"))
    return "default"


def _make_tuple(config: dict, checkpoint: dict, metadata: dict) -> Any:
    """Build a minimal CheckpointTuple-compatible object."""
    # LangGraph's CheckpointTuple is a NamedTuple; we mimic with a simple object
    class _Tuple:
        __slots__ = ("config", "checkpoint", "metadata", "parent_config", "pending_writes")
        def __init__(self):
            self.config = config
            self.checkpoint = checkpoint
            self.metadata = metadata
            self.parent_config = None
            self.pending_writes = []

    t = _Tuple()
    return t


def _gen_ckpt_id() -> str:
    import uuid
    return f"ckpt_{uuid.uuid4().hex[:16]}"


class _CheckpointSerde:
    """JSON-based state serializer."""

    @staticmethod
    def dumps(obj: Any) -> str:
        from datetime import date, datetime
        from decimal import Decimal

        def _default(o):
            if isinstance(o, (datetime, date)):
                return o.isoformat()
            if isinstance(o, Decimal):
                return float(o)
            if isinstance(o, set):
                return list(o)
            return str(o)

        return json.dumps(obj, ensure_ascii=False, default=_default)

    @staticmethod
    def loads(text: str) -> Any:
        return json.loads(text)
