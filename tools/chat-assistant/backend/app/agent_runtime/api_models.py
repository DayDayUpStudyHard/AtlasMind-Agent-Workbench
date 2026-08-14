"""Pydantic contract models for Agent Runtime API."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class RunStatus(str, Enum):
    CREATED = "CREATED"
    CONTEXT_BUILDING = "CONTEXT_BUILDING"
    PLANNING = "PLANNING"
    ANALYZING = "ANALYZING"
    VERIFYING = "VERIFYING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"

    @classmethod
    def is_terminal(cls, status: str) -> bool:
        return status in {cls.COMPLETED, cls.FAILED, cls.CANCELLED}

    @classmethod
    def is_active(cls, status: str) -> bool:
        return status in {
            cls.CREATED,
            cls.CONTEXT_BUILDING,
            cls.PLANNING,
            cls.ANALYZING,
            cls.VERIFYING,
        }


class StartRunRequest:
    """Deserialised from the JSON body of POST /internal/agent/run.
    Java creates the agent_run row first, then passes the generated runId here.
    """

    __slots__ = (
        "request_id", "run_id", "subject_type", "subject_id",
        "project_id", "task_type", "question",
        "actor", "project", "task_input", "options",
    )

    def __init__(self, payload: dict):
        self.request_id: str = str(payload.get("requestId") or "")
        self.run_id: int = int(payload.get("runId") or 0)
        self.subject_type: str = str(payload.get("subjectType") or "PROJECT")
        self.subject_id: int = int(payload.get("subjectId") or 0)
        self.project_id: int = int(payload.get("projectId") or 0)
        # If subjectType is CONTRACT_CASE, treat subjectId as the primary entity id
        if self.subject_type == "CONTRACT_CASE" and self.subject_id > 0:
            self.project_id = self.subject_id  # compat: Runner uses project_id internally
        self.task_type: str = str(payload.get("taskType") or "HEALTH_ANALYSIS")
        self.question: str = str(payload.get("question") or "")
        self.actor: str = str(payload.get("actor") or "")
        self.project: dict = payload.get("project") or {}
        self.task_input: dict = payload.get("taskInput") or {}
        self.options: dict = payload.get("options") or {}


class StartRunResponse:
    __slots__ = ("run_id", "status", "progress", "current_step")

    def __init__(self, run_id: int, status: str, progress: int, current_step: str):
        self.run_id = run_id
        self.status = status
        self.progress = progress
        self.current_step = current_step

    def to_dict(self) -> dict:
        return {
            "runId": self.run_id,
            "status": self.status,
            "progress": self.progress,
            "currentStep": self.current_step,
        }


class RunDetailResponse:
    __slots__ = ("run", "traces", "tool_calls", "report", "actions", "memories")

    def __init__(
        self,
        run: Optional[dict] = None,
        traces: Optional[list[dict]] = None,
        tool_calls: Optional[list[dict]] = None,
        report: Optional[dict] = None,
        actions: Optional[list[dict]] = None,
        memories: Optional[list[dict]] = None,
    ):
        self.run = run or {}
        self.traces = traces or []
        self.tool_calls = tool_calls or []
        self.report = report
        self.actions = actions or []
        self.memories = memories or []

    def to_dict(self) -> dict:
        return {
            "run": self.run,
            "traces": self.traces,
            "toolCalls": self.tool_calls,
            "report": self.report,
            "actions": self.actions,
            "memories": self.memories,
        }


@dataclass(frozen=True)
class AgentTaskContext:
    """Immutable context passed through every phase of the harness."""

    run_id: int
    project_id: int
    task_type: str
    question: str
    subject_type: str = "PROJECT"
    subject_id: int = 0
    project: dict = field(default_factory=dict)
    task_input: dict = field(default_factory=dict)
    # Shadow runs (PRD §26.2) execute a second graph beside the primary one
    # for comparison. The shadow graph must not write run rows, reports or
    # traces — it only produces a result to diff against.
    shadow_mode: bool = False

    @classmethod
    def from_request(cls, run_id: int, request: StartRunRequest) -> "AgentTaskContext":
        return cls(
            run_id=run_id,
            project_id=request.project_id,
            task_type=request.task_type,
            question=request.question,
            subject_type=request.subject_type,
            subject_id=request.subject_id,
            project=request.project,
            task_input=request.task_input,
        )
