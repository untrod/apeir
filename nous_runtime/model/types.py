"""Model Runtime request and selection models."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class ModelRequest:
    task_type: str
    context: str = ""
    privacy: str = "standard"
    cost: float = 0.0
    latency: int = 0
    quality: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ModelSelection:
    provider: str
    model: str
    score: float
    reason: str
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
