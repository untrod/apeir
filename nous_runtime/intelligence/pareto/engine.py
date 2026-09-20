# -*- coding: utf-8 -*-
"""Pareto Engine — multi-objective optimization for Execution Plans.

9 objectives, all maximized internally:
  quality, safety, privacy, -latency, -cost, reliability,
  reproducibility, -resource_usage, -human_intervention.

True Pareto dominance: plan A dominates plan B iff A >= B in all dimensions
AND A > B in at least one dimension.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ParetoResult:
    """Result of Pareto frontier computation."""
    non_dominated: list[dict] = field(default_factory=list)   # [{plan_id, scores, ...}]
    dominated: list[dict] = field(default_factory=list)
    dominance_explanations: dict[str, list[str]] = field(default_factory=dict)  # plan_id → [explanation]
    trade_off_summary: str = ""
    constraint_boundaries: dict[str, tuple[float, float]] = field(default_factory=dict)


def dominates(a: dict[str, float], b: dict[str, float], objectives: list[str]) -> bool:
    """True if plan A dominates plan B across given objectives.

    All objectives must be oriented so that HIGHER = BETTER.
    """
    at_least_one_better = False
    for obj in objectives:
        va = a.get(obj, 0.0)
        vb = b.get(obj, 0.0)
        if va < vb:
            return False
        if va > vb:
            at_least_one_better = True
    return at_least_one_better


class ParetoEngine:
    """Multi-objective Pareto frontier computation for Execution Plans.

    Objectives (all maximized):
      quality_score, safety_score, privacy_score,
      -latency_ms (negated), -cost_usd (negated),
      reliability_score, reproducibility_score,
      -resource_usage (negated), -human_intervention_prob (negated)

    Never collapses to a single scalar.
    """

    OBJECTIVES = [
        "quality_score", "safety_score", "privacy_score",
        "neg_latency", "neg_cost", "reliability_score",
        "reproducibility_score", "neg_resource_usage", "neg_human_intervention",
    ]

    def compute_frontier(self, plans: list[dict[str, Any]]) -> ParetoResult:
        """Compute the Pareto frontier for a list of scored plans.

        Each plan dict must have: plan_id, and all 9 objective scores.
        """
        if not plans:
            return ParetoResult()

        # Normalize objectives so higher = better
        scored = [self._normalize_plan(p) for p in plans]

        n = len(scored)
        dominated = [False] * n
        dominating: list[list[int]] = [[] for _ in range(n)]

        # O(n²) Pareto computation with capability-grouped early termination
        objectives = self.OBJECTIVES
        for i in range(n):
            if dominated[i]:
                continue
            for j in range(n):
                if i == j:
                    continue
                if dominates(scored[i], scored[j], objectives):
                    dominated[j] = True
                    dominating[i].append(j)

        # Separate into non-dominated and dominated
        non_dominated = []
        dominated_list = []
        explanations = {}

        for i in range(n):
            plan = plans[i].copy()
            plan["_scores"] = scored[i]

            if dominated[i]:
                # Find who dominates this plan
                dominators = [j for j in range(n) if j != i and dominates(scored[j], scored[i], objectives)]
                plan["_dominated_by"] = [plans[j].get("plan_id", "") for j in dominators]
                dominated_list.append(plan)
            else:
                non_dominated.append(plan)

        # Generate explanations
        for plan in non_dominated:
            pid = plan.get("plan_id", "")
            scores = plan.get("_scores", {})
            strengths = [obj for obj in objectives if scores.get(obj, 0) > 0.7]
            weaknesses = [obj for obj in objectives if scores.get(obj, 0) < 0.3]
            explanations[pid] = [
                f"Strengths: {', '.join(strengths) if strengths else 'none dominant'}",
                f"Weaknesses: {', '.join(weaknesses) if weaknesses else 'none significant'}",
            ]

        # Trade-off summary
        if len(non_dominated) > 1:
            trade_off = (
                f"{len(non_dominated)} non-dominated plans across "
                f"{len(objectives)} objectives. "
                f"Trade-offs exist between "
                f"{self._identify_tradeoffs(non_dominated)}"
            )
        else:
            trade_off = "Single non-dominated plan found (no trade-offs)"

        return ParetoResult(
            non_dominated=non_dominated,
            dominated=dominated_list,
            dominance_explanations=explanations,
            trade_off_summary=trade_off,
        )

    def _normalize_plan(self, plan: dict) -> dict[str, float]:
        """Convert plan metadata to objective scores (all maximized)."""
        scores = {}

        # Quality: from capability level
        cap = str(plan.get("model_capability_level", "competent")).lower()
        scores["quality_score"] = {"expert": 1.0, "advanced": 0.8, "competent": 0.6, "basic": 0.4, "novice": 0.2}.get(cap, 0.5)

        # Safety: from risk mitigation
        risk = str(plan.get("risk_class", "low"))
        scores["safety_score"] = {"low": 1.0, "medium": 0.8, "high": 0.5, "critical": 0.2}.get(risk, 0.7)

        # Privacy: from data locality
        privacy = str(plan.get("privacy_class", "internal"))
        scores["privacy_score"] = {"restricted": 1.0, "confidential": 0.8, "internal": 0.5, "public": 0.3}.get(privacy, 0.5)

        # Negated latency (higher = faster)
        lat = float(plan.get("estimated_latency_ms", 1000) or 1000)
        scores["neg_latency"] = max(0.0, 1.0 - lat / 120000)  # normalize against 2min

        # Negated cost (higher = cheaper)
        cost = float(plan.get("estimated_cost_usd", 0.01) or 0.01)
        scores["neg_cost"] = max(0.0, 1.0 - cost / 1.0)  # normalize against $1

        # Reliability
        scores["reliability_score"] = float(plan.get("model_success_rate", 0.8) or 0.8)

        # Reproducibility
        temp = float(plan.get("model_temperature", 0.5) or 0.5)
        scores["reproducibility_score"] = 1.0 - temp

        # Negated resource usage (higher = more efficient)
        mem = float(plan.get("estimated_memory_mb", 1024) or 1024)
        scores["neg_resource_usage"] = max(0.0, 1.0 - mem / 32000)

        # Negated human intervention probability
        hi_risk = {"low": 0.05, "medium": 0.15, "high": 0.40, "critical": 0.70}
        scores["neg_human_intervention"] = 1.0 - hi_risk.get(risk, 0.15)

        return scores

    def _identify_tradeoffs(self, non_dominated: list[dict]) -> str:
        """Identify which objectives have significant trade-offs."""
        ranges = {}
        obj_names = [o.replace("neg_", "") for o in self.OBJECTIVES]
        for i, obj in enumerate(self.OBJECTIVES):
            vals = [p.get("_scores", {}).get(obj, 0) for p in non_dominated]
            if vals and max(vals) - min(vals) > 0.3:
                ranges[obj_names[i]] = (min(vals), max(vals))

        if not ranges:
            return "no significant dimensions"
        top_tradeoffs = sorted(ranges.items(), key=lambda x: x[1][1] - x[1][0], reverse=True)[:3]
        return ", ".join(f"{name} ({lo:.2f}–{hi:.2f})" for name, (lo, hi) in top_tradeoffs)
