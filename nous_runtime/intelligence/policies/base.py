"""Base policy contracts."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from nous_runtime.intelligence.models import DecisionRequest, RuntimeDecision


@dataclass(frozen=True)
class RuntimePolicy:
    policy_id: str
    version: str = "1.0"
    priority: int = 0
    decision_type: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


class Policy(Protocol):
    policy_id: str
    version: str
    priority: int
    decision_type: str

    def matches(self, request: DecisionRequest) -> bool:
        ...

    def decide(self, request: DecisionRequest) -> RuntimeDecision:
        ...
