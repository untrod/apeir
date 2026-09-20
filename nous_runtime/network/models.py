# -*- coding: utf-8 -*-
"""Agent Network data models."""

from __future__ import annotations

import uuid as _uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class NodeStatus(str, Enum):
    ONLINE = "online"
    OFFLINE = "offline"
    BUSY = "busy"
    DEGRADED = "degraded"


class TrustLevel(str, Enum):
    OFFICIAL = "official"
    VERIFIED = "verified"
    COMMUNITY = "community"
    UNKNOWN = "unknown"


@dataclass
class AgentNode:
    """A node in the Agent Network representing one agent instance."""
    id: str = ""
    name: str = ""
    node_type: str = ""        # coding, research, security, robot, hardware
    status: str = NodeStatus.OFFLINE.value
    capabilities: tuple[str, ...] = ()
    trust_level: str = TrustLevel.UNKNOWN.value
    host: str = ""
    port: int = 0
    version: str = "1.0.0"
    metadata: dict[str, Any] = field(default_factory=dict)
    registered_at: str = ""
    last_heartbeat: str = ""

    def __post_init__(self):
        if not self.id:
            self.id = f"anode_{_uuid.uuid4().hex[:12]}"
        if not self.registered_at:
            self.registered_at = _now()

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id, "name": self.name, "node_type": self.node_type,
            "status": self.status, "capabilities": list(self.capabilities),
            "trust_level": self.trust_level, "host": self.host, "port": self.port,
            "version": self.version, "metadata": dict(self.metadata),
            "registered_at": self.registered_at, "last_heartbeat": self.last_heartbeat,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AgentNode":
        d = dict(data)
        d["capabilities"] = tuple(d.pop("capabilities", []))
        known = {"id", "name", "node_type", "status", "capabilities", "trust_level",
                 "host", "port", "version", "metadata", "registered_at", "last_heartbeat"}
        return cls(**{k: v for k, v in d.items() if k in known})


@dataclass
class NetworkTopology:
    """Describes the network topology — hub-spoke or mesh."""
    mode: str = "hub_spoke"    # hub_spoke, mesh, hybrid
    control_plane_host: str = "127.0.0.1"
    control_plane_port: int = 9770
    node_count: int = 0
    online_count: int = 0
    last_updated: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode, "control_plane_host": self.control_plane_host,
            "control_plane_port": self.control_plane_port,
            "node_count": self.node_count, "online_count": self.online_count,
            "last_updated": self.last_updated,
        }
