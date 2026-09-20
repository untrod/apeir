"""CLI commands for Intent Runtime."""

from __future__ import annotations

import json

import typer

from nous_runtime.interaction.classifier import IntentClassifier
from nous_runtime.interaction.explain import explain_intent
from nous_runtime.interaction.models import IntentRequest
from nous_runtime.interaction.resolver import resolve_intent
from nous_runtime.interaction.router import list_routes


intent_app = typer.Typer(help="Classify and explain user intent")


@intent_app.command("test")
def test_intent(
    text: str = typer.Argument(..., help="Input text to classify"),
    workspace: str = typer.Option("", help="Optional workspace hint"),
    as_json: bool = typer.Option(False, "--json", help="Emit JSON"),
):
    decision = resolve_intent(IntentClassifier().classify(IntentRequest(text, workspace_hint=workspace)))
    if as_json:
        typer.echo(json.dumps(decision.to_dict(), ensure_ascii=False, indent=2))
    else:
        typer.echo(explain_intent(decision))


@intent_app.command("explain")
def explain(
    text: str = typer.Argument(..., help="Input text to explain"),
    as_json: bool = typer.Option(False, "--json", help="Emit JSON"),
):
    decision = resolve_intent(IntentClassifier().classify(IntentRequest(text)))
    if as_json:
        typer.echo(json.dumps({"decision": decision.to_dict(), "explanation": explain_intent(decision)}, ensure_ascii=False, indent=2))
    else:
        typer.echo(explain_intent(decision))


@intent_app.command("routes")
def routes(as_json: bool = typer.Option(False, "--json", help="Emit JSON")):
    data = list_routes()
    if as_json:
        typer.echo(json.dumps(data, ensure_ascii=False, indent=2))
    else:
        for name, route in data.items():
            typer.echo(f"{name}: {route}")


def register_interaction_commands(app: typer.Typer, inspect_app: typer.Typer | None = None) -> None:
    app.add_typer(intent_app, name="intent")
