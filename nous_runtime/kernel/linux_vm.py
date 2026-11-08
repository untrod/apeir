"""Optional Linux platform adapter for ProcessSandbox, not an execution authority.

Only a digest-pinned, operator-provisioned x86-64 VM profile is accepted. This
first profile runs the pinned CPython runtime against one read-only project
snapshot. Write grants, networking and arbitrary host executables fail closed.
"""

from __future__ import annotations

import base64
import gzip
import hashlib
import hmac
import json
import logging
import os
import platform
import selectors
import signal
import stat
import subprocess
import tempfile
import time
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING

from nous_runtime.kernel.sandbox import SandboxResult
from nous_runtime.kernel.windows_sandbox import (
    _stage_mappings,
    _tree_digest,
    _validate_mapping_root,
)

if TYPE_CHECKING:
    from nous_runtime.kernel.sandbox import SandboxPolicy

_MAX_PROFILE = 256 * 1024
_MAX_IMAGE = 512 * 1024 * 1024
log = logging.getLogger("nous.kernel.linux_vm")


def _digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def _checked_file(root: Path, name: str) -> Path:
    parts = PurePosixPath(name)
    if not name or parts.is_absolute() or ".." in parts.parts or "\\" in name:
        raise ValueError("invalid VM profile path")
    candidate = root / name
    for ancestor in (candidate, *candidate.parents):
        if ancestor == root.parent:
            break
        info = ancestor.lstat()
        if stat.S_ISLNK(info.st_mode) or info.st_mode & 0o022:
            raise ValueError("VM profile inputs must not be links or publicly writable")
        if info.st_uid not in {0, os.getuid()}:
            raise ValueError("VM profile input has an untrusted owner")
    info = candidate.stat()
    if (
        not stat.S_ISREG(info.st_mode)
        or info.st_nlink != 1
        or info.st_size > _MAX_IMAGE
    ):
        raise ValueError("invalid VM profile input file")
    return candidate


def load_profile() -> tuple[Path, dict]:
    name = os.environ.get("APEIR_LINUX_VM_PROFILE", "")
    expected = os.environ.get("APEIR_LINUX_VM_PROFILE_SHA256", "")
    if (
        not name
        or len(expected) != 64
        or any(c not in "0123456789abcdef" for c in expected)
    ):
        raise ValueError("no digest-pinned Linux VM profile configured")
    path = Path(name)
    if not path.is_absolute() or not path.parent.is_dir():
        raise ValueError("VM profile must be an absolute local path")
    root = path.parent
    path = _checked_file(root, path.name)
    if path.stat().st_size > _MAX_PROFILE or _digest(path) != expected:
        raise ValueError("VM profile digest mismatch or size limit exceeded")
    profile = json.loads(path.read_bytes())
    if set(profile) != {
        "schema_version",
        "architecture",
        "files",
        "qemu",
        "kernel",
        "firmware",
        "image",
        "libraries",
        "data",
        "python_sha256",
        "python_version",
        "guest_controller_sha256",
    }:
        raise ValueError("unsupported VM profile fields")
    if profile["schema_version"] != 1 or profile["architecture"] != "x86_64":
        raise ValueError("unsupported VM profile version or architecture")
    if profile["guest_controller_sha256"] != _digest(
        Path(__file__).with_name("linux_vm_guest.py")
    ):
        raise ValueError("VM guest controller does not match this Runtime version")
    files = profile["files"]
    if not isinstance(files, dict) or not 4 <= len(files) <= 512:
        raise ValueError("invalid VM input inventory")
    for relative, digest in files.items():
        candidate = _checked_file(root, relative)
        if _digest(candidate) != digest:
            raise ValueError("VM component digest mismatch")
    for key in ("qemu", "kernel", "firmware", "image"):
        if profile[key] not in files:
            raise ValueError("VM component missing from verified inventory")
    for key in ("libraries", "data"):
        directory = profile[key]
        if (
            not isinstance(directory, str)
            or not directory
            or "/" in directory
            or directory in {".", ".."}
        ):
            raise ValueError("invalid VM host input directory")
        directory_root = root / directory
        if directory_root.exists():
            info = directory_root.lstat()
            if (
                not stat.S_ISDIR(info.st_mode)
                or info.st_mode & 0o022
                or info.st_uid not in {0, os.getuid()}
            ):
                raise ValueError("VM input directory is not operator-controlled")
            # The loader must never discover an unverified extra DSO or ROM.
            actual = {p.relative_to(root).as_posix() for p in directory_root.iterdir()}
            if actual != {p for p in files if p.startswith(directory + "/")}:
                raise ValueError("VM directory inventory mismatch")
    if not Path("/usr/bin/setpriv").is_file():
        raise ValueError("trusted parent-death-signal helper unavailable")
    return root, profile


def supported(policy: SandboxPolicy) -> bool:
    if (
        platform.machine() != "x86_64"
        or policy.network_allowed
        or policy.isolation_level != "strict"
        or policy.write_allowed_paths
    ):
        return False
    try:
        _, profile = load_profile()
        return (
            _digest(Path(policy.executable).resolve(strict=True))
            == profile["python_sha256"]
        )
    except (OSError, ValueError, TypeError, KeyError):
        return False


def cpio(entries: list[tuple[str, bytes, int]]) -> bytes:
    """Create a deterministic newc archive; paths are host-controlled."""
    output = bytearray()
    for ino, (name, data, mode) in enumerate([*entries, ("TRAILER!!!", b"", 0)], 1):
        path = PurePosixPath(name)
        if path.is_absolute() or ".." in path.parts or "\\" in name or "\0" in name:
            raise ValueError("unsafe guest archive path")
        encoded = name.encode() + b"\0"
        fields = [ino, mode, 0, 0, 1, 0, len(data), 0, 0, 0, 0, len(encoded), 0]
        output.extend(b"070701" + b"".join(f"{v:08x}".encode() for v in fields))
        output.extend(encoded)
        output.extend(b"\0" * (-len(output) % 4))
        output.extend(data)
        output.extend(b"\0" * (-len(output) % 4))
    return gzip.compress(output, mtime=0)


def _request(policy: SandboxPolicy, staged: Path, key: bytes, nonce: str) -> bytes:
    root = Path(policy.working_dir).resolve(strict=True)

    def argument(value: str) -> str:
        if value == str(root) or value.startswith(str(root) + "/"):
            return "/project" + value[len(str(root)) :]
        return value

    request = {
        "key": key.hex(),
        "nonce": nonce,
        "args": [argument(v) for v in policy.args],
        "env": dict(policy.env),
        "memory": policy.max_memory_bytes,
        "cpu": policy.max_cpu_time_seconds,
        "processes": policy.max_processes,
        "file_size": min(policy.max_staging_bytes, policy.max_memory_bytes),
        "output": policy.max_output_bytes,
        "timeout_seconds": policy.timeout_seconds,
    }
    data = json.dumps(request).encode()
    if len(data) > 65536:
        raise ValueError("VM request exceeds size bound")
    entries = [
        ("control", b"", stat.S_IFDIR | 0o700),
        ("control/request.json", data, stat.S_IFREG | 0o400),
        ("project", b"", stat.S_IFDIR | 0o555),
    ]
    for path in sorted(staged.rglob("*")):
        name = "project/" + path.relative_to(staged).as_posix()
        mode = stat.S_IFDIR | 0o555 if path.is_dir() else stat.S_IFREG | 0o444
        entries.append((name, b"" if path.is_dir() else path.read_bytes(), mode))
    return cpio(entries)


def _bounded_project(root: Path, policy: SandboxPolicy) -> None:
    """Bound hostile directory input before the shared snapshot walker sorts it."""
    entries = size = 0
    for directory, directories, files in os.walk(root, followlinks=False):
        for name in directories + files:
            info = (Path(directory) / name).lstat()
            entries += 1
            size += info.st_size if stat.S_ISREG(info.st_mode) else 0
            if entries > policy.max_staging_files or size > policy.max_staging_bytes:
                raise ValueError("project snapshot exceeds staging limits")


def _authenticated(line: bytes, key: bytes, nonce: str) -> dict | None:
    if not line.startswith(b"APEIR_VM:"):
        return None
    _, signature, encoded = line.strip().split(b":", 2)
    data = base64.b64decode(encoded, validate=True)
    if not hmac.compare_digest(
        signature.decode(), hmac.new(key, data, hashlib.sha256).hexdigest()
    ):
        raise ValueError("unauthenticated VM result")
    value = json.loads(data)
    if value.get("nonce") != nonce:
        raise ValueError("VM result belongs to another invocation")
    return value


def run(policy: SandboxPolicy, input_bytes: bytes | None = None) -> SandboxResult:
    """Run a read-only Python test in one disposable, networkless guest."""
    started = time.monotonic()
    result = SandboxResult(exit_code=-1, availability_state="unavailable")
    process = None
    if input_bytes:
        result.stderr = "STRICT_SANDBOX_UNSUPPORTED: guest stdin is not supported"
        return result
    try:
        if not supported(policy):
            raise ValueError("read-only Python VM profile does not support this policy")
        if not (
            1 <= policy.max_processes <= 64
            and 1 <= policy.max_cpu_time_seconds <= 3600
            and 1024 <= policy.max_output_bytes <= 10 * 1024 * 1024
            and 32 * 1024**2 <= policy.max_memory_bytes <= 2 * 1024**3
            and policy.timeout_seconds <= 3600
            and 1 <= policy.max_staging_files <= 100_000
            and 1 <= policy.max_staging_bytes <= 512 * 1024**2
        ):
            raise ValueError("VM resource policy exceeds supported bounds")
        if policy.cancel_file and Path(policy.cancel_file).exists():
            return SandboxResult(
                exit_code=130, stderr="Execution cancelled before VM startup"
            )
        root, profile = load_profile()
        workspace = Path(os.path.abspath(policy.working_dir))
        for parent in (workspace, *workspace.parents):
            if parent.is_symlink():
                raise ValueError("symlinked project roots are unsupported")
        if set(map(os.path.abspath, policy.read_allowed_paths)) != {str(workspace)}:
            raise ValueError("VM requires one explicitly granted project directory")
        _bounded_project(workspace, policy)
        _validate_mapping_root(workspace, policy.deny_paths)
        with tempfile.TemporaryDirectory(prefix="apeir-linux-vm-") as temporary:
            temporary = Path(temporary)
            staged, _ = _stage_mappings(
                [(workspace, "/project", True)], temporary / "snapshot", policy
            )
            input_digest = _tree_digest(staged[0][0])[0]
            key, nonce = os.urandom(32), os.urandom(16).hex()
            initrd = temporary / "input.cpio.gz"
            with initrd.open("wb") as handle:
                handle.write((root / profile["image"]).read_bytes())
                handle.write(_request(policy, staged[0][0], key, nonce))
            command = [
                "/usr/bin/setpriv",
                "--pdeathsig",
                "SIGKILL",
                "--no-new-privs",
                str(root / profile["qemu"]),
                "-L",
                str(root / profile["data"]),
                "-bios",
                str(root / profile["firmware"]),
                "-M",
                "q35",
                "-accel",
                "tcg,thread=single",
                "-cpu",
                "max",
                "-object",
                "rng-random,id=apeir-rng,filename=/dev/urandom",
                "-device",
                "virtio-rng-pci,rng=apeir-rng",
                "-m",
                str(policy.max_memory_bytes // 1024**2 + 192),
                "-smp",
                "1",
                "-nodefaults",
                "-no-user-config",
                "-display",
                "none",
                "-monitor",
                "none",
                "-serial",
                "stdio",
                "-nic",
                "none",
                "-no-reboot",
                "-sandbox",
                "on,obsolete=deny,elevateprivileges=deny,spawn=deny,resourcecontrol=deny",
                "-kernel",
                str(root / profile["kernel"]),
                "-initrd",
                str(initrd),
                "-append",
                "console=ttyS0 panic=-1 apeir.readonly_test_vm=1",
            ]
            environment = {
                "PATH": "/usr/bin:/bin",
                "LC_ALL": "C",
                "LD_LIBRARY_PATH": str(root / profile["libraries"]),
            }
            process = subprocess.Popen(
                command,
                env=environment,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
            selector = selectors.DefaultSelector()
            os.set_blocking(process.stdout.fileno(), False)
            selector.register(process.stdout, selectors.EVENT_READ)
            pending = bytearray()
            diagnostics = bytearray()
            received = 0
            ready = False
            child_started = False
            payload = None
            # One vCPU plus a wall bound no larger than the requested CPU
            # budget also bounds aggregate child CPU, including VM startup.
            deadline = started + min(
                policy.timeout_seconds, policy.max_cpu_time_seconds
            )
            try:
                while process.poll() is None or selector.get_map():
                    if policy.cancel_file and Path(policy.cancel_file).exists():
                        result = SandboxResult(
                            exit_code=130, stderr="Execution cancelled"
                        )
                        break
                    if time.monotonic() >= deadline:
                        result = SandboxResult(
                            exit_code=-1, timed_out=True, stderr="VM deadline exceeded"
                        )
                        break
                    for entry, _ in selector.select(0.05):
                        block = os.read(entry.fileobj.fileno(), 65536)
                        if not block:
                            selector.unregister(entry.fileobj)
                            continue
                        pending.extend(block)
                        diagnostics.extend(block)
                        if len(diagnostics) > 8192:
                            del diagnostics[:-8192]
                        received += len(block)
                        if received > 3 * policy.max_output_bytes + 65536:
                            raise ValueError("VM transport exceeded bounded output")
                        while b"\n" in pending:
                            line, _, tail = pending.partition(b"\n")
                            pending[:] = tail
                            value = _authenticated(
                                bytes(line).rstrip(b"\r"), key, nonce
                            )
                            if value is None:
                                continue
                            if value["kind"] == "ready" and not ready:
                                ready = True
                                process.stdin.write(
                                    f"GO:{nonce}:{max(0, deadline - time.monotonic())}\n".encode()
                                )
                                process.stdin.flush()
                            elif (
                                value["kind"] == "started"
                                and ready
                                and not child_started
                            ):
                                child_started = True
                                log.info(
                                    "Linux VM workload started audit_id=linux-vm-%s",
                                    nonce,
                                )
                            elif (
                                value["kind"] == "result"
                                and child_started
                                and payload is None
                            ):
                                payload = value
                            else:
                                raise ValueError("invalid VM control sequence")
                if payload is not None:
                    out = base64.b64decode(payload["stdout"], validate=True)
                    err = base64.b64decode(payload["stderr"], validate=True)
                    if len(out) + len(err) > policy.max_output_bytes:
                        raise ValueError("VM output exceeds policy")
                    result = SandboxResult(
                        exit_code=int(payload["exit_code"]),
                        stdout=out.decode("utf-8", errors="replace"),
                        stderr=err.decode("utf-8", errors="replace"),
                        stdout_bytes=len(out),
                        stderr_bytes=len(err),
                        timed_out=bool(payload["timed_out"]),
                        output_truncated=bool(payload["output_truncated"]),
                        peak_memory_bytes=int(payload["peak_memory_bytes"]),
                        audit_id="linux-vm-" + nonce,
                        input_snapshot_sha256=input_digest,
                    )
                elif not result.stderr:
                    result.stderr = "VM exited without an authenticated result"
                if payload is None:
                    result.stderr += "\n" + diagnostics.decode(
                        "utf-8", errors="replace"
                    )
            finally:
                selector.close()
    except (OSError, ValueError, TypeError, KeyError) as exc:
        result = SandboxResult(
            exit_code=-1,
            stderr=f"STRICT_SANDBOX_UNAVAILABLE: {exc}",
            availability_state="unavailable",
        )
    finally:
        if process is not None:
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGKILL)
            process.wait()
            process.stdin.close()
            process.stdout.close()
    result.wall_time_seconds = time.monotonic() - started
    return result
