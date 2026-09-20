import pytest

from nous_runtime.intelligence.memory_resource import (
    AllocationStatus,
    DegradationLevel,
    InvalidResourceVectorError,
    ResourceAllocator,
    ResourceDemand,
    ResourcePressure,
    ResourcePressureEvaluator,
    ResourceVector,
)


def vector(
    cpu=0,
    memory=0,
    slots=0,
    cost=0,
):
    return ResourceVector(
        cpu_units=cpu,
        memory_mb=memory,
        concurrency_slots=slots,
        cost_usd=cost,
    )


def test_resource_vector_validation_and_fit() -> None:
    with pytest.raises(InvalidResourceVectorError):
        vector(cpu=-1)
    assert vector(cpu=1, memory=100).fits(vector(cpu=2, memory=200))
    assert not vector(cpu=3).fits(vector(cpu=2))


@pytest.mark.parametrize(
    "usage,expected",
    [
        (0.2, ResourcePressure.NORMAL),
        (0.6, ResourcePressure.ELEVATED),
        (0.8, ResourcePressure.HIGH),
        (0.95, ResourcePressure.CRITICAL),
    ],
)
def test_pressure_uses_peak_resource_ratio(usage, expected) -> None:
    result = ResourcePressureEvaluator().evaluate(
        vector(cpu=10, memory=1000),
        vector(cpu=10 * usage, memory=100),
    )
    assert result is expected


def test_allocator_prefers_high_priority_and_degrades_when_needed() -> None:
    decision = ResourceAllocator().allocate(
        capacity=vector(cpu=4, memory=400, slots=2, cost=4),
        usage=vector(),
        demands=(
            ResourceDemand(
                "low",
                minimum=vector(cpu=1, memory=100, slots=1, cost=1),
                preferred=vector(cpu=3, memory=300, slots=2, cost=3),
                priority=10,
            ),
            ResourceDemand(
                "high",
                minimum=vector(cpu=1, memory=100, slots=1, cost=1),
                preferred=vector(cpu=2, memory=200, slots=1, cost=2),
                priority=90,
            ),
        ),
    )

    assert [item.task_id for item in decision.allocations] == ["high", "low"]
    assert [item.status for item in decision.allocations] == [
        AllocationStatus.ALLOCATED,
        AllocationStatus.DEGRADED,
    ]
    assert decision.remaining == vector(cpu=1, memory=100, cost=1)


def test_allocator_defers_when_minimum_is_unavailable() -> None:
    demand = ResourceDemand(
        "large",
        minimum=vector(cpu=2),
        preferred=vector(cpu=4),
    )
    decision = ResourceAllocator().allocate(
        capacity=vector(cpu=1),
        usage=vector(),
        demands=(demand,),
    )

    assert decision.allocations[0].status is AllocationStatus.DEFERRED
    assert decision.allocations[0].reason == "minimum_resources_unavailable"


def test_critical_pressure_defers_preemptible_nonurgent_work() -> None:
    decision = ResourceAllocator().allocate(
        capacity=vector(cpu=10, memory=100),
        usage=vector(cpu=9.5, memory=10),
        demands=(
            ResourceDemand(
                "background",
                minimum=vector(cpu=0.1),
                preferred=vector(cpu=0.2),
                priority=20,
                preemptible=True,
            ),
        ),
    )

    assert decision.pressure is ResourcePressure.CRITICAL
    assert decision.degradation.level is DegradationLevel.EMERGENCY
    assert decision.allocations[0].reason == "critical_pressure_preemption"


def test_pressure_degradation_is_explainable() -> None:
    decision = ResourceAllocator().allocate(
        capacity=vector(cpu=10),
        usage=vector(cpu=8),
        demands=(),
    )

    assert decision.degradation.level is DegradationLevel.CONSTRAINED
    assert not decision.degradation.allow_parallel_models
    assert "compress_context" in decision.degradation.explanation
