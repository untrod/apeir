"""APEIR managed-reality foundation."""

from nous_runtime.reality.contracts import (
    Capability,
    Device,
    DeviceLifecycle,
    EffectVerdict,
    EffectVerification,
    Node,
    Observation,
    Operation,
    RelationKind,
    Resource,
    ResourceKind,
    ResourceRelation,
    Transport,
)
from nous_runtime.reality.graph import ResourceGraph
from nous_runtime.reality.provider import (
    DeviceDiscovery,
    DeviceProvider,
    DeviceTransport,
    SimulatedDeviceProvider,
    SimulatedTransport,
)
from nous_runtime.reality.registry import DeviceRegistry
from nous_runtime.reality.verification import EffectVerifier

__all__ = [
    "Capability",
    "Device",
    "DeviceDiscovery",
    "DeviceLifecycle",
    "DeviceProvider",
    "DeviceRegistry",
    "DeviceTransport",
    "EffectVerdict",
    "EffectVerification",
    "EffectVerifier",
    "Node",
    "Observation",
    "Operation",
    "RelationKind",
    "Resource",
    "ResourceGraph",
    "ResourceKind",
    "ResourceRelation",
    "SimulatedDeviceProvider",
    "SimulatedTransport",
    "Transport",
]
