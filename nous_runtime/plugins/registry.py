"""Local Plugin lifecycle registry."""

from __future__ import annotations

from contextlib import contextmanager

import json
import sqlite3
from pathlib import Path
from typing import Any

from nous_runtime.plugins.models import PluginManifest


class PluginRegistry:
    def __init__(self, root: str | Path = "."):
        self.root = Path(root).resolve()
        self.path = self.root / ".nous" / "plugins.db"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._db() as connection:
            connection.execute("""CREATE TABLE IF NOT EXISTS plugins (
                plugin_id TEXT PRIMARY KEY, manifest_json TEXT NOT NULL,
                package_path TEXT NOT NULL, state TEXT NOT NULL, last_error TEXT NOT NULL DEFAULT ''
            )""")

    @contextmanager
    def _db(self):
        connection = self._connect()
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()
    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA busy_timeout=30000")
        return connection

    def put(self, manifest: PluginManifest, package_path: Path, *, state: str = "disabled") -> None:
        with self._db() as connection:
            connection.execute("""INSERT INTO plugins VALUES (?, ?, ?, ?, '')
                ON CONFLICT(plugin_id) DO UPDATE SET manifest_json=excluded.manifest_json,
                package_path=excluded.package_path, state=excluded.state, last_error=''""",
                (manifest.plugin_id, json.dumps(manifest.to_dict(), sort_keys=True), str(package_path), state),
            )

    def get(self, plugin_id: str) -> dict[str, Any] | None:
        with self._db() as connection:
            row = connection.execute("SELECT * FROM plugins WHERE plugin_id = ?", (plugin_id,)).fetchone()
        if row is None:
            return None
        return {"manifest": PluginManifest.from_dict(json.loads(row["manifest_json"])), "package_path": Path(row["package_path"]), "state": row["state"], "last_error": row["last_error"]}

    def list(self) -> list[dict[str, Any]]:
        with self._db() as connection:
            rows = connection.execute("SELECT * FROM plugins ORDER BY plugin_id").fetchall()
        return [{"plugin_id": row["plugin_id"], "manifest": json.loads(row["manifest_json"]), "package_path": row["package_path"], "state": row["state"], "last_error": row["last_error"]} for row in rows]

    def set_state(self, plugin_id: str, state: str, *, error: str = "") -> bool:
        with self._db() as connection:
            cursor = connection.execute("UPDATE plugins SET state = ?, last_error = ? WHERE plugin_id = ?", (state, error, plugin_id))
        return cursor.rowcount == 1

    def remove(self, plugin_id: str) -> bool:
        with self._db() as connection:
            cursor = connection.execute("DELETE FROM plugins WHERE plugin_id = ?", (plugin_id,))
        return cursor.rowcount == 1