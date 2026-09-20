"""Task status, priority, and legal lifecycle transitions."""

from __future__ import annotations

from enum import Enum

from nous_runtime.task.exceptions import InvalidTaskTransitionError


class TaskStatus(str, Enum):
    CREATED = "CREATED"
    PLANNED = "PLANNED"
    RUNNING = "RUNNING"
    WAITING = "WAITING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"

    @classmethod
    def terminal(cls) -> frozenset["TaskStatus"]:
        return frozenset({cls.COMPLETED, cls.FAILED, cls.CANCELLED})


class Priority(str, Enum):
    HIGH = "HIGH"
    NORMAL = "NORMAL"
    LOW = "LOW"


VALID_TASK_TRANSITIONS: dict[TaskStatus, frozenset[TaskStatus]] = {
    TaskStatus.CREATED: frozenset({TaskStatus.PLANNED, TaskStatus.CANCELLED}),
    TaskStatus.PLANNED: frozenset(
        {TaskStatus.RUNNING, TaskStatus.WAITING, TaskStatus.FAILED, TaskStatus.CANCELLED}
    ),
    TaskStatus.RUNNING: frozenset(
        {TaskStatus.WAITING, TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED}
    ),
    TaskStatus.WAITING: frozenset(
        {TaskStatus.RUNNING, TaskStatus.FAILED, TaskStatus.CANCELLED}
    ),
    TaskStatus.COMPLETED: frozenset(),
    TaskStatus.FAILED: frozenset(),
    TaskStatus.CANCELLED: frozenset(),
}


def normalize_status(status: TaskStatus | str) -> TaskStatus:
    if isinstance(status, TaskStatus):
        return status
    try:
        return TaskStatus(str(status).strip().upper())
    except ValueError as exc:
        raise InvalidTaskTransitionError(f"unknown task status: {status}") from exc


def normalize_priority(priority: Priority | str) -> Priority:
    if isinstance(priority, Priority):
        return priority
    try:
        return Priority(str(priority).strip().upper())
    except ValueError as exc:
        raise InvalidTaskTransitionError(f"unknown task priority: {priority}") from exc


def validate_transition(
    current: TaskStatus | str,
    target: TaskStatus | str,
) -> tuple[TaskStatus, TaskStatus]:
    current_status = normalize_status(current)
    target_status = normalize_status(target)
    if target_status not in VALID_TASK_TRANSITIONS[current_status]:
        raise InvalidTaskTransitionError(
            f"invalid task transition: {current_status.value} -> {target_status.value}"
        )
    return current_status, target_status


__all__ = [
    "Priority",
    "TaskStatus",
    "VALID_TASK_TRANSITIONS",
    "normalize_priority",
    "normalize_status",
    "validate_transition",
]
