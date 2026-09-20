"""Composite policy implementation."""

from __future__ import annotations

from dataclasses import dataclass

from nous_runtime.intelligence.models import DecisionRequest, RuntimeDecision
from nous_runtime.intelligence.policies.base import Policy


@dataclass(frozen=True)
class CompositePolicy:
    policy_id: str
    version: str
    decision_type: str
    policies: tuple[Policy, ...]
    priority: int = 0
    mode: str = "first_match"

    def matches(self, request: DecisionRequest) -> bool:
        if self.decision_type and request.decision_type.value != self.decision_type:
            return False
        return any(policy.matches(request) for policy in self.policies)

    def decide(self, request: DecisionRequest) -> RuntimeDecision:
        matches = [policy for policy in self.policies if policy.matches(request)]
        if not matches:
            raise ValueError(f"composite policy has no match: {self.policy_id}")
        if self.mode == "highest_priority":
            matches.sort(key=lambda policy: policy.priority, reverse=True)
        decision = matches[0].decide(request)
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
