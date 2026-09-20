"""R3 content-addressed artifact commands."""

from __future__ import annotations

import json
from pathlib import Path

import typer

from nous_runtime.project.workspace import default_workspace_path

from .content_store import ContentAddressedArtifactStore


artifact_app = typer.Typer(help="Content-addressed artifact storage and integrity.")


def _store(root: Path) -> ContentAddressedArtifactStore:
    return ContentAddressedArtifactStore(root)


@artifact_app.command("add")
def add_artifact(
    source: Path = typer.Argument(..., exists=True, dir_okay=False),
    artifact_type: str = typer.Option("file", "--type"),
    name: str = typer.Option("", "--name"),
    media_type: str = typer.Option("application/octet-stream", "--media-type"),
    root: Path = typer.Option(default_workspace_path("artifacts"), "--root"),
) -> None:
    result = _store(root).store_file(
        source,
        artifact_type=artifact_type,
        name=name or source.name,
        media_type=media_type,
        produced_by="nous artifact add",
    )
    typer.echo(json.dumps(result, ensure_ascii=False, sort_keys=True))


@artifact_app.command("list")
def list_artifacts(
    artifact_type: str = typer.Option("", "--type"),
    root: Path = typer.Option(default_workspace_path("artifacts"), "--root"),
) -> None:
    values = [item.to_dict() for item in _store(root).list(artifact_type or None)]
    typer.echo(json.dumps(values, ensure_ascii=False, sort_keys=True))


@artifact_app.command("verify")
def verify_artifact(
    digest: str = typer.Argument(...),
    root: Path = typer.Option(default_workspace_path("artifacts"), "--root"),
) -> None:
    verified = _store(root).verify(digest)
    typer.echo(json.dumps({"digest": digest, "verified": verified}, sort_keys=True))
    if not verified:
        raise typer.Exit(code=1)


@artifact_app.command("pin")
def pin_artifact(
    digest: str = typer.Argument(...),
    reason: str = typer.Option("user", "--reason"),
    root: Path = typer.Option(default_workspace_path("artifacts"), "--root"),
) -> None:
    typer.echo(json.dumps(_store(root).pin(digest, reason), sort_keys=True))


@artifact_app.command("unpin")
def unpin_artifact(
    digest: str = typer.Argument(...),
    root: Path = typer.Option(default_workspace_path("artifacts"), "--root"),
) -> None:
    typer.echo(json.dumps(_store(root).unpin(digest), sort_keys=True))


@artifact_app.command("gc")
def garbage_collect(
    apply: bool = typer.Option(False, "--apply", help="Delete unpinned objects"),
    root: Path = typer.Option(default_workspace_path("artifacts"), "--root"),
) -> None:
    typer.echo(
        json.dumps(_store(root).garbage_collect(dry_run=not apply), sort_keys=True)
    )
