"""Static fallback policy implementation."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from nous_runtime.intelligence.models import (
    DecisionOutcome,
    DecisionReason,
    DecisionRequest,
    RuntimeDecision,
    decision_id_for,
)


@dataclass(frozen=True)
class StaticPolicy:
    policy_id: str
    version: str
    decision_type: str
    selected: str
    priority: int = 0
    confidence: float = 0.5
    metadata: dict[str, Any] = field(default_factory=dict)

    def matches(self, request: DecisionRequest) -> bool:
        return not self.decision_type or request.decision_type.value == self.decision_type

    def decide(self, request: DecisionRequest) -> RuntimeDecision:
        reason = DecisionReason(
            code="STATIC_POLICY",
            message=f"Selected by static policy {self.policy_id}.",
            weight=self.confidence,
        )
        return RuntimeDecision(
            decision_id=decision_id_for(request, self.policy_id, self.selected),
            task_id=request.task_id,
            decision_type=request.decision_type,
            outcome=DecisionOutcome(
                selected=self.selected,
                alternatives=tuple(),
                confidence=self.confidence,
                metadata=dict(self.metadata),
            ),
            reasons=(reason,),
            policy_id=self.policy_id,
            policy_version=self.version,
            inputs_snapshot=request.to_dict(),
        )
