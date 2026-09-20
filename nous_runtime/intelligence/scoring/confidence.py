"""Evidence and decision confidence estimation with full breakdown."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Sequence

from nous_runtime.intelligence.scoring.config import RoutingPolicy
from nous_runtime.intelligence.scoring.normalization import clamp_01, round_score
from nous_runtime.intelligence.scoring.utility import CandidateScore
from nous_runtime.intelligence.scoring.vectors import (
    ModelCapabilityVector,
    TaskRequirementVector,
)


@dataclass(frozen=True)
class DecisionConfidenceBreakdown:
    top_model_confidence: float
    score_margin: float
    normalized_margin: float
    evidence_strength: float
    complexity_penalty: float
    risk_penalty: float
    cold_start_penalty: float
    confidence: float

    def to_dict(self) -> dict[str, float]:
        return asdict(self)


def evidence_confidence(sample_count: int, *, smoothing_k: float) -> float:
    if sample_count < 0 or smoothing_k <= 0:
        from nous_runtime.intelligence.scoring.errors import (
            InvalidRoutingConfigurationError,
        )

        raise InvalidRoutingConfigurationError(
            "sample_count must be non-negative and smoothing_k positive"
        )
    return round_score(sample_count / (sample_count + smoothing_k))


def estimate_decision_confidence(
    ranked: Sequence[CandidateScore],
    task: TaskRequirementVector,
    vectors: dict[str, ModelCapabilityVector],
    policy: RoutingPolicy,
) -> DecisionConfidenceBreakdown:
    eligible = [
        candidate
        for candidate in ranked
        if candidate.eligible and candidate.score is not None
    ]
    if not eligible:
        return DecisionConfidenceBreakdown(0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0)
    top = eligible[0]
    second_score = eligible[1].score if len(eligible) > 1 else 0.0
    margin = max(0.0, float(top.score or 0.0) - float(second_score or 0.0))
    normalized_margin = clamp_01(
        margin / policy.confidence_margin_scale,
        name="normalized_margin",
    )
    vector = vectors[top.model_id]
    relevant_counts = [
        vector.sample_count.get(dimension_id, 0)
        for dimension_id, requirement in task.dimensions.items()
        if requirement > 0
    ]
    samples = sum(relevant_counts)
    evidence = evidence_confidence(
        samples,
        smoothing_k=policy.evidence_smoothing_k,
    )
    complexity_penalty = policy.confidence_complexity_penalty * task.complexity
    risk_penalty = policy.confidence_risk_penalty * task.risk_level
    cold_start_penalty = policy.cold_start_penalty if vector.cold_start else 0.0
    confidence = clamp_01(
        policy.confidence_model_weight * top.confidence
        + policy.confidence_margin_weight * normalized_margin
        + policy.confidence_evidence_weight * evidence
        - complexity_penalty
        - risk_penalty
        - cold_start_penalty,
        name="decision_confidence",
    )
    return DecisionConfidenceBreakdown(
        top_model_confidence=top.confidence,
        score_margin=round_score(margin),
        normalized_margin=normalized_margin,
        evidence_strength=evidence,
        complexity_penalty=round_score(complexity_penalty),
        risk_penalty=round_score(risk_penalty),
        cold_start_penalty=cold_start_penalty,
        confidence=confidence,
    )


__all__ = [
    "DecisionConfidenceBreakdown",
    "estimate_decision_confidence",
    "evidence_confidence",
]
