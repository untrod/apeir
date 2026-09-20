"""Terminal presentation for authoritative Run, Event, and Approval records."""

from __future__ import annotations

import re
import textwrap
from collections import OrderedDict
from typing import Any, Iterable, Sequence

from nous_runtime.cli.terminal_ui import _display_width, _pad_display, _term_width

_RUN_STATE = {
    "CREATED": "received",
    "PLANNING": "planning",
    "WAITING_FOR_NODE": "ready",
    "WAITING_FOR_APPROVAL": "waiting_approval",
    "RUNNING": "running",
    "PAUSED": "paused",
    "EVALUATING": "running",
    "RECOVERING": "recovering",
    "COMPLETED": "succeeded",
    "FAILED": "failed",
    "CANCELLED": "cancelled",
}
_TERMINAL_STATES = {"succeeded", "failed", "cancelled", "denied"}
_STATE_ORDER = (
    "received",
    "planning",
    "ready",
    "waiting_approval",
    "running",
    "paused",
    "retrying",
    "recovering",
    "succeeded",
)
_STATE_LABEL = {
    "received": "Received",
    "planning": "Planning",
    "ready": "Ready",
    "waiting_approval": "Waiting for approval",
    "running": "Running",
    "paused": "Paused",
    "retrying": "Retrying",
    "recovering": "Recovering",
    "succeeded": "Succeeded",
    "failed": "Failed",
    "cancelled": "Cancelled",
    "denied": "Denied",
}
_TOOL_TYPES = (
    (("command.",), "Shell command"),
    (("file.read", "file.open"), "File read"),
    (("file.changed", "file.write"), "File write"),
    (("test.",), "Test"),
    (("network.", "http."), "Network request"),
    (("plugin.",), "Plugin call"),
    (("connector.",), "Connector call"),
    (("workflow.", "step."), "Workflow step"),
    (("agent.deleg", "agent.dispatch"), "Agent delegation"),
)
_SECRET_PATTERN = re.compile(
    r"(?i)(api[_-]?key|token|password|secret|authorization)\s*[=:]\s*([^\s]+)"
)


def presentation_state(record: Any, events: Sequence[Any]) -> str:
    """Map canonical state and persisted events to one display-only state."""
    state = getattr(record, "state", "CREATED")
    value = str(getattr(state, "value", state)).upper()
    canonical = _RUN_STATE.get(value, "received")
    if canonical in _TERMINAL_STATES:
        return canonical

    event_types = [str(event.event_type).lower() for event in events]
    progress_types = {
        "run.started",
        "run.recovering",
        "run.completed",
        "run.failed",
        "run.cancelled",
    }
    latest_progress = max(
        (index for index, event_type in enumerate(event_types) if event_type in progress_types),
        default=-1,
    )
    latest_denial = max(
        (index for index, event_type in enumerate(event_types) if event_type == "approval.denied"),
        default=-1,
    )
    if latest_denial > latest_progress:
        return "denied"
    latest_retry = max(
        (index for index, event_type in enumerate(event_types) if "retry" in event_type),
        default=-1,
    )
    if latest_retry > latest_progress:
        return "retrying"
    return canonical

def render_run_view(
    record: Any,
    events: Sequence[Any],
    *,
    width: int | None = None,
    details: bool = False,
) -> str:
    """Render one focused Run from its canonical record and persisted events."""
    width = width or _term_width()
    state = presentation_state(record, events)
    lines = [
        f"Run {record.run_id}",
        f"State  {_STATE_LABEL[state]}",
    ]
    task_id = str(getattr(record, "task_id", "") or "")
    if task_id:
        lines.append(f"Task   {task_id}")
    lines.extend(("", *_render_timeline(state, events)))
    plan = _render_plan(record, events)
    if plan:
        lines.extend(("", *plan))
    cards = render_tool_action_cards(events, width=width, details=details)
    if cards:
        lines.extend(("", cards))
    failure = _render_failure(record, events, state)
    if failure:
        lines.extend(("", *failure))
    return "\n".join(lines)


def render_runs_queue(
    records: Sequence[Any],
    pending_approvals: Sequence[dict[str, Any]] = (),
    *,
    focused_run_id: str = "",
) -> str:
    """Group active, queued, and approval-blocked canonical Runs."""
    approval_runs = {
        str(item.get("run_id") or "") for item in pending_approvals if item.get("run_id")
    }
    groups: OrderedDict[str, list[Any]] = OrderedDict(
        (("Active", []), ("Queued", []), ("Approval required", []), ("Recent", []))
    )
    for record in records:
        state = str(getattr(record.state, "value", record.state)).upper()
        if record.run_id in approval_runs or state == "WAITING_FOR_APPROVAL":
            groups["Approval required"].append(record)
        elif state in {"CREATED", "WAITING_FOR_NODE"}:
            groups["Queued"].append(record)
        elif state in {"PLANNING", "RUNNING", "PAUSED", "EVALUATING", "RECOVERING"}:
            groups["Active"].append(record)
        else:
            groups["Recent"].append(record)
    lines = ["Tasks and Runs"]
    for name, rows in groups.items():
        if not rows:
            continue
        lines.extend(("", name))
        for record in rows[:12]:
            marker = "›" if record.run_id == focused_run_id else " "
            state = _RUN_STATE.get(str(record.state.value).upper(), "received")
            task = str(getattr(record, "task_id", "") or "")
            lines.append(
                f" {marker} {record.run_id:<28} {_STATE_LABEL[state]:<22} {task}"
            )
    if len(lines) == 1:
        lines.append("  No Runs.")
    lines.extend(("", "Use /run focus RUN_ID or /run show RUN_ID."))
    return "\n".join(lines)


def render_tool_action_cards(
    events: Sequence[Any],
    *,
    width: int | None = None,
    details: bool = False,
) -> str:
    """Render bounded action summaries while folding command output by default."""
    width = width or _term_width()
    cards: list[str] = []
    output_count = sum(1 for event in events if event.event_type == "command.output")
    for event in events:
        action = _tool_action(event.event_type)
        if not action or event.event_type == "command.output":
            continue
        payload = dict(getattr(event, "payload", {}) or {})
        rows = _action_rows(action, payload, event)
        if not details:
            rows = [row for row in rows if row[0] not in {"Result detail", "Operation"}]
        cards.append(_card("Action", rows, width))
    if output_count:
        cards.append(_card("Tool logs", (("State", f"Folded · {output_count} events"),), width))
    return "\n\n".join(cards[-8:])


def render_approval_panel(
    request: dict[str, Any],
    proposal: dict[str, Any] | None = None,
    *,
    selected: int = 0,
    details: bool = False,
    width: int | None = None,
) -> str:
    """Render a fail-closed human approval surface above Message input."""
    width = width or _term_width()
    proposal = dict(proposal or {})
    params = dict(proposal.get("params") or {})
    resources = tuple(proposal.get("affected_resources") or ())
    command = _redact(str(params.get("command") or proposal.get("parameter_summary") or ""))
    target = command or ", ".join(map(str, resources)) or str(
        proposal.get("capability_id") or request.get("summary") or "Unknown"
    )
    permissions = ", ".join(proposal.get("required_permissions") or ()) or "Not declared"
    rows: list[tuple[str, Any]] = [
        ("Action", proposal.get("action_type") or request.get("summary") or "Unknown"),
        ("Target", target),
        ("Workspace", proposal.get("target_workspace") or _scope_workspace(request)),
        ("Permissions", permissions),
        ("Risk", request.get("risk_summary") or proposal.get("side_effect_class") or "Unknown"),
        ("Reason", request.get("summary") or "Human confirmation required"),
        ("Actor", request.get("requested_by") or "Unknown"),
        ("Scope", request.get("scope_summary") or "Exact proposal"),
    ]
    if details:
        rows.extend(
            (
                ("Request", request.get("request_id") or ""),
                ("Side effect", proposal.get("side_effect_class") or "Unknown"),
                ("Reversible", proposal.get("reversibility") or "Unknown"),
                ("Expires", request.get("expires_at") or "Unspecified"),
            )
        )
    options = (
        "Allow once",
        "Allow for session",
        "Edit action",
        "Deny",
    )
    lines = [_card("Approval required", rows, width)]
    lines.append("")
    for index, option in enumerate(options):
        marker = "›" if index == selected else " "
        lines.append(f" {marker} {index + 1}. {option}")
    lines.append("   Y/1 once   A/2 session   E/3 edit   N/4 deny   Ctrl+O details")
    return "\n".join(lines)


def render_plan_confirmation(
    proposal: dict[str, Any],
    *,
    width: int | None = None,
) -> str:
    """Render confirmation evidence already present on an action proposal."""
    width = width or _term_width()
    params = dict(proposal.get("params") or {})
    resources = tuple(proposal.get("affected_resources") or ())
    rows = (
        ("Expected files", ", ".join(map(str, resources)) or "None declared"),
        ("Actions", proposal.get("parameter_summary") or proposal.get("action_type") or "Unknown"),
        ("Validation", params.get("test_scope") or params.get("validation") or "Not declared"),
        ("Risk", proposal.get("side_effect_class") or "Unknown"),
        ("Rollback", proposal.get("reversibility") or "Unknown"),
    )
    return _card("Plan confirmation", rows, width)


def _render_timeline(state: str, events: Sequence[Any]) -> list[str]:
    reached = _timeline_states(events)
    if state not in reached:
        reached.append(state)
    current = state
    completed = [item for item in reached if item != current and item not in _TERMINAL_STATES]
    lines = ["Execution"]
    if completed:
        lines.append(f"  ✓ Completed      {len(completed)} stages")
    icon = "✓" if current == "succeeded" else "×" if current in {"failed", "denied"} else "!" if current == "cancelled" else "◌"
    lines.append(f"  {icon} {_STATE_LABEL[current]}")
    return lines


def _timeline_states(events: Sequence[Any]) -> list[str]:
    result: list[str] = []
    mapping = {
        "run.created": "received",
        "runtime.request.received": "received",
        "plan.created": "planning",
        "run.queued": "ready",
        "approval.requested": "waiting_approval",
        "approval.denied": "denied",
        "run.started": "running",
        "run.paused": "paused",
        "run.resumed": "running",
        "run.recovering": "recovering",
        "run.completed": "succeeded",
        "run.failed": "failed",
        "run.cancelled": "cancelled",
    }
    for event in events:
        value = mapping.get(str(event.event_type).lower())
        if "retry" in str(event.event_type).lower():
            value = "retrying"
        if value and value not in result:
            result.append(value)
    return result


def _render_plan(record: Any, events: Sequence[Any]) -> list[str]:
    steps: OrderedDict[str, str] = OrderedDict()
    plan = dict(getattr(record, "plan", {}) or {})
    raw_steps = plan.get("steps") or ()
    for index, item in enumerate(raw_steps):
        if isinstance(item, dict):
            name = str(item.get("name") or item.get("title") or item.get("step_id") or index + 1)
            status = str(item.get("status") or "pending").lower()
        else:
            name, status = str(item), "pending"
        steps[name] = status
    for event in events:
        event_type = str(event.event_type).lower()
        if not event_type.startswith("step."):
            continue
        payload = dict(event.payload or {})
        name = str(payload.get("name") or payload.get("step_id") or event.task_id or "Step")
        status = {
            "step.started": "active",
            "step.progress": "active",
            "step.completed": "completed",
            "step.failed": "failed",
            "step.skipped": "skipped",
        }.get(event_type, "pending")
        steps[name] = status
    if not steps:
        return []
    completed = sum(1 for status in steps.values() if status == "completed")
    visible = [(name, status) for name, status in steps.items() if status != "completed"]
    lines = ["Plan"]
    if completed:
        lines.append(f"  ✓ Completed      {completed} steps")
    icons = {"pending": "○", "active": "◌", "failed": "×", "skipped": "−"}
    for name, status in visible[-8:]:
        lines.append(f"  {icons.get(status, '○')} {name:<28} {status}")
    return lines


def _render_failure(record: Any, events: Sequence[Any], state: str) -> list[str]:
    if state not in {"failed", "recovering", "cancelled", "denied"}:
        return []
    cause = "No additional cause was recorded."
    strategy = "Inspect the persisted Run events."
    for event in reversed(events):
        payload = dict(event.payload or {})
        if event.event_type in {"run.failed", "approval.denied", "recovery.assessed"}:
            cause = str(payload.get("reason") or payload.get("error") or payload.get("fault_type") or cause)
            strategy = str(payload.get("strategy") or strategy)
            break
    control = (
        f"/cancel {record.run_id}"
        if state == "recovering"
        else "Unavailable after a terminal decision"
    )
    return [
        "Failure and recovery",
        f"  Cause       {_redact(cause)}",
        "  Preserved   Run state and persisted events",
        f"  Recovery    {strategy}",
        f"  Inspect     /run show {record.run_id}",
        f"  Cancel      {control}",
        "  Retry       Not exposed by the current Recovery API",
        "  Fallback    Applied only by the existing reliability policy",
    ]


def _tool_action(event_type: str) -> str:
    lowered = event_type.lower()
    for prefixes, label in _TOOL_TYPES:
        if any(lowered.startswith(prefix) for prefix in prefixes):
            return label
    return ""


def _action_rows(action: str, payload: dict[str, Any], event: Any) -> list[tuple[str, Any]]:
    target = (
        payload.get("target")
        or payload.get("path")
        or payload.get("url")
        or payload.get("command")
        or payload.get("capability_id")
        or event.task_id
        or "Not specified"
    )
    rows: list[tuple[str, Any]] = [
        ("Action", action),
        ("Target", _redact(str(target))),
    ]
    fields = (
        ("Workspace", "workspace"),
        ("Purpose", "purpose"),
        ("Risk", "risk"),
        ("Duration", "duration_ms"),
        ("Result", "result"),
        ("Approval", "approval_state"),
        ("Operation", "operation"),
        ("Result detail", "detail"),
    )
    for label, key in fields:
        value = payload.get(key)
        if value is not None and value not in ("", (), []):
            suffix = " ms" if key == "duration_ms" else ""
            rows.append((label, _redact(str(value)) + suffix))
    return rows


def _card(title: str, rows: Iterable[tuple[str, Any]], width: int) -> str:
    width = max(40, width)
    inner = width - 2
    title_text = f"─ {title} "
    lines = ["╭" + title_text + "─" * max(0, inner - _display_width(title_text)) + "╮"]
    value_width = max(12, inner - 18)
    for label, value in rows:
        wrapped = _wrap(str(value), value_width)
        lines.append("│ " + _pad_display(f"{label:<15}{wrapped[0]}", inner - 2) + " │")
        for continuation in wrapped[1:]:
            lines.append("│ " + _pad_display(f"{'':<15}{continuation}", inner - 2) + " │")
    lines.append("╰" + "─" * inner + "╯")
    return "\n".join(lines)


def _wrap(value: str, width: int) -> list[str]:
    lines: list[str] = []
    for source in value.splitlines() or [""]:
        lines.extend(textwrap.wrap(source, width=max(8, width), break_long_words=True) or [""])
    return lines


def _scope_workspace(request: dict[str, Any]) -> str:
    value = str(request.get("scope_summary") or "")
    match = re.search(r"Workspace:\s*([^,]+)", value, re.IGNORECASE)
    return match.group(1).strip() if match else "Not specified"


def _redact(value: str) -> str:
    return _SECRET_PATTERN.sub(lambda match: f"{match.group(1)}=[redacted]", value)