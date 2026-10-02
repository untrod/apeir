"""Durable Device Registry 2.0 lifecycle projection."""

from __future__ import annotations

import json
import os
from dataclasses import replace
from pathlib import Path

from nous_runtime.reality.contracts import Device, DeviceLifecycle, utc_now


_TRANSITIONS = {
    DeviceLifecycle.DISCOVERED: {
        DeviceLifecycle.IDENTIFIED,
        DeviceLifecycle.OFFLINE,
        DeviceLifecycle.REVOKED,
    },
    DeviceLifecycle.IDENTIFIED: {
        DeviceLifecycle.TRUSTED,
        DeviceLifecycle.DEGRADED,
        DeviceLifecycle.OFFLINE,
        DeviceLifecycle.REVOKED,
    },
    DeviceLifecycle.TRUSTED: {
        DeviceLifecycle.AVAILABLE,
        DeviceLifecycle.DEGRADED,
        DeviceLifecycle.OFFLINE,
        DeviceLifecycle.REVOKED,
    },
    DeviceLifecycle.AVAILABLE: {
        DeviceLifecycle.DEGRADED,
        DeviceLifecycle.OFFLINE,
        DeviceLifecycle.REVOKED,
    },
    DeviceLifecycle.DEGRADED: {
        DeviceLifecycle.AVAILABLE,
        DeviceLifecycle.OFFLINE,
        DeviceLifecycle.REVOKED,
    },
    DeviceLifecycle.OFFLINE: {
        DeviceLifecycle.DISCOVERED,
        DeviceLifecycle.REVOKED,
    },
    DeviceLifecycle.REVOKED: set(),
}


class DeviceRegistry:
    def __init__(self, state_dir: str | Path):
        self.state_dir = Path(state_dir).expanduser().resolve()
        self.path = self.state_dir / "reality-devices.json"
        self._devices: dict[str, Device] = {}
        self._load()

    def register(self, device: Device) -> Device:
        existing = self._devices.get(device.device_id)
        if existing is not None and existing.stable_identity != device.stable_identity:
            raise ValueError("device_id collision with a different stable identity")
        for candidate in self._devices.values():
            if (
                candidate.provider_id == device.provider_id
                and candidate.stable_identity == device.stable_identity
                and candidate.device_id != device.device_id
            ):
                raise ValueError("stable device identity is already registered")
        if existing is not None:
            # Rediscovery refreshes routes and metadata, but cannot reduce trust or
            # resurrect a revoked Device.
            device = replace(
                existing,
                node_id=device.node_id or existing.node_id,
                capability_ids=tuple(
                    sorted(set(existing.capability_ids) | set(device.capability_ids))
                ),
                transport_ids=tuple(
                    sorted(set(existing.transport_ids) | set(device.transport_ids))
                ),
                metadata={**existing.metadata, **device.metadata},
                observed_at=utc_now(),
            )
        self._devices[device.device_id] = device
        self._save()
        return device

    def get(self, device_id: str) -> Device | None:
        return self._devices.get(device_id)

    def list(self) -> tuple[Device, ...]:
        return tuple(sorted(self._devices.values(), key=lambda item: item.device_id))

    def transition(self, device_id: str, target: DeviceLifecycle) -> Device:
        current = self.get(device_id)
        if current is None:
            raise KeyError(f"device not found: {device_id}")
        if target is current.lifecycle:
            return current
        if target not in _TRANSITIONS[current.lifecycle]:
            raise ValueError(
                f"invalid device transition: {current.lifecycle.value} -> {target.value}"
            )
        updated = replace(current, lifecycle=target, observed_at=utc_now())
        self._devices[device_id] = updated
        self._save()
        return updated

    def _load(self) -> None:
        if not self.path.is_file():
            return
        value = json.loads(self.path.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise ValueError("device registry state must be a JSON object")
        self._devices = {
            item.device_id: item
            for item in (Device.from_dict(raw) for raw in value.get("devices", ()))
        }

    def _save(self) -> None:
        self.state_dir.mkdir(parents=True, exist_ok=True)
        value = {
            "schema": "apeir.reality-device-registry/v1alpha1",
            "devices": [item.to_dict() for item in self.list()],
        }
        temporary = self.path.with_suffix(f"{self.path.suffix}.{os.getpid()}.tmp")
        with temporary.open("x", encoding="utf-8", newline="\n") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        temporary.replace(self.path)


__all__ = ["DeviceRegistry"]
