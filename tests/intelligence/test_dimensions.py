import math

import pytest

from nous_runtime.intelligence.scoring import (
    CapabilityDimension,
    CapabilityDimensionRegistry,
    InvalidCapabilityDimensionError,
    InvalidRoutingConfigurationError,
    clamp_01,
    default_dimension_registry,
)


def test_standard_dimension_registry_is_extensible() -> None:
    registry = default_dimension_registry()

    assert registry.contains("reasoning")
    assert registry.contains("local_execution")
    custom = registry.register_custom("robotics")
    assert registry.get("robotics") is custom


def test_dimension_duplicate_is_rejected() -> None:
    registry = CapabilityDimensionRegistry(include_standard=False)
    dimension = CapabilityDimension("coding", "Coding", "quality")
    registry.register(dimension)

    with pytest.raises(InvalidCapabilityDimensionError):
        registry.register(dimension)


def test_unknown_dimension_is_reported_or_rejected() -> None:
    registry = default_dimension_registry()

    assert registry.validate({"future_dimension": 0.8}) == (
        "unknown_dimension:future_dimension",
    )
    with pytest.raises(InvalidCapabilityDimensionError):
        registry.validate({"future_dimension": 0.8}, strict=True)


@pytest.mark.parametrize("value", [math.nan, math.inf, -math.inf, "not-a-number"])
def test_non_finite_scores_are_rejected(value) -> None:
    with pytest.raises(InvalidRoutingConfigurationError):
        clamp_01(value)


def test_clamp_01_enforces_bounds() -> None:
    assert clamp_01(-1) == 0.0
    assert clamp_01(2) == 1.0
