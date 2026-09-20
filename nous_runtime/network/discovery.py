# -*- coding: utf-8 -*-
"""Agent Discovery — DNS-like service for finding agents by capability."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from nous_runtime.network.models import AgentNode, TrustLevel
from nous_runtime.network.registry import NetworkRegistry

_log = logging.getLogger("nous.network.discovery")


@dataclass
class DiscoveryResult:
    node: AgentNode
    match_score: float = 0.0
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "node": self.node.to_dict(),
            "match_score": self.match_score,
            "reason": self.reason,
        }




class AgentDiscovery:
    """Finds agents matching capability or role requirements.

    Usage::

        discovery = AgentDiscovery(registry)
        results = discovery.find(capability="python")
        best = results[0]
    """

    def __init__(self, registry: NetworkRegistry | None = None):
        self._registry = registry or NetworkRegistry()

    def find(
        self,
        capability: str = "",
        node_type: str = "",
        min_trust: str = TrustLevel.COMMUNITY.value,
        limit: int = 10,
    ) -> list[DiscoveryResult]:
        """Find agents matching criteria. Returns scored results."""
        # Get all online nodes
        online = self._registry.list(status="online", limit=200)

        # If online is empty, fall back to all registered
        if not online:
            online = self._registry.list(limit=200)

        results: list[DiscoveryResult] = []

        for node in online:
            score = 0.0
            reasons: list[str] = []

            # Capability match
            if capability and capability in node.capabilities:
                score += 0.5
                reasons.append(f"has capability '{capability}'")
            elif capability:
                continue  # Skip nodes without required capability

            # Type match
            if node_type and node.node_type == node_type:
                score += 0.2
                reasons.append(f"type match: {node_type}")

            # Trust bonus
            trust_rank = {"official": 3, "verified": 2, "community": 1, "unknown": 0}
            min_rank = trust_rank.get(min_trust, 1)
            node_rank = trust_rank.get(node.trust_level, 0)
            if node_rank >= min_rank:
                score += 0.2 * (node_rank / 3)
                reasons.append(f"trust: {node.trust_level}")

            # Online bonus
            if node.status == "online":
                score += 0.1
                reasons.append("online")

            if score > 0:
                results.append(DiscoveryResult(
                    node=node,
                    match_score=min(1.0, score),
                    reason="; ".join(reasons),
                ))

        results.sort(key=lambda r: r.match_score, reverse=True)
        return results[:limit]

    def find_by_capability(self, capability: str, limit: int = 10) -> list[DiscoveryResult]:
        """Find agents with a specific capability."""
        return self.find(capability=capability, limit=limit)

    def find_by_type(self, node_type: str, limit: int = 10) -> list[DiscoveryResult]:
        """Find agents of a specific type."""
        return self.find(node_type=node_type, limit=limit)

    def list_all_online(self) -> list[AgentNode]:
        return self._registry.list(status="online", limit=100)

    def network_summary(self) -> dict[str, Any]:
        """Summary of the agent network."""
        all_nodes = self._registry.list(limit=1000)
        online = [n for n in all_nodes if n.status == "online"]
        by_type: dict[str, int] = {}
        for n in all_nodes:
            by_type[n.node_type] = by_type.get(n.node_type, 0) + 1
        return {
            "total_nodes": len(all_nodes),
            "online_nodes": len(online),
            "by_type": by_type,
            "by_trust": {
                "official": sum(1 for n in all_nodes if n.trust_level == "official"),
                "verified": sum(1 for n in all_nodes if n.trust_level == "verified"),
                "community": sum(1 for n in all_nodes if n.trust_level == "community"),
                "unknown": sum(1 for n in all_nodes if n.trust_level == "unknown"),
            },
        }
