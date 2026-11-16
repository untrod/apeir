"""Operator-started Automation consumption over existing Runtime owners."""

import json
import os
from pathlib import Path
import time

import typer

from nous_runtime.governance.cli import _build_context
from nous_runtime.workflow.automation import AutomationConsumer

automation_app = typer.Typer(
    help="Manage pure Workflows and explicitly simulated governed Automations"
)


def register_automation_commands(app: typer.Typer) -> None:
    app.add_typer(automation_app, name="automation")


def _consumer(
    *, simulation: bool, workflow: bool = False, automation_id=""
) -> AutomationConsumer:
    if not simulation and not workflow:
        raise typer.BadParameter(
            "This qualified template requires explicit --simulation; it exercises no physical hardware"
        )
    service = AutomationConsumer(os.environ.get("NOUS_WORKSPACE_ROOT") or Path.cwd())
    if (
        automation_id
        and not simulation
        and service.store.get_automation(automation_id)["adapter"] != "workflow"
    ):
        raise typer.BadParameter(
            "A simulated Automation requires explicit --simulation"
        )
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
    cron: str = typer.Option("", "--cron"),
):
    """Register a reviewable observe/update/verify Workflow; no grant is issued."""
    _emit(
        _consumer(simulation=simulation).add_simulation(
            name=name,
            trigger="cron" if cron else "schedule" if due_at else "manual",
            due_at=due_at,
            firmware_version=firmware_version,
            cron=cron,
        )
    )


@automation_app.command("list")
def list_automations(
    simulation: bool = typer.Option(False, "--simulation"),
    workflow: bool = typer.Option(False, "--workflow"),
):
    _emit(_consumer(simulation=simulation, workflow=workflow).list())


@automation_app.command("trigger")
def trigger(
    automation_id: str,
    trigger_key: str = typer.Option(..., "--trigger-key"),
    simulation: bool = typer.Option(False, "--simulation"),
    workflow: bool = typer.Option(False, "--workflow"),
):
    _emit(
        _consumer(
            simulation=simulation, workflow=workflow, automation_id=automation_id
        ).trigger(automation_id, trigger_key)
    )


@automation_app.command("run-due")
def run_due(
    limit: int = typer.Option(10, "--limit"),
    simulation: bool = typer.Option(False, "--simulation"),
    workflow: bool = typer.Option(False, "--workflow"),
):
    """Consume bounded one-shot/Cron proposals; never approve their effects."""
    _emit(
        _consumer(simulation=simulation, workflow=workflow).run_due(
            limit=limit, include_simulation=simulation
        )
    )


@automation_app.command("resume")
def resume(
    automation_id: str,
    run_id: str,
    simulation: bool = typer.Option(False, "--simulation"),
    workflow: bool = typer.Option(False, "--workflow"),
):
    """Resume/reconcile the original run after separate trusted human approval."""
    _emit(
        _consumer(
            simulation=simulation, workflow=workflow, automation_id=automation_id
        ).resume(automation_id, run_id)
    )


@automation_app.command("cancel")
def cancel(
    automation_id: str,
    run_id: str,
    simulation: bool = typer.Option(False, "--simulation"),
    workflow: bool = typer.Option(False, "--workflow"),
):
    """Fence later Workflow admission; an existing effect still needs evidence."""
    _emit(
        _consumer(
            simulation=simulation, workflow=workflow, automation_id=automation_id
        ).cancel(automation_id, run_id)
    )


@automation_app.command("reconcile")
def reconcile(
    automation_id: str,
    run_id: str,
    simulation: bool = typer.Option(False, "--simulation"),
    workflow: bool = typer.Option(False, "--workflow"),
):
    """Acquire original receipt/effect evidence without re-entering mutation."""
    _emit(
        _consumer(
            simulation=simulation, workflow=workflow, automation_id=automation_id
        ).reconcile(automation_id, run_id)
    )


@automation_app.command("history")
def history(
    automation_id: str,
    simulation: bool = typer.Option(False, "--simulation"),
    workflow: bool = typer.Option(False, "--workflow"),
):
    _emit(
        _consumer(
            simulation=simulation, workflow=workflow, automation_id=automation_id
        ).history(automation_id)
    )


@automation_app.command("bind-workflow")
def bind_workflow(
    name: str,
    workflow_id: str,
    version: str,
    inputs_file: Path | None = typer.Option(None, "--inputs"),
    cron: str = typer.Option("", "--cron"),
    due_at: str = typer.Option("", "--due-at"),
):
    """Schedule an already registered pure Workflow; no model/device permissions."""
    if inputs_file and inputs_file.stat().st_size > 96 * 1024:
        raise typer.BadParameter("Workflow inputs exceed 96 KiB")
    inputs = json.loads(inputs_file.read_text(encoding="utf-8")) if inputs_file else {}
    _emit(
        _consumer(simulation=False, workflow=True).add_workflow(
            name=name,
            workflow_id=workflow_id,
            version=version,
            inputs=inputs,
            trigger="cron" if cron else "schedule" if due_at else "manual",
            due_at=due_at,
            cron=cron,
        )
    )


@automation_app.command("set-enabled")
def set_enabled(
    automation_id: str,
    enabled: bool,
    simulation: bool = typer.Option(False, "--simulation"),
    workflow: bool = typer.Option(False, "--workflow"),
):
    """Control future triggers; existing runs are not cancelled by disabling."""
    service = _consumer(
        simulation=simulation, workflow=workflow, automation_id=automation_id
    )
    _emit(
        service.store.set_automation_enabled(
            automation_id, enabled, before_publish=service.before_consume
        )
    )


@automation_app.command("watch")
def watch(
    simulation: bool = typer.Option(False, "--simulation"),
    workflow: bool = typer.Option(False, "--workflow"),
    interval: float = typer.Option(5, "--interval", min=1, max=60),
    ticks: int = typer.Option(0, "--ticks", min=0, max=1000000),
    limit: int = typer.Option(10, "--limit", min=1, max=10),
):
    """Run the explicit local timer. Stopping it does not cancel original Work.

    Zero ticks means keep running. Each tick rechecks the current local operator
    and permissions; schedules persist in WorkflowStore, never a saved session.
    """
    count = 0
    try:
        while True:
            service = _consumer(simulation=simulation, workflow=workflow)
            _emit(
                {
                    "event": "automation.tick",
                    "runs": service.run_due(limit=limit, include_simulation=simulation),
                }
            )
            count += 1
            if ticks and count >= ticks:
                break
            time.sleep(interval)
    except KeyboardInterrupt:
        _emit({"event": "automation.timer_stopped", "work_cancelled": False})
