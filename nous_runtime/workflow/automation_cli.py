"""Explicit simulated Automation consumption over existing Runtime owners."""

import json
import os
from pathlib import Path

import typer

from nous_runtime.governance.cli import _build_context
from nous_runtime.workflow.automation import AutomationConsumer

automation_app = typer.Typer(
    help="Consume governed Automation triggers (explicit simulation only)"
)


def register_automation_commands(app: typer.Typer) -> None:
    app.add_typer(automation_app, name="automation")


def _consumer(*, simulation: bool) -> AutomationConsumer:
    if not simulation:
        raise typer.BadParameter(
            "This qualified template requires explicit --simulation; it exercises no physical hardware"
        )
    service = AutomationConsumer(os.environ.get("NOUS_WORKSPACE_ROOT") or Path.cwd())
    context = _build_context()
    service.admit_management(context)
    service.before_consume = lambda: service.admit_management(context, audit=False)
    return service


def _emit(value):
    typer.echo(json.dumps(value, ensure_ascii=False, indent=2))


@automation_app.command("add")
def add(
    name: str,
    simulation: bool = typer.Option(False, "--simulation"),
    due_at: str = typer.Option("", "--due-at"),
    firmware_version: str = typer.Option("2.0.0", "--firmware-version"),
):
    """Register a reviewable observe/update/verify Workflow; no grant is issued."""
    _emit(
        _consumer(simulation=simulation).add_simulation(
            name=name,
            trigger="schedule" if due_at else "manual",
            due_at=due_at,
            firmware_version=firmware_version,
        )
    )


@automation_app.command("list")
def list_automations(simulation: bool = typer.Option(False, "--simulation")):
    _emit(_consumer(simulation=simulation).list())


@automation_app.command("trigger")
def trigger(
    automation_id: str,
    trigger_key: str = typer.Option(..., "--trigger-key"),
    simulation: bool = typer.Option(False, "--simulation"),
):
    _emit(_consumer(simulation=simulation).trigger(automation_id, trigger_key))


@automation_app.command("run-due")
def run_due(
    limit: int = typer.Option(10, "--limit"),
    simulation: bool = typer.Option(False, "--simulation"),
):
    """Consume at most ten one-shot due proposals; there is no background timer."""
    _emit(_consumer(simulation=simulation).run_due(limit=limit))


@automation_app.command("resume")
def resume(
    automation_id: str,
    run_id: str,
    simulation: bool = typer.Option(False, "--simulation"),
):
    """Resume/reconcile the original run after separate trusted human approval."""
    _emit(_consumer(simulation=simulation).resume(automation_id, run_id))


@automation_app.command("cancel")
def cancel(
    automation_id: str,
    run_id: str,
    simulation: bool = typer.Option(False, "--simulation"),
):
    """Fence later Workflow admission; an existing effect still needs evidence."""
    _emit(_consumer(simulation=simulation).cancel(automation_id, run_id))


@automation_app.command("reconcile")
def reconcile(
    automation_id: str,
    run_id: str,
    simulation: bool = typer.Option(False, "--simulation"),
):
    """Acquire original receipt/effect evidence without re-entering mutation."""
    _emit(_consumer(simulation=simulation).reconcile(automation_id, run_id))


@automation_app.command("history")
def history(automation_id: str, simulation: bool = typer.Option(False, "--simulation")):
    _emit(_consumer(simulation=simulation).history(automation_id))
