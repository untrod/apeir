# -*- coding: utf-8 -*-
"""Network Topology — describes agent network structure."""

from __future__ import annotations

from nous_runtime.network.models import NetworkTopology
from nous_runtime.network.registry import NetworkRegistry


def describe_topology(registry: NetworkRegistry | None = None) -> NetworkTopology:
    """Describe the current network topology."""
    reg = registry or NetworkRegistry()
    nodes = reg.list(limit=1000)
    online = [n for n in nodes if n.status == "online"]
    t = NetworkTopology(
        mode="hub_spoke",
        node_count=len(nodes),
        online_count=len(online),
    )
    from datetime import datetime, timezone
    t.last_updated = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return t
