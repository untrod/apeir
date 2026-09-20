"""CLI helpers for persisted local Runtime tasks."""

from __future__ import annotations

import json
from pathlib import Path

import typer

from nous_runtime.project.workspace import find_workspace
from nous_runtime.task.manager import TaskManager
from nous_runtime.task.models import Task
from nous_runtime.task.state import Priority, TaskStatus, normalize_priority


def task_storage_path() -> Path:
    workspace = find_workspace()
    root = workspace if workspace is not None else Path.cwd() / ".nous"
    return root / "runtime_tasks.json"


def get_task_manager() -> TaskManager:
    return TaskManager(task_storage_path())


def create_task(
    name: str,
    description: str,
    priority: str,
) -> Task:
    return get_task_manager().create(
        name,
        description,
        priority=normalize_priority(priority),
    )


def echo_task(task: Task, *, as_json: bool = False) -> None:
    if as_json:
        typer.echo(json.dumps(task.to_dict(), ensure_ascii=False, indent=2))
        return
    typer.echo(f"{task.id} [{task.status.value}] {task.name}")
    typer.echo(f"  Priority: {task.priority.value}")
    if task.description:
        typer.echo(f"  Description: {task.description}")


def echo_tasks(tasks: list[Task], *, as_json: bool = False) -> None:
    if as_json:
        typer.echo(
            json.dumps(
                [task.to_dict() for task in tasks],
                ensure_ascii=False,
                indent=2,
            )
        )
        return
    if not tasks:
        typer.echo("No Runtime tasks.")
        return
    for task in tasks:
        typer.echo(
            f"{task.id} [{task.status.value}] [{task.priority.value}] {task.name}"
        )


def echo_status(task_id: str = "", *, as_json: bool = False) -> bool:
    manager = get_task_manager()
    if task_id:
        task = manager.get(task_id)
        if task is None:
            return False
        if as_json:
            typer.echo(
                json.dumps(
                    {"task_id": task.id, "status": task.status.value},
                    indent=2,
                )
            )
        else:
            typer.echo(f"{task.id}: {task.status.value}")
        return True
    counts = manager.counts()
    payload = {"total": sum(counts.values()), "states": counts}
    if as_json:
        typer.echo(json.dumps(payload, indent=2))
    else:
        typer.echo(f"Runtime Tasks: {payload['total']}")
        for status in TaskStatus:
            typer.echo(f"  {status.value}: {counts[status.value]}")
    return True


__all__ = [
    "Priority",
    "create_task",
    "echo_status",
    "echo_task",
    "echo_tasks",
    "get_task_manager",
    "task_storage_path",
]
