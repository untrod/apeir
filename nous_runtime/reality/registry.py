"""Durable Device Registry 2.0 lifecycle projection."""

from __future__ import annotations

import json
import os
from dataclasses import replace
from pathlib import Path
from typing import Any

from nous_runtime.events.bus import RuntimeEventBus
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
        DeviceLifecycle.IDENTIFIED,
        DeviceLifecycle.TRUSTED,
        DeviceLifecycle.AVAILABLE,
        DeviceLifecycle.DEGRADED,
        DeviceLifecycle.REVOKED,
    },
    DeviceLifecycle.REVOKED: set(),
}


class DeviceRegistry:
    def __init__(
        self,
        state_dir: str | Path,
        *,
        event_bus: RuntimeEventBus | None = None,
    ):
        self.state_dir = Path(state_dir).expanduser().resolve()
        self.path = self.state_dir / "reality-devices.json"
        self.events = event_bus
        self._devices: dict[str, Device] = {}
        self._load()

    def register(self, device: Device) -> Device:
        self._load()
        existing = self._devices.get(device.device_id)
        if existing is not None and (
            existing.stable_identity != device.stable_identity
            or existing.provider_id != device.provider_id
        ):
            raise ValueError("device_id collision with a different stable identity")
        for candidate in self._devices.values():
            if (
                candidate.provider_id == device.provider_id
                and candidate.stable_identity == device.stable_identity
                and candidate.device_id != device.device_id
            ):
                raise ValueError("stable device identity is already registered")
        created = existing is None
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
        if created:
            self._publish("reality.device.identified", device)
        return device

    def get(self, device_id: str) -> Device | None:
        self._load()
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
        metadata = dict(current.metadata)
        if target is DeviceLifecycle.OFFLINE:
            metadata["lifecycle_before_offline"] = current.lifecycle.value
        if current.lifecycle is DeviceLifecycle.OFFLINE and target in {
            DeviceLifecycle.IDENTIFIED,
            DeviceLifecycle.TRUSTED,
            DeviceLifecycle.AVAILABLE,
            DeviceLifecycle.DEGRADED,
        }:
            if metadata.get("lifecycle_before_offline") != target.value:
                raise ValueError("offline device has no preserved lifecycle to restore")
        updated = replace(
            current,
            lifecycle=target,
            metadata=metadata,
            observed_at=utc_now(),
        )
        self._devices[device_id] = updated
        self._save()
        self._publish(
            "reality.device.lifecycle.changed",
            updated,
            previous=current.lifecycle.value,
        )
        self._publish(f"reality.device.{target.value.lower()}", updated)
        return updated

    def reconnect(self, device_id: str) -> Device:
        """Restore only trust that existed before a transient disconnect."""
        current = self.get(device_id)
        if current is None:
            raise KeyError(f"device not found: {device_id}")
        if current.lifecycle is DeviceLifecycle.REVOKED:
            return current
        if current.lifecycle is not DeviceLifecycle.OFFLINE:
            return current
        before = str(current.metadata.get("lifecycle_before_offline") or "")
        target = DeviceLifecycle(before) if before else DeviceLifecycle.DISCOVERED
        return self.transition(device_id, target)

    def _publish(self, event_type: str, device: Device, **extra: Any) -> None:
        if self.events is None:
            return
        self.events.publish(
            event_type,
            source="reality.device-registry",
            payload={
                "device_id": device.device_id,
                "provider_id": device.provider_id,
                "lifecycle": device.lifecycle.value,
                **extra,
            },
            metadata={"device_id": device.device_id},
        )

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
