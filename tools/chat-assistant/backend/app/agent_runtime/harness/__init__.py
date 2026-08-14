"""Minimal common evidence harness (PRD Phase 2, 2026-08-14).

Phase 2 extracts ONLY the shared retrieval + validation spine:

* ``models``       — WorkUnit / EvidenceNeed / RetrievalRequest / EvidenceBundle /
                     CandidateResult / ValidationOutcome (PRD §10)
* ``retrieval``    — RetrievalOrchestrator (PRD §11.2)
* ``validation``   — GroundingValidator (PRD §11.3)
* ``observation``  — ObservabilityRecorder (PRD §11.6, minimal dict form)
* ``fakes``        — fake adapters / reranker / snapshot for pure unit tests

TaskSpec, WorkUnit planners, artifact composition, risk scoring, date
calculation and fulfillment persistence stay OUT of this package until the
interfaces prove stable across two graphs (PRD §14.4).
"""

from .models import (  # noqa: F401
    CandidateResult,
    EvidenceBundle,
    EvidenceNeed,
    RetrievalRequest,
    ValidationOutcome,
    WorkUnit,
)
from .retrieval import RetrievalOrchestrator, get_orchestrator  # noqa: F401
from .validation import GroundingValidator  # noqa: F401
