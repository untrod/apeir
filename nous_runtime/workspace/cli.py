"""CLI commands for Workspace Runtime."""

from __future__ import annotations

import json

import typer

from nous_runtime.workspace.registry import WorkspaceRegistry
from nous_runtime.workspace.resolver import resolve_workspace


workspace_app = typer.Typer(help="Manage runtime workspaces")


@workspace_app.command("create")
def create(name: str, path: str = typer.Option("", help="Workspace root path")):
    workspace = WorkspaceRegistry().create(name, path=path)
    typer.echo(json.dumps(workspace.to_dict(), ensure_ascii=False, indent=2))


@workspace_app.command("list")
def list_workspaces(as_json: bool = typer.Option(False, "--json", help="Emit JSON")):
    workspaces = [workspace.to_dict() for workspace in WorkspaceRegistry().list()]
    if as_json:
        typer.echo(json.dumps(workspaces, ensure_ascii=False, indent=2))
    else:
        for workspace in workspaces:
            typer.echo(f"{workspace['id']}\t{workspace['name']}\t{workspace['path']}")


@workspace_app.command("switch")
def switch(workspace_id: str):
    workspace = WorkspaceRegistry().switch(workspace_id)
    typer.echo(f"active workspace: {workspace.id}")


@workspace_app.command("current")
def current(as_json: bool = typer.Option(False, "--json", help="Emit JSON")):
    resolved = resolve_workspace()
    data = resolved.__dict__
    if as_json:
        typer.echo(json.dumps(data, ensure_ascii=False, indent=2))
    else:
        typer.echo(f"{resolved.workspace_id}\t{resolved.path}")


def register_workspace_commands(app: typer.Typer, inspect_app: typer.Typer | None = None) -> None:
    app.add_typer(workspace_app, name="workspace")
