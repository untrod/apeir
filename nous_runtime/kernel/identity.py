# -*- coding: utf-8 -*-
"""
Node and User identity model for Nous Runtime.

Every node (Primary, Worker, Edge, Device) and every user possesses
a unique cryptographic identity. This module defines the identity
objects, key references, and capability grants.

Design principles (from master plan §18.1):
- Every node has an independent key, Node ID, device certificate
- Capability grants are explicit and revocable
- API keys never enter model context or logs
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from nous_runtime.compat.ids import make_id


# Node Role

class NodeRole(str, Enum):
    """Node role per master plan §5.1."""
    PRIMARY = "primary"       # Long-lived control node
    WORKER = "worker"         # Execution node (GPU, workspace)
    EDGE = "edge"             # Phone, Jetson, camera, sensors
    DEVICE = "device"         # STM32, ESP32, PLC, robot


# Node connectivity state

class NodeConnectivity(str, Enum):
    """Node connectivity states per master plan §5.4."""
    ONLINE = "online"
    DEGRADED = "degraded"
    OFFLINE = "offline"
    RECONNECTING = "reconnecting"
    REVOKED = "revoked"


# Valid transitions for node connectivity
NODE_CONNECTIVITY_TRANSITIONS: dict[NodeConnectivity, frozenset[NodeConnectivity]] = {
    NodeConnectivity.ONLINE: frozenset({
        NodeConnectivity.DEGRADED,
        NodeConnectivity.OFFLINE,
        NodeConnectivity.REVOKED,
    }),
    NodeConnectivity.DEGRADED: frozenset({
        NodeConnectivity.ONLINE,
        NodeConnectivity.OFFLINE,
        NodeConnectivity.REVOKED,
    }),
    NodeConnectivity.OFFLINE: frozenset({
        NodeConnectivity.ONLINE,
        NodeConnectivity.RECONNECTING,
        NodeConnectivity.REVOKED,
    }),
    NodeConnectivity.RECONNECTING: frozenset({
        NodeConnectivity.ONLINE,
        NodeConnectivity.DEGRADED,
        NodeConnectivity.OFFLINE,
        NodeConnectivity.REVOKED,
    }),
    NodeConnectivity.REVOKED: frozenset(),  # Terminal state
}


# Identity

@dataclass
class NodeIdentity:
    """Cryptographic identity for a single node.

    Each node possesses exactly one identity. The identity persists
    across restarts; connectivity state is ephemeral.
    """

    node_id: str = field(default_factory=lambda: make_id(prefix="node"))
    role: NodeRole = NodeRole.WORKER
    display_name: str = ""
    public_key_fingerprint: str = ""     # SHA-256 of public key
    certificate_fingerprint: str = ""    # Device certificate hash
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    revoked_at: str | None = None

    @property
    def is_revoked(self) -> bool:
        return self.revoked_at is not None

    def revoke(self) -> None:
        self.revoked_at = datetime.now(timezone.utc).isoformat()


@dataclass
class UserIdentity:
    """Human user identity.

    A user may own multiple nodes. The user identity is the root of trust
    for capability grants and approval decisions.
    """

    user_id: str = field(default_factory=lambda: make_id(prefix="user"))
    display_name: str = ""
    primary_node_id: str = ""            # Preferred primary node
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


# Capability Grant

class GrantScope(str, Enum):
    """Scope of a capability grant."""
    NODE = "node"             # Grant to a specific node
    USER = "user"             # Grant to a user (all their nodes)
    SESSION = "session"       # Grant for the duration of a session
    TASK = "task"             # Grant for a specific task only


@dataclass
class CapabilityGrant:
    """Explicit grant of a capability to a node, user, session, or task.

    Per master plan §9.2, each capability has a risk level and required
    permissions. Grants are always explicit and bounded in time.
    """

    grant_id: str = field(default_factory=lambda: make_id(prefix="grant"))
    capability_id: str = ""
    scope: GrantScope = GrantScope.NODE
    target_id: str = ""                  # node_id, user_id, session_id, or task_id
    risk_level: str = "LOW"              # READ_ONLY | LOW | MEDIUM | HIGH | CRITICAL
    granted_by: str = ""                 # user_id who granted
    granted_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    expires_at: str | None = None
    revoked_at: str | None = None
    max_invocations: int = 0             # 0 = unlimited
    invocation_count: int = 0

    @property
    def is_active(self) -> bool:
        if self.revoked_at is not None:
            return False
        if self.expires_at is not None:
            return datetime.now(timezone.utc).isoformat() < self.expires_at
        return True

    @property
    def is_exhausted(self) -> bool:
        if self.max_invocations <= 0:
            return False
        return self.invocation_count >= self.max_invocations


# Secret Vault reference

@dataclass
class SecretRef:
    """Reference to a secret stored in the Secret Vault.

    Per master plan §18.3, secrets are never:
    - Written into normal config
    - Written into logs
    - Sent to irrelevant nodes
    - Entered into model context

    Only references (vault path + key ID) are passed around.
    """

    vault_path: str                      # e.g., "providers/openai/api_key"
    key_id: str = ""                     # Encryption key identifier
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    rotated_at: str | None = None


# Serialization

def node_identity_to_dict(identity: NodeIdentity) -> dict[str, Any]:
    return {
        "node_id": identity.node_id,
        "role": identity.role.value,
        "display_name": identity.display_name,
        "public_key_fingerprint": identity.public_key_fingerprint,
        "certificate_fingerprint": identity.certificate_fingerprint,
        "created_at": identity.created_at,
        "revoked_at": identity.revoked_at,
    }


def grant_to_dict(grant: CapabilityGrant) -> dict[str, Any]:
    return {
        "grant_id": grant.grant_id,
        "capability_id": grant.capability_id,
        "scope": grant.scope.value,
        "target_id": grant.target_id,
        "risk_level": grant.risk_level,
        "granted_by": grant.granted_by,
        "granted_at": grant.granted_at,
        "expires_at": grant.expires_at,
        "revoked_at": grant.revoked_at,
        "max_invocations": grant.max_invocations,
        "invocation_count": grant.invocation_count,
        "is_active": grant.is_active,
    }
