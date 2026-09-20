"""Deterministic feedback learning without model training."""

from __future__ import annotations

import math
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta, timezone
from types import MappingProxyType
from typing import Mapping

from nous_runtime.intelligence.decisions.posterior import BetaPosterior, EMAValue
from nous_runtime.intelligence.scoring.errors import (
    DuplicateFeedbackError,
    InvalidFeedbackError,
)
from nous_runtime.intelligence.scoring.normalization import finite_float
from nous_runtime.model.profile import ModelProfile


@dataclass(frozen=True)
class FeedbackObservation:
    decision_id: str
    task_id: str
    model_id: str
    task_type: str
    capability_dimensions: Mapping[str, float]
    success: bool | None = None
    quality_score: float | None = None
    latency_ms: int | None = None
    cost: float | None = None
    correction_count: int = 0
    verifier_score: float | None = None
    human_score: float | None = None
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    source: str = "implicit_signal"
    feedback_type: str = "execution"
    feedback_weight: float | None = None
    reviewer_model_id: str = ""

    @property
    def idempotency_key(self) -> str:
        return f"{self.decision_id}:{self.source}:{self.feedback_type}"

    def to_dict(self) -> dict[str, object]:
        return {
            "decision_id": self.decision_id,
            "task_id": self.task_id,
            "model_id": self.model_id,
            "task_type": self.task_type,
            "capability_dimensions": dict(self.capability_dimensions),
            "success": self.success,
            "quality_score": self.quality_score,
            "latency_ms": self.latency_ms,
            "cost": self.cost,
            "correction_count": self.correction_count,
            "verifier_score": self.verifier_score,
            "human_score": self.human_score,
            "timestamp": self.timestamp.isoformat(),
            "source": self.source,
            "feedback_type": self.feedback_type,
            "feedback_weight": self.feedback_weight,
            "reviewer_model_id": self.reviewer_model_id,
        }


@dataclass(frozen=True)
class FeedbackLearningConfig:
    prior_alpha: float = 1.0
    prior_beta: float = 1.0
    ema_eta: float = 0.20
    decay_rate: float = 0.0
    confidence_smoothing_k: float = 10.0
    future_tolerance_seconds: int = 300
    source_weights: Mapping[str, float] = field(
        default_factory=lambda: MappingProxyType(
            {
                "deterministic_verifier": 1.0,
                "test_execution": 0.9,
                "human_explicit": 0.8,
                "model_reviewer": 0.6,
                "implicit_signal": 0.3,
            }
        )
    )
    version: str = "feedback-v1"

    def __post_init__(self) -> None:
        if self.prior_alpha <= 0 or self.prior_beta <= 0:
            raise InvalidFeedbackError("feedback priors must be positive")
        if not 0 < self.ema_eta <= 1:
            raise InvalidFeedbackError("ema_eta must be in (0, 1]")
        if self.decay_rate < 0:
            raise InvalidFeedbackError("decay_rate must be non-negative")
        if self.confidence_smoothing_k <= 0:
            raise InvalidFeedbackError(
                "confidence_smoothing_k must be positive"
            )
        if not self.version:
            raise InvalidFeedbackError("feedback version is required")


@dataclass(frozen=True)
class ModelLearningState:
    model_id: str
    success_by_dimension: Mapping[str, BetaPosterior]
    quality: EMAValue
    latency_ms: EMAValue
    cost: EMAValue
    observation_count: int
    version: str


class FeedbackLearner:
    def __init__(
        self,
        config: FeedbackLearningConfig | None = None,
        *,
        known_decision_ids: set[str] | None = None,
    ) -> None:
        self.config = config or FeedbackLearningConfig()
        self._known_decisions = (
            set(known_decision_ids) if known_decision_ids is not None else None
        )
        self._seen_keys: set[str] = set()
        self._posteriors: dict[tuple[str, str], BetaPosterior] = {}
        self._quality: dict[str, EMAValue] = {}
        self._latency: dict[str, EMAValue] = {}
        self._cost: dict[str, EMAValue] = {}
        self._counts: dict[str, int] = {}
        self._observations: list[FeedbackObservation] = []

    def register_decision(self, decision_id: str) -> None:
        if self._known_decisions is None:
            self._known_decisions = set()
        self._known_decisions.add(str(decision_id))

    def record_feedback(self, observation: FeedbackObservation) -> ModelLearningState:
        self._validate(observation)
        if observation.idempotency_key in self._seen_keys:
            raise DuplicateFeedbackError(
                "feedback already recorded",
                context={"idempotency_key": observation.idempotency_key},
            )
        weight = self._effective_weight(observation)
        if observation.success is not None:
            dimensions = observation.capability_dimensions or {
                observation.task_type: 1.0
            }
            for dimension_id, relevance in dimensions.items():
                posterior_key = (observation.model_id, str(dimension_id))
                posterior = self._posteriors.get(
                    posterior_key,
                    BetaPosterior(
                        self.config.prior_alpha,
                        self.config.prior_beta,
                    ),
                )
                update_weight = weight * finite_float(
                    relevance,
                    name=f"capability_dimensions.{dimension_id}",
                )
                if update_weight > 0:
                    self._posteriors[posterior_key] = posterior.update(
                        observation.success,
                        weight=update_weight,
                    )
        self._update_continuous(observation)
        self._counts[observation.model_id] = (
            self._counts.get(observation.model_id, 0) + 1
        )
        self._seen_keys.add(observation.idempotency_key)
        self._observations.append(observation)
        return self.state_for(observation.model_id)

    def state_for(self, model_id: str) -> ModelLearningState:
        posteriors = {
            dimension_id: posterior
            for (candidate_id, dimension_id), posterior in self._posteriors.items()
            if candidate_id == model_id
        }
        return ModelLearningState(
            model_id=model_id,
            success_by_dimension=MappingProxyType(posteriors),
            quality=self._quality.get(model_id, EMAValue()),
            latency_ms=self._latency.get(model_id, EMAValue()),
            cost=self._cost.get(model_id, EMAValue()),
            observation_count=self._counts.get(model_id, 0),
            version=self.config.version,
        )

    def list_feedback(self) -> list[FeedbackObservation]:
        return list(self._observations)

    def apply_to_profile(self, profile: ModelProfile) -> ModelProfile:
        """Return an updated immutable routing profile from learned estimates."""
        state = self.state_for(profile.model_id)
        dimensions = dict(profile.dimensions)
        confidence = dict(profile.confidence)
        sample_count = dict(profile.sample_count)
        success_values: list[float] = []
        for dimension_id, posterior in state.success_by_dimension.items():
            observations = max(
                0,
                int(
                    round(
                        posterior.alpha
                        + posterior.beta
                        - self.config.prior_alpha
                        - self.config.prior_beta
                    )
                ),
            )
            dimensions[dimension_id] = posterior.expected_success
            sample_count[dimension_id] = (
                sample_count.get(dimension_id, 0) + observations
            )
            confidence[dimension_id] = observations / (
                observations + self.config.confidence_smoothing_k
            )
            success_values.append(posterior.expected_success)
        reliability = (
            sum(success_values) / len(success_values)
            if success_values
            else profile.reliability_score
        )
        metadata = {
            **profile.metadata,
            "feedback_learning": {
                "version": state.version,
                "observation_count": state.observation_count,
                "quality_ema": state.quality.value,
                "latency_ema_ms": state.latency_ms.value,
                "cost_ema": state.cost.value,
            },
        }
        return replace(
            profile,
            dimensions=dimensions,
            confidence=confidence,
            sample_count=sample_count,
            profile_version=state.version,
            reliability_score=reliability,
            estimated_cost=(
                state.cost.value
                if state.cost.value is not None
                else profile.estimated_cost
            ),
            latency_ms=(
                int(round(state.latency_ms.value))
                if state.latency_ms.value is not None
                else profile.latency_ms
            ),
            metadata=metadata,
        )

    def _validate(self, observation: FeedbackObservation) -> None:
        if not observation.decision_id:
            raise InvalidFeedbackError("decision_id is required")
        if not observation.model_id:
            raise InvalidFeedbackError("model_id is required")
        if (
            self._known_decisions is not None
            and observation.decision_id not in self._known_decisions
        ):
            raise InvalidFeedbackError(
                "feedback decision does not exist",
                context={"decision_id": observation.decision_id},
            )
        now = datetime.now(timezone.utc)
        timestamp = observation.timestamp
        if timestamp.tzinfo is None:
            raise InvalidFeedbackError("feedback timestamp must be timezone-aware")
        if timestamp > now + timedelta(seconds=self.config.future_tolerance_seconds):
            raise InvalidFeedbackError("feedback timestamp is in the future")
        if observation.reviewer_model_id == observation.model_id:
            raise InvalidFeedbackError("self-review feedback is not accepted")
        for name in ("quality_score", "verifier_score", "human_score"):
            value = getattr(observation, name)
            if value is not None:
                number = finite_float(value, name=name)
                if not 0 <= number <= 1:
                    raise InvalidFeedbackError(f"{name} must be between 0 and 1")
        if observation.latency_ms is not None and observation.latency_ms < 0:
            raise InvalidFeedbackError("latency_ms must be non-negative")
        if observation.cost is not None and observation.cost < 0:
            raise InvalidFeedbackError("cost must be non-negative")
        if observation.correction_count < 0:
            raise InvalidFeedbackError("correction_count must be non-negative")

    def _effective_weight(self, observation: FeedbackObservation) -> float:
        base = (
            finite_float(observation.feedback_weight, name="feedback_weight")
            if observation.feedback_weight is not None
            else float(self.config.source_weights.get(observation.source, 0.3))
        )
        if base <= 0:
            raise InvalidFeedbackError("feedback weight must be positive")
        age_seconds = max(
            0.0,
            (datetime.now(timezone.utc) - observation.timestamp).total_seconds(),
        )
        return base * math.exp(-self.config.decay_rate * age_seconds)

    def _update_continuous(self, observation: FeedbackObservation) -> None:
        model_id = observation.model_id
        if observation.quality_score is not None:
            self._quality[model_id] = self._quality.get(
                model_id, EMAValue()
            ).update(observation.quality_score, eta=self.config.ema_eta)
        if observation.latency_ms is not None:
            self._latency[model_id] = self._latency.get(
                model_id, EMAValue()
            ).update(float(observation.latency_ms), eta=self.config.ema_eta)
        if observation.cost is not None:
            self._cost[model_id] = self._cost.get(model_id, EMAValue()).update(
                observation.cost,
                eta=self.config.ema_eta,
            )


__all__ = [
    "FeedbackLearner",
    "FeedbackLearningConfig",
    "FeedbackObservation",
    "ModelLearningState",
]
