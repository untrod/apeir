# -*- coding: utf-8 -*-
"""Policy Optimizer — generates policy improvement proposals from experience.

IMPORTANT: Proposals must pass Governance before being applied.
Experience does NOT auto-modify policies.
"""

from __future__ import annotations

import logging

from nous_runtime.experience.models import ExperienceRecord, PolicyProposal
from nous_runtime.experience.store import ExperienceStore

_log = logging.getLogger("nous.experience.policy")


class PolicyOptimizer:
    """Generates policy improvement proposals from experience data.

    Usage::

        optimizer = PolicyOptimizer(store)
        proposals = optimizer.generate_proposals()
        for p in proposals:
            # Submit to governance for approval
            pass
    """

    def __init__(self, store: ExperienceStore | None = None):
        self._store = store or ExperienceStore()
        self._min_samples = 5



    def generate_proposals(self) -> list[PolicyProposal]:
        """Generate all policy improvement proposals."""
        proposals: list[PolicyProposal] = []

        proposals.extend(self._propose_agent_preferences())
        proposals.extend(self._propose_provider_preferences())
        proposals.extend(self._propose_approach_improvements())

        return proposals



    def _propose_agent_preferences(self) -> list[PolicyProposal]:
        """Propose agent preferences based on success rates."""
        proposals: list[PolicyProposal] = []
        experiences = self._store.list(limit=500)
        if not experiences:
            return proposals

        # Group by agent
        by_agent: dict[str, list[ExperienceRecord]] = {}
        for e in experiences:
            if e.agent_id:
                by_agent.setdefault(e.agent_id, []).append(e)

        for agent_id, exps in by_agent.items():
            if len(exps) < self._min_samples:
                continue
            success_rate = sum(1 for e in exps if e.success) / len(exps)
            if success_rate >= 0.85:
                proposals.append(PolicyProposal(
                    title=f"Prefer agent: {agent_id}",
                    description=f"Agent '{agent_id}' has {success_rate:.0%} success rate over {len(exps)} executions.",
                    target_policy="agent_selection",
                    proposed_change=f"Increase weight for agent '{agent_id}' in selection policy.",
                    supporting_experiences=tuple(e.id for e in exps[:10]),
                    confidence=min(0.90, 0.5 + success_rate * 0.4),
                    expected_impact=f"Expected success rate improvement: +{int((success_rate - 0.7) * 100)}%",
                ))
        return proposals

    def _propose_provider_preferences(self) -> list[PolicyProposal]:
        """Propose provider preferences based on experience."""
        proposals: list[PolicyProposal] = []
        experiences = self._store.list(limit=500)

        by_provider: dict[str, list[ExperienceRecord]] = {}
        for e in experiences:
            if e.provider_id:
                by_provider.setdefault(e.provider_id, []).append(e)

        for pid, exps in by_provider.items():
            if len(exps) < self._min_samples:
                continue
            success_rate = sum(1 for e in exps if e.success) / len(exps)
            if success_rate >= 0.85:
                proposals.append(PolicyProposal(
                    title=f"Prefer provider: {pid}",
                    description=f"Provider '{pid}' has {success_rate:.0%} success rate.",
                    target_policy="provider_selection",
                    proposed_change=f"Increase weight for provider '{pid}'.",
                    supporting_experiences=tuple(e.id for e in exps[:10]),
                    confidence=min(0.90, 0.5 + success_rate * 0.4),
                    expected_impact=f"+{int((success_rate - 0.7) * 100)}% success rate",
                ))
        return proposals

    def _propose_approach_improvements(self) -> list[PolicyProposal]:
        """Propose approach improvements from lessons."""
        proposals: list[PolicyProposal] = []
        experiences = self._store.list(status="validated", limit=200)
        experiences.extend(self._store.list(status="trusted", limit=200))

        # Find common lessons from successful experiences
        success_lessons: dict[str, list[str]] = {}
        for e in experiences:
            if e.success and e.lessons:
                for lesson in e.lessons:
                    key = lesson[:80]
                    success_lessons.setdefault(key, []).append(e.id)

        for lesson, exp_ids in success_lessons.items():
            if len(exp_ids) >= 3:
                proposals.append(PolicyProposal(
                    title=f"Apply lesson: {lesson[:80]}",
                    description=f"Lesson from {len(exp_ids)} successful experiences.",
                    target_policy="execution_strategy",
                    proposed_change=f"Incorporate lesson into execution strategy: {lesson[:200]}",
                    supporting_experiences=tuple(exp_ids[:10]),
                    confidence=min(0.85, 0.4 + len(exp_ids) * 0.1),
                    expected_impact="Improved execution strategy based on proven patterns.",
                ))
        return proposals
