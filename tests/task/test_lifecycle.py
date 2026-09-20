"""Task lifecycle transition tests."""

import pytest

from nous_runtime.task import (
    InvalidTaskTransitionError,
    Task,
    TaskLifecycle,
    TaskStatus,
)


def test_task_lifecycle_completes_legal_sequence():
    task = Task(name="Long task")
    lifecycle = TaskLifecycle()

    lifecycle.plan(task)
    lifecycle.start(task)
    lifecycle.complete(task)

    assert task.status is TaskStatus.COMPLETED
    assert task.updated_at >= task.created_at


def test_task_lifecycle_waits_and_resumes():
    task = Task(name="Approval task")
    lifecycle = TaskLifecycle()

    lifecycle.plan(task)
    lifecycle.wait(task)
    lifecycle.resume(task)

    assert task.status is TaskStatus.RUNNING


def test_terminal_task_rejects_restart():
    task = Task(name="Finished task")
    task.transition(TaskStatus.PLANNED)
    task.transition(TaskStatus.RUNNING)
    task.transition(TaskStatus.COMPLETED)

    with pytest.raises(
        InvalidTaskTransitionError,
        match="COMPLETED -> RUNNING",
    ):
        task.transition(TaskStatus.RUNNING)


def test_created_task_cannot_skip_planning():
    task = Task(name="Unplanned task")

    with pytest.raises(InvalidTaskTransitionError, match="CREATED -> RUNNING"):
        task.transition(TaskStatus.RUNNING)
