"""Local Plugin ecosystem CLI."""

from __future__ import annotations

import json
from pathlib import Path

import typer

from nous_runtime.plugins import PluginManager, PluginManifest, package_checksum

plugin_app = typer.Typer(help="Create and manage local Nous plugins")


def _manager() -> PluginManager:
    return PluginManager(Path(".").resolve())


def _emit(data, as_json: bool) -> None:
    if as_json:
        typer.echo(json.dumps(data, ensure_ascii=False, indent=2))
    elif isinstance(data, list):
        for item in data:
            typer.echo(f"{item.get('plugin_id', '')}\t{item.get('state', '')}")
    else:
        typer.echo(str(data))


@plugin_app.command("create")
def create_plugin(path: Path, plugin_id: str = typer.Option(..., "--id")):
    path.mkdir(parents=True, exist_ok=False)
    (path / "plugin_impl.py").write_text("def invoke(capability, payload):\n    return {'capability': capability, 'result': payload}\n", encoding="utf-8")
    manifest = PluginManifest(plugin_id, "0.1.0", "0.1", "plugin_impl:invoke", (f"{plugin_id}.invoke",))
    manifest = PluginManifest.from_dict({**manifest.to_dict(), "package_checksum": package_checksum(path, manifest)})
    (path / "plugin.json").write_text(json.dumps(manifest.to_dict(), indent=2) + "\n", encoding="utf-8")
    typer.echo(str(path.resolve()))


@plugin_app.command("validate")
def validate_plugin(path: Path, as_json: bool = typer.Option(False, "--json")):
    manifest, errors = _manager().validate(path)
    _emit({"plugin_id": manifest.plugin_id, "valid": not errors, "errors": errors}, as_json)
    if errors:
        raise typer.Exit(1)


@plugin_app.command("list")
def list_plugins(as_json: bool = typer.Option(False, "--json")):
    _emit(_manager().registry.list(), as_json)


@plugin_app.command("inspect")
def inspect_plugin(plugin_id: str, as_json: bool = typer.Option(False, "--json")):
    record = _manager().registry.get(plugin_id)
    if record is None:
        raise typer.BadParameter("plugin is not installed")
    _emit({"plugin_id": plugin_id, "manifest": record["manifest"].to_dict(), "state": record["state"], "last_error": record["last_error"]}, as_json)


@plugin_app.command("install")
def install_plugin(path: Path, approve_permissions: bool = typer.Option(False, "--approve-permissions"), as_json: bool = typer.Option(False, "--json")):
    manifest = _manager().install(path, approve_permissions=(lambda permissions: approve_permissions))
    _emit({"plugin_id": manifest.plugin_id, "installed": True, "state": "disabled"}, as_json)


@plugin_app.command("enable")
def enable_plugin(plugin_id: str):
    _manager().enable(plugin_id)
    typer.echo(f"enabled: {plugin_id}")


@plugin_app.command("disable")
def disable_plugin(plugin_id: str):
    _manager().disable(plugin_id)
    typer.echo(f"disabled: {plugin_id}")


@plugin_app.command("uninstall")
def uninstall_plugin(plugin_id: str):
    _manager().uninstall(plugin_id)
    typer.echo(f"uninstalled: {plugin_id}")


def register_plugin_commands(app: typer.Typer) -> None:
    app.add_typer(plugin_app, name="plugin")