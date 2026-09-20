"""R4 deployment-runtime CLI."""

from __future__ import annotations

import json
from pathlib import Path

import typer

from nous_runtime.artifact import ContentAddressedArtifactStore
from nous_runtime.deployment.runtime import DeploymentRuntime
from nous_runtime.project.workspace import default_workspace_path


deploy_app = typer.Typer(help="Deploy verified artifacts with rollback.")


def _runtime(state_dir: Path, artifact_root: Path) -> DeploymentRuntime:
    return DeploymentRuntime(state_dir, ContentAddressedArtifactStore(artifact_root))


@deploy_app.command("apply")
def apply_deployment(
    digest: str = typer.Argument(...),
    target: str = typer.Option(..., "--target"),
    deployment_id: str = typer.Option("", "--deployment-id"),
    artifact_root: Path = typer.Option(default_workspace_path("artifacts"), "--artifact-root"),
    state_dir: Path = typer.Option(default_workspace_path("deployment"), "--state-dir"),
) -> None:
    record = _runtime(state_dir, artifact_root).deploy_static(
        digest, target, deployment_id=deployment_id
    )
    typer.echo(json.dumps(record.to_dict(), ensure_ascii=False, sort_keys=True))


@deploy_app.command("status")
def deployment_status(
    deployment_id: str = typer.Argument(...),
    artifact_root: Path = typer.Option(default_workspace_path("artifacts"), "--artifact-root"),
    state_dir: Path = typer.Option(default_workspace_path("deployment"), "--state-dir"),
) -> None:
    record = _runtime(state_dir, artifact_root).get(deployment_id)
    if record is None:
        typer.echo(json.dumps({"error": "deployment not found"}))
        raise typer.Exit(code=1)
    typer.echo(json.dumps(record.to_dict(), ensure_ascii=False, sort_keys=True))


@deploy_app.command("list")
def list_deployments(
    artifact_root: Path = typer.Option(default_workspace_path("artifacts"), "--artifact-root"),
    state_dir: Path = typer.Option(default_workspace_path("deployment"), "--state-dir"),
) -> None:
    values = [item.to_dict() for item in _runtime(state_dir, artifact_root).list()]
    typer.echo(json.dumps(values, ensure_ascii=False, sort_keys=True))
