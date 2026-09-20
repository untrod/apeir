"""OpenClaw Node → Nous Node adapter.

Maps OpenClaw node concepts to Nous node primitives,
providing identity, capability, and connectivity management.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

log = logging.getLogger("nous.integrations.openclaw.node")


@dataclass
class NodeMapping:
    """Maps an OpenClaw node to a Nous node."""
    openclaw_node_id: str
    nous_node_id: str | None = None
    node_type: str = "generic"  # gateway, worker, edge, device
    capabilities: list[str] = field(default_factory=list)
    resources: dict[str, float] = field(default_factory=dict)
    address: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


class NodeAdapter:
    """Adapts OpenClaw nodes to Nous node primitives.

    Provides:
      - Node identity registration
      - Capability advertisement
      - Resource availability reporting
      - Connectivity management
    """

    NODE_TYPE_MAP = {
        "gateway": "control_plane",
        "worker": "compute",
        "edge": "edge",
        "device": "device",
    }

    def __init__(self):
        self._nodes: dict[str, NodeMapping] = {}

    def register_node(
        self,
        openclaw_node_id: str,
        node_type: str = "generic",
        capabilities: list[str] | None = None,
        resources: dict[str, float] | None = None,
        address: str | None = None,
    ) -> NodeMapping:
        """Register an OpenClaw node as a Nous node."""
        nous_type = self.NODE_TYPE_MAP.get(node_type, "generic")
        mapping = NodeMapping(
            openclaw_node_id=openclaw_node_id,
            nous_node_id=f"nous-node-{openclaw_node_id}",
            node_type=nous_type,
            capabilities=capabilities or [],
            resources=resources or {},
            address=address,
        )
        self._nodes[openclaw_node_id] = mapping
        log.info(
            "Node %s registered → nous node %s (type=%s)",
            openclaw_node_id, mapping.nous_node_id, nous_type,
        )
        return mapping

    def update_resources(
        self,
        openclaw_node_id: str,
        resources: dict[str, float],
    ) -> None:
        """Update resource availability for a node."""
        mapping = self._nodes.get(openclaw_node_id)
        if mapping:
            mapping.resources.update(resources)

    def get_node(self, openclaw_node_id: str) -> NodeMapping | None:
        return self._nodes.get(openclaw_node_id)

    def find_nodes_by_capability(self, capability: str) -> list[NodeMapping]:
        return [
            m for m in self._nodes.values()
            if capability in m.capabilities
        ]

    @property
    def online_nodes(self) -> int:
        return len(self._nodes)
