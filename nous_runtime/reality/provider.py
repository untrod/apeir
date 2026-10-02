"""Minimal provider and transport boundaries for managed devices."""

from __future__ import annotations

import hashlib
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Mapping

from nous_runtime.planner.observation import Observation
from nous_runtime.reality.contracts import Device, DeviceLifecycle, Transport
from nous_runtime.reality.registry import DeviceRegistry


@dataclass(frozen=True)
class DeviceDiscovery:
    provider_id: str
    locator: str
    hints: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.provider_id.strip() or not self.locator.strip():
            raise ValueError("provider_id and locator are required")
        object.__setattr__(self, "hints", dict(self.hints))


class DeviceTransport(ABC):
    """Transport moves requests; it does not define device identity."""

    @property
    @abstractmethod
    def descriptor(self) -> Transport: ...

    @abstractmethod
    def read(self, device: Device) -> Mapping[str, Any]: ...


class DeviceProvider(ABC):
    provider_id: str

    @abstractmethod
    def discover(self) -> tuple[DeviceDiscovery, ...]: ...

    @abstractmethod
    def identify(self, discovery: DeviceDiscovery) -> Device: ...

    @abstractmethod
    def read_state(self, device: Device) -> Observation: ...

    def register_discovered(self, registry: DeviceRegistry) -> tuple[Device, ...]:
        devices = []
        for discovery in self.discover():
            device = self.identify(discovery)
            if device.lifecycle is not DeviceLifecycle.IDENTIFIED:
                raise ValueError("identified devices must enter IDENTIFIED lifecycle")
            devices.append(registry.register(device))
        return tuple(devices)


class SimulatedTransport(DeviceTransport):
    def __init__(self, transport_id: str, states: Mapping[str, Mapping[str, Any]]):
        self._descriptor = Transport(
            transport_id=transport_id,
            kind="simulated",
            locator=f"memory://{transport_id}",
        )
        self._states = {key: dict(value) for key, value in states.items()}

    @property
    def descriptor(self) -> Transport:
        return self._descriptor

    def read(self, device: Device) -> Mapping[str, Any]:
        try:
            return dict(self._states[device.stable_identity])
        except KeyError as exc:
            raise LookupError(
                f"simulated device is unavailable: {device.device_id}"
            ) from exc


class SimulatedDeviceProvider(DeviceProvider):
    """Deterministic skeleton for contract testing; not hardware acceptance."""

    provider_id = "apeir.simulated-device"

    def __init__(self, devices: Mapping[str, Mapping[str, Any]]):
        self._definitions = {key: dict(value) for key, value in devices.items()}
        states = {
            key: dict(value.get("state") or {})
            for key, value in self._definitions.items()
        }
        self.transport = SimulatedTransport("simulated-default", states)

    def discover(self) -> tuple[DeviceDiscovery, ...]:
        return tuple(
            DeviceDiscovery(
                provider_id=self.provider_id,
                locator=f"simulated://{stable_identity}",
                hints={
                    "device_type": value.get("device_type", "simulated"),
                    "stable_identity": stable_identity,
                },
            )
            for stable_identity, value in sorted(self._definitions.items())
        )

    def identify(self, discovery: DeviceDiscovery) -> Device:
        if discovery.provider_id != self.provider_id:
            raise ValueError("discovery belongs to another provider")
        if not discovery.locator.startswith("simulated://"):
            raise ValueError("unsupported simulated locator")
        stable_identity = str(discovery.hints.get("stable_identity") or "")
        if not stable_identity:
            raise ValueError("stable identity evidence is required")
        try:
            definition = self._definitions[stable_identity]
        except KeyError as exc:
            raise LookupError("simulated device was not discovered") from exc
        digest = hashlib.sha256(
            f"{self.provider_id}\0{stable_identity}".encode()
        ).hexdigest()[:24]
        return Device(
            device_id=f"device_{digest}",
            provider_id=self.provider_id,
            stable_identity=stable_identity,
            device_type=str(definition.get("device_type") or "simulated"),
            lifecycle=DeviceLifecycle.IDENTIFIED,
            capability_ids=tuple(
                definition.get("capabilities") or ("device.state.read",)
            ),
            transport_ids=(self.transport.descriptor.transport_id,),
            metadata={"simulation": True},
        )

    def read_state(self, device: Device) -> Observation:
        try:
            state = self.transport.read(device)
        except LookupError as exc:
            return Observation.failure(
                "reality.device.read",
                [str(exc)],
                capability="device.state.read",
                metadata={
                    "device_id": device.device_id,
                    "provider_id": self.provider_id,
                },
            )
        return Observation.success(
            "reality.device.read",
            {"device_id": device.device_id, "state": state},
            capability="device.state.read",
            metadata={"device_id": device.device_id, "provider_id": self.provider_id},
        )


__all__ = [
    "DeviceDiscovery",
    "DeviceProvider",
    "DeviceTransport",
    "SimulatedDeviceProvider",
    "SimulatedTransport",
]
