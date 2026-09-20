# -*- coding: utf-8 -*-
"""Heartbeat -node liveness signal."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from nous_runtime.compat import time as _time


@dataclass(frozen=True)
class Heartbeat:
    """Heartbeat message sent by Node to signal liveness."""

    node_id: str
    session_id: str
    sequence_number: int
    node_health_status: str = "ok"  # ok | degraded | down
    node_health_load: float = 0.0
    capabilities_healthy: int = 0
    timestamp: str = ""

    def __post_init__(self):
        if not self.timestamp:
            object.__setattr__(self, "timestamp", _time.utc_now())

    @classmethod
    def create(
        cls,
        node_id: str,
        session_id: str,
        sequence_number: int,
        health_status: str = "ok",
        load: float = 0.0,
        capabilities_healthy: int = 0,
    ) -> Heartbeat:
        return cls(
            node_id=node_id,
            session_id=session_id,
            sequence_number=sequence_number,
            node_health_status=health_status,
            node_health_load=load,
            capabilities_healthy=capabilities_healthy,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "node_id": self.node_id,
            "session_id": self.session_id,
            "sequence_number": self.sequence_number,
            "node_health": {
                "status": self.node_health_status,
                "load": self.node_health_load,
                "capabilities_healthy": self.capabilities_healthy,
            },
            "timestamp": self.timestamp,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Heartbeat:
        health = data.get("node_health", {})
        return cls(
            node_id=data.get("node_id", ""),
            session_id=data.get("session_id", ""),
            sequence_number=data.get("sequence_number", 0),
            node_health_status=health.get("status", "ok"),
            node_health_load=health.get("load", 0.0),
            capabilities_healthy=health.get("capabilities_healthy", 0),
            timestamp=data.get("timestamp", ""),
        )

