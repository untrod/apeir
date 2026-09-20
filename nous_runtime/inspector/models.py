# -*- coding: utf-8 -*-
"""Read-only inspector snapshot models."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal


Severity = Literal["info", "warning", "error", "critical"]


@dataclass
class DiagnosticFinding:
    code: str
    severity: Severity
    component: str
    message: str
    remediation: str = ""
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class RuntimeSnapshot:
    version: str = ""
    running: bool = False
    demo_mode: bool = False
    providers: int = 0
    capabilities: int = 0
    devices: int = 0
    jobs_pending: int = 0
    workspace: str = ""
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ProviderSnapshot:
    provider_id: str
    name: str = ""
    status: str = "unknown"
    capabilities: list[str] = field(default_factory=list)
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class CapabilitySnapshot:
    capability_id: str
    provider_id: str = ""
    category: str = ""
    risk: str = ""
    available: bool = False
    reason: str = ""
    description: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class TaskSnapshot:
    task_id: str
    status: str = "pending"
    title: str = ""
    description: str = ""
    capability_id: str = ""
    provider_id: str = ""
    plan_id: str = ""
    depends_on: list[str] = field(default_factory=list)
    observation_ids: list[str] = field(default_factory=list)
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class PlanSnapshot:
    plan_id: str
    goal_id: str = ""
    status: str = ""
    task_ids: list[str] = field(default_factory=list)
    progress: dict[str, int] = field(default_factory=dict)
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ObservationSnapshot:
    observation_id: str
    status: str = ""
    task_id: str = ""
    capability_id: str = ""
    provider_id: str = ""
    memory_id: str = ""
    record_type: str = ""
    summary: str = ""
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class MemorySnapshot:
    workspace: str = ""
    stream_counts: dict[str, int] = field(default_factory=dict)
    missing_streams: list[str] = field(default_factory=list)
    invalid_records: list[dict[str, Any]] = field(default_factory=list)
    active_facts: int = 0
    stable_key_conflicts: list[dict[str, Any]] = field(default_factory=list)
    broken_supersedes: list[dict[str, Any]] = field(default_factory=list)
    supersedes_cycles: list[dict[str, Any]] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class DeviceSnapshot:
    device_id: str
    name: str = ""
    device_type: str = "unknown"
    online: bool = False
    capabilities: list[str] = field(default_factory=list)
    last_seen: str = ""
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class InspectorSnapshot:
    runtime: RuntimeSnapshot
    providers: list[ProviderSnapshot] = field(default_factory=list)
    capabilities: list[CapabilitySnapshot] = field(default_factory=list)
    tasks: list[TaskSnapshot] = field(default_factory=list)
    plans: list[PlanSnapshot] = field(default_factory=list)
    observations: list[ObservationSnapshot] = field(default_factory=list)
    memory: MemorySnapshot = field(default_factory=MemorySnapshot)
    devices: list[DeviceSnapshot] = field(default_factory=list)
    findings: list[DiagnosticFinding] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "runtime": self.runtime.to_dict(),
            "providers": [p.to_dict() for p in self.providers],
            "capabilities": [c.to_dict() for c in self.capabilities],
            "tasks": [t.to_dict() for t in self.tasks],
            "plans": [p.to_dict() for p in self.plans],
            "observations": [o.to_dict() for o in self.observations],
            "memory": self.memory.to_dict(),
            "devices": [d.to_dict() for d in self.devices],
            "findings": [f.to_dict() for f in self.findings],
        }
