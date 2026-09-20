"""Hard routing constraints evaluated before candidate scoring."""

from __future__ import annotations

from dataclasses import dataclass

from nous_runtime.intelligence.scoring.errors import (
    InvalidRoutingConfigurationError,
)
from nous_runtime.intelligence.scoring.vectors import ModelCapabilityVector
from nous_runtime.model.profile import ModelProfile


@dataclass(frozen=True)
class RoutingConstraints:
    required_capabilities: frozenset[str] = frozenset()
    forbidden_models: frozenset[str] = frozenset()
    allowed_providers: frozenset[str] | None = None
    required_provider: str | None = None
    max_cost: float | None = None
    max_latency_ms: int | None = None
    min_context_window: int | None = None
    requires_tools: bool = False
    requires_vision: bool = False
    requires_local_execution: bool = False
    requires_structured_output: bool = False
    privacy_level: str | None = None

    def __post_init__(self) -> None:
        if self.max_cost is not None and float(self.max_cost) < 0:
            raise InvalidRoutingConfigurationError("max_cost must be non-negative")
        if self.max_latency_ms is not None and int(self.max_latency_ms) < 0:
            raise InvalidRoutingConfigurationError(
                "max_latency_ms must be non-negative"
            )
        if self.min_context_window is not None and int(self.min_context_window) < 0:
            raise InvalidRoutingConfigurationError(
                "min_context_window must be non-negative"
            )

    def to_dict(self) -> dict[str, object]:
        return {
            "required_capabilities": sorted(self.required_capabilities),
            "forbidden_models": sorted(self.forbidden_models),
            "allowed_providers": (
                sorted(self.allowed_providers)
                if self.allowed_providers is not None
                else None
            ),
            "required_provider": self.required_provider,
            "max_cost": self.max_cost,
            "max_latency_ms": self.max_latency_ms,
            "min_context_window": self.min_context_window,
            "requires_tools": self.requires_tools,
            "requires_vision": self.requires_vision,
            "requires_local_execution": self.requires_local_execution,
            "requires_structured_output": self.requires_structured_output,
            "privacy_level": self.privacy_level,
        }


@dataclass(frozen=True)
class ConstraintResult:
    eligible: bool
    rejection_reasons: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, object]:
        return {
            "eligible": self.eligible,
            "rejection_reasons": list(self.rejection_reasons),
            "warnings": list(self.warnings),
        }


def evaluate_constraints(
    profile: ModelProfile,
    vector: ModelCapabilityVector,
    constraints: RoutingConstraints,
) -> ConstraintResult:
    reasons: list[str] = []
    warnings: list[str] = list(vector.warnings)

    if not profile.available:
        reasons.append("model_unavailable")
    if profile.model_id in constraints.forbidden_models:
        reasons.append("model_forbidden")
    if (
        constraints.allowed_providers is not None
        and profile.provider not in constraints.allowed_providers
    ):
        reasons.append("provider_not_allowed")
    if (
        constraints.required_provider is not None
        and profile.provider != constraints.required_provider
    ):
        reasons.append("required_provider_mismatch")

    for capability in sorted(constraints.required_capabilities):
        if not _supports(profile, capability):
            reasons.append(f"missing_capability:{capability}")

    if constraints.max_cost is not None:
        if profile.estimated_cost is None:
            warnings.append("estimated_cost_unknown")
        elif profile.estimated_cost > constraints.max_cost:
            reasons.append("estimated_cost_exceeds_budget")
    if constraints.max_latency_ms is not None:
        if profile.latency_ms is None:
            warnings.append("latency_unknown")
        elif profile.latency_ms > constraints.max_latency_ms:
            reasons.append("latency_exceeds_limit")
    if constraints.min_context_window is not None:
        if profile.context_window <= 0:
            reasons.append("context_window_unknown")
        elif profile.context_window < constraints.min_context_window:
            reasons.append("context_window_too_small")
    if constraints.requires_tools and not profile.supports_tools:
        reasons.append("tool_use_required")
    if constraints.requires_vision and not _supports(profile, "vision"):
        reasons.append("missing_capability:vision")
    if (
        constraints.requires_structured_output
        and not profile.supports_structured_output
    ):
        reasons.append("structured_output_required")
    if (
        constraints.requires_local_execution
        and not _supports(profile, "local_execution")
    ):
        reasons.append("local_execution_required")
    if constraints.privacy_level == "local" and profile.privacy_level != "local":
        reasons.append("privacy_level_mismatch")

    return ConstraintResult(
        eligible=not reasons,
        rejection_reasons=tuple(dict.fromkeys(reasons)),
        warnings=tuple(dict.fromkeys(warnings)),
    )


def _supports(profile: ModelProfile, capability: str) -> bool:
    aliases = {
        capability,
        {"mathematics": "math", "math": "mathematics"}.get(capability, capability),
        f"model.{capability}",
    }
    if any(profile.supports(alias) for alias in aliases):
        return True
    return any(float(profile.dimensions.get(alias, 0.0)) > 0 for alias in aliases)


__all__ = ["ConstraintResult", "RoutingConstraints", "evaluate_constraints"]
