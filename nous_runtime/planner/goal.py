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
        self._touch()

    def complete(self) -> None:
        self.status = GoalStatus.COMPLETED
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
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "metadata": self.metadata,
        }
