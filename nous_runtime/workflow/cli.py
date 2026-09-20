"""Workflow Runtime CLI."""

from __future__ import annotations

import json
from pathlib import Path

import typer

from nous_runtime.workflow import StepType, TriggerType, WorkflowDefinition, WorkflowRuntime, WorkflowStep

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
    steps = tuple(WorkflowStep(str(item["step_id"]), StepType(str(item["step_type"])), str(item.get("action") or ""), tuple(item.get("depends_on") or ()), str(item.get("condition") or ""), int(item.get("retries") or 0), float(item.get("timeout_seconds") or 60), bool(item.get("approval_required", False)), str(item.get("compensation") or ""), dict(item.get("params") or {})) for item in data.get("steps") or ())
    return WorkflowDefinition(str(data["workflow_id"]), str(data["version"]), TriggerType(str(data.get("trigger") or "manual")), steps, dict(data.get("inputs_schema") or {}), dict(data.get("outputs_schema") or {}), dict(data.get("audit_metadata") or {}))


@workflow_app.command("validate")
def validate_workflow(path: Path, as_json: bool = typer.Option(False, "--json")):
    runtime = _runtime()
    definition = _definition(json.loads(path.read_text(encoding="utf-8")))
    runtime.compiler.validate(definition)
    _emit({"valid": True, "workflow_id": definition.workflow_id, "version": definition.version}, as_json)


@workflow_app.command("register")
def register_workflow(path: Path, as_json: bool = typer.Option(False, "--json")):
    runtime = _runtime()
    definition = _definition(json.loads(path.read_text(encoding="utf-8")))
    runtime.register(definition)
    _emit({"registered": True, "workflow_id": definition.workflow_id, "version": definition.version}, as_json)


@workflow_app.command("list")
def list_workflows(as_json: bool = typer.Option(False, "--json")):
    _emit(_runtime().store.list_definitions(), as_json)


@workflow_app.command("run")
def run_workflow(workflow_id: str, version: str = typer.Option("1.0.0", "--version"), inputs: str = typer.Option("{}", "--inputs"), idempotency_key: str = typer.Option("", "--idempotency-key"), as_json: bool = typer.Option(False, "--json")):
    run = _runtime().start(workflow_id, version, json.loads(inputs), idempotency_key=idempotency_key)
    _emit({"run_id": run.run_id, "state": run.state.value, "step_states": run.step_states, "outputs": run.outputs, "error": run.error}, as_json)


@workflow_app.command("show")
def show_workflow_run(run_id: str, as_json: bool = typer.Option(False, "--json")):
    run = _runtime().store.get_run(run_id)
    if run is None:
        raise typer.BadParameter("workflow run not found")
    _emit({"run_id": run.run_id, "workflow_id": run.workflow_id, "state": run.state.value, "step_states": run.step_states, "outputs": run.outputs, "error": run.error}, as_json)


@workflow_app.command("cancel")
def cancel_workflow_run(run_id: str, as_json: bool = typer.Option(False, "--json")):
    run = _runtime().cancel(run_id)
    _emit({"run_id": run.run_id, "state": run.state.value}, as_json)


def register_workflow_commands(app: typer.Typer) -> None:
    app.add_typer(workflow_app, name="workflow")