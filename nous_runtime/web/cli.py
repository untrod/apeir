"""CLI for governed Web search and fetch."""

from __future__ import annotations

import json
from pathlib import Path

import typer

from nous_runtime.web import WebRuntime


web_app = typer.Typer(help="Search and fetch Web evidence through Network Gateway")


def _emit(result: dict) -> None:
    typer.echo(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    if not result.get("ok"):
        raise typer.Exit(2)


@web_app.command("search")
def search_web(
    query: str,
    root: Path = typer.Option(Path("."), "--root"),
    max_results: int = typer.Option(10, "--max-results", min=1, max=20),
) -> None:
    _emit(WebRuntime(root).search({"query": query, "max_results": max_results}))


@web_app.command("fetch")
def fetch_web(
    url: str,
    root: Path = typer.Option(Path("."), "--root"),
) -> None:
    _emit(WebRuntime(root).fetch({"url": url}))


def register_web_commands(parent_app: typer.Typer) -> None:
    parent_app.add_typer(web_app, name="web")


__all__ = ["register_web_commands", "web_app"]
