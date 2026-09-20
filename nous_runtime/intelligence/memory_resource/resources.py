"""Resource pressure, allocation and graceful degradation algorithms."""

from __future__ import annotations

from dataclasses import asdict

from nous_runtime.intelligence.memory_resource.models import (
    AllocationStatus,
    DegradationDecision,
    DegradationLevel,
    ResourceAllocation,
    ResourceAllocationDecision,
    ResourceDemand,
    ResourcePressure,
    ResourceVector,
)


class ResourcePressureEvaluator:
    def evaluate(
        self,
        capacity: ResourceVector,
        usage: ResourceVector,
    ) -> ResourcePressure:
        ratios = []
        for name, limit in asdict(capacity).items():
            current = asdict(usage)[name]
            if limit > 0:
                ratios.append(current / limit)
        peak = max(ratios, default=0.0)
        if peak >= 0.95:
            return ResourcePressure.CRITICAL
        if peak >= 0.80:
            return ResourcePressure.HIGH
        if peak >= 0.60:
            return ResourcePressure.ELEVATED
        return ResourcePressure.NORMAL


class ResourceDegradationPolicy:
    def decide(
        self,
        pressure: ResourcePressure,
    ) -> DegradationDecision:
        decisions = {
            ResourcePressure.NORMAL: DegradationDecision(
                pressure,
                DegradationLevel.FULL,
                8,
                1.0,
                True,
                False,
                ("capacity_available",),
            ),
            ResourcePressure.ELEVATED: DegradationDecision(
                pressure,
                DegradationLevel.BALANCED,
                4,
                0.8,
                True,
                False,
                ("reduce_parallelism", "trim_context"),
            ),
            ResourcePressure.HIGH: DegradationDecision(
                pressure,
                DegradationLevel.CONSTRAINED,
                2,
                0.5,
                False,
                True,
                (
                    "disable_parallel_models",
                    "prefer_local_execution",
                    "compress_context",
                ),
            ),
            ResourcePressure.CRITICAL: DegradationDecision(
                pressure,
                DegradationLevel.EMERGENCY,
                1,
                0.25,
                False,
                True,
                (
                    "single_worker_only",
                    "minimal_context",
                    "defer_preemptible_work",
                ),
            ),
        }
        return decisions[pressure]


class ResourceAllocator:
    def __init__(
        self,
        *,
        pressure_evaluator: ResourcePressureEvaluator | None = None,
        degradation_policy: ResourceDegradationPolicy | None = None,
    ) -> None:
        self.pressure_evaluator = (
            pressure_evaluator or ResourcePressureEvaluator()
        )
        self.degradation_policy = (
            degradation_policy or ResourceDegradationPolicy()
        )

    def allocate(
        self,
        *,
        capacity: ResourceVector,
        usage: ResourceVector,
        demands: tuple[ResourceDemand, ...],
    ) -> ResourceAllocationDecision:
        if not usage.fits(capacity):
            remaining = ResourceVector()
        else:
            remaining = capacity.subtract(usage)
        pressure = self.pressure_evaluator.evaluate(capacity, usage)
        degradation = self.degradation_policy.decide(pressure)
        allocations = []
        ordered = sorted(
            demands,
            key=lambda item: (
                -max(0, min(100, item.priority)),
                item.task_id,
            ),
        )
        for demand in ordered:
            if (
                pressure is ResourcePressure.CRITICAL
                and demand.preemptible
                and demand.priority < 80
            ):
                allocations.append(
                    ResourceAllocation(
                        demand.task_id,
                        AllocationStatus.DEFERRED,
                        ResourceVector(),
                        demand.priority,
                        "critical_pressure_preemption",
                    )
                )
                continue
            if demand.preferred.fits(remaining):
                allocated = demand.preferred
                status = AllocationStatus.ALLOCATED
                reason = "preferred_resources_available"
            elif demand.minimum.fits(remaining):
                allocated = demand.minimum
                status = AllocationStatus.DEGRADED
                reason = "minimum_resources_only"
            else:
                allocations.append(
                    ResourceAllocation(
                        demand.task_id,
                        AllocationStatus.DEFERRED,
                        ResourceVector(),
                        demand.priority,
                        "minimum_resources_unavailable",
                    )
                )
                continue
            remaining = remaining.subtract(allocated)
            allocations.append(
                ResourceAllocation(
                    demand.task_id,
                    status,
                    allocated,
                    demand.priority,
                    reason,
                )
            )
        return ResourceAllocationDecision(
            allocations=tuple(allocations),
            remaining=remaining,
            pressure=pressure,
            degradation=degradation,
        )


__all__ = [
    "ResourceAllocator",
    "ResourceDegradationPolicy",
    "ResourcePressureEvaluator",
]
