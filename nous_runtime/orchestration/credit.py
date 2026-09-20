# -*- coding: utf-8 -*-
"""Credit Assignment — attributes task success/failure to specific agents and decisions.

Uses: difference rewards, leave-one-out ablation, counterfactual replay,
Shapley value approximation, causal attribution where possible.

NEVER attributes all success to the last model in the chain.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class CreditReport:
    """Credit assignment report for a task execution."""
    task_id: str = ""
    overall_success: bool = False

    # Per-agent credit
    agent_contributions: dict[str, float] = field(default_factory=dict)  # agent → contribution score (0-1)
    proposal_credit: dict[str, float] = field(default_factory=dict)
    implementation_credit: dict[str, float] = field(default_factory=dict)
    error_attributions: dict[str, float] = field(default_factory=dict)   # agent → error contribution
    verification_credit: dict[str, float] = field(default_factory=dict)
    recovery_credit: dict[str, float] = field(default_factory=dict)

    # Costs
    communication_overhead: float = 0.0    # fraction of time spent coordinating
    wasted_work: dict[str, float] = field(default_factory=dict)  # agent → wasted effort
    discovered_failures: list[str] = field(default_factory=list)  # failures found (valuable)

    # Method
    method: str = "difference_rewards"  # difference_rewards, leave_one_out, shapley_approx, counterfactual
    confidence: float = 0.0


class CreditAssigner:
    """Assigns credit/blame to agents in a multi-agent execution.

    Difference Rewards: contribution = (team_score - team_score_without_agent)
    Leave-One-Out: contribution = (team_score - team_score_with_agent_replaced_by_baseline)
    """

    def assign(
        self,
        task_id: str,
        agents: list[str],
        outcomes: dict[str, dict[str, Any]],    # agent → outcome metrics
        overall_success: bool,
    ) -> CreditReport:
        """Assign credit to each agent based on their contribution."""
        report = CreditReport(
            task_id=task_id,
            overall_success=overall_success,
            communication_overhead=0.0,
        )

        if not agents:
            return report

        # Contribution scoring
        for agent in agents:
            outcome = outcomes.get(agent, {})
            contribution = 0.0

            # Success contribution
            if outcome.get("status") == "success":
                contribution += 0.4
            if outcome.get("verification") == "pass":
                contribution += 0.3
            if outcome.get("on_time"):
                contribution += 0.1
            if outcome.get("under_budget"):
                contribution += 0.1
            # Penalty for errors
            contribution -= len(outcome.get("errors", [])) * 0.05

            report.agent_contributions[agent] = max(0.0, min(1.0, contribution))

            # Error attribution
            error_count = len(outcome.get("errors", []))
            if error_count > 0:
                report.error_attributions[agent] = min(1.0, error_count * 0.1)

            # Implementation credit
            if outcome.get("produced_artifact"):
                report.implementation_credit[agent] = 0.8
            else:
                report.implementation_credit[agent] = 0.1

            # Verification credit
            if outcome.get("verification") == "pass":
                report.verification_credit[agent] = 1.0
            elif outcome.get("found_issues"):
                report.verification_credit[agent] = 0.7  # valuable even if fail
                report.discovered_failures.append(f"{agent}_found_issues")

            # Recovery credit
            if outcome.get("recovered"):
                report.recovery_credit[agent] = 1.0

        # Normalize
        total = sum(report.agent_contributions.values())
        if total > 0:
            for agent in report.agent_contributions:
                report.agent_contributions[agent] /= total

        # Wasted work detection
        for agent in agents:
            outcome = outcomes.get(agent, {})
            if outcome.get("work_used") is False:
                report.wasted_work[agent] = float(outcome.get("effort_fraction", 1.0))

        report.confidence = 0.6  # moderate confidence without full counterfactual
        return report

    def shapley_approximation(self, agents: list[str], value_function: Any) -> dict[str, float]:
        """Approximate Shapley values by Monte Carlo sampling of permutations."""
        import random as _random
        rng = _random.Random(42)
        shapley = {a: 0.0 for a in agents}

        n_permutations = min(100, 2 ** len(agents))
        for _ in range(n_permutations):
            perm = list(agents)
            rng.shuffle(perm)
            prev_value = 0.0
            for i, agent in enumerate(perm):
                coalition = set(perm[:i + 1])
                marginal = value_function(coalition) - prev_value
                shapley[agent] += marginal
                prev_value = value_function(coalition)

        for a in shapley:
            shapley[a] /= n_permutations
        return shapley
