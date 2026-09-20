# -*- coding: utf-8 -*-
"""
Device Adapter — unified abstraction for hardware integration.

Implements §16 (External Device & Hardware Access) of the master plan.

Provides a common interface for integrating:
- Jetson (edge AI)
- STM32 (microcontroller)
- ESP32 (IoT)
- PLC (industrial control)
- Raspberry Pi
- Robot platforms
- Cameras and sensors
- App-controlled devices

Design (§16.2): Models never access raw device protocols. All devices
register capabilities (sensor.read, camera.capture, robot.move, etc.)
with safety constraints enforced by the Admission Pipeline.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from nous_runtime.kernel.error_codes import ErrorCode, NousResult
from nous_runtime.compat.ids import make_id

log = logging.getLogger("nous.device")


# Device types

@dataclass
class DeviceInfo:
    """Static device information."""
    device_id: str = field(default_factory=lambda: make_id(prefix="dev"))
    device_type: str = ""             # jetson, stm32, esp32, plc, rpi, camera, robot
    manufacturer: str = ""
    model: str = ""
    firmware_version: str = ""
    serial_number: str = ""
    capabilities: list[str] = field(default_factory=list)  # Registered capability IDs


# Safety constraints

@dataclass
class DeviceSafetyConstraints:
    """Safety limits for device operations (§16.3)."""
    max_value: float = float("inf")
    min_value: float = float("-inf")
    max_rate_per_second: float = 10.0
    require_confirmation: bool = True   # Require user confirmation for operations
    emergency_stop_capability: str = ""  # Capability to call for E-Stop
    physical_safety_check: str = ""     # Pre-condition check (e.g., "area_clear")
    timeout_seconds: int = 30


# Device Adapter ABC

class DeviceAdapter(ABC):
    """Abstract base for all device integrations.

    Subclass this to add support for a new hardware device.
    """

    def __init__(self, device_info: DeviceInfo):
        self.info = device_info
        self._safety = DeviceSafetyConstraints()
        self._rate_limiter: dict[str, list[float]] = {}  # capability → timestamps
        self._connected = False

    @abstractmethod
    def connect(self) -> NousResult[None]:
        """Establish connection to the device."""
        ...

    @abstractmethod
    def disconnect(self) -> NousResult[None]:
        """Safely disconnect from the device."""
        ...

    @abstractmethod
    def execute(self, capability_id: str, params: dict[str, Any]) -> NousResult[Any]:
        """Execute a device capability."""
        ...

    @abstractmethod
    def health(self) -> dict[str, Any]:
        """Return device health status."""
        ...

    # Safety helpers

    def check_value_range(self, value: float, capability_id: str) -> NousResult[None]:
        """Validate that a value is within safety limits."""
        if value > self._safety.max_value:
            return NousResult.err(
                ErrorCode.INVALID_ARGUMENT,
                message=f"Value {value} exceeds max {self._safety.max_value} for {capability_id}",
            )
        if value < self._safety.min_value:
            return NousResult.err(
                ErrorCode.INVALID_ARGUMENT,
                message=f"Value {value} below min {self._safety.min_value} for {capability_id}",
            )
        return NousResult.ok(None)

    def check_rate_limit(self, capability_id: str) -> NousResult[None]:
        """Enforce rate limiting on device operations."""
        import time
        now = time.monotonic()
        if capability_id not in self._rate_limiter:
            self._rate_limiter[capability_id] = []

        # Prune old timestamps
        window = 1.0  # 1-second window
        timestamps = [t for t in self._rate_limiter[capability_id]
                      if now - t < window]
        self._rate_limiter[capability_id] = timestamps

        if len(timestamps) >= self._safety.max_rate_per_second:
            return NousResult.err(
                ErrorCode.RATE_LIMITED,
                message=f"Rate limit exceeded for {capability_id}: "
                        f"max {self._safety.max_rate_per_second}/s",
            )

        self._rate_limiter[capability_id].append(now)
        return NousResult.ok(None)

    def emergency_stop(self) -> NousResult[None]:
        """Trigger emergency stop on the device."""
        if not self._safety.emergency_stop_capability:
            return NousResult.err(ErrorCode.NOT_FOUND,
                                  message="No E-Stop capability configured")
        return self.execute(self._safety.emergency_stop_capability, {})

    @property
    def is_connected(self) -> bool:
        return self._connected

    @property
    def safety(self) -> DeviceSafetyConstraints:
        return self._safety


# Device Registry

class DeviceRegistry:
    """Registry of all connected device adapters."""

    def __init__(self):
        self._devices: dict[str, DeviceAdapter] = {}

    def register(self, adapter: DeviceAdapter) -> NousResult[DeviceAdapter]:
        device_id = adapter.info.device_id
        if device_id in self._devices:
            return NousResult.err(ErrorCode.ALREADY_EXISTS,
                                  message=f"Device '{device_id}' already registered")
        self._devices[device_id] = adapter
        return NousResult.ok(adapter)

    def get(self, device_id: str) -> NousResult[DeviceAdapter]:
        adapter = self._devices.get(device_id)
        if adapter is None:
            return NousResult.err(ErrorCode.NOT_FOUND,
                                  message=f"Device '{device_id}' not found")
        return NousResult.ok(adapter)

    def list_all(self) -> list[DeviceAdapter]:
        return list(self._devices.values())

    def list_by_type(self, device_type: str) -> list[DeviceAdapter]:
        return [d for d in self._devices.values()
                if d.info.device_type == device_type]

    def execute(self, device_id: str, capability_id: str,
                params: dict[str, Any]) -> NousResult[Any]:
        """Execute a capability on a specific device."""
        result = self.get(device_id)
        if not result.ok:
            return result
        adapter = result.value

        # Safety: rate limit check
        rate_result = adapter.check_rate_limit(capability_id)
        if not rate_result.ok:
            return rate_result

        return adapter.execute(capability_id, params)

    def emergency_stop_all(self) -> dict[str, NousResult[None]]:
        """Trigger E-Stop on all connected devices."""
        results = {}
        for device_id, adapter in self._devices.items():
            results[device_id] = adapter.emergency_stop()
            log.warning("E-Stop triggered on device '%s': %s",
                        device_id, "OK" if results[device_id].ok else results[device_id].message)
        return results

    def health(self) -> dict[str, Any]:
        devices_health = {}
        for device_id, adapter in self._devices.items():
            devices_health[device_id] = {
                "type": adapter.info.device_type,
                "connected": adapter.is_connected,
                "health": adapter.health(),
            }
        return {
            "total_devices": len(self._devices),
            "connected": sum(1 for d in self._devices.values() if d.is_connected),
            "devices": devices_health,
        }
