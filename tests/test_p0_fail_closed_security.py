from __future__ import annotations

import ast
import os
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

from nous_runtime.capability import sandbox as sandbox_module
from nous_runtime.compat import brain_exec


def _disable_remote_brain(monkeypatch) -> None:
    monkeypatch.setitem(
        sys.modules, "remote_terminal.brain", ModuleType("remote_terminal.brain")
    )


def test_strict_shell_helper_enforces_process_sandbox(monkeypatch, tmp_path) -> None:
    captured: dict = {}

    class FakeSandbox:
        def __init__(self, config) -> None:
            captured["config"] = config

        def run(self, command: str, *, cwd: str = ""):
            captured["command"] = command
            captured["cwd"] = cwd
            return SimpleNamespace(
                ok=True, stdout="ok", stderr="", returncode=0
            )

    shell_path = (
        r"C:WindowsSystem32WindowsPowerShell1.0powershell.exe"
        if os.name == "nt"
        else "/bin/sh"
    )
    monkeypatch.setattr(sandbox_module, "ExecutionSandbox", FakeSandbox)
    monkeypatch.setattr(
        sandbox_module.shutil,
        "which",
        lambda name: shell_path if name in {"powershell", "sh"} else None,
    )

    result = sandbox_module.run_shell_command_strict(
        "Get-Location", cwd=str(tmp_path), timeout_seconds=17
    )

    assert result.returncode == 0
    assert captured["config"].isolation_level == "strict"
    assert captured["config"].allow_network is False
    assert captured["config"].max_runtime_seconds == 17
    assert "Get-Location" in captured["command"]
    assert captured["cwd"] == str(tmp_path.resolve())


def test_compat_local_execution_is_disabled_by_default(monkeypatch) -> None:
    _disable_remote_brain(monkeypatch)
    monkeypatch.delenv("NOUS_ALLOW_LEGACY_DIRECT_EXEC", raising=False)

    output, returncode = brain_exec._exec_raw("whoami")

    assert returncode == -2
    assert "disabled" in output


def test_compat_local_execution_uses_strict_helper_when_opted_in(
    monkeypatch, tmp_path
) -> None:
    _disable_remote_brain(monkeypatch)
    monkeypatch.setenv("NOUS_ALLOW_LEGACY_DIRECT_EXEC", "1")
    monkeypatch.setattr(
        sandbox_module,
        "run_shell_command_strict",
        lambda command, **kwargs: SimpleNamespace(
            stdout=f"ran:{command}", stderr="", returncode=0
        ),
    )

    output, returncode = brain_exec._exec_raw(
        "whoami", cwd=str(tmp_path), timeout=11
    )

    assert returncode == 0
    assert output == "ran:whoami"


def test_remote_agent_has_no_direct_subprocess_execution() -> None:
    source = Path("remote_terminal/agent.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    run_command = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "run_command"
    )
    calls = {
        ast.unparse(node.func)
        for node in ast.walk(run_command)
        if isinstance(node, ast.Call)
    }
    assert "run_shell_command_strict" in calls
    assert not any(call.startswith("subprocess.") for call in calls)


def test_compat_brain_exec_has_no_python_shell_true_path() -> None:
    source = Path("nous_runtime/compat/brain_exec.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    exec_raw = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "_exec_raw"
    )
    calls = {
        ast.unparse(node.func)
        for node in ast.walk(exec_raw)
        if isinstance(node, ast.Call)
    }
    assert "subprocess.run" not in calls
    assert "get_gate" not in calls

def test_legacy_gateway_direct_execution_respects_runtime_mode(monkeypatch) -> None:
    from nous_runtime.model_runtime.compatibility import (
        _legacy_gateway_direct_allowed,
    )

    monkeypatch.setenv("NOUS_RUNTIME_MODE", "production")
    assert _legacy_gateway_direct_allowed() is False

    monkeypatch.setenv("NOUS_RUNTIME_MODE", "compatibility")
    assert _legacy_gateway_direct_allowed() is True
