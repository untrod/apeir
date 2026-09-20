"""Checkpoint model for task state snapshots."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Mapping

from nous_runtime.task.exceptions import TaskRuntimeError


def _checkpoint_id() -> str:
    return f"checkpoint_{uuid.uuid4().hex}"


def _timestamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace(
        "+00:00", "Z"
    )


@dataclass(frozen=True)
class Checkpoint:
    checkpoint_id: str = field(default_factory=_checkpoint_id)
    task_id: str = ""
    timestamp: str = field(default_factory=_timestamp)
    state: Mapping[str, Any] = field(default_factory=dict)
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        checkpoint_id = str(self.checkpoint_id or "").strip()
        task_id = str(self.task_id or "").strip()
        if not checkpoint_id:
            raise TaskRuntimeError("checkpoint_id is required")
        if not task_id:
            raise TaskRuntimeError("checkpoint task_id is required")
        object.__setattr__(self, "checkpoint_id", checkpoint_id)
        object.__setattr__(self, "task_id", task_id)
        object.__setattr__(self, "state", dict(self.state))
        object.__setattr__(self, "metadata", dict(self.metadata))

    def to_dict(self) -> dict[str, Any]:
        return {
            "checkpoint_id": self.checkpoint_id,
            "task_id": self.task_id,
            "timestamp": self.timestamp,
            "state": dict(self.state),
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "Checkpoint":
        return cls(
            checkpoint_id=str(data.get("checkpoint_id") or _checkpoint_id()),
            task_id=str(data.get("task_id") or ""),
            timestamp=str(data.get("timestamp") or _timestamp()),
            state=dict(data.get("state") or {}),
            metadata=dict(data.get("metadata") or {}),
        )


__all__ = ["Checkpoint"]
