"""Canonical device capability manifest."""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from typing import Any, Mapping

from nous_runtime.core.errors import DeviceError
from nous_runtime.core.events import _timestamp


@dataclass(frozen=True)
class DeviceCapabilityManifest:
    device_id: str
    device_type: str
    capabilities: frozenset[str]
    transport: str = ""
    trust_zone: str = "personal"
    online: bool = True
    battery_percent: float | None = None
    resources: Mapping[str, Any] = field(default_factory=dict)
    metadata: Mapping[str, Any] = field(default_factory=dict)
    observed_at: str = field(default_factory=_timestamp)
    schema_version: str = "1.0"

    def __post_init__(self) -> None:
        if not str(self.device_id).strip():
            raise DeviceError("device_id is required")
        if not str(self.device_type).strip():
            raise DeviceError("device_type is required")
        capabilities = frozenset(
            str(item).strip()
            for item in self.capabilities
            if str(item).strip()
        )
        object.__setattr__(self, "capabilities", capabilities)
        if self.battery_percent is not None:
            battery = float(self.battery_percent)
            if not math.isfinite(battery) or not 0 <= battery <= 100:
                raise DeviceError("battery_percent must be between 0 and 100")
            object.__setattr__(self, "battery_percent", battery)
        object.__setattr__(self, "resources", dict(self.resources))
        object.__setattr__(self, "metadata", dict(self.metadata))

    def supports(self, required: set[str] | frozenset[str]) -> bool:
        return set(required).issubset(self.capabilities)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["capabilities"] = sorted(self.capabilities)
        return data

    @classmethod
    def from_dict(
        cls, data: Mapping[str, Any]
    ) -> "DeviceCapabilityManifest":
        return cls(
            device_id=str(data.get("device_id") or ""),
            device_type=str(data.get("device_type") or ""),
            capabilities=frozenset(data.get("capabilities") or ()),
            transport=str(data.get("transport") or ""),
            trust_zone=str(data.get("trust_zone") or "personal"),
            online=bool(data.get("online", True)),
            battery_percent=(
                float(data["battery_percent"])
                if data.get("battery_percent") is not None
                else None
            ),
            resources=dict(data.get("resources") or {}),
            metadata=dict(data.get("metadata") or {}),
            observed_at=str(data.get("observed_at") or _timestamp()),
            schema_version=str(data.get("schema_version") or "1.0"),
        )


__all__ = ["DeviceCapabilityManifest"]
