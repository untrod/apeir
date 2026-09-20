"""
Device Resource Model — Python mirror of nous-types/src/resource.rs.

This module provides the canonical Python representation of the Nous
resource model: ResourceVector, ResourceDomain, ResourceLease,
ResourceLimits, PriorityClass, and PreemptionPolicy.

These types are wire-compatible with the Rust nous-types crate and
are used by the NKI client, hardware discovery, scheduler, and
Provider SDK.

Design principle:
  - 1:1 field compatibility with Rust types for NKI serialization
  - Pythonic convenience methods (arithmetic, comparison, formatting)
  - Immutable (frozen dataclasses) by default; mutable builders available
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Optional


# ────────────────────────────────────────────────────────────
# ResourceVector — 13-dimension resource measurement
# ────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class ResourceVector:
    """
    A vector of resource dimensions for allocation, reservation, and consumption.

    All fields use their natural units:
    - cpu_cores_millis: 1000 = 1 CPU core
    - *_bytes: bytes
    - *_us: microseconds
    - *_bps: bytes per second
    - power_milliwatts: milliwatts
    - thermal_budget_millic: millidegrees Celsius
    """

    cpu_cores_millis: int = 0
    cpu_time_us: int = 0
    ram_bytes: int = 0
    pinned_ram_bytes: int = 0
    device_memory_bytes: int = 0
    kv_cache_bytes: int = 0
    storage_bytes: int = 0
    memory_bandwidth_bps: int = 0
    interconnect_bandwidth_bps: int = 0
    network_bandwidth_bps: int = 0
    power_milliwatts: int = 0
    thermal_budget_millic: int = 0
    time_budget_us: int = 0

    # ── Factory methods ──

    @classmethod
    def zero(cls) -> "ResourceVector":
        """Create a zero vector."""
        return cls()

    @classmethod
    def from_dict(cls, d: dict) -> "ResourceVector":
        """Deserialize from NKI JSON dict."""
        return cls(
            cpu_cores_millis=int(d.get("cpu_cores_millis", 0)),
            cpu_time_us=int(d.get("cpu_time_us", 0)),
            ram_bytes=int(d.get("ram_bytes", 0)),
            pinned_ram_bytes=int(d.get("pinned_ram_bytes", 0)),
            device_memory_bytes=int(d.get("device_memory_bytes", 0)),
            kv_cache_bytes=int(d.get("kv_cache_bytes", 0)),
            storage_bytes=int(d.get("storage_bytes", 0)),
            memory_bandwidth_bps=int(d.get("memory_bandwidth_bps", 0)),
            interconnect_bandwidth_bps=int(d.get("interconnect_bandwidth_bps", 0)),
            network_bandwidth_bps=int(d.get("network_bandwidth_bps", 0)),
            power_milliwatts=int(d.get("power_milliwatts", 0)),
            thermal_budget_millic=int(d.get("thermal_budget_millic", 0)),
            time_budget_us=int(d.get("time_budget_us", 0)),
        )

    # ── Arithmetic ──

    def __add__(self, other: "ResourceVector") -> "ResourceVector":
        return ResourceVector(
            cpu_cores_millis=self.cpu_cores_millis + other.cpu_cores_millis,
            cpu_time_us=self.cpu_time_us + other.cpu_time_us,
            ram_bytes=self.ram_bytes + other.ram_bytes,
            pinned_ram_bytes=self.pinned_ram_bytes + other.pinned_ram_bytes,
            device_memory_bytes=self.device_memory_bytes + other.device_memory_bytes,
            kv_cache_bytes=self.kv_cache_bytes + other.kv_cache_bytes,
            storage_bytes=self.storage_bytes + other.storage_bytes,
            memory_bandwidth_bps=self.memory_bandwidth_bps + other.memory_bandwidth_bps,
            interconnect_bandwidth_bps=self.interconnect_bandwidth_bps + other.interconnect_bandwidth_bps,
            network_bandwidth_bps=self.network_bandwidth_bps + other.network_bandwidth_bps,
            power_milliwatts=self.power_milliwatts + other.power_milliwatts,
            thermal_budget_millic=self.thermal_budget_millic + other.thermal_budget_millic,
            time_budget_us=self.time_budget_us + other.time_budget_us,
        )

    def __sub__(self, other: "ResourceVector") -> "ResourceVector":
        return ResourceVector(
            cpu_cores_millis=max(0, self.cpu_cores_millis - other.cpu_cores_millis),
            cpu_time_us=max(0, self.cpu_time_us - other.cpu_time_us),
            ram_bytes=max(0, self.ram_bytes - other.ram_bytes),
            pinned_ram_bytes=max(0, self.pinned_ram_bytes - other.pinned_ram_bytes),
            device_memory_bytes=max(0, self.device_memory_bytes - other.device_memory_bytes),
            kv_cache_bytes=max(0, self.kv_cache_bytes - other.kv_cache_bytes),
            storage_bytes=max(0, self.storage_bytes - other.storage_bytes),
            memory_bandwidth_bps=max(0, self.memory_bandwidth_bps - other.memory_bandwidth_bps),
            interconnect_bandwidth_bps=max(0, self.interconnect_bandwidth_bps - other.interconnect_bandwidth_bps),
            network_bandwidth_bps=max(0, self.network_bandwidth_bps - other.network_bandwidth_bps),
            power_milliwatts=max(0, self.power_milliwatts - other.power_milliwatts),
            thermal_budget_millic=max(0, self.thermal_budget_millic - other.thermal_budget_millic),
            time_budget_us=max(0, self.time_budget_us - other.time_budget_us),
        )

    # ── Comparison ──

    def fits_within(self, capacity: "ResourceVector") -> bool:
        """Check if this vector fits within capacity in all dimensions."""
        return (
            self.cpu_cores_millis <= capacity.cpu_cores_millis
            and self.cpu_time_us <= capacity.cpu_time_us
            and self.ram_bytes <= capacity.ram_bytes
            and self.pinned_ram_bytes <= capacity.pinned_ram_bytes
            and self.device_memory_bytes <= capacity.device_memory_bytes
            and self.kv_cache_bytes <= capacity.kv_cache_bytes
            and self.storage_bytes <= capacity.storage_bytes
            and self.memory_bandwidth_bps <= capacity.memory_bandwidth_bps
            and self.interconnect_bandwidth_bps <= capacity.interconnect_bandwidth_bps
            and self.network_bandwidth_bps <= capacity.network_bandwidth_bps
            and self.power_milliwatts <= capacity.power_milliwatts
            and self.thermal_budget_millic <= capacity.thermal_budget_millic
            and self.time_budget_us <= capacity.time_budget_us
        )

    def is_zero(self) -> bool:
        """Check if all dimensions are zero."""
        return self == ResourceVector.zero()

    def max_per_dimension(self, other: "ResourceVector") -> "ResourceVector":
        """Element-wise maximum."""
        return ResourceVector(
            cpu_cores_millis=max(self.cpu_cores_millis, other.cpu_cores_millis),
            cpu_time_us=max(self.cpu_time_us, other.cpu_time_us),
            ram_bytes=max(self.ram_bytes, other.ram_bytes),
            pinned_ram_bytes=max(self.pinned_ram_bytes, other.pinned_ram_bytes),
            device_memory_bytes=max(self.device_memory_bytes, other.device_memory_bytes),
            kv_cache_bytes=max(self.kv_cache_bytes, other.kv_cache_bytes),
            storage_bytes=max(self.storage_bytes, other.storage_bytes),
            memory_bandwidth_bps=max(self.memory_bandwidth_bps, other.memory_bandwidth_bps),
            interconnect_bandwidth_bps=max(self.interconnect_bandwidth_bps, other.interconnect_bandwidth_bps),
            network_bandwidth_bps=max(self.network_bandwidth_bps, other.network_bandwidth_bps),
            power_milliwatts=max(self.power_milliwatts, other.power_milliwatts),
            thermal_budget_millic=max(self.thermal_budget_millic, other.thermal_budget_millic),
            time_budget_us=max(self.time_budget_us, other.time_budget_us),
        )

    # ── Serialization ──

    def to_dict(self) -> dict:
        """Serialize to NKI-compatible JSON dict."""
        return {
            "cpu_cores_millis": self.cpu_cores_millis,
            "cpu_time_us": self.cpu_time_us,
            "ram_bytes": self.ram_bytes,
            "pinned_ram_bytes": self.pinned_ram_bytes,
            "device_memory_bytes": self.device_memory_bytes,
            "kv_cache_bytes": self.kv_cache_bytes,
            "storage_bytes": self.storage_bytes,
            "memory_bandwidth_bps": self.memory_bandwidth_bps,
            "interconnect_bandwidth_bps": self.interconnect_bandwidth_bps,
            "network_bandwidth_bps": self.network_bandwidth_bps,
            "power_milliwatts": self.power_milliwatts,
            "thermal_budget_millic": self.thermal_budget_millic,
            "time_budget_us": self.time_budget_us,
        }

    # ── Human-readable ──

    def summary(self) -> str:
        """One-line human-readable summary."""
        parts = []
        if self.cpu_cores_millis:
            parts.append(f"cpu={self.cpu_cores_millis / 1000:.1f}cores")
        if self.ram_bytes:
            parts.append(f"ram={_human_bytes(self.ram_bytes)}")
        if self.device_memory_bytes:
            parts.append(f"vram={_human_bytes(self.device_memory_bytes)}")
        if self.kv_cache_bytes:
            parts.append(f"kv={_human_bytes(self.kv_cache_bytes)}")
        return " ".join(parts) if parts else "zero"


# ────────────────────────────────────────────────────────────
# ResourceLimits
# ────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class ResourceLimits:
    """Resource limits for a domain or capability grant."""

    max_cpu_cores_millis: Optional[int] = None
    max_ram_bytes: Optional[int] = None
    max_device_memory_bytes: Optional[int] = None
    max_kv_cache_bytes: Optional[int] = None
    max_storage_bytes: Optional[int] = None
    max_power_milliwatts: Optional[int] = None
    max_concurrent_workloads: Optional[int] = None

    @classmethod
    def from_dict(cls, d: dict) -> "ResourceLimits":
        return cls(
            max_cpu_cores_millis=d.get("max_cpu_cores_millis"),
            max_ram_bytes=d.get("max_ram_bytes"),
            max_device_memory_bytes=d.get("max_device_memory_bytes"),
            max_kv_cache_bytes=d.get("max_kv_cache_bytes"),
            max_storage_bytes=d.get("max_storage_bytes"),
            max_power_milliwatts=d.get("max_power_milliwatts"),
            max_concurrent_workloads=d.get("max_concurrent_workloads"),
        )

    def to_dict(self) -> dict:
        return {
            k: v for k, v in {
                "max_cpu_cores_millis": self.max_cpu_cores_millis,
                "max_ram_bytes": self.max_ram_bytes,
                "max_device_memory_bytes": self.max_device_memory_bytes,
                "max_kv_cache_bytes": self.max_kv_cache_bytes,
                "max_storage_bytes": self.max_storage_bytes,
                "max_power_milliwatts": self.max_power_milliwatts,
                "max_concurrent_workloads": self.max_concurrent_workloads,
            }.items() if v is not None
        }


# ────────────────────────────────────────────────────────────
# ResourceDomain
# ────────────────────────────────────────────────────────────

@dataclass
class ResourceDomain:
    """
    A hierarchical resource domain: System → Tenant → Workspace → Agent → Workload.

    Each domain has capacity, tracks allocated and reserved resources,
    and enforces hard/soft limits.
    """

    domain_id: str
    parent_domain_id: Optional[str] = None
    capacity: ResourceVector = field(default_factory=ResourceVector.zero)
    allocated: ResourceVector = field(default_factory=ResourceVector.zero)
    reserved: ResourceVector = field(default_factory=ResourceVector.zero)
    hard_limits: ResourceLimits = field(default_factory=ResourceLimits)
    soft_limits: ResourceLimits = field(default_factory=ResourceLimits)

    def can_fit(self, request: "ResourceVector") -> bool:
        """Check if there is enough available capacity for a request."""
        available = self.capacity - self.allocated - self.reserved
        return request.fits_within(available)

    def available(self) -> "ResourceVector":
        """Resources not currently allocated or reserved."""
        return self.capacity - self.allocated - self.reserved

    def allocate(self, amount: "ResourceVector") -> bool:
        """Try to allocate resources. Returns True on success."""
        if not self.can_fit(amount):
            return False
        self.allocated = self.allocated + amount
        return True

    def release(self, amount: "ResourceVector") -> None:
        """Release previously allocated resources."""
        self.allocated = self.allocated - amount

    def to_dict(self) -> dict:
        return {
            "domain_id": self.domain_id,
            "parent_domain_id": self.parent_domain_id,
            "capacity": self.capacity.to_dict(),
            "allocated": self.allocated.to_dict(),
            "reserved": self.reserved.to_dict(),
            "hard_limits": self.hard_limits.to_dict(),
            "soft_limits": self.soft_limits.to_dict(),
        }


# ────────────────────────────────────────────────────────────
# ResourceLease
# ────────────────────────────────────────────────────────────

@dataclass(init=False)
class ResourceLease:
    """
    A time-bound resource reservation for a specific workload.

    Core invariant: NO LEASE → NO EXECUTION.
    Every workload must hold a valid, unexpired lease before execution.
    """

    lease_id: str = field(default_factory=lambda: f"lease_{uuid.uuid4().hex}")
    workload_id: str = ""
    principal_id: str = ""
    reserved: ResourceVector = field(default_factory=ResourceVector.zero)
    node_id: str = ""
    device_id: str = ""
    granted_at_us: int = 0       # Microseconds since epoch (wire format)
    expires_at_us: int = 0      # Microseconds since epoch (wire format)
    generation: int = 1
    renewable: bool = True

    # ── Backward compat: also expose as float seconds for internal use ──

    def __init__(
        self,
        lease_id: str | None = None,
        workload_id: str = "",
        principal_id: str = "",
        reserved: ResourceVector | None = None,
        node_id: str = "",
        device_id: str = "",
        granted_at_us: int = 0,
        expires_at_us: int = 0,
        generation: int = 1,
        renewable: bool = True,
        *,
        granted_at: float | None = None,
        expires_at: float | None = None,
    ) -> None:
        """Create from canonical microseconds or legacy second values."""
        now_us = int(time.time() * 1_000_000)
        self.lease_id = lease_id or f"lease_{uuid.uuid4().hex}"
        self.workload_id = workload_id
        self.principal_id = principal_id
        self.reserved = reserved or ResourceVector.zero()
        self.node_id = node_id
        self.device_id = device_id
        self.granted_at_us = (
            int(granted_at * 1_000_000)
            if granted_at is not None
            else int(granted_at_us or now_us)
        )
        self.expires_at_us = (
            int(expires_at * 1_000_000)
            if expires_at is not None
            else int(expires_at_us or self.granted_at_us + 300_000_000)
        )
        self.generation = generation
        self.renewable = renewable

    @property
    def granted_at(self) -> float:
        return self.granted_at_us / 1_000_000.0

    @property
    def expires_at(self) -> float:
        return self.expires_at_us / 1_000_000.0

    def is_valid(self) -> bool:
        """Check if the lease is currently valid (not expired)."""
        return time.time() * 1_000_000 < self.expires_at_us

    def is_expired(self) -> bool:
        """Check if the lease has expired."""
        return not self.is_valid()

    def remaining_seconds(self) -> float:
        """Time remaining before expiry in seconds."""
        return max(0.0, (self.expires_at_us - time.time() * 1_000_000) / 1_000_000.0)

    def renew(self, duration_seconds: float = 300.0) -> None:
        """Renew the lease for an additional duration."""
        self.expires_at_us = int(time.time() * 1_000_000 + duration_seconds * 1_000_000)
        self.generation += 1

    def to_dict(self) -> dict:
        # H2 fix: emit microseconds (_us suffix) to match NKI wire format + proto
        return {
            "lease_id": self.lease_id,
            "workload_id": self.workload_id,
            "principal_id": self.principal_id,
            "reserved": self.reserved.to_dict(),
            "node_id": self.node_id,
            "device_id": self.device_id,
            "granted_at_us": self.granted_at_us,
            "expires_at_us": self.expires_at_us,
            "generation": self.generation,
            "renewable": self.renewable,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "ResourceLease":
        # H2 fix: accept both _us (microseconds, wire format) and legacy float seconds
        granted = int(d.get("granted_at_us", 0))
        expires = int(d.get("expires_at_us", 0))
        if not granted:  # Legacy: plain float seconds
            legacy = d.get("granted_at", 0)
            if legacy and legacy > 0:
                granted = int(float(legacy) * 1_000_000)
        if not expires:
            legacy = d.get("expires_at", 0)
            if legacy and legacy > 0:
                expires = int(float(legacy) * 1_000_000)
        return cls(
            lease_id=d.get("lease_id", ""),
            workload_id=d.get("workload_id", ""),
            principal_id=d.get("principal_id", ""),
            reserved=ResourceVector.from_dict(d.get("reserved", {})),
            node_id=d.get("node_id", ""),
            device_id=d.get("device_id", ""),
            granted_at_us=granted,
            expires_at_us=expires,
            generation=int(d.get("generation", 1)),
            renewable=bool(d.get("renewable", True)),
        )


# ────────────────────────────────────────────────────────────
# PriorityClass & PreemptionPolicy
# ────────────────────────────────────────────────────────────

class PriorityClass(IntEnum):
    """Workload priority for scheduling."""
    SYSTEM = 0       # Kernel operations (highest)
    INTERACTIVE = 1  # User-facing requests (default)
    BATCH = 2        # Background jobs
    BEST_EFFORT = 3  # Lowest priority, preemptible

    @classmethod
    def from_string(cls, s: str) -> "PriorityClass":
        mapping = {
            "SYSTEM": cls.SYSTEM,
            "INTERACTIVE": cls.INTERACTIVE,
            "BATCH": cls.BATCH,
            "BEST_EFFORT": cls.BEST_EFFORT,
            "system": cls.SYSTEM,
            "interactive": cls.INTERACTIVE,
            "batch": cls.BATCH,
            "best_effort": cls.BEST_EFFORT,
        }
        return mapping.get(s, cls.INTERACTIVE)


class PreemptionPolicy(IntEnum):
    """Preemption policy for scheduling."""
    NEVER = 0             # Never preempt
    IF_LOWER_PRIORITY = 1  # Preempt if higher priority needs resources
    ALWAYS = 2            # Always allow preemption

    @classmethod
    def from_string(cls, s: str) -> "PreemptionPolicy":
        mapping = {
            "NEVER": cls.NEVER,
            "IF_LOWER_PRIORITY": cls.IF_LOWER_PRIORITY,
            "ALWAYS": cls.ALWAYS,
            "never": cls.NEVER,
            "if_lower_priority": cls.IF_LOWER_PRIORITY,
            "always": cls.ALWAYS,
        }
        return mapping.get(s, cls.NEVER)


# ────────────────────────────────────────────────────────────
# ResourceClaim & ResourceSlice (Provider ↔ Kernel protocol)
# ────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class ResourceClaim:
    """
    What a workload or provider requires from the system.

    This is the "demand side" — submitted by workloads and validated
    by the admission controller against available ResourceSlices.
    """

    claim_id: str = field(default_factory=lambda: f"claim_{uuid.uuid4().hex}")
    workload_id: str = ""
    minimum: ResourceVector = field(default_factory=ResourceVector.zero)
    preferred: ResourceVector = field(default_factory=ResourceVector.zero)
    maximum: ResourceVector = field(default_factory=ResourceVector.zero)
    priority: PriorityClass = PriorityClass.INTERACTIVE
    preemption: PreemptionPolicy = PreemptionPolicy.NEVER
    required_device_classes: tuple[str, ...] = ()  # e.g. ("nvidia.cuda.high-memory",)
    required_capabilities: tuple[str, ...] = ()    # e.g. ("fp16", "cuda_graph")
    allow_remote: bool = True
    deadline_seconds: float = 0.0
    node_affinity: Optional[str] = None
    device_affinity: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "claim_id": self.claim_id,
            "workload_id": self.workload_id,
            "minimum": self.minimum.to_dict(),
            "preferred": self.preferred.to_dict(),
            "maximum": self.maximum.to_dict(),
            "priority": self.priority.name,
            "preemption": self.preemption.name,
            "required_device_classes": list(self.required_device_classes),
            "required_capabilities": list(self.required_capabilities),
            "allow_remote": self.allow_remote,
            "deadline_seconds": self.deadline_seconds,
            "node_affinity": self.node_affinity,
            "device_affinity": self.device_affinity,
        }


@dataclass
class ResourceSlice:
    """
    What a device/provider makes available to the kernel.

    This is the "supply side" — reported by Device Providers via
    the Discovery + Resource Provider interfaces. The scheduler
    matches ResourceClaims against available ResourceSlices.
    """

    slice_id: str = field(default_factory=lambda: f"slice_{uuid.uuid4().hex}")
    device_id: str = ""
    device_class: str = ""  # e.g. "nvidia.cuda.high-memory"
    node_id: str = ""
    capacity: ResourceVector = field(default_factory=ResourceVector.zero)
    available: ResourceVector = field(default_factory=ResourceVector.zero)
    attributes: dict = field(default_factory=dict)
    health_score: float = 1.0  # 0.0 (dead) to 1.0 (perfect)
    last_updated: float = field(default_factory=time.time)

    def utilization(self) -> float:
        """Return utilization ratio (0.0–1.0) for the primary resource."""
        if self.capacity.device_memory_bytes > 0:
            used = self.capacity.device_memory_bytes - self.available.device_memory_bytes
            return max(0.0, min(1.0, used / self.capacity.device_memory_bytes))
        if self.capacity.ram_bytes > 0:
            used = self.capacity.ram_bytes - self.available.ram_bytes
            return max(0.0, min(1.0, used / self.capacity.ram_bytes))
        return 0.0

    def can_satisfy(self, claim: "ResourceClaim") -> bool:
        """Check if this slice can satisfy a ResourceClaim."""
        return claim.minimum.fits_within(self.available)

    def to_dict(self) -> dict:
        return {
            "slice_id": self.slice_id,
            "device_id": self.device_id,
            "device_class": self.device_class,
            "node_id": self.node_id,
            "capacity": self.capacity.to_dict(),
            "available": self.available.to_dict(),
            "attributes": self.attributes,
            "health_score": self.health_score,
            "last_updated": self.last_updated,
        }


# ────────────────────────────────────────────────────────────
# Helpers
# ────────────────────────────────────────────────────────────

def _human_bytes(n: int) -> str:
    if n >= 1 << 40:
        return f"{n / (1 << 40):.1f}TiB"
    if n >= 1 << 30:
        return f"{n / (1 << 30):.1f}GiB"
    if n >= 1 << 20:
        return f"{n / (1 << 20):.1f}MiB"
    if n >= 1 << 10:
        return f"{n / (1 << 10):.1f}KiB"
    return f"{n}B"


__all__ = [
    "ResourceVector",
    "ResourceLimits",
    "ResourceDomain",
    "ResourceLease",
    "ResourceClaim",
    "ResourceSlice",
    "PriorityClass",
    "PreemptionPolicy",
]
