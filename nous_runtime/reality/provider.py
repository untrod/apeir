"""Device-provider boundary and deterministic stateful Reality simulation."""

from __future__ import annotations

import hashlib
import copy
import json
import os
import threading
import time
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Mapping

from nous_runtime.planner.observation import Observation
from nous_runtime.reality.contracts import Device, DeviceLifecycle, Transport
from nous_runtime.reality.registry import DeviceRegistry
from nous_runtime.security.private_files import restrict_owner_only_file


@dataclass(frozen=True)
class DeviceDiscovery:
    provider_id: str
    locator: str
    hints: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.provider_id.strip() or not self.locator.strip():
            raise ValueError("provider_id and locator are required")
        object.__setattr__(self, "hints", dict(self.hints))


class SimulationFault(str, Enum):
    """Deterministic faults consumed in the order they are injected."""

    DEVICE_DISCONNECT = "device_disconnect"
    OPERATION_FAILURE = "operation_failure"
    DELAYED_RESULT = "delayed_result"
    DUPLICATE_OBSERVATION = "duplicate_observation"
    STALE_OBSERVATION = "stale_observation"
    DUPLICATE_RECEIPT = "duplicate_receipt"
    LOST_RESPONSE = "lost_response"
    EFFECT_THEN_RESPONSE_LOST = "effect_then_response_lost"


class SimulatedResponseLost(ConnectionError):
    """Signal that a simulated Node response must be dropped after execution."""

    def __init__(
        self,
        message: str,
        *,
        effect_applied: bool,
        output: Mapping[str, Any],
    ):
        super().__init__(message)
        self.effect_applied = effect_applied
        self.output = dict(output)


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
        self._connected = {key: True for key in states}

    @property
    def descriptor(self) -> Transport:
        return self._descriptor

    def read(self, device: Device) -> Mapping[str, Any]:
        if not self._connected.get(device.stable_identity, False):
            raise LookupError(f"simulated device is unavailable: {device.device_id}")
        try:
            return dict(self._states[device.stable_identity])
        except KeyError as exc:
            raise LookupError(
                f"simulated device is unavailable: {device.device_id}"
            ) from exc

    def replace_state(self, stable_identity: str, state: Mapping[str, Any]) -> None:
        self._states[stable_identity] = dict(state)

    def set_connected(self, stable_identity: str, connected: bool) -> None:
        if stable_identity not in self._states:
            raise LookupError(f"unknown simulated device: {stable_identity}")
        self._connected[stable_identity] = connected


class SimulatedDeviceProvider(DeviceProvider):
    """Deterministic, persistent simulator; never evidence of physical hardware."""

    provider_id = "apeir.simulated-device"

    def __init__(
        self,
        devices: Mapping[str, Mapping[str, Any]],
        *,
        state_dir: str | Path | None = None,
    ):
        self._definitions = {key: dict(value) for key, value in devices.items()}
        self._path = (
            Path(state_dir).expanduser().resolve() / "simulated-reality-state.json"
            if state_dir is not None
            else None
        )
        self._lock = threading.RLock()
        self._states = {
            key: dict(value.get("state") or {})
            for key, value in self._definitions.items()
        }
        self._previous_states = {
            key: dict(value) for key, value in self._states.items()
        }
        self._connected = {key: True for key in self._definitions}
        self._revisions = {key: 0 for key in self._definitions}
        self._last_operations = {key: "" for key in self._definitions}
        self._operation_results: dict[str, dict[str, Any]] = {}
        self._execution_counts: dict[str, int] = {}
        self._faults: dict[str, list[dict[str, Any]]] = {
            key: [] for key in self._definitions
        }
        self._last_observations: dict[str, dict[str, Any]] = {}
        self._load()
        self.transport = SimulatedTransport("simulated-default", self._states)
        for key, connected in self._connected.items():
            self.transport.set_connected(key, connected)

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
            if self._connected.get(stable_identity, False)
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
                definition.get("capabilities")
                or ("device.state.read", "device.state.set")
            ),
            transport_ids=(self.transport.descriptor.transport_id,),
            metadata={"simulation": True},
        )

    def read_state(self, device: Device, *, acquisition_id: str = "") -> Observation:
        with self._lock:
            fault = self._consume_observation_fault(device.stable_identity)
            if fault is SimulationFault.DUPLICATE_OBSERVATION:
                prior = self._last_observations.get(device.stable_identity)
                if prior is not None:
                    return Observation(**prior)
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
            stale = fault is SimulationFault.STALE_OBSERVATION
            if stale:
                state = dict(self._previous_states[device.stable_identity])
            observation = Observation.success(
                "reality.device.read",
                {"device_id": device.device_id, "state": state},
                capability="device.state.read",
                metadata={
                    "device_id": device.device_id,
                    "provider_id": self.provider_id,
                    "state_revision": max(
                        0, self._revisions[device.stable_identity] - int(stale)
                    ),
                    "last_operation_id": self._last_operations[device.stable_identity],
                    "stale": stale,
                    "simulation": True,
                    "acquisition_id": acquisition_id,
                },
            )
            self._last_observations[device.stable_identity] = observation.to_dict()
            self._save()
            return observation

    @staticmethod
    def validate_firmware_mutation(mutation) -> None:
        import re

        if not isinstance(mutation, Mapping) or set(mutation) != {"state"}:
            raise ValueError("Firmware mutation requires only a semantic version")
        state = mutation["state"]
        if (
            not isinstance(state, Mapping)
            or set(state) != {"firmware_version"}
            or not re.fullmatch(r"\d+\.\d+\.\d+", str(state["firmware_version"]))
        ):
            raise ValueError("Firmware mutation requires only a semantic version")

    def apply_operation(
        self,
        device: Device,
        *,
        operation_id: str,
        capability_id: str,
        mutation: Mapping[str, Any],
        before_effect=None,
    ) -> dict[str, Any]:
        """Apply one controlled state update with durable operation idempotency."""
        if capability_id not in {"device.state.set", "device.firmware.update"}:
            raise ValueError("simulator does not support this mutating capability")
        if capability_id == "device.firmware.update":
            self.validate_firmware_mutation(mutation)
        if capability_id not in device.capability_ids:
            raise PermissionError("device does not expose the requested capability")
        if (
            device.provider_id != self.provider_id
            or device.lifecycle is not DeviceLifecycle.AVAILABLE
        ):
            raise PermissionError(
                "device provider or lifecycle does not authorize mutation"
            )
        if not operation_id.strip():
            raise ValueError("operation_id is required")
        stable = device.stable_identity
        request_digest = hashlib.sha256(
            json.dumps(
                {
                    "device_id": device.device_id,
                    "capability_id": capability_id,
                    "mutation": dict(mutation),
                },
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            ).encode()
        ).hexdigest()
        with self._lock:
            existing = self._operation_results.get(operation_id)
            if existing is not None:
                if existing.get("request_digest") != request_digest:
                    raise ValueError("simulated Operation idempotency binding changed")
                return copy.deepcopy(existing)
            fault, options = self._consume_operation_fault(stable)
            if fault is SimulationFault.DEVICE_DISCONNECT:
                self._set_connected(stable, False)
                raise LookupError(
                    f"simulated device is unavailable: {device.device_id}"
                )
            if not self._connected.get(stable, False):
                raise LookupError(
                    f"simulated device is unavailable: {device.device_id}"
                )
            if fault is SimulationFault.DELAYED_RESULT:
                time.sleep(float(options.get("delay_seconds") or 0.01))
            if fault is SimulationFault.OPERATION_FAILURE:
                raise RuntimeError("injected simulated operation failure")
            if fault is SimulationFault.LOST_RESPONSE:
                raise SimulatedResponseLost(
                    "injected response loss before device effect",
                    effect_applied=False,
                    output={
                        "operation_id": operation_id,
                        "device_id": device.device_id,
                        "effect_applied": False,
                    },
                )
            update = mutation.get("state", mutation)
            if not isinstance(update, Mapping) or not update:
                raise ValueError("state mutation must be a non-empty object")
            if any(not isinstance(key, str) or not key for key in update):
                raise ValueError("state mutation keys must be non-empty strings")
            if before_effect is not None:
                before_effect()
            self._previous_states[stable] = dict(self._states[stable])
            self._states[stable].update(dict(update))
            self.transport.replace_state(stable, self._states[stable])
            self._revisions[stable] += 1
            self._last_operations[stable] = operation_id
            self._execution_counts[operation_id] = (
                self._execution_counts.get(operation_id, 0) + 1
            )
            result = {
                "schema": "apeir.simulated-device-operation/v1",
                "operation_id": operation_id,
                "request_digest": request_digest,
                "device_id": device.device_id,
                "capability_id": capability_id,
                "state_revision": self._revisions[stable],
                "effect_applied": True,
                "state": dict(self._states[stable]),
                "duplicate_receipt": fault is SimulationFault.DUPLICATE_RECEIPT,
            }
            self._operation_results[operation_id] = result
            self._save()
            if fault is SimulationFault.EFFECT_THEN_RESPONSE_LOST:
                raise SimulatedResponseLost(
                    "injected response loss after device effect",
                    effect_applied=True,
                    output=result,
                )
            return copy.deepcopy(result)

    def inject_fault(
        self,
        stable_identity: str,
        fault: SimulationFault,
        *,
        occurrences: int = 1,
        delay_seconds: float = 0.01,
    ) -> None:
        if stable_identity not in self._definitions:
            raise LookupError(f"unknown simulated device: {stable_identity}")
        if occurrences < 1:
            raise ValueError("fault occurrences must be positive")
        if not 0 <= delay_seconds <= 5:
            raise ValueError("fault delay must be between zero and five seconds")
        with self._lock:
            self._faults[stable_identity].extend(
                {"fault": fault.value, "delay_seconds": delay_seconds}
                for _ in range(occurrences)
            )
            self._save()

    def disconnect(
        self, stable_identity: str, *, registry: DeviceRegistry | None = None
    ) -> Device | None:
        with self._lock:
            self._set_connected(stable_identity, False)
        if registry is None:
            return None
        device = self._registered_device(stable_identity, registry)
        if device.lifecycle is DeviceLifecycle.REVOKED:
            return device
        return registry.transition(device.device_id, DeviceLifecycle.OFFLINE)

    def reconnect(
        self, stable_identity: str, *, registry: DeviceRegistry | None = None
    ) -> Device | None:
        with self._lock:
            self._set_connected(stable_identity, True)
        if registry is None:
            return None
        device = self._registered_device(stable_identity, registry)
        return registry.reconnect(device.device_id)

    def execution_count(self, operation_id: str) -> int:
        return self._execution_counts.get(operation_id, 0)

    def operation_result(self, operation_id: str) -> dict[str, Any] | None:
        value = self._operation_results.get(operation_id)
        return dict(value) if value is not None else None

    def _registered_device(
        self, stable_identity: str, registry: DeviceRegistry
    ) -> Device:
        device = self.identify(
            DeviceDiscovery(
                self.provider_id,
                f"simulated://{stable_identity}",
                {"stable_identity": stable_identity},
            )
        )
        registered = registry.get(device.device_id)
        if registered is None:
            raise KeyError(f"device not registered: {device.device_id}")
        return registered

    def _set_connected(self, stable_identity: str, connected: bool) -> None:
        if stable_identity not in self._definitions:
            raise LookupError(f"unknown simulated device: {stable_identity}")
        self._connected[stable_identity] = connected
        self.transport.set_connected(stable_identity, connected)
        self._save()

    def _consume_observation_fault(
        self, stable_identity: str
    ) -> SimulationFault | None:
        queue = self._faults[stable_identity]
        if not queue:
            return None
        fault = SimulationFault(str(queue[0]["fault"]))
        if fault not in {
            SimulationFault.DUPLICATE_OBSERVATION,
            SimulationFault.STALE_OBSERVATION,
        }:
            return None
        queue.pop(0)
        self._save()
        return fault

    def _consume_operation_fault(
        self, stable_identity: str
    ) -> tuple[SimulationFault | None, dict[str, Any]]:
        queue = self._faults[stable_identity]
        if not queue:
            return None, {}
        fault = SimulationFault(str(queue[0]["fault"]))
        if fault in {
            SimulationFault.DUPLICATE_OBSERVATION,
            SimulationFault.STALE_OBSERVATION,
        }:
            return None, {}
        value = dict(queue.pop(0))
        self._save()
        return fault, value

    def _load(self) -> None:
        if self._path is None or not self._path.is_file():
            return
        value = json.loads(self._path.read_text(encoding="utf-8"))
        if value.get("schema") != "apeir.simulated-reality-state/v1":
            raise ValueError("simulated Reality state schema is invalid")
        identities = set(self._definitions)
        if set(value.get("states") or {}) != identities:
            raise ValueError("simulated Reality device definitions changed")
        self._states = {key: dict(item) for key, item in value["states"].items()}
        self._previous_states = {
            key: dict(item)
            for key, item in (value.get("previous_states") or value["states"]).items()
        }
        self._connected = {
            key: bool(item) for key, item in value.get("connected", {}).items()
        }
        self._revisions = {
            key: int(item) for key, item in value.get("revisions", {}).items()
        }
        self._last_operations = {
            key: str(item) for key, item in value.get("last_operations", {}).items()
        }
        self._operation_results = {
            key: dict(item) for key, item in value.get("operation_results", {}).items()
        }
        self._execution_counts = {
            key: int(item) for key, item in value.get("execution_counts", {}).items()
        }
        self._faults = {
            key: [dict(item) for item in value.get("faults", {}).get(key, [])]
            for key in identities
        }
        self._last_observations = {
            key: dict(item) for key, item in value.get("last_observations", {}).items()
        }

    def _save(self) -> None:
        if self._path is None:
            return
        self._path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self._path.with_name(f"{self._path.name}.{uuid.uuid4().hex}.tmp")
        value = {
            "schema": "apeir.simulated-reality-state/v1",
            "states": self._states,
            "previous_states": self._previous_states,
            "connected": self._connected,
            "revisions": self._revisions,
            "last_operations": self._last_operations,
            "operation_results": self._operation_results,
            "execution_counts": self._execution_counts,
            "faults": self._faults,
            "last_observations": self._last_observations,
        }
        try:
            with temporary.open("x", encoding="utf-8") as handle:
                json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            restrict_owner_only_file(temporary, subject="simulated Reality state")
            os.replace(temporary, self._path)
        finally:
            temporary.unlink(missing_ok=True)


__all__ = [
    "DeviceDiscovery",
    "DeviceProvider",
    "DeviceTransport",
    "SimulatedDeviceProvider",
    "SimulatedResponseLost",
    "SimulatedTransport",
    "SimulationFault",
]
