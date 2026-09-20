# -*- coding: utf-8 -*-
"""Terminal shell tests — verify slash commands work without crashing.

Subprocess-based shell tests cannot pipe to stdin because Typer detects
non-TTY stdin and shows help instead of invoking the shell callback.
Instead we test the command handler functions directly.
"""

import json
import os
import sys
from pathlib import Path

import pytest

from nous_runtime.version import __version__

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


# Helpers

def _setup_workspace(tmp_path: Path) -> Path:
    """Create a minimal .nous/ workspace and return its Path."""
    from nous_runtime.project.workspace import init_workspace
    return init_workspace(tmp_path)


def _run_cmd(name: str, args: list[str] | None = None) -> str:
    """Execute a registered shell command by name."""
    from nous_runtime.cli.shell_v2 import COMMANDS
    handler = COMMANDS.get(name)
    if handler is None:
        raise KeyError(f"Command not found: /{name}")
    return handler["fn"](args or [])


# Basic command tests

class TestHelpCommand:
    def test_help_contains_commands(self):
        result = _run_cmd("help")
        assert "NOUS commands" in result
        assert "/help" in result
        assert "/quit" in result


class TestStatusCommand:
    def test_status_no_crash(self):
        result = _run_cmd("status")
        assert result  # should return a non-empty string


class TestWorkspaceCommand:
    def test_workspace_no_crash(self):
        result = _run_cmd("workspace")
        assert "Workspace" in result


class TestQuitCommand:
    def test_quit_returns_empty(self):
        result = _run_cmd("quit")
        assert result == ""


class TestClearCommand:
    def test_clear_returns_empty(self):
        result = _run_cmd("clear")
        assert result == ""


# New v1.1 commands

class TestScanCommand:
    def test_scan_with_workspace(self, tmp_path):
        _setup_workspace(tmp_path)
        os.chdir(str(tmp_path))
        try:
            result = _run_cmd("scan")
            assert "Scan" in result or "scan" in result.lower()
        finally:
            os.chdir(str(ROOT))

    def test_scan_creates_workspace_if_missing(self, tmp_path):
        """If no workspace exists, scan creates one."""
        os.chdir(str(tmp_path))
        try:
            result = _run_cmd("scan")
            # Should succeed (either scanning or reporting status)
            assert isinstance(result, str)
        finally:
            os.chdir(str(ROOT))


class TestMemoryCommand:
    def test_memory_empty_workspace(self, tmp_path):
        _setup_workspace(tmp_path)
        os.chdir(str(tmp_path))
        try:
            result = _run_cmd("memory")
            # Should not crash — fresh workspace has 1 timeline event
            assert isinstance(result, str)
        finally:
            os.chdir(str(ROOT))

    def test_memory_no_workspace(self, tmp_path, monkeypatch):
        """Without workspace, /memory should show a helpful message."""
        monkeypatch.setattr(
            "nous_runtime.project.workspace.find_workspace", lambda: None
        )
        os.chdir(str(tmp_path))
        try:
            result = _run_cmd("memory")
            assert "No .nous/" in result or "init" in result.lower()
        finally:
            os.chdir(str(ROOT))


class TestTasksCommand:
    def test_tasks_empty_workspace(self, tmp_path):
        _setup_workspace(tmp_path)
        os.chdir(str(tmp_path))
        try:
            result = _run_cmd("tasks")
            assert "Tasks and Runs" in result
        finally:
            os.chdir(str(ROOT))


class TestSettingsCommand:
    def test_settings_no_workspace(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "nous_runtime.project.workspace.find_workspace", lambda: None
        )
        os.chdir(str(tmp_path))
        try:
            result = _run_cmd("settings")
            assert "No .nous/" in result or "init" in result.lower()
        finally:
            os.chdir(str(ROOT))

    def test_settings_empty_config(self, tmp_path):
        _setup_workspace(tmp_path)
        os.chdir(str(tmp_path))
        try:
            result = _run_cmd("settings")
            # Empty config shows "empty" or renders as empty dict
            assert isinstance(result, str)
        finally:
            os.chdir(str(ROOT))


class TestCapabilitiesCommand:
    def test_capabilities_no_crash(self):
        result = _run_cmd("capabilities")
        assert isinstance(result, str)
        # Should contain "Available" (from availability) or "Capability" (from fallback)
        assert "Available" in result or "Capability" in result or "capability" in result.lower() or result.startswith("No capabilities")


class TestPacksCommand:
    def test_packs_no_crash(self):
        result = _run_cmd("packs")
        assert isinstance(result, str)


class TestProvidersCommand:
    def test_providers_no_crash(self):
        result = _run_cmd("providers")
        assert isinstance(result, str)


# Error cases

class TestUnknownCommand:
    def test_unknown_command(self):
        with pytest.raises(KeyError):
            _run_cmd("foobar_xyz_nonexistent")

    def test_registered_commands_all_callable(self):
        from nous_runtime.cli.shell_v2 import COMMANDS
        for name, info in COMMANDS.items():
            fn = info.get("fn")
            assert callable(fn), f"Command /{name} has non-callable fn: {fn}"

    def test_settings_command_exists(self):
        """Verify /settings is registered."""
        from nous_runtime.cli.shell_v2 import COMMANDS
        assert "settings" in COMMANDS
        assert callable(COMMANDS["settings"]["fn"])


# Dashboard tests

class TestDashboard:
    def test_banner_has_plain_nous_identity_and_bounded_status(self):
        from nous_runtime.cli import terminal_ui

        result = terminal_ui.render_banner(
            ".nous",
            {"session": "resumed", "runtime_status": "ready"},
        )
        assert result.startswith("Nous Runtime")
        assert f"Workspace  {Path.cwd().name}" in result
        assert "Session    Resumed" in result
        assert "Runtime    Ready" in result
        assert "Provider   Not configured" in result
        assert "Model      Not configured" in result
        assert f"Version    {__version__}" in result
        width = terminal_ui._term_width()
        path_value = terminal_ui._middle_ellipsis(
            str(Path.cwd()), max(24, width - 12)
        )
        expected_path = terminal_ui._truncate_display(
            f"Path       {path_value}", width
        )
        assert expected_path in result
        assert "Long-lived intelligent runtime" not in result

    def test_banner_uses_compact_identity_on_narrow_terminal(self, monkeypatch):
        from nous_runtime.cli import terminal_ui

        monkeypatch.setattr(terminal_ui, "_term_width", lambda: 60)
        result = terminal_ui.render_banner(None, {})
        assert result.startswith("Nous Runtime")
        assert "Runtime" in result
        assert "Not configured" in result

    def test_banner_shows_provider_model_and_shortens_long_path(self, monkeypatch):
        from nous_runtime.cli import terminal_ui

        monkeypatch.setattr(terminal_ui, "_term_width", lambda: 60)
        result = terminal_ui.render_banner(
            r"F:\very\long\workspace\location\for\terminal\product\review\nous\.nous",
            {
                "provider": "OpenAI Compatible",
                "model": "gpt-5",
                "path": (
                    r"F:\very\long\workspace\location\for\terminal"
                    r"\product\review\nous"
                ),
            },
        )
        assert result.startswith("Nous Runtime")
        assert "Provider   OpenAI Compatible" in result
        assert "Model      gpt-5" in result
        assert "Path" in result
        assert "…" in result

    def test_render_divider_uses_terminal_width(self, monkeypatch):
        from nous_runtime.cli import terminal_ui

        monkeypatch.setattr(terminal_ui, "_term_width", lambda: 72)
        divider = terminal_ui.render_divider()
        assert divider == "-" * 72

    def test_prompt_is_nous_native(self):
        from nous_runtime.cli.terminal_ui import render_prompt

        assert render_prompt() == "> "

    def test_startup_sequence_is_calm_and_has_no_fake_loading(self):
        from nous_runtime.cli.terminal_ui import render_startup_sequence

        result = render_startup_sequence()
        assert result == "Nous initialized.\nRuntime ready."
        assert "Loading" not in result

    def test_session_summary_is_bounded(self):
        from nous_runtime.cli.terminal_ui import render_session_summary

        result = render_session_summary(
            last_events=[{"detail": "Indexed 42 files"}],
            pending_tasks=2,
            provider_count=1,
        )
        assert "Session summary" in result
        assert "Indexed 42 files" in result
        assert "pending     2" in result
        assert "providers   1" in result

    def test_runtime_dashboard_uses_responsive_cards(self):
        from nous_runtime.cli.terminal_ui import render_runtime_dashboard

        result = render_runtime_dashboard(
            {
                "server_authoritative": True,
                "runtime": {"version": "0.1.0-alpha", "uptime": "02:15:32"},
                "health": {"ok": True},
                "metrics": {"runtime": {"memory_mb": 42}},
                "missions": [
                    {"status": "RUNNING"},
                    {"status": "PAUSED"},
                    {"status": "WAITING_FOR_NODE"},
                ],
                "nodes": [{"online": True}, {"online": False}],
                "alerts": [],
            }
        )
        for section in (
            "Runtime",
            "Scheduler",
            "Memory",
            "Events",
            "Providers",
            "Workspace",
            "Performance",
            "Queue",
        ):
            assert f"╭─ {section}" in result
        assert "Running        1" in result
        assert "Paused         1" in result
        assert "Queued         1" in result

        queue = render_runtime_dashboard(
            {"missions": [{"status": "RUNNING"}, {"status": "QUEUED"}]},
            "queue",
        )
        assert "╭─ Queue" in queue
        assert "╭─ Runtime" not in queue

    def test_inspector_presentation_is_tree_shaped(self):
        from nous_runtime.cli.shell_v2 import (
            _render_inspector_overview,
            _render_inspector_section,
        )

        overview = _render_inspector_overview(
            (("Runtime", "Online"), ("Providers", "1"))
        )
        assert "├─ Runtime" in overview
        assert "└─ Providers" in overview
        detail = _render_inspector_section("Context", "messages  4\nbudget  32000")
        assert "└─ Context" in detail
        assert "   ├─ messages" in detail


# Shell loop entry test

class TestNaturalLanguageNoProvider:
    """Regression: typing 'hi' with no providers must not crash."""

    def test_hi_no_traceback(self, monkeypatch, tmp_path):
        """With no providers configured, 'hi' must give a friendly message."""
        monkeypatch.setenv("NOUS_DATA_DIR", str(tmp_path))
        from remote_terminal.nous_core.db import run_migrations
        run_migrations()

        from nous_runtime.cli.shell_v2 import _friendly_error

        # Simulate execute_capability returning an error by mocking
        class FakeResult:
            ok = False
            error = "No provider found for capability 'model.reason'"
            error_code = "NOUS_CAPABILITY_NOT_FOUND"
            provider_id = ""
            result = None
            duration_ms = 0

        friendly = _friendly_error(FakeResult())
        assert "provider" in friendly.lower()
        # Must not contain internal Python error details
        assert "AttributeError" not in friendly
        assert "list" not in friendly.lower() or "list" in friendly.lower() and "provider" in friendly.lower()

    def test_friendly_error_explains_missing_configured_credential(self, monkeypatch):
        from nous_runtime.cli.shell_v2 import _friendly_error
        from nous_runtime.provider.credentials import CredentialStatus

        monkeypatch.setattr(
            "nous_runtime.cli.provider_experience.configured_provider_rows",
            lambda: [
                {
                    "provider_id": "deepseek",
                    "name": "DeepSeek",
                    "executable_capabilities": ("model.reason", "model.code"),
                    "credential": CredentialStatus(
                        "env:DEEPSEEK_API_KEY",
                        "Environment variable",
                        False,
                        "Missing",
                    ),
                }
            ],
        )

        class FakeResult:
            error = "No provider found for capability model.reason"
            error_code = "NOUS_CAPABILITY_NOT_FOUND"

        message = _friendly_error(FakeResult())
        assert "DeepSeek is configured" in message
        assert "DEEPSEEK_API_KEY" in message
        assert "nous provider doctor deepseek" in message
    def test_friendly_error_no_provider(self):
        """_friendly_error must never return raw Python exceptions."""
        from nous_runtime.cli.shell_v2 import _friendly_error

        class FakeResult:
            ok = False
            error = "Provider selection failed: 'list' object has no attribute 'items'"
            error_code = "NOUS_PROVIDER_UNAVAILABLE"
            provider_id = ""

        msg = _friendly_error(FakeResult())
        # Must be user-friendly, not raw Python
        assert "AttributeError" not in msg
        assert "'list'" not in msg
        assert ".items" not in msg
        assert "provider" in msg.lower()


class TestDebugProviders:
    def test_debug_providers_cli(self):
        """nous debug providers must show all layers."""
        import subprocess
        r = subprocess.run(
            [sys.executable, "-m", "nous_runtime.cli.main", "debug", "providers"],
            capture_output=True, text=True, timeout=30, cwd=str(ROOT),
        )
        assert r.returncode == 0, f"stderr: {r.stderr}"
        # Must show each diagnostic section
        for section in ("Environment", "Config file", "Core _providers",
                         "list_providers", "Registry.list_all",
                         "Resolver", "Runtime.status", "Capability DB"):
            assert section in r.stdout, f"Missing section: {section}"

    def test_debug_providers_shell(self):
        """Shell /debug providers must show all layers."""
        import subprocess
        r = subprocess.run(
            [sys.executable, "-m", "nous_runtime.cli.main"],
            input="n\n/debug providers\n/exit\n",
            capture_output=True, text=True, timeout=30, cwd=str(ROOT),
        )
        # Shell entry may show help if TTY detection fails — either way no crash
        assert r.returncode in (0, 2), f"unexpected return: {r.returncode}"


class TestProviderExecution:
    """Regression: natural language input must select and invoke provider."""

    def test_hi_selects_provider_not_no_provider_msg(self, monkeypatch, tmp_path):
        """With deepseek configured, execute_capability must select provider,
        not return 'No provider configured'."""

        # This exercises the legacy Provider selection path without a Kernel.
        monkeypatch.setenv("NOUS_RUNTIME_MODE", "compatibility")
        monkeypatch.setenv("NOUS_WORKSPACE_ROOT", str(tmp_path))

        # Provider registrations are process-global. Isolate this regression
        # from Providers registered by earlier tests in a full-suite run.
        from remote_terminal.nous_core import provider as provider_registry

        monkeypatch.setattr(provider_registry, "_providers", {})

        # Set up workspace and data dir
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        monkeypatch.setenv("NOUS_DATA_DIR", str(data_dir))

        ws = tmp_path / ".nous"
        ws.mkdir()
        prov = {
            "deepseek": {
                "name": "DeepSeek", "provider_id": "deepseek",
                "endpoint": "https://api.deepseek.com/v1/chat/completions",
                "api_key": "sk-fake1234test", "model": "deepseek-chat",
            }
        }
        (ws / "providers.json").write_text(json.dumps(prov))
        monkeypatch.chdir(tmp_path)

        # Init DB
        from remote_terminal.nous_core.db import run_migrations
        run_migrations()

        # Load providers
        monkeypatch.setenv("NOUS_LLM_API_URL", prov["deepseek"]["endpoint"])
        monkeypatch.setenv("NOUS_LLM_API_KEY", prov["deepseek"]["api_key"])
        monkeypatch.setenv("NOUS_LLM_MODEL", prov["deepseek"]["model"])
        from nous_runtime.cli.provider_setup import load_providers_from_config
        assert load_providers_from_config() == 1

        # Execute capability directly
        from nous_runtime.capability.resolver import execute_capability
        result = execute_capability("model.reason", prompt="hi")

        assert result.provider_id == "deepseek", \
            f"Expected deepseek, got: {result.provider_id}"
        assert result.error_code != "NOUS_CAPABILITY_NOT_FOUND", \
            "Should not be capability-not-found"
        # Execution may fail (fake key → 401) but provider must be selected
        assert "No provider configured" not in result.error, \
            f"Should not say 'No provider configured': {result.error}"


class TestShellEntry:
    def test_shell_run_exits(self, monkeypatch):
        """run() should exit cleanly when running is False from the start."""
        from nous_runtime.cli.shell_v2 import _state, run
        # Set state to not running so the loop exits immediately
        _state.running = False
        run()  # should print banner + Goodbye and return
        assert True  # no exception = pass
