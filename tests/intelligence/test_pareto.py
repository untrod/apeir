from nous_runtime.intelligence.scoring import (
    CandidateScore,
    ScoreBreakdown,
    deterministic_sort,
    dominates,
    pareto_frontier,
)


def scored(
    model_id: str,
    *,
    quality: float,
    reliability: float,
    cost: float,
    latency: float,
    uncertainty: float,
    score: float,
) -> CandidateScore:
    breakdown = ScoreBreakdown(
        capability_fit=quality,
        gap_penalty=0,
        adjusted_fit=quality,
        preference_bonus=0,
        reliability=reliability,
        context_fit=0.5,
        tool_fit=0.5,
        privacy_fit=0.5,
        normalized_cost=cost,
        normalized_latency=latency,
        uncertainty=uncertainty,
        risk_penalty=0,
        utility_raw=score,
        utility=score,
        weights_version="test",
    )
    return CandidateScore(
        model_id,
        True,
        score=score,
        confidence=1 - uncertainty,
        reliability=reliability,
        breakdown=breakdown,
        estimated_cost=cost,
        latency_ms=int(latency * 1000),
    )


def test_pareto_dominance() -> None:
    better = scored(
        "better", quality=0.9, reliability=0.9, cost=0.2, latency=0.2,
        uncertainty=0.1, score=0.9
    )
    worse = scored(
        "worse", quality=0.8, reliability=0.8, cost=0.3, latency=0.3,
        uncertainty=0.2, score=0.7
    )

    assert dominates(better, worse)
    assert not dominates(worse, better)


def test_pareto_frontier_keeps_tradeoffs() -> None:
    quality = scored(
        "quality", quality=0.95, reliability=0.8, cost=0.5, latency=0.3,
        uncertainty=0.1, score=0.85
    )
    economy = scored(
        "economy", quality=0.8, reliability=0.8, cost=0.1, latency=0.3,
        uncertainty=0.1, score=0.8
    )
    dominated = scored(
        "dominated", quality=0.7, reliability=0.7, cost=0.6, latency=0.5,
        uncertainty=0.3, score=0.6
    )

    assert pareto_frontier([quality, economy, dominated]) == frozenset(
        {"quality", "economy"}
    )


def test_deterministic_sort_uses_model_id_as_final_tie_break() -> None:
    left = scored(
        "alpha", quality=0.8, reliability=0.8, cost=0.2, latency=0.2,
        uncertainty=0.2, score=0.8
    ).with_pareto(True)
    right = scored(
        "beta", quality=0.8, reliability=0.8, cost=0.2, latency=0.2,
        uncertainty=0.2, score=0.8
    ).with_pareto(True)

    assert [item.model_id for item in deterministic_sort([right, left])] == [
        "alpha",
        "beta",
    ]
