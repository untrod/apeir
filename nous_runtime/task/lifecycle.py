"""Lifecycle service for Execution Runtime tasks."""

from __future__ import annotations

from nous_runtime.task.models import Task
from nous_runtime.task.state import TaskStatus


class TaskLifecycle:
    """Named lifecycle operations over the canonical Task transition table."""

    @staticmethod
    def transition(task: Task, target: TaskStatus | str) -> Task:
        return task.transition(target)

    def plan(self, task: Task) -> Task:
        return self.transition(task, TaskStatus.PLANNED)

    def start(self, task: Task) -> Task:
        return self.transition(task, TaskStatus.RUNNING)

    def wait(self, task: Task) -> Task:
        return self.transition(task, TaskStatus.WAITING)

    def resume(self, task: Task) -> Task:
        return self.transition(task, TaskStatus.RUNNING)

    def complete(self, task: Task) -> Task:
        return self.transition(task, TaskStatus.COMPLETED)

    def fail(self, task: Task) -> Task:
        return self.transition(task, TaskStatus.FAILED)

    def cancel(self, task: Task) -> Task:
        return self.transition(task, TaskStatus.CANCELLED)


__all__ = ["TaskLifecycle"]
