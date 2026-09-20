"""Task and model vectorization in a shared extensible capability space."""

from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Mapping

from nous_runtime.intelligence.scoring.normalization import clamp_01
from nous_runtime.intelligence.scoring.registry import (
    CapabilityDimensionRegistry,
    default_dimension_registry,
)
from nous_runtime.intelligence.task.models import TaskAnalysis
from nous_runtime.model.profile import ModelProfile


_ALIASES = {
    "math": "mathematics",
    "model.code": "coding",
    "model.reason": "reasoning",
}
_COMPLEXITY = {"low": 0.25, "medium": 0.55, "high": 0.85}
_RISK_PRIORS = {
    "general": 0.25,
    "research": 0.35,
    "coding": 0.45,
    "math": 0.45,
    "computer_vision": 0.60,
    "privacy": 0.65,
}
_GLOBAL_PRIOR = 0.45
_FAMILY_PRIORS: dict[str, dict[str, float]] = {
    "gpt": {"language": 0.92, "tool_use": 0.88, "structured_output": 0.90},
    "claude": {"language": 0.94, "planning": 0.91, "instruction_following": 0.93},
    "deepseek": {"mathematics": 0.96, "coding": 0.88, "reasoning": 0.95},
    "ollama": {"privacy": 0.95, "local_execution": 1.0, "cost_efficiency": 0.95},
}


def _freeze_scores(values: Mapping[str, float], *, prefix: str) -> Mapping[str, float]:
    return MappingProxyType(
        {
            str(key): clamp_01(value, name=f"{prefix}.{key}")
            for key, value in values.items()
        }
    )


def _freeze_counts(values: Mapping[str, int]) -> Mapping[str, int]:
    result: dict[str, int] = {}
    for key, value in values.items():
        count = int(value)
        if count < 0:
            from nous_runtime.intelligence.scoring.errors import (
                InvalidRoutingConfigurationError,
            )

            raise InvalidRoutingConfigurationError(
                "sample_count must be non-negative",
                context={"dimension_id": str(key)},
            )
        result[str(key)] = count
    return MappingProxyType(result)


@dataclass(frozen=True)
class TaskRequirementVector:
    dimensions: Mapping[str, float]
    importance: Mapping[str, float]
    required_capabilities: frozenset[str] = frozenset()
    preferred_capabilities: frozenset[str] = frozenset()
    risk_level: float = 0.25
    complexity: float = 0.25

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "dimensions", _freeze_scores(self.dimensions, prefix="dimensions")
        )
        object.__setattr__(
            self, "importance", _freeze_scores(self.importance, prefix="importance")
        )
        object.__setattr__(
            self,
            "required_capabilities",
            frozenset(_canonical(item) for item in self.required_capabilities),
        )
        object.__setattr__(
            self,
            "preferred_capabilities",
            frozenset(_canonical(item) for item in self.preferred_capabilities),
        )
        object.__setattr__(
            self, "risk_level", clamp_01(self.risk_level, name="risk_level")
        )
        object.__setattr__(
            self, "complexity", clamp_01(self.complexity, name="complexity")
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "dimensions": dict(self.dimensions),
            "importance": dict(self.importance),
            "required_capabilities": sorted(self.required_capabilities),
            "preferred_capabilities": sorted(self.preferred_capabilities),
            "risk_level": self.risk_level,
            "complexity": self.complexity,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> "TaskRequirementVector":
        return cls(
            dimensions=dict(data.get("dimensions") or {}),
            importance=dict(data.get("importance") or {}),
            required_capabilities=frozenset(
                data.get("required_capabilities") or ()
            ),
            preferred_capabilities=frozenset(
                data.get("preferred_capabilities") or ()
            ),
            risk_level=float(data.get("risk_level") or 0.0),
            complexity=float(data.get("complexity") or 0.0),
        )


@dataclass(frozen=True)
class ModelCapabilityVector:
    model_id: str
    dimensions: Mapping[str, float]
    confidence: Mapping[str, float] = field(default_factory=dict)
    sample_count: Mapping[str, int] = field(default_factory=dict)
    profile_version: str = "routing-profile-v1"
    cold_start: bool = False
    warnings: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not str(self.model_id or "").strip():
            from nous_runtime.intelligence.scoring.errors import (
                InvalidRoutingConfigurationError,
            )

            raise InvalidRoutingConfigurationError("model_id is required")
        object.__setattr__(
            self, "dimensions", _freeze_scores(self.dimensions, prefix="dimensions")
        )
        object.__setattr__(
            self, "confidence", _freeze_scores(self.confidence, prefix="confidence")
        )
        object.__setattr__(self, "sample_count", _freeze_counts(self.sample_count))
        if not str(self.profile_version or "").strip():
            from nous_runtime.intelligence.scoring.errors import (
                InvalidRoutingConfigurationError,
            )

            raise InvalidRoutingConfigurationError("profile_version is required")

    def to_dict(self) -> dict[str, object]:
        return {
            "model_id": self.model_id,
            "dimensions": dict(self.dimensions),
            "confidence": dict(self.confidence),
            "sample_count": dict(self.sample_count),
            "profile_version": self.profile_version,
            "cold_start": self.cold_start,
            "warnings": list(self.warnings),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> "ModelCapabilityVector":
        return cls(
            model_id=str(data.get("model_id") or ""),
            dimensions=dict(data.get("dimensions") or {}),
            confidence=dict(data.get("confidence") or {}),
            sample_count=dict(data.get("sample_count") or {}),
            profile_version=str(
                data.get("profile_version") or "routing-profile-v1"
            ),
            cold_start=bool(data.get("cold_start")),
            warnings=tuple(data.get("warnings") or ()),
        )


def build_task_vector(
    analysis: TaskAnalysis,
    *,
    registry: CapabilityDimensionRegistry | None = None,
) -> TaskRequirementVector:
    registry = registry or default_dimension_registry()
    capabilities = tuple(_canonical(item) for item in analysis.required_capabilities)
    dimensions: dict[str, float] = {}
    importance: dict[str, float] = {}
    for index, capability in enumerate(capabilities):
        dimensions[capability] = 1.0 if index == 0 else 0.8
        registered = registry.get(capability)
        importance[capability] = registered.default_weight if registered else 1.0
    preferred = frozenset(
        _canonical(item)
        for item in analysis.metadata.get("preferred_capabilities", ())
    )
    for capability in preferred:
        dimensions.setdefault(capability, 0.5)
        importance.setdefault(capability, 0.5)
    risk = analysis.constraints.get(
        "risk_level",
        analysis.metadata.get("risk_level", _RISK_PRIORS.get(analysis.task_type, 0.3)),
    )
    complexity = analysis.metadata.get(
        "complexity_score",
        _COMPLEXITY.get(str(analysis.complexity).lower(), 0.5),
    )
    return TaskRequirementVector(
        dimensions=dimensions,
        importance=importance,
        required_capabilities=frozenset(capabilities),
        preferred_capabilities=preferred,
        risk_level=risk,
        complexity=complexity,
    )


def build_model_vector(
    profile: ModelProfile,
    *,
    registry: CapabilityDimensionRegistry | None = None,
    cold_start_confidence: float = 0.35,
) -> ModelCapabilityVector:
    registry = registry or default_dimension_registry()
    family_prior = _family_prior(profile.model_id)
    dimensions = {
        dimension.dimension_id: family_prior.get(
            dimension.dimension_id, _GLOBAL_PRIOR
        )
        for dimension in registry.list()
    }
    dimensions.update(
        {
            "reasoning": profile.reasoning_score,
            "coding": profile.coding_score,
            "mathematics": profile.math_score,
            "vision": profile.vision_score,
            "speed": profile.speed_score,
            "cost_efficiency": profile.cost_score,
            "privacy": 1.0 if profile.privacy_level == "local" else 0.5,
            "local_execution": 1.0
            if profile.supports("local_execution")
            else 0.0,
            "reliability": profile.reliability_score,
            "tool_use": 1.0 if profile.supports_tools else dimensions["tool_use"],
            "structured_output": 1.0
            if profile.supports_structured_output
            else dimensions["structured_output"],
        }
    )
    dimensions.update(
        {_canonical(key): value for key, value in profile.dimensions.items()}
    )
    for capability in profile.capabilities:
        dimensions.setdefault(_canonical(capability), 0.65)

    warnings = registry.validate(dimensions)
    confidence = {
        key: profile.confidence.get(key, cold_start_confidence)
        for key in dimensions
    }
    cold_start = not any(profile.sample_count.values())
    return ModelCapabilityVector(
        model_id=profile.model_id,
        dimensions=dimensions,
        confidence=confidence,
        sample_count=profile.sample_count,
        profile_version=profile.profile_version,
        cold_start=cold_start,
        warnings=warnings,
    )


def _canonical(identifier: str) -> str:
    value = str(identifier)
    return _ALIASES.get(value, value)


def _family_prior(model_id: str) -> Mapping[str, float]:
    lowered = str(model_id).lower()
    for family, values in _FAMILY_PRIORS.items():
        if family in lowered:
            return values
    return {}


__all__ = [
    "ModelCapabilityVector",
    "TaskRequirementVector",
    "build_model_vector",
    "build_task_vector",
]
