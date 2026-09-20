"""
ProcessSandbox — fail-closed, VM-isolated subprocess entry point.

Public run() requires an available strict backend unconditionally. The legacy
require_strong_isolation flag cannot enable ordinary host execution. Windows
uses a disposable, network-disabled VM with scoped mappings and bounded I/O.
Legacy resource-only helpers are not reachable fallbacks from run().

On the validated Windows 10 x64 backend, C3 certification assumes the host OS
and current local user are trusted. Guest business results remain untrusted
unless an independent verifier upgrades their receipt status.
"""

from __future__ import annotations

import logging
import os
import signal
import subprocess
import sys
import time
from dataclasses import dataclass, field
from typing import Optional

log = logging.getLogger("nous.kernel.sandbox")


# ────────────────────────────────────────────────────────────
# Sandbox configuration
# ────────────────────────────────────────────────────────────

@dataclass
class SandboxPolicy:
    """Defines what a sandboxed process is allowed to do.

    DEFAULT-DENY: everything is blocked unless explicitly allowed.
    """

    # ── Execution ──
    executable: str = ""                 # Absolute path to binary
    args: list[str] = field(default_factory=list)
    working_dir: str = ""                # Default: system temp
    env: dict[str, str] = field(default_factory=dict)

    # ── Resource limits ──
    max_memory_bytes: int = 256 * 1024 * 1024   # 256 MB default
    max_cpu_time_seconds: int = 60               # 60 seconds default
    max_processes: int = 1                        # No fork bombs
    max_output_bytes: int = 10 * 1024 * 1024     # 10 MB stdout+stderr
    max_staging_bytes: int = 512 * 1024 * 1024   # Immutable input snapshot
    max_staging_files: int = 100_000

    # ── Filesystem ──
    read_allowed_paths: list[str] = field(default_factory=list)
    write_allowed_paths: list[str] = field(default_factory=list)
    deny_paths: list[str] = field(default_factory=list)

    # ── Network ──
    network_allowed: bool = False         # Network disabled by default
    allowed_hosts: list[str] = field(default_factory=list)
    allowed_ports: list[int] = field(default_factory=list)

    # ── Behavior ──
    timeout_seconds: float = 30.0
    kill_timeout_seconds: float = 5.0     # SIGTERM → SIGKILL escalation
    audit: bool = True
    isolation_level: str = "strict"       # "strict" | "relaxed" | "none"
    require_strong_isolation: bool = True
    # Host-side cancellation marker; never relies on a live guest workspace mapping.
    cancel_file: str = ""

    def validate(self) -> list[str]:
        """Validate the policy. Returns list of issues (empty = valid)."""
        issues = []
        if not self.executable:
            issues.append("executable is required")
        elif not os.path.isabs(self.executable):
            issues.append(f"executable must be an absolute path: {self.executable}")
        if self.max_memory_bytes < 1024 * 1024:
            issues.append("max_memory_bytes must be at least 1 MB")
        if self.timeout_seconds <= 0:
            issues.append("timeout_seconds must be positive")
        if self.cancel_file and not os.path.isabs(self.cancel_file):
            issues.append("cancel_file must be absolute")
        if self.max_staging_bytes < 1 or self.max_staging_files < 1:
            issues.append("staging limits must be positive")
        if self.isolation_level not in ("strict", "relaxed", "none"):
            issues.append(f"unknown isolation_level: {self.isolation_level}")
        return issues


# ────────────────────────────────────────────────────────────
# Execution result
# ────────────────────────────────────────────────────────────

@dataclass
class SandboxResult:
    """Result of a sandboxed execution."""

    exit_code: int = -1
    stdout: str = ""
    stderr: str = ""
    stdout_bytes: int = 0
    stderr_bytes: int = 0
    wall_time_seconds: float = 0.0
    cpu_time_seconds: float = 0.0
    peak_memory_bytes: int = 0
    timed_out: bool = False
    memory_limit_hit: bool = False
    output_truncated: bool = False
    killed_by_signal: int = 0
    audit_id: str = ""
    availability_state: str = "available"
    security_grade: str = "unknown"
    enforced_controls: tuple[str, ...] = ()
    unenforced_controls: tuple[str, ...] = ()

    @property
    def success(self) -> bool:
        return self.exit_code == 0 and not self.timed_out and not self.memory_limit_hit


# ────────────────────────────────────────────────────────────
# Process Sandbox
# ────────────────────────────────────────────────────────────

class ProcessSandbox:
    """Execute a process under resource constraints and security policy.

    Windows strict execution uses Windows Sandbox. Other profiles/platforms
    fail closed until a strong backend is available; resource-only helpers
    cannot substitute for isolation.

    Usage:
        policy = SandboxPolicy(
            executable="/usr/bin/python",
            args=["-c", "print('hello')"],
            max_memory_bytes=128 * 1024 * 1024,
            timeout_seconds=10.0,
        )
        sandbox = ProcessSandbox(policy)
        result = sandbox.run()
        if result.success:
            print(result.stdout)
    """

    def __init__(self, policy: SandboxPolicy):
        issues = policy.validate()
        if issues:
            raise ValueError(f"Invalid sandbox policy: {'; '.join(issues)}")
        self.policy = policy
        self._audit_id = ""

    def run(self, input_bytes: bytes | None = None) -> SandboxResult:
        """Execute the process under sandbox constraints. Synchronous."""
        started = time.monotonic()
        security = self.security_report()
        if not security["strong"]:
            return SandboxResult(
                exit_code=-1,
                stderr=(
                    "STRICT_SANDBOX_UNAVAILABLE: the current backend does not "
                    "enforce filesystem, network, environment, and process-spawn boundaries"
                ),
                wall_time_seconds=time.monotonic() - started,
                availability_state="unavailable",
                security_grade=str(security["grade"]),
                enforced_controls=tuple(security["enforced_controls"]),
                unenforced_controls=tuple(security["unenforced_controls"]),
            )

        try:
            result = self._execute_strong_backend(input_bytes, started)
        except FileNotFoundError:
            return SandboxResult(
                exit_code=-1,
                stderr=f"Executable not found: {self.policy.executable}",
                wall_time_seconds=time.monotonic() - started,
                audit_id=self._audit_id,
            )
        except PermissionError:
            return SandboxResult(
                exit_code=-1,
                stderr=f"Permission denied: {self.policy.executable}",
                wall_time_seconds=time.monotonic() - started,
                audit_id=self._audit_id,
            )

        result.wall_time_seconds = time.monotonic() - started
        result.security_grade = str(security["grade"])
        result.enforced_controls = tuple(security["enforced_controls"])
        result.unenforced_controls = tuple(security["unenforced_controls"])

        if self.policy.audit:
            self._audit_log(result)

        return result

    def security_report(self) -> dict[str, object]:
        """Return conservative capabilities for the backend usable right now."""

        enforced = ["exec_array", "timeout", "captured_output", "output_limit"]
        if sys.platform == "win32" and self.policy.isolation_level == "strict":
            from nous_runtime.kernel.windows_sandbox import executable_path

            if executable_path() and not self.policy.network_allowed:
                return {
                    "grade": "strong_vm",
                    "strong": True,
                    "c3_certified": True,
                    "enforced_controls": tuple(
                        enforced
                        + [
                            "ephemeral_vm",
                            "filesystem_scope",
                            "network_disabled",
                            "host_environment_secrecy",
                            "process_boundary",
                            "job_memory_budget",
                            "job_cpu_budget",
                            "job_process_limit",
                            "process_tree_kill",
                            "staged_filesystem",
                            "guarded_write_commit",
                            "result_verification_label",
                            "clipboard_disabled",
                        ]
                    ),
                    "unenforced_controls": (),
                    "trust_assumptions": (
                        "host_os_and_local_user_trusted",
                        "business_result_requires_independent_verifier",
                    ),
                }
        grade = "soft_limits"
        if sys.platform in {"linux", "win32"}:
            grade = "resource_only"
            enforced.append("resource_limits_best_effort")
        return {
            "grade": grade,
            "strong": False,
            "enforced_controls": tuple(enforced),
            "unenforced_controls": (
                "filesystem_scope",
                "network_egress",
                "complete_environment_secrecy",
                "child_process_boundary",
                "symlink_escape",
            ),
        }

    def _build_environment(self) -> dict[str, str]:
        env = os.environ.copy()
        for key in list(env.keys()):
            if key.startswith(("NOUS_SECRET", "NOUS_TOKEN", "NOUS_KEY", "NOUS_CREDENTIAL")):
                env.pop(key, None)
        env.update(self.policy.env)
        env.pop("LD_PRELOAD", None)
        env.pop("LD_LIBRARY_PATH", None)
        if sys.platform == "darwin":
            env.pop("DYLD_INSERT_LIBRARIES", None)
            env.pop("DYLD_LIBRARY_PATH", None)
        if self.policy.read_allowed_paths:
            extra_ld = ":".join(
                path
                for path in self.policy.read_allowed_paths
                if os.path.isdir(path)
            )
            if extra_ld and "LD_LIBRARY_PATH" not in env:
                env["LD_LIBRARY_PATH"] = extra_ld
        return env

    def _execute_strong_backend(
        self, input_bytes: bytes | None, started: float
    ) -> SandboxResult:
        if sys.platform != "win32":
            return SandboxResult(
                exit_code=-1,
                stderr="STRICT_SANDBOX_UNAVAILABLE: no strong backend",
                availability_state="unavailable",
            )
        from nous_runtime.kernel.windows_sandbox import run as run_windows_sandbox

        isolated = run_windows_sandbox(self.policy, input_bytes)
        stdout_bytes = len(isolated.stdout.encode("utf-8"))
        stderr_bytes = len(isolated.stderr.encode("utf-8"))
        return SandboxResult(
            exit_code=isolated.exit_code,
            stdout=isolated.stdout,
            stderr=isolated.stderr,
            stdout_bytes=stdout_bytes,
            stderr_bytes=stderr_bytes,
            wall_time_seconds=time.monotonic() - started,
            timed_out=isolated.timed_out,
            output_truncated=isolated.output_truncated,
            memory_limit_hit=isolated.memory_limit_hit,
            peak_memory_bytes=isolated.peak_memory_bytes,
            availability_state="available",
        )

    def _execute_platform(
        self, cmd: list[str], env: dict, input_bytes: bytes | None, started: float
    ) -> SandboxResult:
        """Platform-specific execution with resource limits."""
        if sys.platform == "linux":
            return self._execute_linux(cmd, env, input_bytes, started)
        elif sys.platform == "win32":
            return self._execute_windows(cmd, env, input_bytes, started)
        else:
            return self._execute_generic(cmd, env, input_bytes, started)

    def _execute_linux(
        self, cmd: list[str], env: dict, input_bytes: bytes | None, started: float
    ) -> SandboxResult:
        """Linux: try cgroups v2 for resource limits."""
        popen_kwargs = self._build_popen_kwargs(env)

        # Try to set up cgroups v2
        cgroup_path = None
        if self.policy.isolation_level == "strict":
            cgroup_path = _setup_cgroup_v2(self.policy)

        try:
            proc = subprocess.Popen(cmd, **popen_kwargs)
        except Exception as exc:
            _cleanup_cgroup(cgroup_path)
            return SandboxResult(
                exit_code=-1,
                stderr=str(exc),
                wall_time_seconds=time.monotonic() - started,
            )

        # Monitor process with timeout
        result = _wait_with_timeout(
            proc, self.policy, input_bytes, started, popen_kwargs.get("stdout"),
        )
        _cleanup_cgroup(cgroup_path)
        return result

    def _execute_windows(
        self, cmd: list[str], env: dict, input_bytes: bytes | None, started: float
    ) -> SandboxResult:
        """Windows: use Job Objects for resource limits, not security isolation."""
        popen_kwargs = self._build_popen_kwargs(env)

        try:
            proc = subprocess.Popen(cmd, **popen_kwargs)
        except Exception as exc:
            return SandboxResult(
                exit_code=-1,
                stderr=str(exc),
                wall_time_seconds=time.monotonic() - started,
            )

        # Try to assign to a Job Object
        if self.policy.isolation_level == "strict" and not _current_process_in_job_windows():
            _assign_job_object_windows(proc, self.policy)
        elif self.policy.isolation_level == "strict":
            log.debug(
                "Process already belongs to an external Windows job; "
                "using inherited isolation and explicit timeout enforcement"
            )

        result = _wait_with_timeout(
            proc, self.policy, input_bytes, started, popen_kwargs.get("stdout"),
        )
        return result

    def _execute_generic(
        self, cmd: list[str], env: dict, input_bytes: bytes | None, started: float
    ) -> SandboxResult:
        """macOS / other: soft limits with audit warning."""
        if self.policy.isolation_level == "strict":
            log.warning(
                "Strict isolation requested but %s has no kernel-level sandbox. "
                "Falling back to soft limits.",
                sys.platform,
            )
        popen_kwargs = self._build_popen_kwargs(env)
        try:
            proc = subprocess.Popen(cmd, **popen_kwargs)
        except Exception as exc:
            return SandboxResult(
                exit_code=-1,
                stderr=str(exc),
                wall_time_seconds=time.monotonic() - started,
            )
        return _wait_with_timeout(
            proc, self.policy, input_bytes, started, popen_kwargs.get("stdout"),
        )

    def _build_popen_kwargs(self, env: dict | None = None) -> dict:
        """Build subprocess.Popen kwargs from policy."""
        # stdout/stderr as pipes (NOT inheriting parent)
        kwargs = {
            "stdin": subprocess.PIPE,
            "stdout": subprocess.PIPE,
            "stderr": subprocess.PIPE,
        }
        if env is not None:
            kwargs["env"] = env

        # Working directory
        if self.policy.working_dir:
            kwargs["cwd"] = self.policy.working_dir
        elif self.policy.write_allowed_paths:
            kwargs["cwd"] = self.policy.write_allowed_paths[0]
        else:
            kwargs["cwd"] = os.environ.get("TEMP", "/tmp")

        # Start new process group (enables clean kill of children)
        if sys.platform != "win32":
            kwargs["start_new_session"] = True
        else:
            kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP

        return kwargs

    def _audit_log(self, result: SandboxResult) -> None:
        """Log sandbox execution for audit trail."""
        log.info(
            "SANDBOX id=%s exe=%s exit=%d wall=%.3fs cpu=%.3fs mem=%d "
            "timeout=%s oom=%s signal=%d output_bytes=%d",
            self._audit_id,
            self.policy.executable,
            result.exit_code,
            result.wall_time_seconds,
            result.cpu_time_seconds,
            result.peak_memory_bytes,
            result.timed_out,
            result.memory_limit_hit,
            result.killed_by_signal,
            result.stdout_bytes + result.stderr_bytes,
        )


# ────────────────────────────────────────────────────────────
# Linux cgroups v2 helpers
# ────────────────────────────────────────────────────────────

def _setup_cgroup_v2(policy: SandboxPolicy) -> Optional[str]:
    """Create a cgroup v2 for the sandbox. Returns cgroup path or None."""
    cgroup_root = "/sys/fs/cgroup"
    if not os.path.ismount(cgroup_root):
        return None

    import uuid
    cgroup_name = f"nous-sandbox-{uuid.uuid4().hex[:12]}"
    cgroup_path = os.path.join(cgroup_root, "nous.slice", cgroup_name)
    if not os.path.exists(os.path.join(cgroup_root, "nous.slice")):
        # Fallback to direct child of root
        cgroup_path = os.path.join(cgroup_root, cgroup_name)

    try:
        os.makedirs(cgroup_path, exist_ok=True)

        # Memory limit
        if policy.max_memory_bytes > 0:
            mem_max = os.path.join(cgroup_path, "memory.max")
            with open(mem_max, "w") as f:
                f.write(str(policy.max_memory_bytes))

        # CPU limit (quota in microseconds per period)
        if policy.max_cpu_time_seconds > 0:
            cpu_max = os.path.join(cgroup_path, "cpu.max")
            quota = policy.max_cpu_time_seconds * 1_000_000
            with open(cpu_max, "w") as f:
                f.write(f"{quota} 100000")

        # Process limit
        pids_max = os.path.join(cgroup_path, "pids.max")
        with open(pids_max, "w") as f:
            f.write(str(policy.max_processes))

        return cgroup_path
    except (PermissionError, OSError) as exc:
        log.debug("cgroup v2 setup failed (running unprivileged?): %s", exc)
        _cleanup_cgroup(cgroup_path)
        return None


def _cleanup_cgroup(cgroup_path: Optional[str]) -> None:
    """Remove a cgroup."""
    if cgroup_path and os.path.exists(cgroup_path):
        try:
            os.rmdir(cgroup_path)
        except OSError:
            pass


# ────────────────────────────────────────────────────────────
# Windows Job Object helpers
# ────────────────────────────────────────────────────────────

def _current_process_in_job_windows() -> bool:
    if sys.platform != "win32":
        return False
    try:
        import ctypes

        in_job = ctypes.c_int(0)
        kernel32 = ctypes.windll.kernel32
        process = kernel32.GetCurrentProcess()
        probed = kernel32.IsProcessInJob(
            ctypes.c_void_p(process),
            ctypes.c_void_p(),
            ctypes.byref(in_job),
        )
        return bool(probed and in_job.value)
    except Exception:
        return False


def _assign_job_object_windows(proc: subprocess.Popen, policy: SandboxPolicy) -> None:
    """Assign the process to a Windows Job Object with resource limits.

    Uses proper ctypes struct definitions for memory and process count
    limits. CPU time limits are not enforced via Job Objects (use
    subprocess timeout instead).
    """
    if sys.platform != "win32":
        return

    try:
        import ctypes

        kernel32 = ctypes.windll.kernel32

        # Create Job Object (must be inheritable for child processes)
        job_handle = kernel32.CreateJobObjectW(None, None)
        if not job_handle:
            log.debug("CreateJobObjectW failed: %s", ctypes.get_last_error())
            return

        # Only set limits that are actually configured
        limit_flags = 0

        # ── Memory limit ──
        if policy.max_memory_bytes > 0:
            # Use JOB_OBJECT_LIMIT_JOB_MEMORY (0x200) to cap total job memory
            limit_flags |= 0x200  # JOB_OBJECT_LIMIT_JOB_MEMORY

        # ── Process count limit ──
        if policy.max_processes > 0:
            limit_flags |= 0x8  # JOB_OBJECT_LIMIT_ACTIVE_PROCESS

        if limit_flags == 0:
            kernel32.CloseHandle(ctypes.c_void_p(job_handle))
            return

        # Define proper JOBOBJECT_EXTENDED_LIMIT_INFORMATION
        class JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
            _fields_ = [
                ("PerProcessUserTimeLimit", ctypes.c_int64),
                ("PerJobUserTimeLimit", ctypes.c_int64),
                ("LimitFlags", ctypes.c_uint32),
                ("MinimumWorkingSetSize", ctypes.c_size_t),
                ("MaximumWorkingSetSize", ctypes.c_size_t),
                ("ActiveProcessLimit", ctypes.c_uint32),
                ("Affinity", ctypes.c_size_t),
                ("PriorityClass", ctypes.c_uint32),
                ("SchedulingClass", ctypes.c_uint32),
            ]

        class JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
            _fields_ = [
                ("BasicLimitInformation", JOBOBJECT_BASIC_LIMIT_INFORMATION),
                ("IoInfo", ctypes.c_byte * 48),
                ("ProcessMemoryLimit", ctypes.c_size_t),
                ("JobMemoryLimit", ctypes.c_size_t),
                ("PeakProcessMemoryUsed", ctypes.c_size_t),
                ("PeakJobMemoryUsed", ctypes.c_size_t),
            ]

        info = JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
        info.BasicLimitInformation.LimitFlags = ctypes.c_uint32(limit_flags)

        # Set ActiveProcessLimit if configured
        if policy.max_processes > 0:
            info.BasicLimitInformation.ActiveProcessLimit = ctypes.c_uint32(
                policy.max_processes
            )

        # Set JobMemoryLimit if configured
        if policy.max_memory_bytes > 0:
            info.JobMemoryLimit = ctypes.c_size_t(policy.max_memory_bytes)

        # Set information on the Job Object
        JobObjectExtendedLimitInformation = 9
        result = kernel32.SetInformationJobObject(
            ctypes.c_void_p(job_handle),
            JobObjectExtendedLimitInformation,
            ctypes.byref(info),
            ctypes.c_uint32(ctypes.sizeof(info)),
        )

        if not result:
            log.debug("SetInformationJobObject failed: %s", ctypes.get_last_error())
            kernel32.CloseHandle(ctypes.c_void_p(job_handle))
            return

        # Assign the process to the Job Object
        PROCESS_SET_QUOTA = 0x0100
        PROCESS_TERMINATE = 0x0001
        proc_handle = kernel32.OpenProcess(
            PROCESS_SET_QUOTA | PROCESS_TERMINATE,
            False,
            ctypes.c_uint32(proc.pid),
        )
        if not proc_handle:
            log.debug("OpenProcess failed for pid %d: %s", proc.pid, ctypes.get_last_error())
            kernel32.CloseHandle(ctypes.c_void_p(job_handle))
            return

        result = kernel32.AssignProcessToJobObject(
            ctypes.c_void_p(job_handle),
            ctypes.c_void_p(proc_handle),
        )
        if not result:
            log.debug(
                "AssignProcessToJobObject failed for pid %d: %s. "
                "Process may already be in a Job Object.",
                proc.pid, ctypes.get_last_error(),
            )

        kernel32.CloseHandle(ctypes.c_void_p(proc_handle))
        # Note: job_handle is intentionally leaked — it must outlive the child process.
        # Windows will clean it up when the process exits.

    except Exception as exc:
        log.debug("Windows Job Object setup failed: %s", exc)


# ────────────────────────────────────────────────────────────
# Timeout & output handling
# ────────────────────────────────────────────────────────────

def _wait_with_timeout(
    proc: subprocess.Popen,
    policy: SandboxPolicy,
    input_bytes: bytes | None,
    started: float,
    stdout_pipe=None,
) -> SandboxResult:
    """Wait for process with timeout, capture output, enforce limits."""
    try:
        out, err = proc.communicate(
            input=input_bytes,
            timeout=policy.timeout_seconds,
        )
        exit_code = proc.returncode or 0
        timed_out = False
    except subprocess.TimeoutExpired:
        # Graceful termination: SIGTERM, wait, then SIGKILL
        timed_out = True
        _terminate_process_tree(proc, policy.kill_timeout_seconds)
        try:
            out, err = proc.communicate(timeout=policy.kill_timeout_seconds)
        except subprocess.TimeoutExpired:
            proc.kill()
            out, err = proc.communicate()
        exit_code = -1

    # Enforce output size limits
    stdout_bytes = len(out) if out else 0
    stderr_bytes = len(err) if err else 0
    output_truncated = False

    if stdout_bytes > policy.max_output_bytes:
        out = out[:policy.max_output_bytes]
        stdout_bytes = policy.max_output_bytes
        output_truncated = True
    if stderr_bytes > policy.max_output_bytes:
        err = err[:policy.max_output_bytes]
        stderr_bytes = policy.max_output_bytes
        output_truncated = True

    return SandboxResult(
        exit_code=exit_code,
        stdout=out.decode("utf-8", errors="replace") if out else "",
        stderr=err.decode("utf-8", errors="replace") if err else "",
        stdout_bytes=stdout_bytes,
        stderr_bytes=stderr_bytes,
        wall_time_seconds=time.monotonic() - started,
        timed_out=timed_out,
        output_truncated=output_truncated,
        killed_by_signal=proc.returncode if proc.returncode and proc.returncode < 0 else 0,
    )


def _terminate_process_tree(proc: subprocess.Popen, kill_timeout: float) -> None:
    """Graceful termination: SIGTERM → wait → SIGKILL."""
    if sys.platform == "win32":
        # Windows: TerminateProcess via taskkill /T
        try:
            subprocess.run(
                ["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                capture_output=True,
                timeout=kill_timeout,
            )
        except Exception:
            proc.kill()
    else:
        # Unix: kill process group
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
        except (ProcessLookupError, OSError):
            pass
        try:
            proc.wait(timeout=kill_timeout)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            except (ProcessLookupError, OSError):
                pass
            proc.kill()


__all__ = [
    "ProcessSandbox",
    "SandboxPolicy",
    "SandboxResult",
]
