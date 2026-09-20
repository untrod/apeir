"""Unified Memory and Resource Intelligence decision facade."""

from __future__ import annotations

from datetime import datetime

from nous_runtime.intelligence.memory_resource.memory import (
    MemoryCandidate,
    MemoryIntelligence,
)
from nous_runtime.intelligence.memory_resource.models import (
    MemoryResourceDecision,
    ResourceDemand,
    ResourceVector,
)
from nous_runtime.intelligence.memory_resource.resources import ResourceAllocator


class MemoryResourceIntelligence:
    def __init__(
        self,
        *,
        memory: MemoryIntelligence | None = None,
        resources: ResourceAllocator | None = None,
    ) -> None:
        self.memory = memory or MemoryIntelligence()
        self.resources = resources or ResourceAllocator()

    def decide(
        self,
        *,
        memories: tuple[MemoryCandidate, ...],
        token_budget: int,
        capacity: ResourceVector,
        usage: ResourceVector,
        demands: tuple[ResourceDemand, ...],
        now: datetime | None = None,
    ) -> MemoryResourceDecision:
        memory_decision = self.memory.select(
            memories,
            token_budget=token_budget,
            now=now,
        )
        resource_decision = self.resources.allocate(
            capacity=capacity,
            usage=usage,
            demands=demands,
        )
        return MemoryResourceDecision(
            memory=memory_decision,
            resources=resource_decision,
            explanation=(
                f"memory_tokens={memory_decision.tokens_used}/{token_budget}",
                f"resource_pressure={resource_decision.pressure.value}",
                f"degradation={resource_decision.degradation.level.value}",
            ),
        )


__all__ = ["MemoryResourceIntelligence"]
