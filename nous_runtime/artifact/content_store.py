"""R3 content-addressed artifact storage with integrity and graph metadata."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from nous_runtime.artifact.models import ArtifactType
from nous_runtime.core.errors import ArtifactError
from nous_runtime.locking import file_lock

_DIGEST = re.compile(r"^sha256:([0-9a-f]{64})$")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace(
        "+00:00", "Z"
    )


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


@dataclass(frozen=True)
class ContentArtifact:
    digest: str
    artifact_type: str
    name: str
    size_bytes: int
    created_at: str
    media_type: str = "application/octet-stream"
    produced_by: str = ""
    depends_on: tuple[str, ...] = field(default_factory=tuple)
    deployed_to: tuple[str, ...] = field(default_factory=tuple)
    derived_from: tuple[str, ...] = field(default_factory=tuple)
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _digest_hex(self.digest)
        if self.artifact_type not in {item.value for item in ArtifactType}:
            raise ArtifactError(f"unsupported artifact type: {self.artifact_type}")
        if not self.name.strip():
            raise ArtifactError("artifact name is required")
        if isinstance(self.size_bytes, bool) or self.size_bytes < 0:
            raise ArtifactError("artifact size must be a non-negative integer")
        for linked in (*self.depends_on, *self.derived_from):
            _digest_hex(linked)

    @property
    def artifact_id(self) -> str:
        return self.digest

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": "nous.content-artifact/v1",
            "artifact_id": self.artifact_id,
            "digest": self.digest,
            "artifact_type": self.artifact_type,
            "name": self.name,
            "size_bytes": self.size_bytes,
            "created_at": self.created_at,
            "media_type": self.media_type,
            "produced_by": self.produced_by,
            "depends_on": list(self.depends_on),
            "deployed_to": list(self.deployed_to),
            "derived_from": list(self.derived_from),
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> ContentArtifact:
        return cls(
            digest=str(value["digest"]),
            artifact_type=str(value["artifact_type"]),
            name=str(value["name"]),
            size_bytes=int(value["size_bytes"]),
            created_at=str(value["created_at"]),
            media_type=str(value.get("media_type") or "application/octet-stream"),
            produced_by=str(value.get("produced_by") or ""),
            depends_on=tuple(value.get("depends_on") or ()),
            deployed_to=tuple(value.get("deployed_to") or ()),
            derived_from=tuple(value.get("derived_from") or ()),
            metadata=dict(value.get("metadata") or {}),
        )


class ContentAddressedArtifactStore:
    """Durable SHA-256 store; the index never substitutes for content verification."""

    def __init__(self, root: str | Path):
        self.root = Path(root).expanduser().resolve()
        self.objects = self.root / "objects" / "sha256"
        self.index_path = self.root / "index.json"
        self.pins_path = self.root / "pins.json"
        self.receipts_path = self.root / "receipts.jsonl"
        self._lock = threading.RLock()
        self.objects.mkdir(parents=True, exist_ok=True)
        self._index = self._load_index()
        self._pins = self._load_pins()

    def store_bytes(
        self,
        content: bytes,
        *,
        artifact_type: str | ArtifactType,
        name: str,
        media_type: str = "application/octet-stream",
        produced_by: str = "",
        depends_on: Iterable[str] = (),
        deployed_to: Iterable[str] = (),
        derived_from: Iterable[str] = (),
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if not isinstance(content, bytes):
            raise ArtifactError("artifact content must be bytes")
        digest = "sha256:" + hashlib.sha256(content).hexdigest()
        return self._commit(
            digest,
            len(content),
            lambda target: _atomic_write_bytes(target, content),
            artifact_type=artifact_type,
            name=name,
            media_type=media_type,
            produced_by=produced_by,
            depends_on=depends_on,
            deployed_to=deployed_to,
            derived_from=derived_from,
            metadata=metadata,
        )

    def store_file(
        self,
        source: str | Path,
        *,
        expected_digest: str = "",
        **metadata: Any,
    ) -> dict[str, Any]:
        source_path = Path(source).expanduser().resolve(strict=True)
        if not source_path.is_file():
            raise ArtifactError("artifact source must be a regular file")
        hasher = hashlib.sha256()
        size = 0
        with source_path.open("rb") as handle:
            while chunk := handle.read(1024 * 1024):
                hasher.update(chunk)
                size += len(chunk)
        digest = "sha256:" + hasher.hexdigest()
        if expected_digest and digest != expected_digest:
            raise ArtifactError(
                f"artifact digest mismatch: expected {expected_digest}, got {digest}"
            )
        return self._commit(
            digest,
            size,
            lambda target: _atomic_copy(source_path, target),
            **metadata,
        )

    def fetch_from_store(
        self, source: ContentAddressedArtifactStore, digest: str
    ) -> dict[str, Any]:
        """Fetch and cache a verified object from another local artifact store."""
        record = source.get(digest)
        if record is None:
            raise ArtifactError(f"source artifact not found: {digest}")
        source_path = source.resolve(digest, verify=True)
        for linked in (*record.depends_on, *record.derived_from):
            if self.get(linked) is None:
                self.fetch_from_store(source, linked)
        return self.store_file(
            source_path,
            expected_digest=digest,
            artifact_type=record.artifact_type,
            name=record.name,
            media_type=record.media_type,
            produced_by=f"artifact.fetch:{source.root}",
            depends_on=record.depends_on,
            deployed_to=record.deployed_to,
            derived_from=record.derived_from,
            metadata=record.metadata,
        )

    def get(self, digest: str) -> ContentArtifact | None:
        _digest_hex(digest)
        value = self._index.get(digest)
        return ContentArtifact.from_dict(value) if value else None

    def list(self, artifact_type: str | ArtifactType | None = None) -> list[ContentArtifact]:
        normalized = artifact_type.value if isinstance(artifact_type, ArtifactType) else str(artifact_type or "")
        values = [ContentArtifact.from_dict(value) for value in self._index.values()]
        if normalized:
            values = [value for value in values if value.artifact_type == normalized]
        return sorted(values, key=lambda value: (value.created_at, value.digest))

    def resolve(self, digest: str, *, verify: bool = True) -> Path:
        path = self._object_path(digest)
        if digest not in self._index or not path.is_file():
            raise ArtifactError(f"artifact not found: {digest}")
        if verify and not self.verify(digest):
            raise ArtifactError(f"artifact integrity verification failed: {digest}")
        return path

    def verify(self, digest: str) -> bool:
        record = self.get(digest)
        if record is None:
            return False
        path = self._object_path(digest)
        if not path.is_file() or path.stat().st_size != record.size_bytes:
            return False
        hasher = hashlib.sha256()
        with path.open("rb") as handle:
            while chunk := handle.read(1024 * 1024):
                hasher.update(chunk)
        return "sha256:" + hasher.hexdigest() == digest

    def pin(self, digest: str, reason: str = "user") -> dict[str, Any]:
        self.resolve(digest)
        with self._lock, file_lock(str(self.index_path) + ".lock"):
            self._pins[digest] = {"reason": reason, "pinned_at": _utc_now()}
            _atomic_write_json(self.pins_path, self._pins)
            return self._receipt("artifact.pin", digest, "COMPLETED")

    def unpin(self, digest: str) -> dict[str, Any]:
        _digest_hex(digest)
        with self._lock, file_lock(str(self.index_path) + ".lock"):
            existed = self._pins.pop(digest, None) is not None
            _atomic_write_json(self.pins_path, self._pins)
            return self._receipt(
                "artifact.unpin", digest, "COMPLETED" if existed else "UNCHANGED"
            )

    def garbage_collect(self, *, dry_run: bool = True) -> dict[str, Any]:
        with self._lock, file_lock(str(self.index_path) + ".lock"):
            protected = self._transitive_pin_closure()
            candidates = sorted(set(self._index) - protected)
            if dry_run:
                return {"dry_run": True, "removed": [], "candidates": candidates, "protected": sorted(protected), "receipt": None}
            next_index = {
                digest: record
                for digest, record in self._index.items()
                if digest not in candidates
            }
            _atomic_write_json(self.index_path, next_index)
            self._index = next_index
            removed = []
            for digest in candidates:
                path = self._object_path(digest)
                if path.is_file():
                    path.unlink()
                removed.append(digest)
            receipt = self._receipt(
                "artifact.gc",
                "artifact-store",
                "COMPLETED",
                effect={"removed": removed, "protected": sorted(protected)},
            )
            return {"dry_run": False, "removed": removed, "candidates": candidates, "protected": sorted(protected), "receipt": receipt}

    def _commit(
        self,
        digest: str,
        size: int,
        writer: Any,
        *,
        artifact_type: str | ArtifactType,
        name: str,
        media_type: str = "application/octet-stream",
        produced_by: str = "",
        depends_on: Iterable[str] = (),
        deployed_to: Iterable[str] = (),
        derived_from: Iterable[str] = (),
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        normalized_type = artifact_type.value if isinstance(artifact_type, ArtifactType) else str(artifact_type)
        if normalized_type not in {item.value for item in ArtifactType}:
            raise ArtifactError(f"unsupported artifact type: {normalized_type}")
        if not name.strip():
            raise ArtifactError("artifact name is required")
        dependencies = tuple(sorted(set(depends_on)))
        origins = tuple(sorted(set(derived_from)))
        for linked in (*dependencies, *origins):
            if linked not in self._index:
                raise ArtifactError(f"artifact graph reference not found: {linked}")
        record = ContentArtifact(
            digest=digest,
            artifact_type=normalized_type,
            name=name.strip(),
            size_bytes=size,
            created_at=_utc_now(),
            media_type=media_type,
            produced_by=produced_by,
            depends_on=dependencies,
            deployed_to=tuple(sorted(set(deployed_to))),
            derived_from=origins,
            metadata=dict(metadata or {}),
        )
        with self._lock, file_lock(str(self.index_path) + ".lock"):
            existing = self._index.get(digest)
            if existing:
                if not self.verify(digest):
                    raise ArtifactError(f"existing artifact is corrupt: {digest}")
                receipt = self._receipt("artifact.store", digest, "UNCHANGED")
                return {"artifact": existing, "receipt": receipt}
            target = self._object_path(digest)
            target.parent.mkdir(parents=True, exist_ok=True)
            writer(target)
            if not self._verify_path(target, digest, size):
                target.unlink(missing_ok=True)
                raise ArtifactError("artifact failed post-write verification")
            self._index[digest] = record.to_dict()
            _atomic_write_json(self.index_path, self._index)
            receipt = self._receipt("artifact.store", digest, "COMPLETED")
            return {"artifact": record.to_dict(), "receipt": receipt}

    def _object_path(self, digest: str) -> Path:
        value = _digest_hex(digest)
        return self.objects / value[:2] / value

    def _verify_path(self, path: Path, digest: str, size: int) -> bool:
        return path.stat().st_size == size and "sha256:" + _sha256_file(path) == digest

    def _load_index(self) -> dict[str, dict[str, Any]]:
        value = _read_json(self.index_path)
        for digest, record in value.items():
            _digest_hex(digest)
            if not isinstance(record, dict) or record.get("digest") != digest:
                raise ArtifactError("artifact index is invalid")
            ContentArtifact.from_dict(record)
        return value

    def _load_pins(self) -> dict[str, dict[str, Any]]:
        value = _read_json(self.pins_path)
        for digest in value:
            _digest_hex(digest)
        return value

    def _transitive_pin_closure(self) -> set[str]:
        protected = set(self._pins)
        pending = list(protected)
        while pending:
            record = self._index.get(pending.pop(), {})
            for linked in (*record.get("depends_on", []), *record.get("derived_from", [])):
                if linked not in protected:
                    protected.add(linked)
                    pending.append(linked)
        return protected

    def _receipt(
        self,
        operation: str,
        target: str,
        result: str,
        *,
        effect: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        now = _utc_now()
        receipt = {
            "schema": "nous.operation-receipt/v1",
            "operation_id": f"op_{uuid.uuid4().hex}",
            "actor": "nous-runtime",
            "source": "artifact-runtime",
            "target": target,
            "requested_capabilities": [operation],
            "granted_capabilities": [operation],
            "input_digest": hashlib.sha256(target.encode("utf-8")).hexdigest(),
            "result": result,
            "timestamps": {"started_at": now, "finished_at": now},
            "policy_version": "artifact-local-v1",
            "executor": "content-addressed-store",
            "effect_digest": hashlib.sha256(_canonical(effect or {"target": target})).hexdigest(),
        }
        with self.receipts_path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(receipt, ensure_ascii=False, sort_keys=True) + "\n")
        return receipt


def _digest_hex(digest: str) -> str:
    match = _DIGEST.fullmatch(digest)
    if not match:
        raise ArtifactError("artifact digest must be sha256:<64 lowercase hex>")
    return match.group(1)


def _read_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ArtifactError(f"artifact state could not be loaded: {exc}") from exc
    if not isinstance(value, dict):
        raise ArtifactError("artifact state must be a JSON object")
    return value


def _atomic_write_json(path: Path, value: Any) -> None:
    _atomic_write_bytes(path, json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2).encode("utf-8") + b"\n")


def _atomic_write_bytes(path: Path, content: bytes) -> None:
    temporary = path.with_suffix(path.suffix + f".{os.getpid()}.tmp")
    with temporary.open("xb") as handle:
        handle.write(content)
        handle.flush()
        os.fsync(handle.fileno())
    temporary.replace(path)


def _atomic_copy(source: Path, target: Path) -> None:
    temporary = target.with_suffix(target.suffix + f".{os.getpid()}.tmp")
    with source.open("rb") as reader, temporary.open("xb") as writer:
        shutil.copyfileobj(reader, writer, length=1024 * 1024)
        writer.flush()
        os.fsync(writer.fileno())
    temporary.replace(target)


def _sha256_file(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            hasher.update(chunk)
    return hasher.hexdigest()
