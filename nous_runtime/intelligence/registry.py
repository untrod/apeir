"""Policy registry and resolution order."""

from __future__ import annotations

from dataclasses import dataclass, field

from nous_runtime.intelligence.models import DecisionRequest
from nous_runtime.intelligence.policies.base import Policy


@dataclass
class PolicyRegistry:
    _policies: list[Policy] = field(default_factory=list)
    _metadata: dict[str, dict] = field(default_factory=dict)

    def register(self, policy: Policy, metadata: dict | None = None) -> None:
        self._policies = [p for p in self._policies if p.policy_id != policy.policy_id]
        self._policies.append(policy)
        self._policies.sort(key=lambda p: p.priority, reverse=True)
        if metadata is not None:
            self._metadata[policy.policy_id] = dict(metadata)

    def list(self) -> list[Policy]:
        return list(self._policies)

    def resolve(self, request: DecisionRequest) -> list[Policy]:
        return [policy for policy in self._policies if policy.matches(request)]

    def metadata_for(self, policy_id: str) -> dict:
        return dict(self._metadata.get(policy_id) or {})


registry = PolicyRegistry()
