# -*- coding: utf-8 -*-
"""
Persistent Checkpoint Store for Nous Runtime.

Provides SQLite-backed checkpoint persistence (§5.4, §6.3).
Enables task state to survive server restarts and node failures.

Implements:
- Save/load checkpoints
- List checkpoints by object (task, node, etc.)
- Prune old checkpoints
- Crash recovery: find objects that need recovery after restart
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
from contextlib import closing
from dataclasses import dataclass

from nous_runtime.kernel.error_codes import ErrorCode, NousResult
from nous_runtime.kernel.state_machine import Checkpoint


@dataclass
class CheckpointRecord:
    """A persisted checkpoint with metadata for querying."""
    checkpoint: Checkpoint
    row_id: int = 0
    created_at: str = ""


class CheckpointStore:
    """SQLite-backed persistent checkpoint store.

    Thread-safe. Used by NousServer for crash recovery.
    """

    def __init__(self, db_path: str):
        self._db_path = db_path
        self._lock = threading.RLock()
        self._ensure_schema()

    def _get_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=5000")
        return conn

    def _ensure_schema(self) -> None:
        os.makedirs(os.path.dirname(self._db_path) or ".", exist_ok=True)
        with closing(self._get_conn()) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS checkpoints (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    checkpoint_id TEXT NOT NULL UNIQUE,
                    object_id TEXT NOT NULL,
                    object_kind TEXT NOT NULL,
                    node_id TEXT NOT NULL DEFAULT '',
                    sequence_number INTEGER NOT NULL DEFAULT 0,
                    state_snapshot TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    UNIQUE(object_id, sequence_number)
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_checkpoints_object
                ON checkpoints(object_id, sequence_number DESC)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_checkpoints_kind
                ON checkpoints(object_kind, created_at DESC)
            """)
            conn.commit()

    # CRUD

    def save(self, checkpoint: Checkpoint) -> NousResult[Checkpoint]:
        """Persist a checkpoint to the store."""
        with self._lock:
            try:
                with closing(self._get_conn()) as conn:
                    conn.execute(
                        """INSERT OR REPLACE INTO checkpoints
                           (checkpoint_id, object_id, object_kind, node_id,
                            sequence_number, state_snapshot, created_at)
                           VALUES (?, ?, ?, ?, ?, ?, ?)""",
                        (
                            checkpoint.checkpoint_id,
                            checkpoint.object_id,
                            checkpoint.object_kind,
                            checkpoint.node_id,
                            checkpoint.sequence_number,
                            json.dumps(checkpoint.state_snapshot, ensure_ascii=False),
                            checkpoint.created_at,
                        ),
                    )
                    conn.commit()
                return NousResult.ok(checkpoint)
            except Exception as e:
                return NousResult.err(ErrorCode.INTERNAL, message=str(e))

    def load(self, checkpoint_id: str) -> NousResult[Checkpoint]:
        """Load a single checkpoint by ID."""
        with self._lock:
            try:
                with closing(self._get_conn()) as conn:
                    row = conn.execute(
                        "SELECT * FROM checkpoints WHERE checkpoint_id = ?",
                        (checkpoint_id,),
                    ).fetchone()
                if row is None:
                    return NousResult.err(
                        ErrorCode.NOT_FOUND,
                        message=f"Checkpoint '{checkpoint_id}' not found",
                    )
                return NousResult.ok(self._row_to_checkpoint(row))
            except Exception as e:
                return NousResult.err(ErrorCode.INTERNAL, message=str(e))

    def load_latest(self, object_id: str) -> NousResult[Checkpoint]:
        """Load the most recent checkpoint for an object."""
        with self._lock:
            try:
                with closing(self._get_conn()) as conn:
                    row = conn.execute(
                        """SELECT * FROM checkpoints
                           WHERE object_id = ?
                           ORDER BY sequence_number DESC LIMIT 1""",
                        (object_id,),
                    ).fetchone()
                if row is None:
                    return NousResult.err(
                        ErrorCode.NOT_FOUND,
                        message=f"No checkpoint for '{object_id}'",
                    )
                return NousResult.ok(self._row_to_checkpoint(row))
            except Exception as e:
                return NousResult.err(ErrorCode.INTERNAL, message=str(e))

    def list_for_object(self, object_id: str, limit: int = 10) -> NousResult[list[Checkpoint]]:
        """List checkpoints for a specific object, newest first."""
        with self._lock:
            try:
                with closing(self._get_conn()) as conn:
                    rows = conn.execute(
                        """SELECT * FROM checkpoints
                           WHERE object_id = ?
                           ORDER BY sequence_number DESC LIMIT ?""",
                        (object_id, limit),
                    ).fetchall()
                return NousResult.ok([self._row_to_checkpoint(r) for r in rows])
            except Exception as e:
                return NousResult.err(ErrorCode.INTERNAL, message=str(e))

    # Recovery

    def find_recoverable(self, object_kind: str = "Task") -> NousResult[list[Checkpoint]]:
        """Find objects that were active before a crash and need recovery.

        Returns the latest checkpoint for each active object (one per object_id).
        Used during server startup to resume interrupted work.

        Active objects are those whose latest checkpoint is not in a terminal
        state (determined by the state_snapshot.phase field).
        """
        with self._lock:
            try:
                with closing(self._get_conn()) as conn:
                    # Get latest checkpoint per object
                    rows = conn.execute(
                        """SELECT c.* FROM checkpoints c
                           INNER JOIN (
                               SELECT object_id, MAX(sequence_number) as max_seq
                               FROM checkpoints
                               WHERE object_kind = ?
                               GROUP BY object_id
                           ) latest
                           ON c.object_id = latest.object_id
                           AND c.sequence_number = latest.max_seq
                           ORDER BY c.created_at DESC""",
                        (object_kind,),
                    ).fetchall()

                checkpoints = [self._row_to_checkpoint(r) for r in rows]

                # Filter out terminal states
                terminal_phases = {
                    "completed", "completed_with_warnings",
                    "failed", "failed_verification", "cancelled",
                }
                active = [
                    c for c in checkpoints
                    if c.state_snapshot.get("phase", "") not in terminal_phases
                ]

                return NousResult.ok(active)
            except Exception as e:
                return NousResult.err(ErrorCode.INTERNAL, message=str(e))

    # Maintenance

    def prune(self, before_sequence: int = 0, max_per_object: int = 50) -> NousResult[int]:
        """Remove old checkpoints, keeping the most recent ones per object."""
        with self._lock:
            try:
                with closing(self._get_conn()) as conn:
                    # Delete checkpoints beyond max_per_object for each object
                    cursor = conn.execute(
                        """DELETE FROM checkpoints WHERE id IN (
                               SELECT id FROM (
                                   SELECT id,
                                          ROW_NUMBER() OVER (
                                              PARTITION BY object_id
                                              ORDER BY sequence_number DESC
                                          ) as rn
                                   FROM checkpoints
                               ) WHERE rn > ?
                           )""",
                        (max_per_object,),
                    )
                    deleted = cursor.rowcount
                    conn.commit()
                return NousResult.ok(deleted)
            except Exception as e:
                return NousResult.err(ErrorCode.INTERNAL, message=str(e))

    def count(self) -> int:
        with self._lock:
            with closing(self._get_conn()) as conn:
                return conn.execute("SELECT COUNT(*) FROM checkpoints").fetchone()[0]

    # Helpers

    @staticmethod
    def _row_to_checkpoint(row: sqlite3.Row) -> Checkpoint:
        return Checkpoint(
            checkpoint_id=row["checkpoint_id"],
            object_id=row["object_id"],
            object_kind=row["object_kind"],
            node_id=row["node_id"] or "",
            sequence_number=row["sequence_number"],
            state_snapshot=json.loads(row["state_snapshot"]),
            created_at=row["created_at"],
        )
