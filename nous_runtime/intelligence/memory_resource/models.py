"""Contracts shared by memory and resource intelligence."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Mapping

from nous_runtime.intelligence.memory_resource.errors import (
    InvalidResourceVectorError,
)


class RetentionAction(str, Enum):
    PIN = "pin"
    KEEP = "keep"
    COMPRESS = "compress"
    EVICT = "evict"
    REJECT = "reject"


class AllocationStatus(str, Enum):
    ALLOCATED = "allocated"
    DEGRADED = "degraded"
    DEFERRED = "deferred"


class ResourcePressure(str, Enum):
    NORMAL = "normal"
    ELEVATED = "elevated"
    HIGH = "high"
    CRITICAL = "critical"


class DegradationLevel(str, Enum):
    FULL = "full"
    BALANCED = "balanced"
    CONSTRAINED = "constrained"
    EMERGENCY = "emergency"


@dataclass(frozen=True)
class MemoryValueBreakdown:
    relevance: float
    confidence: float
    importance: float
    freshness: float
    utility: float
    frequency: float
    token_penalty: float
    sensitivity_penalty: float
    score: float
    explanation: tuple[str, ...] = ()


@dataclass(frozen=True)
class MemorySelection:
    memory_id: str
    action: RetentionAction
    token_allocation: int
    breakdown: MemoryValueBreakdown
    reason: str


@dataclass(frozen=True)
class MemorySelectionDecision:
    selected: tuple[MemorySelection, ...]
    rejected: tuple[MemorySelection, ...]
    token_budget: int
    tokens_used: int
    policy_version: str


@dataclass(frozen=True)
class ResourceVector:
    cpu_units: float = 0.0
    memory_mb: int = 0
    disk_mb: int = 0
    network_mbps: float = 0.0
    accelerator_units: float = 0.0
    concurrency_slots: int = 0
    cost_usd: float = 0.0

    def __post_init__(self) -> None:
        if any(
            value < 0
            for value in (
                self.cpu_units,
                self.memory_mb,
                self.disk_mb,
                self.network_mbps,
                self.accelerator_units,
                self.concurrency_slots,
                self.cost_usd,
            )
        ):
            raise InvalidResourceVectorError(
                "resource vector values must be non-negative"
            )

    def add(self, other: "ResourceVector") -> "ResourceVector":
        return ResourceVector(
            cpu_units=self.cpu_units + other.cpu_units,
            memory_mb=self.memory_mb + other.memory_mb,
            disk_mb=self.disk_mb + other.disk_mb,
            network_mbps=self.network_mbps + other.network_mbps,
            accelerator_units=self.accelerator_units + other.accelerator_units,
            concurrency_slots=self.concurrency_slots + other.concurrency_slots,
            cost_usd=self.cost_usd + other.cost_usd,
        )

    def subtract(self, other: "ResourceVector") -> "ResourceVector":
        return ResourceVector(
            cpu_units=max(0.0, self.cpu_units - other.cpu_units),
            memory_mb=max(0, self.memory_mb - other.memory_mb),
            disk_mb=max(0, self.disk_mb - other.disk_mb),
            network_mbps=max(0.0, self.network_mbps - other.network_mbps),
            accelerator_units=max(
                0.0,
                self.accelerator_units - other.accelerator_units,
            ),
            concurrency_slots=max(
                0,
                self.concurrency_slots - other.concurrency_slots,
            ),
            cost_usd=max(0.0, self.cost_usd - other.cost_usd),
        )

    def fits(self, capacity: "ResourceVector") -> bool:
        return all(
            current <= limit
            for current, limit in zip(
                asdict(self).values(),
                asdict(capacity).values(),
                strict=True,
            )
        )


@dataclass(frozen=True)
class ResourceDemand:
    task_id: str
    minimum: ResourceVector
    preferred: ResourceVector
    priority: int = 50
    preemptible: bool = True
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ResourceAllocation:
    task_id: str
    status: AllocationStatus
    allocated: ResourceVector
    priority: int
    reason: str


@dataclass(frozen=True)
class DegradationDecision:
    pressure: ResourcePressure
    level: DegradationLevel
    max_parallelism: int
    context_token_ratio: float
    allow_parallel_models: bool
    prefer_local_execution: bool
    explanation: tuple[str, ...]


@dataclass(frozen=True)
class ResourceAllocationDecision:
    allocations: tuple[ResourceAllocation, ...]
    remaining: ResourceVector
    pressure: ResourcePressure
    degradation: DegradationDecision


@dataclass(frozen=True)
class MemoryResourceDecision:
    memory: MemorySelectionDecision
    resources: ResourceAllocationDecision
    explanation: tuple[str, ...]
    policy_version: str = "1.0.0"


__all__ = [
    "AllocationStatus",
    "DegradationDecision",
    "DegradationLevel",
    "MemoryResourceDecision",
    "MemorySelection",
    "MemorySelectionDecision",
    "MemoryValueBreakdown",
    "ResourceAllocation",
    "ResourceAllocationDecision",
    "ResourceDemand",
    "ResourcePressure",
    "ResourceVector",
    "RetentionAction",
]
