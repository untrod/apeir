"""Governed Scientific Capability Layer."""

from nous_runtime.scientific.models import (
    ScientificAnalysisSpec,
    ScientificValidationError,
)


def __getattr__(name: str):
    if name in {"ScientificNotFoundError", "ScientificRuntime"}:
        from nous_runtime.scientific.service import (
            ScientificNotFoundError,
            ScientificRuntime,
        )

        return {
            "ScientificNotFoundError": ScientificNotFoundError,
            "ScientificRuntime": ScientificRuntime,
        }[name]
    raise AttributeError(name)


__all__ = [
    "ScientificAnalysisSpec",
    "ScientificNotFoundError",
    "ScientificRuntime",
    "ScientificValidationError",
]
