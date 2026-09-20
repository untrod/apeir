"""Read-only context composition adapter for Execution Runtime."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from nous_runtime.artifact import Artifact
from nous_runtime.execution import ExecutionContext
from nous_runtime.task import Task


class ExecutionContextBuilder:
    """Compose task inputs without taking ownership of source state."""

    def build(
        self,
        task: Task,
        *,
        history: Iterable[Mapping[str, Any]] = (),
        artifacts: Iterable[Artifact] = (),
        memory: Iterable[Mapping[str, Any]] = (),
        provider: str = "",
        agent_id: str = "",
        routing_decision: Any = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> ExecutionContext:
        routing_payload = (
            routing_decision.to_dict()
            if hasattr(routing_decision, "to_dict")
            else routing_decision
        )
        composed_metadata = {
            "task": task.to_dict(),
            "history": [dict(item) for item in history],
            "memory": [dict(item) for item in memory],
            **dict(metadata or {}),
        }
        if routing_payload is not None:
            composed_metadata["routing_decision"] = routing_payload
        return ExecutionContext(
            task_id=task.id,
            provider=provider,
            agent_id=agent_id,
            artifacts=list(artifacts),
            metadata=composed_metadata,
        )


def build_execution_context(task: Task, **kwargs: Any) -> ExecutionContext:
    return ExecutionContextBuilder().build(task, **kwargs)


__all__ = ["ExecutionContextBuilder", "build_execution_context"]
