# -*- coding: utf-8 -*-
"""
Task contracts -TaskSubmission, TaskAssignment, TaskAcknowledgement,
TaskEvent, TaskResult, TaskCancellation, and TaskState enum.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from nous_runtime.compat import ids as _ids
from nous_runtime.compat import time as _time

from .serialization import redacted_serialization


class TaskState(str, Enum):
    """Task lifecycle states."""
    QUEUED = "queued"
    DELIVERED = "delivered"
    ACCEPTED = "accepted"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    EXPIRED = "expired"

    @classmethod
    def terminal_states(cls) -> set[TaskState]:
        return {cls.COMPLETED, cls.FAILED, cls.CANCELLED, cls.EXPIRED}

    @classmethod
    def from_string(cls, s: str) -> TaskState | None:
        try:
            return cls(s.lower())
        except ValueError:
            return None


# Valid transitions
VALID_TRANSITIONS: dict[TaskState, set[TaskState]] = {
    TaskState.QUEUED: {TaskState.DELIVERED, TaskState.CANCELLED, TaskState.EXPIRED},
    TaskState.DELIVERED: {TaskState.ACCEPTED, TaskState.QUEUED, TaskState.FAILED, TaskState.EXPIRED},
    TaskState.ACCEPTED: {TaskState.RUNNING, TaskState.FAILED, TaskState.CANCELLED, TaskState.EXPIRED},
    TaskState.RUNNING: {TaskState.COMPLETED, TaskState.FAILED, TaskState.CANCELLED, TaskState.EXPIRED},
    TaskState.COMPLETED: set(),
    TaskState.FAILED: set(),
    TaskState.CANCELLED: set(),
    TaskState.EXPIRED: set(),
}


@dataclass(frozen=True)
class TaskSubmission:
    """Client submits a task for execution."""

    task_id: str
    capability_id: str
    params: dict[str, Any]
    target_node: str = ""  # specific node_id or empty for any compatible
    idempotency_key: str = ""
    deadline: str = ""
    risk_level: str = "low"
    max_retries: int = 0
    budget_max_time_ms: int = 30000
    created_at: str = ""

    def __post_init__(self):
        if not self.task_id:
            object.__setattr__(self, "task_id", _ids.make_id("task"))
        if not self.idempotency_key:
            object.__setattr__(self, "idempotency_key", _ids.make_id("idem"))
        if not self.created_at:
            object.__setattr__(self, "created_at", _time.utc_now())

    @classmethod
    def create(
        cls,
        capability_id: str,
        params: dict[str, Any],
        target_node: str = "",
        deadline: str = "",
        risk_level: str = "low",
        max_retries: int = 0,
        budget_max_time_ms: int = 30000,
    ) -> TaskSubmission:
        return cls(
            task_id=_ids.make_id("task"),
            capability_id=capability_id,
            params=params,
            target_node=target_node,
            idempotency_key=_ids.make_id("idem"),
            deadline=deadline,
            risk_level=risk_level,
            max_retries=max_retries,
            budget_max_time_ms=budget_max_time_ms,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "capability_id": self.capability_id,
            "params": self.params,
            "target_node": self.target_node,
            "idempotency_key": self.idempotency_key,
            "deadline": self.deadline,
            "risk_level": self.risk_level,
            "max_retries": self.max_retries,
            "budget_max_time_ms": self.budget_max_time_ms,
            "created_at": self.created_at,
        }

    def to_redacted_dict(self) -> dict[str, Any]:
        return redacted_serialization(self.to_dict())

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TaskSubmission:
        return cls(
            task_id=data.get("task_id", ""),
            capability_id=data.get("capability_id", ""),
            params=data.get("params", {}),
            target_node=data.get("target_node", ""),
            idempotency_key=data.get("idempotency_key", ""),
            deadline=data.get("deadline", ""),
            risk_level=data.get("risk_level", "low"),
            max_retries=data.get("max_retries", 0),
            budget_max_time_ms=data.get("budget_max_time_ms", 30000),
            created_at=data.get("created_at", ""),
        )


@dataclass(frozen=True)
class TaskAssignment:
    """Control Plane assigns a task to a Node."""

    task_id: str
    capability_id: str
    params: dict[str, Any]
    node_id: str
    sequence_number: int = 0
    deadline: str = ""
    assigned_at: str = ""

    def __post_init__(self):
        if not self.assigned_at:
            object.__setattr__(self, "assigned_at", _time.utc_now())

    @classmethod
    def from_submission(
        cls, submission: TaskSubmission, node_id: str, sequence_number: int
    ) -> TaskAssignment:
        return cls(
            task_id=submission.task_id,
            capability_id=submission.capability_id,
            params=submission.params,
            node_id=node_id,
            sequence_number=sequence_number,
            deadline=submission.deadline,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "capability_id": self.capability_id,
            "params": self.params,
            "node_id": self.node_id,
            "sequence_number": self.sequence_number,
            "deadline": self.deadline,
            "assigned_at": self.assigned_at,
        }

    def to_redacted_dict(self) -> dict[str, Any]:
        return redacted_serialization(self.to_dict())

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TaskAssignment:
        return cls(
            task_id=data.get("task_id", ""),
            capability_id=data.get("capability_id", ""),
            params=data.get("params", {}),
            node_id=data.get("node_id", ""),
            sequence_number=data.get("sequence_number", 0),
            deadline=data.get("deadline", ""),
            assigned_at=data.get("assigned_at", ""),
        )


@dataclass(frozen=True)
class TaskAcknowledgement:
    """Node acknowledges receipt of a task assignment."""

    task_id: str
    accepted: bool
    reject_reason: str = ""
    timestamp: str = ""

    def __post_init__(self):
        if not self.timestamp:
            object.__setattr__(self, "timestamp", _time.utc_now())

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "accepted": self.accepted,
            "reject_reason": self.reject_reason,
            "timestamp": self.timestamp,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TaskAcknowledgement:
        return cls(
            task_id=data.get("task_id", ""),
            accepted=data.get("accepted", False),
            reject_reason=data.get("reject_reason", ""),
            timestamp=data.get("timestamp", ""),
        )


@dataclass(frozen=True)
class TaskEvent:
    """Node streams execution events for a running task."""

    task_id: str
    event_type: str  # started | progress | log | artifact_ready | completed | failed
    data: dict[str, Any] = field(default_factory=dict)
    timestamp: str = ""

    def __post_init__(self):
        if not self.timestamp:
            object.__setattr__(self, "timestamp", _time.utc_now())

    @classmethod
    def started(cls, task_id: str) -> TaskEvent:
        return cls(task_id=task_id, event_type="started")

    @classmethod
    def log(cls, task_id: str, message: str) -> TaskEvent:
        return cls(task_id=task_id, event_type="log", data={"message": message})

    @classmethod
    def completed(cls, task_id: str) -> TaskEvent:
        return cls(task_id=task_id, event_type="completed")

    @classmethod
    def failed(cls, task_id: str, error: str) -> TaskEvent:
        return cls(task_id=task_id, event_type="failed", data={"error": error})

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "event_type": self.event_type,
            "data": self.data,
            "timestamp": self.timestamp,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TaskEvent:
        return cls(
            task_id=data.get("task_id", ""),
            event_type=data.get("event_type", ""),
            data=data.get("data", {}),
            timestamp=data.get("timestamp", ""),
        )


@dataclass(frozen=True)
class TaskResult:
    """Final result of a task execution."""

    task_id: str
    status: str  # completed | failed
    result: dict[str, Any] = field(default_factory=dict)
    error: str = ""
    artifacts: list[dict[str, Any]] = field(default_factory=list)
    events: list[dict[str, Any]] = field(default_factory=list)
    duration_ms: int = 0
    node_id: str = ""
    completed_at: str = ""

    def __post_init__(self):
        if not self.completed_at:
            object.__setattr__(self, "completed_at", _time.utc_now())

    @classmethod
    def success(
        cls, task_id: str, result: dict[str, Any], node_id: str,
        events: list[dict[str, Any]] | None = None, duration_ms: int = 0,
    ) -> TaskResult:
        return cls(
            task_id=task_id,
            status="completed",
            result=result,
            node_id=node_id,
            events=events or [],
            duration_ms=duration_ms,
        )

    @classmethod
    def failure(
        cls, task_id: str, error: str, node_id: str,
        events: list[dict[str, Any]] | None = None, duration_ms: int = 0,
    ) -> TaskResult:
        return cls(
            task_id=task_id,
            status="failed",
            error=error,
            node_id=node_id,
            events=events or [],
            duration_ms=duration_ms,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "status": self.status,
            "result": self.result,
            "error": self.error,
            "artifacts": self.artifacts,
            "events": self.events,
            "duration_ms": self.duration_ms,
            "node_id": self.node_id,
            "completed_at": self.completed_at,
        }

    def to_redacted_dict(self) -> dict[str, Any]:
        return redacted_serialization(self.to_dict())

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TaskResult:
        return cls(
            task_id=data.get("task_id", ""),
            status=data.get("status", "failed"),
            result=data.get("result", {}),
            error=data.get("error", ""),
            artifacts=data.get("artifacts", []),
            events=data.get("events", []),
            duration_ms=data.get("duration_ms", 0),
            node_id=data.get("node_id", ""),
            completed_at=data.get("completed_at", ""),
        )


@dataclass(frozen=True)
class TaskCancellation:
    """Request to cancel a running task."""

    task_id: str
    reason: str = ""
    requested_at: str = ""

    def __post_init__(self):
        if not self.requested_at:
            object.__setattr__(self, "requested_at", _time.utc_now())

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "reason": self.reason,
            "requested_at": self.requested_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TaskCancellation:
        return cls(
            task_id=data.get("task_id", ""),
            reason=data.get("reason", ""),
            requested_at=data.get("requested_at", ""),
        )

