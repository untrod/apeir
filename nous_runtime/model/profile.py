"""Compact routing manifest for model capability matching.

The detailed, provenance-aware profile remains in
``nous_runtime.intelligence.profiles``.  This manifest is the stable scoring
view consumed by Runtime Intelligence routing.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import math
from typing import Any, Mapping

from nous_runtime.core.errors import CapabilityError


@dataclass(frozen=True)
class ModelProfile:
    model_id: str
    provider: str
    capabilities: tuple[str, ...] = ()
    reasoning_score: float = 0.5
    coding_score: float = 0.5
    math_score: float = 0.5
    vision_score: float = 0.0
    speed_score: float = 0.5
    cost_score: float = 0.5
    privacy_level: str = "cloud"
    metadata: dict[str, Any] = field(default_factory=dict)
    dimensions: Mapping[str, float] = field(default_factory=dict)
    confidence: Mapping[str, float] = field(default_factory=dict)
    sample_count: Mapping[str, int] = field(default_factory=dict)
    profile_version: str = "routing-profile-v1"
    reliability_score: float = 0.5
    context_window: int = 0
    supports_tools: bool = False
    supports_structured_output: bool = False
    estimated_cost: float | None = None
    latency_ms: int | None = None
    available: bool = True

    def __post_init__(self) -> None:
        if not str(self.model_id).strip():
            raise CapabilityError("model_id is required")
        if not str(self.provider).strip():
            raise CapabilityError("model provider is required")
        object.__setattr__(self, "capabilities", tuple(dict.fromkeys(str(item) for item in self.capabilities)))
        object.__setattr__(self, "metadata", dict(self.metadata))
        object.__setattr__(self, "dimensions", dict(self.dimensions))
        object.__setattr__(self, "confidence", dict(self.confidence))
        object.__setattr__(self, "sample_count", dict(self.sample_count))
        for name in (
            "reasoning_score", "coding_score", "math_score", "vision_score",
            "speed_score", "cost_score", "reliability_score",
        ):
            value = float(getattr(self, name))
            if not math.isfinite(value) or not 0.0 <= value <= 1.0:
                raise CapabilityError(f"{name} must be between 0.0 and 1.0")
            object.__setattr__(self, name, value)
        if int(self.context_window) < 0:
            raise CapabilityError("context_window must be non-negative")
        if self.estimated_cost is not None and float(self.estimated_cost) < 0:
            raise CapabilityError("estimated_cost must be non-negative")
        if self.latency_ms is not None and int(self.latency_ms) < 0:
            raise CapabilityError("latency_ms must be non-negative")
        if not str(self.profile_version or "").strip():
            raise CapabilityError("profile_version is required")

    def supports(self, capability: str) -> bool:
        aliases = {capability, f"model.{capability}"}
        return bool(aliases.intersection(self.capabilities))

    def to_dict(self) -> dict[str, Any]:
        return {
            "model_id": self.model_id,
            "provider": self.provider,
            "capabilities": list(self.capabilities),
            "reasoning_score": self.reasoning_score,
            "coding_score": self.coding_score,
            "math_score": self.math_score,
            "vision_score": self.vision_score,
            "speed_score": self.speed_score,
            "cost_score": self.cost_score,
            "privacy_level": self.privacy_level,
            "metadata": dict(self.metadata),
            "dimensions": dict(self.dimensions),
            "confidence": dict(self.confidence),
            "sample_count": dict(self.sample_count),
            "profile_version": self.profile_version,
            "reliability_score": self.reliability_score,
            "context_window": self.context_window,
            "supports_tools": self.supports_tools,
            "supports_structured_output": self.supports_structured_output,
            "estimated_cost": self.estimated_cost,
            "latency_ms": self.latency_ms,
            "available": self.available,
        }


__all__ = ["ModelProfile"]
