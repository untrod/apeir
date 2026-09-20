# -*- coding: utf-8 -*-
"""ExperienceStore — SQLite persistence for experience records and patterns."""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from nous_runtime.experience.models import ExperiencePattern, ExperienceRecord

_log = logging.getLogger("nous.experience.store")


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


class ExperienceStore:
    """SQLite-backed store for experience records and patterns."""

    def __init__(self, workspace_path: str | Path = ""):
        if workspace_path:
            self.db_path = str(Path(workspace_path) / "experience.db")
        else:
            self.db_path = str(Path(os.getcwd()) / ".nous" / "experience.db")
        self._lock = threading.RLock()
        self._ensure_tables()

    def _ensure_tables(self) -> None:
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        with self._lock:
            with _db_connect(self.db_path) as db:
                db.executescript("""
                    CREATE TABLE IF NOT EXISTS experiences (
                        id TEXT PRIMARY KEY,
                        source_type TEXT NOT NULL DEFAULT '',
                        task_type TEXT NOT NULL DEFAULT '',
                        task_summary TEXT NOT NULL DEFAULT '',
                        context_hash TEXT NOT NULL DEFAULT '',
                        action TEXT NOT NULL DEFAULT '',
                        agent_id TEXT NOT NULL DEFAULT '',
                        provider_id TEXT NOT NULL DEFAULT '',
                        result TEXT NOT NULL DEFAULT '',
                        evaluation_score REAL NOT NULL DEFAULT 0.0,
                        success INTEGER NOT NULL DEFAULT 0,
                        failure_reason TEXT NOT NULL DEFAULT '',
                        error_code TEXT NOT NULL DEFAULT '',
                        confidence REAL NOT NULL DEFAULT 0.5,
                        status TEXT NOT NULL DEFAULT 'new',
                        occurrence_count INTEGER NOT NULL DEFAULT 1,
                        created_at TEXT NOT NULL DEFAULT '',
                        record_json TEXT NOT NULL DEFAULT '{}'
                    );
                    CREATE INDEX IF NOT EXISTS idx_exp_task_type ON experiences(task_type);
                    CREATE INDEX IF NOT EXISTS idx_exp_status ON experiences(status);
                    CREATE INDEX IF NOT EXISTS idx_exp_result ON experiences(result);
                    CREATE INDEX IF NOT EXISTS idx_exp_context_hash ON experiences(context_hash);
                    CREATE INDEX IF NOT EXISTS idx_exp_created ON experiences(created_at);

                    CREATE TABLE IF NOT EXISTS experience_patterns (
                        id TEXT PRIMARY KEY,
                        pattern_type TEXT NOT NULL DEFAULT '',
                        name TEXT NOT NULL DEFAULT '',
                        description TEXT NOT NULL DEFAULT '',
                        frequency INTEGER NOT NULL DEFAULT 0,
                        success_rate REAL NOT NULL DEFAULT 0.0,
                        confidence REAL NOT NULL DEFAULT 0.0,
                        created_at TEXT NOT NULL DEFAULT '',
                        pattern_json TEXT NOT NULL DEFAULT '{}'
                    );
                    CREATE INDEX IF NOT EXISTS idx_pat_type ON experience_patterns(pattern_type);

                    CREATE TABLE IF NOT EXISTS policy_proposals (
                        id TEXT PRIMARY KEY,
                        title TEXT NOT NULL DEFAULT '',
                        target_policy TEXT NOT NULL DEFAULT '',
                        status TEXT NOT NULL DEFAULT 'proposed',
                        confidence REAL NOT NULL DEFAULT 0.0,
                        created_at TEXT NOT NULL DEFAULT '',
                        proposal_json TEXT NOT NULL DEFAULT '{}'
                    );
                """)

    # -- Experience CRUD --

    def save(self, record: ExperienceRecord) -> bool:
        try:
            record_json = json.dumps(record.to_dict(), ensure_ascii=False)
            with self._lock:
                with _db_connect(self.db_path) as db:
                    db.execute(
                        """INSERT OR REPLACE INTO experiences
                           (id, source_type, task_type, task_summary, context_hash,
                            action, agent_id, provider_id, result, evaluation_score,
                            success, failure_reason, error_code, confidence, status,
                            occurrence_count, created_at, record_json)
                           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                        (record.id, record.source_type, record.task_type, record.task_summary,
                         record.context_hash, record.action, record.agent_id, record.provider_id,
                         record.result, record.evaluation_score, int(record.success),
                         record.failure_reason, record.error_code, record.confidence,
                         record.status, record.occurrence_count, record.created_at, record_json),
                    )
            return True
        except Exception as exc:
            _log.error("Failed to save experience: %s", exc)
            return False

    def get(self, record_id: str) -> ExperienceRecord | None:
        try:
            with _db_connect(self.db_path, readonly=True) as db:
                row = db.execute("SELECT record_json FROM experiences WHERE id = ?", (record_id,)).fetchone()
            if row is None:
                return None
            return ExperienceRecord.from_dict(json.loads(row["record_json"]))
        except Exception as exc:
            _log.error("Failed to get experience: %s", exc)
            return None

    def list(
        self, *, task_type: str = "", status: str = "", result: str = "",
        limit: int = 50, offset: int = 0,
    ) -> list[ExperienceRecord]:
        try:
            query = "SELECT record_json FROM experiences WHERE 1=1"
            params: list[Any] = []
            if task_type:
                query += " AND task_type = ?"
                params.append(task_type)
            if status:
                query += " AND status = ?"
                params.append(status)
            if result:
                query += " AND result = ?"
                params.append(result)
            query += " ORDER BY created_at DESC LIMIT ? OFFSET ?"
            params.extend([limit, offset])
            with _db_connect(self.db_path, readonly=True) as db:
                rows = db.execute(query, params).fetchall()
            return [ExperienceRecord.from_dict(json.loads(r["record_json"])) for r in rows]
        except Exception as exc:
            _log.error("Failed to list experiences: %s", exc)
            return []

    def search(self, query_text: str, limit: int = 20) -> list[ExperienceRecord]:
        """Full-text-ish search across task_summary, action, failure_reason, lessons."""
        try:
            like = f"%{query_text}%"
            with _db_connect(self.db_path, readonly=True) as db:
                rows = db.execute(
                    """SELECT record_json FROM experiences
                       WHERE task_summary LIKE ? OR action LIKE ?
                          OR failure_reason LIKE ? OR record_json LIKE ?
                       ORDER BY created_at DESC LIMIT ?""",
                    (like, like, like, like, limit),
                ).fetchall()
            return [ExperienceRecord.from_dict(json.loads(r["record_json"])) for r in rows]
        except Exception as exc:
            _log.error("Failed to search experiences: %s", exc)
            return []

    def update_status(self, record_id: str, status: str) -> bool:
        try:
            with self._lock:
                with _db_connect(self.db_path) as db:
                    db.execute("UPDATE experiences SET status = ? WHERE id = ?", (status, record_id))
                    # Also update the status in record_json
                    row = db.execute("SELECT record_json FROM experiences WHERE id = ?", (record_id,)).fetchone()
                    if row:
                        record_data = json.loads(row["record_json"])
                        record_data["status"] = status
                        db.execute("UPDATE experiences SET record_json = ? WHERE id = ?",
                                  (json.dumps(record_data, ensure_ascii=False), record_id))
            return True
        except Exception as exc:
            _log.error("Failed to update status: %s", exc)
            return False

    # -- Patterns --

    def save_pattern(self, pattern: ExperiencePattern) -> bool:
        try:
            pattern_json = json.dumps(pattern.to_dict(), ensure_ascii=False)
            with self._lock:
                with _db_connect(self.db_path) as db:
                    db.execute(
                        """INSERT OR REPLACE INTO experience_patterns
                           (id, pattern_type, name, description, frequency,
                            success_rate, confidence, created_at, pattern_json)
                           VALUES (?,?,?,?,?,?,?,?,?)""",
                        (pattern.id, pattern.pattern_type, pattern.name, pattern.description,
                         pattern.frequency, pattern.success_rate, pattern.confidence,
                         pattern.created_at, pattern_json),
                    )
            return True
        except Exception as exc:
            _log.error("Failed to save pattern: %s", exc)
            return False

    def list_patterns(self, pattern_type: str = "", limit: int = 50) -> list[ExperiencePattern]:
        try:
            query = "SELECT pattern_json FROM experience_patterns WHERE 1=1"
            params: list[Any] = []
            if pattern_type:
                query += " AND pattern_type = ?"
                params.append(pattern_type)
            query += " ORDER BY frequency DESC LIMIT ?"
            params.append(limit)
            with _db_connect(self.db_path, readonly=True) as db:
                rows = db.execute(query, params).fetchall()
            return [ExperiencePattern.from_dict(json.loads(r["pattern_json"])) for r in rows]
        except Exception as exc:
            _log.error("Failed to list patterns: %s", exc)
            return []

    # -- Stats --

    def stats(self) -> dict[str, Any]:
        try:
            with _db_connect(self.db_path, readonly=True) as db:
                total = db.execute("SELECT COUNT(*) FROM experiences").fetchone()[0]
                trusted = db.execute("SELECT COUNT(*) FROM experiences WHERE status='trusted'").fetchone()[0]
                success = db.execute("SELECT COUNT(*) FROM experiences WHERE success=1").fetchone()[0]
                patterns = db.execute("SELECT COUNT(*) FROM experience_patterns").fetchone()[0]
            return {
                "total_experiences": total,
                "trusted": trusted,
                "success_count": success,
                "success_rate": round(success / max(total, 1), 3),
                "patterns": patterns,
            }
        except Exception:
            return {"total_experiences": 0, "trusted": 0, "success_count": 0, "success_rate": 0.0, "patterns": 0}
