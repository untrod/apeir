"""Admission contracts for device and defensive-security workloads.

The contract describes scope only; it does not implement attack techniques.
Executors must receive explicit authorized assets before defensive work runs.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from nous_runtime.core.errors import CapabilityError


class WorkloadKind(str, Enum):
    COMPUTE = "compute"
    DEVICE = "device"
    DEFENSIVE_SECURITY = "defensive_security"


DEFENSIVE_ACTIONS = frozenset(
    {
        "asset_inventory",
        "configuration_audit",
        "vulnerability_assessment",
        "log_analysis",
        "detection",
        "containment",
        "remediation",
        "recovery",
        "compliance",
    }
)

_PROHIBITED_MARKERS = (
    "credential_dump",
    "credential_theft",
    "exfiltration",
    "persistence",
    "self_propagation",
    "ransomware",
    "exploit_public_target",
)


@dataclass(frozen=True)
class WorkloadProfile:
    kind: WorkloadKind = WorkloadKind.COMPUTE
    action: str = "execute"
    required_capabilities: tuple[str, ...] = ()
    target_nodes: tuple[str, ...] = ()
    authorized_assets: tuple[str, ...] = ()
    max_parallel_lanes: int = 1
    metadata: dict[str, Any] = field(default_factory=dict)

    def validate(self) -> None:
        if not 1 <= self.max_parallel_lanes <= 64:
            raise CapabilityError("parallel lane count must be between 1 and 64")
        normalized = " ".join((self.action, *self.required_capabilities)).lower()
        if any(marker in normalized for marker in _PROHIBITED_MARKERS):
            raise CapabilityError("workload is outside the defensive security boundary")
        if self.kind == WorkloadKind.DEFENSIVE_SECURITY:
            if self.action not in DEFENSIVE_ACTIONS:
                raise CapabilityError(
                    f"unsupported defensive action: {self.action or '<empty>'}"
                )
            if not self.authorized_assets:
                raise CapabilityError(
                    "defensive security workloads require explicit authorized assets"
                )

    def to_dict(self) -> dict[str, Any]:
        self.validate()
        return {
            "kind": self.kind.value,
            "action": self.action,
            "required_capabilities": list(self.required_capabilities),
            "target_nodes": list(self.target_nodes),
            "authorized_assets": list(self.authorized_assets),
            "max_parallel_lanes": self.max_parallel_lanes,
            "metadata": dict(self.metadata),
        }


def defensive_workload(
    action: str,
    *,
    authorized_assets: tuple[str, ...] | list[str],
    target_nodes: tuple[str, ...] | list[str] = (),
    max_parallel_lanes: int = 1,
) -> WorkloadProfile:
    """Build and validate an authorized defensive-security workload."""
    profile = WorkloadProfile(
        kind=WorkloadKind.DEFENSIVE_SECURITY,
        action=action,
        required_capabilities=(f"security.defensive.{action}",),
        target_nodes=tuple(target_nodes),
        authorized_assets=tuple(authorized_assets),
        max_parallel_lanes=max_parallel_lanes,
    )
    profile.validate()
    return profile
