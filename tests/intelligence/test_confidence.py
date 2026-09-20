from nous_runtime.intelligence.scoring import (
    CandidateScore,
    ModelCapabilityVector,
    RoutingPolicy,
    TaskRequirementVector,
    estimate_decision_confidence,
    evidence_confidence,
)


def candidate(model_id: str, score: float, confidence: float) -> CandidateScore:
    return CandidateScore(
        model_id,
        True,
        score=score,
        confidence=confidence,
        reliability=0.9,
    )


def task(*, risk: float = 0.2, complexity: float = 0.2) -> TaskRequirementVector:
    return TaskRequirementVector(
        {"reasoning": 1.0},
        {"reasoning": 1.0},
        risk_level=risk,
        complexity=complexity,
    )


def vector(model_id: str, samples: int) -> ModelCapabilityVector:
    return ModelCapabilityVector(
        model_id,
        {"reasoning": 0.8},
        confidence={"reasoning": 0.8},
        sample_count={"reasoning": samples},
        cold_start=samples == 0,
    )


def test_evidence_confidence_increases_with_samples() -> None:
    assert evidence_confidence(100, smoothing_k=10) > evidence_confidence(
        1, smoothing_k=10
    )


def test_larger_score_margin_increases_decision_confidence() -> None:
    policy = RoutingPolicy()
    vectors = {"a": vector("a", 20), "b": vector("b", 20)}
    close = estimate_decision_confidence(
        [candidate("a", 0.8, 0.8), candidate("b", 0.79, 0.8)],
        task(),
        vectors,
        policy,
    )
    clear = estimate_decision_confidence(
        [candidate("a", 0.8, 0.8), candidate("b", 0.4, 0.8)],
        task(),
        vectors,
        policy,
    )

    assert clear.score_margin > close.score_margin
    assert clear.confidence > close.confidence


def test_high_risk_and_complexity_reduce_confidence() -> None:
    policy = RoutingPolicy()
    ranked = [candidate("a", 0.9, 0.9), candidate("b", 0.5, 0.8)]
    vectors = {"a": vector("a", 50), "b": vector("b", 20)}

    low = estimate_decision_confidence(ranked, task(), vectors, policy)
    high = estimate_decision_confidence(
        ranked,
        task(risk=0.9, complexity=0.9),
        vectors,
        policy,
    )

    assert high.confidence < low.confidence


def test_cold_start_penalty_reduces_confidence_without_zeroing() -> None:
    policy = RoutingPolicy()
    ranked = [candidate("a", 0.8, 0.35)]
    result = estimate_decision_confidence(
        ranked,
        task(),
        {"a": vector("a", 0)},
        policy,
    )

    assert 0 < result.confidence < 0.5
    assert result.cold_start_penalty == policy.cold_start_penalty
