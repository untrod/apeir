"""Focused product tests for the persistent Nous terminal."""

from __future__ import annotations

import json
import threading

from nous_runtime.cli.terminal_session import TerminalSession, fold_output, stream_chunks
from nous_runtime.conversation import ConversationMessage
from nous_runtime.events import EventStream, RunState


def test_terminal_session_persists_reconnects_and_searches(tmp_path):
    session = TerminalSession(
        tmp_path,
        workspace_id="workspace",
        owner_id="owner",
        active_window=4,
    )
    result = session.execute("你好 Nous", lambda text, cancel: f"received: {text}")
    assert result.status == "completed"
    assert result.content == "received: 你好 Nous"

    reconnected = TerminalSession(
        tmp_path,
        workspace_id="workspace",
        owner_id="owner",
        conversation_id=session.conversation_id,
        active_window=4,
    )
    history = reconnected.history_page()
    assert history["conversation_id"] == session.conversation_id
    assert any("你好" in item["content"] for item in history["messages"])
    matches = reconnected.search("received")
    assert len(matches["messages"]) == 1
    context = reconnected.context_snapshot()
    assert context["used_chars"] <= context["budget_chars"]


def test_terminal_session_recovers_interrupted_operation(tmp_path):
    session = TerminalSession(tmp_path, workspace_id="workspace", owner_id="owner")
    operation_id = "op_interrupted"
    session.store.append(
        ConversationMessage(
            session.conversation_id,
            "tool",
            json.dumps({"operation_id": operation_id, "state": "started"}),
            metadata={
                "terminal_operation_id": operation_id,
                "terminal_operation_state": "started",
            },
        )
    )

    recovered = TerminalSession(
        tmp_path,
        workspace_id="workspace",
        owner_id="owner",
        conversation_id=session.conversation_id,
    )
    assert recovered.recovered_operations == 1
    states = [
        item.metadata.get("terminal_operation_state")
        for item in recovered.store.history(recovered.conversation_id, limit=20)
    ]
    assert "interrupted" in states


def test_terminal_session_honors_cooperative_cancellation(tmp_path):
    session = TerminalSession(tmp_path, workspace_id="workspace", owner_id="owner")
    session.cancel_event.set()

    def executor(text: str, cancel: threading.Event) -> str:
        return "cancelled" if cancel.is_set() else text

    result = session.execute("work", executor)
    assert result.status == "completed"
    assert result.content == "work"


def test_terminal_folding_and_unicode_batches_are_bounded():
    code = "\n".join(f"line {index}" for index in range(40))
    folded = fold_output(f"before\n```python\n{code}\n```\nafter", max_code_lines=5)
    assert "35 code lines folded" in folded
    chunks = list(stream_chunks("你" * 200, chunk_chars=32))
    assert "".join(chunks) == "你" * 200
    assert max(map(len, chunks)) <= 32


def test_event_stream_reconstructs_and_controls_canonical_run(tmp_path):
    first = EventStream(str(tmp_path))
    first.create_run("run_terminal")
    first.emit_state_change("run_terminal", RunState.RUNNING)

    reconnected = EventStream(str(tmp_path))
    assert reconnected.get_run("run_terminal").state is RunState.RUNNING
    assert reconnected.control_run("run_terminal", "pause").state is RunState.PAUSED
    assert reconnected.control_run("run_terminal", "resume").state is RunState.RUNNING
    assert reconnected.control_run("run_terminal", "cancel").state is RunState.CANCELLED


def test_required_terminal_commands_are_registered():
    from nous_runtime.cli.shell_v2 import COMMANDS

    required = {
        "status",
        "runs",
        "run",
        "approve",
        "pause",
        "resume",
        "cancel",
        "dashboard",
        "inspect",
        "context",
        "files",
        "tests",
        "clear",
        "help",
        "quit",
    }
    assert required <= set(COMMANDS)


def test_slash_completion_progressively_reduces_candidates():
    from nous_runtime.cli.shell_v2 import _command_suggestions

    assert [item.label for item in _command_suggestions("/")] == [
        "/run",
        "/runs",
        "/tasks",
        "/approval",
        "/dashboard",
        "/status",
        "/inspect",
        "/provider",
    ]
    assert [item.label for item in _command_suggestions("/r")] == [
        "/run",
        "/runs",
        "/resume",
    ]
    assert [item.label for item in _command_suggestions("/ru")] == [
        "/run",
        "/runs",
    ]
    assert _command_suggestions("plain language") == []


def test_slash_completion_moves_from_command_to_arguments():
    from nous_runtime.cli.shell_v2 import _command_suggestions

    run_items = _command_suggestions("/run ")
    assert [item.text for item in run_items] == [
        "/run show ",
        "/run focus ",
    ]

    inspect_items = _command_suggestions("/inspect d")
    assert [item.text for item in inspect_items] == ["/inspect devices"]

    dashboard_items = _command_suggestions("/dashboard p")
    assert [item.text for item in dashboard_items] == [
        "/dashboard providers",
        "/dashboard performance",
    ]


def test_command_palette_is_bounded_and_keyboard_legible():
    from nous_runtime.cli.shell_v2 import _command_suggestions
    from nous_runtime.cli.terminal_ui import render_command_suggestions

    rendered = render_command_suggestions(_command_suggestions("/r"), selected=1)
    assert "Execution" in rendered
    assert "› /runs" in rendered
    assert "Recent executions" in rendered
    assert len([line for line in rendered.splitlines() if line.strip().startswith(("› /", "/"))]) <= 8


def test_interactive_reader_has_non_tty_fallback(monkeypatch):
    from nous_runtime.cli import terminal_ui

    monkeypatch.setattr(terminal_ui, "_interactive_editor_supported", lambda: False)
    monkeypatch.setattr("builtins.input", lambda prompt: "/status")
    assert (
        terminal_ui.read_interactive_line(
            "nous › ",
            lambda raw: [],
            activities=(terminal_ui.ActivityItem("Finished", "success"),),
        )
        == "/status"
    )

def test_windows_extended_keys_decode_for_navigation(monkeypatch):
    import os
    import sys
    from types import SimpleNamespace

    import pytest

    if os.name != "nt":
        pytest.skip("Windows console key encoding")

    from nous_runtime.cli import terminal_ui

    keys = iter(("\xe0", "H", "\x00", "\x0f", "\x00", ";"))
    monkeypatch.setitem(
        sys.modules,
        "msvcrt",
        SimpleNamespace(getwch=lambda: next(keys)),
    )
    assert terminal_ui._read_key() == "UP"
    assert terminal_ui._read_key() == "SHIFT_TAB"
    assert terminal_ui._read_key() == "F1"

def test_terminal_footer_has_five_region_controls():
    from nous_runtime.cli.terminal_ui import ActivityItem, render_terminal_footer

    lines, cursor_line = render_terminal_footer(
        "/r",
        activities=(ActivityItem("Planning", "running"),),
        status={
            "json": False,
            "quiet": False,
            "provider": "none",
            "connection": "offline",
        },
    )
    rendered = "\n".join(lines)
    assert lines[0] == "Runtime"
    assert "Planning" in rendered
    assert "╭─ Message" in rendered
    assert "> /r" in lines[cursor_line]
    for label in (
        "TAB Complete",
        "CTRL+C Cancel",
        "CTRL+D Exit",
        "CTRL+F Search",
        "F1 Help",
        "JSON off",
        "Quiet off",
        "Provider Not configured",
    ):
        assert label in rendered


def test_finished_activity_collapses_and_no_color_is_respected(monkeypatch):
    from nous_runtime.cli.terminal_ui import ActivityItem, render_runtime_activity

    monkeypatch.setenv("NO_COLOR", "1")
    rendered = render_runtime_activity(
        (
            ActivityItem("Planning", "success"),
            ActivityItem("Context", "success"),
            ActivityItem("Execution", "running"),
        )
    )
    assert "Completed" in rendered
    assert "2" in rendered
    assert "Execution" in rendered
    assert "Planning" not in rendered
    assert "\x1b[" not in rendered

def test_provider_completion_moves_into_contextual_arguments():
    from nous_runtime.cli.shell_v2 import _command_suggestions

    assert [item.text for item in _command_suggestions("/pro")] == ["/provider"]
    assert [item.text for item in _command_suggestions("/provider ")] == [
        "/provider list",
        "/provider add",
        "/provider quick",
        "/provider health",
        "/provider doctor",
        "/provider test",
        "/provider ping",
    ]
    assert [item.text for item in _command_suggestions("/provider t")] == [
        "/provider test"
    ]


def test_terminal_footer_is_responsive_and_keeps_input_bounded(monkeypatch):
    from nous_runtime.cli import terminal_ui

    activity = (terminal_ui.ActivityItem("Planning", "running"),)
    status = {"provider": "OpenAI", "connection": "ready"}

    monkeypatch.setattr(terminal_ui, "_term_width", lambda: 160)
    wide, wide_cursor = terminal_ui.render_terminal_footer(
        "你好",
        activities=activity,
        status=status,
    )
    assert "Message" in wide[0]
    assert "Runtime" in wide[0]
    assert "> 你好" in wide[wide_cursor]
    assert "Provider Ready" in "\n".join(wide)

    monkeypatch.setattr(terminal_ui, "_term_width", lambda: 100)
    standard, standard_cursor = terminal_ui.render_terminal_footer("hello")
    assert standard[0] == "Runtime"
    assert "╭─ Message" in "\n".join(standard)
    assert "> hello" in standard[standard_cursor]

    monkeypatch.setattr(terminal_ui, "_term_width", lambda: 60)
    compact, _ = terminal_ui.render_terminal_footer("x" * 100)
    assert max(terminal_ui._display_width(line) for line in compact) <= 60


def test_terminal_footer_reports_unicode_cursor_column(monkeypatch):
    from nous_runtime.cli import terminal_ui

    monkeypatch.setattr(terminal_ui, "_term_width", lambda: 100)
    lines, cursor_line, cursor_column = terminal_ui.render_terminal_footer(
        "你好",
        cursor=1,
        return_cursor_column=True,
    )
    assert "> 你好" in lines[cursor_line]
    assert cursor_column == 6


def test_cancelled_operation_does_not_pollute_conversation(tmp_path):
    session = TerminalSession(tmp_path, workspace_id="workspace", owner_id="owner")

    def cancel_during_execution(text: str, cancel: threading.Event) -> str:
        cancel.set()
        return f"late result: {text}"

    result = session.execute("cancel this", cancel_during_execution)
    assert result.status == "cancelled"
    assert result.content == ""
    history = session.store.history(session.conversation_id, limit=20)
    assistant_content = [item.content for item in history if item.role == "assistant"]
    assert not any("Operation cancelled" in content for content in assistant_content)


def test_activity_idle_finished_and_cancelled_are_concise():
    from nous_runtime.cli.terminal_ui import ActivityItem, render_runtime_activity

    assert render_runtime_activity(()) == "Runtime\n  Idle"
    finished = render_runtime_activity((ActivityItem("Planning", "success"),))
    assert "Finished" in finished
    assert "pending" not in finished
    cancelled = render_runtime_activity(
        (ActivityItem("Operation", "warning", "Cancelled"),)
    )
    assert "Cancelled" in cancelled
    assert cancelled.count("Cancelled") == 1
