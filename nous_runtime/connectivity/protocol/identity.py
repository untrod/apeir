# -*- coding: utf-8 -*-
"""
NodeIdentity and NodeManifest -immutable node identity contracts.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from nous_runtime.compat import ids as _ids
from nous_runtime.compat import time as _time

from .serialization import deterministic_hash, redacted_serialization

NODE_ROLES = {"personal_node", "cloud_worker"}
TRUST_ZONES = {"personal", "cloud_trusted", "cloud_untrusted"}


@dataclass(frozen=True)
class NodeIdentity:
    """Cryptographic identity for a Nous Node. Immutable after creation.

    Schema version 1.1: Added platform_abi, runtime_tier, word_size_bits
    for multi-architecture support. These fields default to "unknown"/"full"/64
    for backward compatibility with v1.0 identities.
    """

    node_id: str
    node_name: str
    node_role: str  # personal_node | cloud_worker
    platform_os: str
    platform_os_version: str
    platform_arch: str
    platform_hostname: str
    public_key: str  # Ed25519 public key (hex)
    capabilities: tuple[str, ...] = ()  # capability IDs this node can execute
    runtime_version: str = ""
    created_at: str = ""
    # v1.1 multi-arch fields
    platform_abi: str = ""           # "gnu", "musl", "msvc", "gnueabihf", "gnueabi"
    runtime_tier: str = "full"      # "full" | "lite"
    word_size_bits: int = 64        # 32 | 64

    def __post_init__(self):
        if not self.created_at:
            object.__setattr__(self, "created_at", _time.utc_now())

    @classmethod
    def create(
        cls,
        node_name: str,
        node_role: str,
        platform_os: str,
        platform_os_version: str,
        platform_arch: str,
        platform_hostname: str,
        public_key: str,
        capabilities: list[str] | None = None,
        runtime_version: str = "",
        platform_abi: str = "",
        runtime_tier: str = "full",
        word_size_bits: int = 64,
    ) -> NodeIdentity:
        """Create a new NodeIdentity with generated node_id."""
        return cls(
            node_id=_ids.make_id("node"),
            node_name=node_name,
            node_role=node_role,
            platform_os=platform_os,
            platform_os_version=platform_os_version,
            platform_arch=platform_arch,
            platform_hostname=platform_hostname,
            public_key=public_key,
            capabilities=tuple(capabilities or []),
            runtime_version=runtime_version,
            platform_abi=platform_abi,
            runtime_tier=runtime_tier,
            word_size_bits=word_size_bits,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "node_id": self.node_id,
            "node_name": self.node_name,
            "node_role": self.node_role,
            "platform": {
                "os": self.platform_os,
                "os_version": self.platform_os_version,
                "arch": self.platform_arch,
                "hostname": self.platform_hostname,
                "abi": self.platform_abi,
            },
            "public_key": self.public_key,
            "capabilities": list(self.capabilities),
            "runtime_version": self.runtime_version,
            "created_at": self.created_at,
            "runtime_tier": self.runtime_tier,
            "word_size_bits": self.word_size_bits,
        }

    def to_redacted_dict(self) -> dict[str, Any]:
        return redacted_serialization(self.to_dict())

    def identity_hash(self) -> str:
        """Deterministic hash of identity (for integrity checks)."""
        return deterministic_hash(self.to_dict())

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> NodeIdentity:
        platform = data.get("platform", {})
        return cls(
            node_id=data["node_id"],
            node_name=data["node_name"],
            node_role=data.get("node_role", "personal_node"),
            platform_os=platform.get("os", ""),
            platform_os_version=platform.get("os_version", ""),
            platform_arch=platform.get("arch", ""),
            platform_hostname=platform.get("hostname", ""),
            public_key=data.get("public_key", ""),
            capabilities=tuple(data.get("capabilities", [])),
            runtime_version=data.get("runtime_version", ""),
            created_at=data.get("created_at", ""),
            platform_abi=platform.get("abi", data.get("platform_abi", "")),
            runtime_tier=data.get("runtime_tier", "full"),
            word_size_bits=data.get("word_size_bits", 64),
        )


@dataclass(frozen=True)
class NodeManifest:
    """
    Full node manifest exported to Control Plane.
    Includes identity, workspace config, agent runtimes, and trust zone.
    """

    manifest_version: str = "1.0"
    node_identity: NodeIdentity | None = None
    workspace_root: str = ""
    allowed_paths: tuple[str, ...] = ()
    agent_runtimes: tuple[dict[str, Any], ...] = ()
    trust_zone: str = "personal"
    exported_at: str = ""
    signature: str = ""

    def __post_init__(self):
        if not self.exported_at:
            object.__setattr__(self, "exported_at", _time.utc_now())

    def to_dict(self) -> dict[str, Any]:
        return {
            "manifest_version": self.manifest_version,
            "node_identity": self.node_identity.to_dict() if self.node_identity else {},
            "workspace": {
                "root_path": self.workspace_root,
                "allowed_paths": list(self.allowed_paths),
            },
            "agent_runtimes": list(self.agent_runtimes),
            "trust_zone": self.trust_zone,
            "exported_at": self.exported_at,
        }

    def to_redacted_dict(self) -> dict[str, Any]:
        return redacted_serialization(self.to_dict())

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> NodeManifest:
        identity_data = data.get("node_identity", {})
        workspace = data.get("workspace", {})
        return cls(
            manifest_version=data.get("manifest_version", "1.0"),
            node_identity=NodeIdentity.from_dict(identity_data) if identity_data else None,
            workspace_root=workspace.get("root_path", ""),
            allowed_paths=tuple(workspace.get("allowed_paths", [])),
            agent_runtimes=tuple(data.get("agent_runtimes", [])),
            trust_zone=data.get("trust_zone", "personal"),
            exported_at=data.get("exported_at", ""),
            signature=data.get("signature", ""),
        )

