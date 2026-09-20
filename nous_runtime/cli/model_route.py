"""CLI for task-aware model routing (preview)."""

from __future__ import annotations

import json

import typer

model_route_app = typer.Typer(help="Task-aware model routing (preview)")


@model_route_app.command("test")
def model_route_test(
    prompt: str = typer.Argument(..., help="Prompt to classify and route"),
    json_output: bool = typer.Option(False, "--json", help="JSON output"),
) -> None:
    """Classify a prompt and show which Provider the Runtime would select."""
    from nous_runtime.intelligence.routing import route_model

    route = route_model(prompt)
    if json_output:
        print(
            json.dumps(
                {
                    "task": route.task,
                    "selected": route.selected,
                    "reason": route.reason,
                    "alternatives": list(route.alternatives),
                },
                indent=2,
            )
        )
    else:
        typer.echo(f"Task      {route.task}")
        typer.echo(f"Selected  {route.selected or 'none'}")
        typer.echo(f"Reason    {route.reason}")
        if route.alternatives:
            typer.echo(f"Fallback  {', '.join(route.alternatives)}")
    if not route.selected:
        raise typer.Exit(code=1)
