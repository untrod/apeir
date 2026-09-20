"""Serializable task planning models."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any

from nous_runtime.core.errors import CapabilityError


@dataclass(frozen=True)
class PlanStep:
    step_id: str
    name: str
    capability: str = "reasoning"
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "step_id": self.step_id,
            "name": self.name,
            "capability": self.capability,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class TaskPlan:
    task_id: str
    steps: tuple[PlanStep, ...]
    dependencies: dict[str, tuple[str, ...]] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    plan_id: str = field(default_factory=lambda: f"plan_{uuid.uuid4().hex}")

    def __post_init__(self) -> None:
        known = {step.step_id for step in self.steps}
        for step_id, requirements in self.dependencies.items():
            if step_id not in known or any(item not in known for item in requirements):
                raise CapabilityError("plan dependencies must reference existing steps")

    def to_dict(self) -> dict[str, Any]:
        return {
            "plan_id": self.plan_id,
            "task_id": self.task_id,
            "steps": [step.to_dict() for step in self.steps],
            "dependencies": {key: list(value) for key, value in self.dependencies.items()},
            "metadata": dict(self.metadata),
        }


__all__ = ["PlanStep", "TaskPlan"]
