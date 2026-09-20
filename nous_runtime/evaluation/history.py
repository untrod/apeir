# -*- coding: utf-8 -*-
"""Evaluation History — persistent memory of what works.

Connects to future Experience Runtime. Saves evaluation records so the
Scheduler can prioritize proven approaches.
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

from nous_runtime.evaluation.models import EvaluationRecord

_log = logging.getLogger("nous.evaluation.history")




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



# EvaluationHistory


class EvaluationHistory:
    """Persistent store of evaluation records.

    Usage::

        history = EvaluationHistory(workspace)
        history.save(record)
        records = history.list(target_type="agent", limit=20)
        trend = history.trend("agent", "agent_claude")
    """

    def __init__(self, workspace_path: str | Path = ""):
        if workspace_path:
            self.db_path = str(Path(workspace_path) / "evaluation.db")
        else:
            self.db_path = str(Path(os.getcwd()) / ".nous" / "evaluation.db")
        self._lock = threading.RLock()
        self._ensure_tables()

    def _ensure_tables(self) -> None:
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        with self._lock:
            try:
                with _db_connect(self.db_path) as db:
                    db.executescript("""
                        CREATE TABLE IF NOT EXISTS evaluation_records (
                            id TEXT PRIMARY KEY,
                            target_type TEXT NOT NULL DEFAULT '',
                            target_id TEXT NOT NULL DEFAULT '',
                            status TEXT NOT NULL DEFAULT 'pending',
                            input_summary TEXT NOT NULL DEFAULT '',
                            composite_score REAL NOT NULL DEFAULT 0.0,
                            confidence REAL NOT NULL DEFAULT 0.0,
                            recommendation TEXT NOT NULL DEFAULT '',
                            evaluated_by TEXT NOT NULL DEFAULT '',
                            created_at TEXT NOT NULL DEFAULT '',
                            duration_ms INTEGER NOT NULL DEFAULT 0,
                            record_json TEXT NOT NULL DEFAULT '{}'
                        );
                        CREATE INDEX IF NOT EXISTS idx_eval_target
                            ON evaluation_records(target_type, target_id);
                        CREATE INDEX IF NOT EXISTS idx_eval_created
                            ON evaluation_records(created_at);
                        CREATE INDEX IF NOT EXISTS idx_eval_status
                            ON evaluation_records(status);
                    """)
            except Exception as exc:
                _log.error("Failed to init evaluation history: %s", exc)

    # -- CRUD --

    def save(self, record: EvaluationRecord) -> bool:
        """Persist an evaluation record."""
        try:
            record_json = json.dumps(record.to_dict(), ensure_ascii=False)
            with self._lock:
                with _db_connect(self.db_path) as db:
                    db.execute(
                        """INSERT OR REPLACE INTO evaluation_records
                           (id, target_type, target_id, status, input_summary,
                            composite_score, confidence, recommendation,
                            evaluated_by, created_at, duration_ms, record_json)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        (
                            record.id, record.target_type, record.target_id,
                            record.status, record.input_summary,
                            record.composite_score, record.confidence,
                            record.recommendation, record.evaluated_by,
                            record.created_at, record.duration_ms, record_json,
                        ),
                    )
            return True
        except Exception as exc:
            _log.error("Failed to save evaluation record: %s", exc)
            return False

    def get(self, record_id: str) -> EvaluationRecord | None:
        """Retrieve a single evaluation record."""
        try:
            with _db_connect(self.db_path, readonly=True) as db:
                row = db.execute(
                    "SELECT record_json FROM evaluation_records WHERE id = ?",
                    (record_id,),
                ).fetchone()
            if row is None:
                return None
            return EvaluationRecord.from_dict(json.loads(row["record_json"]))
        except Exception as exc:
            _log.error("Failed to get evaluation record: %s", exc)
            return None

    def list(
        self,
        *,
        target_type: str = "",
        target_id: str = "",
        status: str = "",
        limit: int = 50,
        order: str = "DESC",
    ) -> list[EvaluationRecord]:
        """List evaluation records with optional filters."""
        order = "DESC" if order.upper() == "DESC" else "ASC"
        try:
            with _db_connect(self.db_path, readonly=True) as db:
                query = "SELECT record_json FROM evaluation_records WHERE 1=1"
                params: list[Any] = []
                if target_type:
                    query += " AND target_type = ?"
                    params.append(target_type)
                if target_id:
                    query += " AND target_id = ?"
                    params.append(target_id)
                if status:
                    query += " AND status = ?"
                    params.append(status)
                query += f" ORDER BY created_at {order} LIMIT ?"
                params.append(limit)
                rows = db.execute(query, params).fetchall()
            return [EvaluationRecord.from_dict(json.loads(r["record_json"])) for r in rows]
        except Exception as exc:
            _log.error("Failed to list evaluation records: %s", exc)
            return []

    # -- Analytics --

    def trend(
        self,
        target_type: str,
        target_id: str = "",
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """Get score trend over time for a target."""
        records = self.list(
            target_type=target_type,
            target_id=target_id,
            limit=limit,
            order="ASC",
        )
        return [
            {
                "id": r.id,
                "created_at": r.created_at,
                "composite_score": r.composite_score,
                "status": r.status,
                "recommendation": r.recommendation,
            }
            for r in records
        ]

    def best_approach(
        self,
        target_type: str,
        min_samples: int = 3,
    ) -> dict[str, Any]:
        """Find the best-performing approach for a target type.

        Returns the target_id with the highest average composite score.
        """
        try:
            with _db_connect(self.db_path, readonly=True) as db:
                rows = db.execute(
                    """SELECT target_id, AVG(composite_score) as avg_score,
                              COUNT(*) as sample_count,
                              AVG(duration_ms) as avg_duration
                       FROM evaluation_records
                       WHERE target_type = ? AND status = 'pass'
                       GROUP BY target_id
                       HAVING COUNT(*) >= ?
                       ORDER BY avg_score DESC
                       LIMIT 5""",
                    (target_type, min_samples),
                ).fetchall()
            return [
                {
                    "target_id": r["target_id"],
                    "avg_score": round(r["avg_score"], 3),
                    "sample_count": r["sample_count"],
                    "avg_duration_ms": int(r["avg_duration"]),
                }
                for r in rows
            ]
        except Exception as exc:
            _log.error("Failed to get best approach: %s", exc)
            return []

    def stats(self) -> dict[str, Any]:
        """Return aggregate statistics."""
        try:
            with _db_connect(self.db_path, readonly=True) as db:
                total = db.execute(
                    "SELECT COUNT(*) FROM evaluation_records"
                ).fetchone()[0]
                passed = db.execute(
                    "SELECT COUNT(*) FROM evaluation_records WHERE status = 'pass'"
                ).fetchone()[0]
                avg_score = db.execute(
                    "SELECT AVG(composite_score) FROM evaluation_records"
                ).fetchone()[0] or 0.0
                by_type = db.execute(
                    "SELECT target_type, COUNT(*) as cnt FROM evaluation_records GROUP BY target_type"
                ).fetchall()

            return {
                "total_records": total,
                "passed": passed,
                "pass_rate": round(passed / max(total, 1), 3),
                "avg_score": round(avg_score, 3),
                "by_type": {r["target_type"]: r["cnt"] for r in by_type},
                "db_path": self.db_path,
            }
        except Exception as exc:
            _log.error("Failed to get stats: %s", exc)
            return {"error": str(exc)}
