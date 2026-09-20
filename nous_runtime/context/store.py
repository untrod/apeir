# -*- coding: utf-8 -*-
"""ContextStore — SQLite persistence for Context Snapshots.

Follows the GovernanceStore pattern: per-workspace store at .nous/context.db.
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from nous_runtime.context.exceptions import ContextStoreError
from nous_runtime.context.models import ContextSnapshot

from nous_runtime.schema_registry import STORE_SCHEMA_VERSION

_log = logging.getLogger("nous.context.store")



# Internal helpers


@contextmanager
def _db_connect(db_path: str, readonly: bool = False):
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if readonly:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    else:
        conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=5000")
    if not readonly:
        conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        yield conn
        if not readonly:
            conn.commit()
    except Exception:
        if not readonly:
            conn.rollback()
        raise
    finally:
        conn.close()



# ContextStore


class ContextStore:
    """SQLite-backed store for ContextSnapshots.

    Usage::

        store = ContextStore(workspace)
        store.save(snapshot)
        snap = store.get("snap_abc123")
        for s in store.list(limit=10):
            ...
    """

    def __init__(self, workspace_path: str | Path = ""):
        if workspace_path:
            self.db_path = str(Path(workspace_path) / "context.db")
        else:
            self.db_path = str(Path(os.getcwd()) / ".nous" / "context.db")
        self._lock = threading.RLock()
        self._ensure_tables()

    # schema

    def _ensure_tables(self) -> None:
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        with self._lock:
            try:
                with _db_connect(self.db_path) as db:
                    db.executescript("""
                        CREATE TABLE IF NOT EXISTS context_snapshots (
                            id TEXT PRIMARY KEY,
                            version INTEGER NOT NULL DEFAULT 1,
                            timestamp TEXT NOT NULL DEFAULT '',
                            status TEXT NOT NULL DEFAULT 'active',
                            schema_version TEXT NOT NULL DEFAULT '1.0.0',
                            confidence REAL NOT NULL DEFAULT 0.0,
                            item_count INTEGER NOT NULL DEFAULT 0,
                            checksum TEXT NOT NULL DEFAULT '',
                            sources_json TEXT NOT NULL DEFAULT '[]',
                            snapshot_json TEXT NOT NULL DEFAULT '{}',
                            created_at TEXT NOT NULL DEFAULT ''
                        );
                        CREATE INDEX IF NOT EXISTS idx_snapshots_timestamp
                            ON context_snapshots(timestamp);
                        CREATE INDEX IF NOT EXISTS idx_snapshots_status
                            ON context_snapshots(status);
                        CREATE INDEX IF NOT EXISTS idx_snapshots_checksum
                            ON context_snapshots(checksum);

                        CREATE TABLE IF NOT EXISTS context_audit (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            snapshot_id TEXT NOT NULL,
                            actor TEXT NOT NULL DEFAULT '',
                            purpose TEXT NOT NULL DEFAULT '',
                            decision TEXT NOT NULL DEFAULT 'allow',
                            timestamp TEXT NOT NULL DEFAULT '',
                            metadata_json TEXT NOT NULL DEFAULT '{}'
                        );
                        CREATE INDEX IF NOT EXISTS idx_audit_snapshot
                            ON context_audit(snapshot_id);
                    """)
                    # Schema version tracking
                    db.execute(
                        "INSERT OR IGNORE INTO context_snapshots(id, version, timestamp, status, "
                        "schema_version, confidence, item_count, checksum, sources_json, snapshot_json, created_at) "
                        "VALUES ('__schema__', 0, '', 'active', ?, 0, 0, '', '[]', '{}', '')",
                        (STORE_SCHEMA_VERSION,),
                    )
            except Exception as exc:
                raise ContextStoreError(f"Failed to initialise context store: {exc}") from exc

    # CRUD

    def save(self, snapshot: ContextSnapshot) -> bool:
        """Persist a ContextSnapshot. Returns True on success."""
        try:
            checksum = snapshot.checksum()
            snapshot_json = json.dumps(snapshot.to_dict(), ensure_ascii=False)
            sources_json = json.dumps(list(snapshot.sources), ensure_ascii=False)

            with self._lock:
                with _db_connect(self.db_path) as db:
                    db.execute(
                        """INSERT OR REPLACE INTO context_snapshots
                           (id, version, timestamp, status, schema_version, confidence,
                            item_count, checksum, sources_json, snapshot_json, created_at)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        (
                            snapshot.id,
                            snapshot.version,
                            snapshot.timestamp,
                            snapshot.status,
                            snapshot.schema_version,
                            snapshot.confidence,
                            snapshot.item_count,
                            checksum,
                            sources_json,
                            snapshot_json,
                            snapshot.timestamp,
                        ),
                    )
            _log.debug("Saved snapshot %s (items=%d, checksum=%s)", snapshot.id, snapshot.item_count, checksum[:12])
            return True
        except Exception as exc:
            _log.error("Failed to save snapshot %s: %s", snapshot.id, exc)
            raise ContextStoreError(f"Failed to save snapshot {snapshot.id}: {exc}") from exc

    def get(self, snapshot_id: str) -> ContextSnapshot | None:
        """Retrieve a single snapshot by id. Returns None if not found."""
        try:
            with _db_connect(self.db_path, readonly=True) as db:
                row = db.execute(
                    "SELECT snapshot_json FROM context_snapshots WHERE id = ?", (snapshot_id,)
                ).fetchone()
            if row is None:
                return None
            return ContextSnapshot.from_dict(json.loads(row["snapshot_json"]))
        except Exception as exc:
            _log.error("Failed to get snapshot %s: %s", snapshot_id, exc)
            raise ContextStoreError(f"Failed to get snapshot {snapshot_id}: {exc}") from exc

    def list(
        self,
        *,
        limit: int = 50,
        offset: int = 0,
        status: str = "",
        order: str = "DESC",
    ) -> list[ContextSnapshot]:
        """List snapshots, newest first by default.

        Args:
            limit: Max snapshots to return.
            offset: Pagination offset.
            status: Filter by status (active, archived, restored, stale). Empty = all.
            order: DESC (newest first) or ASC (oldest first).
        """
        order = "DESC" if order.upper() == "DESC" else "ASC"
        try:
            with _db_connect(self.db_path, readonly=True) as db:
                if status:
                    rows = db.execute(
                        f"""SELECT snapshot_json FROM context_snapshots
                            WHERE id != '__schema__' AND status = ?
                            ORDER BY timestamp {order}
                            LIMIT ? OFFSET ?""",
                        (status, limit, offset),
                    ).fetchall()
                else:
                    rows = db.execute(
                        f"""SELECT snapshot_json FROM context_snapshots
                            WHERE id != '__schema__'
                            ORDER BY timestamp {order}
                            LIMIT ? OFFSET ?""",
                        (limit, offset),
                    ).fetchall()
            return [ContextSnapshot.from_dict(json.loads(r["snapshot_json"])) for r in rows]
        except Exception as exc:
            _log.error("Failed to list snapshots: %s", exc)
            raise ContextStoreError(f"Failed to list snapshots: {exc}") from exc

    def delete(self, snapshot_id: str) -> bool:
        """Delete a snapshot by id. Returns True if a row was deleted."""
        try:
            with self._lock:
                with _db_connect(self.db_path) as db:
                    cur = db.execute("DELETE FROM context_snapshots WHERE id = ? AND id != '__schema__'", (snapshot_id,))
            deleted = cur.rowcount > 0
            if deleted:
                _log.debug("Deleted snapshot %s", snapshot_id)
            return deleted
        except Exception as exc:
            _log.error("Failed to delete snapshot %s: %s", snapshot_id, exc)
            raise ContextStoreError(f"Failed to delete snapshot {snapshot_id}: {exc}") from exc

    def restore(self, snapshot_id: str) -> ContextSnapshot | None:
        """Retrieve a snapshot and mark it as restored.

        This is the canonical entry-point for session recovery.
        """
        snap = self.get(snapshot_id)
        if snap is None:
            return None
        from nous_runtime.context.schema import SnapshotStatus
        restored = snap.with_status(SnapshotStatus.RESTORED)
        self.save(restored)
        return restored

    # audit

    def record_audit(
        self,
        snapshot_id: str,
        actor: str,
        purpose: str,
        decision: str = "allow",
        metadata: dict[str, Any] | None = None,
    ) -> bool:
        """Record an audit entry for context access."""
        from datetime import datetime, timezone
        try:
            with self._lock:
                with _db_connect(self.db_path) as db:
                    db.execute(
                        """INSERT INTO context_audit (snapshot_id, actor, purpose, decision, timestamp, metadata_json)
                           VALUES (?, ?, ?, ?, ?, ?)""",
                        (
                            snapshot_id,
                            actor,
                            purpose,
                            decision,
                            datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                            json.dumps(metadata or {}, ensure_ascii=False),
                        ),
                    )
            return True
        except Exception as exc:
            _log.error("Failed to record audit: %s", exc)
            return False

    def get_audit_log(
        self,
        snapshot_id: str = "",
        actor: str = "",
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """Retrieve audit entries, optionally filtered."""
        try:
            with _db_connect(self.db_path, readonly=True) as db:
                if snapshot_id and actor:
                    rows = db.execute(
                        "SELECT * FROM context_audit WHERE snapshot_id = ? AND actor = ? ORDER BY timestamp DESC LIMIT ?",
                        (snapshot_id, actor, limit),
                    ).fetchall()
                elif snapshot_id:
                    rows = db.execute(
                        "SELECT * FROM context_audit WHERE snapshot_id = ? ORDER BY timestamp DESC LIMIT ?",
                        (snapshot_id, limit),
                    ).fetchall()
                elif actor:
                    rows = db.execute(
                        "SELECT * FROM context_audit WHERE actor = ? ORDER BY timestamp DESC LIMIT ?",
                        (actor, limit),
                    ).fetchall()
                else:
                    rows = db.execute(
                        "SELECT * FROM context_audit ORDER BY timestamp DESC LIMIT ?",
                        (limit,),
                    ).fetchall()
            return [dict(r) for r in rows]
        except Exception as exc:
            _log.error("Failed to get audit log: %s", exc)
            return []

    # stats

    def stats(self) -> dict[str, Any]:
        """Return store-level statistics."""
        try:
            with _db_connect(self.db_path, readonly=True) as db:
                total = db.execute(
                    "SELECT COUNT(*) FROM context_snapshots WHERE id != '__schema__'"
                ).fetchone()[0]
                active = db.execute(
                    "SELECT COUNT(*) FROM context_snapshots WHERE id != '__schema__' AND status = 'active'"
                ).fetchone()[0]
                audit_count = db.execute("SELECT COUNT(*) FROM context_audit").fetchone()[0]
            return {
                "total_snapshots": total,
                "active_snapshots": active,
                "audit_entries": audit_count,
                "db_path": self.db_path,
                "store_schema_version": STORE_SCHEMA_VERSION,
            }
        except Exception as exc:
            _log.error("Failed to get stats: %s", exc)
            return {"error": str(exc)}
