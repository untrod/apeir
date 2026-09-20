"""Reference Pareto reduction — simple, obviously correct implementation for testing.

This module is for test-only semantic verification. It is NOT used in production hot paths.
"""

from __future__ import annotations

import math
from typing import Any

# Dimension classification — must match scheduler.py
POSITIVE_DIMS = {"expected_quality", "reliability", "capability_fit", "privacy_fit", "information_gain", "reversibility"}
NEGATIVE_DIMS = {"cost", "latency", "risk", "uncertainty"}
ALL_DIMS = POSITIVE_DIMS | NEGATIVE_DIMS


def _bounded(value: float) -> float:
    if not math.isfinite(value):
        return 0.0
    return min(max(value, 0.0), 1.0)


def _normalize_value(name: str, value: Any) -> float:
    """Normalize a raw feature value to [0, 1] — mirrors scheduler._normalize_feature."""
    if value is None:
        return 0.5
    try:
        v = float(value)
    except (TypeError, ValueError):
        return 0.5
    if not math.isfinite(v):
        return 0.5
    if name in POSITIVE_DIMS:
        return _bounded(v)
    if name == "latency":
        return _bounded(1.0 - min(v, 5000.0) / 5000.0)
    if name == "cost":
        return _bounded(1.0 - min(v, 1.0))
    if name in {"risk", "uncertainty"}:
        return _bounded(1.0 - v)
    return _bounded(v)


def reference_pareto_frontier(
    candidates: list[dict[str, Any]],
    *,
    preserve_fallback: bool = True,
    preserve_unique_capabilities: bool = True,
    missing_value_penalty: float = 0.08,
) -> list[dict[str, Any]]:
    """Reference Pareto reduction — simple, readable O(n²) with explicit semantics.

    Each candidate dict must have:
      - "candidate_id": str
      - "features": dict[str, float | None]  (raw values)
      - "capabilities": set[str] | None
      - "fallback_only": bool
      - "eligible": bool

    Returns candidates with "dominated_by" set and "pareto_rejected" flag.

    Dominance rule:
      A dominates B when:
        - For every dimension, A's normalized value >= B's normalized value
        - For at least one dimension, A's normalized value > B's normalized value
        - A must be at least as good on ALL dimensions

    Preservation:
      - Candidates with unique capabilities (not present in dominator) are preserved
      - fallback_only candidates are preserved when preserve_fallback=True
    """
    dims = sorted(ALL_DIMS)

    # Build normalized vectors
    normalized: dict[str, dict[str, float]] = {}
    for c in candidates:
        cid = c["candidate_id"]
        features = c.get("features", {})
        norm = {}
        for dim in dims:
            raw = features.get(dim)
            norm[dim] = _normalize_value(dim, raw)
        normalized[cid] = norm

    # Determine dominance
    dominated_by: dict[str, list[str]] = {c["candidate_id"]: [] for c in candidates}
    eligible = [c for c in candidates if c.get("eligible", True)]

    for i, a in enumerate(eligible):
        aid = a["candidate_id"]
        a_caps = set(a.get("capabilities") or [])
        for j, b in enumerate(eligible):
            bid = b["candidate_id"]
            if aid == bid:
                continue

            # Check unique capability preservation
            if preserve_unique_capabilities:
                b_caps = set(b.get("capabilities") or [])
                if b_caps - a_caps:  # b has capabilities a doesn't
                    continue

            # Check dominance: a dominates b?
            a_vec = normalized[aid]
            b_vec = normalized[bid]

            better_or_equal = all(a_vec[dim] >= b_vec[dim] for dim in dims)
            strictly_better = any(a_vec[dim] > b_vec[dim] for dim in dims)

            if better_or_equal and strictly_better:
                dominated_by[bid].append(aid)

    # Build result
    result = []
    for c in candidates:
        cid = c["candidate_id"]
        dominators = dominated_by[cid]
        is_fallback = bool(c.get("fallback_only"))
        is_dominated = bool(dominators) and not (preserve_fallback and is_fallback)

        entry = dict(c)
        entry["dominated_by"] = sorted(dominators)
        entry["pareto_rejected"] = is_dominated
        if is_dominated:
            entry["eligible"] = False
        result.append(entry)

    return result


def reference_frontier_ids(
    candidates: list[dict[str, Any]],
    **kwargs: Any,
) -> set[str]:
    """Return the set of candidate IDs that survive Pareto reduction."""
    result = reference_pareto_frontier(candidates, **kwargs)
    return {c["candidate_id"] for c in result if not c["pareto_rejected"]}


def build_test_candidate(
    candidate_id: str,
    features: dict[str, float | None] | None = None,
    *,
    capabilities: set[str] | None = None,
    fallback_only: bool = False,
    eligible: bool = True,
) -> dict[str, Any]:
    """Build a test candidate dict for the reference implementation."""
    return {
        "candidate_id": candidate_id,
        "features": dict(features or {}),
        "capabilities": capabilities or set(),
        "fallback_only": fallback_only,
        "eligible": eligible,
    }
