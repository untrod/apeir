"""Fallback policy implementation."""

from __future__ import annotations

from dataclasses import dataclass

from nous_runtime.intelligence.models import (
    DecisionOutcome,
    DecisionReason,
    DecisionRequest,
    RuntimeDecision,
    decision_id_for,
)
from nous_runtime.intelligence.policies.base import Policy


@dataclass(frozen=True)
class FallbackPolicy:
    policy_id: str
    version: str
    decision_type: str
    primary: Policy
    fallback_selected: str
    priority: int = 0
    confidence: float = 0.4

    def matches(self, request: DecisionRequest) -> bool:
        return not self.decision_type or request.decision_type.value == self.decision_type

    def decide(self, request: DecisionRequest) -> RuntimeDecision:
        if self.primary.matches(request):
            decision = self.primary.decide(request)
            return RuntimeDecision(
                decision_id=decision.decision_id,
                task_id=decision.task_id,
                decision_type=decision.decision_type,
                outcome=decision.outcome,
                reasons=decision.reasons,
                candidates=decision.candidates,
                constraints=decision.constraints,
                policy_id=self.policy_id,
                policy_version=self.version,
                inputs_snapshot=decision.inputs_snapshot,
                created_at=decision.created_at,
            )
        reason = DecisionReason(
            code="FALLBACK_POLICY",
            message="Primary policy did not match; fallback selected.",
            weight=self.confidence,
        )
        return RuntimeDecision(
            decision_id=decision_id_for(request, self.policy_id, self.fallback_selected),
            task_id=request.task_id,
            decision_type=request.decision_type,
            outcome=DecisionOutcome(selected=self.fallback_selected, confidence=self.confidence),
            reasons=(reason,),
            policy_id=self.policy_id,
            policy_version=self.version,
            inputs_snapshot=request.to_dict(),
        )
