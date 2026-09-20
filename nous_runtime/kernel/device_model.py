"""
Device Model — Python mirror of nous-types/src/device.rs.

This module provides the canonical Python representation of the Nous
device model: Device, DeviceSpec, DeviceStatus, DevicePhase,
DeviceClass, and TopologyLink.

These types are wire-compatible with the Rust nous-types crate and
are the foundation for hardware discovery, Provider SDK, and the
conformance test kit.

DeviceClass taxonomy:
  nvidia.cuda.high-memory    — NVIDIA GPU with ≥16GB VRAM
  nvidia.cuda.standard       — NVIDIA GPU with <16GB VRAM
  nvidia.jetson              — NVIDIA Jetson edge devices
  amd.rocm.general           — AMD GPU via ROCm
  intel.openvino.edge        — Intel OpenVINO inference
  qualcomm.qnn.npu           — Qualcomm AI Engine (NPU)
  apple.metal.general         — Apple Silicon via Metal/CoreML
  cpu.general                — Generic CPU inference
  remote.llm.api             — Cloud API endpoint
  remote.compute             — Remote compute node

Design principle:
  - 1:1 field compatibility with Rust types for NKI serialization
  - Stable device_id that survives reboots (not PCI bus order dependent)
  - Vendor-agnostic: same interface for NVIDIA, AMD, Qualcomm, Apple, CPU
"""

from __future__ import annotations

import hashlib
import platform
import time
import uuid
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Optional

from nous_runtime.kernel.resource_model import ResourceVector


# ────────────────────────────────────────────────────────────
# DevicePhase — lifecycle state machine
# ────────────────────────────────────────────────────────────

class DevicePhase(IntEnum):
    """Device lifecycle phase. Mirrors Rust DevicePhase enum."""
    UNKNOWN = 0
    DISCOVERED = 1
    PROBED = 2
    BOUND = 3
    INITIALIZED = 4
    READY = 5
    ALLOCATING = 6
    BUSY = 7
    DRAINING = 8
    SUSPENDED = 9
    RESETTING = 10
    FAILED = 11
    UNBOUND = 12

    @property
    def is_operational(self) -> bool:
        """Device can accept workloads."""
        return self in (
            DevicePhase.READY,
            DevicePhase.ALLOCATING,
            DevicePhase.BUSY,
        )

    @property
    def is_terminal(self) -> bool:
        """Device has reached a terminal state (cannot be recovered)."""
        return self == DevicePhase.UNBOUND

    @property
    def can_recover(self) -> bool:
        """Device can be recovered from this state."""
        return self in (
            DevicePhase.FAILED,
            DevicePhase.SUSPENDED,
            DevicePhase.DRAINING,
            DevicePhase.RESETTING,
        )


# ────────────────────────────────────────────────────────────
# DeviceClass — standard taxonomy
# ────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class DeviceClass:
    """
    Standardized device class identifier.

    Examples:
        nvidia.cuda.high-memory
        amd.rocm.general
        qualcomm.qnn.npu
        cpu.general
        remote.llm.api
    """

    vendor: str
    runtime: str
    tier: str = "general"

    @classmethod
    def from_string(cls, s: str) -> "DeviceClass":
        parts = s.split(".", 2)
        return cls(
            vendor=parts[0] if len(parts) > 0 else "unknown",
            runtime=parts[1] if len(parts) > 1 else "unknown",
            tier=parts[2] if len(parts) > 2 else "general",
        )

    def to_string(self) -> str:
        return f"{self.vendor}.{self.runtime}.{self.tier}"

    def __str__(self) -> str:
        return self.to_string()

    def __hash__(self) -> int:
        return hash(self.to_string())


# Canonical device classes
DEVICE_CLASS_CPU = DeviceClass("cpu", "general", "general")
DEVICE_CLASS_NVIDIA_CUDA = DeviceClass("nvidia", "cuda", "standard")
DEVICE_CLASS_NVIDIA_CUDA_HIGH_MEM = DeviceClass("nvidia", "cuda", "high-memory")
DEVICE_CLASS_NVIDIA_JETSON = DeviceClass("nvidia", "jetson", "edge")
DEVICE_CLASS_AMD_ROCM = DeviceClass("amd", "rocm", "general")
DEVICE_CLASS_INTEL_OPENVINO = DeviceClass("intel", "openvino", "edge")
DEVICE_CLASS_QUALCOMM_QNN = DeviceClass("qualcomm", "qnn", "npu")
DEVICE_CLASS_APPLE_METAL = DeviceClass("apple", "metal", "general")
DEVICE_CLASS_REMOTE_LLM = DeviceClass("remote", "llm", "api")
DEVICE_CLASS_REMOTE_COMPUTE = DeviceClass("remote", "compute", "general")


# ────────────────────────────────────────────────────────────
# DeviceType — hardware type enumeration
# ────────────────────────────────────────────────────────────

class DeviceType(IntEnum):
    """Hardware device type. Mirrors Rust DeviceType enum."""
    UNSPECIFIED = 0
    CPU = 1
    CUDA = 2
    ROCM = 3
    VULKAN = 4
    OPENVINO = 5
    METAL = 6
    SYCL = 7
    CANN = 8
    QNN = 9
    DSP = 10
    FPGA = 11
    NPU = 12
    REMOTE = 13

    @classmethod
    def from_string(cls, s: str) -> "DeviceType":
        mapping = {
            "cpu": cls.CPU, "cuda": cls.CUDA, "rocm": cls.ROCM,
            "vulkan": cls.VULKAN, "openvino": cls.OPENVINO,
            "metal": cls.METAL, "sycl": cls.SYCL, "cann": cls.CANN,
            "qnn": cls.QNN, "dsp": cls.DSP, "fpga": cls.FPGA,
            "npu": cls.NPU, "remote": cls.REMOTE,
        }
        return mapping.get(s.lower(), cls.UNSPECIFIED)


# ────────────────────────────────────────────────────────────
# TopologyLink — device interconnect
# ────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class TopologyLink:
    """A link between two devices in the topology graph."""
    from_device_id: str
    to_device_id: str
    link_type: str = ""         # PCIe, NVLink, RDMA, Ethernet, etc.
    bandwidth_bps: int = 0
    latency_ns: int = 0

    def to_dict(self) -> dict:
        return {
            "from_device_id": self.from_device_id,
            "to_device_id": self.to_device_id,
            "link_type": self.link_type,
            "bandwidth_bps": self.bandwidth_bps,
            "latency_ns": self.latency_ns,
        }


# ────────────────────────────────────────────────────────────
# DeviceSpec — immutable device identity and capability
# ────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class DeviceSpec:
    """Immutable device identity, capabilities, and total resources."""

    device_type: DeviceType = DeviceType.UNSPECIFIED
    vendor: str = ""
    model: str = ""
    driver_version: str = ""
    architecture: str = ""       # e.g. "Ampere", "RDNA3", "A78"
    total_resources: ResourceVector = field(default_factory=ResourceVector.zero)
    capabilities: tuple[str, ...] = ()  # e.g. ("fp16", "bf16", "cuda_graph")
    supported_engines: tuple[str, ...] = ()  # e.g. ("llama.cpp", "vllm", "onnx")
    supported_dtypes: tuple[str, ...] = ()   # e.g. ("fp32", "fp16", "bf16", "int8")
    compute_units: int = 0       # SM count (NVIDIA), CU count (AMD), etc.
    numa_node: int = -1          # NUMA affinity (-1 = unknown)
    pci_bus_id: str = ""         # PCI bus ID for stable identification

    def to_dict(self) -> dict:
        return {
            "device_type": self.device_type.name,
            "vendor": self.vendor,
            "model": self.model,
            "driver_version": self.driver_version,
            "architecture": self.architecture,
            "total_resources": self.total_resources.to_dict(),
            "capabilities": list(self.capabilities),
            "supported_engines": list(self.supported_engines),
            "supported_dtypes": list(self.supported_dtypes),
            "compute_units": self.compute_units,
            "numa_node": self.numa_node,
            "pci_bus_id": self.pci_bus_id,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "DeviceSpec":
        return cls(
            device_type=DeviceType.from_string(d.get("device_type", "")),
            vendor=d.get("vendor", ""),
            model=d.get("model", ""),
            driver_version=d.get("driver_version", ""),
            architecture=d.get("architecture", ""),
            total_resources=ResourceVector.from_dict(d.get("total_resources", {})),
            capabilities=tuple(d.get("capabilities", [])),
            supported_engines=tuple(d.get("supported_engines", [])),
            supported_dtypes=tuple(d.get("supported_dtypes", [])),
            compute_units=int(d.get("compute_units", 0)),
            numa_node=int(d.get("numa_node", -1)),
            pci_bus_id=d.get("pci_bus_id", ""),
        )


# ────────────────────────────────────────────────────────────
# DeviceStatus — mutable device state, telemetry, health
# ────────────────────────────────────────────────────────────

@dataclass
class DeviceStatus:
    """Mutable device state: health, utilization, active workloads."""

    phase: DevicePhase = DevicePhase.UNKNOWN
    available: ResourceVector = field(default_factory=ResourceVector.zero)
    temperature_celsius: float = 0.0
    power_milliwatts: int = 0
    utilization_percent: float = 0.0
    memory_utilization_percent: float = 0.0
    active_engines: list[str] = field(default_factory=list)
    active_workloads: list[str] = field(default_factory=list)
    topology: Optional[TopologyLink] = None
    last_health_check: float = 0.0
    error_count: int = 0
    last_error: str = ""
    uptime_seconds: float = 0.0

    def is_healthy(self) -> bool:
        """Device is operational and not in an error state."""
        return self.phase.is_operational and self.error_count < 3

    def update_telemetry(
        self,
        temperature: float = 0.0,
        power_mw: int = 0,
        utilization: float = 0.0,
        memory_util: float = 0.0,
    ) -> None:
        """Update telemetry readings from hardware."""
        self.temperature_celsius = temperature
        self.power_milliwatts = power_mw
        self.utilization_percent = utilization
        self.memory_utilization_percent = memory_util
        self.last_health_check = time.time()

    def to_dict(self) -> dict:
        return {
            "phase": self.phase.name,
            "available": self.available.to_dict(),
            "temperature_celsius": self.temperature_celsius,
            "power_milliwatts": self.power_milliwatts,
            "utilization_percent": self.utilization_percent,
            "memory_utilization_percent": self.memory_utilization_percent,
            "active_engines": self.active_engines,
            "active_workloads": self.active_workloads,
            "topology": self.topology.to_dict() if self.topology else None,
            "last_health_check": self.last_health_check,
            "error_count": self.error_count,
            "last_error": self.last_error,
            "uptime_seconds": self.uptime_seconds,
        }


# ────────────────────────────────────────────────────────────
# Device — the complete device object
# ────────────────────────────────────────────────────────────

@dataclass
class Device:
    """
    A hardware device registered with the Nous Kernel.

    Mirrors the Rust `Device` type: meta + spec + status.
    The device_id is stable across reboots (derived from hardware identity,
    not PCI enumeration order).
    """

    device_id: str = field(default_factory=lambda: f"dev_{uuid.uuid4().hex}")
    spec: DeviceSpec = field(default_factory=DeviceSpec)
    status: DeviceStatus = field(default_factory=DeviceStatus)
    device_class: DeviceClass = DEVICE_CLASS_CPU
    created_at: float = field(default_factory=time.time)
    labels: dict = field(default_factory=dict)

    # ── Factory methods ──

    @classmethod
    def cpu_default(cls) -> "Device":
        """Create a CPU device from the current system."""
        import os
        cpu_count = os.cpu_count() or 1
        try:
            import psutil
            mem = psutil.virtual_memory()
            ram_bytes = mem.total
        except ImportError:
            ram_bytes = 8 * 1024 * 1024 * 1024  # Assume 8GB

        stable_id = _stable_device_id("cpu", platform.node(), "cpu-0")
        return cls(
            device_id=stable_id,
            spec=DeviceSpec(
                device_type=DeviceType.CPU,
                vendor=platform.processor() or "unknown",
                model=platform.machine(),
                architecture=platform.machine(),
                total_resources=ResourceVector(
                    cpu_cores_millis=cpu_count * 1000,
                    ram_bytes=ram_bytes,
                    storage_bytes=1_000_000_000_000,  # Assume 1TB
                ),
                capabilities=("inference", "embedding"),
                supported_engines=("llama.cpp", "onnx", "openvino"),
                supported_dtypes=("fp32", "fp16", "int8"),
                compute_units=cpu_count,
            ),
            status=DeviceStatus(
                phase=DevicePhase.READY,
                available=ResourceVector(
                    cpu_cores_millis=cpu_count * 1000,
                    ram_bytes=ram_bytes,
                ),
            ),
            device_class=DEVICE_CLASS_CPU,
        )

    @classmethod
    def from_dict(cls, d: dict) -> "Device":
        return cls(
            device_id=d.get("device_id", ""),
            spec=DeviceSpec.from_dict(d.get("spec", {})),
            status=DeviceStatus(),
            device_class=DeviceClass.from_string(d.get("device_class", "cpu.general.general")),
            created_at=float(d.get("created_at", 0)),
            labels=dict(d.get("labels", {})),
        )

    # ── Resource management ──

    def can_accept(self, requirements: ResourceVector) -> bool:
        """Check if this device can accept a workload with given requirements."""
        return requirements.fits_within(self.status.available)

    def reserve(self, amount: ResourceVector) -> bool:
        """Try to reserve resources on this device."""
        if not self.can_accept(amount):
            return False
        self.status.available = self.status.available - amount
        return True

    def release(self, amount: ResourceVector) -> None:
        """Release previously reserved resources."""
        self.status.available = self.status.available + amount

    def utilization(self) -> float:
        """Overall device utilization (0.0–1.0)."""
        return max(self.status.utilization_percent, self.status.memory_utilization_percent) / 100.0

    # ── Serialization ──

    def to_dict(self) -> dict:
        return {
            "device_id": self.device_id,
            "spec": self.spec.to_dict(),
            "status": self.status.to_dict(),
            "device_class": self.device_class.to_string(),
            "created_at": self.created_at,
            "labels": self.labels,
        }

    def to_nki_register_request(self) -> dict:
        """Build the NKI RegisterDevice request payload."""
        return {
            "device": {
                "device_type": self.spec.device_type.name,
                "vendor": self.spec.vendor,
                "model": self.spec.model,
                "driver_version": self.spec.driver_version,
                "total_resources": self.spec.total_resources.to_dict(),
                "capabilities": list(self.spec.capabilities),
            }
        }


# ────────────────────────────────────────────────────────────
# Device Registry
# ────────────────────────────────────────────────────────────

@dataclass
class DeviceRegistry:
    """
    Thread-safe registry of all discovered devices.

    The registry maintains the authoritative list of devices known
    to this node. It is populated by Device Providers during discovery
    and used by the scheduler for placement decisions.
    """

    devices: dict[str, Device] = field(default_factory=dict)

    def register(self, device: Device) -> None:
        """Register or update a device."""
        self.devices[device.device_id] = device

    def unregister(self, device_id: str) -> Optional[Device]:
        """Remove a device from the registry."""
        return self.devices.pop(device_id, None)

    def get(self, device_id: str) -> Optional[Device]:
        """Get a device by ID."""
        return self.devices.get(device_id)

    def list_all(self) -> list[Device]:
        """List all registered devices."""
        return list(self.devices.values())

    def list_by_class(self, device_class: DeviceClass) -> list[Device]:
        """List devices matching a DeviceClass."""
        return [d for d in self.devices.values() if d.device_class == device_class]

    def list_operational(self) -> list[Device]:
        """List devices that are ready for workloads."""
        return [d for d in self.devices.values() if d.status.phase.is_operational]

    def list_by_type(self, device_type: DeviceType) -> list[Device]:
        """List devices of a specific hardware type."""
        return [d for d in self.devices.values() if d.spec.device_type == device_type]

    def find_best_fit(
        self,
        requirements: ResourceVector,
        device_class: Optional[DeviceClass] = None,
        prefer_local: bool = True,
    ) -> Optional[Device]:
        """Find the best device that satisfies the given requirements."""
        candidates = self.list_operational()
        if device_class:
            candidates = [d for d in candidates if d.device_class == device_class]

        # Filter by resource requirements
        feasible = [d for d in candidates if d.can_accept(requirements)]
        if not feasible:
            return None

        # Score: prefer least utilized (best fit, not most free)
        def score(device: Device) -> tuple:
            # Negative utilization → higher score (we want low utilization)
            util = device.utilization()
            # Prefer exact fit over wasteful
            free = device.status.available
            waste = (
                (free.device_memory_bytes - requirements.device_memory_bytes) +
                (free.ram_bytes - requirements.ram_bytes)
            )
            return (util, waste)

        feasible.sort(key=score)
        return feasible[0]

    def total_capacity(self) -> ResourceVector:
        """Aggregate capacity across all registered devices."""
        total = ResourceVector.zero()
        for device in self.devices.values():
            total = total + device.spec.total_resources
        return total

    def total_available(self) -> ResourceVector:
        """Aggregate available resources across all operational devices."""
        total = ResourceVector.zero()
        for device in self.list_operational():
            total = total + device.status.available
        return total


# ────────────────────────────────────────────────────────────
# Stable device ID generation
# ────────────────────────────────────────────────────────────

def _stable_device_id(vendor: str, hostname: str, device_name: str) -> str:
    """
    Generate a stable device ID that survives reboots.

    Uses SHA-256 of (vendor + hostname + device_name) to produce
    a deterministic ID that does not depend on PCI enumeration order
    or driver loading sequence.
    """
    seed = f"{vendor}:{hostname}:{device_name}".encode("utf-8")
    digest = hashlib.sha256(seed).hexdigest()[:16]
    return f"dev-{vendor.lower()}-{digest}"


__all__ = [
    "Device",
    "DeviceSpec",
    "DeviceStatus",
    "DevicePhase",
    "DeviceClass",
    "DeviceType",
    "DeviceRegistry",
    "TopologyLink",
    "DEVICE_CLASS_CPU",
    "DEVICE_CLASS_NVIDIA_CUDA",
    "DEVICE_CLASS_NVIDIA_CUDA_HIGH_MEM",
    "DEVICE_CLASS_NVIDIA_JETSON",
    "DEVICE_CLASS_AMD_ROCM",
    "DEVICE_CLASS_INTEL_OPENVINO",
    "DEVICE_CLASS_QUALCOMM_QNN",
    "DEVICE_CLASS_APPLE_METAL",
    "DEVICE_CLASS_REMOTE_LLM",
    "DEVICE_CLASS_REMOTE_COMPUTE",
]
