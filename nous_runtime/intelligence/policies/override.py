"""Override policy implementation."""

from __future__ import annotations

from dataclasses import dataclass

from nous_runtime.intelligence.models import (
    DecisionOutcome,
    DecisionReason,
    DecisionRequest,
    RuntimeDecision,
    decision_id_for,
)


@dataclass(frozen=True)
class OverridePolicy:
    policy_id: str
    version: str
    decision_type: str
    override_key: str
    priority: int = 10_000

    def matches(self, request: DecisionRequest) -> bool:
        if self.decision_type and request.decision_type.value != self.decision_type:
            return False
        return self.override_key in request.context.explicit_overrides

    def decide(self, request: DecisionRequest) -> RuntimeDecision:
        selected = str(request.context.explicit_overrides[self.override_key])
        reason = DecisionReason(
            code="EXPLICIT_OVERRIDE_POLICY",
            message="Explicit override selected this outcome.",
            weight=1.0,
        )
        return RuntimeDecision(
            decision_id=decision_id_for(request, self.policy_id, selected),
            task_id=request.task_id,
            decision_type=request.decision_type,
            outcome=DecisionOutcome(selected=selected, confidence=1.0),
            reasons=(reason,),
            policy_id=self.policy_id,
            policy_version=self.version,
            inputs_snapshot=request.to_dict(),
        )
