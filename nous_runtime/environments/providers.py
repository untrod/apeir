"""Environment Provider implementations over existing ProcessSandbox and OCI CLIs."""

from __future__ import annotations

import os
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Mapping

from nous_runtime.environments.models import (
    EnvironmentCommand,
    EnvironmentType,
    ExecutionEnvironment,
    MountMode,
)
from nous_runtime.kernel.sandbox import ProcessSandbox, SandboxPolicy
from nous_runtime.execution.executables import resolve_executable
from nous_runtime.schema_registry import ENVIRONMENT_PROVIDER_SCHEMA_VERSION


class EnvironmentProviderError(RuntimeError):
    """A provider failed closed before or during an environment operation."""


@dataclass(frozen=True)
class ProviderExecutionResult:
    ok: bool
    exit_code: int
    stdout: str = ""
    stderr: str = ""
    wall_time_seconds: float = 0.0
    peak_memory_bytes: int = 0
    timed_out: bool = False
    output_truncated: bool = False
    availability_state: str = "available"
    security_grade: str = "unknown"
    enforced_controls: tuple[str, ...] = ()
    unenforced_controls: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "exit_code": self.exit_code,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "wall_time_seconds": self.wall_time_seconds,
            "peak_memory_bytes": self.peak_memory_bytes,
            "timed_out": self.timed_out,
            "output_truncated": self.output_truncated,
            "availability_state": self.availability_state,
            "security_grade": self.security_grade,
            "enforced_controls": list(self.enforced_controls),
            "unenforced_controls": list(self.unenforced_controls),
        }


Runner = Callable[[list[str], str, int, int, Mapping[str, str] | None], ProviderExecutionResult]


def _default_runner(
    argv: list[str],
    cwd: str,
    timeout_seconds: int,
    max_output_bytes: int,
    env: Mapping[str, str] | None = None,
    *,
    memory_limit_mb: int = 512,
    max_processes: int = 64,
    cancel_file: str = "",
) -> ProviderExecutionResult:
    executable = str(argv[0]) if argv else ""
    if executable and not os.path.isabs(executable):
        executable = resolve_executable(executable) or ""
    if not executable:
        return ProviderExecutionResult(ok=False, exit_code=-1, stderr="Executable not found")
    policy = SandboxPolicy(
        executable=executable,
        args=[str(item) for item in argv[1:]],
        working_dir=str(Path(cwd).resolve()),
        env=dict(env or {}),
        max_memory_bytes=max(64, int(memory_limit_mb)) * 1024 * 1024,
        max_cpu_time_seconds=max(1, int(timeout_seconds)),
        max_processes=max(1, min(int(max_processes), 64)),
        max_output_bytes=max(1024, int(max_output_bytes)),
        read_allowed_paths=[str(Path(cwd).resolve())],
        write_allowed_paths=[str(Path(cwd).resolve())],
        network_allowed=False,
        timeout_seconds=max(1, int(timeout_seconds)),
        isolation_level="strict",
        cancel_file=cancel_file,
    )
    result = ProcessSandbox(policy).run()
    return ProviderExecutionResult(
        ok=result.success,
        exit_code=result.exit_code,
        stdout=result.stdout,
        stderr=result.stderr,
        wall_time_seconds=result.wall_time_seconds,
        peak_memory_bytes=result.peak_memory_bytes,
        timed_out=result.timed_out,
        output_truncated=result.output_truncated,
        availability_state=result.availability_state,
        security_grade=result.security_grade,
        enforced_controls=result.enforced_controls,
        unenforced_controls=result.unenforced_controls,
    )


def _under(root: Path, target: Path) -> bool:
    try:
        target.relative_to(root)
        return True
    except ValueError:
        return False


class LocalSandboxProvider:
    """Resource-limited integrated-host environment using the existing ProcessSandbox."""

    provider_id = "local-sandbox"
    contract_version = ENVIRONMENT_PROVIDER_SCHEMA_VERSION

    def __init__(self, runner: Runner = _default_runner) -> None:
        self._runner = runner
        self._logs: dict[str, str] = {}

    def probe(self) -> dict[str, Any]:
        probe_policy = SandboxPolicy(
            executable=str(Path(sys.executable).resolve()),
            working_dir=str(Path.cwd().resolve()),
            network_allowed=False,
            isolation_level="strict",
            require_strong_isolation=True,
        )
        security = ProcessSandbox(probe_policy).security_report()
        available = bool(security["strong"])
        return {
            "provider_id": self.provider_id,
            "contract_version": self.contract_version,
            "available": available,
            "environment_type": EnvironmentType.LOCAL_SANDBOX.value,
            "evidence_level": "strong-vm" if available else "unavailable",
            "hard_network_isolation": available,
            "filesystem_namespace_isolation": available,
            "resource_isolation": str(security["grade"]),
            "enforced_controls": list(security["enforced_controls"]),
            "unenforced_controls": list(security["unenforced_controls"]),
            "limitations": (
                []
                if available
                else [
                    "Windows Sandbox is not ready; complete the pending Windows reboot.",
                    "No ordinary host-process fallback is permitted.",
                ]
            ),
        }

    def prepare(self, environment: ExecutionEnvironment, workspace_root: Path) -> str:
        if environment.environment_type is not EnvironmentType.LOCAL_SANDBOX:
            raise EnvironmentProviderError("LocalSandboxProvider received a non-local environment")
        if environment.device_policy.devices or environment.gpu_policy != "none":
            raise EnvironmentProviderError("local sandbox device and GPU passthrough are unavailable")
        if environment.workspace_mounts:
            raise EnvironmentProviderError("local sandbox cannot provide a host mount namespace; use its isolated scratch workdir")
        workdir = (workspace_root / ".nous" / "environments" / "workdirs" / environment.environment_id).resolve()
        authority = (workspace_root / ".nous" / "environments" / "workdirs").resolve()
        if not _under(authority, workdir):
            raise EnvironmentProviderError("local sandbox workdir escaped environment storage")
        workdir.mkdir(parents=True, exist_ok=True)
        return str(workdir)

    def start(self, environment: ExecutionEnvironment, handle: str) -> None:
        if not self.probe()["available"]:
            raise EnvironmentProviderError(
                "local strong sandbox is unavailable; complete the pending Windows reboot"
            )
        workdir = Path(handle).resolve()
        if not workdir.is_dir():
            raise EnvironmentProviderError("local sandbox workdir is missing")

    def execute(
        self,
        environment: ExecutionEnvironment,
        handle: str,
        command: EnvironmentCommand,
    ) -> ProviderExecutionResult:
        if environment.network_policy.mode != "none":
            raise EnvironmentProviderError("LocalSandboxProvider cannot enforce HTTP host allowlists")
        workdir = Path(handle).resolve()
        cwd = (workdir / Path(*PurePosixPath(command.cwd).parts)).resolve()
        if not _under(workdir, cwd):
            raise EnvironmentProviderError("command cwd escaped the local environment")
        cancel_path = (workdir / command.cancel_file).resolve() if command.cancel_file else None
        if cancel_path is not None and not _under(workdir, cancel_path):
            raise EnvironmentProviderError("cancellation marker escaped the local environment")
        cwd.mkdir(parents=True, exist_ok=True)
        argv = list(command.argv)
        candidate = Path(argv[0])
        if candidate.is_absolute():
            executable = candidate.resolve()
        elif len(candidate.parts) > 1:
            executable = (cwd / candidate).resolve()
            if not _under(workdir, executable):
                raise EnvironmentProviderError("environment executable escaped the workdir")
        else:
            found = resolve_executable(argv[0])
            if not found:
                return ProviderExecutionResult(ok=False, exit_code=-1, stderr=f"Executable not found: {argv[0]}")
            executable = Path(found).resolve()
        argv[0] = str(executable)
        if self._runner is _default_runner:
            result = _default_runner(
                argv,
                str(cwd),
                command.timeout_seconds,
                command.max_output_bytes,
                command.env,
                memory_limit_mb=environment.memory_limit_mb,
                max_processes=64,
                cancel_file=str(cancel_path) if cancel_path is not None else "",
            )
        else:
            result = self._runner(
                argv,
                str(cwd),
                command.timeout_seconds,
                command.max_output_bytes,
                command.env,
            )
        self._logs[environment.environment_id] = (
            f"$ {' '.join(command.argv)}\n{result.stdout}{result.stderr}"
        )[-2_000_000:]
        return result

    def stop(self, environment: ExecutionEnvironment, handle: str) -> None:
        if not Path(handle).exists():
            raise EnvironmentProviderError("local sandbox workdir is missing")

    def destroy(self, environment: ExecutionEnvironment, handle: str) -> None:
        workdir = Path(handle).resolve()
        expected = f"workdirs{os.sep}{environment.environment_id}".casefold()
        if expected not in str(workdir).casefold():
            raise EnvironmentProviderError("refusing to remove an unrecognized local environment path")
        if workdir.is_dir():
            for path in sorted(workdir.rglob("*"), key=lambda item: len(item.parts), reverse=True):
                if path.is_symlink() or path.is_file():
                    path.unlink(missing_ok=True)
                elif path.is_dir():
                    path.rmdir()
            workdir.rmdir()
        self._logs.pop(environment.environment_id, None)

    def logs(self, environment: ExecutionEnvironment, handle: str) -> str:
        return self._logs.get(environment.environment_id, "")


class OCIContainerProvider:
    """Engine-neutral OCI provider; Docker/Podman details remain behind this adapter."""

    provider_id = "oci"
    contract_version = ENVIRONMENT_PROVIDER_SCHEMA_VERSION

    def __init__(self, engine_path: str = "", runner: Runner = _default_runner) -> None:
        self._engine = engine_path or shutil.which("docker") or shutil.which("podman") or ""
        self._runner = runner

    @property
    def engine_name(self) -> str:
        return Path(self._engine).stem.casefold() if self._engine else ""

    def probe(self) -> dict[str, Any]:
        available = bool(self._engine)
        return {
            "provider_id": self.provider_id,
            "contract_version": self.contract_version,
            "available": available,
            "environment_type": EnvironmentType.OCI_CONTAINER.value,
            "engine": self.engine_name,
            "engine_path": self._engine,
            "evidence_level": "static" if not available else "middleware",
            "hard_network_isolation": available,
            "filesystem_namespace_isolation": available,
            "default_security": {
                "network": "none",
                "host_filesystem": "none",
                "privileged": False,
                "host_devices": "none",
                "engine_socket": "none",
                "host_pid": False,
                "host_network": False,
            },
            "limitations": [] if available else ["No Docker or Podman engine is installed on this host."],
        }

    def _require_engine(self) -> None:
        if not self._engine:
            raise EnvironmentProviderError("OCI provider is unavailable: Docker or Podman was not found")

    def build_create_command(self, environment: ExecutionEnvironment, workspace_root: Path) -> list[str]:
        self._require_engine()
        if environment.environment_type is not EnvironmentType.OCI_CONTAINER:
            raise EnvironmentProviderError("OCIContainerProvider received a non-OCI environment")
        if environment.network_policy.mode != "none":
            raise EnvironmentProviderError(
                "OCI HTTP allowlists require a governed egress proxy and are unavailable in v1"
            )
        if environment.device_policy.devices:
            raise EnvironmentProviderError("host device passthrough is unavailable in OCI provider v1")
        if environment.gpu_policy != "none":
            raise EnvironmentProviderError("GPU passthrough is unavailable in OCI provider v1")
        name = f"nous-{environment.environment_id[-12:]}"
        argv = [
            self._engine,
            "create",
            "--name",
            name,
            "--label",
            f"nous.environment_id={environment.environment_id}",
            "--network",
            "none",
            "--read-only",
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges",
            "--pids-limit",
            "64",
            "--memory",
            f"{environment.memory_limit_mb}m",
            "--cpus",
            str(environment.cpu_limit),
            "--user",
            "65532:65532",
        ]
        temporary_mb = environment.filesystem_policy.temporary_filesystem_mb
        if temporary_mb:
            argv.extend(["--tmpfs", f"/tmp:rw,noexec,nosuid,nodev,size={temporary_mb}m"])
        root = workspace_root.resolve()
        for mount in environment.workspace_mounts:
            source = (root / Path(*PurePosixPath(mount.source).parts)).resolve()
            if not _under(root, source):
                raise EnvironmentProviderError("workspace mount escaped the active workspace")
            if "docker.sock" in str(source).casefold() or "podman.sock" in str(source).casefold():
                raise EnvironmentProviderError("container engine sockets cannot be mounted")
            if mount.mode is MountMode.ARTIFACT_OUTPUT_ONLY:
                source.mkdir(parents=True, exist_ok=True)
            elif not source.exists():
                raise EnvironmentProviderError(f"workspace mount source does not exist: {mount.source}")
            mode = "ro" if mount.mode is MountMode.READ_ONLY else "rw"
            argv.extend(["--volume", f"{source}:{mount.target}:{mode}"])
        argv.extend(
            [
                environment.image,
                "/bin/sh",
                "-c",
                "trap 'exit 0' TERM INT; while :; do sleep 3600; done",
            ]
        )
        forbidden = {"--privileged", "--pid=host", "--network=host"}
        if forbidden.intersection(argv):
            raise EnvironmentProviderError("unsafe OCI option was generated")
        return argv

    def prepare(self, environment: ExecutionEnvironment, workspace_root: Path) -> str:
        argv = self.build_create_command(environment, workspace_root)
        result = self._runner(argv, str(workspace_root), 120, 1_000_000, None)
        if not result.ok:
            raise EnvironmentProviderError(f"OCI create failed: {result.stderr or result.stdout}")
        return f"nous-{environment.environment_id[-12:]}"

    def start(self, environment: ExecutionEnvironment, handle: str) -> None:
        self._require_engine()
        result = self._runner([self._engine, "start", handle], os.getcwd(), 60, 1_000_000, None)
        if not result.ok:
            raise EnvironmentProviderError(f"OCI start failed: {result.stderr or result.stdout}")

    def execute(
        self,
        environment: ExecutionEnvironment,
        handle: str,
        command: EnvironmentCommand,
    ) -> ProviderExecutionResult:
        self._require_engine()
        workdir = PurePosixPath("/model-workspace") / PurePosixPath(command.cwd)
        argv = [self._engine, "exec", "--workdir", workdir.as_posix()]
        for key, value in sorted(command.env.items()):
            argv.extend(["--env", f"{key}={value}"])
        argv.extend([handle, *command.argv])
        return self._runner(argv, os.getcwd(), command.timeout_seconds, command.max_output_bytes, None)

    def stop(self, environment: ExecutionEnvironment, handle: str) -> None:
        self._require_engine()
        result = self._runner([self._engine, "stop", "--time", "5", handle], os.getcwd(), 30, 1_000_000, None)
        if not result.ok:
            raise EnvironmentProviderError(f"OCI stop failed: {result.stderr or result.stdout}")

    def destroy(self, environment: ExecutionEnvironment, handle: str) -> None:
        self._require_engine()
        result = self._runner([self._engine, "rm", "--force", handle], os.getcwd(), 30, 1_000_000, None)
        if not result.ok and "No such container" not in (result.stderr + result.stdout):
            raise EnvironmentProviderError(f"OCI destroy failed: {result.stderr or result.stdout}")

    def logs(self, environment: ExecutionEnvironment, handle: str) -> str:
        self._require_engine()
        result = self._runner([self._engine, "logs", "--tail", "2000", handle], os.getcwd(), 30, 2_000_000, None)
        if not result.ok:
            raise EnvironmentProviderError(f"OCI logs failed: {result.stderr or result.stdout}")
        return result.stdout + result.stderr


class EnvironmentProviderRegistry:
    """One provider resolver for every Environment Runtime consumer."""

    def __init__(self, providers: Mapping[str, Any] | None = None) -> None:
        entries = providers or {
            LocalSandboxProvider.provider_id: LocalSandboxProvider(),
            OCIContainerProvider.provider_id: OCIContainerProvider(),
        }
        self._providers = {str(key): value for key, value in entries.items()}

    def get(self, provider_id: str):
        provider = self._providers.get(str(provider_id))
        if provider is None:
            raise EnvironmentProviderError(f"environment provider is not registered: {provider_id}")
        return provider

    def status(self) -> list[dict[str, Any]]:
        return [self._providers[key].probe() for key in sorted(self._providers)]


__all__ = [
    "EnvironmentProviderError",
    "EnvironmentProviderRegistry",
    "LocalSandboxProvider",
    "OCIContainerProvider",
    "ProviderExecutionResult",
]
