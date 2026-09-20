# -*- coding: utf-8 -*-
"""
Node object model for Nous Runtime.

Implements §5 (Node Architecture), §5.3 (Node State Model),
and §5.4 (Fault & Offline Recovery) of the master plan.

Every node is a NousObject with:
- Cryptographic identity
- Connectivity state machine
- Capability and resource reporting
- Heartbeat and lease management
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from nous_runtime.kernel.object_model import (
    NousObject,
)
from nous_runtime.kernel.identity import (
    CapabilityGrant,
    NodeConnectivity,
    NodeIdentity,
    NodeRole,
    NODE_CONNECTIVITY_TRANSITIONS,
)
from nous_runtime.kernel.state_machine import (
    Checkpoint,
    Lease,
    StateMachine,
    TransitionRecord,
)


# Node resource report

@dataclass
class NodeResources:
    """Hardware and software resource snapshot (§5.3)."""

    os_name: str = ""                    # e.g., "Windows 10 Pro", "Ubuntu 22.04"
    cpu_cores: int = 0
    cpu_model: str = ""
    gpu_model: str = ""                  # e.g., "RTX 3070 Laptop"
    gpu_memory_mb: int = 0
    ram_total_mb: int = 0
    ram_available_mb: int = 0
    disk_total_mb: int = 0
    disk_available_mb: int = 0
    network_interfaces: list[str] = field(default_factory=list)
    reported_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


@dataclass
class NodeCapabilities:
    """What this node can do (§5.3 capability report)."""

    workspaces: list[str] = field(default_factory=list)     # Project workspaces
    local_models: list[str] = field(default_factory=list)   # Model IDs available locally
    inference_engines: list[str] = field(default_factory=list)  # Ollama, llama.cpp, vLLM
    tools: list[str] = field(default_factory=list)          # Available tool IDs
    authorized_capabilities: list[str] = field(default_factory=list)  # Granted capability IDs
    python_version: str = ""
    git_available: bool = False
    docker_available: bool = False


# Node object

@dataclass
class Node(NousObject):
    """Represents any node in the Nous mesh network.

    A node can be a Primary, Worker, Edge, or Device node (§5.1).
    Its connectivity state follows the 5-state model (§5.4).
    """

    kind: str = field(default="Node", init=False)

    # Identity
    identity: NodeIdentity = field(default_factory=NodeIdentity)

    # Connectivity state machine
    connectivity_sm: StateMachine[NodeConnectivity] = field(
        default_factory=lambda: StateMachine(
            transitions=NODE_CONNECTIVITY_TRANSITIONS,
            current=NodeConnectivity.OFFLINE,
        )
    )

    # Resource and capability snapshots
    resources: NodeResources = field(default_factory=NodeResources)
    capabilities: NodeCapabilities = field(default_factory=NodeCapabilities)

    # Capability grants assigned to this node
    grants: list[CapabilityGrant] = field(default_factory=list)

    # Active leases held by this node
    leases: list[Lease] = field(default_factory=list)

    # Checkpoints (for primary node task recovery)
    checkpoints: list[Checkpoint] = field(default_factory=list)

    # Connectivity metadata
    last_heartbeat: str = ""
    heartbeat_interval_ms: int = 30000     # Default 30s
    address: str = ""                      # IP:port or hostname
    wireguard_pubkey: str = ""             # WireGuard public key for secure transport

    # Properties

    @property
    def connectivity(self) -> NodeConnectivity:
        return self.connectivity_sm.current

    @property
    def is_online(self) -> bool:
        return self.connectivity in (
            NodeConnectivity.ONLINE,
            NodeConnectivity.DEGRADED,
        )

    @property
    def is_revoked(self) -> bool:
        return self.connectivity == NodeConnectivity.REVOKED

    @property
    def role(self) -> NodeRole:
        return self.identity.role

    # Connectivity transitions

    def mark_online(self, reason: str = "", trace_id: str = "") -> TransitionRecord:
        return self.connectivity_sm.transition(
            NodeConnectivity.ONLINE, reason=reason, trace_id=trace_id
        )

    def mark_degraded(self, reason: str = "", trace_id: str = "") -> TransitionRecord:
        return self.connectivity_sm.transition(
            NodeConnectivity.DEGRADED, reason=reason, trace_id=trace_id
        )

    def mark_offline(self, reason: str = "", trace_id: str = "") -> TransitionRecord:
        return self.connectivity_sm.transition(
            NodeConnectivity.OFFLINE, reason=reason, trace_id=trace_id
        )

    def mark_reconnecting(self, reason: str = "", trace_id: str = "") -> TransitionRecord:
        return self.connectivity_sm.transition(
            NodeConnectivity.RECONNECTING, reason=reason, trace_id=trace_id
        )

    def mark_revoked(self, reason: str = "", trace_id: str = "") -> TransitionRecord:
        record = self.connectivity_sm.transition(
            NodeConnectivity.REVOKED, reason=reason, trace_id=trace_id
        )
        self.identity.revoke()
        return record

    # Heartbeat

    def record_heartbeat(self) -> None:
        """Record a heartbeat, updating last seen time."""
        self.last_heartbeat = datetime.now(timezone.utc).isoformat()

    @property
    def heartbeat_missed_ms(self) -> float:
        """Milliseconds since last heartbeat (∞ if never received)."""
        if not self.last_heartbeat:
            return float("inf")
        last = datetime.fromisoformat(self.last_heartbeat.replace("Z", "+00:00"))
        now = datetime.now(timezone.utc)
        return (now - last).total_seconds() * 1000

    @property
    def heartbeat_timed_out(self) -> bool:
        return self.heartbeat_missed_ms > (self.heartbeat_interval_ms * 3)

    # Active grants

    @property
    def active_grants(self) -> list[CapabilityGrant]:
        return [g for g in self.grants if g.is_active and not g.is_exhausted]

    # Serialization

    def to_dict(self) -> dict[str, Any]:
        base = super().to_dict()
        base["node"] = {
            "identity": {
                "node_id": self.identity.node_id,
                "role": self.identity.role.value,
                "display_name": self.identity.display_name,
            },
            "connectivity": self.connectivity.value,
            "last_heartbeat": self.last_heartbeat,
            "address": self.address,
            "resources": {
                "os_name": self.resources.os_name,
                "cpu_cores": self.resources.cpu_cores,
                "gpu_model": self.resources.gpu_model,
                "gpu_memory_mb": self.resources.gpu_memory_mb,
                "ram_available_mb": self.resources.ram_available_mb,
            },
            "capabilities": {
                "local_models": self.capabilities.local_models,
                "inference_engines": self.capabilities.inference_engines,
                "tools": self.capabilities.tools,
                "authorized_capabilities": self.capabilities.authorized_capabilities,
            },
            "connectivity_history": [
                {
                    "from": h.from_state,
                    "to": h.to_state,
                    "at": h.timestamp,
                    "reason": h.reason,
                }
                for h in self.connectivity_sm.history[-10:]  # Last 10 transitions
            ],
        }
        return base
