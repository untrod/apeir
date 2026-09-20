from __future__ import annotations

import pytest

from nous_runtime.core.errors import DeviceError
from nous_runtime.device_runtime import (
    DeviceCapabilityManifest,
    DeviceManager,
)


def test_device_manager_selects_capable_healthy_device() -> None:
    events = []
    manager = DeviceManager(event_sink=events.append)
    manager.register(
        DeviceCapabilityManifest(
            device_id="esp32",
            device_type="esp32",
            capabilities=frozenset({"gpio", "adc", "pwm", "uart", "i2c"}),
            transport="serial",
            battery_percent=80,
        )
    )
    manager.register(
        DeviceCapabilityManifest(
            device_id="stm32",
            device_type="stm32",
            capabilities=frozenset({"gpio", "adc"}),
            transport="serial",
            battery_percent=20,
        )
    )
    selected = manager.select(
        {"gpio", "pwm"},
        minimum_battery_percent=30,
    )
    assert selected.device.device_id == "esp32"
    assert events[-1].event_type == "device.selected"


def test_device_manager_heartbeat_and_constraints() -> None:
    manager = DeviceManager()
    manager.register(
        DeviceCapabilityManifest(
            device_id="jetson",
            device_type="jetson",
            capabilities=frozenset({"cuda", "vision", "ai"}),
        )
    )
    manager.heartbeat("jetson", online=False)
    with pytest.raises(DeviceError, match="no device"):
        manager.select({"vision"})
