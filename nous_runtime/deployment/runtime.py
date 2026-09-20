"""R4 durable deployment state machine for verified static artifacts."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import uuid
from contextlib import ExitStack
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Callable

from nous_runtime.artifact import ContentAddressedArtifactStore
from nous_runtime.errors import DeploymentError
from nous_runtime.locking import file_lock


class DeploymentState(str, Enum):
    PENDING = "PENDING"
    RESOLVING = "RESOLVING"
    TRANSFERRING = "TRANSFERRING"
    INSTALLING = "INSTALLING"
    STARTING = "STARTING"
    VERIFYING = "VERIFYING"
    ACTIVE = "ACTIVE"
    FAILED = "FAILED"
    ROLLING_BACK = "ROLLING_BACK"
    ROLLED_BACK = "ROLLED_BACK"


_TRANSITIONS = {
    DeploymentState.PENDING: {DeploymentState.RESOLVING, DeploymentState.FAILED},
    DeploymentState.RESOLVING: {DeploymentState.TRANSFERRING, DeploymentState.FAILED},
    DeploymentState.TRANSFERRING: {DeploymentState.INSTALLING, DeploymentState.FAILED},
    DeploymentState.INSTALLING: {DeploymentState.STARTING, DeploymentState.FAILED},
    DeploymentState.STARTING: {DeploymentState.VERIFYING, DeploymentState.FAILED},
    DeploymentState.VERIFYING: {DeploymentState.ACTIVE, DeploymentState.FAILED},
    DeploymentState.FAILED: {DeploymentState.ROLLING_BACK},
    DeploymentState.ROLLING_BACK: {DeploymentState.ROLLED_BACK},
    DeploymentState.ACTIVE: set(),
    DeploymentState.ROLLED_BACK: set(),
}
_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


@dataclass
class DeploymentRecord:
    deployment_id: str
    artifact_digest: str
    target_id: str
    mode: str = "static"
    state: DeploymentState = DeploymentState.PENDING
    created_at: str = field(default_factory=_now)
    updated_at: str = field(default_factory=_now)
    previous_active: str = ""
    release_path: str = ""
    error_code: str = ""
    error_message: str = ""
    events: list[dict[str, Any]] = field(default_factory=list)
    receipt: dict[str, Any] = field(default_factory=dict)

    def transition(self, state: DeploymentState, **details: Any) -> None:
        if state not in _TRANSITIONS[self.state]:
            raise DeploymentError(f"invalid deployment transition: {self.state} -> {state}")
        self.state = state
        self.updated_at = _now()
        self.events.append({"state": state.value, "timestamp": self.updated_at, **details})

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": "nous.deployment/v1",
            "deployment_id": self.deployment_id,
            "artifact_digest": self.artifact_digest,
            "target_id": self.target_id,
            "mode": self.mode,
            "state": self.state.value,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "previous_active": self.previous_active,
            "release_path": self.release_path,
            "error_code": self.error_code,
            "error_message": self.error_message,
            "events": self.events,
            "receipt": self.receipt,
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> DeploymentRecord:
        return cls(
            deployment_id=str(value["deployment_id"]),
            artifact_digest=str(value["artifact_digest"]),
            target_id=str(value["target_id"]),
            mode=str(value.get("mode") or "static"),
            state=DeploymentState(value["state"]),
            created_at=str(value["created_at"]),
            updated_at=str(value["updated_at"]),
            previous_active=str(value.get("previous_active") or ""),
            release_path=str(value.get("release_path") or ""),
            error_code=str(value.get("error_code") or ""),
            error_message=str(value.get("error_message") or ""),
            events=list(value.get("events") or []),
            receipt=dict(value.get("receipt") or {}),
        )


class DeploymentRuntime:
    """Deploy verified static artifacts with atomic activation and rollback."""

    def __init__(
        self,
        state_dir: str | Path,
        source_store: ContentAddressedArtifactStore,
    ):
        self.state_dir = Path(state_dir).expanduser().resolve()
        self.source_store = source_store
        self.records = self.state_dir / "deployments"
        self.targets = self.state_dir / "targets"
        self.desired = self.state_dir / "desired"
        self.records.mkdir(parents=True, exist_ok=True)
        self.targets.mkdir(parents=True, exist_ok=True)
        self.desired.mkdir(parents=True, exist_ok=True)

    def reconcile_static(
        self,
        artifact_digest: str,
        target_id: str,
        *,
        health_check: Callable[[Path], bool] | None = None,
    ) -> dict[str, Any]:
        """Converge one target to a verified desired artifact without false success."""
        _safe_id(target_id, "target_id")
        self.source_store.resolve(artifact_digest, verify=True)
        desired_path = self.desired / f"{target_id}.json"
        _atomic_json(
            desired_path,
            {
                "schema": "nous.deployment-desired/v1",
                "target_id": target_id,
                "artifact_digest": artifact_digest,
                "mode": "static",
                "updated_at": _now(),
            },
        )
        current_path = self.targets / target_id / "current.json"
        current = _read_json(current_path) if current_path.is_file() else {}
        release_path = Path(str(current.get("release_path") or ""))
        payload = release_path / "payload" if release_path else Path()
        observed_digest = str(current.get("artifact_digest") or "")
        healthy = (
            observed_digest == artifact_digest
            and bool(current.get("deployment_id"))
            and payload.is_file()
            and "sha256:" + _sha256(payload) == artifact_digest
            and (health_check is None or health_check(payload))
        )
        if healthy:
            return {
                "schema": "nous.reconciliation/v1",
                "target_id": target_id,
                "desired_digest": artifact_digest,
                "observed_digest": observed_digest,
                "state": "CONVERGED",
                "action": "NONE",
                "deployment_id": current["deployment_id"],
                "verified_at": _now(),
            }
        record = self.deploy_static(
            artifact_digest,
            target_id,
            deployment_id=f"reconcile_{uuid.uuid4().hex}",
            health_check=health_check,
        )
        return {
            "schema": "nous.reconciliation/v1",
            "target_id": target_id,
            "desired_digest": artifact_digest,
            "observed_digest": observed_digest,
            "state": "CONVERGED" if record.state is DeploymentState.ACTIVE else "FAILED",
            "action": "DEPLOY",
            "deployment_id": record.deployment_id,
            "deployment_state": record.state.value,
            "verified_at": _now(),
            "receipt": record.receipt,
        }

    def deploy_static(
        self,
        artifact_digest: str,
        target_id: str,
        *,
        deployment_id: str = "",
        health_check: Callable[[Path], bool] | None = None,
    ) -> DeploymentRecord:
        self.source_store.resolve(artifact_digest, verify=True)
        _safe_id(target_id, "target_id")
        deployment_id = deployment_id or f"deploy_{uuid.uuid4().hex}"
        _safe_id(deployment_id, "deployment_id")
        record_path = self.records / f"{deployment_id}.json"
        target_lock = self.targets / f".{target_id}.deployment.lock"
        with ExitStack() as locks:
            locks.enter_context(file_lock(str(target_lock)))
            locks.enter_context(file_lock(str(record_path) + ".lock"))
            if record_path.is_file():
                existing = DeploymentRecord.from_dict(_read_json(record_path))
                if existing.artifact_digest != artifact_digest or existing.target_id != target_id:
                    raise DeploymentError("deployment idempotency collision")
                if existing.state in {DeploymentState.ACTIVE, DeploymentState.ROLLED_BACK}:
                    return existing
                self._recover_interrupted(existing, record_path)
                return existing

            record = DeploymentRecord(deployment_id, artifact_digest, target_id)
            record.events.append({"state": "PENDING", "timestamp": record.created_at})
            self._persist(record, record_path)
            target_root = self.targets / target_id
            releases = target_root / "releases"
            release = releases / deployment_id
            current_path = target_root / "current.json"
            previous = _read_json(current_path) if current_path.is_file() else {}
            record.previous_active = str(previous.get("deployment_id") or "")
            try:
                self._step(record, record_path, DeploymentState.RESOLVING)
                artifact = self.source_store.get(artifact_digest)
                if artifact is None:
                    raise DeploymentError("artifact metadata disappeared during resolution")
                self._step(record, record_path, DeploymentState.TRANSFERRING)
                cache = ContentAddressedArtifactStore(target_root / "artifact-cache")
                cache.fetch_from_store(self.source_store, artifact_digest)
                self._step(record, record_path, DeploymentState.INSTALLING)
                release.mkdir(parents=True, exist_ok=False)
                payload = release / "payload"
                _atomic_copy(cache.resolve(artifact_digest), payload)
                manifest = {
                    "schema": "nous.deployment-release/v1",
                    "deployment_id": deployment_id,
                    "artifact_digest": artifact_digest,
                    "artifact_type": artifact.artifact_type,
                    "size_bytes": artifact.size_bytes,
                }
                _atomic_json(release / "manifest.json", manifest)
                record.release_path = str(release)
                self._step(record, record_path, DeploymentState.STARTING, activation="static-pointer")
                self._step(record, record_path, DeploymentState.VERIFYING)
                if "sha256:" + _sha256(payload) != artifact_digest:
                    raise DeploymentError("installed artifact digest mismatch")
                if health_check is not None and not health_check(payload):
                    raise DeploymentError("deployment health check failed")
                _atomic_json(
                    current_path,
                    {
                        "schema": "nous.deployment-active/v1",
                        "deployment_id": deployment_id,
                        "artifact_digest": artifact_digest,
                        "release_path": str(release),
                        "activated_at": _now(),
                    },
                )
                record.transition(DeploymentState.ACTIVE)
                record.receipt = self._receipt(record, "COMPLETED")
                self._persist(record, record_path)
                return record
            except Exception as exc:
                self._rollback(record, record_path, release, current_path, previous, exc)
                return record

    def get(self, deployment_id: str) -> DeploymentRecord | None:
        _safe_id(deployment_id, "deployment_id")
        path = self.records / f"{deployment_id}.json"
        return DeploymentRecord.from_dict(_read_json(path)) if path.is_file() else None

    def list(self) -> list[DeploymentRecord]:
        return [DeploymentRecord.from_dict(_read_json(path)) for path in sorted(self.records.glob("*.json"))]

    def _step(self, record: DeploymentRecord, path: Path, state: DeploymentState, **details: Any) -> None:
        record.transition(state, **details)
        self._persist(record, path)

    def _rollback(
        self,
        record: DeploymentRecord,
        path: Path,
        release: Path,
        current_path: Path,
        previous: dict[str, Any],
        error: Exception,
    ) -> None:
        record.error_code = "NOUS_DEPLOYMENT_FAILED"
        record.error_message = f"{type(error).__name__}: {error}"
        if record.state not in {DeploymentState.FAILED, DeploymentState.ROLLING_BACK}:
            record.transition(DeploymentState.FAILED)
        self._persist(record, path)
        record.transition(DeploymentState.ROLLING_BACK)
        if previous:
            _atomic_json(current_path, previous)
        elif current_path.is_file():
            current_path.unlink()
        if release.is_dir():
            shutil.rmtree(release)
        record.transition(DeploymentState.ROLLED_BACK)
        record.receipt = self._receipt(record, "ROLLED_BACK")
        self._persist(record, path)

    def _recover_interrupted(self, record: DeploymentRecord, path: Path) -> None:
        error = DeploymentError("deployment was interrupted before reaching a terminal state")
        target_root = self.targets / record.target_id
        release = target_root / "releases" / record.deployment_id
        current_path = target_root / "current.json"
        previous = {}
        if current_path.is_file():
            active = _read_json(current_path)
            if active.get("deployment_id") != record.deployment_id:
                previous = active
        self._rollback(record, path, release, current_path, previous, error)

    def _persist(self, record: DeploymentRecord, path: Path) -> None:
        _atomic_json(path, record.to_dict())

    def _receipt(self, record: DeploymentRecord, result: str) -> dict[str, Any]:
        return {
            "schema": "nous.operation-receipt/v1",
            "operation_id": record.deployment_id,
            "actor": "nous-runtime",
            "source": "deployment-runtime",
            "target": record.target_id,
            "requested_capabilities": ["artifact.deploy"],
            "granted_capabilities": ["artifact.deploy"],
            "input_digest": record.artifact_digest.removeprefix("sha256:"),
            "result": result,
            "timestamps": {"started_at": record.created_at, "finished_at": record.updated_at},
            "policy_version": "deployment-static-v1",
            "executor": "static-artifact-activator",
            "effect_digest": hashlib.sha256(json.dumps(record.events, sort_keys=True).encode()).hexdigest(),
        }


def _safe_id(value: str, field: str) -> None:
    if not _SAFE_ID.fullmatch(value):
        raise DeploymentError(f"invalid {field}")


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise DeploymentError(f"deployment state is invalid: {path}") from exc
    if not isinstance(value, dict):
        raise DeploymentError("deployment state must be an object")
    return value


def _atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + f".{os.getpid()}.tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def _atomic_copy(source: Path, target: Path) -> None:
    temporary = target.with_suffix(".tmp")
    with source.open("rb") as reader, temporary.open("xb") as writer:
        shutil.copyfileobj(reader, writer, length=1024 * 1024)
        writer.flush()
        os.fsync(writer.fileno())
    temporary.replace(target)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()
