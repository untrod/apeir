"""Execution Runtime task exceptions."""

from nous_runtime.core.errors import TaskError


class TaskRuntimeError(TaskError):
    """Base exception for the Execution Runtime task subsystem."""


class TaskNotFoundError(TaskRuntimeError, LookupError):
    """Raised when a requested Runtime task does not exist."""


class InvalidTaskTransitionError(TaskRuntimeError):
    """Raised when a task lifecycle transition is not allowed."""


__all__ = [
    "InvalidTaskTransitionError",
    "TaskNotFoundError",
    "TaskRuntimeError",
]
