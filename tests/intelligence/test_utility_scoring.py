from nous_runtime.intelligence.scoring import (
    ModelCapabilityVector,
    RoutingPolicy,
    TaskRequirementVector,
    capability_fit,
    score_candidate,
)
from nous_runtime.model import ModelProfile


def task_vector() -> TaskRequirementVector:
    return TaskRequirementVector(
        dimensions={"reasoning": 1.0},
        importance={"reasoning": 1.0},
        required_capabilities=frozenset({"reasoning"}),
        risk_level=0.4,
        complexity=0.5,
    )


def model_vector(capability: float, confidence: float = 0.8) -> ModelCapabilityVector:
    return ModelCapabilityVector(
        "model",
        {
            "reasoning": capability,
            "reliability": 0.9,
            "long_context": 0.8,
            "tool_use": 0.7,
            "privacy": 0.6,
        },
        confidence={"reasoning": confidence},
        sample_count={"reasoning": 20},
    )


def test_capability_fit_and_squared_gap_formula() -> None:
    fit, gap = capability_fit(task_vector(), model_vector(0.8))

    assert fit == 0.8
    assert gap == 0.04


def test_score_contains_complete_breakdown() -> None:
    profile = ModelProfile(
        "model",
        "provider",
        ("reasoning",),
        reliability_score=0.9,
        estimated_cost=2.0,
        latency_ms=500,
    )

    candidate = score_candidate(
        task_vector(),
        model_vector(0.8),
        profile,
        RoutingPolicy(mode="adaptive"),
    )

    assert 0 <= candidate.score <= 1
    assert candidate.breakdown is not None
    assert candidate.breakdown.capability_fit == 0.8
    assert candidate.breakdown.gap_penalty == 0.04
    assert candidate.breakdown.utility_raw == candidate.breakdown.utility


def test_severe_capability_gap_receives_larger_penalty() -> None:
    profile = ModelProfile("model", "provider", ("reasoning",))
    policy = RoutingPolicy(mode="adaptive")

    strong = score_candidate(task_vector(), model_vector(0.9), profile, policy)
    weak = score_candidate(task_vector(), model_vector(0.3), profile, policy)

    assert weak.breakdown.gap_penalty > strong.breakdown.gap_penalty
    assert weak.score < strong.score


def test_cost_and_latency_are_normalized_separately() -> None:
    profile = ModelProfile(
        "model",
        "provider",
        ("reasoning",),
        estimated_cost=5.0,
        latency_ms=5_000,
    )
    candidate = score_candidate(
        task_vector(),
        model_vector(0.8),
        profile,
        RoutingPolicy(cost_ceiling=10.0, latency_ceiling_ms=10_000),
    )

    assert candidate.breakdown.normalized_cost == 0.5
    assert candidate.breakdown.normalized_latency == 0.5


def test_uncertainty_penalizes_equal_capability_model() -> None:
    profile = ModelProfile("model", "provider", ("reasoning",))
    policy = RoutingPolicy(mode="adaptive")

    known = score_candidate(task_vector(), model_vector(0.8, 0.9), profile, policy)
    uncertain = score_candidate(
        task_vector(), model_vector(0.8, 0.2), profile, policy
    )

    assert uncertain.breakdown.uncertainty > known.breakdown.uncertainty
    assert uncertain.score < known.score
