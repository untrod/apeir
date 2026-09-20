# -*- coding: utf-8 -*-
"""
Memory Manager — full CRUD for long-term user memory.

Implements §7.4 (Long-term Memory) of the master plan.
Memory types: user-explicit, project-facts, task-state, user-preferences,
temporary-session-summary, sensitive (should not persist).

Supports: view, edit, delete, export, retention policies, sensitive marking.
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from nous_runtime.kernel.error_codes import ErrorCode, NousResult
from nous_runtime.compat.ids import make_id

log = logging.getLogger("nous.project.memory")


class MemoryType(str, Enum):
    USER_EXPLICIT = "user_explicit"          # User explicitly asked to save
    PROJECT_FACT = "project_fact"            # Discovered project fact
    TASK_STATE = "task_state"                # Task-related context
    USER_PREFERENCE = "user_preference"      # User behavior preference
    SESSION_SUMMARY = "session_summary"      # Temporary — auto-deleted
    SENSITIVE = "sensitive"                  # Marked for non-persistence


class RetentionPolicy(str, Enum):
    FOREVER = "forever"
    DAYS_30 = "30d"
    DAYS_90 = "90d"
    SESSION = "session"                      # Delete when session ends
    MANUAL = "manual"                        # Only delete on user request


@dataclass
class MemoryRecord:
    """A single memory entry."""
    memory_id: str = field(default_factory=lambda: make_id(prefix="mem"))
    user_id: str = ""
    conversation_id: str = ""
    memory_type: MemoryType = MemoryType.USER_EXPLICIT
    content: str = ""
    tags: list[str] = field(default_factory=list)
    source: str = ""                         # Where it came from
    importance: int = 0                      # 0–10, higher = more important
    access_count: int = 0
    retention: RetentionPolicy = RetentionPolicy.FOREVER
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = ""
    expires_at: str = ""                     # Computed from retention
    deleted: bool = False

    def to_dict(self, include_content: bool = True) -> dict[str, Any]:
        d = {
            "memory_id": self.memory_id,
            "memory_type": self.memory_type.value,
            "tags": self.tags,
            "importance": self.importance,
            "retention": self.retention.value,
            "created_at": self.created_at,
        }
        if include_content:
            d["content"] = self.content
        return d


class MemoryManager:
    """Full CRUD memory management with retention policies.

    Separates long-term memory (persistent) from session memory (temporary).
    Supports export, sensitive marking, and retention-based auto-cleanup.
    """

    def __init__(self, db_path: str):
        self._db_path = db_path
        self._lock = threading.RLock()
        self._ensure_schema()

    def _get_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path)
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _ensure_schema(self) -> None:
        os.makedirs(os.path.dirname(self._db_path) or ".", exist_ok=True)
        with self._get_conn() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS memories (
                    memory_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL DEFAULT '',
                    conversation_id TEXT NOT NULL DEFAULT '',
                    memory_type TEXT NOT NULL DEFAULT 'user_explicit',
                    content TEXT NOT NULL DEFAULT '',
                    tags TEXT NOT NULL DEFAULT '[]',
                    source TEXT NOT NULL DEFAULT '',
                    importance INTEGER NOT NULL DEFAULT 0,
                    access_count INTEGER NOT NULL DEFAULT 0,
                    retention TEXT NOT NULL DEFAULT 'forever',
                    created_at TEXT NOT NULL DEFAULT '',
                    updated_at TEXT NOT NULL DEFAULT '',
                    expires_at TEXT NOT NULL DEFAULT '',
                    deleted INTEGER NOT NULL DEFAULT 0
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_memories_user ON memories(user_id, deleted)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_memories_type ON memories(memory_type, deleted)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_memories_tags ON memories(tags)")
            conn.commit()

    # CRUD

    def save(self, record: MemoryRecord) -> NousResult[MemoryRecord]:
        with self._lock:
            try:
                now = datetime.now(timezone.utc).isoformat()
                with self._get_conn() as conn:
                    conn.execute(
                        """INSERT OR REPLACE INTO memories VALUES
                           (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        (record.memory_id, record.user_id, record.conversation_id,
                         record.memory_type.value, record.content,
                         json.dumps(record.tags), record.source,
                         record.importance, record.access_count,
                         record.retention.value, record.created_at,
                         now, record.expires_at, 0),
                    )
                    conn.commit()
                record.updated_at = now
                return NousResult.ok(record)
            except Exception as e:
                return NousResult.err(ErrorCode.INTERNAL, message=str(e))

    def get(self, memory_id: str) -> NousResult[MemoryRecord]:
        with self._lock:
            try:
                with self._get_conn() as conn:
                    row = conn.execute(
                        "SELECT * FROM memories WHERE memory_id = ? AND deleted = 0",
                        (memory_id,),
                    ).fetchone()
                if row is None:
                    return NousResult.err(ErrorCode.NOT_FOUND,
                                          message=f"Memory '{memory_id}' not found")
                record = self._row_to_record(row)
                # Update access count
                self._increment_access(memory_id)
                return NousResult.ok(record)
            except Exception as e:
                return NousResult.err(ErrorCode.INTERNAL, message=str(e))

    def update(self, memory_id: str, content: str = "",
               importance: int | None = None,
               tags: list[str] | None = None) -> NousResult[MemoryRecord]:
        with self._lock:
            result = self.get(memory_id)
            if not result.ok:
                return result
            record = result.value
            if content:
                record.content = content
            if importance is not None:
                record.importance = importance
            if tags is not None:
                record.tags = tags
            return self.save(record)

    def delete(self, memory_id: str, hard: bool = False) -> NousResult[None]:
        with self._lock:
            try:
                with self._get_conn() as conn:
                    if hard:
                        conn.execute("DELETE FROM memories WHERE memory_id = ?",
                                     (memory_id,))
                    else:
                        conn.execute(
                            "UPDATE memories SET deleted = 1 WHERE memory_id = ?",
                            (memory_id,),
                        )
                    conn.commit()
                return NousResult.ok(None)
            except Exception as e:
                return NousResult.err(ErrorCode.INTERNAL, message=str(e))

    def list_all(self, user_id: str = "", memory_type: str = "",
                 limit: int = 100, include_deleted: bool = False) -> NousResult[list[MemoryRecord]]:
        with self._lock:
            try:
                query = "SELECT * FROM memories WHERE 1=1"
                params: list[Any] = []
                if not include_deleted:
                    query += " AND deleted = 0"
                if user_id:
                    query += " AND user_id = ?"
                    params.append(user_id)
                if memory_type:
                    query += " AND memory_type = ?"
                    params.append(memory_type)
                query += " ORDER BY importance DESC, created_at DESC LIMIT ?"
                params.append(limit)

                with self._get_conn() as conn:
                    rows = conn.execute(query, params).fetchall()
                return NousResult.ok([self._row_to_record(r) for r in rows])
            except Exception as e:
                return NousResult.err(ErrorCode.INTERNAL, message=str(e))

    def search(self, query: str, limit: int = 20) -> NousResult[list[MemoryRecord]]:
        """Simple text search across memory content."""
        with self._lock:
            try:
                with self._get_conn() as conn:
                    rows = conn.execute(
                        """SELECT * FROM memories
                           WHERE deleted = 0 AND content LIKE ?
                           ORDER BY importance DESC LIMIT ?""",
                        (f"%{query}%", limit),
                    ).fetchall()
                return NousResult.ok([self._row_to_record(r) for r in rows])
            except Exception as e:
                return NousResult.err(ErrorCode.INTERNAL, message=str(e))

    def export(self, user_id: str = "", filepath: str = "") -> NousResult[str]:
        """Export memories to JSON file."""
        result = self.list_all(user_id=user_id, limit=10000)
        if not result.ok:
            return NousResult.err(result.code, message=result.message)

        data = [r.to_dict(include_content=True)
                for r in result.value
                if r.memory_type != MemoryType.SENSITIVE]

        path = filepath or os.path.join(os.path.dirname(self._db_path), "memory_export.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

        return NousResult.ok(path)

    def purge_expired(self) -> NousResult[int]:
        """Delete memories past their retention period."""
        now = datetime.now(timezone.utc).isoformat()
        with self._lock:
            try:
                with self._get_conn() as conn:
                    cursor = conn.execute(
                        """UPDATE memories SET deleted = 1
                           WHERE deleted = 0 AND expires_at != ''
                           AND expires_at < ?""",
                        (now,),
                    )
                    count = cursor.rowcount
                    conn.commit()
                if count > 0:
                    log.info("Purged %d expired memories", count)
                return NousResult.ok(count)
            except Exception as e:
                return NousResult.err(ErrorCode.INTERNAL, message=str(e))

    def mark_sensitive(self, memory_id: str) -> NousResult[None]:
        """Mark a memory as sensitive (will not export, auto-delete)."""
        with self._lock:
            try:
                with self._get_conn() as conn:
                    conn.execute(
                        "UPDATE memories SET memory_type = ? WHERE memory_id = ?",
                        (MemoryType.SENSITIVE.value, memory_id),
                    )
                    conn.commit()
                return NousResult.ok(None)
            except Exception as e:
                return NousResult.err(ErrorCode.INTERNAL, message=str(e))

    def count(self, user_id: str = "") -> int:
        with self._lock:
            with self._get_conn() as conn:
                query = "SELECT COUNT(*) FROM memories WHERE deleted = 0"
                params: list[Any] = []
                if user_id:
                    query += " AND user_id = ?"
                    params.append(user_id)
                return conn.execute(query, params).fetchone()[0]

    def _increment_access(self, memory_id: str) -> None:
        with self._get_conn() as conn:
            conn.execute(
                "UPDATE memories SET access_count = access_count + 1 WHERE memory_id = ?",
                (memory_id,),
            )
            conn.commit()

    @staticmethod
    def _row_to_record(row: sqlite3.Row) -> MemoryRecord:
        return MemoryRecord(
            memory_id=row["memory_id"],
            user_id=row["user_id"],
            conversation_id=row["conversation_id"],
            memory_type=MemoryType(row["memory_type"]),
            content=row["content"],
            tags=json.loads(row["tags"]) if row["tags"] else [],
            source=row["source"],
            importance=row["importance"],
            access_count=row["access_count"],
            retention=RetentionPolicy(row["retention"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            expires_at=row["expires_at"],
            deleted=bool(row["deleted"]),
        )
