"""Knowledge Library CLI."""

from __future__ import annotations

import json
from pathlib import Path

import typer

from nous_runtime.knowledge import KnowledgeLibraryService

library_app = typer.Typer(help="Manage user-owned knowledge libraries")


def _service() -> KnowledgeLibraryService:
    return KnowledgeLibraryService(Path(".").resolve())


def _emit(data, as_json: bool) -> None:
    if as_json:
        typer.echo(json.dumps(data, ensure_ascii=False, indent=2))
    elif isinstance(data, list):
        for item in data:
            typer.echo(str(item))
    else:
        typer.echo(str(data))


@library_app.command("create")
def create_library(name: str, workspace_id: str = typer.Option("default", "--workspace"), owner_id: str = typer.Option("local", "--owner"), as_json: bool = typer.Option(False, "--json")):
    library = _service().create(workspace_id, owner_id, name)
    _emit(dict(library.__dict__), as_json)


@library_app.command("list")
def list_libraries(workspace_id: str = typer.Option("default", "--workspace"), owner_id: str = typer.Option("local", "--owner"), as_json: bool = typer.Option(False, "--json")):
    items = [dict(item.__dict__) for item in _service().store.list_libraries(workspace_id=workspace_id, owner_id=owner_id)]
    _emit(items, as_json)


@library_app.command("import")
def import_document(library_id: str, path: Path, workspace_id: str = typer.Option("default", "--workspace"), owner_id: str = typer.Option("local", "--owner"), logical_source: str = typer.Option("", "--source"), as_json: bool = typer.Option(False, "--json")):
    _emit(_service().import_file(library_id, path, workspace_id=workspace_id, owner_id=owner_id, logical_source=logical_source), as_json)


@library_app.command("search")
def search_library(library_id: str, query: str, workspace_id: str = typer.Option("default", "--workspace"), owner_id: str = typer.Option("local", "--owner"), limit: int = typer.Option(10, "--limit"), as_json: bool = typer.Option(False, "--json")):
    results = [item.to_dict() for item in _service().search(library_id, query, workspace_id=workspace_id, owner_id=owner_id, limit=limit)]
    if as_json:
        _emit(results, True)
    else:
        for item in results:
            typer.echo(f"{item['relevance']:.3f}\t{item['logical_source']}\t{item['citation_snippet']}")


@library_app.command("rebuild")
def rebuild_library(library_id: str, workspace_id: str = typer.Option("default", "--workspace"), owner_id: str = typer.Option("local", "--owner"), as_json: bool = typer.Option(False, "--json")):
    generation = _service().rebuild(library_id, workspace_id=workspace_id, owner_id=owner_id)
    _emit({"library_id": library_id, "generation": generation}, as_json)


@library_app.command("export")
def export_library(library_id: str, output: Path, workspace_id: str = typer.Option("default", "--workspace"), owner_id: str = typer.Option("local", "--owner")):
    data = _service().export(library_id, workspace_id=workspace_id, owner_id=owner_id)
    output.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    typer.echo(str(output.resolve()))


@library_app.command("delete-document")
def delete_document(library_id: str, logical_source: str, workspace_id: str = typer.Option("default", "--workspace"), owner_id: str = typer.Option("local", "--owner"), as_json: bool = typer.Option(False, "--json")):
    changed = _service().delete_document(library_id, logical_source, workspace_id=workspace_id, owner_id=owner_id)
    _emit({"deleted": changed, "logical_source": logical_source}, as_json)


def register_library_commands(app: typer.Typer) -> None:
    app.add_typer(library_app, name="library")