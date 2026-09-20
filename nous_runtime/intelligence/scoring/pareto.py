"""Deterministic O(n²) Pareto frontier for small model candidate sets."""

from __future__ import annotations

from collections.abc import Sequence

from nous_runtime.intelligence.scoring.utility import CandidateScore


def dominates(left: CandidateScore, right: CandidateScore) -> bool:
    left_objectives = _objectives(left)
    right_objectives = _objectives(right)
    no_worse = all(a >= b for a, b in zip(left_objectives, right_objectives))
    strictly_better = any(a > b for a, b in zip(left_objectives, right_objectives))
    return no_worse and strictly_better


def pareto_frontier(candidates: Sequence[CandidateScore]) -> frozenset[str]:
    eligible = [candidate for candidate in candidates if candidate.eligible]
    frontier: set[str] = set()
    for candidate in eligible:
        if not any(
            other.model_id != candidate.model_id and dominates(other, candidate)
            for other in eligible
        ):
            frontier.add(candidate.model_id)
    return frozenset(frontier)


def deterministic_sort(
    candidates: Sequence[CandidateScore],
) -> list[CandidateScore]:
    def key(candidate: CandidateScore) -> tuple[object, ...]:
        return (
            not candidate.eligible,
            not candidate.pareto_optimal,
            -(candidate.score if candidate.score is not None else -1.0),
            -candidate.confidence,
            -candidate.reliability,
            candidate.estimated_cost
            if candidate.estimated_cost is not None
            else float("inf"),
            candidate.latency_ms
            if candidate.latency_ms is not None
            else float("inf"),
            candidate.model_id,
        )

    return sorted(candidates, key=key)


def _objectives(candidate: CandidateScore) -> tuple[float, ...]:
    breakdown = candidate.breakdown
    if breakdown is None:
        return (-1.0, -1.0, -1.0, -1.0, -1.0)
    return (
        breakdown.adjusted_fit,
        candidate.reliability,
        -breakdown.normalized_cost,
        -breakdown.normalized_latency,
        -breakdown.uncertainty,
    )


__all__ = ["deterministic_sort", "dominates", "pareto_frontier"]
