"""Versioned adaptive routing configuration."""

from __future__ import annotations

from dataclasses import dataclass, field, fields

from nous_runtime.intelligence.scoring.errors import (
    InvalidRoutingConfigurationError,
)
from nous_runtime.intelligence.scoring.normalization import finite_float


@dataclass(frozen=True)
class RoutingWeights:
    quality: float = 0.38
    reliability: float = 0.14
    context: float = 0.08
    tools: float = 0.06
    privacy: float = 0.06
    cost: float = 0.08
    latency: float = 0.08
    uncertainty: float = 0.07
    risk: float = 0.05
    gap_penalty: float = 0.55
    version: str = "weights-v1"

    def __post_init__(self) -> None:
        for item in fields(self):
            if item.name == "version":
                continue
            value = finite_float(getattr(self, item.name), name=item.name)
            if value < 0:
                raise InvalidRoutingConfigurationError(
                    f"{item.name} must be non-negative"
                )
            object.__setattr__(self, item.name, value)
        if not self.version:
            raise InvalidRoutingConfigurationError("weights version is required")
        if not any(
            getattr(self, name) > 0
            for name in ("quality", "reliability", "context", "tools", "privacy")
        ):
            raise InvalidRoutingConfigurationError(
                "at least one positive objective weight is required"
            )


@dataclass(frozen=True)
class StrategyThresholds:
    single_max_risk: float = 0.35
    single_max_complexity: float = 0.45
    single_min_confidence: float = 0.75
    single_min_margin: float = 0.15
    review_min_risk: float = 0.60
    review_min_complexity: float = 0.70
    repair_min_risk: float = 0.75
    parallel_max_margin: float = 0.05
    parallel_min_task_value: float = 0.45
    fallback_max_reliability: float = 0.55
    version: str = "strategy-v1"

    def __post_init__(self) -> None:
        for item in fields(self):
            if item.name == "version":
                continue
            value = finite_float(getattr(self, item.name), name=item.name)
            if not 0 <= value <= 1:
                raise InvalidRoutingConfigurationError(
                    f"{item.name} must be between 0 and 1"
                )
            object.__setattr__(self, item.name, value)
        if not self.version:
            raise InvalidRoutingConfigurationError(
                "strategy version is required"
            )


@dataclass(frozen=True)
class DynamicWeightConfig:
    complexity_threshold: float = 0.70
    risk_threshold: float = 0.60
    preference_threshold: float = 0.70
    quality_complexity_multiplier: float = 1.25
    reliability_complexity_multiplier: float = 1.15
    efficiency_complexity_multiplier: float = 0.75
    reliability_risk_multiplier: float = 1.35
    uncertainty_risk_multiplier: float = 1.35
    risk_multiplier: float = 1.25
    latency_preference_multiplier: float = 1.50
    cost_preference_multiplier: float = 1.50
    privacy_preference_multiplier: float = 1.75
    version: str = "dynamic-weights-v1"

    def __post_init__(self) -> None:
        for item in fields(self):
            if item.name == "version":
                continue
            value = finite_float(getattr(self, item.name), name=item.name)
            if value < 0:
                raise InvalidRoutingConfigurationError(
                    f"{item.name} must be non-negative"
                )
            object.__setattr__(self, item.name, value)
        for name in (
            "complexity_threshold",
            "risk_threshold",
            "preference_threshold",
        ):
            if getattr(self, name) > 1:
                raise InvalidRoutingConfigurationError(
                    f"{name} must be between 0 and 1"
                )
        if not self.version:
            raise InvalidRoutingConfigurationError(
                "dynamic weights version is required"
            )


@dataclass(frozen=True)
class RoutingPolicy:
    weights: RoutingWeights = field(default_factory=RoutingWeights)
    strategy: StrategyThresholds = field(default_factory=StrategyThresholds)
    dynamic_weights: DynamicWeightConfig = field(
        default_factory=DynamicWeightConfig
    )
    preference_weight: float = 0.04
    preference_bonus_cap: float = 0.10
    evidence_smoothing_k: float = 10.0
    cost_ceiling: float = 10.0
    latency_ceiling_ms: float = 10_000.0
    confidence_model_weight: float = 0.45
    confidence_margin_weight: float = 0.25
    confidence_evidence_weight: float = 0.30
    confidence_complexity_penalty: float = 0.15
    confidence_risk_penalty: float = 0.15
    confidence_margin_scale: float = 0.25
    cold_start_penalty: float = 0.10
    mode: str = "auto"
    version: str = "adaptive-routing-v1"

    def __post_init__(self) -> None:
        if self.mode not in {"legacy", "adaptive", "auto"}:
            raise InvalidRoutingConfigurationError(
                f"unsupported routing mode: {self.mode}"
            )
        if not self.version:
            raise InvalidRoutingConfigurationError("policy version is required")
        if self.evidence_smoothing_k <= 0:
            raise InvalidRoutingConfigurationError(
                "evidence_smoothing_k must be positive"
            )
        for name in (
            "preference_weight",
            "preference_bonus_cap",
            "cost_ceiling",
            "latency_ceiling_ms",
            "confidence_model_weight",
            "confidence_margin_weight",
            "confidence_evidence_weight",
            "confidence_complexity_penalty",
            "confidence_risk_penalty",
            "confidence_margin_scale",
            "cold_start_penalty",
        ):
            value = finite_float(getattr(self, name), name=name)
            if value < 0:
                raise InvalidRoutingConfigurationError(
                    f"{name} must be non-negative"
                )
            object.__setattr__(self, name, value)
        if self.cost_ceiling <= 0 or self.latency_ceiling_ms <= 0:
            raise InvalidRoutingConfigurationError(
                "normalization ceilings must be positive"
            )
        if self.confidence_margin_scale <= 0:
            raise InvalidRoutingConfigurationError(
                "confidence_margin_scale must be positive"
            )


__all__ = [
    "DynamicWeightConfig",
    "RoutingPolicy",
    "RoutingWeights",
    "StrategyThresholds",
]
