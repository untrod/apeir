"""Explainable adaptive candidate scoring."""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from typing import Mapping

from nous_runtime.intelligence.scoring.config import RoutingPolicy, RoutingWeights
from nous_runtime.intelligence.scoring.normalization import (
    clamp_01,
    normalize_cost,
    normalize_latency,
    round_score,
)
from nous_runtime.intelligence.scoring.vectors import (
    ModelCapabilityVector,
    TaskRequirementVector,
)
from nous_runtime.model.profile import ModelProfile


@dataclass(frozen=True)
class ScoreBreakdown:
    capability_fit: float
    gap_penalty: float
    adjusted_fit: float
    preference_bonus: float
    reliability: float
    context_fit: float
    tool_fit: float
    privacy_fit: float
    normalized_cost: float
    normalized_latency: float
    uncertainty: float
    risk_penalty: float
    utility_raw: float
    utility: float
    weights_version: str

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class CandidateScore:
    model_id: str
    eligible: bool
    rejection_reasons: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    pareto_optimal: bool = False
    score: float | None = None
    confidence: float = 0.0
    breakdown: ScoreBreakdown | None = None
    reliability: float = 0.0
    estimated_cost: float | None = None
    latency_ms: int | None = None

    def with_pareto(self, value: bool) -> "CandidateScore":
        return replace(self, pareto_optimal=value)

    def to_dict(self) -> dict[str, object]:
        return {
            "model_id": self.model_id,
            "eligible": self.eligible,
            "rejection_reasons": list(self.rejection_reasons),
            "warnings": list(self.warnings),
            "pareto_optimal": self.pareto_optimal,
            "score": self.score,
            "confidence": self.confidence,
            "breakdown": self.breakdown.to_dict() if self.breakdown else None,
            "reliability": self.reliability,
            "estimated_cost": self.estimated_cost,
            "latency_ms": self.latency_ms,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> "CandidateScore":
        raw_breakdown = data.get("breakdown")
        breakdown = (
            ScoreBreakdown(**dict(raw_breakdown))
            if isinstance(raw_breakdown, Mapping)
            else None
        )
        return cls(
            model_id=str(data.get("model_id") or ""),
            eligible=bool(data.get("eligible")),
            rejection_reasons=tuple(data.get("rejection_reasons") or ()),
            warnings=tuple(data.get("warnings") or ()),
            pareto_optimal=bool(data.get("pareto_optimal")),
            score=float(data["score"]) if data.get("score") is not None else None,
            confidence=float(data.get("confidence") or 0.0),
            breakdown=breakdown,
            reliability=float(data.get("reliability") or 0.0),
            estimated_cost=(
                float(data["estimated_cost"])
                if data.get("estimated_cost") is not None
                else None
            ),
            latency_ms=(
                int(data["latency_ms"])
                if data.get("latency_ms") is not None
                else None
            ),
        )


def capability_fit(
    task: TaskRequirementVector,
    model: ModelCapabilityVector,
) -> tuple[float, float]:
    denominator = 0.0
    fit_numerator = 0.0
    gap_numerator = 0.0
    for dimension_id, requirement in task.dimensions.items():
        if requirement <= 0:
            continue
        weight = task.importance.get(dimension_id, 1.0)
        capability = model.dimensions.get(dimension_id, 0.0)
        term = weight * requirement
        denominator += term
        fit_numerator += term * capability
        gap_numerator += term * max(0.0, requirement - capability) ** 2
    if denominator <= 0:
        return 0.0, 0.0
    return (
        round_score(fit_numerator / denominator),
        round_score(gap_numerator / denominator),
    )


def preference_bonus(
    task: TaskRequirementVector,
    model: ModelCapabilityVector,
    policy: RoutingPolicy,
) -> float:
    total = sum(
        policy.preference_weight * model.dimensions.get(capability, 0.0)
        for capability in task.preferred_capabilities
    )
    return round_score(min(policy.preference_bonus_cap, total))


def score_candidate(
    task: TaskRequirementVector,
    model: ModelCapabilityVector,
    profile: ModelProfile,
    policy: RoutingPolicy,
) -> CandidateScore:
    weights = effective_weights(task, policy)
    fit, gap = capability_fit(task, model)
    adjusted_fit = clamp_01(
        fit - weights.gap_penalty * gap,
        name="adjusted_fit",
    )
    bonus = preference_bonus(task, model, policy)
    reliability = model.dimensions.get("reliability", profile.reliability_score)
    context_fit = model.dimensions.get("long_context", 0.5)
    tool_fit = model.dimensions.get("tool_use", 0.5)
    privacy_fit = model.dimensions.get("privacy", 0.5)
    normalized_cost = normalize_cost(
        profile.estimated_cost,
        ceiling=policy.cost_ceiling,
    )
    normalized_latency = normalize_latency(
        profile.latency_ms,
        ceiling_ms=policy.latency_ceiling_ms,
    )
    uncertainty = task_weighted_uncertainty(task, model)
    risk_penalty = task.risk_level * (1.0 - reliability)
    raw = (
        weights.quality * min(1.0, adjusted_fit + bonus)
        + weights.reliability * reliability
        + weights.context * context_fit
        + weights.tools * tool_fit
        + weights.privacy * privacy_fit
        - weights.cost * normalized_cost
        - weights.latency * normalized_latency
        - weights.uncertainty * uncertainty
        - weights.risk * risk_penalty
    )
    utility = clamp_01(raw, name="utility")
    confidence = round_score(1.0 - uncertainty)
    breakdown = ScoreBreakdown(
        capability_fit=fit,
        gap_penalty=gap,
        adjusted_fit=adjusted_fit,
        preference_bonus=bonus,
        reliability=round_score(reliability),
        context_fit=round_score(context_fit),
        tool_fit=round_score(tool_fit),
        privacy_fit=round_score(privacy_fit),
        normalized_cost=normalized_cost,
        normalized_latency=normalized_latency,
        uncertainty=uncertainty,
        risk_penalty=round_score(risk_penalty),
        utility_raw=round_score(raw),
        utility=utility,
        weights_version=weights.version,
    )
    return CandidateScore(
        model_id=profile.model_id,
        eligible=True,
        score=utility,
        confidence=confidence,
        breakdown=breakdown,
        reliability=round_score(reliability),
        estimated_cost=profile.estimated_cost,
        latency_ms=profile.latency_ms,
    )


def task_weighted_uncertainty(
    task: TaskRequirementVector,
    model: ModelCapabilityVector,
) -> float:
    denominator = 0.0
    numerator = 0.0
    for dimension_id, requirement in task.dimensions.items():
        if requirement <= 0:
            continue
        weight = task.importance.get(dimension_id, 1.0) * requirement
        denominator += weight
        numerator += weight * model.confidence.get(dimension_id, 0.0)
    if denominator <= 0:
        return 1.0
    return clamp_01(1.0 - numerator / denominator, name="uncertainty")


def effective_weights(
    task: TaskRequirementVector,
    policy: RoutingPolicy,
) -> RoutingWeights:
    base = policy.weights
    dynamic = policy.dynamic_weights
    quality = base.quality
    reliability = base.reliability
    cost = base.cost
    latency = base.latency
    uncertainty = base.uncertainty
    risk = base.risk
    if task.complexity >= dynamic.complexity_threshold:
        quality *= dynamic.quality_complexity_multiplier
        reliability *= dynamic.reliability_complexity_multiplier
        cost *= dynamic.efficiency_complexity_multiplier
        latency *= dynamic.efficiency_complexity_multiplier
    if task.risk_level >= dynamic.risk_threshold:
        reliability *= dynamic.reliability_risk_multiplier
        uncertainty *= dynamic.uncertainty_risk_multiplier
        risk *= dynamic.risk_multiplier
    if task.dimensions.get("speed", 0.0) >= dynamic.preference_threshold:
        latency *= dynamic.latency_preference_multiplier
    if (
        task.dimensions.get("cost_efficiency", 0.0)
        >= dynamic.preference_threshold
    ):
        cost *= dynamic.cost_preference_multiplier
    if (
        task.dimensions.get("local_execution", 0.0)
        >= dynamic.preference_threshold
    ):
        return replace(
            base,
            quality=quality,
            reliability=reliability,
            privacy=base.privacy * dynamic.privacy_preference_multiplier,
            cost=cost,
            latency=latency,
            uncertainty=uncertainty,
            risk=risk,
        )
    return replace(
        base,
        quality=quality,
        reliability=reliability,
        cost=cost,
        latency=latency,
        uncertainty=uncertainty,
        risk=risk,
    )


__all__ = [
    "CandidateScore",
    "ScoreBreakdown",
    "capability_fit",
    "effective_weights",
    "preference_bonus",
    "score_candidate",
    "task_weighted_uncertainty",
]
