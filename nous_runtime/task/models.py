"""Execution Runtime task model."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Mapping

from nous_runtime.task.exceptions import TaskRuntimeError
from nous_runtime.task.state import (
    Priority,
    TaskStatus,
    normalize_priority,
    normalize_status,
    validate_transition,
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace(
        "+00:00", "Z"
    )


def task_id() -> str:
    return f"task_{uuid.uuid4().hex}"


@dataclass
class Task:
    """A long-lived Runtime task with an explicit lifecycle."""

    id: str = field(default_factory=task_id)
    name: str = ""
    description: str = ""
    status: TaskStatus = TaskStatus.CREATED
    priority: Priority = Priority.NORMAL
    created_at: str = field(default_factory=utc_now)
    updated_at: str = field(default_factory=utc_now)
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.id = str(self.id or "").strip()
        self.name = str(self.name or "").strip()
        if not self.id:
            raise TaskRuntimeError("task id is required")
        if not self.name:
            raise TaskRuntimeError("task name is required")
        self.description = str(self.description or "")
        self.status = normalize_status(self.status)
        self.priority = normalize_priority(self.priority)
        self.metadata = dict(self.metadata)

    def transition(self, target: TaskStatus | str) -> "Task":
        """Apply one validated lifecycle transition."""
        _, target_status = validate_transition(self.status, target)
        self.status = target_status
        self.updated_at = utc_now()
        return self

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "status": self.status.value,
            "priority": self.priority.value,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "Task":
        return cls(
            id=str(data.get("id") or task_id()),
            name=str(data.get("name") or ""),
            description=str(data.get("description") or ""),
            status=normalize_status(data.get("status") or TaskStatus.CREATED),
            priority=normalize_priority(data.get("priority") or Priority.NORMAL),
            created_at=str(data.get("created_at") or utc_now()),
            updated_at=str(data.get("updated_at") or utc_now()),
            metadata=dict(data.get("metadata") or {}),
        )


__all__ = ["Task", "task_id", "utc_now"]
