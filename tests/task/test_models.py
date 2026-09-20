"""Task model tests."""

import pytest

from nous_runtime.task import Priority, Task, TaskRuntimeError, TaskStatus


def test_task_creation_has_runtime_defaults():
    task = Task(name="Generate report", description="Create the weekly report")

    assert task.id.startswith("task_")
    assert task.status is TaskStatus.CREATED
    assert task.priority is Priority.NORMAL
    assert task.created_at.endswith("Z")
    assert task.updated_at.endswith("Z")


def test_task_round_trip_preserves_contract():
    task = Task(
        id="task-fixed",
        name="Analyze incident",
        description="Inspect the failure",
        priority=Priority.HIGH,
        metadata={"project": "nous"},
    )

    restored = Task.from_dict(task.to_dict())

    assert restored.to_dict() == task.to_dict()
    assert restored.metadata is not task.metadata


def test_task_requires_name_and_normalizes_priority():
    with pytest.raises(TaskRuntimeError, match="name is required"):
        Task(name="")

    assert Task(name="Index", priority="low").priority is Priority.LOW
