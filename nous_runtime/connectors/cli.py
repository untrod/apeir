"""Connector Runtime CLI."""

from __future__ import annotations

import json
from pathlib import Path

import typer

from nous_runtime.connectors.models import ConnectorManifest
from nous_runtime.connectors.store import ConnectorStore

connector_app = typer.Typer(help="Manage secure enterprise connectors")


def _root() -> Path:
    return Path(".").resolve()


def _emit(data, as_json: bool) -> None:
    if as_json:
        typer.echo(json.dumps(data, ensure_ascii=False, indent=2))
    elif isinstance(data, list):
        for item in data:
            typer.echo(f"{item.get('connector_id', '')}\t{'revoked' if item.get('revoked') else 'active'}")
    else:
        typer.echo(str(data))


@connector_app.command("list")
def list_connectors(as_json: bool = typer.Option(False, "--json")):
    _emit(ConnectorStore(_root()).list(), as_json)


@connector_app.command("register")
def register_connector(manifest_path: Path, credential_ref: str = typer.Option("", "--credential-ref"), as_json: bool = typer.Option(False, "--json")):
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest = ConnectorManifest.from_dict(data)
    ConnectorStore(_root()).register(manifest, credential_ref=credential_ref)
    _emit({"connector_id": manifest.connector_id, "registered": True}, as_json)


@connector_app.command("inspect")
def inspect_connector(connector_id: str, as_json: bool = typer.Option(False, "--json")):
    item = ConnectorStore(_root()).get(connector_id)
    if item is None:
        raise typer.BadParameter("connector is not registered")
    manifest, credential_ref, revoked = item
    _emit({"manifest": manifest.to_dict(), "credential_configured": bool(credential_ref), "revoked": revoked}, as_json)


@connector_app.command("enable")
def enable_connector(connector_id: str, as_json: bool = typer.Option(False, "--json")):
    _emit({"connector_id": connector_id, "enabled": ConnectorStore(_root()).set_enabled(connector_id, True)}, as_json)


@connector_app.command("disable")
def disable_connector(connector_id: str, as_json: bool = typer.Option(False, "--json")):
    _emit({"connector_id": connector_id, "disabled": ConnectorStore(_root()).set_enabled(connector_id, False)}, as_json)


@connector_app.command("add")
def add_connector(manifest_path: Path, credential_ref: str = typer.Option("", "--credential-ref"), as_json: bool = typer.Option(False, "--json")):
    register_connector(manifest_path, credential_ref, as_json)

@connector_app.command("revoke")
def revoke_connector(connector_id: str, as_json: bool = typer.Option(False, "--json")):
    changed = ConnectorStore(_root()).revoke(connector_id)
    _emit({"connector_id": connector_id, "revoked": changed}, as_json)


def register_connector_commands(app: typer.Typer) -> None:
    app.add_typer(connector_app, name="connector")
    app.add_typer(connector_app, name="connectors", hidden=True)