# -*- coding: utf-8 -*-
"""Agent Network Registry — distributed registry for agent nodes."""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from nous_runtime.network.models import AgentNode, NodeStatus

_log = logging.getLogger("nous.network.registry")


@contextmanager
def _db(db_path: str, readonly: bool = False):
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if readonly:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    else:
        conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    try:
        yield conn
        if not readonly:
            conn.commit()
    finally:
        conn.close()


class NetworkRegistry:
    """SQLite-backed registry of all agent nodes on the network.

    Integrates with existing NodeRegistry in connectivity/ for device nodes.
    """

    def __init__(self, workspace: str = ""):
        if workspace:
            self.db_path = str(Path(workspace) / "network.db")
        else:
            self.db_path = str(Path(os.getcwd()) / ".nous" / "network.db")
        self._lock = threading.RLock()
        self._ensure()

    def _ensure(self):
        with _db(self.db_path) as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS agent_nodes (
                    id TEXT PRIMARY KEY, name TEXT, node_type TEXT,
                    status TEXT DEFAULT 'offline', capabilities TEXT DEFAULT '[]',
                    trust_level TEXT DEFAULT 'unknown', host TEXT, port INTEGER DEFAULT 0,
                    version TEXT, metadata_json TEXT DEFAULT '{}',
                    registered_at TEXT, last_heartbeat TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_anode_type ON agent_nodes(node_type);
                CREATE INDEX IF NOT EXISTS idx_anode_status ON agent_nodes(status);
                CREATE INDEX IF NOT EXISTS idx_anode_trust ON agent_nodes(trust_level);
            """)

    def register(self, node: AgentNode) -> bool:
        try:
            caps = json.dumps(list(node.capabilities))
            meta = json.dumps(node.metadata)
            with self._lock:
                with _db(self.db_path) as db:
                    db.execute(
                        """INSERT OR REPLACE INTO agent_nodes
                           (id,name,node_type,status,capabilities,trust_level,
                            host,port,version,metadata_json,registered_at,last_heartbeat)
                           VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                        (node.id, node.name, node.node_type, node.status, caps,
                         node.trust_level, node.host, node.port, node.version,
                         meta, node.registered_at, node.last_heartbeat),
                    )
            return True
        except Exception as exc:
            _log.error("Failed to register node: %s", exc)
            return False

    def get(self, node_id: str) -> AgentNode | None:
        try:
            with _db(self.db_path, readonly=True) as db:
                row = db.execute("SELECT * FROM agent_nodes WHERE id=?", (node_id,)).fetchone()
            if row is None:
                return None
            return AgentNode(
                id=row["id"], name=row["name"], node_type=row["node_type"],
                status=row["status"], capabilities=tuple(json.loads(row["capabilities"])),
                trust_level=row["trust_level"], host=row["host"] or "", port=row["port"] or 0,
                version=row["version"] or "", metadata=json.loads(row["metadata_json"]),
                registered_at=row["registered_at"] or "", last_heartbeat=row["last_heartbeat"] or "",
            )
        except Exception as exc:
            _log.error("Failed to get node: %s", exc)
            return None

    def list(self, node_type: str = "", status: str = "", limit: int = 50) -> list[AgentNode]:
        try:
            query = "SELECT * FROM agent_nodes WHERE 1=1"
            params: list[Any] = []
            if node_type:
                query += " AND node_type=?"
                params.append(node_type)
            if status:
                query += " AND status=?"
                params.append(status)
            query += " ORDER BY registered_at DESC LIMIT ?"
            params.append(limit)
            with _db(self.db_path, readonly=True) as db:
                rows = db.execute(query, params).fetchall()
            return [
                AgentNode(
                    id=r["id"], name=r["name"], node_type=r["node_type"],
                    status=r["status"], capabilities=tuple(json.loads(r["capabilities"])),
                    trust_level=r["trust_level"], host=r["host"] or "", port=r["port"] or 0,
                ) for r in rows
            ]
        except Exception as exc:
            _log.error("Failed to list: %s", exc)
            return []

    def heartbeat(self, node_id: str) -> bool:
        try:
            from nous_runtime.network.models import _now
            with self._lock:
                with _db(self.db_path) as db:
                    db.execute(
                        "UPDATE agent_nodes SET last_heartbeat=?, status=? WHERE id=?",
                        (_now(), NodeStatus.ONLINE.value, node_id),
                    )
            return True
        except Exception:
            return False

    def set_status(self, node_id: str, status: str) -> bool:
        try:
            with self._lock:
                with _db(self.db_path) as db:
                    db.execute("UPDATE agent_nodes SET status=? WHERE id=?", (status, node_id))
            return True
        except Exception:
            return False

    def remove(self, node_id: str) -> bool:
        try:
            with self._lock:
                with _db(self.db_path) as db:
                    db.execute("DELETE FROM agent_nodes WHERE id=?", (node_id,))
            return True
        except Exception:
            return False
