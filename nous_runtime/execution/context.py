"""Shared execution context for future model, agent, and device workers."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from nous_runtime.artifact import Artifact
from nous_runtime.core.events import EventEnvelope
from nous_runtime.task.exceptions import TaskRuntimeError


@dataclass
class ExecutionContext:
    """Mutable collaboration context scoped to one Runtime task."""

    task_id: str
    provider: str = ""
    agent_id: str = ""
    artifacts: list[Artifact] = field(default_factory=list)
    events: list[EventEnvelope] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.task_id = str(self.task_id or "").strip()
        if not self.task_id:
            raise TaskRuntimeError("execution context task_id is required")
        self.provider = str(self.provider or "")
        self.agent_id = str(self.agent_id or "")
        self.artifacts = list(self.artifacts)
        self.events = list(self.events)
        self.metadata = dict(self.metadata)

    def add_artifact(self, artifact: Artifact) -> Artifact:
        if not isinstance(artifact, Artifact):
            raise TaskRuntimeError("execution artifact must be an Artifact instance")
        if all(existing.id != artifact.id for existing in self.artifacts):
            self.artifacts.append(artifact)
        return artifact

    def add_event(self, event: EventEnvelope) -> EventEnvelope:
        if not isinstance(event, EventEnvelope):
            raise TaskRuntimeError("execution event must be an EventEnvelope instance")
        self.events.append(event)
        return event

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "provider": self.provider,
            "agent_id": self.agent_id,
            "artifacts": [artifact.to_dict() for artifact in self.artifacts],
            "events": [event.to_dict() for event in self.events],
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ExecutionContext":
        return cls(
            task_id=str(data.get("task_id") or ""),
            provider=str(data.get("provider") or ""),
            agent_id=str(data.get("agent_id") or ""),
            artifacts=[
                Artifact.from_dict(item) for item in data.get("artifacts") or []
            ],
            events=[
                EventEnvelope.from_dict(item) for item in data.get("events") or []
            ],
            metadata=dict(data.get("metadata") or {}),
        )


__all__ = ["ExecutionContext"]
