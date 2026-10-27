"""Workflow Runtime CLI."""

from __future__ import annotations

import json
from pathlib import Path

import typer

from nous_runtime.workflow import (
    WorkflowDefinition,
    WorkflowRuntime,
    WorkflowValidationError,
)

workflow_app = typer.Typer(help="Manage durable governed workflows")


def _runtime() -> WorkflowRuntime:
    return WorkflowRuntime(str(Path(".").resolve()))


def _emit(data, as_json: bool) -> None:
    if as_json:
        typer.echo(json.dumps(data, ensure_ascii=False, indent=2))
    elif isinstance(data, list):
        for item in data:
            typer.echo(f"{item.get('workflow_id', '')}\t{item.get('version', '')}")
    else:
        typer.echo(str(data))


def _definition(data: dict) -> WorkflowDefinition:
    from nous_runtime.workflow.models import definition_from_dict

    return definition_from_dict(data)


@workflow_app.command("validate")
def validate_workflow(path: Path, as_json: bool = typer.Option(False, "--json")):
    runtime = _runtime()
    definition = _definition(json.loads(path.read_text(encoding="utf-8")))
    try:
        runtime.compiler.validate(definition)
    except WorkflowValidationError as exc:
        raise typer.BadParameter(str(exc)) from None
    _emit(
        {
            "valid": True,
            "workflow_id": definition.workflow_id,
            "version": definition.version,
        },
        as_json,
    )


@workflow_app.command("register")
def register_workflow(path: Path, as_json: bool = typer.Option(False, "--json")):
    runtime = _runtime()
    definition = _definition(json.loads(path.read_text(encoding="utf-8")))
    try:
        runtime.register(definition)
    except WorkflowValidationError as exc:
        raise typer.BadParameter(str(exc)) from None
    _emit(
        {
            "registered": True,
            "workflow_id": definition.workflow_id,
            "version": definition.version,
        },
        as_json,
    )


@workflow_app.command("list")
def list_workflows(as_json: bool = typer.Option(False, "--json")):
    _emit(_runtime().store.list_definitions(), as_json)


@workflow_app.command("run")
def run_workflow(
    workflow_id: str,
    version: str = typer.Option("1.0.0", "--version"),
    inputs: str = typer.Option("{}", "--inputs"),
    idempotency_key: str = typer.Option("", "--idempotency-key"),
    as_json: bool = typer.Option(False, "--json"),
):
    try:
        run = _runtime().start(
            workflow_id, version, json.loads(inputs), idempotency_key=idempotency_key
        )
    except WorkflowValidationError as exc:
        raise typer.BadParameter(str(exc)) from None
    _emit(
        {
            "run_id": run.run_id,
            "state": run.state.value,
            "step_states": run.step_states,
            "outputs": run.outputs,
            "error": run.error,
        },
        as_json,
    )


@workflow_app.command("show")
def show_workflow_run(run_id: str, as_json: bool = typer.Option(False, "--json")):
    run = _runtime().store.get_run(run_id)
    if run is None:
        raise typer.BadParameter("workflow run not found")
    _emit(
        {
            "run_id": run.run_id,
            "workflow_id": run.workflow_id,
            "state": run.state.value,
            "step_states": run.step_states,
            "outputs": run.outputs,
            "error": run.error,
        },
        as_json,
    )


@workflow_app.command("cancel")
def cancel_workflow_run(run_id: str, as_json: bool = typer.Option(False, "--json")):
    run = _runtime().cancel(run_id)
    _emit({"run_id": run.run_id, "state": run.state.value}, as_json)


def register_workflow_commands(app: typer.Typer) -> None:
    app.add_typer(workflow_app, name="workflow")
