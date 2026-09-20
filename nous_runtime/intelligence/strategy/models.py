"""Execution strategy decision contracts."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum
from typing import Mapping


class RoutingStrategy(str, Enum):
    SINGLE = "single"
    FALLBACK = "fallback"
    REVIEW = "review"
    REPAIR = "repair"
    PARALLEL_COMPARE = "parallel_compare"


@dataclass(frozen=True)
class StrategyDecision:
    strategy: RoutingStrategy
    primary_model_id: str
    secondary_model_ids: tuple[str, ...] = ()
    max_attempts: int = 1
    requires_verification: bool = False
    rationale: tuple[str, ...] = ()
    confidence: float = 0.0

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["strategy"] = self.strategy.value
        payload["secondary_model_ids"] = list(self.secondary_model_ids)
        payload["rationale"] = list(self.rationale)
        return payload

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> "StrategyDecision":
        return cls(
            strategy=RoutingStrategy(str(data.get("strategy") or "single")),
            primary_model_id=str(data.get("primary_model_id") or ""),
            secondary_model_ids=tuple(data.get("secondary_model_ids") or ()),
            max_attempts=int(data.get("max_attempts") or 1),
            requires_verification=bool(data.get("requires_verification")),
            rationale=tuple(data.get("rationale") or ()),
            confidence=float(data.get("confidence") or 0.0),
        )


__all__ = ["RoutingStrategy", "StrategyDecision"]
