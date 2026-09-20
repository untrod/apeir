"""Finite numeric normalization shared by adaptive routing algorithms."""

from __future__ import annotations

import math
from typing import Any

from nous_runtime.intelligence.scoring.errors import (
    InvalidRoutingConfigurationError,
)

SCORE_PRECISION = 6


def finite_float(value: Any, *, name: str, default: float | None = None) -> float:
    if value is None and default is not None:
        return float(default)
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise InvalidRoutingConfigurationError(
            f"{name} must be numeric",
            context={"field": name},
        ) from exc
    if not math.isfinite(result):
        raise InvalidRoutingConfigurationError(
            f"{name} must be finite",
            context={"field": name},
        )
    return result


def clamp_01(value: Any, *, name: str = "value") -> float:
    number = finite_float(value, name=name)
    return round_score(max(0.0, min(1.0, number)))


def round_score(value: float) -> float:
    if not math.isfinite(value):
        raise InvalidRoutingConfigurationError(
            "score must be finite",
            context={"field": "score"},
        )
    return round(float(value), SCORE_PRECISION)


def normalize_cost(value: float | None, *, ceiling: float) -> float:
    if value is None:
        return 0.5
    limit = finite_float(ceiling, name="cost_ceiling")
    if limit <= 0:
        raise InvalidRoutingConfigurationError("cost_ceiling must be positive")
    return clamp_01(finite_float(value, name="estimated_cost") / limit)


def normalize_latency(value: int | float | None, *, ceiling_ms: float) -> float:
    if value is None:
        return 0.5
    limit = finite_float(ceiling_ms, name="latency_ceiling_ms")
    if limit <= 0:
        raise InvalidRoutingConfigurationError(
            "latency_ceiling_ms must be positive"
        )
    return clamp_01(finite_float(value, name="latency_ms") / limit)


__all__ = [
    "SCORE_PRECISION",
    "clamp_01",
    "finite_float",
    "normalize_cost",
    "normalize_latency",
    "round_score",
]
