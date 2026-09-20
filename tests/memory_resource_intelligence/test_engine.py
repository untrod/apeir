from nous_runtime.intelligence.memory_resource import (
    MemoryCandidate,
    MemoryResourceIntelligence,
    ResourceDemand,
    ResourceVector,
)


def test_unified_decision_connects_memory_and_resource_policy() -> None:
    result = MemoryResourceIntelligence().decide(
        memories=(
            MemoryCandidate(
                "memory",
                "important",
                relevance=1,
                confidence=1,
                importance=1,
                token_estimate=10,
            ),
        ),
        token_budget=20,
        capacity=ResourceVector(cpu_units=4, concurrency_slots=2),
        usage=ResourceVector(cpu_units=1),
        demands=(
            ResourceDemand(
                "task",
                minimum=ResourceVector(
                    cpu_units=1,
                    concurrency_slots=1,
                ),
                preferred=ResourceVector(
                    cpu_units=2,
                    concurrency_slots=1,
                ),
            ),
        ),
    )

    assert result.memory.selected[0].memory_id == "memory"
    assert result.resources.allocations[0].task_id == "task"
    assert result.explanation[0] == "memory_tokens=10/20"
