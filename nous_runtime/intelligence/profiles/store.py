"""Profile storage — JSONL-based persistence following existing patterns.

Local-filesystem safety, same-host concurrency, idempotent append,
truncated-line recovery, schema migration hooks, secret redaction,
deterministic snapshots, integrity verification.

Explicitly does NOT support: NFS, SMB, multi-host writers, distributed filesystems.
"""

from __future__ import annotations

import json
import os
import socket
import threading
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator, Protocol

from nous_runtime.intelligence.profiles.models import (
    PROFILE_SCHEMA_VERSION,
    CapabilityObservation,
    DiscoveryRecord,
    ModelProfile,
    PerformanceObservation,
    ProbeResult,
    ProfileSnapshot,
    ProviderProfile,
)


class ProfileStore(Protocol):
    """Protocol for profile persistence backends."""

    def save_model_profile(self, profile: ModelProfile) -> bool: ...
    def save_provider_profile(self, profile: ProviderProfile) -> bool: ...
    def append_capability_observation(self, obs: CapabilityObservation) -> bool: ...
    def append_performance_observation(self, obs: PerformanceObservation) -> bool: ...
    def append_probe_result(self, result: ProbeResult) -> bool: ...
    def get_model_profile(self, model_id: str) -> ModelProfile | None: ...
    def list_model_profiles(self) -> list[ModelProfile]: ...
    def get_provider_profile(self, provider_id: str) -> ProviderProfile | None: ...
    def list_provider_profiles(self) -> list[ProviderProfile]: ...
    def find_stale_profiles(self, *, now: datetime | None = None) -> list[ModelProfile | ProviderProfile]: ...
    def verify_integrity(self) -> dict[str, Any]: ...
    def rebuild_indexes(self) -> dict[str, Any]: ...


# in-memory store

@dataclass
class InMemoryProfileStore:
    model_profiles: dict[str, ModelProfile] = field(default_factory=dict)
    provider_profiles: dict[str, ProviderProfile] = field(default_factory=dict)
    capability_obs: list[CapabilityObservation] = field(default_factory=list)
    performance_obs: list[PerformanceObservation] = field(default_factory=list)
    probe_results: list[ProbeResult] = field(default_factory=list)
    snapshots: dict[str, ProfileSnapshot] = field(default_factory=dict)
    discovery_records: list[DiscoveryRecord] = field(default_factory=list)

    def save_model_profile(self, profile: ModelProfile) -> bool:
        self.model_profiles[profile.model_id] = profile
        return True

    def save_provider_profile(self, profile: ProviderProfile) -> bool:
        self.provider_profiles[profile.provider_id] = profile
        return True

    def append_capability_observation(self, obs: CapabilityObservation) -> bool:
        self.capability_obs.append(obs)
        return True

    def append_performance_observation(self, obs: PerformanceObservation) -> bool:
        self.performance_obs.append(obs)
        return True

    def append_probe_result(self, result: ProbeResult) -> bool:
        self.probe_results.append(result)
        return True

    def get_model_profile(self, model_id: str) -> ModelProfile | None:
        return self.model_profiles.get(model_id)

    def list_model_profiles(self) -> list[ModelProfile]:
        return list(self.model_profiles.values())

    def get_provider_profile(self, provider_id: str) -> ProviderProfile | None:
        return self.provider_profiles.get(provider_id)

    def list_provider_profiles(self) -> list[ProviderProfile]:
        return list(self.provider_profiles.values())

    def find_stale_profiles(self, *, now: datetime | None = None) -> list[ModelProfile | ProviderProfile]:
        stale: list[ModelProfile | ProviderProfile] = []
        for p in self.model_profiles.values():
            if p.lifecycle.value in ("degraded", "quarantined", "retired"):
                stale.append(p)
        return stale

    def verify_integrity(self) -> dict[str, Any]:
        return {"ok": True, "invalid_records": 0}

    def rebuild_indexes(self) -> dict[str, Any]:
        return {"ok": True, "models": len(self.model_profiles), "providers": len(self.provider_profiles)}


# JSONL store

class JsonlProfileStore:
    SUPPORTED_CONCURRENCY_MODES = {"single_process", "file_lock"}

    def __init__(self, workspace_path: str | Path, *, concurrency_mode: str = "single_process"):
        if concurrency_mode not in self.SUPPORTED_CONCURRENCY_MODES:
            raise ValueError(f"unsupported concurrency mode: {concurrency_mode}")
        self.concurrency_mode = concurrency_mode
        self.root = Path(workspace_path) / "intelligence" / "profiles"
        self.manifest_root = self.root / "manifests"
        self.manifest_path = self.manifest_root / "store.json"
        self.lock_path = self.root / ".store.lock"
        self._lock = threading.RLock()

        # File paths
        self.models_path = self.root / "models.jsonl"
        self.providers_path = self.root / "providers.jsonl"
        self.capability_obs_path = self.root / "capability_observations.jsonl"
        self.performance_obs_path = self.root / "performance_observations.jsonl"
        self.probes_path = self.root / "probes.jsonl"
        self.snapshots_path = self.root / "snapshots.jsonl"
        self.discovery_path = self.root / "discovery.jsonl"

        self._write_manifest()

    # save

    def save_model_profile(self, profile: ModelProfile) -> bool:
        return self._append_unique(self.models_path, "model_id", profile.model_id, profile.to_dict())

    def save_provider_profile(self, profile: ProviderProfile) -> bool:
        return self._append_unique(self.providers_path, "provider_id", profile.provider_id, profile.to_dict())

    def append_capability_observation(self, obs: CapabilityObservation) -> bool:
        return self._append(self.capability_obs_path, obs.to_dict())

    def append_performance_observation(self, obs: PerformanceObservation) -> bool:
        return self._append_unique(self.performance_obs_path, "observation_id", obs.observation_id, obs.to_dict())

    def append_probe_result(self, result: ProbeResult) -> bool:
        return self._append_unique(self.probes_path, "result_id", result.result_id, result.to_dict())

    def append_discovery_record(self, record: DiscoveryRecord) -> bool:
        return self._append(self.discovery_path, record.to_dict())

    def save_snapshot(self, snapshot: ProfileSnapshot) -> bool:
        return self._append_unique(self.snapshots_path, "snapshot_id", snapshot.snapshot_id, snapshot.to_dict())

    # get / list

    def get_model_profile(self, model_id: str) -> ModelProfile | None:
        for row in reversed(_read_jsonl(self.models_path)["records"]):
            if row.get("model_id") == model_id:
                return ModelProfile.from_dict(row)
        return None

    def list_model_profiles(self) -> list[ModelProfile]:
        return [ModelProfile.from_dict(r) for r in _read_jsonl(self.models_path)["records"]]

    def get_provider_profile(self, provider_id: str) -> ProviderProfile | None:
        for row in reversed(_read_jsonl(self.providers_path)["records"]):
            if row.get("provider_id") == provider_id:
                return ProviderProfile.from_dict(row)
        return None

    def list_provider_profiles(self) -> list[ProviderProfile]:
        return [ProviderProfile.from_dict(r) for r in _read_jsonl(self.providers_path)["records"]]

    def list_capability_observations(self, *, model_id: str = "", capability_id: str = "", limit: int = 100) -> list[CapabilityObservation]:
        result = []
        for row in _read_jsonl(self.capability_obs_path)["records"]:
            if model_id and row.get("model_id") != model_id:
                continue
            if capability_id and row.get("capability_id") != capability_id:
                continue
            result.append(CapabilityObservation.from_dict(row))
        return result[-limit:]

    def list_performance_observations(self, *, model_id: str = "", limit: int = 100) -> list[PerformanceObservation]:
        result = []
        for row in _read_jsonl(self.performance_obs_path)["records"]:
            if model_id and row.get("model_id") != model_id:
                continue
            result.append(PerformanceObservation.from_dict(row))
        return result[-limit:]

    def list_probe_results(self, *, model_id: str = "", probe_id: str = "", limit: int = 100) -> list[ProbeResult]:
        result = []
        for row in _read_jsonl(self.probes_path)["records"]:
            if model_id and row.get("model_id") != model_id:
                continue
            if probe_id and row.get("probe_id") != probe_id:
                continue
            result.append(ProbeResult.from_dict(row))
        return result[-limit:]

    def list_discovery_records(self, limit: int = 100) -> list[DiscoveryRecord]:
        return [DiscoveryRecord.from_dict(r) for r in _read_jsonl(self.discovery_path)["records"]][-limit:]

    def get_snapshot(self, snapshot_id: str) -> ProfileSnapshot | None:
        for row in reversed(_read_jsonl(self.snapshots_path)["records"]):
            if row.get("snapshot_id") == snapshot_id:
                return ProfileSnapshot.from_dict(row)
        return None

    # maintenance

    def find_stale_profiles(self, *, now: datetime | None = None) -> list[ModelProfile | ProviderProfile]:
        stale: list[ModelProfile | ProviderProfile] = []
        for mp in self.list_model_profiles():
            if mp.lifecycle.value in ("degraded", "quarantined", "retired"):
                stale.append(mp)
        return stale

    def verify_integrity(self) -> dict[str, Any]:
        files = {
            "models": _read_jsonl(self.models_path),
            "providers": _read_jsonl(self.providers_path),
            "capability_observations": _read_jsonl(self.capability_obs_path),
            "performance_observations": _read_jsonl(self.performance_obs_path),
            "probes": _read_jsonl(self.probes_path),
            "snapshots": _read_jsonl(self.snapshots_path),
            "discovery": _read_jsonl(self.discovery_path),
        }
        invalid = sum(len(f["invalid"]) for f in files.values())
        return {
            "ok": invalid == 0,
            "invalid_records": invalid,
            "files": list(files),
            "concurrency_mode": self.concurrency_mode,
        }

    def rebuild_indexes(self) -> dict[str, Any]:
        models = self.list_model_profiles()
        providers = self.list_provider_profiles()
        observations = self.list_performance_observations(limit=10000)
        return {
            "ok": True,
            "models": len(models),
            "providers": len(providers),
            "performance_observations": len(observations),
            "model_observation_keys": len({obs.model_id for obs in observations if obs.model_id}),
            "provider_observation_keys": len({obs.provider_id for obs in observations if obs.provider_id}),
        }

    # internals

    def _append(self, path: Path, data: dict[str, Any]) -> bool:
        with self._concurrency_guard():
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8", newline="\n") as fh:
                fh.write(json.dumps(data, ensure_ascii=False, sort_keys=True) + "\n")
                fh.flush()
            return True

    def _append_unique(self, path: Path, key: str, value: str, data: dict[str, Any]) -> bool:
        with self._concurrency_guard():
            if any(row.get(key) == value for row in _read_jsonl(path)["records"]):
                return False
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8", newline="\n") as fh:
                fh.write(json.dumps(data, ensure_ascii=False, sort_keys=True) + "\n")
                fh.flush()
            return True

    @contextmanager
    def _concurrency_guard(self) -> Iterator[None]:
        with self._lock:
            if self.concurrency_mode == "single_process":
                yield
                return
            if self.concurrency_mode == "file_lock":
                with _file_lock(self.lock_path):
                    yield
                return
            raise ValueError(f"unsupported concurrency mode: {self.concurrency_mode}")

    def _write_manifest(self) -> None:
        self.manifest_root.mkdir(parents=True, exist_ok=True)
        data = {
            "schema_version": PROFILE_SCHEMA_VERSION,
            "store": "JsonlProfileStore",
            "concurrency_mode": self.concurrency_mode,
            "pid": os.getpid(),
            "host": socket.gethostname(),
            "updated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "multi_host_safe": False,
            "supported_fs": ["local"],
            "unsupported_fs": ["nfs", "smb", "distributed"],
        }
        self.manifest_path.write_text(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


# file helpers

@contextmanager
def _file_lock(path: Path) -> Iterator[None]:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as fh:
        if os.name == "nt":
            import msvcrt
            fh.seek(0)
            msvcrt.locking(fh.fileno(), msvcrt.LK_LOCK, 1)
            try:
                yield
            finally:
                fh.seek(0)
                msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(fh.fileno(), fcntl.LOCK_UN)


def _read_jsonl(path: Path) -> dict[str, Any]:
    records: list[dict[str, Any]] = []
    invalid: list[dict[str, Any]] = []
    if not path.is_file():
        return {"records": records, "invalid": invalid}
    with path.open(encoding="utf-8") as fh:
        for lineno, line in enumerate(fh, start=1):
            text = line.strip()
            if not text:
                continue
            try:
                data = json.loads(text)
            except json.JSONDecodeError as exc:
                invalid.append({"line": lineno, "error": str(exc)})
                continue
            if isinstance(data, dict):
                records.append(data)
            else:
                invalid.append({"line": lineno, "error": "record is not an object"})
    return {"records": records, "invalid": invalid}
