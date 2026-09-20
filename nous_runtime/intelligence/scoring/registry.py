"""Extensible capability dimension registry."""

from __future__ import annotations

from collections.abc import Iterable, Mapping

from nous_runtime.intelligence.scoring.dimensions import (
    STANDARD_DIMENSIONS,
    CapabilityDimension,
)
from nous_runtime.intelligence.scoring.errors import (
    InvalidCapabilityDimensionError,
)


class CapabilityDimensionRegistry:
    def __init__(
        self,
        dimensions: Iterable[CapabilityDimension] = (),
        *,
        include_standard: bool = True,
    ) -> None:
        self._dimensions: dict[str, CapabilityDimension] = {}
        source = (*STANDARD_DIMENSIONS, *tuple(dimensions)) if include_standard else dimensions
        for dimension in source:
            self.register(dimension)

    def register(self, dimension: CapabilityDimension) -> CapabilityDimension:
        if not isinstance(dimension, CapabilityDimension):
            raise InvalidCapabilityDimensionError(
                "dimension must be a CapabilityDimension"
            )
        if dimension.dimension_id in self._dimensions:
            raise InvalidCapabilityDimensionError(
                f"dimension already registered: {dimension.dimension_id}",
                context={"dimension_id": dimension.dimension_id},
            )
        self._dimensions[dimension.dimension_id] = dimension
        return dimension

    def register_custom(self, dimension_id: str) -> CapabilityDimension:
        dimension = CapabilityDimension(
            dimension_id,
            f"Custom capability dimension: {dimension_id}",
            "custom",
        )
        return self.register(dimension)

    def get(self, dimension_id: str) -> CapabilityDimension | None:
        return self._dimensions.get(str(dimension_id))

    def contains(self, dimension_id: str) -> bool:
        return str(dimension_id) in self._dimensions

    def list(self) -> list[CapabilityDimension]:
        return sorted(self._dimensions.values(), key=lambda item: item.dimension_id)

    def validate(
        self,
        values: Mapping[str, object] | Iterable[str],
        *,
        strict: bool = False,
    ) -> tuple[str, ...]:
        identifiers = values.keys() if isinstance(values, Mapping) else values
        unknown = sorted(
            {str(identifier) for identifier in identifiers if not self.contains(str(identifier))}
        )
        if unknown and strict:
            raise InvalidCapabilityDimensionError(
                "unknown capability dimensions",
                context={"unknown": tuple(unknown)},
            )
        return tuple(f"unknown_dimension:{identifier}" for identifier in unknown)


def default_dimension_registry() -> CapabilityDimensionRegistry:
    return CapabilityDimensionRegistry()


__all__ = ["CapabilityDimensionRegistry", "default_dimension_registry"]
