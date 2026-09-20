from nous_runtime.intelligence.scoring import (
    CandidateScore,
    StrategyThresholds,
    TaskRequirementVector,
)
from nous_runtime.intelligence.strategy import RoutingStrategy, select_strategy


def task(risk: float, complexity: float) -> TaskRequirementVector:
    return TaskRequirementVector(
        {"reasoning": 1.0},
        {"reasoning": 1.0},
        risk_level=risk,
        complexity=complexity,
    )


def candidates(reliability: float = 0.9) -> list[CandidateScore]:
    return [
        CandidateScore("primary", True, score=0.9, confidence=0.9, reliability=reliability),
        CandidateScore("secondary", True, score=0.7, confidence=0.8, reliability=0.8),
    ]


def test_single_strategy() -> None:
    decision = select_strategy(
        task(0.2, 0.2),
        candidates(),
        decision_confidence=0.9,
        score_margin=0.2,
        thresholds=StrategyThresholds(),
    )

    assert decision.strategy is RoutingStrategy.SINGLE


def test_fallback_strategy() -> None:
    decision = select_strategy(
        task(0.2, 0.2),
        candidates(reliability=0.4),
        decision_confidence=0.7,
        score_margin=0.2,
        thresholds=StrategyThresholds(),
    )

    assert decision.strategy is RoutingStrategy.FALLBACK
    assert decision.secondary_model_ids == ("secondary",)


def test_review_strategy() -> None:
    decision = select_strategy(
        task(0.65, 0.5),
        candidates(),
        decision_confidence=0.7,
        score_margin=0.1,
        thresholds=StrategyThresholds(),
    )

    assert decision.strategy is RoutingStrategy.REVIEW
    assert decision.requires_verification


def test_repair_strategy() -> None:
    decision = select_strategy(
        task(0.8, 0.8),
        candidates(),
        decision_confidence=0.7,
        score_margin=0.1,
        thresholds=StrategyThresholds(),
        result_verifiable=True,
    )

    assert decision.strategy is RoutingStrategy.REPAIR
    assert decision.max_attempts == 3


def test_parallel_compare_strategy() -> None:
    decision = select_strategy(
        task(0.5, 0.5),
        candidates(),
        decision_confidence=0.6,
        score_margin=0.01,
        thresholds=StrategyThresholds(),
    )

    assert decision.strategy is RoutingStrategy.PARALLEL_COMPARE
