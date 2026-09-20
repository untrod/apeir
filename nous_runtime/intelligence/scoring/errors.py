"""Adaptive routing errors built on the Runtime error hierarchy."""

from __future__ import annotations

from typing import Mapping, Sequence

from nous_runtime.core.errors import CapabilityError, ConfigurationError, NousError


class AdaptiveIntelligenceError(NousError):
    error_code = "adaptive_intelligence_error"

    def __init__(self, message: str, *, context: Mapping[str, object] | None = None):
        super().__init__(message)
        self.context = dict(context or {})


class InvalidCapabilityDimensionError(AdaptiveIntelligenceError, CapabilityError):
    error_code = "invalid_capability_dimension"


class InvalidRoutingConfigurationError(
    AdaptiveIntelligenceError, ConfigurationError
):
    error_code = "invalid_routing_configuration"


class NoEligibleModelError(AdaptiveIntelligenceError):
    error_code = "no_eligible_model"

    def __init__(
        self,
        message: str,
        *,
        rejections: Mapping[str, Sequence[str]],
    ):
        self.rejections = {
            str(model_id): tuple(str(reason) for reason in reasons)
            for model_id, reasons in rejections.items()
        }
        super().__init__(
            message,
            context={"candidate_count": len(self.rejections)},
        )


class InvalidFeedbackError(AdaptiveIntelligenceError):
    error_code = "invalid_feedback"


class DuplicateFeedbackError(InvalidFeedbackError):
    error_code = "duplicate_feedback"


class RoutingComputationError(AdaptiveIntelligenceError):
    error_code = "routing_computation_error"


__all__ = [
    "AdaptiveIntelligenceError",
    "DuplicateFeedbackError",
    "InvalidCapabilityDimensionError",
    "InvalidFeedbackError",
    "InvalidRoutingConfigurationError",
    "NoEligibleModelError",
    "RoutingComputationError",
]
