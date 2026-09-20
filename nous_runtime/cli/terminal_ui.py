"""Terminal-native presentation primitives for the Nous Runtime control surface."""

from __future__ import annotations

import os
import shutil
import sys
import unicodedata
from collections import OrderedDict
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterator, Sequence

try:
    from rich.console import Console
except ImportError:
    Console = None

_HAS_RICH = Console is not None and "NO_COLOR" not in os.environ
HEADER_TITLE = "NOUS"
PROMPT = "> "

NOUS_LOGO = "Nous Runtime"
COMPACT_LOGO = NOUS_LOGO
_ACTIVITY_ICONS = {
    "pending": "[ ]",
    "running": "[~]",
    "success": "[OK]",
    "warning": "[!]",
    "failure": "[X]",
}
_COLOR_CODES = {
    "information": "36",
    "success": "32",
    "warning": "33",
    "failure": "31",
    "selection": "7",
    "neutral": "2",
}


@dataclass(frozen=True)
class CompletionItem:
    """A presentation-only completion candidate."""

    text: str
    label: str
    description: str
    group: str = "Commands"


@dataclass(frozen=True)
class ActivityItem:
    """A presentation-only view of one Runtime activity."""

    name: str
    state: str
    detail: str = ""


Completer = Callable[[str], Sequence[CompletionItem]]


def render_banner(
    workspace: str | None = None,
    status: dict[str, Any] | None = None,
) -> str:
    """Render a responsive identity header with bounded operational context."""
    values = _build_status(workspace, status or {})
    width = _term_width()
    metadata = (
        ("Workspace", values["workspace"]),
        ("Session", values["session"]),
        ("Provider", values["provider"]),
        ("Model", values["model"]),
        ("Path", values["path"]),
        ("Runtime", values["runtime"]),
        ("Version", values["version"]),
    )
    if width < 80:
        lines = [COMPACT_LOGO, ""]
        value_width = max(12, width - 12)
        lines.extend(
            f"{label:<11}{_truncate_display(value, value_width)}"
            for label, value in metadata
        )
        return "\n".join(lines)

    logo_lines = NOUS_LOGO.splitlines()

    column = max(28, (width - 3) // 2)
    lines = [*logo_lines, ""]
    lines.append(
        _pad_display(f"{'Workspace':<11}{values['workspace']}", column)
        + "   "
        + f"{'Session':<11}{values['session']}"
    )
    lines.append(
        _pad_display(f"{'Provider':<11}{values['provider']}", column)
        + "   "
        + f"{'Model':<11}{values['model']}"
    )
    lines.append(
        _pad_display(f"{'Runtime':<11}{values['runtime']}", column)
        + "   "
        + f"{'Version':<11}{values['version']}"
    )
    lines.append(f"{'Path':<11}{values['path']}")
    return "\n".join(_truncate_display(line, width) for line in lines)


def render_divider() -> str:
    return "-" * _term_width()


def render_prompt() -> str:
    return PROMPT


def render_startup_sequence() -> str:
    """Describe readiness without fake progress or artificial delay."""
    return "Nous initialized.\nRuntime ready."


def render_session_summary(
    last_events: list[dict[str, Any]] | None = None,
    pending_tasks: int = 0,
    provider_count: int = 0,
) -> str:
    """Render bounded continuity information for a restored session."""
    events = last_events or []
    lines = ["Session summary"]
    if events:
        for event in events[-3:]:
            detail = event.get("detail", event.get("type", "?"))
            lines.append(f"  {detail}")
    else:
        lines.append("  No previous activity.")
    lines.extend(("", f"pending     {pending_tasks}", f"providers   {provider_count}"))
    return "\n".join(lines)


def render_result(text: str) -> str:
    return text.rstrip()


def render_runtime_dashboard(
    data: dict[str, Any],
    section: str = "",
) -> str:
    """Render responsive cards from an authoritative Runtime snapshot."""
    runtime = data.get("runtime") or {}
    runtime_data = runtime.get("data") or {}
    health = data.get("health") or {}
    metrics = (data.get("metrics") or {}).get("runtime") or {}
    scheduler = data.get("scheduler") or {}
    missions = list(data.get("missions") or ())
    nodes = list(data.get("nodes") or ())
    alerts = list(data.get("alerts") or ())
    providers = list(data.get("providers") or ())
    running = sum(
        1 for item in missions if str(item.get("status", "")).upper() == "RUNNING"
    )
    paused = sum(
        1 for item in missions if str(item.get("status", "")).upper() == "PAUSED"
    )
    queued = max(0, len(missions) - running - paused)
    provider_count = (
        len(providers)
        if providers
        else int(runtime.get("providers", runtime_data.get("providers", 0)) or 0)
    )
    version = runtime.get("version", runtime_data.get("version", "Unknown"))
    workspace = runtime.get("workspace", runtime_data.get("workspace", "Not selected"))
    sections: OrderedDict[str, tuple[tuple[str, Any], ...]] = OrderedDict(
        (
            (
                "runtime",
                (
                    ("Authority", "server" if data.get("server_authoritative") else "local"),
                    ("Status", "Online" if health.get("ok", True) else "Degraded"),
                    ("Version", version),
                    ("Uptime", runtime.get("uptime", runtime.get("uptime_seconds", "Unknown"))),
                ),
            ),
            (
                "scheduler",
                (
                    ("Policy", scheduler.get("policy", "Governed")),
                    ("Running", running),
                    ("Paused", paused),
                ),
            ),
            (
                "memory",
                (
                    ("Resident", f"{metrics.get('memory_mb', 0)} MB"),
                    ("Context", metrics.get("context_state", "Ready")),
                ),
            ),
            ("events", (("Alerts", len(alerts)), ("Latest", data.get("latest_event", "None")))),
            ("providers", (("Configured", provider_count), ("Connection", data.get("connection", "Local")))),
            ("workspace", (("Path", workspace or "Not selected"),
                    ("Nodes", f"{sum(1 for node in nodes if node.get('online'))}/{len(nodes)} online"))),
            (
                "performance",
                (
                    ("Latency p95", metrics.get("latency_p95_ms", "Unavailable")),
                    ("Rendering", "Incremental"),
                ),
            ),
            (
                "queue",
                (
                    ("Queued", queued),
                    ("Visible", len(missions)),
                    ("Current", str(missions[0].get("run_id") or missions[0].get("task_id") or "None") if missions else "None"),
                ),
            ),
        )
    )
    selected = section.lower().strip()
    if selected and selected not in sections:
        choices = "|".join(sections)
        return f"Usage: /dashboard [{choices}]"
    visible = [(selected, sections[selected])] if selected else list(sections.items())
    width = _term_width()
    card_width = width if width < 120 or selected else (width - 3) // 2
    cards = [_render_card(name.title(), rows, card_width) for name, rows in visible]
    lines = ["NOUS Runtime Dashboard", ""]
    if width >= 120 and not selected:
        for index in range(0, len(cards), 2):
            pair = cards[index : index + 2]
            left = pair[0]
            right = pair[1] if len(pair) == 2 else []
            height = max(len(left), len(right))
            for row in range(height):
                left_line = left[row] if row < len(left) else " " * card_width
                if right:
                    right_line = right[row] if row < len(right) else " " * card_width
                    lines.append(_pad_display(left_line, card_width) + "   " + right_line)
                else:
                    lines.append(left_line)
            if index + 2 < len(cards):
                lines.append("")
    else:
        for index, card in enumerate(cards):
            if index:
                lines.append("")
            lines.extend(card)
    if not selected:
        lines.extend(("", "Use /dashboard <section> for a focused view."))
    return "\n".join(lines)


def render_command_suggestions(
    items: Sequence[CompletionItem],
    *,
    selected: int = 0,
    width: int | None = None,
    limit: int = 8,
) -> str:
    """Render a bounded completion palette without printing command lists."""
    visible = list(items[: max(1, limit)])
    if not visible:
        return ""
    selected = max(0, min(selected, len(visible) - 1))
    width = width or _term_width()
    groups = {item.group for item in visible}
    heading = next(iter(groups)) if len(groups) == 1 else "Commands"
    label_width = min(18, max(_display_width(item.label) for item in visible) + 2)
    lines = [f" {heading}", ""]
    for index, item in enumerate(visible):
        marker = "›" if index == selected else " "
        label = f" {marker} {item.label:<{label_width}}"
        available = max(8, width - _display_width(label) - 2)
        row = label + _truncate_display(item.description, available)
        lines.append(_style(row, "selection") if index == selected else row)
    return "\n".join(lines)


def render_runtime_activity(items: Sequence[ActivityItem]) -> str:
    """Render a compact activity stream separate from conversation content."""
    completed = sum(1 for item in items if item.state == "success")
    active = [item for item in items if item.state != "success"][-4:]
    lines = ["Runtime"]
    if not items:
        lines.append("  Idle")
        return "\n".join(lines)
    if completed and not active:
        detail = f"{completed} step{'s' if completed != 1 else ''}"
        lines.append(_activity_line(ActivityItem("Finished", "success", detail)))
        return "\n".join(lines)
    if completed:
        lines.append(_activity_line(ActivityItem("Completed", "success", str(completed))))
    lines.extend(_activity_line(item) for item in active)
    return "\n".join(lines)


def render_status_bar(status: dict[str, Any] | None = None) -> str:
    """Render permanent keyboard help and bounded control-plane context."""
    values = status or {}
    width = _term_width()
    primary = "TAB Complete   CTRL+C Cancel   CTRL+D Exit   F1 Help"
    secondary = (
        "CTRL+F Search   CTRL+R Tasks   CTRL+P Palette   CTRL+O Details"
    )
    if width < 80:
        primary = "TAB Complete  ^C Cancel  ^D Exit  F1 Help"
        secondary = "^F Search  ^R Tasks  ^P Palette  ^O Details"
    provider = str(values.get("provider") or "Not configured")
    connection = str(values.get("connection") or "offline").lower()
    if provider.lower() in {"none", "not configured"}:
        readiness = "Not configured"
    elif connection in {"online", "ready"}:
        readiness = "Ready"
    else:
        readiness = "Offline"
    focus = _middle_ellipsis(str(values.get("focus") or "None"), max(12, width // 3))
    control = (
        f"Provider {readiness}   Focus {focus}   "
        f"Approval {values.get('approval_mode') or 'strict'}"
    )
    modes = (
        f"JSON {'on' if values.get('json') else 'off'}   "
        f"Quiet {'on' if values.get('quiet') else 'off'}"
    )
    return "\n".join(
        _style(_truncate_display(line, width), "neutral")
        for line in (primary, secondary, control, modes)
    )

def render_terminal_footer(
    raw: str = "",
    *,
    activities: Sequence[ActivityItem] = (),
    status: dict[str, Any] | None = None,
    disabled: bool = False,
    cursor: int | None = None,
    return_cursor_column: bool = False,
) -> tuple[list[str], int] | tuple[list[str], int, int]:
    """Build stable Runtime, Input, and Status regions for the current width."""
    width = _term_width()
    cursor = len(raw) if cursor is None else max(0, min(cursor, len(raw)))
    activity_lines = render_runtime_activity(activities).splitlines()
    label = "Message · running" if disabled else "Message"

    if width >= 140:
        gap = 3
        input_width = max(72, int(width * 0.62))
        runtime_width = width - input_width - gap
        input_lines, input_cursor_line, input_cursor_column = _render_input_box(
            raw if not disabled else "",
            cursor if not disabled else 0,
            input_width,
            label,
        )
        height = max(len(input_lines), len(activity_lines))
        lines: list[str] = []
        for row in range(height):
            left = input_lines[row] if row < len(input_lines) else ""
            right = activity_lines[row] if row < len(activity_lines) else ""
            lines.append(
                _pad_display(left, input_width)
                + " " * gap
                + _truncate_display(right, runtime_width)
            )
        cursor_line = input_cursor_line
    else:
        input_lines, input_cursor_in_box, input_cursor_column = _render_input_box(
            raw if not disabled else "",
            cursor if not disabled else 0,
            width,
            label,
        )
        lines = [*activity_lines, "", *input_lines]
        cursor_line = len(activity_lines) + 1 + input_cursor_in_box

    lines.extend(("", *render_status_bar(status).splitlines()))
    if return_cursor_column:
        return lines, cursor_line, input_cursor_column
    return lines, cursor_line


def _render_input_box(
    raw: str,
    cursor: int,
    width: int,
    label: str,
) -> tuple[list[str], int, int]:
    """Render a bounded input viewport and report its cursor position."""
    width = max(40, width)
    if width < 56:
        divider = "─" * width
        available = max(1, width - _display_width(PROMPT))
        visible, offset = _input_view(raw, cursor, available)
        return [divider, label, PROMPT + visible, divider], 2, 2 + offset

    inner = width - 2
    title = f"─ {label} "
    top = "╭" + title + "─" * max(0, inner - _display_width(title)) + "╮"
    available = max(1, inner - 3 - _display_width(PROMPT))
    visible, offset = _input_view(raw, cursor, available)
    content = PROMPT + visible
    middle = "│ " + _pad_display(content, inner - 2) + " │"
    bottom = "╰" + "─" * inner + "╯"
    return [top, middle, bottom], 1, 2 + _display_width(PROMPT) + offset


def _input_view(raw: str, cursor: int, width: int) -> tuple[str, int]:
    if _display_width(raw) <= width:
        return raw, _display_width(raw[:cursor])
    left_budget = max(1, int(width * 0.65))
    right_budget = max(1, width - left_budget)
    left, left_clipped = _take_suffix_display(raw[:cursor], left_budget)
    right, right_clipped = _take_prefix_display(raw[cursor:], right_budget)
    if left_clipped:
        left = "…" + _take_suffix_display(left, max(1, left_budget - 1))[0]
    if right_clipped:
        right = _take_prefix_display(right, max(1, right_budget - 1))[0] + "…"
    visible = _truncate_display(left + right, width)
    return visible, min(_display_width(left), width)


def _render_card(
    title: str,
    rows: Sequence[tuple[str, Any]],
    width: int,
) -> list[str]:
    width = max(32, width)
    inner = width - 2
    title_text = f"─ {title} "
    lines = ["╭" + title_text + "─" * max(0, inner - _display_width(title_text)) + "╮"]
    for label, value in rows:
        label_width = 12 if label in {"Authority", "Version", "Nodes"} else 15
        content = f"{label:<{label_width}}{value}"
        lines.append("│ " + _pad_display(_truncate_display(content, inner - 2), inner - 2) + " │")
    lines.append("╰" + "─" * inner + "╯")
    return lines


class RuntimeActivityPanel:
    """Incrementally redraw the transient Activity/Input/Status region."""

    def __init__(self, status: dict[str, Any] | None = None) -> None:
        self.status = dict(status or {})
        self._items: OrderedDict[str, ActivityItem] = OrderedDict()
        self._lines = 0

    def update(self, name: str, state: str, detail: str = "") -> None:
        normalized = state if state in _ACTIVITY_ICONS else "pending"
        self._items[name] = ActivityItem(name, normalized, detail)
        self.draw()

    def draw(self) -> None:
        lines, _ = render_terminal_footer(
            activities=tuple(self._items.values()),
            status=self.status,
            disabled=True,
        )
        if self._lines:
            _clear_rendered_region(self._lines, self._lines - 1)
        sys.stdout.write("\n".join(lines))
        sys.stdout.flush()
        self._lines = len(lines)

    def snapshot(self) -> tuple[ActivityItem, ...]:
        """Return the current presentation items without exposing mutable state."""
        return tuple(self._items.values())

    def clear(self) -> None:
        if self._lines:
            _clear_rendered_region(self._lines, self._lines - 1)
            sys.stdout.flush()
            self._lines = 0


def read_interactive_line(
    prompt: str,
    completer: Completer,
    *,
    history: Sequence[str] = (),
    status: dict[str, Any] | None = None,
    activities: Sequence[ActivityItem] = (),
    initial: str = "",
) -> str:
    """Read one editable line while preserving Activity, Input and Status regions."""
    if not _interactive_editor_supported():
        return input(prompt)

    buffer: list[str] = list(initial)
    cursor = len(buffer)
    selected = 0
    history_index = len(history)
    hidden = False
    previous_lines = 0
    previous_cursor_line = 0

    def current_items() -> list[CompletionItem]:
        if hidden:
            return []
        raw = "".join(buffer)
        return list(completer(raw)) if raw.startswith("/") else []

    def clear_frame() -> None:
        nonlocal previous_lines
        if not previous_lines:
            return
        _clear_rendered_region(previous_lines, previous_cursor_line)
        previous_lines = 0

    def draw() -> list[CompletionItem]:
        nonlocal previous_lines, previous_cursor_line, selected
        raw = "".join(buffer)
        items = current_items()
        selected = max(0, min(selected, max(0, len(items) - 1)))
        palette = render_command_suggestions(items, selected=selected)
        footer, footer_cursor, footer_column = render_terminal_footer(
            raw,
            activities=activities,
            status=status,
            cursor=cursor,
            return_cursor_column=True,
        )
        palette_lines = palette.splitlines() if palette else []
        frame = [*palette_lines, *footer]
        cursor_line = len(palette_lines) + footer_cursor
        cursor_column = footer_column
        clear_frame()
        sys.stdout.write("\n".join(frame))
        lines_below = len(frame) - 1 - cursor_line
        if lines_below:
            sys.stdout.write(f"\x1b[{lines_below}A")
        sys.stdout.write("\r")
        if cursor_column:
            sys.stdout.write(f"\x1b[{cursor_column}C")
        sys.stdout.flush()
        previous_lines = len(frame)
        previous_cursor_line = cursor_line
        return items

    def finish(raw: str) -> str:
        clear_frame()
        if raw.startswith("/"):
            sys.stdout.write(f"{PROMPT}{raw}\n")
        elif raw:
            sys.stdout.write(f"You\n{PROMPT}{raw}\n")
        else:
            sys.stdout.write("\n")
        sys.stdout.flush()
        return raw

    with _raw_input_mode():
        items = draw()
        while True:
            key = _read_key()
            raw = "".join(buffer)

            if key == "ENTER":
                if items:
                    candidate = items[selected].text
                    if candidate.rstrip() != raw.rstrip():
                        buffer[:] = list(candidate)
                        cursor = len(buffer)
                        selected = 0
                        hidden = False
                        items = draw()
                        continue
                return finish(raw)
            if key == "F1":
                return finish("/help")
            if key == "CTRL_R":
                return finish("/runs")
            if key == "CTRL_P":
                buffer[:] = list("/")
                cursor = len(buffer)
                hidden = False
                items = draw()
                continue
            if key == "CTRL_O":
                return finish("/inspect")
            if key == "CTRL_C":
                clear_frame()
                raise KeyboardInterrupt
            if key == "CTRL_D":
                if not buffer:
                    clear_frame()
                    raise EOFError
                continue
            if key == "CTRL_L":
                sys.stdout.write("\x1b[2J\x1b[H")
                previous_lines = 0
                items = draw()
                continue
            if key == "CTRL_F":
                buffer[:] = list("/logs ")
                cursor = len(buffer)
                selected = 0
                hidden = True
                items = draw()
                continue
            if key == "ESC":
                hidden = True
                items = draw()
                continue
            if key == "TAB":
                if items:
                    buffer[:] = list(items[selected].text)
                    cursor = len(buffer)
                    selected = 0
                    hidden = False
                    items = draw()
                continue
            if key in {"UP", "SHIFT_TAB"}:
                if items:
                    selected = (selected - 1) % len(items)
                elif history:
                    history_index = max(0, history_index - 1)
                    buffer[:] = list(history[history_index])
                    cursor = len(buffer)
                items = draw()
                continue
            if key == "DOWN":
                if items:
                    selected = (selected + 1) % len(items)
                elif history and history_index < len(history) - 1:
                    history_index += 1
                    buffer[:] = list(history[history_index])
                    cursor = len(buffer)
                elif history_index == len(history) - 1:
                    history_index = len(history)
                    buffer.clear()
                    cursor = 0
                items = draw()
                continue
            if key == "LEFT":
                cursor = max(0, cursor - 1)
                items = draw()
                continue
            if key == "RIGHT":
                if items and cursor == len(buffer):
                    buffer[:] = list(items[selected].text)
                    cursor = len(buffer)
                    selected = 0
                    hidden = False
                else:
                    cursor = min(len(buffer), cursor + 1)
                items = draw()
                continue
            if key == "HOME":
                cursor = 0
                items = draw()
                continue
            if key == "END":
                cursor = len(buffer)
                items = draw()
                continue
            if key == "BACKSPACE":
                if cursor:
                    del buffer[cursor - 1]
                    cursor -= 1
                    selected = 0
                    hidden = False
                items = draw()
                continue
            if len(key) == 1 and key.isprintable():
                buffer.insert(cursor, key)
                cursor += 1
                selected = 0
                hidden = False
                items = draw()

def read_approval_decision(
    request: dict[str, Any],
    proposal: dict[str, Any] | None = None,
    *,
    status: dict[str, Any] | None = None,
) -> str:
    """Read a human decision while keeping approval and input regions separate."""
    if not _interactive_editor_supported():
        return "dismiss"

    from nous_runtime.cli.execution_ui import render_approval_panel

    selected = 0
    details = False
    previous_lines = 0

    def clear_frame() -> None:
        nonlocal previous_lines
        if previous_lines:
            _clear_rendered_region(previous_lines, previous_lines - 1)
            previous_lines = 0

    def draw() -> None:
        nonlocal previous_lines
        panel = render_approval_panel(
            request,
            proposal,
            selected=selected,
            details=details,
        )
        footer, _ = render_terminal_footer(
            "",
            activities=(ActivityItem("Approval", "warning", "Decision required"),),
            status=status,
        )
        frame = [*panel.splitlines(), "", *footer]
        clear_frame()
        sys.stdout.write("\n".join(frame))
        sys.stdout.flush()
        previous_lines = len(frame)

    decisions = ("once", "session", "edit", "deny")
    with _raw_input_mode():
        draw()
        while True:
            key = _read_key()
            if key in {"UP", "SHIFT_TAB"}:
                selected = (selected - 1) % len(decisions)
                draw()
                continue
            if key in {"DOWN", "TAB"}:
                selected = (selected + 1) % len(decisions)
                draw()
                continue
            if key == "CTRL_O":
                details = not details
                draw()
                continue
            direct = {
                "1": "once", "Y": "once", "y": "once",
                "2": "session", "A": "session", "a": "session",
                "3": "edit", "E": "edit", "e": "edit",
                "4": "deny", "N": "deny", "n": "deny",
            }.get(key)
            if direct:
                clear_frame()
                return direct
            if key == "ENTER":
                clear_frame()
                return decisions[selected]
            if key in {"ESC", "CTRL_C"}:
                clear_frame()
                return "dismiss"
            if key == "CTRL_D":
                clear_frame()
                raise EOFError

def _build_status(
    workspace: str | None,
    raw: dict[str, Any],
) -> dict[str, str]:
    from nous_runtime.version import __version__

    workspace_path = raw.get("path") or workspace or raw.get("_workspace_path")
    if workspace_path:
        path = Path(str(workspace_path)).resolve()
        root = path.parent if path.name == ".nous" else path
    else:
        root = Path.cwd().resolve()
    project = root.name
    path_label = _middle_ellipsis(str(root), max(24, _term_width() - 12))

    def display_state(value: Any, default: str) -> str:
        text = str(value or default).replace("_", " ").strip()
        return text[:1].upper() + text[1:]

    provider = str(raw.get("provider") or "Not configured")
    if provider.lower() == "none":
        provider = "Not configured"
    model = str(raw.get("model") or "Not configured")
    if model.lower() == "none":
        model = "Not configured"
    return {
        "workspace": project or "Not selected",
        "session": display_state(raw.get("session"), "Active"),
        "runtime": display_state(raw.get("runtime_status"), "Ready"),
        "provider": provider,
        "model": model,
        "path": path_label,
        "version": str(raw.get("version") or __version__),
        "started": str(raw.get("started", datetime.now(timezone.utc).strftime("%H:%M"))),
    }


def _activity_line(item: ActivityItem) -> str:
    state = item.state if item.state in _ACTIVITY_ICONS else "pending"
    icon = _ACTIVITY_ICONS[state]
    role = {
        "running": "information",
        "success": "success",
        "warning": "warning",
        "failure": "failure",
        "pending": "neutral",
    }[state]
    detail = item.detail or {
        "pending": "Waiting",
        "running": "Running…",
        "success": "Done",
        "warning": "Attention",
        "failure": "Failed",
    }[state]
    return f"  {_style(icon, role)} {item.name:<14}{detail}"


def _style(text: str, role: str) -> str:
    if "NO_COLOR" in os.environ or not sys.stdout.isatty():
        return text
    code = _COLOR_CODES.get(role)
    return f"\x1b[{code}m{text}\x1b[0m" if code else text


def _clear_rendered_region(line_count: int, cursor_line: int) -> None:
    if line_count <= 0:
        return
    lines_below = line_count - 1 - cursor_line
    if lines_below:
        sys.stdout.write(f"\x1b[{lines_below}B")
    sys.stdout.write("\r\x1b[2K")
    for _ in range(line_count - 1):
        sys.stdout.write("\x1b[1A\r\x1b[2K")


def _term_width() -> int:
    try:
        return max(40, min(shutil.get_terminal_size().columns, 160))
    except OSError:
        return 80


def _display_width(text: str) -> int:
    width = 0
    in_escape = False
    for char in text:
        if char == "\x1b":
            in_escape = True
            continue
        if in_escape:
            if char == "m":
                in_escape = False
            continue
        if unicodedata.combining(char):
            continue
        width += 2 if unicodedata.east_asian_width(char) in {"W", "F"} else 1
    return width


def _pad_display(text: str, width: int) -> str:
    return text + " " * max(0, width - _display_width(text))


def _middle_ellipsis(text: str, width: int) -> str:
    if _display_width(text) <= width:
        return text
    side = max(4, (width - 1) // 2)
    left = _take_prefix_display(text, side)[0]
    right = _take_suffix_display(text, width - _display_width(left) - 1)[0]
    return left + "…" + right


def _take_prefix_display(text: str, width: int) -> tuple[str, bool]:
    result: list[str] = []
    used = 0
    for char in text:
        char_width = 0 if unicodedata.combining(char) else (
            2 if unicodedata.east_asian_width(char) in {"W", "F"} else 1
        )
        if used + char_width > width:
            return "".join(result), True
        result.append(char)
        used += char_width
    return "".join(result), False


def _take_suffix_display(text: str, width: int) -> tuple[str, bool]:
    result: list[str] = []
    used = 0
    for char in reversed(text):
        char_width = 0 if unicodedata.combining(char) else (
            2 if unicodedata.east_asian_width(char) in {"W", "F"} else 1
        )
        if used + char_width > width:
            return "".join(reversed(result)), True
        result.append(char)
        used += char_width
    return "".join(reversed(result)), False

def _truncate_display(text: str, width: int) -> str:
    if _display_width(text) <= width:
        return text
    result: list[str] = []
    used = 0
    for char in text:
        char_width = 0 if unicodedata.combining(char) else (
            2 if unicodedata.east_asian_width(char) in {"W", "F"} else 1
        )
        if used + char_width > max(0, width - 1):
            break
        result.append(char)
        used += char_width
    return "".join(result).rstrip() + "…"


def _interactive_editor_supported() -> bool:
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        return False
    if os.name == "nt":
        return _enable_windows_ansi()
    return os.environ.get("TERM", "").lower() != "dumb"


def _enable_windows_ansi() -> bool:
    try:
        import ctypes

        kernel32 = ctypes.windll.kernel32
        handle = kernel32.GetStdHandle(-11)
        mode = ctypes.c_uint()
        if not kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
            return False
        return bool(kernel32.SetConsoleMode(handle, mode.value | 0x0004))
    except (AttributeError, OSError):
        return False


@contextmanager
def _raw_input_mode() -> Iterator[None]:
    if os.name == "nt":
        yield
        return
    import termios
    import tty

    descriptor = sys.stdin.fileno()
    previous = termios.tcgetattr(descriptor)
    try:
        tty.setraw(descriptor)
        yield
    finally:
        termios.tcsetattr(descriptor, termios.TCSADRAIN, previous)


def _read_key() -> str:
    if os.name == "nt":
        import msvcrt

        char = msvcrt.getwch()
        if char in {"\x00", "\xe0"}:
            return {
                "H": "UP",
                "P": "DOWN",
                "K": "LEFT",
                "M": "RIGHT",
                "G": "HOME",
                "O": "END",
                "S": "DELETE",
                ";": "F1",
                "\x0f": "SHIFT_TAB",
            }.get(msvcrt.getwch(), "")
        return _map_character(char)

    import select

    char = sys.stdin.read(1)
    if char == "\x1b":
        sequence = ""
        while select.select([sys.stdin], [], [], 0.01)[0]:
            sequence += sys.stdin.read(1)
        return {
            "[A": "UP",
            "[B": "DOWN",
            "[C": "RIGHT",
            "[D": "LEFT",
            "[H": "HOME",
            "[F": "END",
            "[Z": "SHIFT_TAB",
            "OP": "F1",
            "OH": "HOME",
            "OF": "END",
        }.get(sequence, "ESC")
    return _map_character(char)


def _map_character(char: str) -> str:
    return {
        "\r": "ENTER",
        "\n": "ENTER",
        "\t": "TAB",
        "\x03": "CTRL_C",
        "\x04": "CTRL_D",
        "\x06": "CTRL_F",
        "\x0c": "CTRL_L",
        "\x0f": "CTRL_O",
        "\x10": "CTRL_P",
        "\x12": "CTRL_R",
        "\x1b": "ESC",
        "\x08": "BACKSPACE",
        "\x7f": "BACKSPACE",
    }.get(char, char)
