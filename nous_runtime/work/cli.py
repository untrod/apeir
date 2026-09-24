"""CLI entry points for durable Work runs."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import typer

from nous_runtime.work.runtime import WorkHarness


work_app = typer.Typer(help="Run and inspect durable APEIR Work", no_args_is_help=True)


def _echo(value: Any, *, as_json: bool) -> None:
    if as_json:
        typer.echo(json.dumps(value, ensure_ascii=False, indent=2, default=str))
        return
    if isinstance(value, dict) and "run_id" in value:
        typer.echo(f"Work: {value['run_id']}")
        typer.echo(f"State: {value.get('state', '')}")
        goal = value.get("goal") or {}
        typer.echo(f"Goal: {goal.get('objective', '')}")
        plan = value.get("plan") or {}
        if plan:
            progress = plan.get("progress") or {}
            typer.echo(
                "Plan: "
                f"v{plan.get('revision', 1)} "
                f"{progress.get('done', 0)}/{progress.get('total', 0)} complete"
            )
        if value.get("error"):
            typer.echo(f"Error: {value['error']}")
        return
    typer.echo(str(value))


def _runtime_components(root: Path, snapshot):
    from nous_runtime.work.components import build_work_components

    components = build_work_components(root, snapshot)
    return components.tools, components.deliberator


@work_app.command("run")
def run_work(
    objective: str = typer.Argument(..., help="Outcome to accomplish"),
    root: Path = typer.Option(Path("."), "--root", help="Workspace root"),
    model: str = typer.Option("", "--model", help="Preferred model ID"),
    read_only: bool = typer.Option(False, "--read-only"),
    max_iterations: int = typer.Option(32, "--max-iterations", min=1, max=1000),
    model_timeout_s: float = typer.Option(
        180.0, "--model-timeout", min=1.0, max=3600.0
    ),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Create and execute one durable Work run."""
    from nous_runtime.work.deliberation import verify_recorded_work

    harness = WorkHarness(root)
    snapshot = harness.create(
        objective,
        execution_options={
            "preferred_model": model,
            "read_only": read_only,
            "max_iterations": max_iterations,
            "model_timeout_s": model_timeout_s,
        },
    )
    try:
        tools, deliberator = _runtime_components(root, snapshot)
        snapshot = harness.run(
            snapshot.run_id,
            deliberator=deliberator,
            tools=tools,
            verifier=verify_recorded_work,
            max_iterations=max_iterations,
        )
    except Exception as exc:
        snapshot = harness.fail(snapshot.run_id, reason=str(exc))
        _echo(snapshot.to_dict(), as_json=json_output)
        raise typer.Exit(code=2) from exc
    _echo(snapshot.to_dict(), as_json=json_output)


@work_app.command("list")
def list_work(
    root: Path = typer.Option(Path("."), "--root", help="Workspace root"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """List the latest projection for each Work run."""
    items = [item.to_dict() for item in WorkHarness(root).list()]
    if json_output:
        _echo(items, as_json=True)
        return
    if not items:
        typer.echo("No Work runs.")
        return
    for item in items:
        typer.echo(
            f"{item['run_id']}  {item['state']}  "
            f"{(item.get('goal') or {}).get('objective', '')}"
        )


@work_app.command("inspect")
def inspect_work(
    run_id: str,
    root: Path = typer.Option(Path("."), "--root", help="Workspace root"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Show durable Work state and its progress events."""
    report = WorkHarness(root).inspect(run_id)
    if json_output:
        _echo(report, as_json=True)
        return
    _echo(report["work"], as_json=False)
    typer.echo(f"Events: {len(report['events'])}")


@work_app.command("resume")
def resume_work(
    run_id: str,
    root: Path = typer.Option(Path("."), "--root", help="Workspace root"),
    model: str = typer.Option("", "--model", help="Preferred model ID"),
    read_only: bool = typer.Option(False, "--read-only"),
    max_iterations: int = typer.Option(32, "--max-iterations", min=1, max=1000),
    model_timeout_s: float = typer.Option(
        180.0, "--model-timeout", min=1.0, max=3600.0
    ),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Restore a Work checkpoint and reassess before any new action."""
    from nous_runtime.work.deliberation import verify_recorded_work

    harness = WorkHarness(root)
    snapshot = harness.require(run_id)
    snapshot.execution_options.update(
        {
            "preferred_model": model
            or str(snapshot.execution_options.get("preferred_model") or ""),
            "read_only": read_only
            or bool(snapshot.execution_options.get("read_only", False)),
            "max_iterations": max_iterations,
            "model_timeout_s": model_timeout_s,
        }
    )
    harness.persist_progress(
        snapshot,
        "work.execution.configured",
        {"source": "cli.resume"},
    )
    tools, deliberator = _runtime_components(root, snapshot)
    snapshot = harness.resume(
        run_id,
        deliberator=deliberator,
        tools=tools,
        verifier=verify_recorded_work,
        max_iterations=max_iterations,
    )
    _echo(snapshot.to_dict(), as_json=json_output)


@work_app.command("pause")
def pause_work(
    run_id: str,
    reason: str = typer.Option("", "--reason"),
    root: Path = typer.Option(Path("."), "--root", help="Workspace root"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Request a durable pause at the next Work loop boundary."""
    snapshot = WorkHarness(root).pause(run_id, reason=reason)
    _echo(snapshot.to_dict(), as_json=json_output)


@work_app.command("cancel")
def cancel_work(
    run_id: str,
    reason: str = typer.Option("", "--reason"),
    root: Path = typer.Option(Path("."), "--root", help="Workspace root"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Cancel a non-terminal Work run."""
    snapshot = WorkHarness(root).cancel(run_id, reason=reason)
    _echo(snapshot.to_dict(), as_json=json_output)


@work_app.command("steer")
def steer_work(
    run_id: str,
    instruction: str = typer.Argument(...),
    root: Path = typer.Option(Path("."), "--root", help="Workspace root"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Update the active Goal and force plan reassessment in the same run."""
    snapshot = WorkHarness(root).steer(run_id, instruction)
    _echo(snapshot.to_dict(), as_json=json_output)


def register_work_commands(parent_app: typer.Typer) -> None:
    parent_app.add_typer(work_app, name="work")


__all__ = ["register_work_commands", "work_app"]
