"""Intent Runtime transport models."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass(frozen=True)
class IntentRequest:
    input_text: str
    user_id: str = "local"
    workspace_hint: str = ""
    timestamp: str = field(default_factory=_utc_now)
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.input_text.strip():
            raise ValueError("input_text is required")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class IntentDecision:
    intent: str
    confidence: float
    workspace: str = ""
    project: str = ""
    task: str = ""
    requires_confirmation: bool = False
    reason: str = ""
    route: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "confidence", max(0.0, min(1.0, float(self.confidence))))

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
