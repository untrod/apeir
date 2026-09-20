# -*- coding: utf-8 -*-
"""DatasetRegistry — versioned, queryable dataset management."""

from __future__ import annotations

import json
import logging
import threading
import uuid
from pathlib import Path

from .models import DatasetRecord, DatasetType

_log = logging.getLogger("nous.dataset.registry")


class DatasetRegistry:
    """Thread-safe registry of intelligence datasets.

    Enforces: no training/experiment code reads unregistered directories.
    """

    def __init__(self, storage_dir: str = "") -> None:
        from pathlib import Path as _Path
        ws = _Path(storage_dir or _Path.home() / ".nous" / "datasets")
        self._dir = ws
        self._dir.mkdir(parents=True, exist_ok=True)
        self._index_path = self._dir / "dataset_index.json"
        self._lock = threading.RLock()
        self._records: dict[str, DatasetRecord] = {}
        self._load_index()

    # CRUD

    def register(self, record: DatasetRecord) -> str:
        """Register a dataset. Returns dataset_id."""
        if not record.dataset_id:
            record.dataset_id = f"ds_{uuid.uuid4().hex[:12]}"
        record.seal()

        with self._lock:
            # Version check: bump version if dataset_id already exists
            existing = self._records.get(record.dataset_id)
            if existing is not None:
                record = self._bump_version(existing, record)

            self._records[record.dataset_id] = record
            self._save_index()

        _log.info("Registered dataset %s (type=%s, tasks=%d)",
                   record.dataset_id, record.dataset_type.value, record.task_count)
        return record.dataset_id

    def get(self, dataset_id: str) -> DatasetRecord | None:
        with self._lock:
            return self._records.get(dataset_id)

    def query(
        self,
        *,
        dataset_type: DatasetType | None = None,
        privacy_level: str = "",
        source: str = "",
        min_tasks: int = 0,
        since: str = "",
    ) -> list[DatasetRecord]:
        """Query datasets by filter criteria."""
        with self._lock:
            results = list(self._records.values())

        if dataset_type is not None:
            results = [r for r in results if r.dataset_type == dataset_type]
        if privacy_level:
            results = [r for r in results if r.privacy_level == privacy_level]
        if source:
            results = [r for r in results if r.source == source]
        if min_tasks > 0:
            results = [r for r in results if r.task_count >= min_tasks]
        if since:
            results = [r for r in results if r.created_at >= since]

        return sorted(results, key=lambda r: r.created_at, reverse=True)

    def list_all(self) -> list[DatasetRecord]:
        with self._lock:
            return sorted(
                self._records.values(),
                key=lambda r: r.created_at,
                reverse=True,
            )

    def delete(self, dataset_id: str) -> bool:
        with self._lock:
            if dataset_id in self._records:
                del self._records[dataset_id]
                self._save_index()
                return True
        return False

    def count(self) -> int:
        with self._lock:
            return len(self._records)

    # Versioning

    def versions(self, dataset_id: str) -> list[str]:
        """Return all version strings for a dataset."""
        with self._lock:
            return sorted({
                r.version
                for rid, r in self._records.items()
                if rid == dataset_id or rid.startswith(dataset_id)
            })

    def latest_version(self, dataset_id: str) -> DatasetRecord | None:
        versions = self.versions(dataset_id)
        if not versions:
            return None
        latest = versions[-1]
        return self.get(f"{dataset_id}_v{latest}")

    def _bump_version(self, existing: DatasetRecord, new_record: DatasetRecord) -> DatasetRecord:
        """Auto-bump version when re-registering."""
        try:
            parts = existing.version.split(".")
            major, minor, patch = int(parts[0]), int(parts[1]), int(parts[2])
            new_record.version = f"{major}.{minor}.{patch + 1}"
        except (ValueError, IndexError):
            new_record.version = "1.0.1"
        new_record.dataset_id = f"{existing.dataset_id}_v{new_record.version}"
        return new_record

    # Export

    def export_index(self, output_path: str) -> None:
        """Export the full dataset index as JSON."""
        with self._lock:
            data = {
                "datasets": [r.to_dict() for r in self._records.values()],
                "total_count": len(self._records),
            }
        Path(output_path).write_text(
            json.dumps(data, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    # Internal

    def _load_index(self) -> None:
        if not self._index_path.exists():
            return
        try:
            data = json.loads(self._index_path.read_text(encoding="utf-8"))
            for d in data.get("datasets", []):
                record = DatasetRecord.from_dict(d)
                self._records[record.dataset_id] = record
        except Exception as e:
            _log.warning("Failed to load dataset index: %s", e)

    def _save_index(self) -> None:
        data = {
            "datasets": [r.to_dict() for r in self._records.values()],
            "total_count": len(self._records),
        }
        self._index_path.write_text(
            json.dumps(data, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
