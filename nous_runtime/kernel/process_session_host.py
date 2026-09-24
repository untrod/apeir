"""Detached host for one governed, reconnectable process session.

The host is deliberately small: it owns only the OS process, its process
group, stdin, output spools, and control acknowledgements.  Work state and
tool authority remain outside this module.
"""

from __future__ import annotations

import argparse
import base64
import binascii
import ctypes
import hashlib
import json
import os
import signal
import subprocess
import sys
import time
from uuid import uuid4
from collections.abc import Mapping
from pathlib import Path
from typing import Any


def _utc_now() -> str:
    from datetime import datetime, timezone

    return (
        datetime.now(timezone.utc)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )


def _atomic_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + f".{uuid4().hex}.tmp")
    with temporary.open("x", encoding="utf-8", newline="\n") as handle:
        json.dump(dict(value), handle, ensure_ascii=False, sort_keys=True, indent=2)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    for attempt in range(20):
        try:
            os.replace(temporary, path)
            return
        except PermissionError:
            if attempt == 19:
                raise
            time.sleep(0.01)


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return dict(value) if isinstance(value, Mapping) else {}


def _creation_token_windows(pid: int) -> str:
    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    kernel32 = ctypes.windll.kernel32
    kernel32.OpenProcess.restype = ctypes.c_void_p
    handle = kernel32.OpenProcess(
        PROCESS_QUERY_LIMITED_INFORMATION, False, ctypes.c_uint32(pid)
    )
    if not handle:
        return ""
    try:
        creation = ctypes.c_uint64()
        exit_time = ctypes.c_uint64()
        kernel = ctypes.c_uint64()
        user = ctypes.c_uint64()
        ok = kernel32.GetProcessTimes(
            ctypes.c_void_p(handle),
            ctypes.byref(creation),
            ctypes.byref(exit_time),
            ctypes.byref(kernel),
            ctypes.byref(user),
        )
        return str(creation.value) if ok else ""
    finally:
        kernel32.CloseHandle(ctypes.c_void_p(handle))


def process_creation_token(pid: int) -> str:
    """Return an OS creation marker suitable for rejecting PID reuse."""
    if pid <= 0:
        return ""
    if sys.platform == "win32":
        return _creation_token_windows(pid)
    stat = Path(f"/proc/{pid}/stat")
    if stat.is_file():
        try:
            # Field 22 is the kernel start time.  The command field may contain
            # spaces, so split only after its closing parenthesis.
            suffix = stat.read_text(encoding="utf-8").rsplit(")", 1)[1].split()
            return suffix[19]
        except (OSError, IndexError):
            return ""
    return ""


def process_identity_matches(identity: Mapping[str, Any]) -> bool:
    pid = int(identity.get("pid") or 0)
    expected = str(identity.get("creation_time") or "")
    return bool(pid > 0 and expected and process_creation_token(pid) == expected)


class ProcessSandboxHost:
    """The single subprocess boundary for persistent development commands."""

    @staticmethod
    def launch(spec_path: str | Path) -> dict[str, Any]:
        path = Path(spec_path).resolve(strict=True)
        if getattr(sys, "frozen", False):
            raise RuntimeError(
                "persistent process sessions require the Python runtime host"
            )
        log_path = path.parent / "host.log"
        log_handle = log_path.open("ab", buffering=0)
        kwargs: dict[str, Any] = {
            "stdin": subprocess.DEVNULL,
            "stdout": log_handle,
            "stderr": log_handle,
            "cwd": str(path.parent),
            "close_fds": True,
        }
        environment = dict(os.environ)
        source_root = str(Path(__file__).resolve().parents[2])
        environment["PYTHONPATH"] = os.pathsep.join(
            item for item in (source_root, environment.get("PYTHONPATH", "")) if item
        )
        kwargs["env"] = environment
        if sys.platform == "win32":
            kwargs["creationflags"] = (
                subprocess.DETACHED_PROCESS
                | subprocess.CREATE_NEW_PROCESS_GROUP
                | subprocess.CREATE_NO_WINDOW
            )
        else:
            kwargs["start_new_session"] = True
        try:
            subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "nous_runtime.kernel.process_session_host",
                    "--serve",
                    str(path),
                ],
                **kwargs,
            )
        finally:
            log_handle.close()
        # Some Windows virtual-environment launchers hand execution to another
        # interpreter process.  The host records its own stable identity after
        # startup; the launcher's PID must never be treated as that identity.
        return {}

    @staticmethod
    def serve(spec_path: str | Path) -> int:
        path = Path(spec_path).resolve(strict=True)
        spec = _read_json(path)
        session_id = str(spec.get("session_id") or "")
        command = [str(item) for item in spec.get("command") or ()]
        command_digest = str(spec.get("command_digest") or "")
        directory = path.parent
        state_path = directory / "host.json"
        controls = directory / "control"
        acknowledgements = directory / "ack"
        stdout_path = directory / "stdout.log"
        stderr_path = directory / "stderr.log"
        controls.mkdir(exist_ok=True)
        acknowledgements.mkdir(exist_ok=True)

        state: dict[str, Any] = {
            "schema": "nous.process-host-state/v1",
            "session_id": session_id,
            "command_digest": command_digest,
            "state": "STARTING",
            "helper_pid": os.getpid(),
            "helper_identity": {
                "pid": os.getpid(),
                "creation_time": process_creation_token(os.getpid()),
                "command_digest": "sha256:"
                + hashlib.sha256(str(path).encode("utf-8")).hexdigest(),
            },
            "updated_at": _utc_now(),
            "stdout_cursor": stdout_path.stat().st_size if stdout_path.exists() else 0,
            "stderr_cursor": stderr_path.stat().st_size if stderr_path.exists() else 0,
            "stdin_available": False,
        }
        _atomic_json(state_path, state)
        if not session_id or not command or not command_digest:
            state.update(
                state="RECOVERY_REQUIRED",
                error="process host specification is incomplete",
                updated_at=_utc_now(),
            )
            _atomic_json(state_path, state)
            return 2

        process: subprocess.Popen[bytes] | None = None
        job_handle: int = 0
        last_control = ""
        try:
            with (
                stdout_path.open("ab", buffering=0) as stdout,
                stderr_path.open("ab", buffering=0) as stderr,
            ):
                kwargs: dict[str, Any] = {
                    "stdin": subprocess.PIPE,
                    "stdout": stdout,
                    "stderr": stderr,
                    "cwd": str(spec["cwd"]),
                    "env": {
                        str(key): str(value)
                        for key, value in dict(spec.get("env") or {}).items()
                    },
                    "shell": False,
                    "close_fds": True,
                }
                if sys.platform == "win32":
                    kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
                else:
                    kwargs["start_new_session"] = True
                process = subprocess.Popen(command, **kwargs)
                creation = process_creation_token(process.pid)
                if not creation:
                    raise RuntimeError(
                        "could not obtain a stable process creation time"
                    )
                if sys.platform == "win32":
                    job_handle = ProcessSandboxHost._create_windows_job(process.pid)
                identity = {
                    "pid": process.pid,
                    "creation_time": creation,
                    "command_digest": command_digest,
                    "process_group": process.pid,
                    "executable": command[0],
                }
                state.update(
                    state="RUNNING",
                    process_identity=identity,
                    started_at=_utc_now(),
                    updated_at=_utc_now(),
                    stdin_available=True,
                )
                _atomic_json(state_path, state)

                while process.poll() is None:
                    for control_path in sorted(controls.glob("*.json")):
                        ack_path = acknowledgements / control_path.name
                        if ack_path.exists():
                            continue
                        control = _read_json(control_path)
                        action = str(control.get("action") or "")
                        try:
                            if str(control.get("session_id") or "") != session_id:
                                raise ValueError(
                                    "process control session binding mismatch"
                                )
                            ProcessSandboxHost._apply_control(process, action, control)
                            if action in {"interrupt", "terminate", "kill"}:
                                last_control = action
                            result = {"ok": True, "action": action, "at": _utc_now()}
                        except (
                            OSError,
                            RuntimeError,
                            ValueError,
                            binascii.Error,
                        ) as exc:
                            result = {
                                "ok": False,
                                "action": action,
                                "error": str(exc),
                                "at": _utc_now(),
                            }
                        _atomic_json(ack_path, result)
                    state.update(
                        updated_at=_utc_now(),
                        stdout_cursor=stdout_path.stat().st_size,
                        stderr_cursor=stderr_path.stat().st_size,
                        stdin_available=bool(
                            process.stdin is not None and not process.stdin.closed
                        ),
                    )
                    _atomic_json(state_path, state)
                    time.sleep(0.05)

                exit_code = int(process.returncode or 0)
                ProcessSandboxHost._cleanup_descendants(process, job_handle)
                terminal = {
                    "interrupt": "INTERRUPTED",
                    "terminate": "TERMINATED",
                    "kill": "KILLED",
                }.get(last_control, "EXITED")
                state.update(
                    state=terminal,
                    exit_code=exit_code,
                    completed_at=_utc_now(),
                    updated_at=_utc_now(),
                    stdout_cursor=stdout_path.stat().st_size,
                    stderr_cursor=stderr_path.stat().st_size,
                    stdin_available=False,
                )
                _atomic_json(state_path, state)
                return 0
        except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as exc:
            if process is not None and process.poll() is None:
                try:
                    ProcessSandboxHost._hard_kill(process, job_handle)
                except (OSError, RuntimeError, subprocess.SubprocessError):
                    state["cleanup_error"] = "process cleanup could not be confirmed"
            state.update(
                state="RECOVERY_REQUIRED",
                error=str(exc),
                completed_at=_utc_now(),
                updated_at=_utc_now(),
                stdin_available=False,
            )
            _atomic_json(state_path, state)
            return 1
        finally:
            if job_handle:
                ctypes.windll.kernel32.CloseHandle(ctypes.c_void_p(job_handle))

    @staticmethod
    def _apply_control(
        process: subprocess.Popen[bytes], action: str, control: Mapping[str, Any]
    ) -> None:
        if action == "stdin":
            if process.stdin is None or process.stdin.closed:
                raise RuntimeError("stdin is closed")
            payload = base64.b64decode(
                str(control.get("data_base64") or ""), validate=True
            )
            process.stdin.write(payload)
            process.stdin.flush()
            return
        if action == "close_stdin":
            if process.stdin is not None and not process.stdin.closed:
                process.stdin.close()
            return
        if action == "interrupt":
            if sys.platform == "win32":
                process.send_signal(signal.CTRL_BREAK_EVENT)
            else:
                os.killpg(process.pid, signal.SIGINT)
            return
        if action == "terminate":
            if sys.platform == "win32":
                process.terminate()
            else:
                os.killpg(process.pid, signal.SIGTERM)
            return
        if action == "kill":
            ProcessSandboxHost._hard_kill(process, 0)
            return
        raise ValueError(f"unknown process control action: {action}")

    @staticmethod
    def _create_windows_job(pid: int) -> int:
        if sys.platform != "win32":
            return 0

        class BasicLimits(ctypes.Structure):
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

        class ExtendedLimits(ctypes.Structure):
            _fields_ = [
                ("BasicLimitInformation", BasicLimits),
                ("IoInfo", ctypes.c_byte * 48),
                ("ProcessMemoryLimit", ctypes.c_size_t),
                ("JobMemoryLimit", ctypes.c_size_t),
                ("PeakProcessMemoryUsed", ctypes.c_size_t),
                ("PeakJobMemoryUsed", ctypes.c_size_t),
            ]

        kernel32 = ctypes.windll.kernel32
        kernel32.CreateJobObjectW.restype = ctypes.c_void_p
        kernel32.OpenProcess.restype = ctypes.c_void_p
        handle = kernel32.CreateJobObjectW(None, None)
        if not handle:
            return 0
        info = ExtendedLimits()
        info.BasicLimitInformation.LimitFlags = 0x2000  # KILL_ON_JOB_CLOSE
        if not kernel32.SetInformationJobObject(
            ctypes.c_void_p(handle), 9, ctypes.byref(info), ctypes.sizeof(info)
        ):
            kernel32.CloseHandle(ctypes.c_void_p(handle))
            return 0
        process_handle = kernel32.OpenProcess(0x0100 | 0x0001, False, pid)
        if not process_handle:
            kernel32.CloseHandle(ctypes.c_void_p(handle))
            return 0
        try:
            if not kernel32.AssignProcessToJobObject(
                ctypes.c_void_p(handle), ctypes.c_void_p(process_handle)
            ):
                kernel32.CloseHandle(ctypes.c_void_p(handle))
                return 0
        finally:
            kernel32.CloseHandle(ctypes.c_void_p(process_handle))
        return int(handle)

    @staticmethod
    def _hard_kill(process: subprocess.Popen[bytes], job_handle: int) -> None:
        if sys.platform == "win32" and job_handle:
            ctypes.windll.kernel32.TerminateJobObject(ctypes.c_void_p(job_handle), 1)
        elif sys.platform == "win32":
            subprocess.run(
                ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                capture_output=True,
                timeout=5,
                check=False,
            )
        else:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass

    @staticmethod
    def _cleanup_descendants(process: subprocess.Popen[bytes], job_handle: int) -> None:
        if sys.platform == "win32":
            if job_handle:
                ctypes.windll.kernel32.TerminateJobObject(
                    ctypes.c_void_p(job_handle), 0
                )
            return
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            return
        time.sleep(0.05)
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--serve", action="store_true")
    parser.add_argument("spec", nargs="?")
    args = parser.parse_args(argv)
    if not args.serve or not args.spec:
        return 2
    return ProcessSandboxHost.serve(args.spec)


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "ProcessSandboxHost",
    "process_creation_token",
    "process_identity_matches",
]
