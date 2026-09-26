"""Ephemeral Windows Sandbox backend for strongly isolated local execution."""

from __future__ import annotations

import base64
import html
import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from nous_runtime.kernel.sandbox import SandboxPolicy


_HOST_STATE_NAMES = frozenset({".nous", ".apeir", ".git"})
_SANDBOX_RUN_LOCK = threading.Lock()
_RELAUNCH_GRACE_SECONDS = 2.0
_HOST_STARTUP_GRACE_SECONDS = 90.0
_last_run_finished_at = 0.0


def _ignore_host_state(_directory: str, names: list[str]) -> list[str]:
    return [name for name in names if name.casefold() in _HOST_STATE_NAMES]


@dataclass(frozen=True)
class WindowsSandboxExecution:
    exit_code: int = -1
    stdout: str = ""
    stderr: str = ""
    timed_out: bool = False
    output_truncated: bool = False
    memory_limit_hit: bool = False
    peak_memory_bytes: int = 0


def executable_path() -> str | None:
    """Return the Windows Sandbox launcher only when it is usable now."""
    if os.name != "nt":
        return None
    # Never launch a PATH-provided executable at this host trust boundary.
    system_root = Path(os.environ.get("SystemRoot", r"C:\Windows"))
    candidate = system_root / "System32" / "WindowsSandbox.exe"
    return str(candidate.resolve()) if candidate.is_file() else None


def run(
    policy: SandboxPolicy,
    input_bytes: bytes | None = None,
) -> WindowsSandboxExecution:
    """Serialize disposable VM sessions and allow the host to finish teardown."""
    global _last_run_finished_at
    with _SANDBOX_RUN_LOCK:
        remaining = _last_run_finished_at + _RELAUNCH_GRACE_SECONDS - time.monotonic()
        if remaining > 0:
            time.sleep(remaining)
        try:
            return _run_locked(policy, input_bytes)
        finally:
            _last_run_finished_at = time.monotonic()


def _run_locked(
    policy: SandboxPolicy,
    input_bytes: bytes | None = None,
) -> WindowsSandboxExecution:
    """Run one argv invocation inside a disposable, network-disabled VM."""
    launcher = executable_path()
    if not launcher:
        return WindowsSandboxExecution(
            stderr="STRICT_SANDBOX_UNAVAILABLE: Windows Sandbox is not ready"
        )
    if policy.network_allowed:
        return WindowsSandboxExecution(
            stderr=(
                "STRICT_SANDBOX_UNAVAILABLE: process network access cannot be "
                "host-scoped by the Windows Sandbox backend"
            )
        )

    if policy.cancel_file and Path(policy.cancel_file).is_file():
        return WindowsSandboxExecution(
            exit_code=130, stderr="Execution cancelled before VM startup"
        )

    task_root = Path(tempfile.mkdtemp(prefix="nous-wsb-"))
    control_root = task_root / "control"
    output_root = task_root / "output"
    control_root.mkdir()
    output_root.mkdir()
    process = None
    try:
        mappings, translations = _build_mappings(policy, control_root)
        mappings, commits = _stage_mappings(mappings, task_root / "staged", policy)
        mappings.append((output_root, r"C:\NousOutput", False))
        request_environment = _safe_environment(policy.env)
        venv_root = _venv_runtime_root(Path(policy.executable).resolve())
        if venv_root is not None:
            base_runtime = _venv_base_runtime(venv_root)
            assert base_runtime is not None
            base_executable = base_runtime / Path(policy.executable).name
            if not base_executable.is_file():
                raise ValueError(
                    f"virtual environment base executable does not exist: {base_executable}"
                )
            request_executable = _translate_path(str(base_executable), translations)
            python_paths = [r"C:\NousPackages"]
            workspace_src = Path(policy.working_dir).resolve() / "src"
            if workspace_src.is_dir():
                python_paths.insert(0, _translate_path(workspace_src, translations))
            request_environment["PYTHONPATH"] = ";".join(python_paths)
            request_environment["APEIR_SANDBOX_PACKAGES"] = r"C:\NousPackages"
        else:
            request_executable = _translate_path(policy.executable, translations)
        request = {
            "executable": request_executable,
            "arguments": subprocess.list2cmdline(
                [_translate_argument(item, translations) for item in policy.args]
            ),
            "working_dir": _translate_path(policy.working_dir, translations),
            "environment": request_environment,
            "stdin_base64": base64.b64encode(input_bytes or b"").decode("ascii"),
            "timeout_ms": max(1, int(policy.timeout_seconds * 1000)),
            "max_output_bytes": policy.max_output_bytes,
            "max_memory_bytes": max(1, int(policy.max_memory_bytes)),
            "max_cpu_time_seconds": max(1, int(policy.max_cpu_time_seconds)),
            "max_processes": max(1, int(policy.max_processes)),
        }
        (control_root / "request.json").write_text(
            json.dumps(request, ensure_ascii=False), encoding="utf-8"
        )
        (control_root / "launcher.ps1").write_text(
            _LAUNCHER_SCRIPT, encoding="utf-8-sig"
        )
        config_path = task_root / "sandbox.wsb"
        config_path.write_text(
            _configuration_xml(mappings, policy.max_memory_bytes), encoding="utf-8"
        )

        creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startupinfo.wShowWindow = 0
        process = subprocess.Popen(
            [launcher, str(config_path)],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=creationflags,
            startupinfo=startupinfo,
        )
        result_path = output_root / "result.json"
        # The guest enforces the workload timeout after its process starts.
        # Keep VM cold-start/teardown latency in a separate host-side budget.
        deadline = (
            time.monotonic() + policy.timeout_seconds + _HOST_STARTUP_GRACE_SECONDS
        )
        while time.monotonic() < deadline:
            if policy.cancel_file and Path(policy.cancel_file).is_file():
                _stop(process)
                return WindowsSandboxExecution(
                    exit_code=130, stderr="Execution cancelled by host"
                )
            if result_path.is_file():
                break
            if process.poll() is not None:
                break
            time.sleep(0.1)
        if not result_path.is_file():
            timed_out = time.monotonic() >= deadline
            _stop(process)
            return WindowsSandboxExecution(
                stderr=(
                    "Windows Sandbox execution timed out"
                    if timed_out
                    else f"Windows Sandbox exited without a result (launcher={process.returncode})"
                ),
                timed_out=timed_out,
            )

        try:
            # Guest output is untrusted, including the result envelope itself.
            envelope_limit = 12 * policy.max_output_bytes + 65536
            encoded = _read_result_bytes(result_path, envelope_limit)
            if len(encoded) > envelope_limit:
                raise ValueError("result envelope exceeds size limit")
            payload = json.loads(encoded.decode("utf-8-sig"))
            if not isinstance(payload, dict):
                raise ValueError("result envelope must be an object")
        except (OSError, ValueError) as exc:
            _stop(process)
            return WindowsSandboxExecution(
                stderr=f"Windows Sandbox returned an invalid result: {exc}"
            )
        _stop(process)
        if int(payload.get("exit_code", -1)) == 0 and not bool(
            payload.get("timed_out")
        ):
            try:
                _commit_writable_mappings(commits, policy.deny_paths)
            except (OSError, ValueError) as exc:
                return WindowsSandboxExecution(
                    stderr=f"Sandbox output commit rejected: {exc}"
                )
        stdout, stdout_cut = _bounded_text(
            str(payload.get("stdout", "")), policy.max_output_bytes
        )
        stderr, stderr_cut = _bounded_text(
            str(payload.get("stderr", "")),
            max(0, policy.max_output_bytes - len(stdout.encode("utf-8"))),
        )
        return WindowsSandboxExecution(
            exit_code=int(payload.get("exit_code", -1)),
            stdout=stdout,
            stderr=stderr,
            timed_out=bool(payload.get("timed_out", False)),
            output_truncated=stdout_cut
            or stderr_cut
            or bool(payload.get("output_truncated")),
            memory_limit_hit=bool(payload.get("memory_limit_hit", False)),
            peak_memory_bytes=max(0, int(payload.get("peak_memory_bytes", 0))),
        )
    except (OSError, ValueError) as exc:
        return WindowsSandboxExecution(stderr=f"Windows Sandbox setup failed: {exc}")
    finally:
        if process is not None:
            _stop(process)
        shutil.rmtree(task_root, ignore_errors=True)


def _read_result_bytes(path: Path, limit: int, retry_seconds: float = 2.0) -> bytes:
    """Retry short Windows shared-folder sharing violations, never invalid data."""
    deadline = time.monotonic() + retry_seconds
    while True:
        try:
            with path.open("rb") as handle:
                return handle.read(limit + 1)
        except PermissionError:
            if time.monotonic() >= deadline:
                raise
            time.sleep(0.05)


def _safe_environment(values: dict[str, str]) -> dict[str, str]:
    safe = {}
    for key, value in values.items():
        upper = str(key).upper()
        if upper.startswith(
            (
                "NOUS_SECRET",
                "NOUS_TOKEN",
                "NOUS_KEY",
                "NOUS_CREDENTIAL",
                "APEIR_SECRET",
                "APEIR_TOKEN",
                "APEIR_KEY",
                "APEIR_CREDENTIAL",
            )
        ):
            continue
        if upper in {"LD_PRELOAD", "LD_LIBRARY_PATH", "DYLD_INSERT_LIBRARIES"}:
            continue
        safe[str(key)] = str(value)
    return safe


def _build_mappings(
    policy: SandboxPolicy, task_root: Path
) -> tuple[list[tuple[Path, str, bool]], list[tuple[Path, str]]]:
    for raw in [
        str(task_root),
        policy.working_dir,
        policy.executable,
        *policy.read_allowed_paths,
        *policy.write_allowed_paths,
    ]:
        path = Path(os.path.abspath(raw))
        for ancestor in (path, *path.parents):
            info = ancestor.lstat()
            if getattr(info, "st_file_attributes", 0) & 0x400 or ancestor.is_symlink():
                raise ValueError(
                    "reparse points are unsupported in sandbox mapping roots"
                )
    entries: list[tuple[Path, bool, str | None]] = [
        (task_root.resolve(), True, "Control")
    ]
    working_dir = Path(policy.working_dir).resolve()
    if not working_dir.is_dir():
        raise ValueError(f"working directory does not exist: {working_dir}")
    writable_roots = [Path(raw).resolve() for raw in policy.write_allowed_paths]
    working_readonly = not any(_is_within(working_dir, root) for root in writable_roots)
    entries.append((working_dir, working_readonly, "Workspace"))

    executable = Path(policy.executable).resolve()
    if not executable.is_file():
        raise ValueError(f"executable does not exist: {executable}")
    system_root = Path(os.environ.get("SystemRoot", r"C:\Windows")).resolve()
    if not _is_within(executable, system_root):
        runtime_root = executable.parent
        if (
            runtime_root.name.casefold() == "scripts"
            and (runtime_root.parent / "pyvenv.cfg").is_file()
        ):
            runtime_root = runtime_root.parent
        base_runtime = _venv_base_runtime(runtime_root)
        if base_runtime is not None:
            entries.append((base_runtime, True, "BaseRuntime"))
            site_packages = runtime_root / "Lib" / "site-packages"
            if site_packages.is_dir():
                entries.append((site_packages, True, "Packages"))
        else:
            entries.append((runtime_root, True, "Runtime"))

    for raw in policy.read_allowed_paths:
        path = Path(raw).resolve()
        if not path.is_dir():
            raise ValueError("Windows Sandbox requires directory-scoped read grants")
        entries.append((path, True, None))
    for raw in policy.write_allowed_paths:
        path = Path(raw).resolve()
        if not path.is_dir():
            raise ValueError("Windows Sandbox requires directory-scoped write grants")
        entries.append((path, False, None))

    merged: dict[str, tuple[Path, bool, str | None]] = {}
    for host, readonly, preferred in entries:
        _validate_mapping_root(host, policy.deny_paths)
        key = os.path.normcase(str(host))
        previous = merged.get(key)
        if previous:
            merged[key] = (host, previous[1] and readonly, previous[2] or preferred)
        else:
            merged[key] = (host, readonly, preferred)

    mappings = []
    translations = []
    used_names: set[str] = set()
    for index, (host, readonly, preferred) in enumerate(merged.values()):
        name = preferred or f"Path{index}"
        while name in used_names:
            name = f"{name}{index}"
        used_names.add(name)
        guest = rf"C:\Nous{name}"
        mappings.append((host, guest, readonly))
        translations.append((host, guest))
    translations.sort(key=lambda item: len(str(item[0])), reverse=True)
    return mappings, translations


def _validate_mapping_root(root: Path, deny_paths: list[str]) -> None:
    """Reject scopes WSB cannot represent without broadening authority."""
    if root == Path(root.anchor):
        raise ValueError("mapping an entire volume is forbidden")
    # Mapping a state directory itself would expose every record below it.
    # A specifically granted descendant (for example one environment's
    # isolated workdir under .nous/environments/workdirs) remains a bounded
    # directory mapping and cannot expose siblings through Windows Sandbox.
    if root.name.casefold() in _HOST_STATE_NAMES:
        raise ValueError("mapping protected host state is forbidden")
    for denied in deny_paths:
        path = Path(denied).resolve()
        if _is_within(path, root) or _is_within(root, path):
            raise ValueError("mapped directory overlaps a denied path")
    # WSB exposes entire directories. Reject existing reparse points and hard
    # links; live mapping TOCTOU still requires post-boot adversarial validation.
    for current, directories, files in os.walk(root, followlinks=False):
        for name in directories + files:
            path = Path(current) / name
            info = path.lstat()
            if getattr(info, "st_file_attributes", 0) & 0x400 or path.is_symlink():
                raise ValueError("reparse points are unsupported in sandbox mappings")
            if name in files and info.st_nlink > 1:
                raise ValueError("hard links are unsupported in sandbox mappings")


def _snapshot_readonly_mappings(
    mappings: list[tuple[Path, str, bool]],
    staging_root: Path,
    policy: SandboxPolicy,
) -> list[tuple[Path, str, bool]]:
    """Compatibility wrapper returning only staged mappings."""
    staged, _ = _stage_mappings(mappings, staging_root, policy)
    return staged


def _stage_mappings(
    mappings: list[tuple[Path, str, bool]],
    staging_root: Path,
    policy: SandboxPolicy,
) -> tuple[list[tuple[Path, str, bool]], list[tuple[Path, Path, str]]]:
    """Snapshot untrusted policy mappings, not trusted runtime/control folders."""
    staged: list[tuple[Path, str, bool]] = []
    commits: list[tuple[Path, Path, str]] = []
    total_files = 0
    total_bytes = 0
    for index, (host, guest, readonly) in enumerate(mappings):
        if guest in {
            r"C:\NousControl",
            r"C:\NousBaseRuntime",
            r"C:\NousPackages",
        }:
            staged.append((host, guest, readonly))
            continue
        destination = staging_root / f"input-{index}"
        source_before = _tree_digest(host)
        _, files, size = source_before
        total_files += files
        total_bytes += size
        if (
            total_files > policy.max_staging_files
            or total_bytes > policy.max_staging_bytes
        ):
            raise ValueError("read-only input snapshot exceeds staging limits")
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(
            host, destination, copy_function=shutil.copy2, ignore=_ignore_host_state
        )
        staged_digest, staged_files, staged_size = _tree_digest(destination)
        source_after = _tree_digest(host)
        if source_before != source_after or source_before != (
            staged_digest,
            staged_files,
            staged_size,
        ):
            raise ValueError("read-only input changed while its snapshot was created")
        staged.append((destination, guest, readonly))
        if not readonly:
            commits.append((destination, host, source_before[0]))
    return staged, commits


def _venv_base_runtime(runtime_root: Path) -> Path | None:
    config = runtime_root / "pyvenv.cfg"
    if not config.is_file():
        return None
    for line in config.read_text(encoding="utf-8").splitlines():
        key, separator, value = line.partition("=")
        if separator and key.strip().casefold() == "home":
            base_runtime = Path(value.strip()).resolve()
            if not base_runtime.is_dir():
                raise ValueError(
                    f"virtual environment base runtime does not exist: {base_runtime}"
                )
            return base_runtime
    raise ValueError(f"virtual environment has no home entry: {config}")


def _venv_runtime_root(executable: Path) -> Path | None:
    scripts = executable.parent
    runtime_root = scripts.parent
    if scripts.name.casefold() == "scripts" and (runtime_root / "pyvenv.cfg").is_file():
        return runtime_root
    return None


def _commit_writable_mappings(
    commits: list[tuple[Path, Path, str]], deny_paths: list[str]
) -> None:
    """Apply staged writes only when each authorized host root is unchanged."""
    for staged, host, expected_digest in commits:
        _validate_mapping_root(host, deny_paths)
        # Reject attempts to create protected metadata through task output.
        for _current, directories, files in os.walk(staged, followlinks=False):
            if any(
                name.casefold() in _HOST_STATE_NAMES for name in directories + files
            ):
                raise ValueError("sandbox output contains protected host state")
        current_digest, _, _ = _tree_digest(host)
        if current_digest != expected_digest:
            raise ValueError(f"authorized write root changed during execution: {host}")
        staged_digest, _, _ = _tree_digest(staged)
        if staged_digest is None:
            raise ValueError("invalid staged output")
        for current, directories, files in os.walk(host, followlinks=False):
            directories[:] = [
                name for name in directories if name.casefold() not in _HOST_STATE_NAMES
            ]
            for name in files:
                if name.casefold() in _HOST_STATE_NAMES:
                    continue
                target = staged / Path(current).relative_to(host) / name
                if not target.is_file():
                    (Path(current) / name).unlink()
        shutil.copytree(
            staged,
            host,
            dirs_exist_ok=True,
            copy_function=shutil.copy2,
            ignore=_ignore_host_state,
        )
        _validate_mapping_root(host, deny_paths)


def _tree_digest(root: Path) -> tuple[str, int, int]:
    digest = hashlib.sha256()
    count = 0
    size = 0
    paths = []
    for current, directories, files in os.walk(root, followlinks=False):
        directories[:] = [
            name for name in directories if name.casefold() not in _HOST_STATE_NAMES
        ]
        paths.extend(
            Path(current) / name
            for name in directories + files
            if name.casefold() not in _HOST_STATE_NAMES
        )
    for path in sorted(paths, key=lambda item: item.relative_to(root).as_posix()):
        relative = path.relative_to(root).as_posix().encode("utf-8")
        info = path.lstat()
        if getattr(info, "st_file_attributes", 0) & 0x400 or path.is_symlink():
            raise ValueError("reparse points are unsupported in input snapshots")
        if path.is_dir():
            digest.update(b"d" + relative)
            continue
        if not path.is_file() or info.st_nlink > 1:
            raise ValueError("unsupported file type in input snapshot")
        count += 1
        size += info.st_size
        digest.update(b"f" + relative + info.st_size.to_bytes(8, "big"))
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    return digest.hexdigest(), count, size


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _translate_path(raw: str, translations: list[tuple[Path, str]]) -> str:
    path = Path(raw).resolve()
    system_root = Path(os.environ.get("SystemRoot", r"C:\Windows")).resolve()
    if _is_within(path, system_root):
        return str(Path(r"C:\Windows") / path.relative_to(system_root))
    for host, guest in translations:
        if _is_within(path, host):
            relative = path.relative_to(host)
            return str(Path(guest) / relative)
    raise ValueError(f"path is outside the sandbox mappings: {path}")


def _translate_argument(raw: str, translations: list[tuple[Path, str]]) -> str:
    value = str(raw)
    if not os.path.isabs(value):
        return value
    return _translate_path(value, translations)


def _configuration_xml(
    mappings: list[tuple[Path, str, bool]], max_memory_bytes: int
) -> str:
    mapped = []
    for host, guest, readonly in mappings:
        mapped.append(
            "<MappedFolder>"
            f"<HostFolder>{html.escape(str(host))}</HostFolder>"
            f"<SandboxFolder>{html.escape(guest)}</SandboxFolder>"
            f"<ReadOnly>{str(readonly).lower()}</ReadOnly>"
            "</MappedFolder>"
        )
    memory_mb = max(2048, int(max_memory_bytes / (1024 * 1024)))
    return (
        "<Configuration>"
        "<VGpu>Disable</VGpu>"
        "<Networking>Disable</Networking>"
        "<AudioInput>Disable</AudioInput>"
        "<VideoInput>Disable</VideoInput>"
        "<PrinterRedirection>Disable</PrinterRedirection>"
        "<ClipboardRedirection>Disable</ClipboardRedirection>"
        f"<MemoryInMB>{memory_mb}</MemoryInMB>"
        f"<MappedFolders>{''.join(mapped)}</MappedFolders>"
        "<LogonCommand><Command>powershell.exe -NoProfile -NonInteractive "
        "-ExecutionPolicy Bypass -File C:\\NousControl\\launcher.ps1"
        "</Command></LogonCommand>"
        "</Configuration>"
    )


def _bounded_text(value: str, limit: int) -> tuple[str, bool]:
    encoded = value.encode("utf-8")
    if len(encoded) <= limit:
        return value, False
    return encoded[:limit].decode("utf-8", errors="ignore"), True


def _stop(process: subprocess.Popen, graceful_seconds: float = 0.0) -> None:
    if process.poll() is not None:
        return
    if graceful_seconds:
        try:
            process.wait(timeout=graceful_seconds)
            return
        except subprocess.TimeoutExpired:
            pass
    taskkill = str(
        Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32/taskkill.exe"
    )
    subprocess.run(
        [taskkill, "/PID", str(process.pid), "/T", "/F"],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        timeout=10,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        check=False,
    )
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


_LAUNCHER_SCRIPT = r"""$ErrorActionPreference = "Stop"
$control = "C:\NousControl"
$request = Get-Content -LiteralPath "$control\request.json" -Raw -Encoding UTF8 | ConvertFrom-Json
$result = [ordered]@{ exit_code = -1; stdout = ""; stderr = ""; timed_out = $false; memory_limit_hit = $false; peak_memory_bytes = 0 }
$job = [IntPtr]::Zero
try {
    Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
public static class NousJobLimits {
    [StructLayout(LayoutKind.Sequential)]
    struct IoCounters { public ulong ReadOps, WriteOps, OtherOps, ReadBytes, WriteBytes, OtherBytes; }
    [StructLayout(LayoutKind.Sequential)]
    struct Basic {
        public long PerProcessUserTimeLimit, PerJobUserTimeLimit;
        public uint LimitFlags;
        public UIntPtr MinimumWorkingSetSize, MaximumWorkingSetSize;
        public uint ActiveProcessLimit;
        public UIntPtr Affinity;
        public uint PriorityClass, SchedulingClass;
    }
    [StructLayout(LayoutKind.Sequential)]
    struct Extended {
        public Basic BasicLimitInformation;
        public IoCounters IoInfo;
        public UIntPtr ProcessMemoryLimit, JobMemoryLimit;
        public UIntPtr PeakProcessMemoryUsed, PeakJobMemoryUsed;
    }
    [DllImport("kernel32.dll", SetLastError=true)]
    static extern IntPtr CreateJobObject(IntPtr attrs, string name);
    [DllImport("kernel32.dll", SetLastError=true)]
    static extern bool SetInformationJobObject(IntPtr job, int infoClass, ref Extended info, uint length);
    [DllImport("kernel32.dll", SetLastError=true)]
    static extern bool AssignProcessToJobObject(IntPtr job, IntPtr process);
    [DllImport("kernel32.dll", SetLastError=true)]
    static extern bool QueryInformationJobObject(IntPtr job, int infoClass, out Extended info, uint length, IntPtr returned);
    [DllImport("kernel32.dll", SetLastError=true)]
    static extern bool CloseHandle(IntPtr handle);
    public static IntPtr Apply(System.Diagnostics.Process process, long memory, int cpuSeconds, int maxProcesses) {
        IntPtr job = CreateJobObject(IntPtr.Zero, null);
        if (job == IntPtr.Zero) throw new InvalidOperationException("CreateJobObject failed: " + Marshal.GetLastWin32Error());
        try {
            var info = new Extended();
            info.BasicLimitInformation.LimitFlags = 0x00000004u | 0x00000008u | 0x00000100u | 0x00000200u | 0x00002000u;
            info.BasicLimitInformation.PerJobUserTimeLimit = checked((long)cpuSeconds * 10000000L);
            info.BasicLimitInformation.ActiveProcessLimit = (uint)Math.Max(1, maxProcesses);
            info.ProcessMemoryLimit = new UIntPtr(checked((ulong)Math.Max(1L, memory)));
            info.JobMemoryLimit = info.ProcessMemoryLimit;
            if (!SetInformationJobObject(job, 9, ref info, (uint)Marshal.SizeOf(typeof(Extended))))
                throw new InvalidOperationException("SetInformationJobObject failed: " + Marshal.GetLastWin32Error());
            if (!AssignProcessToJobObject(job, process.Handle))
                throw new InvalidOperationException("AssignProcessToJobObject failed: " + Marshal.GetLastWin32Error());
            return job;
        } catch { CloseHandle(job); throw; }
    }
    public static ulong PeakMemory(IntPtr job) {
        Extended info;
        if (!QueryInformationJobObject(job, 9, out info, (uint)Marshal.SizeOf(typeof(Extended)), IntPtr.Zero))
            throw new InvalidOperationException("QueryInformationJobObject failed: " + Marshal.GetLastWin32Error());
        return info.PeakJobMemoryUsed.ToUInt64();
    }
    public static void Close(IntPtr job) { if (job != IntPtr.Zero) CloseHandle(job); }
}
'@
    # .NET Framework initializes redirected stdin from Console.InputEncoding.
    # Its default UTF-8 preamble otherwise corrupts arbitrary input bytes.
    [Console]::InputEncoding = New-Object System.Text.UTF8Encoding($false)
    # Drain both pipes continuously but retain only a shared bounded byte budget.
    # C# tasks run without requiring a PowerShell runspace on worker threads.
    Add-Type -TypeDefinition @'
using System;
using System.IO;
using System.Threading.Tasks;
public sealed class NousOutputCollector {
    private readonly object gate = new object();
    private int remaining;
    public bool Truncated { get; private set; }
    public NousOutputCollector(int limit) { remaining = limit; }
    public async Task<byte[]> Drain(Stream stream) {
        using (var kept = new MemoryStream()) {
            var buffer = new byte[4096];
            int count;
            while ((count = await stream.ReadAsync(buffer, 0, buffer.Length)) != 0) {
                lock (gate) {
                    int take = Math.Min(count, remaining);
                    kept.Write(buffer, 0, take);
                    remaining -= take;
                    if (take < count) Truncated = true;
                }
            }
            return kept.ToArray();
        }
    }
    public static async Task Send(Stream stream, byte[] input) {
        try { await stream.WriteAsync(input, 0, input.Length); }
        catch (IOException) { }
        finally { stream.Close(); }
    }
}
'@
    $start = New-Object System.Diagnostics.ProcessStartInfo
    $start.FileName = [string]$request.executable
    $start.Arguments = [string]$request.arguments
    $start.WorkingDirectory = [string]$request.working_dir
    $start.UseShellExecute = $false
    $start.CreateNoWindow = $true
    $start.RedirectStandardInput = $true
    $start.RedirectStandardOutput = $true
    $start.RedirectStandardError = $true
    $start.StandardOutputEncoding = New-Object System.Text.UTF8Encoding($false)
    $start.StandardErrorEncoding = New-Object System.Text.UTF8Encoding($false)
    $start.EnvironmentVariables['PYTHONIOENCODING'] = 'utf-8'
    foreach ($property in $request.environment.PSObject.Properties) {
        $start.EnvironmentVariables[[string]$property.Name] = [string]$property.Value
    }
    $process = New-Object System.Diagnostics.Process
    $process.StartInfo = $start
    [void]$process.Start()
    $job = [NousJobLimits]::Apply(
        $process,
        [long]$request.max_memory_bytes,
        [int]$request.max_cpu_time_seconds,
        [int]$request.max_processes
    )
    $collector = New-Object NousOutputCollector([int]$request.max_output_bytes)
    $stdout = $collector.Drain($process.StandardOutput.BaseStream)
    $stderr = $collector.Drain($process.StandardError.BaseStream)
    $bytes = [Convert]::FromBase64String([string]$request.stdin_base64)
    $stdin = [NousOutputCollector]::Send($process.StandardInput.BaseStream, $bytes)
    $deadline = [DateTime]::UtcNow.AddMilliseconds([int]$request.timeout_ms)
    while (-not $process.WaitForExit(50)) {
        $process.Refresh()
        $observedMemory = [Math]::Max(
            [uint64]$process.PrivateMemorySize64,
            [NousJobLimits]::PeakMemory($job)
        )
        $result.peak_memory_bytes = [Math]::Max(
            [uint64]$result.peak_memory_bytes,
            [uint64]$observedMemory
        )
        # Keep headroom for sampling and Job accounting granularity. The native
        # hard limit remains at 100%; the watcher closes the job at 95%.
        $memoryThreshold = [uint64](
            ([decimal]$request.max_memory_bytes * [decimal]95) / [decimal]100
        )
        if ($observedMemory -ge $memoryThreshold) {
            $result.memory_limit_hit = $true
            [NousJobLimits]::Close($job)
            $job = [IntPtr]::Zero
            [void]$process.WaitForExit(2000)
            break
        }
        if ([DateTime]::UtcNow -ge $deadline) {
            $result.timed_out = $true
            [NousJobLimits]::Close($job)
            $job = [IntPtr]::Zero
            [void]$process.WaitForExit(2000)
            break
        }
    }
    $result.exit_code = if ($result.timed_out -or $result.memory_limit_hit) {
        -1
    } else {
        $process.ExitCode
    }
    # Descendants can retain inherited pipe handles. Never wait indefinitely.
    if (-not [Threading.Tasks.Task]::WaitAll([Threading.Tasks.Task[]]@($stdout, $stderr), 2000)) {
        throw 'Child processes retained output pipes; host must destroy the VM'
    }
    $result.stdout = [Text.Encoding]::UTF8.GetString($stdout.Result)
    $result.stderr = [Text.Encoding]::UTF8.GetString($stderr.Result)
    $result.output_truncated = $collector.Truncated
} catch {
    $result.exit_code = -1
    $result.stderr = $_.Exception.ToString()
}
$temporary = "C:\NousOutput\result.tmp"
[IO.File]::WriteAllText($temporary, ($result | ConvertTo-Json -Compress), [Text.Encoding]::UTF8)
Move-Item -LiteralPath $temporary -Destination "C:\NousOutput\result.json" -Force
# Close the job only after the result file is durable; KILL_ON_JOB_CLOSE
# recursively terminates any descendant that survived the requested timeout.
[NousJobLimits]::Close($job)
# The host terminates this exact launcher/client tree after reading the result.
"""


__all__ = ["WindowsSandboxExecution", "executable_path", "run"]
