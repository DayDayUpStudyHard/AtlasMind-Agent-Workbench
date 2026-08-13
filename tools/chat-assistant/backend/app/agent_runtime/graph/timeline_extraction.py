"""Final fulfillment schedule graph.

The graph intentionally has a narrow responsibility: publish only timeline
nodes that survived LLM semantic review. It reuses the parsed clause evidence
and current fact snapshot rather than reparsing the contract.
"""

from __future__ import annotations

from typing import Any

from langgraph.graph import END, START, StateGraph

from ..contract_document_parser import extract_final_contract_timeline
from .nodes.context import freeze_case_snapshot, load_run_context
from .state import BaseGraphState


def publish_final_timeline(state: dict[str, Any]) -> dict[str, Any]:
    analysis_workflow = state.get("analysis_workflow") or {}
    artifact = extract_final_contract_timeline(
        int(state.get("subject_id") or 0),
        int(state.get("run_id") or 0),
        int(analysis_workflow.get("documentId") or 0) or None,
    )
    return {
        "state_revision": int(state.get("state_revision") or 0) + 1,
        "current_node": "publish_final_timeline",
        "artifact": artifact,
        "observations": [{
            "callId": f"final-timeline-{state.get('run_id', 0)}",
            "planStepId": "publish_final_timeline",
            "toolName": "publishFinalContractTimeline",
            "arguments": {
                "caseId": state.get("subject_id"),
                "documentId": analysis_workflow.get("documentId"),
                "evidenceSnapshotHash": analysis_workflow.get("evidenceSnapshotHash"),
            },
            "output": {
                "timelineNodeCount": artifact.get("timelineNodeCount", 0),
                "documentId": artifact.get("documentId"),
            },
            "status": "DONE",
        }],
    }


def build_timeline_extraction_graph(checkpointer: Any = None) -> Any:
    builder = StateGraph(BaseGraphState)
    builder.add_node("load_run_context", load_run_context)
    builder.add_node("freeze_case_snapshot", freeze_case_snapshot)
    builder.add_node("publish_final_timeline", publish_final_timeline)
    builder.add_edge(START, "load_run_context")
    builder.add_edge("load_run_context", "freeze_case_snapshot")
    builder.add_edge("freeze_case_snapshot", "publish_final_timeline")
    builder.add_edge("publish_final_timeline", END)
    return builder.compile(checkpointer=checkpointer)
