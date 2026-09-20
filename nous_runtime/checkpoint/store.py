"""Thread-safe checkpoint storage for transient and durable execution state."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Protocol

from nous_runtime.checkpoint.models import Checkpoint
from nous_runtime.core.redaction import redact_sensitive_data
from nous_runtime.task.exceptions import TaskRuntimeError


class CheckpointStoreError(TaskRuntimeError):
    """Raised when durable checkpoint data cannot be trusted or decoded."""


class CheckpointStore(Protocol):
    def save(self, checkpoint: Checkpoint) -> Checkpoint: ...

    def load(self, checkpoint_id: str) -> Checkpoint | None: ...

    def list(self, task_id: str = "") -> list[Checkpoint]: ...


class InMemoryCheckpointStore:
    """Save, load, and list task checkpoints without external persistence."""

    def __init__(self) -> None:
        self._checkpoints: dict[str, Checkpoint] = {}
        self._lock = threading.RLock()

    def save(self, checkpoint: Checkpoint) -> Checkpoint:
        with self._lock:
            self._checkpoints[checkpoint.checkpoint_id] = checkpoint
        return checkpoint

    def load(self, checkpoint_id: str) -> Checkpoint | None:
        with self._lock:
            return self._checkpoints.get(str(checkpoint_id))

    def list(self, task_id: str = "") -> list[Checkpoint]:
        with self._lock:
            checkpoints = list(self._checkpoints.values())
        if task_id:
            checkpoints = [
                item for item in checkpoints if item.task_id == task_id
            ]
        return sorted(
            checkpoints,
            key=lambda item: (item.timestamp, item.checkpoint_id),
        )


class SQLiteCheckpointStore:
    """SQLite-backed, checksum-verified checkpoint storage.

    Each operation uses its own bounded connection so separate Runtime
    processes can safely save and restore through the same workspace database.
    """

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path).resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._initialize()

    @contextmanager
    def _db(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA busy_timeout=30000")
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _initialize(self) -> None:
        with self._db() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS checkpoints (
                    checkpoint_id TEXT PRIMARY KEY,
                    task_id TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    payload_sha256 TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_checkpoints_task_time
                    ON checkpoints(task_id, timestamp, checkpoint_id);
                """
            )

    def save(self, checkpoint: Checkpoint) -> Checkpoint:
        payload = json.dumps(
            checkpoint.to_dict(),
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
        with self._lock, self._db() as connection:
            connection.execute(
                """
                INSERT INTO checkpoints (
                    checkpoint_id, task_id, timestamp,
                    payload_json, payload_sha256
                ) VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(checkpoint_id) DO UPDATE SET
                    task_id = excluded.task_id,
                    timestamp = excluded.timestamp,
                    payload_json = excluded.payload_json,
                    payload_sha256 = excluded.payload_sha256
                """,
                (
                    checkpoint.checkpoint_id,
                    checkpoint.task_id,
                    checkpoint.timestamp,
                    payload,
                    digest,
                ),
            )
        return checkpoint

    def load(self, checkpoint_id: str) -> Checkpoint | None:
        with self._lock, self._db() as connection:
            row = connection.execute(
                "SELECT * FROM checkpoints WHERE checkpoint_id = ?",
                (str(checkpoint_id),),
            ).fetchone()
        return self._decode(row) if row is not None else None

    def list(self, task_id: str = "") -> list[Checkpoint]:
        query = "SELECT * FROM checkpoints"
        parameters: tuple[str, ...] = ()
        if task_id:
            query += " WHERE task_id = ?"
            parameters = (str(task_id),)
        query += " ORDER BY timestamp, checkpoint_id"
        with self._lock, self._db() as connection:
            rows = connection.execute(query, parameters).fetchall()
        return [self._decode(row) for row in rows]

    def inspect(
        self,
        *,
        limit: int = 20,
        keep_latest_per_task: int = 20,
    ) -> dict[str, Any]:
        """Return a bounded, payload-free integrity and retention report."""
        maximum = max(1, min(int(limit), 100))
        keep_latest = self._validate_keep_latest(keep_latest_per_task)
        with self._lock, self._db() as connection:
            quick_check = [
                str(row[0])
                for row in connection.execute("PRAGMA quick_check").fetchall()
            ]
            rows = connection.execute(
                "SELECT * FROM checkpoints ORDER BY timestamp, checkpoint_id"
            ).fetchall()

        verified, invalid = self._verify_rows(rows)
        plan = self._retention_plan(verified, keep_latest)
        latest = sorted(
            verified,
            key=lambda item: (item.timestamp, item.checkpoint_id),
            reverse=True,
        )[:maximum]
        database_ok = quick_check == ["ok"]
        return {
            "status": "healthy" if database_ok and not invalid else "degraded",
            "database": {
                "filename": self.path.name,
                "exists": self.path.is_file(),
                "size_bytes": self.path.stat().st_size if self.path.is_file() else 0,
            },
            "integrity": {
                "quick_check": "ok" if database_ok else "failed",
                "messages": quick_check[:10],
                "total": len(rows),
                "valid": len(verified),
                "invalid": len(invalid),
            },
            "tasks": len({item.task_id for item in verified}),
            "latest": [
                self._public_metadata(item)
                for item in latest
            ],
            "invalid": invalid[:maximum],
            "retention": {
                "policy": "keep_latest_per_task",
                "keep_latest_per_task": keep_latest,
                "candidate_count": len(plan["candidate_checkpoint_ids"]),
                "protected_count": len(verified) - len(plan["candidate_checkpoint_ids"]),
                "invalid_excluded": len(invalid),
                "plan_digest": plan["plan_digest"],
                "requires_governed_apply": True,
            },
        }

    def prune(
        self,
        *,
        keep_latest_per_task: int,
        expected_plan_digest: str,
    ) -> dict[str, Any]:
        """Apply an exact retention plan after a caller confirms its digest."""
        keep_latest = self._validate_keep_latest(keep_latest_per_task)
        expected = str(expected_plan_digest or "").strip().lower()
        if len(expected) != 64 or any(ch not in "0123456789abcdef" for ch in expected):
            raise CheckpointStoreError(
                "a valid checkpoint retention plan digest is required"
            )

        with self._lock, self._db() as connection:
            connection.execute("BEGIN IMMEDIATE")
            rows = connection.execute(
                "SELECT * FROM checkpoints ORDER BY timestamp, checkpoint_id"
            ).fetchall()
            verified, _invalid = self._verify_rows(rows)
            plan = self._retention_plan(verified, keep_latest)
            if plan["plan_digest"] != expected:
                raise CheckpointStoreError(
                    "checkpoint retention plan changed; request a new preview"
                )
            candidate_ids = plan["candidate_checkpoint_ids"]
            if candidate_ids:
                connection.executemany(
                    "DELETE FROM checkpoints WHERE checkpoint_id = ?",
                    [(checkpoint_id,) for checkpoint_id in candidate_ids],
                )
        return {
            "status": "completed",
            "deleted_count": len(candidate_ids),
            "keep_latest_per_task": keep_latest,
            "plan_digest": expected,
        }

    @classmethod
    def _verify_rows(
        cls,
        rows: list[sqlite3.Row],
    ) -> tuple[list[Checkpoint], list[dict[str, str]]]:
        verified: list[Checkpoint] = []
        invalid: list[dict[str, str]] = []
        for row in rows:
            try:
                verified.append(cls._decode(row))
            except CheckpointStoreError:
                invalid.append(
                    {
                        "checkpoint_id": cls._safe_text(row["checkpoint_id"]),
                        "task_id": cls._safe_text(row["task_id"]),
                        "timestamp": cls._safe_text(row["timestamp"]),
                        "reason": "integrity_verification_failed",
                    }
                )
        return verified, invalid

    @staticmethod
    def _safe_text(value: Any) -> str:
        return str(redact_sensitive_data(str(value or "")))

    @classmethod
    def _public_metadata(cls, checkpoint: Checkpoint) -> dict[str, str]:
        metadata = checkpoint.metadata
        return {
            "checkpoint_id": cls._safe_text(checkpoint.checkpoint_id),
            "task_id": cls._safe_text(checkpoint.task_id),
            "timestamp": cls._safe_text(checkpoint.timestamp),
            "kind": cls._safe_text(metadata.get("kind")),
            "run_id": cls._safe_text(metadata.get("run_id")),
            "agent_id": cls._safe_text(metadata.get("agent_id")),
        }

    @staticmethod
    def _validate_keep_latest(value: int) -> int:
        try:
            keep_latest = int(value)
        except (TypeError, ValueError) as exc:
            raise CheckpointStoreError(
                "keep_latest_per_task must be an integer"
            ) from exc
        if not 1 <= keep_latest <= 10_000:
            raise CheckpointStoreError(
                "keep_latest_per_task must be between 1 and 10000"
            )
        return keep_latest

    @staticmethod
    def _retention_plan(
        checkpoints: list[Checkpoint],
        keep_latest_per_task: int,
    ) -> dict[str, Any]:
        by_task: dict[str, list[Checkpoint]] = {}
        for checkpoint in checkpoints:
            by_task.setdefault(checkpoint.task_id, []).append(checkpoint)

        candidate_ids: list[str] = []
        for task_checkpoints in by_task.values():
            ordered = sorted(
                task_checkpoints,
                key=lambda item: (item.timestamp, item.checkpoint_id),
                reverse=True,
            )
            candidate_ids.extend(
                item.checkpoint_id
                for item in ordered[keep_latest_per_task:]
            )
        candidate_ids.sort()
        canonical = json.dumps(
            {
                "keep_latest_per_task": keep_latest_per_task,
                "candidate_checkpoint_ids": candidate_ids,
            },
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        return {
            "candidate_checkpoint_ids": candidate_ids,
            "plan_digest": hashlib.sha256(
                canonical.encode("utf-8")
            ).hexdigest(),
        }

    @staticmethod
    def _decode(row: sqlite3.Row) -> Checkpoint:
        payload = str(row["payload_json"])
        expected = str(row["payload_sha256"])
        actual = hashlib.sha256(payload.encode("utf-8")).hexdigest()
        if not expected or actual != expected:
            raise CheckpointStoreError(
                f"checkpoint integrity verification failed: {row['checkpoint_id']}"
            )
        try:
            data = json.loads(payload)
            if not isinstance(data, dict):
                raise ValueError("checkpoint payload must be an object")
            checkpoint = Checkpoint.from_dict(data)
        except (TaskRuntimeError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise CheckpointStoreError(
                f"checkpoint payload is invalid: {row['checkpoint_id']}"
            ) from exc
        if (
            checkpoint.checkpoint_id != str(row["checkpoint_id"])
            or checkpoint.task_id != str(row["task_id"])
            or checkpoint.timestamp != str(row["timestamp"])
        ):
            raise CheckpointStoreError(
                f"checkpoint index does not match payload: {row['checkpoint_id']}"
            )
        return checkpoint


__all__ = [
    "CheckpointStore",
    "CheckpointStoreError",
    "InMemoryCheckpointStore",
    "SQLiteCheckpointStore",
]
