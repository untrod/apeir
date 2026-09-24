"""Developer CLI for progressive tool discovery."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import typer

from nous_runtime.tools import ToolCatalog


tools_app = typer.Typer(
    help="Discover governed Runtime tools",
    invoke_without_command=True,
)


def _catalog(root: Path, *, allow_mutations: bool) -> ToolCatalog:
    from nous_runtime.chat.agent_tools import WorkspaceToolRuntime
    from nous_runtime.skills import SkillToolRuntime
    from nous_runtime.tools import ArtifactToolRuntime, GitToolRuntime

    catalog = ToolCatalog()
    catalog.register_runtime(
        WorkspaceToolRuntime(
            str(root.resolve()),
            allow_mutations=allow_mutations,
        )
    )
    catalog.register_runtime(GitToolRuntime(root), provider_id="git-sandbox")
    catalog.register_runtime(
        ArtifactToolRuntime(root, allow_mutations=allow_mutations),
        provider_id="artifact-runtime",
    )
    catalog.register_runtime(
        SkillToolRuntime(root, allow_mutations=allow_mutations),
        provider_id="skill-registry",
    )
    return catalog


def _print(value: Any, *, as_json: bool) -> None:
    if as_json:
        typer.echo(json.dumps(value, ensure_ascii=False, indent=2, default=str))
        return
    if isinstance(value, (tuple, list)):
        for item in value:
            if isinstance(item, dict) and "category" in item:
                typer.echo(
                    f"{item['category']}  {item.get('tool_count', 0)} tools  "
                    f"effects={','.join(item.get('effects') or ())}"
                )
            elif isinstance(item, dict):
                typer.echo(f"{item.get('tool_id', '')}  {item.get('description', '')}")
            else:
                typer.echo(str(item))
        return
    typer.echo(str(value))


@tools_app.callback()
def tools_root(
    ctx: typer.Context,
    root: Path = typer.Option(Path("."), "--root", help="Workspace root"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """List capability categories when no subcommand is provided."""
    if ctx.invoked_subcommand is None:
        _print(_catalog(root, allow_mutations=False).categories(), as_json=json_output)


@tools_app.command("list")
def list_tools(
    category: str = typer.Option("", "--category"),
    query: str = typer.Option("", "--query"),
    root: Path = typer.Option(Path("."), "--root", help="Workspace root"),
    include_effects: bool = typer.Option(False, "--include-effects"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """List compact tool summaries without loading schemas."""
    catalog = _catalog(root, allow_mutations=include_effects)
    _print(
        catalog.discover(category=category, query=query),
        as_json=json_output,
    )


@tools_app.command("expand")
def expand_tools(
    category: str,
    root: Path = typer.Option(Path("."), "--root", help="Workspace root"),
    include_effects: bool = typer.Option(False, "--include-effects"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Load full schemas for one capability category."""
    result = _catalog(root, allow_mutations=include_effects).expand(category)
    _print(result, as_json=json_output)
    if not result.get("ok"):
        raise typer.Exit(code=2)


@tools_app.command("info")
def tool_info(
    tool_id: str,
    root: Path = typer.Option(Path("."), "--root", help="Workspace root"),
    include_effects: bool = typer.Option(False, "--include-effects"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Show one normalized tool definition."""
    try:
        definition = _catalog(root, allow_mutations=include_effects).require(tool_id)
    except KeyError as exc:
        typer.echo(f"Unknown tool: {tool_id}", err=True)
        raise typer.Exit(code=2) from exc
    _print(definition.to_dict(), as_json=json_output)


def register_tool_commands(parent_app: typer.Typer) -> None:
    parent_app.add_typer(tools_app, name="tools")


__all__ = ["register_tool_commands", "tools_app"]
