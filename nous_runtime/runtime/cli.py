"""CLI commands for the unified Runtime Pipeline."""

from __future__ import annotations

import json

import typer

from nous_runtime.runtime.orchestrator import RuntimeOrchestrator
from nous_runtime.runtime.request import RuntimeRequest
from nous_runtime.runtime.session import RuntimeSessionStore


runtime_app = typer.Typer(help="Run unified Runtime requests")
session_app = typer.Typer(help="Manage runtime sessions")


def _echo_json(data: object) -> None:
    typer.echo(json.dumps(data, ensure_ascii=False, indent=2))


@runtime_app.command("run")
def run(
    text: str = typer.Argument(..., help="Natural language request"),
    workspace: str = typer.Option("", help="Workspace id or name"),
    session: str = typer.Option("", help="Session id"),
    as_json: bool = typer.Option(False, "--json", help="Emit JSON"),
):
    response = RuntimeOrchestrator().run(RuntimeRequest(text, workspace=workspace, session=session))
    if as_json:
        _echo_json(response.to_dict())
    else:
        typer.echo(f"{response.status}: {response.message}")
        typer.echo(f"trace: {response.trace_id}")


@runtime_app.command("status")
def status(as_json: bool = typer.Option(False, "--json", help="Emit JSON")):
    try:
        from nous_runtime.api.routes import handle_status

        data = handle_status()
    except Exception as exc:
        data = {"ok": False, "error": str(exc)}
    if as_json:
        _echo_json(data)
        return
    payload = data.get("data", {}) if isinstance(data, dict) else {}
    typer.echo("Nous Runtime")
    typer.echo(f"Version: {payload.get('version', 'unknown')}")
    typer.echo(f"Status: {'Ready' if data.get('ok') else 'Degraded'}")
    typer.echo(f"Providers: {payload.get('providers', 0)}")
    typer.echo(f"Capabilities: {payload.get('capabilities', 0)}")
    typer.echo(f"Devices: {payload.get('devices', 0)}")


@runtime_app.command("audit")
def audit(
    root: str = typer.Option(
        "",
        "--root",
        help="Repository root; defaults to the current directory",
    ),
    strict: bool = typer.Option(
        False,
        "--strict",
        help="Exit non-zero when the release gate fails",
    ),
    as_json: bool = typer.Option(False, "--json", help="Emit JSON"),
):
    """Audit the unified model execution boundary and security gate."""
    from nous_runtime.runtime.audit import audit_runtime

    report = audit_runtime(root or ".")
    if as_json:
        _echo_json(report.to_dict())
    else:
        typer.echo("Runtime Audit")
        typer.echo(
            f"Gateway Calls: {report.gateway_percentage:.2f}% "
            f"({report.gateway_calls})"
        )
        typer.echo(f"Direct Provider: {report.direct_provider_calls}")
        typer.echo(f"Deprecated: {report.deprecated_calls}")
        typer.echo(
            "Security: "
            + ("PASS" if report.security_findings == 0 else "FAIL")
        )
        typer.echo(f"Result: {'PASS' if report.passed else 'FAIL'}")
        for finding in report.findings:
            typer.echo(
                f"- {finding.path}:{finding.line} "
                f"[{finding.category}] {finding.detail}"
            )
    if strict and not report.passed:
        raise typer.Exit(code=1)


@runtime_app.command("trace")
def trace(
    limit: int = typer.Option(10, "--limit", help="Maximum sessions to show"),
    as_json: bool = typer.Option(False, "--json", help="Emit JSON"),
):
    sessions = RuntimeSessionStore().list()[:limit]
    if as_json:
        _echo_json(sessions)
        return
    if not sessions:
        typer.echo("No runtime sessions recorded.")
        return
    for session in sessions:
        typer.echo(f"{session.get('session_id', '')}\t{len(session.get('events', []))} events")


@runtime_app.command("explain")
def explain(trace_id: str, as_json: bool = typer.Option(False, "--json", help="Emit JSON")):
    store = RuntimeSessionStore()
    for session in store.list():
        for event in session.get("events", []):
            if event.get("trace_id") == trace_id:
                data = {"trace_id": trace_id, "session_id": session.get("session_id", ""), "event": event}
                if as_json:
                    _echo_json(data)
                else:
                    typer.echo(f"trace: {trace_id}")
                    typer.echo(f"session: {data['session_id']}")
                    typer.echo(f"status: {event.get('response_status', 'unknown')}")
                return
    data = {"trace_id": trace_id, "found": False}
    if as_json:
        _echo_json(data)
    else:
        typer.echo(f"Trace not found: {trace_id}")


@session_app.command("list")
def list_sessions(as_json: bool = typer.Option(False, "--json", help="Emit JSON")):
    sessions = RuntimeSessionStore().list()
    if as_json:
        _echo_json(sessions)
    else:
        for session in sessions:
            typer.echo(f"{session.get('session_id', '')}\t{len(session.get('events', []))} events")


@session_app.command("resume")
def resume(session_id: str, as_json: bool = typer.Option(False, "--json", help="Emit JSON")):
    data = RuntimeSessionStore().explain(session_id)
    if as_json:
        _echo_json(data)
    else:
        typer.echo(f"{session_id}: {data['event_count']} events")


@session_app.command("explain")
def explain_session(session_id: str, as_json: bool = typer.Option(False, "--json", help="Emit JSON")):
    resume(session_id, as_json=as_json)


def register_runtime_commands(app: typer.Typer, inspect_app: typer.Typer | None = None) -> None:
    app.add_typer(runtime_app, name="runtime")
    app.add_typer(session_app, name="session")
