# -*- coding: utf-8 -*-
"""Persistent, hash-verified snapshots of external content."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import threading
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from nous_runtime.locking import file_lock


@dataclass
class ContentSnapshot:
    snapshot_id: str = ""
    source_id: str = ""
    artifact_id: str = ""
    raw_content_hash: str = ""
    cleaned_content_hash: str = ""
    content_type: str = "application/octet-stream"
    retrieval_headers: dict[str, str] = field(default_factory=dict)
    retrieval_timestamp: str = ""
    parser_version: str = "1.0"
    storage_path: str = ""
    size_bytes: int = 0
    limitations: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, values: dict[str, Any]) -> "ContentSnapshot":
        allowed = cls.__dataclass_fields__
        return cls(**{key: value for key, value in values.items() if key in allowed})


class SnapshotStore:
    """Stores immutable response bodies and an atomic metadata index."""

    def __init__(self, storage_dir: str | Path = "") -> None:
        self._dir = Path(storage_dir or Path.home() / ".nous" / "snapshots").expanduser().resolve()
        self._dir.mkdir(parents=True, exist_ok=True)
        self._index = self._dir / "index.json"
        self._snapshots: dict[str, ContentSnapshot] = {}
        self._lock = threading.RLock()
        self._load()

    def store(
        self,
        source_id: str,
        raw_content: str | bytes,
        cleaned_content: str | None = None,
        content_type: str = "application/octet-stream",
        *,
        retrieval_headers: dict[str, str] | None = None,
        limitations: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> ContentSnapshot:
        raw = raw_content.encode("utf-8") if isinstance(raw_content, str) else bytes(raw_content)
        cleaned = (cleaned_content or "").encode("utf-8")
        digest = hashlib.sha256(raw).hexdigest()
        safe_source = "".join(character for character in str(source_id) if character.isalnum() or character in "._-")[:80]
        filename = f"{safe_source or 'source'}_{digest[:24]}.snap"
        target = (self._dir / filename).resolve()
        target.relative_to(self._dir)

        with self._lock:
            if not target.is_file():
                descriptor, temporary = tempfile.mkstemp(prefix=".snapshot-", dir=self._dir)
                try:
                    with os.fdopen(descriptor, "wb") as stream:
                        stream.write(raw)
                        stream.flush()
                        os.fsync(stream.fileno())
                    os.replace(temporary, target)
                finally:
                    if os.path.exists(temporary):
                        os.unlink(temporary)
            snapshot = ContentSnapshot(
                snapshot_id=f"snap_{uuid.uuid4().hex[:12]}",
                source_id=str(source_id),
                raw_content_hash=digest,
                cleaned_content_hash=hashlib.sha256(cleaned).hexdigest() if cleaned else "",
                content_type=str(content_type or "application/octet-stream"),
                retrieval_headers=dict(retrieval_headers or {}),
                retrieval_timestamp=_utc_now(),
                storage_path=str(target),
                size_bytes=len(raw),
                limitations=list(limitations or []),
                metadata=dict(metadata or {}),
            )
            self._snapshots[snapshot.snapshot_id] = snapshot
            self._persist()
            return snapshot

    def update_artifact(self, snapshot_id: str, artifact_id: str) -> ContentSnapshot:
        with self._lock:
            snapshot = self._snapshots.get(str(snapshot_id))
            if snapshot is None:
                raise KeyError(snapshot_id)
            snapshot.artifact_id = str(artifact_id)
            self._persist()
            return snapshot

    def get(self, snapshot_id: str) -> ContentSnapshot | None:
        with self._lock:
            return self._snapshots.get(str(snapshot_id))

    def list(self, *, source_id: str = "", limit: int = 200) -> list[ContentSnapshot]:
        with self._lock:
            snapshots = list(self._snapshots.values())
        if source_id:
            snapshots = [item for item in snapshots if item.source_id == source_id]
        snapshots.sort(key=lambda item: item.retrieval_timestamp, reverse=True)
        return snapshots[: max(1, min(int(limit), 1000))]

    def get_content(self, snapshot_id: str) -> bytes | None:
        snapshot = self.get(snapshot_id)
        if snapshot is None or not snapshot.storage_path:
            return None
        path = Path(snapshot.storage_path).expanduser().resolve()
        try:
            path.relative_to(self._dir)
        except ValueError:
            return None
        if not path.is_file() or path.stat().st_size != snapshot.size_bytes:
            return None
        content = path.read_bytes()
        return content if self.verify(snapshot_id, content) else None

    def verify(self, snapshot_id: str, content: bytes) -> bool:
        snapshot = self.get(snapshot_id)
        return bool(snapshot and hashlib.sha256(content).hexdigest() == snapshot.raw_content_hash)

    def _load(self) -> None:
        if not self._index.is_file():
            return
        try:
            with file_lock(str(self._index) + ".lock"):
                values = json.loads(self._index.read_text(encoding="utf-8"))
            records = values.get("snapshots", []) if isinstance(values, dict) else values
            for value in records:
                if isinstance(value, dict):
                    snapshot = ContentSnapshot.from_dict(value)
                    if snapshot.snapshot_id:
                        self._snapshots[snapshot.snapshot_id] = snapshot
        except (OSError, ValueError, TypeError):
            self._snapshots.clear()

    def _persist(self) -> None:
        payload = {
            "schema_version": "1.0",
            "snapshots": [snapshot.to_dict() for snapshot in self._snapshots.values()],
        }
        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2).encode("utf-8")
        descriptor, temporary = tempfile.mkstemp(prefix=".snapshot-index-", dir=self._dir)
        try:
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(encoded)
                stream.flush()
                os.fsync(stream.fileno())
            with file_lock(str(self._index) + ".lock"):
                os.replace(temporary, self._index)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
