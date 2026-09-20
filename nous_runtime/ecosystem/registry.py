# -*- coding: utf-8 -*-
"""Capability Registry — store and query installed capabilities."""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from nous_runtime.ecosystem.manifest import CapabilityManifest

_log = logging.getLogger("nous.ecosystem.registry")


@contextmanager
def _db(db_path: str, readonly: bool = False):
    p = Path(db_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(f"file:{p}?mode=ro" if readonly else str(p), uri=readonly)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    try:
        yield conn
        if not readonly:
            conn.commit()
    finally:
        conn.close()


class CapabilityRegistry:
    """SQLite registry of installed capabilities."""

    def __init__(self, workspace: str = ""):
        self.db_path = str(Path(workspace or os.getcwd()) / ".nous" / "capabilities.db")
        self._lock = threading.RLock()
        self._ensure()

    def _ensure(self):
        with _db(self.db_path) as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS capabilities (
                    name TEXT PRIMARY KEY, version TEXT, description TEXT,
                    author TEXT, category TEXT, risk_level TEXT, trust TEXT,
                    entry_point TEXT, signature TEXT,
                    manifest_json TEXT NOT NULL DEFAULT '{}',
                    installed_at TEXT NOT NULL DEFAULT ''
                );
                CREATE INDEX IF NOT EXISTS idx_cap_category ON capabilities(category);
            """)

    def install(self, manifest: CapabilityManifest) -> bool:
        try:
            manifest_json = json.dumps(manifest.to_dict(), ensure_ascii=False)
            with self._lock:
                with _db(self.db_path) as db:
                    db.execute(
                        """INSERT OR REPLACE INTO capabilities
                           (name,version,description,author,category,risk_level,
                            trust,entry_point,signature,manifest_json,installed_at)
                           VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                        (manifest.name, manifest.version, manifest.description,
                         manifest.author, manifest.category, manifest.risk_level,
                         manifest.trust, manifest.entry_point, manifest.signature,
                         manifest_json, manifest.created_at),
                    )
            _log.info("Installed capability: %s v%s", manifest.name, manifest.version)
            return True
        except Exception as exc:
            _log.error("Failed to install: %s", exc)
            return False

    def get(self, name: str) -> CapabilityManifest | None:
        try:
            with _db(self.db_path, readonly=True) as db:
                row = db.execute("SELECT manifest_json FROM capabilities WHERE name=?", (name,)).fetchone()
            return CapabilityManifest.from_dict(json.loads(row["manifest_json"])) if row else None
        except Exception:
            return None

    def list(self, category: str = "", limit: int = 100) -> list[CapabilityManifest]:
        try:
            q = "SELECT manifest_json FROM capabilities"
            params: list[Any] = []
            if category:
                q += " WHERE category=?"
                params.append(category)
            q += " ORDER BY installed_at DESC LIMIT ?"
            params.append(limit)
            with _db(self.db_path, readonly=True) as db:
                rows = db.execute(q, params).fetchall()
            return [CapabilityManifest.from_dict(json.loads(r["manifest_json"])) for r in rows]
        except Exception:
            return []

    def remove(self, name: str) -> bool:
        try:
            with self._lock:
                with _db(self.db_path) as db:
                    db.execute("DELETE FROM capabilities WHERE name=?", (name,))
            return True
        except Exception:
            return False

    def stats(self) -> dict[str, Any]:
        try:
            with _db(self.db_path, readonly=True) as db:
                total = db.execute("SELECT COUNT(*) FROM capabilities").fetchone()[0]
                cats = db.execute("SELECT category, COUNT(*) as n FROM capabilities GROUP BY category").fetchall()
            return {"total": total, "by_category": {r["category"]: r["n"] for r in cats}}
        except Exception:
            return {"total": 0, "by_category": {}}
