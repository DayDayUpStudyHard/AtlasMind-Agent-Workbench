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
    "load_extraction_context": ("CONTEXT_BUILDING", 12, "正在加载当前合同版本与条款证据"),
    "freeze_case_snapshot": ("CONTEXT_BUILDING", 12, "正在固化合同证据快照"),
    "inventory_clauses": ("CONTEXT_BUILDING", 20, "正在盘点合同条款"),
    "create_domain_tasks": ("PLANNING", 30, "Planner 正在规划风险领域"),
    "select_element_packs": ("PLANNING", 25, "Planner 正在规划合同要素包"),
    "retrieve_domain_evidence": ("ANALYZING", 45, "正在检索合同与知识库证据"),
    "retrieve_element_evidence": ("ANALYZING", 46, "正在检索要素对应的合同原文"),
    "run_deterministic_rules": ("ANALYZING", 55, "正在执行确定性规则"),
    "draft_domain_findings": ("ANALYZING", 70, "LLM 正在生成逐领域风险发现"),
    "extract_element_batches": ("ANALYZING", 72, "LLM 正在整理主体、金额、期限与义务"),
    "validate_claims": ("VERIFYING", 78, "正在核验风险主张与引用"),
    "validate_extracted_elements": ("VERIFYING", 88, "正在核验合同要素与连续原文引用"),
    "coverage_reflection": ("VERIFYING", 84, "Reflection 正在检查证据覆盖"),
    "targeted_retrieval": ("VERIFYING", 87, "正在补充检索缺失证据"),
    "persist_extraction_snapshot": ("VERIFYING", 96, "正在保存可复用合同事实快照"),
    "publish_final_timeline": ("VERIFYING", 96, "正在发布经 LLM 复核的正式履约日程"),
    "decompose_requirements": ("PLANNING", 30, "正在拆解当前履约节点的合同要求"),
    "retrieve_fulfillment_evidence": ("ANALYZING", 48, "正在检索合同条款与已上传履约材料"),
    "judge_each_requirement": ("ANALYZING", 68, "正在逐项比对合同要求与履约证据"),
    "validate_fulfillment_judgement": ("VERIFYING", 78, "正在校验履约结论与证据边界"),
    "prepare_human_confirmation": ("WAITING_HUMAN", 85, "核验分析已完成，等待人工确认"),
    "wait_human_confirmation": ("WAITING_HUMAN", 85, "等待人工确认履约核验结果"),
    "apply_human_result": ("VERIFYING", 92, "正在记录人工履约确认结果"),
    "compose_report": ("VERIFYING", 91, "正在组装完整审查报告"),
    "compose_limited_report": ("VERIFYING", 91, "正在生成范围受限报告"),
    "validate_schema": ("VERIFYING", 95, "正在执行报告质量门禁"),
    "repair_artifact": ("VERIFYING", 96, "正在修复报告结构"),
    "persist_report": ("VERIFYING", 98, "正在保存报告与风险发现"),
}


def _observation_status(value: Any) -> str:
    status = str(value or "DONE").upper()
    if status in {"FAILED", "ERROR"}:
        return "FAILED"
    if status in {"RUNNING", "PENDING"}:
        return status
    if status in {"FALLBACK", "DEGRADED"}:
        return "FALLBACK"
    return "DONE"


def _node_observations(channel_values: dict[str, Any], node_name: str) -> list[dict[str, Any]]:
    """Return observations belonging to this checkpoint without duplicating rows."""
    result = []
    for observation in channel_values.get("observations") or []:
        if not isinstance(observation, dict):
            continue
        plan_step = str(observation.get("planStepId") or "")
        if plan_step and node_name and node_name not in plan_step and node_name != str(
            observation.get("nodeName") or ""
        ):
            # Observations produced by earlier nodes are still persisted as
            # tool calls at the first checkpoint that contains them. They are
            # filtered here only when an explicit nodeName is present.
            if observation.get("nodeName"):
                continue
        result.append(observation)
    return result


def _summary_keys(value: Any, limit: int = 16) -> list[str]:
    if not isinstance(value, dict):
        return []
    return sorted(str(key) for key in value.keys())[:limit]


def _summary_count(value: Any) -> int:
    if isinstance(value, (list, tuple, set, dict)):
        return len(value)
    return 0


def _node_input_summary(channel_values: dict[str, Any], node_name: str) -> dict[str, Any]:
    task_input = channel_values.get("task_input")
    plan = channel_values.get("plan")
    return {
        "taskType": channel_values.get("task_type"),
        "subjectType": channel_values.get("subject_type"),
        "subjectId": channel_values.get("subject_id"),
        "node": node_name,
        "stateRevision": channel_values.get("state_revision", 0),
        "stateKeys": _summary_keys(channel_values),
        "taskInputKeys": _summary_keys(task_input),
        "planKeys": _summary_keys(plan),
        "citationCountBefore": _summary_count(channel_values.get("citations")),
        "errorCountBefore": _summary_count(channel_values.get("errors")),
    }


def _node_output_summary(
    channel_values: dict[str, Any],
    node_name: str,
    state_revision: int,
) -> dict[str, Any]:
    observations = _node_observations(channel_values, node_name)
    tool_calls = []
    for observation in observations[:12]:
        output = observation.get("output") if isinstance(observation.get("output"), dict) else {}
        tool_calls.append({
            "toolName": observation.get("toolName"),
            "planStepId": observation.get("planStepId"),
            "status": _observation_status(observation.get("status")),
            "outputKeys": _summary_keys(output, 10),
        })

    evidence = channel_values.get("element_evidence") or channel_values.get("domain_evidence") or {}
    evidence_counts = {
        str(key): _summary_count(value)
        for key, value in evidence.items()
    } if isinstance(evidence, dict) else {}
    return {
        "currentNode": node_name,
        "stateRevision": state_revision,
        "stateKeys": _summary_keys(channel_values),
        "observationCount": _summary_count(channel_values.get("observations")),
        "nodeToolCalls": tool_calls,
        "citationCount": _summary_count(channel_values.get("citations")),
        "evidenceCounts": evidence_counts,
        "extractedElementCount": _summary_count(channel_values.get("extracted_elements")),
        "validatedElementCount": _summary_count(channel_values.get("validated_elements")),
        "findingCount": _summary_count(channel_values.get("findings")),
        "requirementCount": _summary_count(channel_values.get("requirements")),
        "errorCount": _summary_count(channel_values.get("errors")),
    }


def _node_token_usage(channel_values: dict[str, Any], node_name: str) -> tuple[int, int]:
    """Return real prompt/completion usage for one graph node.

    Usage is deliberately keyed by node rather than read from the cumulative
    WorkUnit budget, because a cumulative value would be double-counted on
    every checkpoint.
    """
    usage_map = channel_values.get("llm_usage") or {}
    if not isinstance(usage_map, dict):
        return 0, 0
    usage = usage_map.get(node_name) or {}
    if not isinstance(usage, dict):
        return 0, 0
    try:
        prompt = max(0, int(usage.get("promptTokens") or usage.get("prompt_tokens") or 0))
    except (TypeError, ValueError):
        prompt = 0
    try:
        completion = max(0, int(usage.get("completionTokens") or usage.get("completion_tokens") or 0))
    except (TypeError, ValueError):
        completion = 0
    return prompt, completion


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

                    stored_state = self._serde.loads(row["state_json"] or "{}")
                    checkpoint_meta = stored_state.pop("__checkpoint_meta__", {}) \
                        if isinstance(stored_state, dict) else {}
                    channel_values = stored_state if isinstance(stored_state, dict) else {}

                    # Build Checkpoint
                    checkpoint: dict = {
                        "v": 1,
                        "id": row["checkpoint_id"],
                        "ts": str(row["create_time"]),
                        "channel_values": channel_values,
                        "channel_versions": checkpoint_meta.get("channel_versions") or {},
                        "versions_seen": checkpoint_meta.get("versions_seen") or {},
                        "updated_channels": checkpoint_meta.get("updated_channels"),
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
        stored_state = {
            **channel_values,
            "__checkpoint_meta__": {
                "channel_versions": checkpoint.get("channel_versions") or new_versions or {},
                "versions_seen": checkpoint.get("versions_seen") or {},
                "updated_channels": checkpoint.get("updated_channels"),
            },
        }
        state_json = self._serde.dumps(stored_state)
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

        # Shadow runs (PRD §26.2) checkpoint under a "shadow-" thread and must
        # not touch the primary run's row, traces or tool-call records — the
        # primary graph owns those. Checkpoint rows themselves stay separate
        # per thread, which also keeps the primary's resume history clean.
        shadow_thread = thread_id.startswith("shadow-")

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
                    if run_id > 0 and not shadow_thread and node_name in _NODE_PROGRESS:
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

                    if run_id > 0 and not shadow_thread:
                        # Keep the business run self-describing. These
                        # columns are optional for older databases, so a
                        # missing metadata column must not prevent checkpoint
                        # persistence.
                        try:
                            cur.execute(
                                """UPDATE agent_run
                                   SET runtime_engine='langgraph', graph_name=%s,
                                       graph_version=%s, model=%s, prompt_version=%s
                                   WHERE id=%s""",
                                (
                                    graph_name,
                                    graph_version,
                                    str(channel_values.get("model") or "")[:128],
                                    str(channel_values.get("prompt_version") or channel_values.get("promptVersion") or "")[:64],
                                    run_id,
                                ),
                            )
                        except Exception as metadata_exc:
                            logger.debug("Agent run metadata update skipped: %s", metadata_exc)

                        # Persist the unified evidence snapshot hash so the
                        # run detail (management UI) can show which evidence
                        # version a run observed. Kept separate from the
                        # metadata update above so a missing column never
                        # blocks graph/version/model persistence.
                        evidence_snapshot = channel_values.get("evidence_snapshot") or {}
                        analysis_workflow = channel_values.get("analysis_workflow") or {}
                        # Fulfillment's human-gate materializes an evidence
                        # *list* for display.  Only the shared contract
                        # snapshot is a mapping with a snapshot hash; do not
                        # let the UI-facing list break checkpoint persistence
                        # and make the graph impossible to resume.
                        if not isinstance(evidence_snapshot, dict):
                            evidence_snapshot = {}
                        if not isinstance(analysis_workflow, dict):
                            analysis_workflow = {}
                        snapshot_hash = str(
                            evidence_snapshot.get("snapshot_hash")
                            or evidence_snapshot.get("snapshotHash")
                            or analysis_workflow.get("evidenceSnapshotHash")
                            or ""
                        ).strip()
                        if snapshot_hash:
                            try:
                                cur.execute(
                                    """UPDATE agent_run
                                       SET evidence_snapshot_hash=%s
                                       WHERE id=%s""",
                                    (snapshot_hash[:128], run_id),
                                )
                            except Exception as snapshot_exc:
                                logger.debug("Agent run snapshot hash update skipped: %s", snapshot_exc)

                        sequence_no = max(0, state_revision)
                        token_input, token_output = _node_token_usage(channel_values, node_name)
                        input_summary = self._serde.dumps(
                            _node_input_summary(channel_values, node_name)
                        )
                        output_summary = self._serde.dumps(
                            _node_output_summary(channel_values, node_name, state_revision)
                        )
                        input_hash = hashlib.sha256(input_summary.encode()).hexdigest()
                        node_status = "FAILED" if any(
                            _observation_status(item.get("status")) == "FAILED"
                            for item in _node_observations(channel_values, node_name)
                        ) else "DONE"
                        try:
                            cur.execute(
                                """UPDATE agent_node_execution
                                   SET node_name=%s, node_type='GRAPH_NODE', status=%s,
                                       output_hash=%s, output_summary=%s,
                                       finished_at=NOW(), latency_ms=COALESCE(latency_ms, 0),
                                       llm_model=%s, prompt_version=%s,
                                       token_input=%s, token_output=%s,
                                       error_message=%s
                                   WHERE run_id=%s AND sequence_no=%s""",
                                (
                                    node_name,
                                    node_status,
                                    state_hash,
                                    output_summary,
                                    str(channel_values.get("model") or "")[:128],
                                    str(channel_values.get("prompt_version") or channel_values.get("promptVersion") or "")[:64],
                                    token_input,
                                    token_output,
                                    str((channel_values.get("errors") or [{}])[-1].get("error") or "")[:4000]
                                    if channel_values.get("errors") else None,
                                    run_id,
                                    sequence_no,
                                ),
                            )
                            if cur.rowcount == 0:
                                cur.execute(
                                    """INSERT INTO agent_node_execution
                                       (run_id, node_name, node_type, sequence_no, attempt,
                                        status, input_hash, output_hash, started_at, finished_at,
                                        latency_ms, llm_model, prompt_version, input_summary,
                                        output_summary, token_input, token_output, error_message)
                                       VALUES (%s,%s,'GRAPH_NODE',%s,1,%s,%s,%s,NOW(),NOW(),%s,%s,%s,%s,%s,%s,%s,%s)""",
                                    (
                                        run_id,
                                        node_name,
                                        sequence_no,
                                        node_status,
                                        input_hash,
                                        state_hash,
                                        0,
                                        str(channel_values.get("model") or "")[:128],
                                        str(channel_values.get("prompt_version") or channel_values.get("promptVersion") or "")[:64],
                                        input_summary,
                                        output_summary,
                                        token_input,
                                        token_output,
                                        str((channel_values.get("errors") or [{}])[-1].get("error") or "")[:4000]
                                        if channel_values.get("errors") else None,
                                    ),
                                )
                        except Exception as node_exc:
                            logger.debug("Node execution observability skipped: %s", node_exc)

                        # One trace row represents one graph checkpoint. Tool
                        # observations use call_id as their idempotency key.
                        try:
                            trace_payload = self._serde.dumps({
                                "graphName": graph_name,
                                "graphVersion": graph_version,
                                "stateRevision": state_revision,
                                "currentNode": node_name,
                                "observationCount": len(channel_values.get("observations") or []),
                            })
                            cur.execute(
                                """INSERT IGNORE INTO agent_run_trace
                                   (run_id, event_type, sequence_no, summary, payload_json)
                                   VALUES (%s,'GRAPH_NODE',%s,%s,%s)""",
                                (run_id, sequence_no, f"Graph 节点：{node_name}"[:500], trace_payload),
                            )
                        except Exception as trace_exc:
                            logger.debug("Graph trace observability skipped: %s", trace_exc)

                        for observation in _node_observations(channel_values, node_name):
                            call_id = str(observation.get("callId") or "").strip()
                            tool_name = str(observation.get("toolName") or "").strip()
                            if not call_id or not tool_name:
                                continue
                            try:
                                obs_status = _observation_status(observation.get("status"))
                                cur.execute(
                                    """INSERT INTO agent_tool_call
                                       (run_id, plan_step_id, call_id, tool_name, input_json,
                                        output_json, status, latency_ms, error_message)
                                       VALUES (%s,%s,%s,%s,%s,%s,%s,0,%s)
                                       ON DUPLICATE KEY UPDATE
                                         plan_step_id=VALUES(plan_step_id),
                                         tool_name=VALUES(tool_name),
                                         input_json=VALUES(input_json),
                                         output_json=VALUES(output_json),
                                         status=VALUES(status),
                                         error_message=VALUES(error_message)""",
                                    (
                                        run_id,
                                        str(observation.get("planStepId") or "")[:80],
                                        call_id[:120],
                                        tool_name[:80],
                                        self._serde.dumps(observation.get("arguments") or {}),
                                        self._serde.dumps(observation.get("output") or {}),
                                        obs_status,
                                        str(observation.get("error") or "")[:4000] or None,
                                    ),
                                )
                            except Exception as tool_exc:
                                logger.debug("Tool observability skipped for %s: %s", tool_name, tool_exc)
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
                        stored_state = self._serde.loads(row["state_json"] or "{}")
                        checkpoint_meta = stored_state.pop("__checkpoint_meta__", {}) \
                            if isinstance(stored_state, dict) else {}
                        channel_values = stored_state if isinstance(stored_state, dict) else {}
                        checkpoint: dict = {
                            "v": 1, "id": row["checkpoint_id"],
                            "ts": str(row["create_time"]),
                            "channel_values": channel_values,
                            "channel_versions": checkpoint_meta.get("channel_versions") or {},
                            "versions_seen": checkpoint_meta.get("versions_seen") or {},
                            "updated_channels": checkpoint_meta.get("updated_channels"),
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

    def get_next_version(self, current: Any | None, channel: str | None = None) -> Any:
        """Return a strictly increasing version for one LangGraph channel."""
        if current is None:
            return 1
        if isinstance(current, bool):
            return int(current) + 1
        if isinstance(current, int):
            return current + 1
        if isinstance(current, float):
            return current + 1.0
        if isinstance(current, str):
            try:
                return str(int(current) + 1)
            except ValueError:
                return f"{current}.{time.monotonic_ns()}"
        raise TypeError(f"Unsupported checkpoint version type: {type(current).__name__}")

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
