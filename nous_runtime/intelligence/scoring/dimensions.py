"""Capability dimension contracts and standard Runtime dimensions."""

from __future__ import annotations

from dataclasses import dataclass

from nous_runtime.intelligence.scoring.normalization import finite_float


@dataclass(frozen=True)
class CapabilityDimension:
    dimension_id: str
    description: str
    category: str
    default_weight: float = 1.0
    higher_is_better: bool = True

    def __post_init__(self) -> None:
        identifier = str(self.dimension_id or "").strip()
        if not identifier:
            from nous_runtime.intelligence.scoring.errors import (
                InvalidCapabilityDimensionError,
            )

            raise InvalidCapabilityDimensionError("dimension_id is required")
        weight = finite_float(self.default_weight, name="default_weight")
        if weight < 0:
            from nous_runtime.intelligence.scoring.errors import (
                InvalidCapabilityDimensionError,
            )

            raise InvalidCapabilityDimensionError(
                "default_weight must be non-negative",
                context={"dimension_id": identifier},
            )
        object.__setattr__(self, "dimension_id", identifier)
        object.__setattr__(self, "default_weight", weight)

    def to_dict(self) -> dict[str, object]:
        return {
            "dimension_id": self.dimension_id,
            "description": self.description,
            "category": self.category,
            "default_weight": self.default_weight,
            "higher_is_better": self.higher_is_better,
        }


_STANDARD_SPECS = (
    ("reasoning", "General reasoning", "quality"),
    ("coding", "Software implementation", "quality"),
    ("mathematics", "Mathematical reasoning", "quality"),
    ("language", "Language understanding", "quality"),
    ("vision", "Image understanding", "modality"),
    ("audio", "Audio understanding", "modality"),
    ("long_context", "Long context handling", "runtime"),
    ("structured_output", "Structured output generation", "runtime"),
    ("tool_use", "Tool invocation", "runtime"),
    ("planning", "Multi-step planning", "quality"),
    ("retrieval", "Retrieval augmented work", "runtime"),
    ("verification", "Result verification", "quality"),
    ("instruction_following", "Instruction adherence", "quality"),
    ("speed", "Execution speed", "efficiency"),
    ("cost_efficiency", "Cost efficiency", "efficiency"),
    ("reliability", "Observed reliability", "quality"),
    ("privacy", "Privacy preservation", "governance"),
    ("local_execution", "On-device execution", "governance"),
)

STANDARD_DIMENSIONS = tuple(
    CapabilityDimension(identifier, description, category)
    for identifier, description, category in _STANDARD_SPECS
)


__all__ = ["CapabilityDimension", "STANDARD_DIMENSIONS"]
