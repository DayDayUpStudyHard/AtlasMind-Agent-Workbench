"""Minimal test graph — validates the full LangGraph infrastructure.

This graph does the absolute minimum: reads a contract case title from MySQL
and returns it. It proves that:
  - State compiles and flows through nodes
  - Checkpoint writes to MySQL
  - Node trace records each visit
  - RuntimeRouter dispatches correctly
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

# LangGraph is optional — only import when available (installed via requirements-graph.txt)
try:
    from langgraph.graph import StateGraph, START, END
    _LANGGRAPH_AVAILABLE = True
except ImportError:
    _LANGGRAPH_AVAILABLE = False

from .state import BaseGraphState


def _ping_node(state: BaseGraphState) -> dict[str, Any]:
    """Read the contract case title and set it as the artifact."""
    run_id = state.get("run_id", 0)
    case_snapshot = state.get("case_snapshot") or {}
    case_id = case_snapshot.get("id", 0)

    title = case_snapshot.get("title") or "未命名合同"

    # Try to read from DB if case_snapshot is empty
    if not title or title == "未命名合同":
        try:
            from ..persistence import _conn

            with _conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT title FROM contract_case WHERE id=%s AND deleted=0",
                        (case_id,),
                    )
                    row = cur.fetchone()
                    if row and row.get("title"):
                        title = str(row["title"])
        except Exception as exc:
            logger.warning("Ping graph DB read failed: %s", exc)

    return {
        "state_revision": state.get("state_revision", 0) + 1,
        "current_node": "ping_node",
        "artifact": {
            "reportType": "PING_REPORT",
            "title": f"[Ping] {title}",
            "summary": f"Ping graph completed for run {run_id}, case {case_id}",
            "caseTitle": title,
            "runId": run_id,
        },
    }


def build_ping_graph() -> Any:
    """Build and compile the minimal ping test graph."""
    if not _LANGGRAPH_AVAILABLE:
        raise RuntimeError(
            "LangGraph is not installed. Install requirements-graph.txt first."
        )

    builder = StateGraph(BaseGraphState)

    builder.add_node("ping_node", _ping_node)

    builder.add_edge(START, "ping_node")
    builder.add_edge("ping_node", END)

    return builder.compile()


def register(registry=None) -> None:
    """Register the ping graph with the global graph registry."""
    if not _LANGGRAPH_AVAILABLE:
        logger.info("LangGraph not available, skipping ping graph registration")
        return

    if registry is None:
        from .registry import get_graph_registry
        registry = get_graph_registry()

    registry.register(
        name="ping",
        version="v1",
        builder=build_ping_graph,
    )
    logger.info("Registered ping graph v1")
