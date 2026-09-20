"""Device registration, heartbeat and capability-aware selection."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Callable

from nous_runtime.core.errors import DeviceError
from nous_runtime.core.events import EventEnvelope, _timestamp
from nous_runtime.device_runtime.models import DeviceCapabilityManifest


EventSink = Callable[[EventEnvelope], None]


@dataclass(frozen=True)
class DeviceSelection:
    device: DeviceCapabilityManifest
    score: float
    reasons: tuple[str, ...]


class DeviceManager:
    def __init__(self, *, event_sink: EventSink | None = None) -> None:
        self._devices: dict[str, DeviceCapabilityManifest] = {}
        self.event_sink = event_sink

    def register(
        self,
        manifest: DeviceCapabilityManifest,
        *,
        replace_existing: bool = False,
    ) -> DeviceCapabilityManifest:
        if (
            manifest.device_id in self._devices
            and not replace_existing
        ):
            raise DeviceError(
                f"device already registered: {manifest.device_id}"
            )
        self._devices[manifest.device_id] = manifest
        self._emit("device.registered", manifest)
        return manifest

    def get(self, device_id: str) -> DeviceCapabilityManifest | None:
        return self._devices.get(str(device_id))

    def list(
        self, *, online_only: bool = False
    ) -> tuple[DeviceCapabilityManifest, ...]:
        return tuple(
            item
            for item in sorted(
                self._devices.values(), key=lambda value: value.device_id
            )
            if not online_only or item.online
        )

    def remove(self, device_id: str) -> DeviceCapabilityManifest:
        try:
            manifest = self._devices.pop(str(device_id))
        except KeyError as exc:
            raise DeviceError(f"device not found: {device_id}") from exc
        self._emit("device.removed", manifest)
        return manifest

    def heartbeat(
        self,
        device_id: str,
        *,
        online: bool = True,
        battery_percent: float | None = None,
    ) -> DeviceCapabilityManifest:
        current = self.get(device_id)
        if current is None:
            raise DeviceError(f"device not found: {device_id}")
        updated = replace(
            current,
            online=online,
            battery_percent=(
                current.battery_percent
                if battery_percent is None
                else battery_percent
            ),
            observed_at=_timestamp(),
        )
        self._devices[device_id] = updated
        self._emit("device.heartbeat", updated)
        return updated

    def select(
        self,
        capabilities: set[str] | frozenset[str],
        *,
        trust_zones: set[str] | frozenset[str] | None = None,
        transport: str | None = None,
        minimum_battery_percent: float = 0.0,
    ) -> DeviceSelection:
        required = frozenset(str(item) for item in capabilities)
        candidates: list[DeviceSelection] = []
        for device in self._devices.values():
            if not device.online or not device.supports(required):
                continue
            if trust_zones and device.trust_zone not in trust_zones:
                continue
            if transport and device.transport != transport:
                continue
            if (
                device.battery_percent is not None
                and device.battery_percent < minimum_battery_percent
            ):
                continue
            battery_score = (
                1.0
                if device.battery_percent is None
                else device.battery_percent / 100.0
            )
            headroom = max(0, len(device.capabilities - required))
            score = 0.75 + battery_score * 0.20 + min(0.05, headroom * 0.01)
            candidates.append(
                DeviceSelection(
                    device=device,
                    score=round(score, 6),
                    reasons=(
                        "all required capabilities available",
                        f"trust_zone={device.trust_zone}",
                        f"transport={device.transport or 'unspecified'}",
                    ),
                )
            )
        if not candidates:
            raise DeviceError("no device satisfies capability constraints")
        candidates.sort(key=lambda item: (-item.score, item.device.device_id))
        selected = candidates[0]
        self._emit("device.selected", selected.device)
        return selected

    def _emit(
        self, event_type: str, manifest: DeviceCapabilityManifest
    ) -> None:
        if self.event_sink is not None:
            self.event_sink(
                EventEnvelope(
                    event_type=event_type,
                    source="device_runtime",
                    payload={
                        "device_id": manifest.device_id,
                        "device_type": manifest.device_type,
                        "capabilities": sorted(manifest.capabilities),
                    },
                )
            )


__all__ = ["DeviceManager", "DeviceSelection"]
