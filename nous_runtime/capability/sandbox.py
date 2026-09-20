# -*- coding: utf-8 -*-
"""
Compatibility execution sandbox for APEIR Distribution.

Direct subprocess execution is a compatibility boundary, not Kernel authority.
Governed side-effect operations must use an NKI WorkloadSpec with explicit
capability requirements and fail closed when strong isolation is unavailable.

Implements §9.4 of the master plan. Provides workspace-bounded,
resource-limited, command-whitelisted execution environment for
capability invocations.

Design: Models and agents must not get unrestricted shell access.
All commands go through the sandbox which enforces:
- Workspace boundaries (chroot-like)
- Command whitelist
- Resource limits (CPU, memory, time, filesystem)
- Network restrictions
- Process limits
- Secret isolation
"""

from __future__ import annotations

import logging
import os
import shlex
import shutil
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from nous_runtime.compat.ids import make_id
from nous_runtime.execution.executables import resolve_executable

log = logging.getLogger("nous.capability.sandbox")


@dataclass
class SandboxConfig:
    """Configuration for a sandboxed execution environment."""

    # Workspace
    workspace_root: str = ""  # All operations restricted under this path
    allow_temp_dir: bool = True  # Allow temp directory access

    # Command
    allowed_commands: list[str] = field(
        default_factory=lambda: [
            "python",
            "python3",
            "pytest",
            "git",
            "npm",
            "node",
            "cargo",
            "go",
            "make",
            "cmake",
            "ls",
            "dir",
            "cat",
            "grep",
            "find",
            "wc",
            "head",
            "tail",
            "echo",
            "pwd",
        ]
    )
    denied_commands: list[str] = field(
        default_factory=lambda: [
            "rm",
            "rmdir",
            "del",
            "format",
            "mkfs",
            "dd",
            "shred",
            "chmod",
            "chown",
            "sudo",
            "su",
        ]
    )

    # Resource limits
    max_runtime_seconds: int = 300
    max_memory_mb: int = 1024
    max_output_bytes: int = 1_000_000
    max_processes: int = 10

    # Network
    allow_network: bool = False
    allowed_hosts: list[str] = field(default_factory=list)

    # Filesystem
    readonly_paths: list[str] = field(default_factory=list)
    denied_paths: list[str] = field(
        default_factory=lambda: [
            "/etc/passwd",
            "/etc/shadow",
            "~/.ssh",
            "~/.aws",
        ]
    )

    # Secrets
    secret_env_vars: list[str] = field(default_factory=list)

    # Governed execution is always fail-closed on a strong isolation backend.
    isolation_level: str = "strict"


@dataclass
class SandboxResult:
    """Result of sandboxed execution."""

    ok: bool = False
    stdout: str = ""
    stderr: str = ""
    returncode: int = -1
    runtime_seconds: float = 0.0
    memory_used_mb: float = 0.0
    limit_exceeded: str = ""  # Which limit was hit, if any
    availability_state: str = "available"
    security_grade: str = "unknown"
    enforced_controls: tuple[str, ...] = ()
    unenforced_controls: tuple[str, ...] = ()
    sandbox_id: str = field(default_factory=lambda: make_id(prefix="sbx"))
    executed_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


class ExecutionSandbox:
    """Secure execution environment for capability operations.

    Usage:
        sandbox = ExecutionSandbox(SandboxConfig(workspace_root="/workspace"))
        result = sandbox.run("python -m pytest tests/")
    """

    def __init__(self, config: SandboxConfig | None = None):
        self._config = config or SandboxConfig()
        self._lock = threading.RLock()
        self._execution_count = 0

    def run(
        self, command: str, env: dict[str, str] | None = None, cwd: str = ""
    ) -> SandboxResult:
        """Execute a command within the sandbox constraints."""

        # 1. Validate command
        cmd_parts = shlex.split(command)
        if not cmd_parts:
            return SandboxResult(ok=False, stderr="Empty command")

        executable = os.path.basename(cmd_parts[0])
        executable_names = {
            executable.casefold(),
            os.path.splitext(executable)[0].casefold(),
        }
        denied = {item.casefold() for item in self._config.denied_commands}
        allowed = {item.casefold() for item in self._config.allowed_commands}
        if executable_names & denied:
            return SandboxResult(
                ok=False,
                stderr=f"Command '{executable}' is denied by sandbox policy",
            )

        if not executable_names & allowed:
            return SandboxResult(
                ok=False,
                stderr=f"Command '{executable}' is not in the allowed list. "
                f"Allowed: {', '.join(self._config.allowed_commands[:10])}...",
            )

        # 2. Validate paths
        if cwd and self._config.workspace_root:
            if not self._is_under_workspace(cwd):
                return SandboxResult(
                    ok=False, stderr=f"cwd '{cwd}' is outside workspace"
                )

        # Only explicit values may cross the host/guest boundary.
        exec_env = dict(env or {})
        for secret_var in self._config.secret_env_vars:
            exec_env.pop(secret_var, None)

        # 4. Execute only through the strong ProcessSandbox backend.
        start = datetime.now(timezone.utc)
        result = self._run_strict(command, exec_env, cwd)

        result.runtime_seconds = (datetime.now(timezone.utc) - start).total_seconds()

        with self._lock:
            self._execution_count += 1

        return result

    def _run_strict(self, command: str, exec_env: dict, cwd: str) -> SandboxResult:
        """Execute through ProcessSandbox using an argument array, never a shell."""
        from nous_runtime.kernel.sandbox import ProcessSandbox, SandboxPolicy
        import shlex

        result = SandboxResult()
        try:
            tokens = shlex.split(command)
            if not tokens:
                result.stderr = "Empty command"
                result.returncode = -1
                return result
            executable = resolve_executable(tokens[0])
            if not executable:
                result.stderr = f"Executable not found: {tokens[0]}"
                result.returncode = -1
                return result
            args_list = tokens[1:] if len(tokens) > 1 else []

            policy = SandboxPolicy(
                executable=executable,
                args=args_list,
                working_dir=cwd or self._config.workspace_root,
                env={
                    k: v for k, v in exec_env.items() if not k.startswith("NOUS_SECRET")
                },
                max_memory_bytes=getattr(self._config, "max_memory_mb", 256)
                * 1024
                * 1024,
                max_cpu_time_seconds=int(self._config.max_runtime_seconds or 30),
                max_output_bytes=self._config.max_output_bytes,
                timeout_seconds=self._config.max_runtime_seconds or 30.0,
                read_allowed_paths=[cwd or self._config.workspace_root],
                write_allowed_paths=[cwd or self._config.workspace_root],
                network_allowed=self._config.allow_network,
                isolation_level="strict",
                require_strong_isolation=True,
            )

            sandbox = ProcessSandbox(policy)
            new_result = sandbox.run()

            result.ok = new_result.success
            result.returncode = new_result.exit_code
            result.stdout = new_result.stdout
            result.stderr = new_result.stderr
            result.availability_state = new_result.availability_state
            result.security_grade = new_result.security_grade
            result.enforced_controls = new_result.enforced_controls
            result.unenforced_controls = new_result.unenforced_controls
            result.limit_exceeded = (
                "max_output_bytes"
                if new_result.output_truncated
                else "max_runtime_seconds"
                if new_result.timed_out
                else ""
            )
        except Exception as exc:
            log.warning("ProcessSandbox execution failed closed: %s", exc)
            result.stderr = f"Sandbox execution error: {exc}"
            result.returncode = -1

        return result

    def run_capability(self, capability_id: str, args: dict[str, Any]) -> SandboxResult:
        """Execute a capability within the sandbox."""
        command = args.get("command", "")
        cwd = args.get("cwd", self._config.workspace_root)
        env = args.get("env")
        return self.run(command, env=env, cwd=cwd)

    @property
    def config(self) -> SandboxConfig:
        return self._config

    @property
    def execution_count(self) -> int:
        with self._lock:
            return self._execution_count

    def _is_under_workspace(self, path: str) -> bool:
        if not self._config.workspace_root:
            return True
        abs_path = os.path.realpath(path)
        abs_root = os.path.realpath(self._config.workspace_root)
        try:
            return os.path.commonpath([abs_path, abs_root]) == abs_root
        except ValueError:
            return False

    @staticmethod
    def for_workspace(workspace_root: str) -> "ExecutionSandbox":
        """Create a sandbox for a specific workspace."""
        return ExecutionSandbox(
            SandboxConfig(
                workspace_root=workspace_root,
                allow_network=False,
            )
        )

    @staticmethod
    def for_testing(workspace_root: str) -> "ExecutionSandbox":
        """Create a sandbox suitable for running tests."""
        return ExecutionSandbox(
            SandboxConfig(
                workspace_root=workspace_root,
                allowed_commands=["python", "python3", "pytest", "git"],
                max_runtime_seconds=600,
                max_memory_mb=4096,
            )
        )


def run_process_strict(
    argv: list[str],
    *,
    cwd: str = "",
    timeout_seconds: int = 30,
    max_output_bytes: int = 1_000_000,
) -> SandboxResult:
    """Run an authorized argv array through ProcessSandbox without a shell."""
    if not argv or not str(argv[0]).strip():
        return SandboxResult(ok=False, stderr="Empty command", returncode=-1)
    executable = resolve_executable(str(argv[0]))
    if not executable:
        return SandboxResult(
            ok=False,
            stderr=f"Executable not found: {argv[0]}",
            returncode=-1,
        )

    from nous_runtime.kernel.sandbox import ProcessSandbox, SandboxPolicy

    workspace = os.path.abspath(cwd or os.getcwd())
    policy = SandboxPolicy(
        executable=executable,
        args=[str(argument) for argument in argv[1:]],
        working_dir=workspace,
        max_cpu_time_seconds=max(1, int(timeout_seconds)),
        max_output_bytes=max(1, int(max_output_bytes)),
        timeout_seconds=max(1, int(timeout_seconds)),
        read_allowed_paths=[workspace],
        write_allowed_paths=[workspace],
        network_allowed=False,
        isolation_level="strict",
        require_strong_isolation=True,
    )
    result = ProcessSandbox(policy).run()
    return SandboxResult(
        ok=result.success,
        stdout=result.stdout,
        stderr=result.stderr,
        returncode=result.exit_code,
        runtime_seconds=result.wall_time_seconds,
        memory_used_mb=result.peak_memory_bytes / (1024 * 1024),
        limit_exceeded=(
            "max_output_bytes"
            if result.output_truncated
            else "max_runtime_seconds"
            if result.timed_out
            else ""
        ),
        availability_state=result.availability_state,
        security_grade=result.security_grade,
        enforced_controls=result.enforced_controls,
        unenforced_controls=result.unenforced_controls,
    )


def run_shell_command_strict(
    command: str,
    *,
    cwd: str = "",
    timeout_seconds: int = 30,
    max_output_bytes: int = 1_000_000,
) -> SandboxResult:
    """Run an explicitly authorized shell command through ProcessSandbox.

    The shell is launched as an argv array inside strong isolation.
    Authorization remains the caller's responsibility because
    this helper is also used behind the Remote Agent's signed-command boundary.
    """
    if not str(command).strip():
        return SandboxResult(ok=False, stderr="Empty command", returncode=-1)

    if os.name == "nt":
        executable = shutil.which("powershell") or shutil.which("pwsh")
        arguments = ["-NoProfile", "-NonInteractive", "-Command", command]
    else:
        executable = shutil.which("sh")
        arguments = ["-c", command]
    if not executable:
        return SandboxResult(
            ok=False,
            stderr="A supported system shell is not available",
            returncode=-1,
        )

    workspace = os.path.abspath(cwd or os.getcwd())
    sandbox = ExecutionSandbox(
        SandboxConfig(
            workspace_root=workspace,
            allowed_commands=[os.path.basename(executable)],
            max_runtime_seconds=max(1, int(timeout_seconds)),
            max_output_bytes=max(1, int(max_output_bytes)),
            allow_network=False,
            isolation_level="strict",
        )
    )
    argv = shlex.join([executable, *arguments])
    return sandbox.run(argv, cwd=workspace)
