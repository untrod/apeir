"""Task analysis contracts."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class TaskAnalysis:
    """A lightweight, explainable description of a Runtime task."""

    task_id: str
    task_type: str
    complexity: str
    required_capabilities: tuple[str, ...] = ()
    constraints: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "task_type": self.task_type,
            "complexity": self.complexity,
            "required_capabilities": list(self.required_capabilities),
            "constraints": dict(self.constraints),
            "metadata": dict(self.metadata),
        }


__all__ = ["TaskAnalysis"]
