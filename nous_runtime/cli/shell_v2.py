# -*- coding: utf-8 -*-
"""
Nous Interactive Shell v2 -professional terminal experience.

Features:
  - Rich status bar with live runtime health
  - Natural language ->Goal ->Plan ->Execute routing
  - Streaming output with progress spinner
  - Execution timeline visualization
  - Slash commands with auto-complete hints
  - Error explanation with suggested fixes

Usage:
    nous          # Enter interactive shell
"""

from __future__ import annotations

import json
import os
import sys
import threading
import uuid
from pathlib import Path
from typing import Any, Callable

from nous_runtime.cli.execution_ui import (
    render_approval_panel,
    render_run_view,
    render_runs_queue,
)
from nous_runtime.cli.stream import StreamWriter
from nous_runtime.cli.terminal_session import TerminalSession, fold_output, stream_chunks
from nous_runtime.cli.terminal_ui import ActivityItem, CompletionItem
from nous_runtime.version import __version__ as _V


# Shell State

class ShellState:
    def __init__(self):
        self.running = True
        self.history: list[str] = []
        self.last_result: Any = None
        self.json_output = False
        self.quiet = False
        self.session: TerminalSession | None = None
        self.active_run_id = ""
        self.activity_callback: Callable[[str, str, str], None] | None = None
        self.provider_label = "Not configured"
        self.model_label = "Not configured"
        self.connection_label = "offline"
        self.last_activities: tuple[ActivityItem, ...] = ()
        self.approval_mode = "strict"
        self.dismissed_approvals: set[str] = set()
        self.input_prefill = ""


_state = ShellState()
_out = StreamWriter(prefix="")


def _open_terminal_session(session_id: str = "") -> TerminalSession:
    from nous_runtime.project.workspace import find_workspace

    workspace = find_workspace()
    root = workspace.parent if workspace else Path.cwd()
    workspace_id = str(root.resolve())
    owner_id = os.environ.get("NOUS_SUBJECT_ID", "local")
    session = TerminalSession(
        root,
        workspace_id=workspace_id,
        owner_id=owner_id,
        conversation_id=session_id,
    )
    _state.session = session
    return session


def _session() -> TerminalSession:
    return _state.session or _open_terminal_session()


# Banner

def _banner() -> str:
    """Render the startup identity with current presentation metadata."""
    try:
        from nous_runtime.cli.terminal_ui import render_banner
        from nous_runtime.project.workspace import find_workspace

        workspace = find_workspace()
        root = workspace.parent if workspace else Path.cwd()
        status: dict[str, Any] = {
            "_workspace_path": str(workspace) if workspace else "",
            "path": str(root.resolve()),
            "runtime_status": "Ready",
            "session": "Active",
            "provider": _state.provider_label,
            "model": _state.model_label,
        }
        try:
            from nous_runtime.runtime.no_intelligence import no_intelligence_enabled

            if no_intelligence_enabled():
                from nous_runtime.runtime.bootstrap import NousRuntime

                runtime = NousRuntime.current(required=False)
                status["runtime_status"] = (
                    "Online" if runtime is not None and runtime.snapshot().ready else "Limited"
                )
            else:
                from nous_runtime.runtime.lifecycle import Runtime

                runtime_status = Runtime().status()
                status["runtime_status"] = (
                    "Online" if runtime_status.running else "Offline"
                )
        except Exception:
            status["runtime_status"] = "Limited"

        if _state.session is not None:
            page = _state.session.history_page(page_size=1)
            status["session"] = "Resumed" if page["messages"] else "Active"
            if _state.session.recovered_operations:
                status["session"] = (
                    f"Recovered · {_state.session.recovered_operations} interrupted"
                )

        return render_banner(str(workspace) if workspace else None, status)
    except Exception:
        return f"NOUS\n\nRuntime  Limited\nVersion  {_V}"


# Command Registry

COMMANDS: dict[str, dict] = {}

_COMMAND_LAYOUT: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Runtime", ("status", "dashboard", "inspect", "provider")),
    ("Execution", ("run", "runs", "tasks", "approval", "approve", "pause", "resume", "cancel")),
    ("Context", ("context", "files", "tests")),
    ("Session", ("clear", "help", "quit")),
)
_COMMAND_DESCRIPTIONS = {
    "status": "Runtime status",
    "dashboard": "Runtime dashboard",
    "inspect": "Inspect a subsystem",
    "provider": "Provider configuration and health",
    "run": "Show an execution",
    "runs": "Recent executions",
    "tasks": "Task and execution queue",
    "approval": "Approval panel and policy mode",
    "approve": "Compatibility approval command",
    "pause": "Pause an execution",
    "resume": "Resume an execution",
    "cancel": "Cancel an operation or run",
    "context": "Current conversation context",
    "files": "Indexed workspace files",
    "tests": "Recent test activity",
    "clear": "Clear the visible terminal",
    "help": "Command reference",
    "quit": "Close this terminal session",
}
_COMMAND_ORDER = tuple(
    command for _, commands in _COMMAND_LAYOUT for command in commands
)
_COMMAND_LAUNCH = (
    "run", "runs", "tasks", "approval", "dashboard", "status",
    "inspect", "provider", "context", "help"
)
_COMMAND_GROUP = {
    command: group for group, commands in _COMMAND_LAYOUT for command in commands
}

def cmd(name: str, help_text: str, aliases: list[str] | None = None):
    def decorator(fn):
        COMMANDS[name] = {"fn": fn, "help": help_text, "aliases": aliases or []}
        for a in (aliases or []):
            COMMANDS[a] = {"fn": fn, "help": f"Alias for /{name}"}
        return fn
    return decorator


@cmd("help", "Show help", aliases=["h", "?"])
def _help(args: list[str]) -> str:
    lines = ["NOUS commands"]
    for group, commands in _COMMAND_LAYOUT:
        lines.extend(("", group))
        for name in commands:
            lines.append(f"  /{name:<13}{_COMMAND_DESCRIPTIONS[name]}")
    lines.extend(("", "Type natural language to work through the governed Runtime."))
    return "\n".join(lines)


@cmd("status", "Runtime health and stats", aliases=["st"])
def _status(args: list[str]) -> str:
    try:
        from nous_runtime.runtime.lifecycle import Runtime
        from nous_runtime.learning.experience import count as exp_count
        from nous_runtime.services.packs import count_packs

        snapshot = Runtime().status()
        return "\n".join(
            (
                "NOUS Runtime",
                "",
                f"  {'status':<14}{'online' if snapshot.running else 'offline'}",
                f"  {'version':<14}{snapshot.version}",
                f"  {'uptime':<14}{snapshot.uptime_seconds:.0f}s",
                "",
                "Execution",
                f"  {'events':<14}{snapshot.events_total}",
                f"  {'queued':<14}{snapshot.jobs_pending}",
                "",
                "Capabilities",
                f"  {'available':<14}{snapshot.capabilities}",
                f"  {'providers':<14}{snapshot.providers}",
                f"  {'packs':<14}{count_packs()}",
                f"  {'experience':<14}{exp_count()}",
            )
        )
    except Exception as exc:
        return f"Status unavailable: {exc}"


@cmd("dashboard", "Runtime dashboard", aliases=["dash"])
def _dashboard(args: list[str]) -> str:
    try:
        from nous_runtime.cli.terminal_ui import render_runtime_dashboard
        from nous_runtime.control_center.snapshot import control_center_snapshot

        section = args[0].lower() if args else ""
        return render_runtime_dashboard(control_center_snapshot(), section)
    except Exception as exc:
        return f"Dashboard unavailable: {exc}"


def _event_stream():
    from nous_runtime.events import EventStream

    return EventStream(str(_session().root))


def _page_arg(args: list[str], default: int = 1) -> int:
    try:
        return max(1, int(args[0])) if args else default
    except ValueError:
        return default


@cmd("runs", "List Runtime runs by page")
def _runs(args: list[str]) -> str:
    page = _page_arg(args)
    rows = _event_stream().list_runs(limit=20, offset=(page - 1) * 20)
    try:
        from nous_runtime.governance.broker import get_broker

        pending = get_broker().get_pending()
    except Exception:
        pending = []
    if rows and not _state.active_run_id:
        _state.active_run_id = rows[0].run_id
    return render_runs_queue(
        rows,
        pending,
        focused_run_id=_state.active_run_id,
    )


@cmd("run", "Show or focus a run")
def _run(args: list[str]) -> str:
    if len(args) >= 2 and args[0].lower() == "focus":
        run_id = args[1]
        record = _event_stream().get_run(run_id)
        if record is None:
            return f"Run not found: {run_id}"
        _state.active_run_id = run_id
        return f"Focused Run {run_id}: {record.state.value}"
    if len(args) < 2 or args[0].lower() != "show":
        return "Usage: /run [show|focus] RUN_ID [page]"
    run_id = args[1]
    page = _page_arg(args[2:])
    stream = _event_stream()
    record = stream.get_run(run_id)
    if record is None:
        return f"Run not found: {run_id}"
    events = list(
        stream.iter_persisted_events(
            run_id,
            after_sequence=(page - 1) * 50,
            limit=50,
        )
    )
    _state.active_run_id = run_id
    rendered = render_run_view(record, events)
    return f"{rendered}\n\nEvent page {page} · {len(events)} records"

def _control(args: list[str], action: str) -> str:
    run_id = args[0] if args else _state.active_run_id
    if not run_id:
        runs = _event_stream().list_runs(limit=1)
        run_id = runs[0].run_id if runs else ""
    if not run_id:
        return f"No run available to {action}."
    try:
        record = _event_stream().control_run(run_id, action)
    except (KeyError, ValueError) as exc:
        return str(exc)
    _state.active_run_id = run_id
    return f"Run {run_id}: {record.state.value}"


@cmd("pause", "Pause the active run")
def _pause(args: list[str]) -> str:
    return _control(args, "pause")


@cmd("resume", "Resume the active run")
def _resume(args: list[str]) -> str:
    return _control(args, "resume")


@cmd("cancel", "Cancel the active operation or run")
def _cancel(args: list[str]) -> str:
    if not args and _session().cancel_event.is_set():
        return "The active operation is already cancelling."
    if not args and not _state.active_run_id:
        _session().cancel_active()
        return "Active terminal operation cancellation requested."
    return _control(args, "cancel")


@cmd("approval", "Review or resolve approvals")
def _approval(args: list[str]) -> str:
    from nous_runtime.governance.broker import get_broker

    broker = get_broker()
    if not args:
        pending = broker.get_pending()
        if not pending:
            return f"Approval mode: {_state.approval_mode}\nNo pending approvals."
        request = pending[0]
        proposal = _proposal_for_request(request)
        suffix = "" if len(pending) == 1 else f"\n\n{len(pending) - 1} more pending."
        return render_approval_panel(request, proposal, details=False) + suffix

    command = args[0].lower()
    if command in {"mode", "rules"}:
        if len(args) == 1:
            return _approval_mode_summary()
        return _set_approval_mode(args[1].lower())
    if command in {"strict", "balanced", "assisted"}:
        return _set_approval_mode(command)
    if command == "reset":
        return _set_approval_mode("strict")
    if command == "details" and len(args) >= 2:
        request = _pending_approval(args[1])
        if request is None:
            return f"Pending approval not found: {args[1]}"
        return render_approval_panel(
            request,
            _proposal_for_request(request),
            details=True,
        )
    if command == "edit" and len(args) >= 2:
        return _edit_approval(args[1], args[2:])
    if command in {"once", "session", "deny"} and len(args) >= 2:
        request_id = args[1]
        reason = " ".join(args[2:])
        approver_id = _terminal_subject_id()
        try:
            if command == "deny":
                response = broker.deny(
                    request_id,
                    approver_id=approver_id,
                    reason=reason or "Denied in terminal",
                )
            else:
                response = broker.approve(
                    request_id,
                    approver_id=approver_id,
                    scope=command,
                    reason=reason,
                    prevent_self_approval=True,
                )
        except ValueError as exc:
            return str(exc)
        _state.dismissed_approvals.discard(request_id)
        return f"Approval {request_id}: {response.decision} ({command})"
    return (
        "Usage: /approval [details ID|once ID|session ID|edit ID key=value|"
        "deny ID|mode strict|balanced|assisted|reset]"
    )


def _terminal_subject_id() -> str:
    return os.environ.get("NOUS_SUBJECT_ID", "local")


def _pending_approval(request_id: str) -> dict[str, Any] | None:
    from nous_runtime.governance.broker import get_broker

    return next(
        (
            item
            for item in get_broker().get_pending()
            if str(item.get("request_id") or "") == request_id
        ),
        None,
    )


def _proposal_for_request(request: dict[str, Any]) -> dict[str, Any] | None:
    from nous_runtime.governance.broker import get_broker

    proposal_hash = str(request.get("proposal_hash") or "")
    store = getattr(get_broker(), "_store", None)
    if not proposal_hash or store is None:
        return None
    return store.get_proposal(proposal_hash)


def _approval_mode_summary() -> str:
    return "\n".join(
        (
            f"Approval mode: {_state.approval_mode}",
            "  strict    Ask for every governed action",
            "  balanced  Existing policy may allow low-risk actions",
            "  assisted  Existing policy may allow low- and medium-risk actions",
            "Critical risk always requires a human decision.",
        )
    )


def _set_approval_mode(mode: str) -> str:
    from nous_runtime.governance.broker import ApprovalPolicy, get_broker

    settings = {
        "strict": ("always_ask", False, False),
        "balanced": ("policy_controlled", False, False),
        "assisted": ("policy_controlled", False, False),
    }
    if mode not in settings:
        return "Approval mode must be strict, balanced, or assisted."
    scope, read_only, tests = settings[mode]
    max_risk = "medium" if mode == "assisted" else "low"
    policy = ApprovalPolicy(
        agent_id=_terminal_subject_id(),
        scope=scope,
        max_auto_approve_risk=max_risk,
        auto_approve_read_only=read_only,
        auto_approve_tests=tests,
        require_confirmation_for_policy_change=True,
    )
    get_broker().set_policy(policy)
    _state.approval_mode = mode
    return _approval_mode_summary()


def _edit_approval(request_id: str, changes: list[str]) -> str:
    from nous_runtime.cli.execution_ui import render_plan_confirmation
    from nous_runtime.governance.contracts import ActionProposal, AuthorizationContext
    from nous_runtime.governance.gate import get_gate

    request = _pending_approval(request_id)
    if request is None:
        return f"Pending approval not found: {request_id}"
    original_data = _proposal_for_request(request)
    if original_data is None:
        return "Proposal details are unavailable; the edit is denied."
    if not changes:
        return (
            f"Usage: /approval edit {request_id} key=value\n"
            "Editable: target_workspace, affected_resources, required_permissions, "
            "data_classification, side_effect_class, reversibility, retry_behavior, "
            "external_recipients"
        )
    scalar_fields = {
        "target_workspace",
        "data_classification",
        "side_effect_class",
        "reversibility",
        "retry_behavior",
    }
    sequence_fields = {
        "affected_resources",
        "required_permissions",
        "external_recipients",
    }
    updates: dict[str, Any] = {}
    for change in changes:
        if "=" not in change:
            return f"Invalid edit: {change}. Use key=value."
        key, value = change.split("=", 1)
        if key in scalar_fields:
            updates[key] = value
        elif key in sequence_fields:
            updates[key] = tuple(item for item in value.split(",") if item)
        else:
            return f"Field is not safely editable: {key}"

    original = ActionProposal.from_dict(original_data)
    data = original.to_dict()
    for key in ("proposal_id", "proposal_hash", "action_id", "parameter_hash", "created_at"):
        data.pop(key, None)
    data.update(updates)
    edited = ActionProposal(**data)
    context = AuthorizationContext(
        subject_type="human",
        subject_id=_terminal_subject_id(),
        subject_claims=("terminal:approval",),
        authn_method="local_terminal",
        authn_confidence=1.0,
        session_id=_session().conversation_id,
        session_locality="local",
    )
    decision = get_gate().evaluate(edited, context)
    return "\n".join(
        (
            render_plan_confirmation(edited.to_dict()),
            "",
            f"Revalidation: {decision.action_mode}",
            f"Reason: {decision.reason or 'Governance evaluation completed'}",
            "The original request remains pending. Its owner must resubmit the edited action.",
        )
    )


@cmd("approve", "Compatibility approval command")
def _approve(args: list[str]) -> str:
    if not args:
        return _approval([])
    decision = args[0].lower()
    if decision == "approve" and len(args) >= 2:
        return _approval(["once", *args[1:]])
    if decision == "deny" and len(args) >= 2:
        return _approval(["deny", *args[1:]])
    return "Usage: /approve [approve|deny] REQUEST_ID [reason]"

@cmd("context", "Show the active conversation context")
def _context(args: list[str]) -> str:
    snapshot = _session().context_snapshot()
    summary = snapshot.get("summary") or "(none)"
    return (
        f"Conversation: {_session().conversation_id}\n"
        f"Context: {snapshot.get('used_chars', 0)} / "
        f"{snapshot.get('budget_chars', 0)} characters\n"
        f"Loaded messages: {len(snapshot.get('messages', []))}\n"
        f"Rolling summary: {summary}"
    )


@cmd("history", "Show paginated conversation history")
def _history(args: list[str]) -> str:
    page_data = _session().history_page(_page_arg(args))
    lines = [f"History - page {page_data['page']}"]
    for message in reversed(page_data["messages"]):
        content = str(message.get("content") or "").replace("\n", " ")
        lines.append(f"  {message.get('role', '?'):<10} {content[:160]}")
    if page_data["has_more"]:
        lines.append("  More history is available on the next page.")
    return "\n".join(lines)


@cmd("logs", "Search conversation logs: /logs QUERY [page]")
def _logs(args: list[str]) -> str:
    if not args:
        return "Usage: /logs QUERY [page]"
    page = 1
    query_args = args
    if len(args) > 1:
        try:
            page = max(1, int(args[-1]))
            query_args = args[:-1]
        except ValueError:
            pass
    data = _session().search(" ".join(query_args), page=page)
    lines = [f"Log search - page {page} - {data['query']}"]
    for message in data["messages"]:
        content = str(message.get("content") or "").replace("\n", " ")
        lines.append(f"  {message.get('role', '?'):<10} {content[:160]}")
    if len(lines) == 1:
        lines.append("  No matches.")
    return "\n".join(lines)


@cmd("files", "Show indexed workspace files")
def _files(args: list[str]) -> str:
    path = _session().root / ".nous" / "index" / "files.json"
    if not path.is_file():
        return "No file index. Run /scan to create one."
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return f"File index unavailable: {exc}"
    rows = data.get("files", data) if isinstance(data, dict) else data
    if isinstance(rows, dict):
        rows = list(rows)
    if not isinstance(rows, list):
        return "File index format is not supported."
    page = _page_arg(args)
    selected = rows[(page - 1) * 50 : page * 50]
    lines = [f"Indexed files - page {page}"]
    for item in selected:
        value = item.get("path", "") if isinstance(item, dict) else str(item)
        lines.append(f"  {value}")
    if not selected:
        lines.append("  No files on this page.")
    return "\n".join(lines)


@cmd("tests", "Show recent test events")
def _tests(args: list[str]) -> str:
    page = _page_arg(args)
    test_events = []
    stream = _event_stream()
    for run in stream.list_runs(limit=50):
        for event in stream.iter_persisted_events(run.run_id, limit=1000):
            if event.event_type in {"test.started", "test.completed"}:
                test_events.append(event)
    test_events.sort(key=lambda event: event.timestamp, reverse=True)
    selected = test_events[(page - 1) * 20 : page * 20]
    lines = [f"Test events - page {page}"]
    lines.extend(
        f"  {event.timestamp}  {event.run_id}  {event.event_type}"
        for event in selected
    )
    if not selected:
        lines.append("  No test events.")
    return "\n".join(lines)

@cmd("provider", "Provider configuration and health")
def _provider(args: list[str]) -> str:
    """Present the Provider Wizard, dashboard, and explicit diagnostics."""
    from nous_runtime.cli.provider_experience import (
        configured_provider_rows,
        diagnose_provider,
        probe_provider,
        read_provider_configs,
        render_probe_result,
        render_provider_dashboard,
        render_provider_doctor,
    )

    action = args[0].lower() if args else "list"
    if action in {"list", "status", "health", "dashboard"}:
        return render_provider_dashboard()
    if action in {"add", "setup", "quick"}:
        from nous_runtime.cli.provider_setup import run_provider_setup

        result = run_provider_setup(quick=action == "quick")
        if result.startswith("Provider saved."):
            _ensure_providers()
            from nous_runtime.runtime.bootstrap import NousRuntime

            NousRuntime.bootstrap(
                workspace_root=str(_session().root),
                force=True,
            )
        return result
    if action == "doctor":
        provider_id = args[1] if len(args) > 1 else ""
        targets = [provider_id] if provider_id else list(read_provider_configs())
        if not targets:
            return "No configured Providers. Use /provider add first."
        return "\n\n".join(
            render_provider_doctor(diagnose_provider(target)) for target in targets
        )
    if action in {"test", "ping"}:
        provider_id = args[1] if len(args) > 1 else ""
        if not provider_id:
            rows = configured_provider_rows()
            if len(rows) == 1:
                provider_id = str(rows[0]["provider_id"])
            else:
                return f"Usage: /provider {action} PROVIDER_ID"
        return render_probe_result(probe_provider(provider_id, action))
    return (
        "Usage: /provider "
        "[list|add|quick|health|doctor [PROVIDER_ID]|test PROVIDER_ID|ping PROVIDER_ID]"
    )


@cmd("providers", "List providers", aliases=["pr"])
def _providers(args: list[str]) -> str:
    return _provider(["list"])

@cmd("capabilities", "List capabilities with availability", aliases=["cap"])
def _capabilities(args: list[str]) -> str:
    """Show capabilities with available/unavailable split."""
    try:
        from nous_runtime.capability.availability import check_availability
        avail = check_availability()

        available = avail.get("available", [])
        unavailable = avail.get("unavailable", [])

        lines: list[str] = []

        lines.append("Available:")
        lines.append(f"  {'Capability':<36} {'Provider':<16} {'Risk':<8}")
        lines.append(f"  {'-'*34}  {'-'*14}  {'-'*6}")
        if available:
            for c in available[:20]:
                name = c.get("name", "?")[:34]
                prov = c.get("provider", "")[:14]
                risk = c.get("risk", "")[:6]
                lines.append(f"  {name:<36} {prov:<16} {risk:<8}")
            if len(available) > 20:
                lines.append(f"  ... +{len(available) - 20} more")
        else:
            lines.append("  (none)")

        if unavailable:
            lines.append("")
            lines.append("Unavailable:")
            for c in unavailable[:10]:
                name = c.get("name", "?")[:34]
                reason = c.get("reason", "unknown")[:40]
                lines.append(f"  {name:<36} {reason}")
            if len(unavailable) > 10:
                lines.append(f"  ... +{len(unavailable) - 10} more")

        return "\n".join(lines)
    except ImportError:
        # Fall back to basic capability list
        try:
            from nous_runtime.services.capabilities import list_capabilities
            caps = list_capabilities()
            if not caps:
                return "No capabilities."
            lines = [f"{'Capability':<36} {'Risk':<8}", "-" * 46]
            for c in caps[:25]:
                name = c.get("name", "?") if isinstance(c, dict) else str(c)
                risk = c.get("risk", "") if isinstance(c, dict) else ""
                lines.append(f"{name:<36} {risk:<8}")
            return "\n".join(lines)
        except Exception as e:
            return f"Error: {e}"


@cmd("packs", "List installed packs", aliases=["pk"])
def _packs(args: list[str]) -> str:
    try:
        from nous_runtime.services.packs import list_packs
        packs = list_packs()
        if not packs:
            return "No packs. Try: nous pack install packs/examples/hello_pack"
        lines = [f"{'Pack':<24} {'Version':<8} Enab.", "-" * 40]
        for p in packs:
            lines.append(f"{p['name']:<24} {p['version']:<8} {str(p['enabled'])[:5]}")
        return "\n".join(lines)
    except Exception as e:
        return f"Error: {e}"


@cmd("jobs", "Recent jobs", aliases=["j"])
def _jobs(args: list[str]) -> str:
    try:
        from nous_runtime.services.jobs import list_jobs
        all_jobs = list_jobs()
        if not all_jobs:
            return "No jobs."
        lines = [f"{'ID':<30} {'Status':<12}", "-" * 44]
        for j in all_jobs[-10:]:
            jid = (j.get("job_id") or j.get("id") or "?")[:28]
            st = j.get("status", "?")
            lines.append(f"{jid:<30} {st:<12}")
        return "\n".join(lines)
    except Exception as e:
        return f"Error: {e}"


@cmd("trace", "Execution traces", aliases=["t"])
def _trace(args: list[str]) -> str:
    try:
        limit = int(args[0]) if args else 8
    except ValueError:
        limit = 8
    try:
        from nous_runtime.services.traces import get_recent_traces
        traces = get_recent_traces(limit)
        if not traces:
            return "No traces."
        lines = [f"{'Trace':<30} {'Capability':<22} {'Decision'}", "-" * 64]
        for t in traces[:limit]:
            if isinstance(t, dict):
                lines.append(
                    f"{t.get('trace_id','?')[:28]:<30} "
                    f"{t.get('capability','?')[:20]:<22} "
                    f"{t.get('decision','?')[:10]}"
                )
        return "\n".join(lines)
    except Exception as e:
        return f"Error: {e}"


@cmd("workspace", "Workspace info", aliases=["ws"])
def _workspace(args: list[str]) -> str:
    try:
        from nous_runtime.project.workspace import find_workspace
        ws = find_workspace()
        if ws:
            return (
                f"Workspace: {ws}\n"
                f"Project:   {ws.parent}\n"
                f"Structure: memory/ index/ traces/ artifacts/"
            )
        return f"Workspace: {os.getcwd()}\nNo .nous/ found. Run 'nous project init'."
    except Exception:
        return f"Workspace: {os.getcwd()}\nPacks dir: packs/\nData dir: remote_terminal/data/"


@cmd("scan", "Scan project files into .nous/index/files.json", aliases=[])
def _scan(args: list[str]) -> str:
    """Scan the project and index files."""
    try:
        from nous_runtime.project.workspace import find_workspace, init_workspace
        ws = find_workspace()
        if ws is None:
            ws = init_workspace()

        from nous_runtime.project.scan import scan_project

        root = str(ws.parent)
        summary = scan_project(root)
        lines = [
            "Project scan complete.",
            f"  Files:  {summary['total_files']}",
            f"  Size:   {summary['total_size_kb']} KB",
        ]
        types = summary.get("types", {})
        if types:
            lines.append("  Top types:")
            for ftype, count in list(types.items())[:5]:
                lines.append(f"    {ftype:<16} {count}")
        return "\n".join(lines)
    except Exception as e:
        return f"Scan failed: {e}"


@cmd("memory", "Show recent timeline entries", aliases=["mem"])
def _memory(args: list[str]) -> str:
    """Display recent memory timeline entries."""
    try:
        from nous_runtime.project.workspace import find_workspace
        ws = find_workspace()
        if ws is None:
            return "No .nous/ workspace. Run 'nous project init' first."

        from nous_runtime.project.memory import (
            active_facts,
            recent_decisions,
            read_recent,
            search_memory,
        )

        if args and args[0] == "facts":
            facts = active_facts(str(ws))
            if not facts:
                return "No active facts."
            return "\n".join(f"{f.get('key')}: {f.get('value')}" for f in facts[:20])

        if args and args[0] == "decisions":
            decisions = recent_decisions(str(ws), limit=10)
            if not decisions:
                return "No decisions recorded."
            return "\n".join(
                f"{d.get('question', '')}: {d.get('answer', '')}"
                for d in decisions
            )

        if args and args[0] == "search":
            query = " ".join(args[1:]).strip()
            if not query:
                return "Usage: /memory search <query>"
            results = search_memory(str(ws), query, limit=10)
            if not results:
                return "No matching memory records."
            return "\n".join(
                f"{r.get('record_type', r.get('_kind', 'record'))}: "
                f"{r.get('key', r.get('event_type', r.get('content', '')))}"
                for r in results
            )

        limit = 10
        if args:
            try:
                limit = int(args[0])
            except ValueError:
                pass

        entries = read_recent(str(ws), "timeline", limit=limit)
        if not entries:
            return "No timeline entries yet. Events are recorded as you work."

        lines = [f"{'Time':<22} {'Type':<24} Detail", "-" * 72]
        for e in entries:
            ts = e.get("timestamp", "")[:19]
            typ = e.get("type", "")[:24]
            detail = e.get("detail", "")
            if len(detail) > 60:
                detail = detail[:57] + "..."
            lines.append(f"{ts:<22} {typ:<26} {detail}")
        return "\n".join(lines)
    except Exception as e:
        return f"Memory unavailable: {e}"


@cmd("tasks", "Show the canonical task and run queue", aliases=["task"])
def _tasks_cmd(args: list[str]) -> str:
    """Present tasks through authoritative Run and Approval records."""
    return _runs(args)

@cmd("inspect", "Unified runtime inspector", aliases=[])
def _inspect(args: list[str]) -> str:
    """Display one requested read-only diagnostic branch."""
    try:
        from nous_runtime.inspector import diagnose, snapshot

        snap = snapshot()
        snap.findings = diagnose(snap)
        data = snap.to_dict()
        section = args[0].lower() if args else "overview"
        aliases = {
            "summary": "overview",
            "tasks": "scheduler",
            "observations": "context",
            "diagnose": "diagnostics",
            "diagnostics": "diagnostics",
            "provider": "providers",
            "device": "devices",
        }
        section = aliases.get(section, section)

        if section == "overview":
            return _render_inspector_overview(
                (
                    ("Runtime", data["runtime"].get("version", "Unknown")),
                    ("Scheduler", f"{len(data['tasks'])} tasks"),
                    ("Context", f"{len(data['observations'])} observations"),
                    ("Memory", "Available"),
                    ("Retrieval", "Available"),
                    ("Events", f"{len(data['findings'])} findings"),
                    ("Providers", str(len(data["providers"]))),
                    ("Devices", str(len(data["devices"]))),
                )
            )
        if section == "diagnostics":
            return _render_inspector_section(
                "Diagnostics", _format_inspect_rows(data["findings"])
            )
        if section == "runtime":
            return _render_inspector_section(
                "Runtime", _format_inspect_mapping(data["runtime"])
            )
        if section == "scheduler":
            return _render_inspector_section(
                "Scheduler", _format_inspect_rows(data["tasks"])
            )
        if section == "context":
            return _render_inspector_section(
                "Context", _format_inspect_mapping(_session().context_snapshot())
            )
        if section == "memory":
            return _render_inspector_section(
                "Memory", _format_inspect_mapping(data["memory"])
            )
        if section == "retrieval":
            from nous_runtime.retrieval.inspector import retrieval_snapshot

            workspace = _session().root / ".nous"
            return _render_inspector_section(
                "Retrieval",
                _format_inspect_mapping(retrieval_snapshot(workspace)),
            )
        if section == "events":
            runs = _event_stream().list_runs(limit=20)
            body = "\n".join(
                f"{run.run_id:<28}{run.state.value:<22}{run.updated_at}"
                for run in runs
            )
            return _render_inspector_section("Events", body or "(none)")
        if section == "providers":
            return _render_inspector_section(
                "Providers", _format_inspect_rows(data["providers"])
            )
        if section == "devices":
            return _render_inspector_section(
                "Devices", _format_inspect_rows(data["devices"])
            )

        return (
            "Usage: /inspect "
            "[overview|diagnostics|runtime|scheduler|context|memory|retrieval|events|providers|devices]"
        )
    except Exception as exc:
        return f"Inspector unavailable: {exc}"


def _render_inspector_overview(rows: tuple[tuple[str, str], ...]) -> str:
    lines = ["Inspector Snapshot"]
    for index, (name, detail) in enumerate(rows):
        branch = "└─" if index == len(rows) - 1 else "├─"
        lines.append(f"{branch} {name:<13}{detail}")
    lines.extend(("", "Use /inspect <section> to expand one branch."))
    return "\n".join(lines)


def _render_inspector_section(title: str, body: str) -> str:
    rows = [line.strip() for line in body.splitlines() if line.strip()]
    lines = ["Inspector", f"└─ {title}"]
    if not rows:
        rows = ["(none)"]
    for index, row in enumerate(rows):
        branch = "└─" if index == len(rows) - 1 else "├─"
        lines.append(f"   {branch} {row}")
    return "\n".join(lines)


def _format_inspect_mapping(data: dict[str, Any]) -> str:
    lines: list[str] = []
    for key, value in data.items():
        if isinstance(value, (list, dict)):
            lines.append(f"{key:<22}{len(value)}")
        else:
            lines.append(f"{key:<22}{value}")
    return "\n".join(lines) if lines else "(none)"


def _format_inspect_rows(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return "(none)"
    lines: list[str] = []
    for item in rows[:40]:
        if "code" in item:
            lines.append(
                f"{item.get('severity', ''):<8} {item.get('code', ''):<32} "
                f"{item.get('message', '')}"
            )
        elif "task_id" in item:
            detail = item.get("description") or item.get("title", "")
            lines.append(
                f"{item.get('task_id', ''):<24} "
                f"{item.get('status', ''):<12} {detail}"
            )
        elif "capability_id" in item:
            state = "available" if item.get("available") else "unavailable"
            lines.append(
                f"{item.get('capability_id', ''):<34} {state:<12} "
                f"{item.get('provider_id', '')}"
            )
        elif "provider_id" in item:
            lines.append(
                f"{item.get('provider_id', ''):<24} "
                f"{item.get('status', ''):<12} {item.get('name', '')}"
            )
        elif "device_id" in item:
            online = "online" if item.get("online") else "offline"
            lines.append(
                f"{item.get('device_id', ''):<24} {online:<8} "
                f"{item.get('device_type', '')}"
            )
        elif "observation_id" in item:
            lines.append(
                f"{item.get('observation_id', ''):<24} "
                f"{item.get('status', ''):<12} {item.get('record_type', '')}"
            )
        else:
            lines.append(str(item))
    if len(rows) > 40:
        lines.append(f"... +{len(rows) - 40} more")
    return "\n".join(lines)


@cmd("debug", "Debug diagnostic commands", aliases=["dbg"])
def _debug(args: list[str]) -> str:
    """Route to debug sub-commands."""
    sub = args[0].lower() if args else ""
    if sub == "providers":
        from nous_runtime.cli.debug_providers import debug_providers
        from nous_runtime.cli.provider_setup import load_providers_from_config
        load_providers_from_config()
        return debug_providers()
    return "Usage: /debug providers"


@cmd("settings", "Show project settings from .nous/config.json", aliases=["cfg"])
def _settings(args: list[str]) -> str:
    """Display project configuration."""
    try:
        from nous_runtime.project.workspace import find_workspace
        ws = find_workspace()
        if ws is None:
            return "No .nous/ workspace. Run 'nous project init' first."

        config_path = ws / "config.json"
        if not config_path.is_file():
            return "No config.json found in workspace."

        import json
        data = json.loads(config_path.read_text(encoding="utf-8"))
        if not data:
            return "No project settings configured yet."

        lines = ["Project Settings:", ""]
        for key, value in sorted(data.items()):
            val_str = json.dumps(value, ensure_ascii=False)
            if len(val_str) > 60:
                val_str = val_str[:57] + "..."
            lines.append(f"  {key:<24} {val_str}")
        return "\n".join(lines)
    except Exception as e:
        return f"Settings unavailable: {e}"


@cmd("clear", "Clear screen", aliases=["cls"])
def _clear(args: list[str]) -> str:
    os.system("cls" if os.name == "nt" else "clear")
    return ""


@cmd("quit", "Exit shell", aliases=["q", "exit"])
def _quit(args: list[str]) -> str:
    _state.running = False
    return ""


# Natural Language Router

def _ensure_providers() -> None:
    """Load configured providers and refresh presentation-only labels."""
    try:
        from nous_runtime.runtime.no_intelligence import no_intelligence_enabled

        if no_intelligence_enabled():
            from nous_runtime.runtime.bootstrap import NousRuntime

            runtime = NousRuntime.current(required=False)
            _state.provider_label = "Disabled"
            _state.model_label = "Disabled"
            _state.connection_label = (
                "ready" if runtime is not None and runtime.snapshot().ready else "offline"
            )
            return
        from nous_runtime.cli.provider_setup import load_providers_from_config
        from nous_runtime.runtime.lifecycle import Runtime

        load_providers_from_config()
        _state.provider_label, _state.model_label = _provider_presentation()
        status = Runtime().status()
        _state.connection_label = (
            "ready" if status.running and status.providers else "offline"
        )
    except Exception:
        _state.provider_label = "Not configured"
        _state.model_label = "Not configured"
        _state.connection_label = "offline"


def _provider_presentation() -> tuple[str, str]:
    """Read sanitized provider/model labels from existing CLI configuration."""
    try:
        from nous_runtime.cli.provider_setup import PROVIDER_PRESETS
        from nous_runtime.project.workspace import find_workspace

        workspace = find_workspace()
        config_path = workspace / "providers.json" if workspace else None
        if config_path is not None and config_path.is_file():
            data = json.loads(config_path.read_text(encoding="utf-8"))
            entries = list(data.items()) if isinstance(data, dict) else []
            if entries:
                provider_id, config = entries[0]
                config = config if isinstance(config, dict) else {}
                preset = PROVIDER_PRESETS.get(str(provider_id), {})
                name = str(config.get("name") or preset.get("name") or provider_id)
                if len(entries) > 1:
                    name = f"{name} +{len(entries) - 1}"
                model = str(config.get("model") or "Default")
                return name, model

        from nous_runtime.services.providers import list_provider_summaries

        providers = list_provider_summaries()
        if providers:
            first = providers[0]
            name = str(first.get("name") or first.get("provider_id") or "Configured")
            if len(providers) > 1:
                name = f"{name} +{len(providers) - 1}"
            model = str(first.get("model") or os.environ.get("NOUS_LLM_MODEL") or "Default")
            return name, model
    except Exception:
        pass
    return "Not configured", "Not configured"


def _activity(name: str, state: str, detail: str = "") -> None:
    """Send presentation progress without changing Runtime state."""
    callback = _state.activity_callback
    if callback is not None:
        callback(name, state, detail)


def _record_trace_timeline(event_type: str, detail: str) -> None:
    """Write a trace event to .nous/memory/timeline.jsonl if workspace exists."""
    try:
        from nous_runtime.project.workspace import find_workspace
        ws = find_workspace()
        if ws:
            from nous_runtime.project.memory import add_event
            add_event(str(ws), event_type, detail)
    except Exception:
        pass  # best-effort; never break the shell


def _friendly_error(result) -> str:
    """Convert execution errors to user-friendly messages."""
    err = getattr(result, "error", "") or ""
    code = getattr(result, "error_code", "") or ""
    provider_hint = _configured_provider_unavailable_hint()

    if "not found" in err.lower() or "not_found" in code.lower():
        return provider_hint or "No provider configured. Run: nous provider add"
    if "no provider" in err.lower() or "provider" in err.lower():
        return (
            provider_hint
            or "No provider configured for this capability. Run: nous provider add"
        )
    if "no handler" in err.lower() or "no_handler" in code.lower():
        return "Provider registered but no handler available. Check provider health."
    if "disabled" in err.lower():
        return "This capability is currently disabled."
    return (
        provider_hint
        or "Unable to execute. No provider is configured for this capability."
    )


def _configured_provider_unavailable_hint() -> str:
    """Explain an unusable configured Provider without exposing credentials."""
    try:
        from nous_runtime.cli.provider_experience import configured_provider_rows
        from nous_runtime.provider.credentials import credential_fix_suggestion

        rows = configured_provider_rows()
        candidates = [
            row
            for row in rows
            if "model.reason" in set(row.get("executable_capabilities") or ())
        ]
        for row in candidates:
            credential = row.get("credential")
            if credential is not None and not credential.available:
                name = str(row.get("name") or row.get("provider_id") or "Provider")
                provider_id = str(row.get("provider_id") or "").strip()
                suggestion = credential_fix_suggestion(credential)
                doctor = (
                    f" Run 'nous provider doctor {provider_id}'."
                    if provider_id
                    else ""
                )
                return (
                    f"Unable to execute. {name} is configured, but its credential "
                    f"is unavailable. {suggestion}.{doctor}"
                )
        if candidates:
            name = str(candidates[0].get("name") or "The configured Provider")
            provider_id = str(candidates[0].get("provider_id") or "").strip()
            doctor = (
                f" Run 'nous provider doctor {provider_id}'."
                if provider_id
                else ""
            )
            return f"Unable to execute. {name} is configured but unavailable.{doctor}"
    except Exception:
        return ""
    return ""


def _route_natural(
    text: str,
    cancel: threading.Event | None = None,
) -> str:
    """Route natural language while reporting presentation-only activity."""
    _activity("Planning", "running")
    if cancel and cancel.is_set():
        _activity("Planning", "warning", "cancelled")
        return "Operation cancelled."
    text_lower = text.lower()

    if any(kw in text_lower for kw in ["status", "health", "check", "how is"]):
        _activity("Planning", "success")
        return _status([])
    if any(kw in text_lower for kw in ["list", "show", "ls"]):
        _activity("Planning", "success")
        return "Try /runs, /files, /providers, /capabilities, /jobs, or /trace."

    from nous_runtime.planner.tool_router import (
        build_llm_prompt,
        detect_intent,
        execute_tool,
    )

    intent = detect_intent(text)
    if cancel and cancel.is_set():
        _activity("Planning", "warning", "cancelled")
        return "Operation cancelled."
    _activity("Planning", "success")
    if not intent:
        return _call_llm(text, cancel)

    _activity("Context", "running")
    observation = execute_tool(intent)
    if cancel and cancel.is_set():
        _activity("Context", "warning", "cancelled")
        return "Operation cancelled."
    if observation.status != "success":
        _activity("Context", "warning", "limited context")
        return _call_llm(text, cancel)

    _activity("Context", "success")
    if "retriev" in observation.tool.lower():
        _activity("Retrieval", "success")
    _record_trace_timeline(
        f"tool_{observation.tool.replace('.', '_')}",
        f"status={observation.status} "
        f"data_keys={observation.summary()['data_keys']}",
    )
    prompt = build_llm_prompt(intent, observation, text)
    return _call_llm(prompt, cancel)


def _call_llm(
    prompt: str,
    cancel: threading.Event | None = None,
) -> str:
    """Invoke conversational models through the unified Model Gateway."""
    if cancel and cancel.is_set():
        _activity("Execution", "warning", "cancelled")
        return "Operation cancelled."

    _activity("Provider", "running")
    _activity("Execution", "pending")
    try:
        from nous_runtime.model_runtime.facade import (
            GatewayExecutionContext,
            GatewayOperation,
            GatewayRequest,
            GatewayTraceContext,
            get_gateway_facade,
        )
        from nous_runtime.runtime.bootstrap import NousRuntime

        session = _session()
        request_id = f"shell-{uuid.uuid4().hex}"
        NousRuntime.bootstrap(workspace_root=str(session.root))
        facade = get_gateway_facade(required=True)
        response = facade.try_invoke_sync(
            GatewayRequest(
                operation=GatewayOperation.CHAT,
                execution=GatewayExecutionContext(
                    task_id=request_id,
                    workspace_id=session.workspace_id,
                    session_id=session.conversation_id,
                ),
                input=prompt,
                trace=GatewayTraceContext(
                    trace_id=request_id,
                    correlation_id=session.conversation_id,
                ),
            )
        )
        if cancel and cancel.is_set():
            _activity("Execution", "warning", "cancelled")
            return "Operation cancelled."

        if response.ok:
            _activity("Provider", "success")
            _activity("Execution", "success")
            content = response.content
            if not isinstance(content, str):
                content = json.dumps(content, ensure_ascii=False)
            _record_trace_timeline("nl_execution_ok", prompt[:40])
            return content

        _activity("Provider", "failure")
        _activity("Execution", "failure")
        error = dict(response.error)
        error_message = _friendly_error(
            type(
                "GatewayFailure",
                (),
                {
                    "error": str(error.get("message") or "Model Gateway failed"),
                    "error_code": str(error.get("code") or "NOUS_MODEL_GATEWAY_ERROR"),
                },
            )()
        )
        _record_trace_timeline(
            "nl_execution_failed",
            f"prompt={prompt[:40]} reason={error_message[:40]}",
        )
        return error_message
    except Exception:
        _activity("Provider", "failure")
        _activity("Execution", "failure")
        _record_trace_timeline(
            "nl_execution_error",
            f"prompt={prompt[:40]} reason=exception",
        )
        return _configured_provider_unavailable_hint() or (
            "No provider configured. Run: nous provider add"
        )


def _command_suggestions(raw: str) -> list[CompletionItem]:
    """Return strict, progressively narrower presentation completions."""
    if not raw.startswith("/"):
        return []
    body = raw[1:]
    if " " not in body:
        prefix = body.lower()
        names = _COMMAND_LAUNCH if not prefix else tuple(
            name for name in _COMMAND_ORDER if name.startswith(prefix)
        )
        return [
            CompletionItem(
                text=f"/{name}",
                label=f"/{name}",
                description=_COMMAND_DESCRIPTIONS[name],
                group=_COMMAND_GROUP[name],
            )
            for name in names[:8]
        ]

    command, remainder = body.split(" ", 1)
    command = command.lower()
    if command == "provider":
        actions = (
            ("list", "Configured Provider dashboard"),
            ("add", "Open the service-first Provider Wizard"),
            ("quick", "Configure a common service in one minute"),
            ("health", "Show Provider health"),
            ("doctor", "Diagnose connection, authentication, models, and latency"),
            ("test", "Send a minimal model request"),
            ("ping", "Check endpoint reachability"),
        )
        if " " not in remainder:
            return [
                CompletionItem(
                    text=f"/provider {action}",
                    label=action,
                    description=description,
                    group="Provider",
                )
                for action, description in actions
                if action.startswith(remainder.lower())
            ]
        action, prefix = remainder.split(" ", 1)
        if action not in {"test", "ping", "doctor"}:
            return []
        try:
            from nous_runtime.cli.provider_experience import configured_provider_rows

            rows = configured_provider_rows()
        except Exception:
            return []
        return [
            CompletionItem(
                text=f"/provider {action} {row['provider_id']}",
                label=str(row["provider_id"]),
                description=str(row["name"]),
                group="Configured Providers",
            )
            for row in rows
            if str(row["provider_id"]).lower().startswith(prefix.lower())
        ][:8]
    if command == "run":
        return _run_argument_suggestions(remainder)
    if command in {"pause", "resume", "cancel"}:
        return _run_control_suggestions(command, remainder)
    if command in {"approval", "approve"}:
        return _approval_suggestions(remainder, command)
    if command == "dashboard":
        sections = (
            "runtime", "scheduler", "memory", "events",
            "providers", "workspace", "performance", "queue",
        )
        return [
            CompletionItem(
                text=f"/dashboard {section}",
                label=section,
                description="Dashboard section",
                group="Dashboard",
            )
            for section in sections
            if section.startswith(remainder.lower())
        ][:8]
    if command == "inspect":
        sections = (
            "overview", "runtime", "scheduler", "context", "memory",
            "retrieval", "events", "providers", "devices",
        )
        return [
            CompletionItem(
                text=f"/inspect {section}",
                label=section,
                description="Read-only diagnostic section",
                group="Inspector",
            )
            for section in sections
            if section.startswith(remainder.lower())
        ][:8]
    return []


def _run_argument_suggestions(remainder: str) -> list[CompletionItem]:
    actions = (
        ("show", "Show timeline and action cards"),
        ("focus", "Focus a Run for keyboard controls"),
    )
    if " " not in remainder:
        return [
            CompletionItem(
                text=f"/run {action} ",
                label=action,
                description=description,
                group="Run",
            )
            for action, description in actions
            if action.startswith(remainder.lower())
        ]
    action, prefix = remainder.split(" ", 1)
    if action not in {"show", "focus"}:
        return []
    return _recent_run_items(f"run {action}", prefix.strip().lower())

def _run_control_suggestions(
    command: str,
    remainder: str,
) -> list[CompletionItem]:
    return _recent_run_items(command, remainder.strip().lower())


def _recent_run_items(command: str, prefix: str) -> list[CompletionItem]:
    try:
        records = _event_stream().list_runs(limit=20)
    except Exception:
        return []
    allowed = {
        "pause": {"RUNNING"},
        "resume": {"PAUSED"},
        "cancel": {
            "CREATED", "PLANNING", "WAITING_FOR_NODE",
            "WAITING_FOR_APPROVAL", "RUNNING", "PAUSED",
            "EVALUATING", "RECOVERING",
        },
    }.get(command)
    items: list[CompletionItem] = []
    for record in records:
        state = str(getattr(record.state, "value", record.state)).upper()
        if allowed is not None and state not in allowed:
            continue
        if prefix and not record.run_id.lower().startswith(prefix):
            continue
        items.append(
            CompletionItem(
                text=f"/{command} {record.run_id}",
                label=record.run_id,
                description=state,
                group="Recent runs",
            )
        )
        if len(items) == 8:
            break
    return items


def _approval_suggestions(
    remainder: str,
    command_name: str = "approval",
) -> list[CompletionItem]:
    actions = (
        ("details", "Show proposal and scope"),
        ("once", "Allow this exact proposal once"),
        ("session", "Allow this proposal under the existing session scope"),
        ("edit", "Edit scope and revalidate"),
        ("deny", "Deny the request"),
        ("mode", "Review approval modes"),
        ("reset", "Restore strict mode"),
    )
    if command_name == "approve":
        actions = (("approve", "Compatibility: allow once"), ("deny", "Deny request"))
    if " " not in remainder:
        return [
            CompletionItem(
                text=f"/{command_name} {action} ",
                label=action,
                description=description,
                group="Approval",
            )
            for action, description in actions
            if action.startswith(remainder.lower())
        ][:8]
    action, prefix = remainder.split(" ", 1)
    if action == "mode" and command_name == "approval":
        return [
            CompletionItem(
                text=f"/approval mode {mode}",
                label=mode,
                description="Existing ApprovalPolicy preset",
                group="Approval mode",
            )
            for mode in ("strict", "balanced", "assisted")
            if mode.startswith(prefix.lower())
        ]
    if action not in {"details", "once", "session", "edit", "deny", "approve"}:
        return []
    try:
        from nous_runtime.governance.broker import get_broker

        pending = get_broker().get_pending()
    except Exception:
        return []
    items: list[CompletionItem] = []
    for request in pending:
        request_id = str(request.get("request_id") or "")
        if not request_id or (prefix and not request_id.lower().startswith(prefix.lower())):
            continue
        summary = str(request.get("summary") or request.get("run_id") or "pending")
        items.append(
            CompletionItem(
                text=f"/{command_name} {action} {request_id}",
                label=request_id,
                description=summary,
                group="Pending approvals",
            )
        )
        if len(items) == 8:
            break
    return items


def _next_interactive_approval() -> dict[str, Any] | None:
    try:
        from nous_runtime.governance.broker import get_broker

        pending = get_broker().get_pending()
    except Exception:
        return None
    live_ids = {str(item.get("request_id") or "") for item in pending}
    _state.dismissed_approvals.intersection_update(live_ids)
    return next(
        (
            item
            for item in pending
            if str(item.get("request_id") or "") not in _state.dismissed_approvals
        ),
        None,
    )

# Shell Loop

def _dispatch(raw: str) -> dict[str, Any]:
    if raw.startswith("/"):
        parts = raw[1:].split()
        name = parts[0].lower() if parts else ""
        handler = COMMANDS.get(name)
        if handler is None:
            return {
                "kind": "command",
                "command": name,
                "status": "error",
                "content": f"Unknown command: /{name}. Type /help.",
            }
        return {
            "kind": "command",
            "command": name,
            "status": "ok",
            "content": handler["fn"](parts[1:]),
        }

    result = _session().execute(
        raw,
        lambda text, cancel: _route_natural(text, cancel),
    )
    return {
        "kind": "conversation",
        "status": result.status,
        "operation_id": result.operation_id,
        "conversation_id": result.conversation_id,
        "content": result.content,
    }


def _render_result(result: dict[str, Any]) -> None:
    if _state.json_output:
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return
    content = str(result.get("content") or "")
    if not content:
        return
    if result.get("kind") == "conversation":
        label = "Nous" if result.get("status") == "completed" else "Recovery"
        sys.stdout.write(f"\n{label}\n")
    elif result.get("status") == "error":
        sys.stdout.write("\nError\n")
    for chunk in stream_chunks(fold_output(content)):
        sys.stdout.write(chunk)
        sys.stdout.flush()
    sys.stdout.write("\n")
    sys.stdout.flush()


def run(
    *,
    json_output: bool = False,
    quiet: bool = False,
    session_id: str = "",
    interactive: bool | None = None,
) -> None:
    """Run the persistent terminal client over authoritative Runtime stores."""
    from nous_runtime.cli.terminal_ui import (
        RuntimeActivityPanel,
        read_approval_decision,
        read_interactive_line,
        render_divider,
        render_prompt,
    )

    _state.json_output = bool(json_output)
    _state.quiet = bool(quiet)
    _open_terminal_session(session_id)
    if interactive is None:
        interactive = bool(sys.stdin.isatty())

    _ensure_providers()
    if interactive and not json_output and not quiet:
        print(_banner())
        print()
        print("Conversation")
        print(render_divider())
        print()

    _init_readline()
    _record_trace_timeline("shell_started", "Terminal session started")
    prompt = render_prompt() if interactive and not json_output and not quiet else ""
    footer_status = {
        "json": json_output,
        "quiet": quiet,
        "provider": _state.provider_label,
        "connection": _state.connection_label,
    }

    while _state.running:
        footer_status["focus"] = _state.active_run_id or "None"
        footer_status["approval_mode"] = _state.approval_mode
        try:
            if interactive and not json_output and not quiet:
                request = _next_interactive_approval()
                if request is not None:
                    request_id = str(request.get("request_id") or "")
                    decision = read_approval_decision(
                        request,
                        _proposal_for_request(request),
                        status=footer_status,
                    )
                    if decision == "dismiss":
                        _state.dismissed_approvals.add(request_id)
                    elif decision == "edit":
                        _state.dismissed_approvals.add(request_id)
                        _state.input_prefill = f"/approval edit {request_id} "
                    else:
                        content = _approval([decision, request_id])
                        _render_result(
                            {
                                "kind": "command",
                                "status": "ok",
                                "content": content,
                            }
                        )
                        print()
                        continue
                initial = _state.input_prefill
                _state.input_prefill = ""
                raw = read_interactive_line(
                    prompt,
                    _command_suggestions,
                    history=_state.history,
                    status=footer_status,
                    activities=_state.last_activities,
                    initial=initial,
                ).strip()
            else:
                raw = input(prompt).strip()
        except EOFError:
            if interactive and not json_output and not quiet:
                print()
            break
        except KeyboardInterrupt:
            _state.last_activities = ()
            continue

        if not raw:
            continue
        _state.history.append(raw)
        _save_readline(raw)
        _state.last_activities = ()
        activity_panel = None
        if interactive and not json_output and not quiet and not raw.startswith("/"):
            activity_panel = RuntimeActivityPanel(footer_status)
            _state.activity_callback = activity_panel.update
            activity_panel.update("Planning", "pending")
        try:
            result = _dispatch(raw)
        finally:
            _state.activity_callback = None
            if activity_panel is not None:
                activity_panel.clear()
        if result.get("status") == "cancelled":
            _state.last_activities = (
                ActivityItem("Operation", "warning", "Cancelled"),
            )
        elif activity_panel is not None and result.get("status") == "completed":
            _state.last_activities = (
                ActivityItem("Finished", "success", "Ready"),
            )
        elif activity_panel is not None and result.get("status") in {"error", "failed"}:
            _state.last_activities = (
                ActivityItem("Operation", "failure", "Failed"),
            )
        _state.last_result = result
        _render_result(result)
        if interactive and not json_output and not quiet and _state.running:
            print()

    _record_trace_timeline("shell_exited", "Terminal session ended")
    _write_readline_history()
    if interactive and not json_output and not quiet:
        print("Session closed.")


# Readline helpers

def _init_readline() -> None:
    """Set up readline for up/down history navigation."""
    try:
        import readline
        readline.parse_and_bind("tab: complete")
        # Load history from .nous/history if available
        try:
            from nous_runtime.project.workspace import find_workspace
            ws = find_workspace()
            if ws:
                hist_file = str(ws / "history")
                if os.path.isfile(hist_file):
                    readline.read_history_file(hist_file)
        except Exception:
            pass
    except ImportError:
        pass  # Windows may not have readline; plain input() is fine


def _save_readline(line: str) -> None:
    """Append a line to the in-process readline history."""
    try:
        import readline
        # Only add if different from last entry
        try:
            prev = readline.get_history_item(readline.get_current_history_length())
        except Exception:
            prev = None
        if prev != line:
            readline.add_history(line)
    except ImportError:
        pass


def _write_readline_history() -> None:
    """Persist readline history to .nous/history."""
    try:
        import readline
        from nous_runtime.project.workspace import find_workspace
        ws = find_workspace()
        if ws:
            hist_file = str(ws / "history")
            readline.write_history_file(hist_file)
    except Exception:
        pass


if __name__ == "__main__":
    run()
