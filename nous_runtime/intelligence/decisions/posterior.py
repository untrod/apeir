"""Small standard-library posterior and EMA primitives."""

from __future__ import annotations

from dataclasses import dataclass

from nous_runtime.intelligence.scoring.errors import InvalidFeedbackError
from nous_runtime.intelligence.scoring.normalization import round_score


@dataclass(frozen=True)
class BetaPosterior:
    alpha: float = 1.0
    beta: float = 1.0

    def __post_init__(self) -> None:
        if self.alpha <= 0 or self.beta <= 0:
            raise InvalidFeedbackError("Beta prior parameters must be positive")

    @property
    def expected_success(self) -> float:
        return round_score(self.alpha / (self.alpha + self.beta))

    def update(self, success: bool, *, weight: float = 1.0) -> "BetaPosterior":
        if weight <= 0:
            raise InvalidFeedbackError("feedback weight must be positive")
        return BetaPosterior(
            alpha=self.alpha + (weight if success else 0.0),
            beta=self.beta + (0.0 if success else weight),
        )


@dataclass(frozen=True)
class EMAValue:
    value: float | None = None
    sample_count: int = 0

    def update(self, observation: float, *, eta: float) -> "EMAValue":
        if not 0 < eta <= 1:
            raise InvalidFeedbackError("EMA eta must be in (0, 1]")
        next_value = (
            observation
            if self.value is None
            else (1.0 - eta) * self.value + eta * observation
        )
        return EMAValue(round_score(next_value), self.sample_count + 1)


__all__ = ["BetaPosterior", "EMAValue"]
