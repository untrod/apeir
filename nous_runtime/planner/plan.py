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
    BLOCKED = "blocked"


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
            "params": self.params,
            "status": self.status.value,
            "depends_on": self.depends_on,
            "expected_output": self.expected_output,
            "retry_count": self.retry_count,
            "max_retries": self.max_retries,
            "timeout_seconds": self.timeout_seconds,
            "result": self.result,
            "error": self.error,
            "observations": self.observations,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "observation_ids": [
                o.get("id", o.get("observation_id", ""))
                for o in self.observations
                if isinstance(o, dict)
            ],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Task":
        return cls(
            task_id=str(data.get("task_id") or ""),
            description=str(data.get("description") or ""),
            capability_id=str(data.get("capability_id") or ""),
            params=dict(data.get("params") or {}),
            status=TaskStatus(str(data.get("status") or TaskStatus.PENDING.value)),
            depends_on=[str(item) for item in data.get("depends_on") or ()],
            expected_output=str(data.get("expected_output") or ""),
            retry_count=int(data.get("retry_count") or 0),
            max_retries=int(data.get("max_retries") or 3),
            timeout_seconds=int(data.get("timeout_seconds") or 60),
            result=data.get("result"),
            error=str(data.get("error") or ""),
            observations=[
                dict(item)
                for item in data.get("observations") or ()
                if isinstance(item, dict)
            ],
            started_at=str(data.get("started_at") or ""),
            completed_at=str(data.get("completed_at") or ""),
        )


@dataclass(frozen=True)
class PlanRevision:
    """Immutable snapshot of the plan immediately before a revision."""

    revision: int
    reason: str
    created_at: str
    tasks: tuple[dict[str, Any], ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "revision": self.revision,
            "reason": self.reason,
            "created_at": self.created_at,
            "tasks": [dict(item) for item in self.tasks],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "PlanRevision":
        return cls(
            revision=int(data.get("revision") or 1),
            reason=str(data.get("reason") or ""),
            created_at=str(data.get("created_at") or ""),
            tasks=tuple(
                dict(item) for item in data.get("tasks") or () if isinstance(item, dict)
            ),
        )


@dataclass
class Plan:
    """A plan decomposing a goal into tasks."""

    goal_id: str
    plan_id: str = ""
    tasks: list[Task] = field(default_factory=list)
    status: PlanStatus = PlanStatus.BUILDING
    created_at: str = ""
    revision: int = 1
    revision_history: list[PlanRevision] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if not self.plan_id:
            self.plan_id = make_id(prefix="plan")
        if not self.created_at:
            self.created_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    def add_task(
        self,
        description: str,
        capability_id: str = "",
        depends_on: list[str] | None = None,
        *,
        revision_reason: str = "",
        **params,
    ) -> Task:
        self._prepare_mutation(revision_reason)
        task = Task(description=description, capability_id=capability_id, params=params)
        if depends_on:
            task.depends_on = depends_on
        self.tasks.append(task)
        return task

    def mark_ready(self) -> None:
        self.status = PlanStatus.READY

    def note_revision(self, *, reason: str) -> None:
        """Advance the audit revision before external steering or replanning."""
        self._record_revision(reason)

    def replace_tasks(self, tasks: list[Task], *, reason: str) -> None:
        self._record_revision(reason)
        self.tasks = list(tasks)

    def remove_task(self, task_id: str, *, reason: str) -> Task:
        for index, task in enumerate(self.tasks):
            if task.task_id == task_id:
                self._record_revision(reason)
                removed = self.tasks.pop(index)
                for remaining in self.tasks:
                    remaining.depends_on = [
                        item for item in remaining.depends_on if item != task_id
                    ]
                return removed
        raise KeyError(task_id)

    def replace_task(self, task_id: str, replacement: Task, *, reason: str) -> None:
        for index, task in enumerate(self.tasks):
            if task.task_id == task_id:
                self._record_revision(reason)
                self.tasks[index] = replacement
                return
        raise KeyError(task_id)

    def reorder(self, task_ids: list[str], *, reason: str) -> None:
        if len(task_ids) != len(self.tasks) or set(task_ids) != {
            task.task_id for task in self.tasks
        }:
            raise ValueError("reorder must contain every task id exactly once")
        self._record_revision(reason)
        by_id = {task.task_id: task for task in self.tasks}
        self.tasks = [by_id[task_id] for task_id in task_ids]

    def mark_skipped(self, task_id: str, *, reason: str) -> None:
        task = self.require_task(task_id)
        self._record_revision(reason)
        task.status = TaskStatus.SKIPPED
        task.error = ""

    def mark_blocked(self, task_id: str, *, reason: str) -> None:
        task = self.require_task(task_id)
        self._record_revision(reason)
        task.status = TaskStatus.BLOCKED
        task.error = str(reason or "")

    def require_task(self, task_id: str) -> Task:
        for task in self.tasks:
            if task.task_id == task_id:
                return task
        raise KeyError(task_id)

    def _prepare_mutation(self, reason: str) -> None:
        if self.status is not PlanStatus.BUILDING or reason:
            self._record_revision(reason or "plan updated")

    def _record_revision(self, reason: str) -> None:
        text = str(reason or "").strip()
        if not text:
            raise ValueError("plan revision reason is required")
        self.revision_history.append(
            PlanRevision(
                revision=self.revision,
                reason=text,
                created_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                tasks=tuple(task.to_dict() for task in self.tasks),
            )
        )
        self.revision += 1

    def ready_tasks(self, completed_ids: set[str]) -> list[Task]:
        """Return tasks whose dependencies are all complete."""
        return [
            t
            for t in self.tasks
            if t.status == TaskStatus.PENDING and t.is_ready(completed_ids)
        ]

    def all_done(self) -> bool:
        return all(
            t.status in (TaskStatus.COMPLETED, TaskStatus.SKIPPED) for t in self.tasks
        )

    def any_failed(self) -> bool:
        return any(t.status == TaskStatus.FAILED for t in self.tasks)

    def progress(self) -> dict[str, int]:
        total = len(self.tasks)
        done = sum(1 for t in self.tasks if t.status == TaskStatus.COMPLETED)
        failed = sum(1 for t in self.tasks if t.status == TaskStatus.FAILED)
        skipped = sum(1 for t in self.tasks if t.status == TaskStatus.SKIPPED)
        blocked = sum(1 for t in self.tasks if t.status == TaskStatus.BLOCKED)
        pending = total - done - failed - skipped - blocked
        return {
            "total": total,
            "done": done,
            "failed": failed,
            "skipped": skipped,
            "blocked": blocked,
            "pending": pending,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "plan_id": self.plan_id,
            "goal_id": self.goal_id,
            "tasks": [t.to_dict() for t in self.tasks],
            "status": self.status.value,
            "created_at": self.created_at,
            "revision": self.revision,
            "revision_history": [item.to_dict() for item in self.revision_history],
            "progress": self.progress(),
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Plan":
        return cls(
            plan_id=str(data.get("plan_id") or ""),
            goal_id=str(data.get("goal_id") or ""),
            tasks=[Task.from_dict(item) for item in data.get("tasks") or ()],
            status=PlanStatus(str(data.get("status") or PlanStatus.BUILDING.value)),
            created_at=str(data.get("created_at") or ""),
            revision=max(1, int(data.get("revision") or 1)),
            revision_history=[
                PlanRevision.from_dict(item)
                for item in data.get("revision_history") or ()
            ],
            metadata=dict(data.get("metadata") or {}),
        )
