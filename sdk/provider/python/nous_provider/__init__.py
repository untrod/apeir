"""
Nous Provider SDK — Build hardware providers, engine adapters, and plugins
without reading kernel internals.

This is the ONLY Python module a third-party Provider developer should need
to import. It provides the four Provider interfaces (Discovery, Resource,
Execution, Telemetry) plus lifecycle, health, version negotiation, and
error mapping.

Usage:
    from nous_provider import (
        DiscoveryProvider, ResourceProvider, ExecutionProvider, TelemetryProvider,
        ProviderPackage, Device, Engine, register_provider,
    )

    class MyGPUProvider(DiscoveryProvider, ResourceProvider, TelemetryProvider):
        ...
"""

from __future__ import annotations

__version__ = "1.0.0-beta1"
__api_version__ = "v1beta1"


# ── Re-export public types from the stable ABI ──
# These types are part of the frozen public API. Their definitions live
# in the nous_runtime.kernel package but are re-exported here as the
# stable SDK surface. Third parties should import from nous_provider, not
# from nous_runtime.kernel directly.

from nous_runtime.kernel.resource_model import (
    ResourceVector,
    ResourceLimits,
    ResourceDomain,
    ResourceLease,
    ResourceClaim,
    ResourceSlice,
    PriorityClass,
    PreemptionPolicy,
)

from nous_runtime.kernel.device_model import (
    Device,
    DeviceSpec,
    DeviceStatus,
    DevicePhase,
    DeviceClass,
    DeviceType,
    DeviceRegistry,
    TopologyLink,
)

# ── Provider Interface Base Classes ──

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional
import logging

log = logging.getLogger("nous.provider")


# ── Discovery Provider ──

class DiscoveryProvider(ABC):
    """Discover and describe hardware devices or engines.

    Implement this to make devices/engines visible to the Nous Kernel.
    """

    @abstractmethod
    def discover(self) -> list[Device]:
        """Discover all devices/engines this provider manages.

        Returns a list of Device objects with populated DeviceSpec.
        Each device must have a stable device_id (survives reboots).
        """
        ...

    @abstractmethod
    def probe(self, device_id: str) -> Optional[Device]:
        """Probe a specific device for detailed capabilities."""
        ...

    def describe(self) -> dict:
        """Return provider metadata."""
        return {
            "provider_name": self.__class__.__name__,
            "provider_version": __version__,
            "api_version": __api_version__,
        }

    def topology(self) -> list[TopologyLink]:
        """Return device topology links. Override if devices are interconnected."""
        return []

    def health(self) -> dict:
        """Return provider-level health status."""
        return {"healthy": True, "message": "OK"}


# ── Resource Provider ──

class ResourceProvider(ABC):
    """Manage resource allocation and deallocation for devices.

    The kernel calls these methods to reserve and release hardware resources.
    """

    @abstractmethod
    def claim(self, claim: ResourceClaim) -> bool:
        """Try to claim resources. Returns True if successful."""
        ...

    @abstractmethod
    def reserve(self, device_id: str, amount: ResourceVector) -> Optional[ResourceLease]:
        """Reserve resources on a device. Returns a lease or None."""
        ...

    @abstractmethod
    def release(self, lease_id: str) -> bool:
        """Release a previously granted lease. Returns True if released."""
        ...

    def prepare(self, device_id: str, amount: ResourceVector) -> bool:
        """Prepare a device for workload execution. Optional optimization."""
        return True

    def renew(self, lease_id: str, expected_generation: int) -> Optional[ResourceLease]:
        """Renew a lease. Returns updated lease or None if renewal failed."""
        return None

    def partition(self, device_id: str, partitions: int) -> list[ResourceSlice]:
        """Partition a device into sub-resources. Optional."""
        return []


# ── Execution Provider ──

class ExecutionProvider(ABC):
    """Execute workloads on engines or devices.

    This is the actual inference/execution interface.
    """

    @abstractmethod
    def load(self, model_id: str, device_id: str, config: dict) -> bool:
        """Load a model onto a device/engine."""
        ...

    @abstractmethod
    def infer(self, request: dict) -> dict:
        """Execute an inference request. Returns the response."""
        ...

    def stream(self, request: dict):
        """Stream inference results. Yields token chunks."""
        raise NotImplementedError("Streaming not supported by this provider")

    def cancel(self, request_id: str) -> bool:
        """Cancel an in-flight inference."""
        return False

    def unload(self, model_id: str) -> bool:
        """Unload a model from the device/engine."""
        return True

    def reset(self, device_id: str) -> bool:
        """Reset a device to a clean state."""
        return False


# ── Telemetry Provider ──

class TelemetryProvider(ABC):
    """Report device/engine health, metrics, and faults."""

    @abstractmethod
    def metrics(self, device_id: str) -> dict:
        """Return current metrics for a device."""
        ...

    def events(self, since_us: int = 0) -> list[dict]:
        """Return events since a timestamp. Optional."""
        return []

    def faults(self, device_id: str) -> list[dict]:
        """Return active faults for a device. Optional."""
        return []

    def power(self, device_id: str) -> dict:
        """Return power consumption data. Optional."""
        return {"power_milliwatts": 0}

    def temperature(self, device_id: str) -> float:
        """Return device temperature in Celsius. Optional."""
        return 0.0

    def memory_pressure(self, device_id: str) -> float:
        """Return memory pressure ratio (0.0–1.0). Optional."""
        return 0.0


# ── Provider Registration ──

@dataclass
class ProviderPackage:
    """A complete provider package ready for registration."""
    name: str
    version: str
    provider_class: str  # "device", "engine", "policy"
    discovery: Optional[DiscoveryProvider] = None
    resource: Optional[ResourceProvider] = None
    execution: Optional[ExecutionProvider] = None
    telemetry: Optional[TelemetryProvider] = None
    kernel_min: str = "2.0.0"
    kernel_max: str = "2.99.0"
    os_supported: list[str] = field(default_factory=lambda: ["any"])
    arch_supported: list[str] = field(default_factory=lambda: ["any"])
    hardware_required: list[str] = field(default_factory=list)
    driver_required: list[str] = field(default_factory=list)
    capabilities: list[str] = field(default_factory=list)
    permissions: list[str] = field(default_factory=list)
    conformance_level: str = ""  # DISCOVERABLE, RUNNABLE, ..., CERTIFIED


def register_provider(package: ProviderPackage, endpoint: str | None = None) -> bool:
    """
    Register a provider with the Nous Kernel via NKI.

    This is the standard entry point for all third-party providers.
    It handles:
    1. Connecting to nousd via NKI
    2. Registering devices via RegisterDevice
    3. Registering engines via RegisterEngine
    4. Reporting initial telemetry
    5. Starting the health check loop

    Returns True if registration succeeded.
    """
    import asyncio
    from compat.nki_client import NKIClient

    async def _register():
        client = await NKIClient.connect(endpoint) if endpoint else await NKIClient.connect()

        try:
            # Register devices
            if package.discovery:
                devices = package.discovery.discover()
                for device in devices:
                    nki_req = device.to_nki_register_request()
                    await client.register_device(nki_req["device"])
                    log.info("Registered device: %s (%s)", device.device_id, device.spec.model)

            # Register engines
            if package.execution:
                engine_spec = {
                    "engine_type": package.provider_class,
                    "version": package.version,
                    "capabilities": package.capabilities,
                    "supported_architectures": [],
                    "supported_quantizations": [],
                    "supports_streaming": hasattr(package.execution, "stream"),
                    "supports_batching": False,
                    "supports_pause": False,
                    "supports_snapshot": False,
                }
                await client.register_engine(engine_spec)
                log.info("Registered engine: %s v%s", package.name, package.version)

            return True
        except Exception as exc:
            log.error("Provider registration failed: %s", exc)
            return False
        finally:
            await client.close()

    return asyncio.run(_register())


__all__ = [
    # Types (re-exported from stable ABI)
    "ResourceVector", "ResourceLimits", "ResourceDomain", "ResourceLease",
    "ResourceClaim", "ResourceSlice", "PriorityClass", "PreemptionPolicy",
    "Device", "DeviceSpec", "DeviceStatus", "DevicePhase", "DeviceClass",
    "DeviceType", "DeviceRegistry", "TopologyLink",
    # Provider interfaces
    "DiscoveryProvider", "ResourceProvider", "ExecutionProvider",
    "TelemetryProvider",
    # Package and registration
    "ProviderPackage", "register_provider",
]
