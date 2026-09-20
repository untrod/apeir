import time

import pytest

from nous_runtime.context import build_execution_context
from nous_runtime.intelligence.adaptive import AdaptiveRoutingEngine
from nous_runtime.intelligence.routing import RoutingDecision, route_capabilities
from nous_runtime.intelligence.scoring import NoEligibleModelError, RoutingConstraints
from nous_runtime.intelligence.task import analyze_task
from nous_runtime.intelligence.task.models import TaskAnalysis
from nous_runtime.model import ModelProfile, ModelRegistry, default_model_registry
from nous_runtime.task import Task


def test_legacy_routing_decision_serialization_is_unchanged() -> None:
    decision = RoutingDecision("task", ("a", "b"), "a", "legacy", 0.7)

    assert decision.to_dict() == {
        "task_id": "task",
        "candidate_models": ["a", "b"],
        "selected_model": "a",
        "reason": "legacy",
        "score": 0.7,
    }
    assert RoutingDecision.from_dict(decision.to_dict()).selected_model == "a"


def test_adaptive_decision_has_explainable_fields() -> None:
    decision = route_capabilities(
        analyze_task("Write Python code", task_id="code"),
        registry=default_model_registry(),
        mode="adaptive",
    )

    assert decision.decision_id.startswith("route_")
    assert decision.selected_model_id
    assert decision.ranked_candidates
    assert all(
        not candidate.eligible or candidate.breakdown is not None
        for candidate in decision.ranked_candidates
    )
    assert decision.strategy is not None
    assert 0 <= decision.confidence <= 1
    assert decision.policy_version
    assert decision.observability["eligible_count"] >= 1


def test_adaptive_decision_round_trip() -> None:
    original = route_capabilities(
        analyze_task("Prove a math equation", task_id="math"),
        mode="adaptive",
    )

    restored = RoutingDecision.from_dict(original.to_dict())

    assert restored.selected_model_id == original.selected_model_id
    assert restored.strategy.strategy == original.strategy.strategy
    assert restored.ranked_candidates[0].model_id == original.ranked_candidates[0].model_id


def test_routing_modes_keep_legacy_available() -> None:
    analysis = analyze_task("Write Python code", task_id="code")

    legacy = route_capabilities(analysis, mode="legacy")
    automatic = route_capabilities(analysis, mode="auto")

    assert legacy.routing_mode == ""
    assert legacy.decision_id == ""
    assert automatic.routing_mode == "adaptive"


def test_auto_mode_safely_falls_back_when_profiles_are_unavailable() -> None:
    decision = route_capabilities(
        analyze_task("General reasoning", task_id="empty"),
        registry=ModelRegistry(),
        mode="auto",
    )

    assert decision.routing_mode == "auto"
    assert decision.fallback_reason == "no model profiles available"


def test_hard_constraints_are_not_ignored_by_auto_mode() -> None:
    constraints = RoutingConstraints(
        required_capabilities=frozenset({"nonexistent_capability"})
    )

    with pytest.raises(NoEligibleModelError):
        route_capabilities(
            analyze_task("General reasoning", task_id="none"),
            constraints=constraints,
            mode="auto",
        )


def test_same_input_has_deterministic_ranking() -> None:
    analysis = analyze_task("Write Python code", task_id="code")
    first = route_capabilities(analysis, mode="adaptive")
    second = route_capabilities(analysis, mode="adaptive")

    assert first.selected_model_id == second.selected_model_id
    assert [item.model_id for item in first.ranked_candidates] == [
        item.model_id for item in second.ranked_candidates
    ]
    assert [item.score for item in first.ranked_candidates] == [
        item.score for item in second.ranked_candidates
    ]


def test_execution_context_accepts_routing_decision() -> None:
    task = Task(id="task-1", name="Code")
    decision = route_capabilities(analyze_task(task), mode="adaptive")

    context = build_execution_context(task, routing_decision=decision)

    assert (
        context.metadata["routing_decision"]["decision_id"]
        == decision.decision_id
    )
    assert task.status.value == "CREATED"


def test_unknown_cold_start_model_remains_eligible() -> None:
    registry = ModelRegistry(
        [ModelProfile("new-model", "new-provider", ("reasoning",))]
    )

    decision = route_capabilities(
        analyze_task("General reasoning", task_id="new"),
        registry=registry,
        mode="adaptive",
    )

    assert decision.selected_model_id == "new-model"
    assert decision.score > 0
    assert decision.confidence > 0


def test_100_candidates_route_in_memory_without_io() -> None:
    dimensions = (
        "reasoning",
        "coding",
        "mathematics",
        "language",
        "vision",
        "audio",
        "long_context",
        "structured_output",
        "tool_use",
        "planning",
        "retrieval",
        "verification",
        "instruction_following",
        "speed",
        "cost_efficiency",
        "reliability",
        "privacy",
        "local_execution",
        "custom_a",
        "custom_b",
    )
    profiles = [
        ModelProfile(
            f"model-{index:03d}",
            f"provider-{index % 5}",
            dimensions,
            reasoning_score=0.4 + (index % 50) / 100,
            reliability_score=0.5 + (index % 40) / 100,
            sample_count={"reasoning": index},
            confidence={"reasoning": 0.6},
            estimated_cost=float(index % 10),
            latency_ms=500 + index,
        )
        for index in range(100)
    ]
    started = time.perf_counter()

    decision = AdaptiveRoutingEngine().route(
        TaskAnalysis(
            task_id="perf",
            task_type="benchmark",
            complexity="medium",
            required_capabilities=dimensions,
            constraints={},
            metadata={},
        ),
        profiles,
    )

    assert time.perf_counter() - started < 1.0
    assert len(decision.ranked_candidates) == 100
