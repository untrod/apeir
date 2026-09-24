"""CLI for Skill discovery, loading, and governed package installation."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import typer

from nous_runtime.skills import SkillRegistry


skill_app = typer.Typer(help="Discover and manage progressively loaded Skills")
catalog_app = typer.Typer(help="Manage Skill catalog sources")
skill_app.add_typer(catalog_app, name="catalog")


def _registry(root: Path) -> SkillRegistry:
    return SkillRegistry(root)


def _emit(value: Any, *, as_json: bool) -> None:
    if as_json:
        typer.echo(json.dumps(value, ensure_ascii=False, indent=2, default=str))
        return
    if isinstance(value, list):
        for item in value:
            typer.echo(
                f"{item.get('skill_id', '')}\t{item.get('version', '')}\t"
                f"{item.get('provider', '')}\t{item.get('description', '')}"
            )
        return
    typer.echo(str(value))


@skill_app.command("list")
def list_skills(
    root: Path = typer.Option(Path("."), "--root"),
    include_disabled: bool = typer.Option(False, "--include-disabled"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    _emit(
        [
            item.summary()
            for item in _registry(root).list(include_disabled=include_disabled)
        ],
        as_json=json_output,
    )


@skill_app.command("search")
def search_skills(
    query: str,
    root: Path = typer.Option(Path("."), "--root"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    _emit(
        [item.summary() for item in _registry(root).search(query)],
        as_json=json_output,
    )


@skill_app.command("info")
def skill_info(
    skill_id: str,
    root: Path = typer.Option(Path("."), "--root"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    try:
        value = _registry(root).load(skill_id).to_dict()
    except (KeyError, OSError, ValueError) as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(2) from exc
    _emit(value, as_json=json_output)


@skill_app.command("install")
def install_skill(
    source: Path,
    root: Path = typer.Option(Path("."), "--root"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Install a local Skill package; package scripts are never executed."""

    try:
        value = _registry(root).install(source).to_dict()
    except (OSError, ValueError) as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(2) from exc
    _emit(value, as_json=json_output)


@skill_app.command("update")
def update_skill(
    source: Path,
    root: Path = typer.Option(Path("."), "--root"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    try:
        value = _registry(root).update(source).to_dict()
    except (KeyError, OSError, ValueError) as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(2) from exc
    _emit(value, as_json=json_output)


@skill_app.command("remove")
def remove_skill(
    skill_id: str,
    root: Path = typer.Option(Path("."), "--root"),
) -> None:
    try:
        removed = _registry(root).remove(skill_id)
    except (KeyError, OSError, ValueError) as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(2) from exc
    typer.echo("removed" if removed else "not installed")


@skill_app.command("enable")
def enable_skill(
    skill_id: str,
    root: Path = typer.Option(Path("."), "--root"),
) -> None:
    try:
        value = _registry(root).enable(skill_id)
    except (KeyError, OSError, ValueError) as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(2) from exc
    typer.echo(f"enabled {value.skill_id}")


@skill_app.command("disable")
def disable_skill(
    skill_id: str,
    root: Path = typer.Option(Path("."), "--root"),
) -> None:
    try:
        value = _registry(root).disable(skill_id)
    except (KeyError, OSError, ValueError) as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(2) from exc
    typer.echo(f"disabled {value.skill_id}")


@catalog_app.command("list")
def list_catalogs(
    root: Path = typer.Option(Path("."), "--root"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    _emit(list(_registry(root).catalogs()), as_json=json_output)


@catalog_app.command("add")
def add_catalog(
    source: str,
    root: Path = typer.Option(Path("."), "--root"),
) -> None:
    try:
        _registry(root).add_catalog(source)
    except (OSError, ValueError) as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(2) from exc
    typer.echo(f"added {source}")


@catalog_app.command("remove")
def remove_catalog(
    source: str,
    root: Path = typer.Option(Path("."), "--root"),
) -> None:
    typer.echo(
        "removed" if _registry(root).remove_catalog(source) else "not configured"
    )


def register_skill_commands(parent_app: typer.Typer) -> None:
    parent_app.add_typer(skill_app, name="skill")


__all__ = ["register_skill_commands", "skill_app"]
