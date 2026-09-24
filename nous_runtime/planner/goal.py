# -*- coding: utf-8 -*-
"""Goal model describing the requested outcome."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from nous_runtime.compat.ids import make_id


class GoalStatus(str, Enum):
    CREATED = "created"
    UNDERSTANDING = "understanding"
    PLANNING = "planning"
    EXECUTING = "executing"
    PAUSED = "paused"
    BLOCKED = "blocked"
    WAITING_USER = "waiting_user"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class Goal:
    """A user goal that the Runtime will plan and execute."""

    objective: str
    goal_id: str = ""
    status: GoalStatus = GoalStatus.CREATED
    constraints: dict[str, Any] = field(default_factory=dict)
    requirements: list[str] = field(default_factory=list)
    completion_criteria: list[str] = field(default_factory=list)
    current_plan_revision: int = 0
    blocker: str = ""
    created_at: str = ""
    updated_at: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if not self.goal_id:
            self.goal_id = make_id(prefix="goal")
        if not self.created_at:
            self.created_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    def start_understanding(self) -> None:
        self.status = GoalStatus.UNDERSTANDING
        self._touch()

    def start_planning(self) -> None:
        self.status = GoalStatus.PLANNING
        self._touch()

    def start_executing(self) -> None:
        self.status = GoalStatus.EXECUTING
        self.blocker = ""
        self._touch()

    def pause(self, reason: str = "") -> None:
        self.status = GoalStatus.PAUSED
        self.blocker = str(reason or "")
        self._touch()

    def block(self, reason: str) -> None:
        self.status = GoalStatus.BLOCKED
        self.blocker = str(reason or "")
        self._touch()

    def wait_for_user(self, reason: str) -> None:
        self.status = GoalStatus.WAITING_USER
        self.blocker = str(reason or "")
        self._touch()

    def resume(self) -> None:
        if self.status not in {
            GoalStatus.PAUSED,
            GoalStatus.BLOCKED,
            GoalStatus.WAITING_USER,
        }:
            raise ValueError(f"goal cannot resume from {self.status.value}")
        self.status = GoalStatus.UNDERSTANDING
        self.blocker = ""
        self._touch()

    def steer(
        self,
        instruction: str,
        *,
        constraints: dict[str, Any] | None = None,
    ) -> None:
        text = str(instruction or "").strip()
        if text:
            self.requirements.append(text)
        if constraints:
            self.constraints.update(dict(constraints))
        self._touch()

    def bind_plan_revision(self, revision: int) -> None:
        self.current_plan_revision = max(0, int(revision))
        self._touch()

    def complete(self) -> None:
        self.status = GoalStatus.COMPLETED
        self.blocker = ""
        self._touch()

    def fail(self, reason: str = "") -> None:
        self.status = GoalStatus.FAILED
        self.metadata["failure_reason"] = reason
        self._touch()

    def cancel(self) -> None:
        self.status = GoalStatus.CANCELLED
        self._touch()

    def _touch(self) -> None:
        self.updated_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    def to_dict(self) -> dict[str, Any]:
        return {
            "goal_id": self.goal_id,
            "objective": self.objective,
            "status": self.status.value,
            "constraints": self.constraints,
            "requirements": self.requirements,
            "completion_criteria": self.completion_criteria,
            "current_plan_revision": self.current_plan_revision,
            "blocker": self.blocker,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Goal":
        return cls(
            goal_id=str(data.get("goal_id") or ""),
            objective=str(data.get("objective") or ""),
            status=GoalStatus(str(data.get("status") or GoalStatus.CREATED.value)),
            constraints=dict(data.get("constraints") or {}),
            requirements=[str(item) for item in data.get("requirements") or ()],
            completion_criteria=[
                str(item) for item in data.get("completion_criteria") or ()
            ],
            current_plan_revision=int(data.get("current_plan_revision") or 0),
            blocker=str(data.get("blocker") or ""),
            created_at=str(data.get("created_at") or ""),
            updated_at=str(data.get("updated_at") or ""),
            metadata=dict(data.get("metadata") or {}),
        )
