"""PRD Phase 8 / §10: artifact version stamping.

Every published artifact carries a `versions` block freezing the runtime
stack that produced it — graph, prompt, retrieval, rerank, scorer — plus
the evidence snapshot hash. This is the acceptance requirement that every
metric be traceable to its artifact, citation, and exact implementation
version (no constant-1.0 placeholder scoring, no untraceable results).
"""

from __future__ import annotations

from typing import Any, Mapping

ARTIFACT_SCHEMA_VERSION = "artifact-v2"


def stamp_artifact_versions(
    state: Mapping[str, Any], artifact: dict[str, Any]
) -> dict[str, Any]:
    """Attach the frozen version block to an artifact and return it.

    Versions come from the graph state (GraphAdapter seeds them from the
    runtime constants at dispatch), so they reflect what actually ran, not
    what a composer happens to import.
    """
    evidence = state.get("evidence_snapshot") or {}
    snapshot_hash = ""
    if isinstance(evidence, dict):
        snapshot_hash = str(
            evidence.get("hash") or evidence.get("snapshotHash") or ""
        )
    artifact["versions"] = {
        "artifactSchemaVersion": ARTIFACT_SCHEMA_VERSION,
        "snapshotHash": snapshot_hash,
        "graphName": state.get("graph_name") or "",
        "graphVersion": state.get("graph_version") or "",
        "model": state.get("model") or "",
        "promptVersion": state.get("prompt_version") or "",
        "retrievalVersion": state.get("retrieval_version") or "",
        "rerankVersion": state.get("rerank_version") or "",
        "scorerVersion": state.get("scorer_version") or "",
    }
    return artifact
