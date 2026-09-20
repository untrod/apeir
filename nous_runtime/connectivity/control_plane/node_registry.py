# -*- coding: utf-8 -*-
"""
NodeRegistry -manages registered nodes, their identities, and credential state.
Reuses nous_core/devices/ table structure with extended node-specific columns.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from nous_runtime.compat import time as _time
from nous_runtime.compat.db import connect as _connect, run_migrations as _run_migrations

from ..protocol.identity import NodeIdentity

_log = logging.getLogger("nous.control_plane.node_registry")


class NodeRegistry:
    """Manages Nous Node registration, identity, and credential state."""

    @staticmethod
    def _ensure_tables() -> None:
        """Ensure node-specific tables exist (idempotent)."""
        _run_migrations()
        try:
            with _connect() as db:
                db.executescript("""
                    CREATE TABLE IF NOT EXISTS connectivity_nodes (
                        node_id TEXT PRIMARY KEY,
                        node_name TEXT NOT NULL,
                        node_role TEXT NOT NULL DEFAULT 'personal_node',
                        platform_os TEXT NOT NULL DEFAULT '',
                        platform_os_version TEXT NOT NULL DEFAULT '',
                        platform_arch TEXT NOT NULL DEFAULT '',
                        platform_hostname TEXT NOT NULL DEFAULT '',
                        public_key TEXT NOT NULL DEFAULT '',
                        capabilities TEXT NOT NULL DEFAULT '[]',
                        runtime_version TEXT NOT NULL DEFAULT '',
                        trust_zone TEXT NOT NULL DEFAULT 'personal',
                        credential_id TEXT NOT NULL DEFAULT '',
                        credential_status TEXT NOT NULL DEFAULT 'active',
                        credential_issued_at TEXT NOT NULL DEFAULT '',
                        credential_expires_at TEXT NOT NULL DEFAULT '',
                        is_online INTEGER NOT NULL DEFAULT 0,
                        last_seen TEXT NOT NULL DEFAULT '',
                        created_at TEXT NOT NULL DEFAULT '',
                        updated_at TEXT NOT NULL DEFAULT ''
                    );
                    CREATE TABLE IF NOT EXISTS connectivity_pairing_codes (
                        code_hash TEXT PRIMARY KEY,
                        created_at TEXT NOT NULL DEFAULT '',
                        expires_at TEXT NOT NULL DEFAULT '',
                        created_by TEXT NOT NULL DEFAULT '',
                        attempts INTEGER NOT NULL DEFAULT 0,
                        consumed INTEGER NOT NULL DEFAULT 0
                    );
                """)
        except Exception as e:
            _log.warning("Failed to create connectivity tables: %s", e)

    @staticmethod
    def register(node_identity: NodeIdentity, credential_id: str,
                 credential_expires_at: str = "") -> bool:
        """Register a new node. Returns True on success."""
        NodeRegistry._ensure_tables()
        now = _time.utc_now()
        try:
            with _connect() as db:
                db.execute(
                    """INSERT OR REPLACE INTO connectivity_nodes
                       (node_id, node_name, node_role, platform_os, platform_os_version,
                        platform_arch, platform_hostname, public_key, capabilities,
                        runtime_version, credential_id, credential_status,
                        credential_issued_at, credential_expires_at, created_at, updated_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'active', ?, ?, ?, ?)""",
                    (
                        node_identity.node_id, node_identity.node_name,
                        node_identity.node_role, node_identity.platform_os,
                        node_identity.platform_os_version, node_identity.platform_arch,
                        node_identity.platform_hostname, node_identity.public_key,
                        json.dumps(list(node_identity.capabilities)),
                        node_identity.runtime_version, credential_id,
                        now, credential_expires_at, now, now,
                    ),
                )
            _log.info("Node registered: %s (%s)", node_identity.node_id, node_identity.node_name)
            return True
        except Exception as e:
            _log.error("Failed to register node: %s", e)
            return False

    @staticmethod
    def get(node_id: str) -> dict[str, Any] | None:
        """Get a node by ID."""
        NodeRegistry._ensure_tables()
        try:
            with _connect(readonly=True) as db:
                row = db.execute(
                    "SELECT * FROM connectivity_nodes WHERE node_id = ?", (node_id,)
                ).fetchone()
                if row:
                    d = dict(row)
                    d["capabilities"] = json.loads(d.get("capabilities", "[]"))
                    return d
        except Exception as e:
            _log.warning("Failed to get node %s: %s", node_id, e)
        return None

    @staticmethod
    def list_all() -> list[dict[str, Any]]:
        """List all registered nodes."""
        NodeRegistry._ensure_tables()
        try:
            with _connect(readonly=True) as db:
                rows = db.execute(
                    "SELECT * FROM connectivity_nodes ORDER BY created_at DESC"
                ).fetchall()
                result = []
                for row in rows:
                    d = dict(row)
                    d["capabilities"] = json.loads(d.get("capabilities", "[]"))
                    result.append(d)
                return result
        except Exception as e:
            _log.warning("Failed to list nodes: %s", e)
            return []

    @staticmethod
    def set_online(node_id: str, online: bool) -> None:
        """Update node online status."""
        try:
            with _connect() as db:
                db.execute(
                    "UPDATE connectivity_nodes SET is_online = ?, last_seen = ?, updated_at = ? WHERE node_id = ?",
                    (1 if online else 0, _time.utc_now(), _time.utc_now(), node_id),
                )
        except Exception as e:
            _log.warning("Failed to update node status: %s", e)

    @staticmethod
    def revoke(node_id: str) -> bool:
        """Revoke a node's credential. Returns True on success."""
        try:
            with _connect() as db:
                db.execute(
                    "UPDATE connectivity_nodes SET credential_status = 'revoked', updated_at = ? WHERE node_id = ?",
                    (_time.utc_now(), node_id),
                )
            _log.info("Node revoked: %s", node_id)
            return True
        except Exception as e:
            _log.error("Failed to revoke node: %s", e)
            return False

    @staticmethod
    def is_revoked(node_id: str) -> bool:
        """Check if a node is revoked."""
        node = NodeRegistry.get(node_id)
        if not node:
            return False
        return node.get("credential_status") == "revoked"

    @staticmethod
    def has_capability(node_id: str, capability_id: str) -> bool:
        """Check if a node has a specific capability."""
        node = NodeRegistry.get(node_id)
        if not node:
            return False
        return capability_id in node.get("capabilities", [])

