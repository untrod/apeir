# -*- coding: utf-8 -*-
"""SessionRegistry — manages active node sessions."""

from __future__ import annotations

import logging
import threading
from typing import Any


from ..protocol.session import NodeSession

_log = logging.getLogger("nous.control_plane.session_registry")


class SessionRegistry:
    """Thread-safe registry of active node sessions (in-memory + SQLite)."""

    def __init__(self):
        self._lock = threading.Lock()
        self._sessions: dict[str, NodeSession] = {}  # session_id -> session
        self._node_sessions: dict[str, str] = {}  # node_id -> session_id

    def create_session(
        self, node_id: str, protocol_version: str = "1.0",
        resumed_from: str = "", remote_address: str = "",
    ) -> NodeSession:
        """Create a new session for a node. Duplicate node policy: newest wins."""
        with self._lock:
            # Terminate existing session for this node if any
            existing_sid = self._node_sessions.get(node_id)
            if existing_sid and existing_sid in self._sessions:
                old = self._sessions[existing_sid]
                self._sessions[existing_sid] = old.with_status("terminated")
                _log.info("Terminated duplicate session %s for node %s", existing_sid, node_id)

            session = NodeSession.create(
                node_id=node_id,
                protocol_version=protocol_version,
                resumed_from=resumed_from,
                remote_address=remote_address,
            )
            self._sessions[session.session_id] = session
            self._node_sessions[node_id] = session.session_id
            _log.info("Session created: %s for node %s", session.session_id, node_id)
            return session

    def get(self, session_id: str) -> NodeSession | None:
        with self._lock:
            return self._sessions.get(session_id)

    def get_by_node(self, node_id: str) -> NodeSession | None:
        with self._lock:
            sid = self._node_sessions.get(node_id)
            if sid:
                return self._sessions.get(sid)
            return None

    def heartbeat(self, session_id: str) -> NodeSession | None:
        """Update heartbeat timestamp. Returns updated session or None."""
        with self._lock:
            session = self._sessions.get(session_id)
            if not session or session.status != "active":
                return None
            updated = session.with_heartbeat()
            self._sessions[session_id] = updated
            return updated

    def increment_sequence(self, session_id: str) -> NodeSession | None:
        """Increment and return the sequence number for a session."""
        with self._lock:
            session = self._sessions.get(session_id)
            if not session or session.status != "active":
                return None
            updated = session.with_incremented_sequence()
            self._sessions[session_id] = updated
            return updated

    def terminate(self, session_id: str) -> None:
        with self._lock:
            session = self._sessions.get(session_id)
            if session:
                self._sessions[session_id] = session.with_status("terminated")
                if self._node_sessions.get(session.node_id) == session_id:
                    del self._node_sessions[session.node_id]

    def terminate_node(self, node_id: str) -> None:
        with self._lock:
            sid = self._node_sessions.pop(node_id, None)
            if sid and sid in self._sessions:
                self._sessions[sid] = self._sessions[sid].with_status("terminated")

    def expire_stale(self, liveness_timeout_sec: float = 45.0) -> list[str]:
        """Expire stale sessions. Returns list of expired node_ids."""
        expired: list[str] = []
        with self._lock:
            for sid, session in list(self._sessions.items()):
                if session.status == "active" and session.is_expired(liveness_timeout_sec):
                    self._sessions[sid] = session.with_status("expired")
                    if self._node_sessions.get(session.node_id) == sid:
                        del self._node_sessions[session.node_id]
                    expired.append(session.node_id)
        return expired

    def list_active(self) -> list[NodeSession]:
        with self._lock:
            return [s for s in self._sessions.values() if s.status == "active"]

    def list_all(self) -> list[dict[str, Any]]:
        with self._lock:
            return [s.to_dict() for s in self._sessions.values()]
