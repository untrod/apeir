"""Stable ExecutionEnvironment contract for governed runtime workloads."""

from __future__ import annotations

import hashlib
import json
import platform
import re
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from enum import Enum
from pathlib import PurePosixPath
from typing import Any, Mapping, Sequence
from uuid import uuid4

from nous_runtime.schema_registry import ENVIRONMENT_SCHEMA_VERSION

_ID_PATTERN = re.compile(r"^env_[a-f0-9]{32}$")
_PROVIDER_PATTERN = re.compile(r"^[a-z][a-z0-9-]{0,63}$")
_MAX_TEXT = 4096
_MAX_MOUNTS = 16
_MAX_ENV_VARS = 64
_SENSITIVE_ENV = ("secret", "token", "password", "credential", "private_key", "api_key")


class EnvironmentValidationError(ValueError):
    """The Environment Contract is malformed or exceeds a safety bound."""


class EnvironmentType(str, Enum):
    LOCAL_SANDBOX = "local_sandbox"
    OCI_CONTAINER = "oci_container"


class EnvironmentState(str, Enum):
    CREATED = "created"
    PREPARING = "preparing"
    READY = "ready"
    RUNNING = "running"
    SUSPENDED = "suspended"
    STOPPING = "stopping"
    STOPPED = "stopped"
    DESTROYED = "destroyed"
    FAILED = "failed"


class MountMode(str, Enum):
    READ_ONLY = "read-only"
    READ_WRITE = "read-write"
    ARTIFACT_OUTPUT_ONLY = "artifact-output-only"


ALLOWED_TRANSITIONS: dict[EnvironmentState, frozenset[EnvironmentState]] = {
    EnvironmentState.CREATED: frozenset({EnvironmentState.PREPARING, EnvironmentState.DESTROYED, EnvironmentState.FAILED}),
    EnvironmentState.PREPARING: frozenset({EnvironmentState.READY, EnvironmentState.FAILED, EnvironmentState.STOPPING}),
    EnvironmentState.READY: frozenset({EnvironmentState.RUNNING, EnvironmentState.STOPPING, EnvironmentState.DESTROYED, EnvironmentState.FAILED}),
    EnvironmentState.RUNNING: frozenset({EnvironmentState.READY, EnvironmentState.SUSPENDED, EnvironmentState.STOPPING, EnvironmentState.FAILED}),
    EnvironmentState.SUSPENDED: frozenset({EnvironmentState.RUNNING, EnvironmentState.STOPPING, EnvironmentState.FAILED}),
    EnvironmentState.STOPPING: frozenset({EnvironmentState.STOPPED, EnvironmentState.FAILED}),
    EnvironmentState.STOPPED: frozenset({EnvironmentState.PREPARING, EnvironmentState.DESTROYED, EnvironmentState.FAILED}),
    EnvironmentState.DESTROYED: frozenset(),
    EnvironmentState.FAILED: frozenset({EnvironmentState.PREPARING, EnvironmentState.STOPPING, EnvironmentState.DESTROYED}),
}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _text(value: Any, field_name: str, *, required: bool = False, maximum: int = _MAX_TEXT) -> str:
    result = str(value or "").strip()
    if required and not result:
        raise EnvironmentValidationError(f"{field_name} is required")
    if len(result) > maximum:
        raise EnvironmentValidationError(f"{field_name} exceeds {maximum} characters")
    return result


def _enum(enum_type, value: Any, field_name: str):
    try:
        return value if isinstance(value, enum_type) else enum_type(str(value))
    except ValueError as exc:
        allowed = ", ".join(item.value for item in enum_type)
        raise EnvironmentValidationError(f"{field_name} must be one of: {allowed}") from exc


def _relative_path(value: Any, field_name: str, *, allow_dot: bool = True) -> str:
    text = _text(value, field_name, required=True, maximum=512).replace("\\", "/")
    path = PurePosixPath(text)
    if path.is_absolute() or ".." in path.parts:
        raise EnvironmentValidationError(f"{field_name} must remain workspace-relative")
    normalized = path.as_posix()
    if not allow_dot and normalized in {"", "."}:
        raise EnvironmentValidationError(f"{field_name} cannot be the workspace root")
    return normalized


def _container_path(value: Any) -> str:
    text = _text(value, "container_path", required=True, maximum=512).replace("\\", "/")
    path = PurePosixPath(text)
    if not path.is_absolute() or ".." in path.parts:
        raise EnvironmentValidationError("container_path must be an absolute container path")
    normalized = path.as_posix()
    if normalized != "/model-workspace" and not normalized.startswith("/model-workspace/"):
        raise EnvironmentValidationError("container_path must remain below /model-workspace")
    return normalized


@dataclass(frozen=True)
class WorkspaceMount:
    source: str
    target: str
    mode: MountMode = MountMode.READ_ONLY

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "WorkspaceMount":
        if not isinstance(value, Mapping):
            raise EnvironmentValidationError("workspace mount must be an object")
        unknown = set(value) - {"source", "target", "mode"}
        if unknown:
            raise EnvironmentValidationError(f"unknown workspace mount fields: {sorted(unknown)}")
        source = _relative_path(value.get("source") or ".", "workspace mount source")
        target = _container_path(value.get("target") or "/model-workspace")
        mode = _enum(MountMode, value.get("mode") or MountMode.READ_ONLY.value, "workspace mount mode")
        lowered = f"{source}/{target}".casefold()
        if "docker.sock" in lowered or "podman.sock" in lowered:
            raise EnvironmentValidationError("container engine sockets cannot be mounted")
        if mode is MountMode.ARTIFACT_OUTPUT_ONLY and not (
            source == "artifacts" or source.startswith("artifacts/")
        ):
            raise EnvironmentValidationError("artifact-output-only sources must remain below artifacts/")
        return cls(source=source, target=target, mode=mode)

    def to_dict(self) -> dict[str, str]:
        return {"source": self.source, "target": self.target, "mode": self.mode.value}


@dataclass(frozen=True)
class NetworkPolicy:
    mode: str = "none"
    allowed_hosts: tuple[str, ...] = ()

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any] | None) -> "NetworkPolicy":
        data = dict(value or {})
        unknown = set(data) - {"mode", "allowed_hosts"}
        if unknown:
            raise EnvironmentValidationError(f"unknown network policy fields: {sorted(unknown)}")
        mode = _text(data.get("mode") or "none", "network_policy.mode", required=True, maximum=32).lower()
        if mode not in {"none", "http"}:
            raise EnvironmentValidationError("network_policy.mode must be none or http")
        hosts_value = data.get("allowed_hosts") or []
        if not isinstance(hosts_value, Sequence) or isinstance(hosts_value, (str, bytes)):
            raise EnvironmentValidationError("network_policy.allowed_hosts must be an array")
        hosts = tuple(dict.fromkeys(_text(item, "allowed host", required=True, maximum=253).lower() for item in hosts_value))
        if len(hosts) > 32:
            raise EnvironmentValidationError("network policy exceeds 32 allowed hosts")
        if mode == "none" and hosts:
            raise EnvironmentValidationError("network_policy.allowed_hosts requires http mode")
        return cls(mode=mode, allowed_hosts=hosts)

    def to_dict(self) -> dict[str, Any]:
        return {"mode": self.mode, "allowed_hosts": list(self.allowed_hosts)}


@dataclass(frozen=True)
class FilesystemPolicy:
    read_only_root: bool = True
    temporary_filesystem_mb: int = 64

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any] | None) -> "FilesystemPolicy":
        data = dict(value or {})
        unknown = set(data) - {"read_only_root", "temporary_filesystem_mb"}
        if unknown:
            raise EnvironmentValidationError(f"unknown filesystem policy fields: {sorted(unknown)}")
        read_only_root = data.get("read_only_root", True)
        if not isinstance(read_only_root, bool):
            raise EnvironmentValidationError("filesystem_policy.read_only_root must be a boolean")
        temporary = int(data["temporary_filesystem_mb"]) if "temporary_filesystem_mb" in data else 64
        if not read_only_root:
            raise EnvironmentValidationError("filesystem root must remain read-only")
        if temporary < 0 or temporary > 4096:
            raise EnvironmentValidationError("temporary_filesystem_mb must be between 0 and 4096")
        return cls(read_only_root=True, temporary_filesystem_mb=temporary)

    def to_dict(self) -> dict[str, Any]:
        return {"read_only_root": self.read_only_root, "temporary_filesystem_mb": self.temporary_filesystem_mb}


@dataclass(frozen=True)
class DevicePolicy:
    gpu: str = "none"
    devices: tuple[str, ...] = ()

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any] | None, *, gpu_policy: Any = "none") -> "DevicePolicy":
        data = dict(value or {})
        unknown = set(data) - {"gpu", "devices"}
        if unknown:
            raise EnvironmentValidationError(f"unknown device policy fields: {sorted(unknown)}")
        gpu = _text(data.get("gpu") or gpu_policy or "none", "gpu_policy", required=True, maximum=32).lower()
        if gpu not in {"none", "compute"}:
            raise EnvironmentValidationError("gpu_policy must be none or compute")
        raw_devices = data.get("devices") or []
        if not isinstance(raw_devices, Sequence) or isinstance(raw_devices, (str, bytes)):
            raise EnvironmentValidationError("device_policy.devices must be an array")
        devices = tuple(dict.fromkeys(_text(item, "device", required=True, maximum=128) for item in raw_devices))
        if len(devices) > 16:
            raise EnvironmentValidationError("device policy exceeds 16 devices")
        return cls(gpu=gpu, devices=devices)

    def to_dict(self) -> dict[str, Any]:
        return {"gpu": self.gpu, "devices": list(self.devices)}


@dataclass(frozen=True)
class ExecutionEnvironment:
    environment_id: str
    provider: str
    environment_type: EnvironmentType
    image: str = ""
    architecture: str = field(default_factory=lambda: platform.machine().lower() or "unknown")
    os: str = field(default_factory=lambda: platform.system().lower() or "unknown")
    cpu_limit: float = 1.0
    memory_limit_mb: int = 512
    gpu_policy: str = "none"
    network_policy: NetworkPolicy = field(default_factory=NetworkPolicy)
    filesystem_policy: FilesystemPolicy = field(default_factory=FilesystemPolicy)
    device_policy: DevicePolicy = field(default_factory=DevicePolicy)
    workspace_mounts: tuple[WorkspaceMount, ...] = ()
    lifetime_seconds: int = 3600
    task_id: str = ""
    run_id: str = ""
    trace_id: str = ""
    state: EnvironmentState = EnvironmentState.CREATED
    provider_handle: str = ""
    created_at: str = field(default_factory=_utc_now)
    updated_at: str = field(default_factory=_utc_now)
    last_error: str = ""
    metadata: Mapping[str, Any] = field(default_factory=dict)
    schema_version: str = ENVIRONMENT_SCHEMA_VERSION

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any], *, new_identity: bool = False) -> "ExecutionEnvironment":
        if not isinstance(value, Mapping):
            raise EnvironmentValidationError("environment must be an object")
        allowed_fields = {
            "schema_version", "environment_id", "provider", "environment_type",
            "image", "architecture", "os", "cpu_limit", "memory_limit_mb",
            "memory_limit", "gpu_policy", "network_policy", "filesystem_policy",
            "device_policy", "workspace_mounts", "lifetime_seconds", "lifetime",
            "task_id", "run_id", "trace_id", "state", "provider_handle",
            "created_at", "updated_at", "last_error", "metadata",
        }
        unknown = set(value) - allowed_fields
        if unknown:
            raise EnvironmentValidationError(f"unknown environment fields: {sorted(unknown)}")
        environment_id = (
            f"env_{uuid4().hex}"
            if new_identity
            else _text(value.get("environment_id"), "environment_id", required=True, maximum=36)
        )
        if not _ID_PATTERN.fullmatch(environment_id):
            raise EnvironmentValidationError("environment_id is invalid")
        environment_type = _enum(
            EnvironmentType,
            value.get("environment_type") or EnvironmentType.LOCAL_SANDBOX.value,
            "environment_type",
        )
        provider = _text(
            value.get("provider") or ("local-sandbox" if environment_type is EnvironmentType.LOCAL_SANDBOX else "oci"),
            "provider",
            required=True,
            maximum=64,
        ).lower()
        if not _PROVIDER_PATTERN.fullmatch(provider):
            raise EnvironmentValidationError("provider is invalid")
        image = _text(value.get("image"), "image", maximum=512)
        if environment_type is EnvironmentType.OCI_CONTAINER and not image:
            raise EnvironmentValidationError("image is required for an OCI container")
        if any(character.isspace() for character in image):
            raise EnvironmentValidationError("image cannot contain whitespace")
        cpu_limit = float(value["cpu_limit"]) if "cpu_limit" in value else 1.0
        memory_limit = (
            int(value["memory_limit_mb"])
            if "memory_limit_mb" in value
            else int(value["memory_limit"])
            if "memory_limit" in value
            else 512
        )
        if cpu_limit < 0.1 or cpu_limit > 64:
            raise EnvironmentValidationError("cpu_limit must be between 0.1 and 64")
        if memory_limit < 64 or memory_limit > 131072:
            raise EnvironmentValidationError("memory_limit_mb must be between 64 and 131072")
        lifetime = (
            int(value["lifetime_seconds"])
            if "lifetime_seconds" in value
            else int(value["lifetime"])
            if "lifetime" in value
            else 3600
        )
        if lifetime < 60 or lifetime > 604800:
            raise EnvironmentValidationError("lifetime_seconds must be between 60 and 604800")
        raw_mounts = value.get("workspace_mounts") or []
        if not isinstance(raw_mounts, Sequence) or isinstance(raw_mounts, (str, bytes)):
            raise EnvironmentValidationError("workspace_mounts must be an array")
        if len(raw_mounts) > _MAX_MOUNTS:
            raise EnvironmentValidationError(f"workspace_mounts exceeds {_MAX_MOUNTS} entries")
        mounts = tuple(WorkspaceMount.from_mapping(item) for item in raw_mounts)
        targets = [item.target.casefold() for item in mounts]
        if len(set(targets)) != len(targets):
            raise EnvironmentValidationError("workspace mount targets must be unique")
        network_policy = NetworkPolicy.from_mapping(value.get("network_policy"))
        filesystem_policy = FilesystemPolicy.from_mapping(value.get("filesystem_policy"))
        device_policy = DevicePolicy.from_mapping(value.get("device_policy"), gpu_policy=value.get("gpu_policy"))
        raw_metadata = value.get("metadata") or {}
        if not isinstance(raw_metadata, Mapping):
            raise EnvironmentValidationError("metadata must be an object")
        metadata = dict(raw_metadata)
        try:
            metadata_bytes = len(json.dumps(metadata, ensure_ascii=False, sort_keys=True).encode("utf-8"))
        except (TypeError, ValueError) as exc:
            raise EnvironmentValidationError("metadata must be JSON serializable") from exc
        if metadata_bytes > 32768:
            raise EnvironmentValidationError("metadata exceeds 32768 bytes")
        now = _utc_now()
        state = (
            EnvironmentState.CREATED
            if new_identity
            else _enum(EnvironmentState, value.get("state") or EnvironmentState.CREATED.value, "state")
        )
        provider_handle = "" if new_identity else _text(value.get("provider_handle"), "provider_handle", maximum=256)
        created_at = now if new_identity else _text(value.get("created_at") or now, "created_at", required=True, maximum=64)
        updated_at = now if new_identity else _text(value.get("updated_at") or now, "updated_at", required=True, maximum=64)
        last_error = "" if new_identity else _text(value.get("last_error"), "last_error", maximum=2048)
        schema = _text(value.get("schema_version") or ENVIRONMENT_SCHEMA_VERSION, "schema_version", required=True, maximum=64)
        if schema != ENVIRONMENT_SCHEMA_VERSION:
            raise EnvironmentValidationError(
                f"unsupported Environment Contract: {schema}; expected {ENVIRONMENT_SCHEMA_VERSION}"
            )
        return cls(
            environment_id=environment_id,
            provider=provider,
            environment_type=environment_type,
            image=image,
            architecture=_text(value.get("architecture") or platform.machine().lower() or "unknown", "architecture", required=True, maximum=64).lower(),
            os=_text(value.get("os") or ("linux" if environment_type is EnvironmentType.OCI_CONTAINER else platform.system().lower()), "os", required=True, maximum=64).lower(),
            cpu_limit=cpu_limit,
            memory_limit_mb=memory_limit,
            gpu_policy=device_policy.gpu,
            network_policy=network_policy,
            filesystem_policy=filesystem_policy,
            device_policy=device_policy,
            workspace_mounts=mounts,
            lifetime_seconds=lifetime,
            task_id=_text(value.get("task_id"), "task_id", maximum=128),
            run_id=_text(value.get("run_id"), "run_id", maximum=128),
            trace_id=_text(value.get("trace_id"), "trace_id", maximum=128),
            state=state,
            provider_handle=provider_handle,
            created_at=created_at,
            updated_at=updated_at,
            last_error=last_error,
            metadata=metadata,
            schema_version=schema,
        )

    def transition(self, state: EnvironmentState, **changes: Any) -> "ExecutionEnvironment":
        target = _enum(EnvironmentState, state, "state")
        if target not in ALLOWED_TRANSITIONS[self.state]:
            raise EnvironmentValidationError(f"invalid environment transition: {self.state.value} -> {target.value}")
        return replace(self, state=target, updated_at=_utc_now(), **changes)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "environment_id": self.environment_id,
            "provider": self.provider,
            "environment_type": self.environment_type.value,
            "image": self.image,
            "architecture": self.architecture,
            "os": self.os,
            "cpu_limit": self.cpu_limit,
            "memory_limit_mb": self.memory_limit_mb,
            "gpu_policy": self.gpu_policy,
            "network_policy": self.network_policy.to_dict(),
            "filesystem_policy": self.filesystem_policy.to_dict(),
            "device_policy": self.device_policy.to_dict(),
            "workspace_mounts": [item.to_dict() for item in self.workspace_mounts],
            "lifetime_seconds": self.lifetime_seconds,
            "task_id": self.task_id,
            "run_id": self.run_id,
            "trace_id": self.trace_id,
            "state": self.state.value,
            "provider_handle": self.provider_handle,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "last_error": self.last_error,
            "metadata": dict(self.metadata),
        }

    def digest(self) -> str:
        encoded = json.dumps(self.to_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True)
class EnvironmentCommand:
    argv: tuple[str, ...]
    cwd: str = "."
    timeout_seconds: int = 60
    max_output_bytes: int = 1_000_000
    env: Mapping[str, str] = field(default_factory=dict)
    cancel_file: str = ""

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "EnvironmentCommand":
        if not isinstance(value, Mapping):
            raise EnvironmentValidationError("command must be an object")
        unknown = set(value) - {"argv", "cwd", "timeout_seconds", "max_output_bytes", "env", "cancel_file"}
        if unknown:
            raise EnvironmentValidationError(f"unknown command fields: {sorted(unknown)}")
        raw_argv = value.get("argv")
        if not isinstance(raw_argv, Sequence) or isinstance(raw_argv, (str, bytes)) or not raw_argv:
            raise EnvironmentValidationError("argv must be a non-empty array")
        if len(raw_argv) > 64:
            raise EnvironmentValidationError("argv exceeds 64 entries")
        argv = tuple(_text(item, "argv entry", required=True, maximum=4096) for item in raw_argv)
        cwd = _relative_path(value.get("cwd") or ".", "cwd")
        cancel_file = (
            _relative_path(value["cancel_file"], "cancel_file", allow_dot=False)
            if value.get("cancel_file") else ""
        )
        if ":" in cancel_file or "\0" in cancel_file:
            raise EnvironmentValidationError("cancel_file must remain workspace-relative")
        timeout = int(value.get("timeout_seconds") or 60)
        output = int(value.get("max_output_bytes") or 1_000_000)
        if timeout < 1 or timeout > 3600:
            raise EnvironmentValidationError("timeout_seconds must be between 1 and 3600")
        if output < 1024 or output > 10_485_760:
            raise EnvironmentValidationError("max_output_bytes must be between 1024 and 10485760")
        raw_env = value.get("env") or {}
        if not isinstance(raw_env, Mapping) or len(raw_env) > _MAX_ENV_VARS:
            raise EnvironmentValidationError(f"env must be an object with at most {_MAX_ENV_VARS} entries")
        environment: dict[str, str] = {}
        for key, item in raw_env.items():
            name = _text(key, "environment variable name", required=True, maximum=128)
            if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name):
                raise EnvironmentValidationError(f"invalid environment variable name: {name}")
            if any(marker in name.casefold() for marker in _SENSITIVE_ENV):
                raise EnvironmentValidationError("inline secret environment variables are forbidden; use a credential reference")
            environment[name] = _text(item, f"environment variable {name}", maximum=4096)
        return cls(argv=argv, cwd=cwd, timeout_seconds=timeout, max_output_bytes=output,
                   env=environment, cancel_file=cancel_file)

    def to_dict(self) -> dict[str, Any]:
        return {
            "argv": list(self.argv),
            "cwd": self.cwd,
            "timeout_seconds": self.timeout_seconds,
            "max_output_bytes": self.max_output_bytes,
            "env": dict(self.env),
            **({"cancel_file": self.cancel_file} if self.cancel_file else {}),
        }


__all__ = [
    "ALLOWED_TRANSITIONS",
    "DevicePolicy",
    "EnvironmentCommand",
    "EnvironmentState",
    "EnvironmentType",
    "EnvironmentValidationError",
    "ExecutionEnvironment",
    "FilesystemPolicy",
    "MountMode",
    "NetworkPolicy",
    "WorkspaceMount",
]
