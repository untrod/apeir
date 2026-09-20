# -*- coding: utf-8 -*-
"""Node Manager — manage all connected nodes."""
from __future__ import annotations
from typing import Any

class NodeManager:
    """Unified node management across the network."""
    def __init__(self, workspace: str = ""):
        self._workspace = workspace

    def list_all(self) -> list[dict[str, Any]]:
        nodes = []
        try:
            from nous_runtime.network.registry import NetworkRegistry
            for n in NetworkRegistry(self._workspace).list(limit=200):
                nodes.append(n.to_dict())
        except Exception:
            pass
        try:
            from nous_runtime.connectivity.control_plane.node_registry import NodeRegistry
            for n in NodeRegistry.list_all():
                nodes.append({"id": n.get("node_id", ""), "name": n.get("node_name", ""),
                              "type": "device", "status": "online" if n.get("is_online") else "offline"})
        except Exception:
            pass
        return nodes

    def summary(self) -> dict[str, Any]:
        nodes = self.list_all()
        online = [n for n in nodes if n.get("status") == "online"]
        return {"total": len(nodes), "online": len(online), "nodes": nodes[:20]}
