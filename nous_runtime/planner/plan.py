# -*- coding: utf-8 -*-
"""Plan Model -how to accomplish a goal."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from nous_runtime.compat.ids import make_id


class TaskStatus(str, Enum):
    PENDING = "pending"
    READY = "ready"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class PlanStatus(str, Enum):
    BUILDING = "building"
    READY = "ready"
    EXECUTING = "executing"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class TaskDependency:
    """A dependency edge: task depends on another task."""
    task_id: str
    depends_on: str


@dataclass
class Task:
    """A single step in a plan."""

    description: str
    task_id: str = ""
    capability_id: str = ""
    params: dict[str, Any] = field(default_factory=dict)
    status: TaskStatus = TaskStatus.PENDING
    depends_on: list[str] = field(default_factory=list)
    expected_output: str = ""
    retry_count: int = 0
    max_retries: int = 3
    timeout_seconds: int = 60
    result: Any = None
    error: str = ""
    observations: list[dict[str, Any]] = field(default_factory=list)
    started_at: str = ""
    completed_at: str = ""

    def __post_init__(self):
        if not self.task_id:
            self.task_id = make_id(prefix="task")

    def is_ready(self, completed: set[str]) -> bool:
        """Check if all dependencies are satisfied."""
        return all(d in completed for d in self.depends_on)

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "description": self.description,
            "capability_id": self.capability_id,
            "status": self.status.value,
            "depends_on": self.depends_on,
            "observation_ids": [
                o.get("id", o.get("observation_id", ""))
                for o in self.observations
                if isinstance(o, dict)
            ],
        }


@dataclass
class Plan:
    """A plan decomposing a goal into tasks."""

    goal_id: str
    plan_id: str = ""
    tasks: list[Task] = field(default_factory=list)
    status: PlanStatus = PlanStatus.BUILDING
    created_at: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if not self.plan_id:
            self.plan_id = make_id(prefix="plan")
        if not self.created_at:
            self.created_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    def add_task(self, description: str, capability_id: str = "", depends_on: list[str] | None = None, **params) -> Task:
        task = Task(description=description, capability_id=capability_id, params=params)
        if depends_on:
            task.depends_on = depends_on
        self.tasks.append(task)
        return task

    def ready_tasks(self, completed_ids: set[str]) -> list[Task]:
        """Return tasks whose dependencies are all complete."""
        return [t for t in self.tasks if t.status == TaskStatus.PENDING and t.is_ready(completed_ids)]

    def all_done(self) -> bool:
        return all(t.status in (TaskStatus.COMPLETED, TaskStatus.SKIPPED) for t in self.tasks)

    def any_failed(self) -> bool:
        return any(t.status == TaskStatus.FAILED for t in self.tasks)

    def progress(self) -> dict[str, int]:
        total = len(self.tasks)
        done = sum(1 for t in self.tasks if t.status == TaskStatus.COMPLETED)
        failed = sum(1 for t in self.tasks if t.status == TaskStatus.FAILED)
        pending = total - done - failed
        return {"total": total, "done": done, "failed": failed, "pending": pending}

    def to_dict(self) -> dict[str, Any]:
        return {
            "plan_id": self.plan_id,
            "goal_id": self.goal_id,
            "tasks": [t.to_dict() for t in self.tasks],
            "status": self.status.value,
            "progress": self.progress(),
        }
