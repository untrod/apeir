"""R1 Nous Node service with real host probes and durable local state."""

from __future__ import annotations

import hashlib
import json
import math
import os
import platform
import re
import shutil
import signal
import socket
import struct
import sys
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from nous_runtime.artifact.content_store import ContentAddressedArtifactStore
from nous_runtime.connectivity.protocol.identity import NodeIdentity
from nous_runtime.kernel.hardware_discovery import discover_all_devices
from nous_runtime.node_runtime.execution_host import (
    collect_execution_host_inventory,
    evaluate_execution_preflight,
)
from nous_runtime.version import __version__


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


@dataclass(frozen=True)
class NodeRuntimeConfig:
    state_dir: Path
    node_name: str = ""
    heartbeat_seconds: float = 15.0
    telemetry_max_bytes: int = 10 * 1024 * 1024
    artifact_max_bytes: int = 512 * 1024 * 1024

    def __post_init__(self) -> None:
        if self.heartbeat_seconds <= 0:
            raise ValueError("heartbeat_seconds must be positive")
        if self.telemetry_max_bytes < 4096:
            raise ValueError("telemetry_max_bytes must be at least 4096")
        if self.artifact_max_bytes < 1024 * 1024:
            raise ValueError("artifact_max_bytes must be at least 1048576")


class NodeRuntimeService:
    """Own a Node's durable identity, probes, heartbeat and local workloads."""

    def __init__(self, config: NodeRuntimeConfig):
        self.config = config
        self.state_dir = config.state_dir.expanduser().resolve()
        self.artifact_store = ContentAddressedArtifactStore(self.state_dir / "artifacts")
        self.artifact_cache = self.artifact_store.objects
        self.identity_path = self.state_dir / "identity.json"
        self.private_key_path = self.state_dir / "identity.ed25519.pem"
        self.registration_path = self.state_dir / "registration.json"
        self.status_path = self.state_dir / "status.json"
        self.workloads_path = self.state_dir / "workloads.json"
        self.leases_path = self.state_dir / "leases.json"
        self.lease_counter_path = self.state_dir / "lease-counter.json"
        self.transfers_path = self.state_dir / "artifact-transfers"
        self.telemetry_path = self.state_dir / "telemetry.jsonl"
        self._stop = threading.Event()
        self._started_at = ""
        self._sequence = 0
        self._execution_host_inventory: dict[str, Any] | None = None
        self._execution_host_inventory_at = 0.0
        self._workloads: dict[str, dict[str, Any]] = {}
        self._leases: dict[str, dict[str, Any]] = {}
        self._state_lock = threading.RLock()
        self._handlers: dict[str, Callable[[dict[str, Any]], dict[str, Any]]] = {
            "system.echo": lambda arguments: {"echo": arguments.get("message", "")},
            "node.resource-report": lambda _arguments: self.probe_resources(),
            "node.device-report": lambda _arguments: {
                "devices": self.probe_devices()
            },
            "node.execution-host-inventory": lambda _arguments: (
                self.probe_execution_host()
            ),
            "node.execution-host-evidence": self.execution_host_evidence,
            "node.execution-preflight": self.preflight_execution,
        }
        self._prepare_state()
        self.identity = self._load_or_create_identity()
        self._sequence = self._load_heartbeat_sequence()
        self._workloads = self._load_workloads()
        self._leases = self._load_leases()

    def _prepare_state(self) -> None:
        self.artifact_cache.mkdir(parents=True, exist_ok=True)
        self.transfers_path.mkdir(parents=True, exist_ok=True)

    def _load_or_create_identity(self) -> NodeIdentity:
        if self.identity_path.is_file() and self.private_key_path.is_file():
            value = json.loads(self.identity_path.read_text(encoding="utf-8"))
            if not isinstance(value, dict):
                raise ValueError("node identity must be a JSON object")
            identity = NodeIdentity.from_dict(value)
            self._verify_identity_key(identity)
            return identity

        key = Ed25519PrivateKey.generate()
        private_pem = key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
        public = key.public_key().public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        ).hex()
        identity = NodeIdentity.create(
            node_name=self.config.node_name or platform.node() or "nous-node",
            node_role="personal_node",
            platform_os=platform.system(),
            platform_os_version=platform.version(),
            platform_arch=platform.machine(),
            platform_hostname=platform.node(),
            public_key=public,
            capabilities=sorted(self._handlers),
            runtime_version=__version__,
            platform_abi=_platform_abi(),
            runtime_tier="full",
            word_size_bits=struct.calcsize("P") * 8,
        )
        _atomic_write_bytes(self.private_key_path, private_pem)
        try:
            os.chmod(self.private_key_path, 0o600)
        except OSError:
            pass
        _atomic_write_json(self.identity_path, identity.to_dict())
        self._verify_identity_key(identity)
        return identity

    def _verify_identity_key(self, identity: NodeIdentity) -> None:
        try:
            key = serialization.load_pem_private_key(
                self.private_key_path.read_bytes(), password=None
            )
        except (OSError, TypeError, ValueError) as exc:
            raise ValueError("node identity private key is invalid") from exc
        if not isinstance(key, Ed25519PrivateKey):
            raise ValueError("node identity key must be Ed25519")
        actual = key.public_key().public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        ).hex()
        if actual != identity.public_key:
            raise ValueError("node identity does not match private key")

    def _load_heartbeat_sequence(self) -> int:
        """Continue the monotonic heartbeat sequence across process restarts."""
        if not self.status_path.is_file():
            return 0
        try:
            value = json.loads(self.status_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return 0
        if not isinstance(value, dict) or value.get("node_id") != self.identity.node_id:
            return 0
        sequence = value.get("heartbeat_sequence", 0)
        if isinstance(sequence, bool) or not isinstance(sequence, int):
            return 0
        return max(sequence, 0)

    def _load_workloads(self) -> dict[str, dict[str, Any]]:
        if not self.workloads_path.is_file():
            return {}
        try:
            value = json.loads(self.workloads_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError("durable workload state is invalid") from exc
        if not isinstance(value, dict):
            raise ValueError("durable workload state must be an object")
        return {
            key: item
            for key, item in value.items()
            if isinstance(key, str) and isinstance(item, dict)
        }

    def _load_leases(self) -> dict[str, dict[str, Any]]:
        if not self.leases_path.is_file():
            return {}
        try:
            value = json.loads(self.leases_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError("durable lease state is invalid") from exc
        if not isinstance(value, dict):
            raise ValueError("durable lease state must be an object")
        return {
            key: item
            for key, item in value.items()
            if isinstance(key, str) and isinstance(item, dict)
        }

    def acquire_lease(
        self, lease_id: str, resource_id: str, ttl_seconds: float
    ) -> dict[str, Any]:
        """Reserve a node-local resource label; this does not grant Kernel authority."""
        _safe_runtime_id(lease_id, "lease_id")
        _safe_runtime_id(resource_id, "resource_id")
        if isinstance(ttl_seconds, bool) or not isinstance(ttl_seconds, (int, float)):
            raise ValueError("ttl_seconds must be numeric")
        if not math.isfinite(ttl_seconds) or ttl_seconds <= 0 or ttl_seconds > 86_400:
            raise ValueError("ttl_seconds must be in the range 0 < ttl <= 86400")
        now = time.time()
        with self._state_lock:
            self._expire_leases(now)
            existing = self._leases.get(lease_id)
            if existing is not None:
                if existing.get("resource_id") != resource_id:
                    raise ValueError("lease idempotency collision")
                return dict(existing)
            for lease in self._leases.values():
                if lease.get("resource_id") == resource_id:
                    raise ValueError("resource is already leased")
            counter = self._next_fencing_token()
            lease = {
                "schema": "nous.resource-lease/v1",
                "lease_id": lease_id,
                "resource_id": resource_id,
                "owner_node_id": self.identity.node_id,
                "state": "ACTIVE",
                "authority": "none",
                "kernel_traversed": False,
                "resource_enforced": False,
                "fencing_token": counter,
                "acquired_at": _utc_now(),
                "expires_at_epoch": now + float(ttl_seconds),
                "ttl_seconds": float(ttl_seconds),
            }
            self._leases[lease_id] = lease
            _atomic_write_json(self.leases_path, self._leases)
            self._emit("node.lease.acquired", lease)
            return dict(lease)

    def release_lease(self, lease_id: str, resource_id: str) -> dict[str, Any]:
        """Release the exact lease/resource pair; repeated release is idempotent."""
        _safe_runtime_id(lease_id, "lease_id")
        _safe_runtime_id(resource_id, "resource_id")
        with self._state_lock:
            lease = self._leases.get(lease_id)
            if lease is None:
                return {
                    "schema": "nous.resource-lease/v1",
                    "lease_id": lease_id,
                    "resource_id": resource_id,
                    "state": "RELEASED",
                    "idempotent": True,
                }
            if lease.get("resource_id") != resource_id:
                raise ValueError("lease resource does not match")
            released = {**lease, "state": "RELEASED", "released_at": _utc_now()}
            self._leases.pop(lease_id, None)
            _atomic_write_json(self.leases_path, self._leases)
            self._emit("node.lease.released", released)
            return released

    def _expire_leases(self, now: float | None = None) -> None:
        current = time.time() if now is None else now
        expired = [
            lease_id
            for lease_id, lease in self._leases.items()
            if float(lease.get("expires_at_epoch", 0)) <= current
        ]
        if expired:
            for lease_id in expired:
                self._leases.pop(lease_id, None)
            _atomic_write_json(self.leases_path, self._leases)

    def _next_fencing_token(self) -> int:
        value: dict[str, Any] = {}
        if self.lease_counter_path.is_file():
            try:
                loaded = json.loads(self.lease_counter_path.read_text(encoding="utf-8"))
                if not isinstance(loaded, dict) or "counter" not in loaded:
                    raise ValueError("durable fencing counter is invalid")
                value = loaded
            except (OSError, json.JSONDecodeError) as exc:
                raise ValueError("durable fencing counter is invalid") from exc
        previous = value.get("counter", 0)
        if not isinstance(previous, int) or isinstance(previous, bool) or previous < 0:
            raise ValueError("durable fencing counter is invalid")
        counter = previous + 1
        _atomic_write_json(self.lease_counter_path, {"counter": counter})
        return counter

    def ingest_artifact_chunk(
        self,
        *,
        digest: str,
        transfer_id: str,
        offset: int,
        content: bytes,
        total_size: int,
        artifact: dict[str, Any],
        eof: bool,
    ) -> dict[str, Any]:
        """Durably receive a bounded artifact chunk and verify before CAS commit."""
        if not re.fullmatch(r"sha256:[0-9a-f]{64}", digest):
            raise ValueError("invalid artifact digest")
        _safe_runtime_id(transfer_id, "transfer_id")
        if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
            raise ValueError("artifact offset must be a non-negative integer")
        if isinstance(total_size, bool) or not isinstance(total_size, int):
            raise ValueError("artifact total_size must be an integer")
        if total_size < 0 or total_size > self.config.artifact_max_bytes:
            raise ValueError("artifact exceeds configured size limit")
        if not isinstance(content, bytes) or len(content) > 384 * 1024:
            raise ValueError("artifact chunk exceeds 393216 bytes")
        if offset + len(content) > total_size:
            raise ValueError("artifact chunk exceeds declared size")
        part = self.transfers_path / f"{transfer_id}.part"
        with self._state_lock:
            current = part.stat().st_size if part.is_file() else 0
            if offset < current:
                with part.open("rb") as handle:
                    handle.seek(offset)
                    if handle.read(len(content)) != content:
                        raise ValueError("artifact retry content mismatch")
            elif offset != current:
                raise ValueError("artifact chunk offset is not contiguous")
            else:
                with part.open("ab") as handle:
                    handle.write(content)
                    handle.flush()
                    os.fsync(handle.fileno())
            received = part.stat().st_size
            if not eof:
                return {"digest": digest, "state": "RECEIVING", "received_bytes": received}
            if received != total_size:
                raise ValueError("artifact transfer ended before declared size")
            result = self.artifact_store.store_file(
                part,
                expected_digest=digest,
                artifact_type=str(artifact.get("artifact_type") or "binary"),
                name=str(artifact.get("name") or digest),
                media_type=str(artifact.get("media_type") or "application/octet-stream"),
                produced_by="node-relay/v1",
                depends_on=tuple(artifact.get("depends_on") or ()),
                deployed_to=tuple(artifact.get("deployed_to") or ()),
                derived_from=tuple(artifact.get("derived_from") or ()),
                metadata=dict(artifact.get("metadata") or {}),
            )
            part.unlink(missing_ok=True)
            ready = {
                "digest": digest,
                "state": "READY",
                "received_bytes": received,
                "artifact": result["artifact"],
                "receipt": result["receipt"],
            }
            self._emit("node.artifact.ready", ready)
            return ready

    def stop_workload(self, workload_id: str) -> dict[str, Any]:
        """Persist a pre-start cancellation or truthfully report a terminal workload."""
        _safe_runtime_id(workload_id, "workload_id")
        with self._state_lock:
            existing = self._workloads.get(workload_id)
            if existing is not None:
                return {**existing, "stop_result": "ALREADY_TERMINAL"}
            now = _utc_now()
            result = {
                "workload_id": workload_id,
                "capability": "",
                "state": "CANCELLED",
                "started_at": now,
                "finished_at": now,
                "stop_result": "CANCELLED_BEFORE_START",
            }
            self._workloads[workload_id] = result
            _atomic_write_json(self.workloads_path, self._workloads)
            self._emit("node.workload.cancelled", result)
            return dict(result)

    def load_private_key(self) -> Ed25519PrivateKey:
        """Load and verify the durable node signing key."""
        key = serialization.load_pem_private_key(
            self.private_key_path.read_bytes(), password=None
        )
        if not isinstance(key, Ed25519PrivateKey):
            raise ValueError("node identity key must be Ed25519")
        return key

    def register_local(self) -> dict[str, Any]:
        registration = {
            "schema": "nous.node-registration/v1",
            "node_id": self.identity.node_id,
            "identity_hash": self.identity.identity_hash(),
            "registered_at": _utc_now(),
            "scope": "local",
            "authority": "none",
        }
        if self.registration_path.is_file():
            existing = json.loads(self.registration_path.read_text(encoding="utf-8"))
            if (
                isinstance(existing, dict)
                and existing.get("node_id") == self.identity.node_id
                and existing.get("identity_hash") == self.identity.identity_hash()
            ):
                return existing
            raise ValueError("node registration does not match durable identity")
        _atomic_write_json(self.registration_path, registration)
        return registration

    def probe_resources(self) -> dict[str, Any]:
        disk = shutil.disk_usage(self.state_dir)
        memory_total, memory_available = _memory_bytes()
        addresses = sorted(
            {
                item[4][0]
                for item in socket.getaddrinfo(socket.gethostname(), None)
                if item and item[4] and item[4][0]
            }
        )
        return {
            "schema": "nous.node-resource-report/v1",
            "measured_at": _utc_now(),
            "os": platform.system(),
            "os_version": platform.version(),
            "architecture": platform.machine(),
            "hostname": platform.node(),
            "cpu_logical": os.cpu_count() or 1,
            "memory_total_bytes": memory_total,
            "memory_available_bytes": memory_available,
            "disk_total_bytes": disk.total,
            "disk_free_bytes": disk.free,
            "network_addresses": addresses,
            "uptime_seconds": _uptime_seconds(),
            "measurement_source": "host-os",
        }

    def probe_devices(self) -> list[dict[str, Any]]:
        devices = []
        for device in discover_all_devices():
            value = device.to_dict()
            value["probe_source"] = "nous.kernel.hardware_discovery"
            devices.append(value)
        return devices

    def probe_execution_host(
        self, resources: dict[str, Any] | None = None, *, refresh: bool = False
    ) -> dict[str, Any]:
        """Report host facts without granting or implying authorization."""
        now = time.monotonic()
        if (
            not refresh
            and self._execution_host_inventory is not None
            and now - self._execution_host_inventory_at < 300
        ):
            return dict(self._execution_host_inventory)
        inventory = collect_execution_host_inventory(resources or self.probe_resources())
        self._execution_host_inventory = inventory
        self._execution_host_inventory_at = now
        return dict(inventory)

    def preflight_execution(self, requirements: dict[str, Any]) -> dict[str, Any]:
        """Check whether this host meets declared execution requirements."""
        return evaluate_execution_preflight(self.probe_execution_host(), requirements)

    def execution_host_evidence(self, arguments: dict[str, Any]) -> dict[str, Any]:
        """Store canonical host facts as content-addressed evidence, never authority."""
        refresh = arguments.get("refresh", False)
        if not isinstance(refresh, bool):
            raise TypeError("refresh must be a boolean")
        inventory = self.probe_execution_host(refresh=refresh)
        canonical = json.dumps(
            inventory, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        stored = self.artifact_store.store_bytes(
            canonical,
            artifact_type="verification_result",
            name="execution-host-inventory.json",
            media_type="application/vnd.apeir.execution-host-inventory+json",
            produced_by="node.execution-host-evidence/v1",
            metadata={
                "schema": inventory["schema"],
                "authority": "none",
                "grants_capabilities": False,
            },
        )
        artifact = stored["artifact"]
        digest = str(artifact["digest"])
        return {
            "schema": "apeir.execution-host-evidence/v1",
            "evidence_ref": digest,
            "digest": digest.removeprefix("sha256:"),
            "artifact": artifact,
            "authority": "none",
            "grants_capabilities": False,
        }

    def execute_workload(
        self,
        workload_id: str,
        capability: str,
        arguments: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if not workload_id or any(part in workload_id for part in ("/", "\\", "..", "\0")):
            raise ValueError("invalid workload_id")
        canonical_arguments = json.dumps(
            arguments or {}, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        if len(canonical_arguments) > 262_144:
            raise ValueError("workload arguments exceed 262144 bytes")
        if workload_id in self._workloads:
            return dict(self._workloads[workload_id])
        started = _utc_now()
        handler = self._handlers.get(capability)
        if handler is None:
            result = {
                "workload_id": workload_id,
                "capability": capability,
                "state": "FAILED",
                "error_code": "NOUS_NODE_CAPABILITY_UNAVAILABLE",
                "started_at": started,
                "finished_at": _utc_now(),
            }
        else:
            try:
                output = handler(dict(arguments or {}))
                result = {
                    "workload_id": workload_id,
                    "capability": capability,
                    "state": "COMPLETED",
                    "output": output,
                    "started_at": started,
                    "finished_at": _utc_now(),
                }
            except Exception as exc:
                result = {
                    "workload_id": workload_id,
                    "capability": capability,
                    "state": "FAILED",
                    "error_code": "NOUS_NODE_WORKLOAD_FAILED",
                    "error": f"{type(exc).__name__}: {exc}",
                    "started_at": started,
                    "finished_at": _utc_now(),
                }
        self._workloads[workload_id] = result
        output_bytes = json.dumps(
            result, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        result["receipt"] = {
            "schema": "nous.operation-receipt/v1",
            "operation_id": workload_id,
            "actor": self.identity.node_id,
            "source": "nous-node",
            "target": capability,
            "requested_capabilities": [capability],
            "granted_capabilities": [capability] if handler is not None else [],
            "input_digest": hashlib.sha256(canonical_arguments).hexdigest(),
            "result": result["state"],
            "timestamps": {
                "started_at": result["started_at"],
                "finished_at": result["finished_at"],
            },
            "policy_version": "node-local-v1",
            "executor": "nous-node/bounded-handler",
            "effect_digest": hashlib.sha256(output_bytes).hexdigest(),
        }
        _atomic_write_json(self.workloads_path, self._workloads)
        self._emit("node.workload.finished", result)
        return dict(result)

    def run_once(self) -> dict[str, Any]:
        if not self._started_at:
            self._started_at = _utc_now()
        registration = self.register_local()
        resources = self.probe_resources()
        devices = self.probe_devices()
        execution_host = self.probe_execution_host(resources)
        self._sequence += 1
        cache_files = [path for path in self.artifact_cache.rglob("*") if path.is_file()]
        status = {
            "schema": "nous.node-status/v1",
            "state": "ONLINE",
            "pid": os.getpid(),
            "node_id": self.identity.node_id,
            "node_name": self.identity.node_name,
            "started_at": self._started_at,
            "last_heartbeat": _utc_now(),
            "heartbeat_sequence": self._sequence,
            "registration": registration,
            "resources": resources,
            "devices": devices,
            "execution_host": execution_host,
            "artifact_cache": {
                "root": str(self.artifact_cache),
                "objects": len(cache_files),
                "bytes": sum(path.stat().st_size for path in cache_files),
            },
            "workloads": list(self._workloads.values()),
            "telemetry": "HEALTHY",
            "watchdog": {"last_tick": _utc_now(), "healthy": True},
            "intelligence_providers": 0,
        }
        _atomic_write_json(self.status_path, status)
        self._emit(
            "node.heartbeat",
            {
                "node_id": self.identity.node_id,
                "sequence": self._sequence,
                "resource_report": resources,
                "device_count": len(devices),
            },
        )
        return status

    def run_forever(self, *, install_signal_handlers: bool = True) -> None:
        if install_signal_handlers and threading.current_thread() is threading.main_thread():
            signal.signal(signal.SIGINT, self._signal_stop)
            signal.signal(signal.SIGTERM, self._signal_stop)
        self._stop.clear()
        self._emit("node.started", {"node_id": self.identity.node_id})
        try:
            while not self._stop.is_set():
                self.run_once()
                self._stop.wait(self.config.heartbeat_seconds)
        finally:
            self._write_stopped_status()
            self._emit("node.stopped", {"node_id": self.identity.node_id})

    def stop(self) -> None:
        self._stop.set()

    def mark_stopped(self) -> None:
        """Persist an explicit stopped state for external transport runners."""
        self.stop()
        self._write_stopped_status()
        self._emit("node.stopped", {"node_id": self.identity.node_id})

    def _signal_stop(self, _signum: int, _frame: Any) -> None:
        self.stop()

    def _write_stopped_status(self) -> None:
        status: dict[str, Any] = {}
        if self.status_path.is_file():
            value = json.loads(self.status_path.read_text(encoding="utf-8"))
            if isinstance(value, dict):
                status = value
        status.update({"state": "STOPPED", "stopped_at": _utc_now()})
        _atomic_write_json(self.status_path, status)

    def _emit(self, event_type: str, payload: dict[str, Any]) -> None:
        if self.telemetry_path.exists() and self.telemetry_path.stat().st_size >= self.config.telemetry_max_bytes:
            rotated = self.telemetry_path.with_suffix(".jsonl.1")
            if rotated.exists():
                rotated.unlink()
            self.telemetry_path.replace(rotated)
        event = {
            "schema": "nous.node-telemetry/v1",
            "event_type": event_type,
            "timestamp": _utc_now(),
            "node_id": self.identity.node_id,
            "payload": payload,
        }
        with self.telemetry_path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n")


def _platform_abi() -> str:
    if os.name == "nt":
        return "msvc"
    libc, _version = platform.libc_ver()
    return libc or "unknown"


def _safe_runtime_id(value: str, field: str) -> None:
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}", value):
        raise ValueError(f"invalid {field}")


def _memory_bytes() -> tuple[int, int]:
    try:
        import psutil

        memory = psutil.virtual_memory()
        return int(memory.total), int(memory.available)
    except ImportError:
        pass
    if os.name == "nt":
        import ctypes

        class MemoryStatus(ctypes.Structure):
            _fields_ = [
                ("length", ctypes.c_ulong),
                ("memory_load", ctypes.c_ulong),
                ("total_physical", ctypes.c_ulonglong),
                ("available_physical", ctypes.c_ulonglong),
                ("total_page_file", ctypes.c_ulonglong),
                ("available_page_file", ctypes.c_ulonglong),
                ("total_virtual", ctypes.c_ulonglong),
                ("available_virtual", ctypes.c_ulonglong),
                ("available_extended_virtual", ctypes.c_ulonglong),
            ]

        status = MemoryStatus()
        status.length = ctypes.sizeof(MemoryStatus)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
            return int(status.total_physical), int(status.available_physical)
    if sys.platform == "darwin":
        try:
            import ctypes

            libc = ctypes.CDLL("libc.dylib", use_errno=True)
            value = ctypes.c_uint64()
            size = ctypes.c_size_t(ctypes.sizeof(value))
            result = libc.sysctlbyname(
                b"hw.memsize",
                ctypes.byref(value),
                ctypes.byref(size),
                None,
                0,
            )
            if result == 0 and value.value > 0:
                return int(value.value), 0
        except (AttributeError, OSError, ValueError):
            pass
    try:
        values: dict[str, int] = {}
        for line in Path("/proc/meminfo").read_text(encoding="utf-8").splitlines():
            key, raw = line.split(":", 1)
            values[key] = int(raw.strip().split()[0]) * 1024
        return values.get("MemTotal", 0), values.get("MemAvailable", 0)
    except (OSError, ValueError, IndexError):
        return 0, 0


def _uptime_seconds() -> float:
    try:
        import psutil

        return max(0.0, time.time() - psutil.boot_time())
    except ImportError:
        pass
    if os.name == "nt":
        import ctypes

        return float(ctypes.windll.kernel32.GetTickCount64()) / 1000.0
    try:
        return float(Path("/proc/uptime").read_text(encoding="ascii").split()[0])
    except (OSError, ValueError, IndexError):
        return 0.0


def _atomic_write_json(path: Path, value: dict[str, Any]) -> None:
    _atomic_write_bytes(
        path,
        (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode(
            "utf-8"
        ),
    )


def _atomic_write_bytes(path: Path, value: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_bytes(value)
    temporary.replace(path)


__all__ = ["NodeRuntimeConfig", "NodeRuntimeService"]
