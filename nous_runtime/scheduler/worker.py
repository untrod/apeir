"""Single-task worker primitive without Agent coupling."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from nous_runtime.scheduler.queue import TaskQueue
from nous_runtime.task.models import Task
from nous_runtime.task.state import TaskStatus


@dataclass(frozen=True)
class WorkResult:
    task: Task | None
    value: Any = None
    error: str = ""

    @property
    def ok(self) -> bool:
        return self.task is not None and not self.error


class Worker:
    """Run one queued task through its lifecycle using a supplied handler."""

    def __init__(self, handler: Callable[[Task], Any]) -> None:
        self.handler = handler

    def run_next(self, queue: TaskQueue) -> WorkResult:
        task = queue.dequeue()
        if task is None:
            return WorkResult(task=None)
        if task.status is TaskStatus.CREATED:
            task.transition(TaskStatus.PLANNED)
        if task.status in {TaskStatus.PLANNED, TaskStatus.WAITING}:
            task.transition(TaskStatus.RUNNING)
        try:
            value = self.handler(task)
        except Exception as exc:
            task.transition(TaskStatus.FAILED)
            return WorkResult(task=task, error=str(exc))
        task.transition(TaskStatus.COMPLETED)
        return WorkResult(task=task, value=value)


__all__ = ["Worker", "WorkResult"]
