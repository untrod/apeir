"""Reality contracts built on APEIR's existing Work and evidence contracts.

These types describe managed reality. They do not execute Work, grant authority,
or replace Capability, Observation, OperationReceipt, or Verification Runtime.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Mapping

from nous_runtime.capability.contract import CapabilityContract
from nous_runtime.connectivity.protocol.identity import NodeIdentity
from nous_runtime.planner.observation import Observation


def utc_now() -> str:
    return (
        datetime.now(timezone.utc)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )


class ResourceKind(str, Enum):
    NODE = "node"
    DEVICE = "device"
    CAPABILITY = "capability"
    TRANSPORT = "transport"
    OBSERVATION = "observation"
    OPERATION = "operation"


class RelationKind(str, Enum):
    HOSTS = "HOSTS"
    CONNECTED_TO = "CONNECTED_TO"
    EXPOSES = "EXPOSES"
    REQUIRES = "REQUIRES"
    OBSERVED_BY = "OBSERVED_BY"


class DeviceLifecycle(str, Enum):
    DISCOVERED = "DISCOVERED"
    IDENTIFIED = "IDENTIFIED"
    TRUSTED = "TRUSTED"
    AVAILABLE = "AVAILABLE"
    DEGRADED = "DEGRADED"
    OFFLINE = "OFFLINE"
    REVOKED = "REVOKED"


class EffectVerdict(str, Enum):
    MATCH = "MATCH"
    MISMATCH = "MISMATCH"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class Resource:
    """A persisted graph projection, never an execution authority object."""

    resource_id: str
    kind: ResourceKind
    attributes: Mapping[str, Any] = field(default_factory=dict)
    updated_at: str = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        if not self.resource_id.strip():
            raise ValueError("resource_id is required")
        object.__setattr__(self, "attributes", dict(self.attributes))

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["kind"] = self.kind.value
        return value

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "Resource":
        return cls(
            resource_id=str(value.get("resource_id") or ""),
            kind=ResourceKind(str(value.get("kind") or "")),
            attributes=dict(value.get("attributes") or {}),
            updated_at=str(value.get("updated_at") or utc_now()),
        )


@dataclass(frozen=True)
class Transport:
    """A mutable route to a device; its locator is never device identity."""

    transport_id: str
    kind: str
    locator: str
    node_id: str = ""
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.transport_id.strip() or not self.kind.strip():
            raise ValueError("transport_id and kind are required")
        object.__setattr__(self, "metadata", dict(self.metadata))

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class Device:
    """A managed real-world resource with stable, provider-backed identity."""

    device_id: str
    provider_id: str
    stable_identity: str
    device_type: str
    lifecycle: DeviceLifecycle = DeviceLifecycle.DISCOVERED
    node_id: str = ""
    capability_ids: tuple[str, ...] = ()
    transport_ids: tuple[str, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)
    observed_at: str = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        if not self.device_id.strip() or not self.provider_id.strip():
            raise ValueError("device_id and provider_id are required")
        if not self.stable_identity.strip():
            raise ValueError("stable_identity is required")
        object.__setattr__(
            self, "capability_ids", tuple(sorted(set(self.capability_ids)))
        )
        object.__setattr__(
            self, "transport_ids", tuple(sorted(set(self.transport_ids)))
        )
        object.__setattr__(self, "metadata", dict(self.metadata))

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["lifecycle"] = self.lifecycle.value
        return value

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "Device":
        return cls(
            device_id=str(value.get("device_id") or ""),
            provider_id=str(value.get("provider_id") or ""),
            stable_identity=str(value.get("stable_identity") or ""),
            device_type=str(value.get("device_type") or ""),
            lifecycle=DeviceLifecycle(str(value.get("lifecycle") or "DISCOVERED")),
            node_id=str(value.get("node_id") or ""),
            capability_ids=tuple(value.get("capability_ids") or ()),
            transport_ids=tuple(value.get("transport_ids") or ()),
            metadata=dict(value.get("metadata") or {}),
            observed_at=str(value.get("observed_at") or utc_now()),
        )


@dataclass(frozen=True)
class ResourceRelation:
    source_id: str
    relation: RelationKind
    target_id: str
    attributes: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.source_id.strip() or not self.target_id.strip():
            raise ValueError("relation endpoints are required")
        object.__setattr__(self, "attributes", dict(self.attributes))

    @property
    def relation_id(self) -> str:
        raw = f"{self.source_id}\0{self.relation.value}\0{self.target_id}".encode()
        return "rel_" + hashlib.sha256(raw).hexdigest()[:24]

    def to_dict(self) -> dict[str, Any]:
        return {
            "relation_id": self.relation_id,
            "source_id": self.source_id,
            "relation": self.relation.value,
            "target_id": self.target_id,
            "attributes": dict(self.attributes),
        }


@dataclass(frozen=True)
class Operation:
    """An intended capability invocation belonging to an existing Work."""

    work_id: str
    capability_id: str
    target_resource_id: str
    expected_effect: Mapping[str, Any]
    operation_id: str = field(default_factory=lambda: f"op_{uuid.uuid4().hex}")
    requested_at: str = field(default_factory=utc_now)
    agent_session_id: str = ""
    plan_id: str = ""
    workflow_id: str = ""
    workflow_run_id: str = ""
    node_id: str = ""
    input_artifacts: tuple[str, ...] = ()
    observation_request_id: str = ""
    secret_handles: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not all(
            (
                self.operation_id,
                self.work_id,
                self.capability_id,
                self.target_resource_id,
            )
        ):
            raise ValueError(
                "operation, work, capability, and target identifiers are required"
            )
        object.__setattr__(self, "expected_effect", dict(self.expected_effect))
        object.__setattr__(
            self, "input_artifacts", tuple(dict.fromkeys(self.input_artifacts))
        )

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["input_artifacts"] = list(self.input_artifacts)
        if self.secret_handles:
            value["secret_handles"] = list(self.secret_handles)
        else:
            value.pop("secret_handles")
        return value

    @property
    def expected_effect_digest(self) -> str:
        encoded = json.dumps(
            self.expected_effect,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True)
class EffectVerification:
    operation_id: str
    receipt_operation_id: str
    observation_ids: tuple[str, ...]
    verdict: EffectVerdict
    reason: str
    verification_id: str = field(
        default_factory=lambda: f"effect_verify_{uuid.uuid4().hex}"
    )
    verified_at: str = field(default_factory=utc_now)
    work_id: str = ""
    device_id: str = ""
    receipt_digest: str = ""

    @property
    def committable(self) -> bool:
        """Only independently observed MATCH results may auto-commit."""
        return self.verdict is EffectVerdict.MATCH

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["verdict"] = self.verdict.value
        value["committable"] = self.committable
        return value


# Explicit reuse aliases: these remain the authoritative contracts.
Node = NodeIdentity
Capability = CapabilityContract


__all__ = [
    "Capability",
    "Device",
    "DeviceLifecycle",
    "EffectVerdict",
    "EffectVerification",
    "Node",
    "Observation",
    "Operation",
    "RelationKind",
    "Resource",
    "ResourceKind",
    "ResourceRelation",
    "Transport",
    "utc_now",
]
