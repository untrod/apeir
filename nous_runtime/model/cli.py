"""CLI commands for Model Runtime."""

from __future__ import annotations

import json

import typer

from nous_runtime.model.runtime import ModelRuntime
from nous_runtime.model.types import ModelRequest


model_runtime_app = typer.Typer(help="Inspect model runtime selection")


@model_runtime_app.command("select")
def select(
    task_type: str = typer.Argument(..., help="Task type"),
    privacy: str = typer.Option("standard", help="Privacy mode"),
    as_json: bool = typer.Option(False, "--json", help="Emit JSON"),
):
    selection = ModelRuntime().select(ModelRequest(task_type=task_type, privacy=privacy))
    if as_json:
        typer.echo(json.dumps(selection.to_dict(), ensure_ascii=False, indent=2))
    else:
        typer.echo(f"{selection.provider}/{selection.model}: {selection.reason}")


def register_model_runtime_commands(app: typer.Typer, inspect_app: typer.Typer | None = None) -> None:
    app.add_typer(model_runtime_app, name="model-runtime")
