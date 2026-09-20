"""Rule-based execution strategy selection."""

from __future__ import annotations

from collections.abc import Sequence

from nous_runtime.intelligence.scoring.config import StrategyThresholds
from nous_runtime.intelligence.scoring.utility import CandidateScore
from nous_runtime.intelligence.scoring.vectors import TaskRequirementVector
from nous_runtime.intelligence.strategy.models import (
    RoutingStrategy,
    StrategyDecision,
)


def select_strategy(
    task: TaskRequirementVector,
    ranked: Sequence[CandidateScore],
    *,
    decision_confidence: float,
    score_margin: float,
    thresholds: StrategyThresholds,
    result_verifiable: bool = False,
    availability_required: bool = False,
) -> StrategyDecision:
    eligible = [candidate for candidate in ranked if candidate.eligible]
    primary = eligible[0]
    secondary = tuple(candidate.model_id for candidate in eligible[1:3])

    if task.risk_level >= thresholds.repair_min_risk and result_verifiable:
        return StrategyDecision(
            RoutingStrategy.REPAIR,
            primary.model_id,
            secondary[:1],
            max_attempts=3,
            requires_verification=True,
            rationale=("high_risk", "result_verifiable"),
            confidence=decision_confidence,
        )
    if (
        task.risk_level >= thresholds.review_min_risk
        or task.complexity >= thresholds.review_min_complexity
    ):
        return StrategyDecision(
            RoutingStrategy.REVIEW,
            primary.model_id,
            secondary[:1],
            max_attempts=2,
            requires_verification=True,
            rationale=("risk_or_complexity_requires_review",),
            confidence=decision_confidence,
        )
    if (
        score_margin <= thresholds.parallel_max_margin
        and max(task.risk_level, task.complexity)
        >= thresholds.parallel_min_task_value
        and secondary
    ):
        return StrategyDecision(
            RoutingStrategy.PARALLEL_COMPARE,
            primary.model_id,
            secondary,
            max_attempts=1,
            requires_verification=True,
            rationale=("candidate_scores_close", "task_value_nontrivial"),
            confidence=decision_confidence,
        )
    if (
        availability_required
        or primary.reliability <= thresholds.fallback_max_reliability
    ) and secondary:
        return StrategyDecision(
            RoutingStrategy.FALLBACK,
            primary.model_id,
            secondary,
            max_attempts=1 + len(secondary),
            rationale=("availability_or_reliability_requires_fallback",),
            confidence=decision_confidence,
        )
    if (
        task.risk_level < thresholds.single_max_risk
        and task.complexity < thresholds.single_max_complexity
        and decision_confidence >= thresholds.single_min_confidence
        and score_margin >= thresholds.single_min_margin
    ):
        return StrategyDecision(
            RoutingStrategy.SINGLE,
            primary.model_id,
            confidence=decision_confidence,
            rationale=("low_risk", "low_complexity", "clear_high_confidence_winner"),
        )
    if secondary:
        return StrategyDecision(
            RoutingStrategy.FALLBACK,
            primary.model_id,
            secondary,
            max_attempts=1 + len(secondary),
            rationale=("default_resilience_policy",),
            confidence=decision_confidence,
        )
    return StrategyDecision(
        RoutingStrategy.SINGLE,
        primary.model_id,
        confidence=decision_confidence,
        rationale=("only_eligible_candidate",),
    )


__all__ = ["select_strategy"]
