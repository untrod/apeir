"""Read-only Git tools executed through the existing process sandbox."""

from __future__ import annotations

import os
import re
import shlex
from pathlib import Path
from typing import Any, Mapping

from nous_runtime.agents.adapters.workspace_guard import WorkspaceGuard
from nous_runtime.capability.sandbox import ExecutionSandbox, SandboxConfig
from nous_runtime.execution.executables import resolve_executable
from nous_runtime.kernel.sandbox import ProcessSandbox, SandboxPolicy


_MAX_OUTPUT = 128 * 1024
_REVISION = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/@{}~^:+-]{0,199}$")


class GitToolRuntime:
    """Expose fixed read-only Git operations for one workspace."""

    def __init__(self, workspace: str | Path) -> None:
        self.guard = WorkspaceGuard(str(workspace))
        self.root = Path(self.guard.root)
        self.git = resolve_executable("git")
        self.sandbox_available = self._has_strong_sandbox()

    def specifications(self) -> tuple[dict[str, Any], ...]:
        if (
            not self.git
            or not self.sandbox_available
            or not (self.root / ".git").exists()
        ):
            return ()
        path = {"type": "string", "description": "Optional workspace-relative path"}
        return (
            _tool("git_status", "Show the read-only Git working tree status.", {}),
            _tool(
                "git_diff",
                "Show a read-only Git diff, optionally staged or path-scoped.",
                {"staged": {"type": "boolean"}, "path": path},
            ),
            _tool(
                "git_log",
                "Show recent Git commits without changing repository state.",
                {"max_count": {"type": "integer", "minimum": 1, "maximum": 50}},
            ),
            _tool("git_branch", "List local Git branches.", {}),
            _tool(
                "git_show",
                "Show one Git revision without changing repository state.",
                {"revision": {"type": "string"}, "path": path},
            ),
        )

    def execute(self, name: str, arguments: Mapping[str, Any]) -> dict[str, Any]:
        if not self.git:
            return {"ok": False, "error": "git executable is unavailable"}
        if not self.sandbox_available:
            return {"ok": False, "error": "strong process sandbox is unavailable"}
        if not (self.root / ".git").exists():
            return {"ok": False, "error": "workspace is not a Git repository"}
        handlers = {
            "git_status": self._status,
            "git_diff": self._diff,
            "git_log": self._log,
            "git_branch": self._branch,
            "git_show": self._show,
        }
        handler = handlers.get(str(name or ""))
        if handler is None:
            return {"ok": False, "error": f"unknown Git tool: {name}"}
        try:
            return handler(dict(arguments))
        except (OSError, RuntimeError, ValueError) as exc:
            return {"ok": False, "error": str(exc)}

    def _status(self, _arguments: dict[str, Any]) -> dict[str, Any]:
        return self._run(("status", "--short", "--branch"))

    def _diff(self, arguments: dict[str, Any]) -> dict[str, Any]:
        command = ["diff", "--no-ext-diff"]
        if bool(arguments.get("staged")):
            command.append("--cached")
        path = self._relative_path(arguments.get("path"))
        if path:
            command.extend(("--", path))
        return self._run(tuple(command))

    def _log(self, arguments: dict[str, Any]) -> dict[str, Any]:
        count = max(1, min(int(arguments.get("max_count") or 10), 50))
        return self._run(
            (
                "log",
                f"-{count}",
                "--date=iso-strict",
                "--pretty=format:%H%x09%ad%x09%an%x09%s",
            )
        )

    def _branch(self, _arguments: dict[str, Any]) -> dict[str, Any]:
        return self._run(("branch", "--list", "--format=%(refname:short)"))

    def _show(self, arguments: dict[str, Any]) -> dict[str, Any]:
        revision = str(arguments.get("revision") or "HEAD")
        if not _REVISION.fullmatch(revision) or revision.startswith("-"):
            raise ValueError("invalid Git revision")
        command = ["show", "--no-ext-diff", "--stat", "--oneline", revision]
        path = self._relative_path(arguments.get("path"))
        if path:
            command.extend(("--", path))
        return self._run(tuple(command))

    def _relative_path(self, value: Any) -> str:
        text = str(value or "").strip()
        if not text:
            return ""
        path = Path(self.guard.validate_path(text, allow_nonexistent=False))
        return path.relative_to(self.root).as_posix()

    def _run(self, arguments: tuple[str, ...]) -> dict[str, Any]:
        assert self.git is not None
        sandbox = ExecutionSandbox(
            SandboxConfig(
                workspace_root=str(self.root),
                allowed_commands=[Path(self.git).name],
                max_runtime_seconds=30,
                max_output_bytes=_MAX_OUTPUT,
                allow_network=False,
                isolation_level="strict",
            )
        )
        completed = sandbox.run(
            shlex.join((self.git, *arguments)),
            cwd=str(self.root),
            env=_safe_environment(),
        )
        return {
            "ok": completed.returncode == 0,
            "exit_code": completed.returncode,
            "stdout": completed.stdout[-_MAX_OUTPUT:],
            "stderr": completed.stderr[-_MAX_OUTPUT:],
        }

    def _has_strong_sandbox(self) -> bool:
        if not self.git:
            return False
        policy = SandboxPolicy(
            executable=self.git,
            args=["status", "--short"],
            working_dir=str(self.root),
            max_memory_bytes=256 * 1024 * 1024,
            max_cpu_time_seconds=30,
            max_output_bytes=_MAX_OUTPUT,
            timeout_seconds=30,
            read_allowed_paths=[str(self.root)],
            write_allowed_paths=[str(self.root)],
            network_allowed=False,
            isolation_level="strict",
            require_strong_isolation=True,
        )
        return bool(ProcessSandbox(policy).security_report()["strong"])


def _tool(name: str, description: str, properties: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": properties,
                "additionalProperties": False,
            },
        },
    }


def _safe_environment() -> dict[str, str]:
    allowed = {
        "PATH",
        "PATHEXT",
        "SYSTEMROOT",
        "WINDIR",
        "TEMP",
        "TMP",
        "LANG",
        "LC_ALL",
    }
    return {key: value for key, value in os.environ.items() if key.upper() in allowed}


__all__ = ["GitToolRuntime"]
