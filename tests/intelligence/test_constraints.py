import pytest

from nous_runtime.intelligence.adaptive import AdaptiveRoutingEngine
from nous_runtime.intelligence.scoring import (
    NoEligibleModelError,
    RoutingConstraints,
    build_model_vector,
    evaluate_constraints,
)
from nous_runtime.intelligence.task import analyze_task
from nous_runtime.model import ModelProfile


def candidate(**overrides) -> ModelProfile:
    values = {
        "model_id": "candidate",
        "provider": "provider-a",
        "capabilities": ("reasoning", "vision", "local_execution"),
        "privacy_level": "local",
        "context_window": 16_000,
        "supports_tools": True,
        "supports_structured_output": True,
        "estimated_cost": 2.0,
        "latency_ms": 500,
    }
    values.update(overrides)
    return ModelProfile(**values)


def test_matching_candidate_is_eligible() -> None:
    profile = candidate()
    result = evaluate_constraints(
        profile,
        build_model_vector(profile),
        RoutingConstraints(
            required_capabilities=frozenset({"reasoning", "vision"}),
            max_cost=3.0,
            max_latency_ms=1_000,
            min_context_window=8_000,
            requires_tools=True,
            requires_local_execution=True,
            requires_structured_output=True,
            privacy_level="local",
        ),
    )

    assert result.eligible
    assert result.rejection_reasons == ()


def test_hard_constraints_keep_specific_rejection_reasons() -> None:
    profile = candidate(
        capabilities=("reasoning",),
        privacy_level="cloud",
        context_window=2_000,
        supports_tools=False,
        estimated_cost=8.0,
        latency_ms=4_000,
    )
    result = evaluate_constraints(
        profile,
        build_model_vector(profile),
        RoutingConstraints(
            required_capabilities=frozenset({"vision"}),
            max_cost=3.0,
            max_latency_ms=1_000,
            min_context_window=8_000,
            requires_tools=True,
            requires_local_execution=True,
            privacy_level="local",
        ),
    )

    assert not result.eligible
    assert "missing_capability:vision" in result.rejection_reasons
    assert "context_window_too_small" in result.rejection_reasons
    assert "estimated_cost_exceeds_budget" in result.rejection_reasons
    assert "latency_exceeds_limit" in result.rejection_reasons
    assert "local_execution_required" in result.rejection_reasons


def test_provider_filters_are_hard_constraints() -> None:
    profile = candidate()
    result = evaluate_constraints(
        profile,
        build_model_vector(profile),
        RoutingConstraints(
            allowed_providers=frozenset({"provider-b"}),
            required_provider="provider-b",
        ),
    )

    assert result.rejection_reasons == (
        "provider_not_allowed",
        "required_provider_mismatch",
    )


def test_unknown_cost_and_latency_are_warnings() -> None:
    profile = candidate(estimated_cost=None, latency_ms=None)
    result = evaluate_constraints(
        profile,
        build_model_vector(profile),
        RoutingConstraints(max_cost=1.0, max_latency_ms=100),
    )

    assert result.eligible
    assert "estimated_cost_unknown" in result.warnings
    assert "latency_unknown" in result.warnings


def test_all_candidates_filtered_raises_structured_error() -> None:
    profiles = [
        candidate(model_id="a", capabilities=("reasoning",)),
        candidate(model_id="b", capabilities=("reasoning",)),
    ]

    with pytest.raises(NoEligibleModelError) as captured:
        AdaptiveRoutingEngine().route(
            analyze_task("Analyze image", task_id="vision"),
            profiles,
            RoutingConstraints(required_capabilities=frozenset({"vision"})),
        )

    assert set(captured.value.rejections) == {"a", "b"}
    assert captured.value.rejections["a"] == ("missing_capability:vision",)
