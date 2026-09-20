# -*- coding: utf-8 -*-
"""NodeSession -session state for an authenticated node connection."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from nous_runtime.compat import ids as _ids
from nous_runtime.compat import time as _time


@dataclass(frozen=True)
class NodeSession:
    """Represents an active, authenticated session for a connected node."""

    session_id: str
    node_id: str
    protocol_version: str
    created_at: str
    last_heartbeat: str = ""
    status: str = "active"  # active | expired | terminated
    resumed_from: str = ""  # previous session_id if resumed
    sequence_number: int = 0
    remote_address: str = ""  # informational only

    @classmethod
    def create(
        cls,
        node_id: str,
        protocol_version: str,
        resumed_from: str = "",
        remote_address: str = "",
    ) -> NodeSession:
        return cls(
            session_id=_ids.make_id("ses"),
            node_id=node_id,
            protocol_version=protocol_version,
            created_at=_time.utc_now(),
            last_heartbeat=_time.utc_now(),
            resumed_from=resumed_from,
            remote_address=remote_address,
        )

    def with_heartbeat(self) -> NodeSession:
        """Return a new session with updated heartbeat time."""
        return NodeSession(
            session_id=self.session_id,
            node_id=self.node_id,
            protocol_version=self.protocol_version,
            created_at=self.created_at,
            last_heartbeat=_time.utc_now(),
            status=self.status,
            resumed_from=self.resumed_from,
            sequence_number=self.sequence_number,
            remote_address=self.remote_address,
        )

    def with_status(self, status: str) -> NodeSession:
        return NodeSession(
            session_id=self.session_id,
            node_id=self.node_id,
            protocol_version=self.protocol_version,
            created_at=self.created_at,
            last_heartbeat=self.last_heartbeat,
            status=status,
            resumed_from=self.resumed_from,
            sequence_number=self.sequence_number,
            remote_address=self.remote_address,
        )

    def with_incremented_sequence(self) -> NodeSession:
        return NodeSession(
            session_id=self.session_id,
            node_id=self.node_id,
            protocol_version=self.protocol_version,
            created_at=self.created_at,
            last_heartbeat=self.last_heartbeat,
            status=self.status,
            resumed_from=self.resumed_from,
            sequence_number=self.sequence_number + 1,
            remote_address=self.remote_address,
        )

    def is_expired(self, liveness_timeout_sec: float = 45.0) -> bool:
        """Check if session has expired due to no heartbeat."""
        last = _time.parse_iso(self.last_heartbeat)
        now = _time.utc_now_epoch()
        return (now - last) > liveness_timeout_sec

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "node_id": self.node_id,
            "protocol_version": self.protocol_version,
            "created_at": self.created_at,
            "last_heartbeat": self.last_heartbeat,
            "status": self.status,
            "resumed_from": self.resumed_from,
            "sequence_number": self.sequence_number,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> NodeSession:
        return cls(
            session_id=data["session_id"],
            node_id=data["node_id"],
            protocol_version=data.get("protocol_version", "1.0"),
            created_at=data.get("created_at", ""),
            last_heartbeat=data.get("last_heartbeat", ""),
            status=data.get("status", "active"),
            resumed_from=data.get("resumed_from", ""),
            sequence_number=data.get("sequence_number", 0),
            remote_address=data.get("remote_address", ""),
        )

