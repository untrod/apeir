"""Stable priority queue for Runtime tasks."""

from __future__ import annotations

import heapq
import itertools
import threading

from nous_runtime.task.exceptions import TaskRuntimeError
from nous_runtime.task.models import Task
from nous_runtime.task.state import Priority, TaskStatus

_PRIORITY_WEIGHT = {
    Priority.HIGH: 0,
    Priority.NORMAL: 1,
    Priority.LOW: 2,
}


class TaskQueue:
    """Thread-safe HIGH > NORMAL > LOW queue with FIFO tie-breaking."""

    def __init__(self) -> None:
        self._items: list[tuple[int, int, Task]] = []
        self._task_ids: set[str] = set()
        self._sequence = itertools.count()
        self._lock = threading.RLock()

    def enqueue(self, task: Task) -> Task:
        if not isinstance(task, Task):
            raise TaskRuntimeError("scheduler accepts Runtime Task instances only")
        if task.status in TaskStatus.terminal():
            raise TaskRuntimeError(f"cannot queue terminal task: {task.id}")
        with self._lock:
            if task.id in self._task_ids:
                raise TaskRuntimeError(f"task already queued: {task.id}")
            heapq.heappush(
                self._items,
                (_PRIORITY_WEIGHT[task.priority], next(self._sequence), task),
            )
            self._task_ids.add(task.id)
        return task

    def dequeue(self) -> Task | None:
        with self._lock:
            if not self._items:
                return None
            _, _, task = heapq.heappop(self._items)
            self._task_ids.remove(task.id)
            return task

    def peek(self) -> Task | None:
        with self._lock:
            return self._items[0][2] if self._items else None

    def __len__(self) -> int:
        with self._lock:
            return len(self._items)


__all__ = ["TaskQueue"]
