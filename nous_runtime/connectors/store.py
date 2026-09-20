"""Persistent connector registration, health, cursor, and revocation state."""

from __future__ import annotations

from contextlib import contextmanager

import json
import sqlite3
from pathlib import Path
from typing import Any

from nous_runtime.connectors.models import ConnectorManifest


class ConnectorStore:
    def __init__(self, root: str | Path = "."):
        self.path = Path(root).resolve() / ".nous" / "connectors.db"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._db() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS connectors (
                    connector_id TEXT PRIMARY KEY,
                    manifest_json TEXT NOT NULL,
                    credential_ref TEXT NOT NULL DEFAULT '',
                    revoked INTEGER NOT NULL DEFAULT 0,
                    health_json TEXT NOT NULL DEFAULT '{}',
                    cursor TEXT NOT NULL DEFAULT ''
                );
                CREATE TABLE IF NOT EXISTS connector_idempotency (
                    connector_id TEXT NOT NULL,
                    idempotency_key TEXT NOT NULL,
                    result_json TEXT NOT NULL,
                    PRIMARY KEY(connector_id, idempotency_key)
                );
                """
            )

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

    def register(self, manifest: ConnectorManifest, *, credential_ref: str = "") -> None:
        errors = manifest.validate()
        if errors:
            raise ValueError("; ".join(errors))
        if credential_ref and not credential_ref.startswith(("env:", "vault:", "test:")):
            raise ValueError("credential_ref must reference a credential provider")
        with self._db() as connection:
            connection.execute(
                """INSERT INTO connectors (connector_id, manifest_json, credential_ref, revoked)
                VALUES (?, ?, ?, 0)
                ON CONFLICT(connector_id) DO UPDATE SET manifest_json=excluded.manifest_json,
                credential_ref=excluded.credential_ref, revoked=0""",
                (manifest.connector_id, json.dumps(manifest.to_dict(), sort_keys=True), credential_ref),
            )

    def get(self, connector_id: str) -> tuple[ConnectorManifest, str, bool] | None:
        with self._db() as connection:
            row = connection.execute("SELECT * FROM connectors WHERE connector_id = ?", (connector_id,)).fetchone()
        if row is None:
            return None
        return ConnectorManifest.from_dict(json.loads(row["manifest_json"])), str(row["credential_ref"]), bool(row["revoked"])

    def list(self) -> list[dict[str, Any]]:
        with self._db() as connection:
            rows = connection.execute("SELECT connector_id, manifest_json, revoked, health_json, cursor FROM connectors ORDER BY connector_id").fetchall()
        return [{"connector_id": row["connector_id"], "manifest": json.loads(row["manifest_json"]), "revoked": bool(row["revoked"]), "health": json.loads(row["health_json"]), "cursor": row["cursor"]} for row in rows]

    def set_enabled(self, connector_id: str, enabled: bool) -> bool:
        """Enable or disable an existing Connector registration."""
        with self._db() as connection:
            cursor = connection.execute(
                "UPDATE connectors SET revoked = ? WHERE connector_id = ?",
                (0 if enabled else 1, connector_id),
            )
        return cursor.rowcount == 1
    def revoke(self, connector_id: str) -> bool:
        with self._db() as connection:
            cursor = connection.execute("UPDATE connectors SET revoked = 1 WHERE connector_id = ?", (connector_id,))
        return cursor.rowcount == 1

    def set_cursor(self, connector_id: str, cursor: str) -> None:
        with self._db() as connection:
            connection.execute("UPDATE connectors SET cursor = ? WHERE connector_id = ?", (cursor, connector_id))

    def cursor(self, connector_id: str) -> str:
        with self._db() as connection:
            row = connection.execute("SELECT cursor FROM connectors WHERE connector_id = ?", (connector_id,)).fetchone()
        return str(row[0]) if row else ""

    def set_health(self, connector_id: str, health: dict[str, Any]) -> None:
        with self._db() as connection:
            connection.execute("UPDATE connectors SET health_json = ? WHERE connector_id = ?", (json.dumps(health, sort_keys=True), connector_id))

    def get_idempotent(self, connector_id: str, key: str) -> dict[str, Any] | None:
        if not key:
            return None
        with self._db() as connection:
            row = connection.execute("SELECT result_json FROM connector_idempotency WHERE connector_id = ? AND idempotency_key = ?", (connector_id, key)).fetchone()
        return json.loads(row[0]) if row else None

    def save_idempotent(self, connector_id: str, key: str, result: dict[str, Any]) -> None:
        if not key:
            return
        with self._db() as connection:
            connection.execute("INSERT OR IGNORE INTO connector_idempotency VALUES (?, ?, ?)", (connector_id, key, json.dumps(result, sort_keys=True)))