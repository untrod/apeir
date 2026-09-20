"""Task registry, lifecycle facade, and optional JSON persistence."""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Any, Iterable, Mapping

from nous_runtime.artifact import Artifact, ArtifactRegistry
from nous_runtime.core.state import RuntimeState
from nous_runtime.task.exceptions import TaskNotFoundError, TaskRuntimeError
from nous_runtime.task.lifecycle import TaskLifecycle
from nous_runtime.task.models import Task
from nous_runtime.task.state import (
    Priority,
    TaskStatus,
    normalize_status,
    validate_transition,
)


class TaskManager:
    """Manage Runtime tasks without taking over existing Planner tasks."""

    def __init__(
        self,
        storage_path: str | Path | None = None,
        *,
        artifact_registry: ArtifactRegistry | None = None,
        runtime_state: RuntimeState | None = None,
    ) -> None:
        self.storage_path = Path(storage_path) if storage_path else None
        self.artifacts = artifact_registry or ArtifactRegistry()
        self.state = runtime_state or RuntimeState()
        self.lifecycle = TaskLifecycle()
        self._tasks = self.state.tasks
        self._lock = threading.RLock()
        self._load()

    def create(
        self,
        name: str,
        description: str = "",
        *,
        priority: Priority | str = Priority.NORMAL,
        metadata: Mapping[str, Any] | None = None,
    ) -> Task:
        return self.register(
            Task(
                name=name,
                description=description,
                priority=priority,
                metadata=dict(metadata or {}),
            )
        )

    def register(self, task: Task) -> Task:
        if not isinstance(task, Task):
            raise TaskRuntimeError("task must be a Runtime Task instance")
        with self._lock:
            if task.id in self._tasks:
                raise TaskRuntimeError(f"task already registered: {task.id}")
            self.state.register("tasks", task.id, task)
            self._save_unlocked()
        return task

    def get(self, task_id: str) -> Task | None:
        with self._lock:
            return self.state.get("tasks", str(task_id))

    def require(self, task_id: str) -> Task:
        task = self.get(task_id)
        if task is None:
            raise TaskNotFoundError(f"task not found: {task_id}")
        return task

    def list(self, status: TaskStatus | str | None = None) -> list[Task]:
        normalized = normalize_status(status) if status else None
        with self._lock:
            tasks = list(self._tasks.values())
        if normalized is not None:
            tasks = [task for task in tasks if task.status is normalized]
        return sorted(tasks, key=lambda task: (task.created_at, task.id), reverse=True)

    def transition(self, task_id: str, target: TaskStatus | str) -> Task:
        with self._lock:
            task = self.require(task_id)
            self.lifecycle.transition(task, target)
            self._save_unlocked()
            return task

    def attach_artifact(self, task_id: str, artifact: Artifact) -> Task:
        with self._lock:
            task = self.require(task_id)
            registered = self.artifacts.get(artifact.id)
            if registered is None:
                self.artifacts.register(artifact)
            elif registered != artifact:
                raise TaskRuntimeError(f"artifact id conflict: {artifact.id}")
            artifact_ids = list(task.metadata.get("artifacts") or [])
            if artifact.id not in artifact_ids:
                artifact_ids.append(artifact.id)
                task.metadata["artifacts"] = artifact_ids
                self._save_unlocked()
            return task

    def complete(self, task_id: str, artifacts: Iterable[Artifact] = ()) -> Task:
        task = self.require(task_id)
        validate_transition(task.status, TaskStatus.COMPLETED)
        for artifact in artifacts:
            self.attach_artifact(task_id, artifact)
        return self.transition(task.id, TaskStatus.COMPLETED)

    def remove(self, task_id: str) -> Task | None:
        with self._lock:
            task = self.state.remove("tasks", str(task_id))
            if task is not None:
                self._save_unlocked()
            return task

    def counts(self) -> dict[str, int]:
        counts = {status.value: 0 for status in TaskStatus}
        with self._lock:
            for task in self._tasks.values():
                counts[task.status.value] += 1
        return counts

    def _load(self) -> None:
        if self.storage_path is None or not self.storage_path.is_file():
            return
        try:
            data = json.loads(self.storage_path.read_text(encoding="utf-8"))
            tasks = [Task.from_dict(item) for item in data.get("tasks", [])]
        except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise TaskRuntimeError(f"failed to load Runtime tasks: {exc}") from exc
        for task in tasks:
            self.state.register("tasks", task.id, task)

    def _save_unlocked(self) -> None:
        if self.storage_path is None:
            return
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.storage_path.with_suffix(self.storage_path.suffix + ".tmp")
        payload = {
            "schema_version": 1,
            "tasks": [task.to_dict() for task in self._tasks.values()],
        }
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        os.replace(temporary, self.storage_path)


__all__ = ["TaskManager"]
