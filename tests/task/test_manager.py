"""Task manager and Artifact integration tests."""

import json

from nous_runtime.artifact import Artifact
from nous_runtime.task import Priority, TaskManager, TaskStatus


def test_task_manager_creates_queries_and_filters():
    manager = TaskManager()
    high = manager.create("Incident", priority=Priority.HIGH)
    low = manager.create("Index", priority=Priority.LOW)
    manager.transition(high.id, TaskStatus.PLANNED)

    assert manager.get(high.id) is high
    assert manager.state.get("tasks", high.id) is high
    assert manager.list(TaskStatus.PLANNED) == [high]
    assert {task.id for task in manager.list()} == {high.id, low.id}


def test_task_manager_persists_tasks_without_database(tmp_path):
    path = tmp_path / ".nous" / "runtime_tasks.json"
    first = TaskManager(path)
    task = first.create("Persistent task", description="Survive CLI restart")
    first.transition(task.id, TaskStatus.PLANNED)

    restarted = TaskManager(path)
    restored = restarted.require(task.id)

    assert restored.status is TaskStatus.PLANNED
    assert restored.description == "Survive CLI restart"
    assert json.loads(path.read_text(encoding="utf-8"))["schema_version"] == 1


def test_completed_task_records_artifact_ids():
    manager = TaskManager()
    task = manager.create("Generate code")
    manager.transition(task.id, TaskStatus.PLANNED)
    manager.transition(task.id, TaskStatus.RUNNING)
    artifact = Artifact(type="code", name="runtime.py", creator="worker")

    completed = manager.complete(task.id, [artifact])

    assert completed.status is TaskStatus.COMPLETED
    assert completed.metadata["artifacts"] == [artifact.id]
    assert manager.artifacts.get(artifact.id) is artifact


def test_task_manager_counts_all_lifecycle_states():
    manager = TaskManager()
    task = manager.create("Planned")
    manager.transition(task.id, TaskStatus.PLANNED)
    manager.create("Created")

    counts = manager.counts()

    assert counts["CREATED"] == 1
    assert counts["PLANNED"] == 1
    assert sum(counts.values()) == 2
