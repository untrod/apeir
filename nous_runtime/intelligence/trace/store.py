# -*- coding: utf-8 -*-
"""TraceStore — JSONL + SQLite dual persistence for ExecutionTraceRecord.

Features:
- Append-only JSONL (primary, immutable)
- SQLite index (fast query)
- Schema migration
- Anonymization (basic, strict, anonymous levels)
- Export (JSONL, JSON array) and deletion
- Thread-safe writes
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import sqlite3
import threading
import uuid
from pathlib import Path
from typing import Any

from .schema import ExecutionTraceRecord, TRACE_SCHEMA_VERSION

_log = logging.getLogger("nous.trace.store")


class TraceStore:
    """Dual-persistence store for execution trace records."""

    def __init__(self, workspace_root: str = "") -> None:
        ws = Path(workspace_root or os.path.expanduser("~/.nous"))
        self._dir = ws / "traces"
        self._dir.mkdir(parents=True, exist_ok=True)
        self._jsonl_path = self._dir / "traces.jsonl"
        self._db_path = self._dir / "traces.db"
        self._lock = threading.Lock()
        self._db: sqlite3.Connection | None = None
        self._ensure_db()

    # Write

    def append(self, record: ExecutionTraceRecord) -> str:
        """Persist a trace record. Returns the trace_id."""
        if not record.trace_id:
            record.trace_id = f"etr_{uuid.uuid4().hex[:16]}"
        record.seal()

        # JSONL append (primary)
        with self._lock:
            with open(self._jsonl_path, "a", encoding="utf-8") as f:
                f.write(record.to_jsonl() + "\n")
            self._index_record(record)

        return record.trace_id

    def append_batch(self, records: list[ExecutionTraceRecord]) -> list[str]:
        """Persist multiple trace records efficiently."""
        ids = []
        with self._lock:
            with open(self._jsonl_path, "a", encoding="utf-8") as f:
                for record in records:
                    if not record.trace_id:
                        record.trace_id = f"etr_{uuid.uuid4().hex[:16]}"
                    record.seal()
                    f.write(record.to_jsonl() + "\n")
                    self._index_record(record)
                    ids.append(record.trace_id)
        return ids

    # Read

    def get(self, trace_id: str) -> ExecutionTraceRecord | None:
        """Get a single trace by ID (uses SQLite index)."""
        self._ensure_db()
        if self._db is None:
            return self._load_from_jsonl(trace_id)
        try:
            row = self._db.execute(
                "SELECT payload FROM trace_index WHERE trace_id = ?",
                (trace_id,),
            ).fetchone()
            if row:
                return ExecutionTraceRecord.from_dict(json.loads(row[0]))
        except Exception as e:
            _log.warning("Failed to query trace %s: %s", trace_id, e)
        return self._load_from_jsonl(trace_id)

    def query(
        self,
        *,
        task_type: str = "",
        session_id: str = "",
        model_id: str = "",
        status: str = "",
        since: str = "",
        limit: int = 100,
        offset: int = 0,
    ) -> list[ExecutionTraceRecord]:
        """Query traces with filters. Falls back to JSONL scan if DB unavailable."""
        self._ensure_db()
        if self._db is not None:
            return self._query_db(
                task_type=task_type, session_id=session_id,
                model_id=model_id, status=status,
                since=since, limit=limit, offset=offset,
            )
        return self._query_jsonl(
            task_type=task_type, session_id=session_id,
            status=status, since=since, limit=limit, offset=offset,
        )

    def count(self, **filters: str) -> int:
        """Count traces matching filters."""
        records = self.query(limit=100000, **filters)
        return len(records)

    def all_ids(self) -> list[str]:
        """Return all trace IDs."""
        self._ensure_db()
        if self._db is None:
            return self._all_ids_jsonl()
        try:
            rows = self._db.execute("SELECT trace_id FROM trace_index").fetchall()
            return [r[0] for r in rows]
        except Exception:
            return self._all_ids_jsonl()

    # Export

    def export_jsonl(self, output_path: str, **filters: str) -> int:
        """Export matching traces to a new JSONL file."""
        records = self.query(limit=100000, **filters)
        path = Path(output_path)
        count = 0
        with open(path, "w", encoding="utf-8") as f:
            for r in records:
                f.write(r.to_jsonl() + "\n")
                count += 1
        return count

    def export_json(self, output_path: str, **filters: str) -> int:
        """Export matching traces as a JSON array."""
        records = self.query(limit=100000, **filters)
        path = Path(output_path)
        data = [r.to_dict() for r in records]
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        return len(data)

    # Anonymization

    def anonymize(
        self,
        trace_id: str,
        level: str = "basic",
    ) -> ExecutionTraceRecord | None:
        """Return an anonymized copy of a trace.

        Levels:
          basic  — remove user content, keep model/node IDs
          strict — remove all IDs, keep statistics
          anonymous — remove all potentially identifying information
        """
        record = self.get(trace_id)
        if record is None:
            return None

        # Create a copy
        r = ExecutionTraceRecord.from_dict(record.to_dict())
        r.sanitization_level = level

        if level in ("strict", "anonymous"):
            r.task_info.task_id = _hash_id(r.task_info.task_id)
            r.session_id = _hash_id(r.session_id)
            r.environment.node_id = _hash_id(r.environment.node_id)

        if level == "anonymous":
            r.task_info.user_preferences = {}
            r.decision.rejected_plans = [
                _hash_id(p) for p in r.decision.rejected_plans
            ]
            r.execution.model_assignments = {
                k: _hash_id(v) for k, v in r.execution.model_assignments.items()
            }
            r.execution.node_assignments = {
                k: _hash_id(v) for k, v in r.execution.node_assignments.items()
            }
            r.outcome.artifact_ids = [
                _hash_id(a) for a in r.outcome.artifact_ids
            ]

        r.seal()
        return r

    # Delete

    def delete(self, trace_id: str) -> bool:
        """Delete a trace record."""
        self._ensure_db()
        deleted = False
        if self._db is not None:
            try:
                self._db.execute(
                    "DELETE FROM trace_index WHERE trace_id = ?",
                    (trace_id,),
                )
                self._db.commit()
                deleted = True
            except Exception as e:
                _log.warning("Failed to delete from DB: %s", e)

        # Also remove from JSONL (rewrite)
        if self._jsonl_path.exists():
            lines = self._jsonl_path.read_text(encoding="utf-8").splitlines()
            kept = []
            found = False
            for line in lines:
                try:
                    d = json.loads(line)
                    if d.get("trace_id") == trace_id:
                        found = True
                        continue
                    kept.append(line)
                except json.JSONDecodeError:
                    kept.append(line)
            if found:
                self._jsonl_path.write_text("\n".join(kept) + ("\n" if kept else ""), encoding="utf-8")
                deleted = True

        return deleted or deleted

    def delete_all(self) -> int:
        """Delete all trace records. Returns count deleted."""
        count = self.count()
        if self._jsonl_path.exists():
            self._jsonl_path.write_text("", encoding="utf-8")
        self._ensure_db()
        if self._db is not None:
            try:
                self._db.execute("DELETE FROM trace_index")
                self._db.commit()
            except Exception as e:
                _log.warning("Failed to clear DB: %s", e)
        return count

    # Migration

    def migrate_schema(self, from_version: str, to_version: str) -> int:
        """Migrate traces from one schema version to another.

        Current implementation: no-op since we're at v1.0.0.
        Future versions will implement actual migration logic here.
        """
        if from_version == to_version:
            return 0
        _log.info(
            "Schema migration %s → %s: no migration path defined yet",
            from_version, to_version,
        )
        return 0

    # Statistics

    def statistics(self) -> dict[str, Any]:
        """Return aggregate statistics over all traces."""
        self._ensure_db()
        if self._db is not None:
            try:
                total = self._db.execute("SELECT COUNT(*) FROM trace_index").fetchone()
                return {
                    "total_traces": int(total[0]) if total else 0,
                    "storage_jsonl_bytes": self._jsonl_path.stat().st_size if self._jsonl_path.exists() else 0,
                    "storage_db_bytes": self._db_path.stat().st_size if self._db_path.exists() else 0,
                    "schema_version": TRACE_SCHEMA_VERSION,
                }
            except Exception:
                pass
        return {"total_traces": 0, "schema_version": TRACE_SCHEMA_VERSION}

    def close(self) -> None:
        """Close the SQLite index connection owned by this store."""
        with self._lock:
            if self._db is None:
                return
            self._db.close()
            self._db = None

    shutdown = close

    def __enter__(self) -> "TraceStore":
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.close()

    # Internal

    def _ensure_db(self) -> None:
        if self._db is not None:
            return
        try:
            self._db = sqlite3.connect(str(self._db_path), check_same_thread=False, timeout=5.0)
            self._db.execute("PRAGMA journal_mode=WAL")
            self._db.execute("""
                CREATE TABLE IF NOT EXISTS trace_index (
                    trace_id TEXT PRIMARY KEY,
                    task_type TEXT NOT NULL DEFAULT '',
                    session_id TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL DEFAULT '',
                    model_id TEXT NOT NULL DEFAULT '',
                    sequence INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL DEFAULT '',
                    payload TEXT NOT NULL DEFAULT '{}'
                )
            """)
            for col in ("task_type", "session_id", "status", "model_id", "sequence", "created_at"):
                try:
                    self._db.execute(
                        f"CREATE INDEX IF NOT EXISTS idx_trace_{col} ON trace_index({col})"
                    )
                except Exception:
                    pass
            self._db.commit()
        except Exception as e:
            _log.warning("Failed to init trace store DB: %s", e)
            self._db = None

    def _index_record(self, record: ExecutionTraceRecord) -> None:
        self._ensure_db()
        if self._db is None:
            return
        try:
            self._db.execute(
                """INSERT OR REPLACE INTO trace_index
                   (trace_id, task_type, session_id, status, model_id,
                    sequence, created_at, payload)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (
                    record.trace_id,
                    record.task_info.task_type,
                    record.session_id,
                    record.outcome.final_status,
                    next(iter(record.execution.model_assignments.values()), ""),
                    record.sequence,
                    record.created_at,
                    json.dumps(record.to_dict(), ensure_ascii=False),
                ),
            )
            self._db.commit()
        except Exception as e:
            _log.warning("Failed to index trace %s: %s", record.trace_id, e)

    def _load_from_jsonl(self, trace_id: str) -> ExecutionTraceRecord | None:
        if not self._jsonl_path.exists():
            return None
        try:
            for line in self._jsonl_path.read_text(encoding="utf-8").splitlines():
                try:
                    d = json.loads(line)
                    if d.get("trace_id") == trace_id:
                        return ExecutionTraceRecord.from_dict(d)
                except json.JSONDecodeError:
                    continue
        except Exception as e:
            _log.warning("Failed to scan JSONL: %s", e)
        return None

    def _query_db(self, **kwargs: Any) -> list[ExecutionTraceRecord]:
        conditions: list[str] = []
        params: list[Any] = []

        for field, col in [
            ("task_type", "task_type"),
            ("session_id", "session_id"),
            ("status", "status"),
            ("model_id", "model_id"),
        ]:
            if kwargs.get(field):
                conditions.append(f"{col} = ?")
                params.append(kwargs[field])

        if kwargs.get("since"):
            conditions.append("created_at >= ?")
            params.append(kwargs["since"])

        where = (" WHERE " + " AND ".join(conditions)) if conditions else ""
        limit = max(1, min(int(kwargs.get("limit", 100)), 1000))
        offset = max(0, int(kwargs.get("offset", 0)))

        try:
            rows = self._db.execute(
                f"SELECT payload FROM trace_index{where} "
                f"ORDER BY sequence DESC LIMIT ? OFFSET ?",
                params + [limit, offset],
            ).fetchall() if self._db else []
            return [ExecutionTraceRecord.from_dict(json.loads(r[0])) for r in rows]
        except Exception as e:
            _log.warning("Failed to query DB: %s", e)
            return []

    def _query_jsonl(self, **kwargs: Any) -> list[ExecutionTraceRecord]:
        if not self._jsonl_path.exists():
            return []
        results = []
        limit = max(1, min(int(kwargs.get("limit", 100)), 1000))
        offset = max(0, int(kwargs.get("offset", 0)))
        skipped = 0
        for line in self._jsonl_path.read_text(encoding="utf-8").splitlines():
            try:
                d = json.loads(line)
            except json.JSONDecodeError:
                continue
            # Apply filters
            if kwargs.get("task_type") and d.get("task_info", {}).get("task_type") != kwargs["task_type"]:
                continue
            if kwargs.get("session_id") and d.get("session_id") != kwargs["session_id"]:
                continue
            if kwargs.get("status") and d.get("outcome", {}).get("final_status") != kwargs["status"]:
                continue
            if kwargs.get("since") and d.get("created_at", "") < kwargs["since"]:
                continue
            if skipped < offset:
                skipped += 1
                continue
            results.append(ExecutionTraceRecord.from_dict(d))
            if len(results) >= limit:
                break
        return results

    def _all_ids_jsonl(self) -> list[str]:
        if not self._jsonl_path.exists():
            return []
        ids = []
        for line in self._jsonl_path.read_text(encoding="utf-8").splitlines():
            try:
                d = json.loads(line)
                tid = d.get("trace_id", "")
                if tid:
                    ids.append(tid)
            except json.JSONDecodeError:
                pass
        return ids


def _hash_id(value: str) -> str:
    """Hash an identifier for anonymization."""
    if not value:
        return ""
    return hashlib.sha256(value.encode()).hexdigest()[:12]
