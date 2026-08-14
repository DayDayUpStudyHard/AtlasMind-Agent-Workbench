"""Regenerate the risk v1 golden fixture (PRD Phase 4 / §14-4).

The golden tests (tests/test_task_spec_builder.py) run the REAL v1 node
chain — stubs only for the DB / LLM / orchestrator I/O nodes — and compare
the produced artifact plus per-node input/output samples against the frozen
file tests/golden/contract_review_v1_golden_artifact.json.

This script re-drives exactly that pipeline (shared helpers live in the
test module, so capture and test can never diverge) and rewrites the
fixture. Run it only after a deliberate change to the golden pipeline or
fixtures — the committed file is the frozen baseline that guards against
accidental drift in the real v1 nodes.

Usage (from the backend directory's Python environment):
    python scripts/capture_contract_review_v1_golden.py
"""

from __future__ import annotations

import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1] / "tools" / "chat-assistant" / "backend"
sys.path.insert(0, str(BACKEND))
# tests/ is not a package; import the test module by directory (a
# site-packages `tests` package would otherwise shadow the namespace).
sys.path.insert(0, str(BACKEND / "tests"))

from test_task_spec_builder import capture_golden  # noqa: E402

GOLDEN_FILE = BACKEND / "tests" / "golden" / "contract_review_v1_golden_artifact.json"


def main() -> None:
    capture_golden()
    print(f"golden fixture regenerated: {GOLDEN_FILE}")


if __name__ == "__main__":
    main()
