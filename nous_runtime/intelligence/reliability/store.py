"""Reliability storage — JSONL-based persistence. Same filesystem/locking boundary as existing stores."""

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

from nous_runtime.intelligence.reliability.models import (
    RELIABILITY_SCHEMA_VERSION,
    CircuitStateRecord,
    FailureSignal,
    FallbackExecution,
    ProviderHealthSnapshot,
    RetryAttempt,
)


class ReliabilityStore(Protocol):
    def append_signal(self, signal: FailureSignal) -> bool: ...
    def save_health_snapshot(self, snapshot: ProviderHealthSnapshot) -> bool: ...
    def append_circuit_event(self, record: CircuitStateRecord) -> bool: ...
    def append_retry_attempt(self, attempt: RetryAttempt) -> bool: ...
    def append_fallback(self, fallback: FallbackExecution) -> bool: ...
    def get_current_health(self, provider_id: str, model_id: str) -> ProviderHealthSnapshot | None: ...
    def get_circuit_state(self, breaker_key: str) -> CircuitStateRecord | None: ...
    def verify_integrity(self) -> dict[str, Any]: ...


@dataclass
class InMemoryReliabilityStore:
    signals: list[FailureSignal] = field(default_factory=list)
    health_snapshots: dict[str, ProviderHealthSnapshot] = field(default_factory=dict)
    circuit_events: list[CircuitStateRecord] = field(default_factory=list)
    retry_attempts: list[RetryAttempt] = field(default_factory=list)
    fallback_events: list[FallbackExecution] = field(default_factory=list)

    def append_signal(self, signal: FailureSignal) -> bool:
        self.signals.append(signal)
        return True

    def save_health_snapshot(self, snapshot: ProviderHealthSnapshot) -> bool:
        key = f"{snapshot.provider_id}:{snapshot.model_id}"
        self.health_snapshots[key] = snapshot
        return True

    def append_circuit_event(self, record: CircuitStateRecord) -> bool:
        self.circuit_events.append(record)
        return True

    def append_retry_attempt(self, attempt: RetryAttempt) -> bool:
        self.retry_attempts.append(attempt)
        return True

    def append_fallback(self, fallback: FallbackExecution) -> bool:
        self.fallback_events.append(fallback)
        return True

    def get_current_health(self, provider_id: str, model_id: str = "") -> ProviderHealthSnapshot | None:
        key = f"{provider_id}:{model_id}"
        return self.health_snapshots.get(key)

    def get_circuit_state(self, breaker_key: str) -> CircuitStateRecord | None:
        for r in reversed(self.circuit_events):
            if r.breaker_key == breaker_key:
                return r
        return None

    def verify_integrity(self) -> dict[str, Any]:
        return {"ok": True, "invalid_records": 0}


class JsonlReliabilityStore:
    SUPPORTED_CONCURRENCY_MODES = {"single_process", "file_lock"}

    def __init__(self, workspace_path: str | Path, *, concurrency_mode: str = "single_process"):
        if concurrency_mode not in self.SUPPORTED_CONCURRENCY_MODES:
            raise ValueError(f"unsupported concurrency mode: {concurrency_mode}")
        self.concurrency_mode = concurrency_mode
        self.root = Path(workspace_path) / "intelligence" / "reliability"
        self.manifest_root = self.root / "manifests"
        self.manifest_path = self.manifest_root / "store.json"
        self.lock_path = self.root / ".store.lock"
        self._lock = threading.RLock()

        self.signals_path = self.root / "signals.jsonl"
        self.health_snapshots_path = self.root / "health_snapshots.jsonl"
        self.circuit_events_path = self.root / "circuit_events.jsonl"
        self.retry_attempts_path = self.root / "retry_attempts.jsonl"
        self.fallback_events_path = self.root / "fallback_events.jsonl"

        self._write_manifest()

    def append_signal(self, signal: FailureSignal) -> bool:
        return self._append_unique(self.signals_path, "signal_id", signal.signal_id, signal.to_dict())

    def save_health_snapshot(self, snapshot: ProviderHealthSnapshot) -> bool:
        return self._append(self.health_snapshots_path, snapshot.to_dict())

    def append_circuit_event(self, record: CircuitStateRecord) -> bool:
        return self._append_unique(self.circuit_events_path, "record_id", record.record_id, record.to_dict())

    def append_retry_attempt(self, attempt: RetryAttempt) -> bool:
        return self._append_unique(self.retry_attempts_path, "attempt_id", attempt.attempt_id, attempt.to_dict())

    def append_fallback(self, fallback: FallbackExecution) -> bool:
        return self._append_unique(self.fallback_events_path, "fallback_id", fallback.fallback_id, fallback.to_dict())

    def get_current_health(self, provider_id: str, model_id: str = "") -> ProviderHealthSnapshot | None:
        for row in reversed(_read_jsonl(self.health_snapshots_path)["records"]):
            if row.get("provider_id") == provider_id and row.get("model_id") == model_id:
                return ProviderHealthSnapshot.from_dict(row)
        return None

    def get_circuit_state(self, breaker_key: str) -> CircuitStateRecord | None:
        for row in reversed(_read_jsonl(self.circuit_events_path)["records"]):
            if row.get("breaker_key") == breaker_key:
                return CircuitStateRecord.from_dict(row)
        return None

    def list_signals(self, *, provider_id: str = "", limit: int = 100) -> list[FailureSignal]:
        result = []
        for row in _read_jsonl(self.signals_path)["records"]:
            if provider_id and row.get("provider_id") != provider_id:
                continue
            result.append(FailureSignal.from_dict(row))
        return result[-limit:]

    def list_retries(self, *, provider_id: str = "", limit: int = 100) -> list[RetryAttempt]:
        result = []
        for row in _read_jsonl(self.retry_attempts_path)["records"]:
            attempt = RetryAttempt.from_dict(row)
            if provider_id and (attempt.failure is None or attempt.failure.provider_id != provider_id):
                continue
            result.append(attempt)
        return result[-limit:]

    def list_health(self, limit: int = 100) -> list[ProviderHealthSnapshot]:
        return [ProviderHealthSnapshot.from_dict(r) for r in _read_jsonl(self.health_snapshots_path)["records"]][-limit:]

    def list_fallbacks(self, limit: int = 100) -> list[FallbackExecution]:
        return [FallbackExecution.from_dict(r) for r in _read_jsonl(self.fallback_events_path)["records"]][-limit:]

    def verify_integrity(self) -> dict[str, Any]:
        files = {
            "signals": _read_jsonl(self.signals_path),
            "health_snapshots": _read_jsonl(self.health_snapshots_path),
            "circuit_events": _read_jsonl(self.circuit_events_path),
            "retry_attempts": _read_jsonl(self.retry_attempts_path),
            "fallback_events": _read_jsonl(self.fallback_events_path),
        }
        invalid = sum(len(f["invalid"]) for f in files.values())
        return {"ok": invalid == 0, "invalid_records": invalid, "files": list(files), "concurrency_mode": self.concurrency_mode}

    def _append(self, path: Path, data: dict[str, Any]) -> bool:
        with self._concurrency_guard():
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8", newline="\n") as fh:
                fh.write(json.dumps(data, ensure_ascii=False, sort_keys=True) + "\n")
            return True

    def _append_unique(self, path: Path, key: str, value: str, data: dict[str, Any]) -> bool:
        with self._concurrency_guard():
            if any(row.get(key) == value for row in _read_jsonl(path)["records"]):
                return False
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8", newline="\n") as fh:
                fh.write(json.dumps(data, ensure_ascii=False, sort_keys=True) + "\n")
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
            raise ValueError(f"unsupported: {self.concurrency_mode}")

    def _write_manifest(self) -> None:
        self.manifest_root.mkdir(parents=True, exist_ok=True)
        data = {
            "schema_version": RELIABILITY_SCHEMA_VERSION,
            "store": "JsonlReliabilityStore",
            "concurrency_mode": self.concurrency_mode,
            "pid": os.getpid(),
            "host": socket.gethostname(),
            "updated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "multi_host_safe": False,
            "supported_fs": ["local"],
            "unsupported_fs": ["nfs", "smb", "distributed"],
        }
        self.manifest_path.write_text(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


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
