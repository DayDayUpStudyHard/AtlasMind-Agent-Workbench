"""ObservabilityRecorder — minimal dict-shaped observation helpers (PRD §11.6).

Phase 2 keeps this deliberately small: the recorder turns bundles and
validation outcomes into the observation dicts the graph nodes already write
(callId / planStepId / toolName / arguments / output / status). Full trace
persistence stays with the existing run-trace pipeline.

The per-round summary is the Phase 2 acceptance surface: every retrieval
round records its input (query variants), per-channel hit counts and
post-fusion counts.
"""

from __future__ import annotations

from typing import Any

from .models import EvidenceBundle, ValidationOutcome


class ObservabilityRecorder:
    """Builds observation dicts from harness outputs."""

    @staticmethod
    def retrieval_observation(
        bundle: EvidenceBundle,
        *,
        call_id: str,
        plan_step_id: str,
        arguments: dict[str, Any] | None = None,
        status: str = "DONE",
        error: str = "",
    ) -> dict[str, Any]:
        stats = bundle.get("retrieval_stats") or {}
        return {
            "callId": call_id,
            "planStepId": plan_step_id,
            "toolName": "retrieveEvidenceBundle",
            "arguments": arguments or {},
            "output": ObservabilityRecorder.bundle_summary(bundle),
            "status": status,
            "error": error,
        }

    @staticmethod
    def bundle_summary(bundle: EvidenceBundle) -> dict[str, Any]:
        """Per-round input / hit / post-fusion counts (acceptance surface)."""
        stats = bundle.get("retrieval_stats") or {}
        return {
            "workUnitId": bundle.get("work_unit_id"),
            "requestHash": bundle.get("request_hash"),
            "queryVariantCount": stats.get("queryVariantCount", 0),
            "counterQueryCount": stats.get("counterQueryCount", 0),
            "channelHitCounts": stats.get("channelHitCounts", {}),
            "postFusionCounts": stats.get("postFusionCounts", {}),
            "finalCounts": stats.get("finalCounts", {}),
            "rerank": stats.get("rerank", {}),
            "elapsedMs": stats.get("elapsedMs"),
            "warningCount": len(bundle.get("warnings") or []),
            "warnings": [
                {"channel": item.get("channel"), "error": item.get("error")}
                for item in (bundle.get("warnings") or [])
                if item.get("error")
            ][:5],
        }

    @staticmethod
    def validation_observation(
        outcomes: list[ValidationOutcome],
        *,
        call_id: str,
        plan_step_id: str,
        arguments: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        verdict_counts: dict[str, int] = {}
        for outcome in outcomes:
            verdict = str(outcome.get("verdict") or "UNKNOWN")
            verdict_counts[verdict] = verdict_counts.get(verdict, 0) + 1
        return {
            "callId": call_id,
            "planStepId": plan_step_id,
            "toolName": "groundingValidate",
            "arguments": arguments or {},
            "output": {
                "candidateCount": len(outcomes),
                "verdictCounts": verdict_counts,
                "evidenceNeedCount": sum(len(outcome.get("evidence_needs") or []) for outcome in outcomes),
            },
            "status": "DONE",
        }
