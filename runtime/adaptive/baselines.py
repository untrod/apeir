"""
Deterministic baselines for adaptive intelligence.

Per LMetric (OSDI'26): simple multiplication scoring can match or exceed
heavily-tuned complex methods. Nous MUST implement these as formal,
tested, documented baselines before adding Bandit/BO methods.

These are PURE FUNCTIONS — no side effects, no I/O, no learned parameters.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable


@dataclass(frozen=True)
class CandidateScore:
    """A scored candidate from any scoring strategy."""

    candidate_id: str
    quality_score: float
    latency_score: float
    cost_score: float
    reliability_score: float
    privacy_score: float
    composite_score: float
    rank: int = 0
    strategy: str = "multiplication"


@dataclass
class MultiplicationScorer:
    """Simple multiplicative scoring — the GOLD BASELINE.

    score = Π(weight_i × estimated_i)

    Where weights are configurable per workload class.
    This is intentionally simple — no neural network, no learned parameters.
    The complexity is in getting the estimates right, not in the scoring function.

    Reference: LMetric (OSDI'26) — "Simple Is Better: Multiplication May Be
    All You Need for LLM Request Scheduling"
    """

    quality_weight: float = 0.35
    latency_weight: float = 0.20
    cost_weight: float = 0.20
    reliability_weight: float = 0.15
    privacy_weight: float = 0.10
    normalize_weights: bool = True

    def __post_init__(self) -> None:
        if self.normalize_weights:
            total = (
                self.quality_weight
                + self.latency_weight
                + self.cost_weight
                + self.reliability_weight
                + self.privacy_weight
            )
            if total > 0:
                self.quality_weight /= total
                self.latency_weight /= total
                self.cost_weight /= total
                self.reliability_weight /= total
                self.privacy_weight /= total

        # Validate weights are non-negative
        for name in [
            "quality_weight",
            "latency_weight",
            "cost_weight",
            "reliability_weight",
            "privacy_weight",
        ]:
            val = getattr(self, name)
            if val < 0:
                raise ValueError(f"{name} must be non-negative, got {val}")

    def score(
        self,
        candidate_id: str,
        estimated_quality: float,
        estimated_latency_ms: float,
        estimated_cost: float,
        estimated_reliability: float = 0.99,
        estimated_privacy: float = 1.0,
        latency_scale_ms: float = 1000.0,
        cost_scale: float = 0.01,
    ) -> CandidateScore:
        """Score a single candidate.

        Quality and reliability are directly proportional (higher = better).
        Latency and cost are inversely proportional (lower = better),
        scaled to avoid division-by-zero and to normalize ranges.
        """
        # Higher is better for all normalized values
        quality_norm = max(0.0, min(1.0, estimated_quality))
        latency_norm = latency_scale_ms / max(
            1.0, estimated_latency_ms
        )  # 1ms → 1.0, 1000ms → 1.0
        cost_norm = cost_scale / max(0.0001, estimated_cost)  # $0.01 → 1.0
        reliability_norm = max(0.0, min(1.0, estimated_reliability))
        privacy_norm = max(0.0, min(1.0, estimated_privacy))

        quality_term = self.quality_weight * quality_norm
        latency_term = self.latency_weight * min(
            latency_norm, 10.0
        )  # Cap latency benefit
        cost_term = self.cost_weight * min(cost_norm, 10.0)  # Cap cost benefit
        reliability_term = self.reliability_weight * reliability_norm
        privacy_term = self.privacy_weight * privacy_norm

        composite = (
            quality_term + latency_term + cost_term + reliability_term + privacy_term
        )

        return CandidateScore(
            candidate_id=candidate_id,
            quality_score=quality_term,
            latency_score=latency_term,
            cost_score=cost_term,
            reliability_score=reliability_term,
            privacy_score=privacy_term,
            composite_score=composite,
            strategy="multiplication",
        )

    def rank(
        self,
        candidates: list[tuple[str, float, float, float, float, float]],
    ) -> list[CandidateScore]:
        """Score and rank multiple candidates. Returns sorted by composite score descending.

        Each tuple: (candidate_id, estimated_quality, estimated_latency_ms, estimated_cost,
                      estimated_reliability, estimated_privacy)
        """
        scored = [
            self.score(cid, q, lat, cost, rel, priv)
            for cid, q, lat, cost, rel, priv in candidates
        ]
        scored.sort(key=lambda s: s.composite_score, reverse=True)
        for i, s in enumerate(scored):
            object.__setattr__(s, "rank", i + 1)
        return scored


@dataclass
class ParetoRanker:
    """Pareto-optimal ranking — the SECOND baseline.

    Identifies the Pareto frontier of non-dominated candidates across
    multiple objectives. A candidate dominates another if it is better
    or equal in all dimensions and strictly better in at least one.

    This is useful when there is no single "best" candidate and the
    decision requires trade-off visualization.
    """

    objectives: list[str] = field(
        default_factory=lambda: ["quality", "latency", "cost", "reliability", "privacy"]
    )
    # For each objective, True means higher is better
    higher_is_better: dict[str, bool] = field(
        default_factory=lambda: {
            "quality": True,
            "latency": False,
            "cost": False,
            "reliability": True,
            "privacy": True,
        }
    )

    def dominates(self, a: dict[str, float], b: dict[str, float]) -> bool:
        """Check if candidate 'a' dominates candidate 'b'.

        a dominates b if:
        - a is not worse than b in any objective
        - a is strictly better than b in at least one objective
        """
        at_least_one_better = False
        for obj in self.objectives:
            a_val = a.get(obj, 0.0)
            b_val = b.get(obj, 0.0)
            higher_good = self.higher_is_better.get(obj, True)

            if higher_good:
                if a_val < b_val:
                    return False  # a is worse in this objective
                if a_val > b_val:
                    at_least_one_better = True
            else:
                if a_val > b_val:
                    return False  # a is worse (higher latency/cost)
                if a_val < b_val:
                    at_least_one_better = True

        return at_least_one_better

    def find_pareto_frontier(self, candidates: list[dict[str, float]]) -> list[int]:
        """Return indices of candidates on the Pareto frontier."""
        n = len(candidates)
        dominated = [False] * n

        for i in range(n):
            for j in range(n):
                if i == j:
                    continue
                if self.dominates(candidates[j], candidates[i]):
                    dominated[i] = True
                    break

        return [i for i in range(n) if not dominated[i]]

    def rank_by_frontier(
        self, candidates: list[dict[str, float]]
    ) -> list[dict[str, float]]:
        """Rank candidates by Pareto frontier layers.

        Layer 0 = Pareto frontier
        Layer 1 = Pareto frontier of remaining
        etc.
        """
        remaining = list(range(len(candidates)))
        rankings: list[dict[str, float]] = []

        layer = 0
        while remaining:
            remaining_candidates = [candidates[i] for i in remaining]
            frontier_indices = self.find_pareto_frontier(remaining_candidates)

            for fi in frontier_indices:
                ranked = dict(candidates[remaining[fi]])
                ranked["pareto_layer"] = float(layer)
                rankings.append(ranked)

            # Remove frontier from remaining
            frontier_original = [remaining[fi] for fi in frontier_indices]
            remaining = [r for r in remaining if r not in frontier_original]
            layer += 1

        return rankings


class DeterministicRouter:
    """Deterministic model router — used when adaptive_routing is disabled.

    This is the RC9-equivalent routing logic. It filters candidates through
    hard constraints, then scores with multiplication scoring.
    """

    def __init__(self) -> None:
        self._scorer = MultiplicationScorer()

    def route(
        self,
        candidates: list[dict],
        constraints: dict[str, Callable[[dict], bool]] | None = None,
    ) -> CandidateScore | None:
        """Route to the best candidate, filtered by constraints.

        Returns None if no candidate passes all constraints.
        """
        # Filter through hard constraints
        filtered = candidates
        if constraints:
            for name, check_fn in constraints.items():
                filtered = [c for c in filtered if check_fn(c)]
                if not filtered:
                    return None

        if not filtered:
            return None

        # Score and select best
        scored = []
        for c in filtered:
            s = self._scorer.score(
                candidate_id=c.get("id", "unknown"),
                estimated_quality=c.get("quality", 0.5),
                estimated_latency_ms=c.get("latency_ms", 1000.0),
                estimated_cost=c.get("cost", 0.01),
                estimated_reliability=c.get("reliability", 0.99),
                estimated_privacy=c.get("privacy", 1.0),
            )
            scored.append(s)

        scored.sort(key=lambda s: s.composite_score, reverse=True)
        return scored[0] if scored else None


# Convenience function: create the gold baseline scorer.
def gold_baseline_scorer() -> MultiplicationScorer:
    """Create the gold baseline scorer with default weights.

    This is the first scorer that should be used in any adaptive experiment.
    It is the reference against which all learning-based methods are compared.
    """
    return MultiplicationScorer()
