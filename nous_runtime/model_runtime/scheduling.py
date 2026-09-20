"""Hardware- and cost-aware policies layered on the canonical ModelRouter.

RC6: HardwareSnapshot now integrates with the new Device Resource Model
(nous_runtime.kernel.device_model) for GPU discovery via NVML and proper
NUMA topology. The legacy psutil+env fallback is preserved for backward compat.
"""

from __future__ import annotations

import logging
import os
import platform
import shutil
from dataclasses import dataclass, replace
from pathlib import Path
from typing import TYPE_CHECKING

from nous_runtime.model_runtime.models import (
    ModelRequest,
    PrivacyClass,
    RouteDecision,
    RoutingMode,
)
from nous_runtime.model_runtime.registry import ModelRuntimeRegistry
from nous_runtime.model_runtime.router import ModelRouter, RoutingWeights

if TYPE_CHECKING:
    from nous_runtime.kernel.device_model import DeviceRegistry

log = logging.getLogger("nous.model_runtime.scheduling")


@dataclass(frozen=True)
class HardwareSnapshot:
    cpu_count: int
    ram_available_mb: int
    disk_available_mb: int
    gpu_available: bool = False
    vram_available_mb: int = 0
    battery_percent: float | None = None
    on_battery: bool = False
    network_available: bool = True
    network_metered: bool = False
    architecture: str = ""


def detect_hardware_snapshot(path: str | Path = ".") -> HardwareSnapshot:
    ram_mb = 0
    battery_percent: float | None = None
    on_battery = False
    try:
        import psutil

        ram_mb = int(psutil.virtual_memory().available / (1024 * 1024))
        battery = psutil.sensors_battery()
        if battery is not None:
            battery_percent = float(battery.percent)
            on_battery = not bool(battery.power_plugged)
    except (ImportError, OSError, AttributeError):
        pass
    vram_mb = max(0, int(os.environ.get("NOUS_GPU_VRAM_MB") or 0))
    network = os.environ.get("NOUS_NETWORK_AVAILABLE", "1") != "0"
    metered = os.environ.get("NOUS_NETWORK_METERED", "0") == "1"
    return HardwareSnapshot(
        cpu_count=os.cpu_count() or 1,
        ram_available_mb=ram_mb,
        disk_available_mb=int(shutil.disk_usage(Path(path)).free / (1024 * 1024)),
        gpu_available=vram_mb > 0,
        vram_available_mb=vram_mb,
        battery_percent=battery_percent,
        on_battery=on_battery,
        network_available=network,
        network_metered=metered,
        architecture=platform.machine(),
    )


@dataclass(frozen=True)
class ResourceSchedulingDecision:
    request: ModelRequest
    locality_preference: str
    preferred_models: tuple[str, ...]
    reasons: tuple[str, ...]


class HardwareScheduler:
    """Translate live resources into Router constraints and preferences.

    RC6: Prefers the new Device model (DeviceRegistry) when available,
    with automatic fallback to legacy HardwareSnapshot.
    """

    def __init__(
        self,
        registry: ModelRuntimeRegistry,
        snapshot: HardwareSnapshot | None = None,
    ) -> None:
        self.registry = registry
        # Try RC6 Device model first
        if snapshot is not None:
            self.snapshot = snapshot
        else:
            try:
                device_registry = detect_devices_rc6()
                self.snapshot = hardware_snapshot_from_devices(device_registry)
            except Exception:
                self.snapshot = detect_hardware_snapshot()

    def prepare(self, request: ModelRequest) -> ResourceSchedulingDecision:
        reasons: list[str] = []
        routing_mode = request.routing_mode
        local_preferred = (
            self.snapshot.gpu_available
            and self.snapshot.vram_available_mb >= 4096
            and self.snapshot.ram_available_mb >= 8192
        )
        if request.privacy_policy in {
            PrivacyClass.PRIVATE,
            PrivacyClass.RESTRICTED,
        }:
            local_preferred = True
            routing_mode = RoutingMode.LOCAL_ONLY
            reasons.append("privacy policy requires local execution")
        elif not self.snapshot.network_available:
            local_preferred = True
            routing_mode = RoutingMode.OFFLINE
            reasons.append("network unavailable")
        elif self.snapshot.on_battery and (
            self.snapshot.battery_percent is None or self.snapshot.battery_percent < 30
        ):
            local_preferred = False
            reasons.append("low battery favors remote execution")
        elif self.snapshot.network_metered:
            local_preferred = True
            reasons.append("metered network favors local execution")
        elif local_preferred:
            reasons.append("local accelerator capacity is sufficient")
        else:
            reasons.append("limited local resources favor remote execution")

        preferred = tuple(
            descriptor.model_id
            for descriptor in self.registry.enabled_descriptors()
            if descriptor.is_local is local_preferred and self._fits(descriptor)
        )
        if preferred and routing_mode is RoutingMode.AUTO:
            routing_mode = RoutingMode.PREFERRED
        prepared = replace(
            request,
            preferred_models=tuple(
                dict.fromkeys((*request.preferred_models, *preferred))
            ),
            routing_mode=routing_mode,
            metadata={
                **dict(request.metadata),
                "hardware_scheduler": {
                    "locality_preference": ("local" if local_preferred else "remote"),
                    "reasons": reasons,
                },
            },
        )
        return ResourceSchedulingDecision(
            request=prepared,
            locality_preference="local" if local_preferred else "remote",
            preferred_models=preferred,
            reasons=tuple(reasons),
        )

    def route(self, request: ModelRequest) -> RouteDecision:
        return ModelRouter(self.registry).route(self.prepare(request).request)

    def _fits(self, descriptor: object) -> bool:
        requirements = descriptor.resource_requirements
        if (
            self.snapshot.ram_available_mb
            and requirements.memory_mb > self.snapshot.ram_available_mb
        ):
            return False
        if requirements.gpu_required and not self.snapshot.gpu_available:
            return False
        return not (
            self.snapshot.vram_available_mb
            and requirements.vram_mb > self.snapshot.vram_available_mb
        )


# ────────────────────────────────────────────────────────────
# RC6: Device-aware detection using the new Device Resource Model
# ────────────────────────────────────────────────────────────


def detect_devices_rc6() -> "DeviceRegistry":
    """
    RC6 hardware discovery using the new Device Resource Model.

    Performs full hardware discovery (CPU with NUMA, NVIDIA GPUs via NVML)
    and returns a populated DeviceRegistry. Falls back to a basic CPU device
    if discovery fails.

    This is the preferred detection mechanism going forward. The legacy
    HardwareSnapshot/detect_hardware_snapshot() is preserved for backward
    compatibility.
    """
    from nous_runtime.kernel.device_model import DeviceRegistry, Device

    registry = DeviceRegistry()

    try:
        from nous_runtime.kernel.hardware_discovery import discover_all_devices

        devices = discover_all_devices()
        for device in devices:
            registry.register(device)
        log.info("RC6 Device discovery: registered %d device(s)", len(devices))
    except Exception as exc:
        log.warning("RC6 Device discovery failed (%s), using CPU fallback", exc)
        registry.register(Device.cpu_default())

    if not registry.devices:
        registry.register(Device.cpu_default())

    return registry


def hardware_snapshot_from_devices(registry: "DeviceRegistry") -> "HardwareSnapshot":
    """
    Build a legacy HardwareSnapshot from the new DeviceRegistry.

    This bridge allows existing code to consume the new Device model
    without changes, while new code uses the full DeviceRegistry.
    """
    from nous_runtime.kernel.device_model import DeviceType

    cpu_count = 0
    ram_available_mb = 0
    disk_available_mb = 0
    gpu_available = False
    vram_available_mb = 0

    # Aggregate from all CPU devices
    cpu_devices = registry.list_by_type(DeviceType.CPU)
    for device in cpu_devices:
        cpu_count += device.spec.compute_units
        ram_available_mb += device.status.available.ram_bytes // (1024 * 1024)

    # Aggregate from GPU devices
    gpu_devices = (
        registry.list_by_type(DeviceType.CUDA)
        + registry.list_by_type(DeviceType.ROCM)
        + registry.list_by_type(DeviceType.METAL)
        + registry.list_by_type(DeviceType.VULKAN)
        + registry.list_by_type(DeviceType.NPU)
    )
    for device in gpu_devices:
        gpu_available = True
        vram_available_mb += device.status.available.device_memory_bytes // (
            1024 * 1024
        )

    # Accumulate from all devices
    for device in registry.list_all():
        ram_available_mb += device.status.available.ram_bytes // (1024 * 1024)

    if cpu_count == 0:
        cpu_count = os.cpu_count() or 1
    if ram_available_mb == 0:
        try:
            import psutil

            ram_available_mb = int(psutil.virtual_memory().available / (1024 * 1024))
        except ImportError:
            ram_available_mb = 8192

    try:
        disk_available_mb = int(shutil.disk_usage(Path(".")).free / (1024 * 1024))
    except Exception:
        disk_available_mb = 10240

    return HardwareSnapshot(
        cpu_count=cpu_count,
        ram_available_mb=int(ram_available_mb),
        disk_available_mb=disk_available_mb,
        gpu_available=gpu_available,
        vram_available_mb=int(vram_available_mb),
        battery_percent=None,
        on_battery=False,
        network_available=True,
        network_metered=False,
        architecture=platform.machine(),
    )


class CostScheduler:
    """Use the Router with an explicit quality/speed/price objective."""

    COST_AWARE_WEIGHTS = RoutingWeights(
        capability=0.24,
        modality=0.12,
        quality=0.18,
        availability=0.10,
        latency=0.14,
        cost=0.17,
        privacy=0.05,
    )

    def __init__(self, registry: ModelRuntimeRegistry) -> None:
        self.router = ModelRouter(
            registry,
            weights=self.COST_AWARE_WEIGHTS,
        )

    def route(self, request: ModelRequest) -> RouteDecision:
        return self.router.route(request)


__all__ = [
    "CostScheduler",
    "HardwareScheduler",
    "HardwareSnapshot",
    "ResourceSchedulingDecision",
    "detect_hardware_snapshot",
    "detect_devices_rc6",
    "hardware_snapshot_from_devices",
]
