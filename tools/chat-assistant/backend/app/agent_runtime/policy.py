"""Agent execution policy — budget enforcement and duplicate detection.

Direct port of Java AgentExecutionPolicy with identical semantics:
- max tool calls (8), max turns (2), wall-clock deadline (300 s)
- Duplicate-call fingerprint: toolName:canonicalJson(arguments)
"""

from __future__ import annotations

import json
import time
from typing import Any


class BudgetExceeded(Exception):
    """Raised when tool-call count, turn count, or wall-clock deadline is hit."""


class RepeatedToolCall(Exception):
    """Raised when the model requests an identical tool call twice."""


class RunCancelled(Exception):
    """Raised when the run has been cancelled by an external request."""


class AgentExecutionPolicy:
    """Enforces bounded, non-repeating execution."""

    __slots__ = (
        "_max_tool_calls",
        "_max_turns",
        "_deadline",
        "_signatures",
        "tool_calls",
        "turns",
    )

    def __init__(
        self,
        max_tool_calls: int = 8,
        max_turns: int = 2,
        timeout_seconds: float = 300.0,
    ):
        if max_tool_calls < 1 or max_turns < 1 or timeout_seconds <= 0:
            raise ValueError("Agent execution limits must be positive")
        self._max_tool_calls = max_tool_calls
        self._max_turns = max_turns
        self._deadline = time.monotonic() + timeout_seconds
        self._signatures: set[str] = set()
        self.tool_calls = 0
        self.turns = 0

    # -- public -----------------------------------------------------------

    def begin_turn(self) -> None:
        if time.monotonic() > self._deadline:
            raise BudgetExceeded("Agent execution time budget exceeded")
        self.turns += 1
        if self.turns > self._max_turns:
            raise BudgetExceeded("Agent turn budget exceeded")

    def reserve_tool_call(self, tool_name: str, arguments: dict[str, Any]) -> None:
        if time.monotonic() > self._deadline:
            raise BudgetExceeded("Agent execution time budget exceeded")
        if self.tool_calls >= self._max_tool_calls:
            raise BudgetExceeded("Agent tool-call budget exceeded")
        signature = f"{tool_name}:{self._canonical(arguments)}"
        if signature in self._signatures:
            raise RepeatedToolCall(f"Repeated tool call blocked: {tool_name}")
        self._signatures.add(signature)
        self.tool_calls += 1

    def remaining_tool_calls(self) -> int:
        return max(0, self._max_tool_calls - self.tool_calls)

    @property
    def max_turns(self) -> int:
        return self._max_turns

    @property
    def max_tool_calls(self) -> int:
        return self._max_tool_calls

    # -- internal ---------------------------------------------------------

    @staticmethod
    def _canonical(arguments: dict[str, Any] | None) -> str:
        if not arguments:
            return "{}"
        # Use sorted keys for deterministic fingerprint
        return json.dumps(arguments, sort_keys=True, ensure_ascii=False, default=str)
