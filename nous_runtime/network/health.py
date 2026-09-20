# -*- coding: utf-8 -*-
"""Network Health — monitoring and health checks for agent nodes."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from nous_runtime.network.models import NodeStatus
from nous_runtime.network.registry import NetworkRegistry

_log = logging.getLogger("nous.network.health")


@dataclass
class HealthReport:
    node_id: str = ""
    healthy: bool = False
    status: str = NodeStatus.OFFLINE.value
    last_heartbeat: str = ""
    latency_ms: int = 0
    capabilities_healthy: bool = False
    message: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "node_id": self.node_id, "healthy": self.healthy,
            "status": self.status, "last_heartbeat": self.last_heartbeat,
            "latency_ms": self.latency_ms, "capabilities_healthy": self.capabilities_healthy,
            "message": self.message,
        }


class NetworkHealth:
    """Monitors agent node health and detects issues."""

    def __init__(self, registry: NetworkRegistry | None = None):
        self._registry = registry or NetworkRegistry()

    def check_node(self, node_id: str) -> HealthReport:
        """Health check for a single node."""
        node = self._registry.get(node_id)
        if node is None:
            return HealthReport(node_id=node_id, message="Node not found")

        healthy = node.status == NodeStatus.ONLINE.value

        # Check heartbeat staleness
        stale = False
        if node.last_heartbeat:
            try:
                last = datetime.fromisoformat(node.last_heartbeat.replace("Z", "+00:00"))
                stale = (datetime.now(timezone.utc) - last).total_seconds() > 60
            except Exception:
                stale = True

        if stale:
            self._registry.set_status(node_id, NodeStatus.OFFLINE.value)
            healthy = False

        return HealthReport(
            node_id=node_id, healthy=healthy,
            status=node.status, last_heartbeat=node.last_heartbeat or "never",
            capabilities_healthy=len(node.capabilities) > 0,
            message="OK" if healthy else "Node is offline or stale",
        )

    def check_all(self) -> list[HealthReport]:
        """Check health of all registered nodes."""
        nodes = self._registry.list(limit=500)
        return [self.check_node(n.id) for n in nodes]

    def network_health(self) -> dict[str, Any]:
        """Aggregated network health."""
        reports = self.check_all()
        total = len(reports)
        healthy_count = sum(1 for r in reports if r.healthy)
        return {
            "total_nodes": total,
            "healthy": healthy_count,
            "unhealthy": total - healthy_count,
            "health_rate": round(healthy_count / max(total, 1), 3),
            "reports": [r.to_dict() for r in reports[:20]],
        }
