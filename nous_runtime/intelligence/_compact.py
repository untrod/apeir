"""Compact internal candidate representation and optimized Pareto reduction.

Internal-only module. Public API in scheduler.py remains unchanged.
The compact representation is NOT persisted as the canonical contract.
"""

from __future__ import annotations

import math
from typing import Any

# Dimension classification — must stay in sync with scheduler.py
POSITIVE_DIMS = frozenset({"expected_quality", "reliability", "capability_fit", "privacy_fit", "information_gain", "reversibility"})
NEGATIVE_DIMS = frozenset({"cost", "latency", "risk", "uncertainty"})
ALL_DIMS = POSITIVE_DIMS | NEGATIVE_DIMS
DIM_ORDER: tuple[str, ...] = tuple(sorted(ALL_DIMS))
DIM_INDEX: dict[str, int] = {dim: idx for idx, dim in enumerate(DIM_ORDER)}
DIM_COUNT = len(DIM_ORDER)

# Direction: True = maximize (higher is better), False = minimize (lower is better)
DIM_MAXIMIZE: tuple[bool, ...] = tuple(dim in POSITIVE_DIMS for dim in DIM_ORDER)


def _bounded(value: float) -> float:
    """Clamp to [0, 1], reject non-finite."""
    if not math.isfinite(value):
        return 0.0
    return min(max(value, 0.0), 1.0)


def _normalize_raw(dim: str, raw_value: Any) -> float:
    """Normalize a single raw value to [0, 1]. Fast, no allocations."""
    if raw_value is None:
        return 0.5
    try:
        v = float(raw_value)
    except (TypeError, ValueError):
        return 0.5
    if not math.isfinite(v):
        return 0.5
    if dim in POSITIVE_DIMS:
        return _bounded(v)
    if dim == "latency":
        return _bounded(1.0 - min(v, 5000.0) / 5000.0)
    if dim == "cost":
        return _bounded(1.0 - min(v, 1.0))
    if dim in {"risk", "uncertainty"}:
        return _bounded(1.0 - v)
    return _bounded(v)


class CompactCandidate:
    """Precomputed, allocation-free internal representation for scheduler hot path.

    One-time feature extraction. No dict lookups, Enum access, or dataclass
    traversal inside Pareto comparison loops.
    """

    __slots__ = (
        "index",           # stable integer index
        "candidate_id",    # str
        "vector",          # tuple[float, ...] of normalized values, length DIM_COUNT
        "eligible",        # bool
        "cap_sig",         # int — hash of frozenset of capability strings
        "fallback_tier",   # bool — is fallback-only
        "cap_set",         # frozenset[str] — for unique capability check
    )

    def __init__(
        self,
        index: int,
        candidate_id: str,
        vector: tuple[float, ...],
        eligible: bool,
        cap_set: frozenset[str],
        fallback_tier: bool,
    ) -> None:
        self.index = index
        self.candidate_id = candidate_id
        self.vector = vector
        self.eligible = eligible
        self.cap_set = cap_set
        self.cap_sig = hash(cap_set) if cap_set else 0
        self.fallback_tier = fallback_tier

    def __repr__(self) -> str:
        return f"CompactCandidate({self.candidate_id}, idx={self.index}, eligible={self.eligible})"


def build_compact_candidates(
    candidates: tuple[Any, ...],
    context: Any,
) -> list[CompactCandidate]:
    """Build compact representation from DecisionCandidate tuples.

    Each candidate's metadata is extracted once. Feature values are normalized
    once per scheduling execution.
    """

    result: list[CompactCandidate] = []
    for idx, candidate in enumerate(candidates):
        # Extract metadata once
        metadata = candidate.metadata
        raw_features: dict[str, Any] = {}

        # Build feature values inline (avoids creating DecisionFeature objects)
        stale_set = set(_as_list_fast(metadata.get("stale_features")))
        raw_features["expected_quality"] = metadata.get("quality", metadata.get("expected_quality"))
        raw_features["reliability"] = metadata.get("success_rate", metadata.get("reliability"))
        raw_features["capability_fit"] = _capability_fit_fast(metadata, context)
        raw_features["privacy_fit"] = metadata.get("privacy_fit", 1.0 if metadata.get("local") else None)
        raw_features["information_gain"] = metadata.get("information_gain")
        raw_features["reversibility"] = metadata.get("reversibility")
        raw_features["cost"] = metadata.get("cost")
        raw_features["latency"] = metadata.get("latency_ms", metadata.get("avg_latency_ms"))
        raw_features["risk"] = _risk_value_fast(metadata.get("risk"))

        # Normalize each dimension once
        vector_parts: list[float] = []
        for dim in DIM_ORDER:
            raw = raw_features.get(dim)
            # Stale values are treated as half-penalty
            if dim in stale_set:
                base = _normalize_raw(dim, raw)
                vector_parts.append(base * 0.5 + 0.25)  # halfway to neutral
            else:
                vector_parts.append(_normalize_raw(dim, raw))

        vector = tuple(vector_parts)

        # Capabilities
        caps_raw = metadata.get("capabilities") or ()
        cap_set = frozenset(str(c) for c in caps_raw)

        fallback_tier = bool(metadata.get("fallback_only"))

        result.append(CompactCandidate(
            index=idx,
            candidate_id=candidate.candidate_id,
            vector=vector,
            eligible=True,  # will be updated after constraint/policy check
            cap_set=cap_set,
            fallback_tier=fallback_tier,
        ))

    return result


def optimized_pareto_reduction(
    compact_candidates: list[CompactCandidate],
    *,
    preserve_fallback: bool = True,
) -> tuple[list[CompactCandidate], list[tuple[int, int, int]]]:
    """Optimized Pareto reduction on compact candidates.

    Returns:
      (survivors, dominance_records)
      dominance_records: list of (dominated_idx, dominator_idx, dim_mask)

    Algorithm: O(n²) worst case, but with:
      - Grouping by capability signature to skip pointless comparisons
      - Local-variable access in hot loops (no dict/object lookups)
      - Early termination during dominance checks
      - Compact integer masks instead of string/dict operations
      - No allocations in the inner comparison loop
    """
    # Separate eligible from ineligible
    eligible = [c for c in compact_candidates if c.eligible]
    n = len(eligible)

    if n <= 1:
        return list(compact_candidates), []

    # Group by capability signature for early skip
    # Candidates with different cap sigs may still need comparison
    # (unique capability check handles this), but we can skip when
    # the sigs are identical AND we already know one dominates the other.

    # Pre-extract vectors and ids for hot loop
    vecs = [c.vector for c in eligible]
    cap_sets = [c.cap_set for c in eligible]
    fallback_flags = [c.fallback_tier for c in eligible]

    dominated: set[int] = set()  # indices into eligible
    dominance_records: list[tuple[int, int, int]] = []  # (dominated_idx, dominator_idx, dim_mask)

    # dimension metadata as local tuples for fast access
    dim_indices = tuple(range(DIM_COUNT))

    for i in range(n):
        if i in dominated:
            continue
        vi = vecs[i]
        caps_i = cap_sets[i]

        for j in range(n):
            if i == j or j in dominated:
                continue

            vj = vecs[j]

            # Check if i can dominate j
            # i dominates j when: for all dims, vi[dim] >= vj[dim]
            # AND at least one dim is strictly better

            better_or_equal = True
            strictly_better = False
            dim_mask = 0

            for d in dim_indices:
                a = vi[d]
                b = vj[d]
                if a >= b:
                    if a > b:
                        strictly_better = True
                        dim_mask |= (1 << d)
                else:
                    better_or_equal = False
                    # Early termination: if a < b and b is NOT dominated yet,
                    # check the reverse direction in a future iteration
                    break

            if better_or_equal and strictly_better:
                # Check unique capability preservation
                caps_j = cap_sets[j]
                if caps_j and caps_i and (caps_j - caps_i):
                    # j has unique capabilities that i doesn't — preserve j
                    continue

                # Check fallback preservation
                if preserve_fallback and fallback_flags[j]:
                    continue

                dominated.add(j)
                dominance_records.append((eligible[j].index, eligible[i].index, dim_mask))

    # Build survivors
    dominated_indices = {eligible[j].index for j in dominated}
    survivors = [c for c in compact_candidates if c.index not in dominated_indices]

    # Mark dominated as ineligible
    for c in compact_candidates:
        if c.index in dominated_indices:
            c.eligible = False

    return survivors, dominance_records


# fast helpers (no dataclass/Enum allocations)

def _as_list_fast(value: Any) -> list[str]:
    if value is None or value == "":
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, (list, tuple, set)):
        return [str(item) for item in value]
    return [str(value)]


def _capability_fit_fast(metadata: dict[str, Any], context: Any) -> float | None:
    required = str(context.constraints.get("required_capability") or "")
    if not required:
        return 1.0
    capabilities = set(str(item) for item in metadata.get("capabilities") or ())
    if required in capabilities:
        return 1.0
    # wildcard match
    for cap in capabilities:
        if cap.endswith("*") and required.startswith(cap[:-1]):
            return 1.0
    return 0.0


def _risk_value_fast(value: Any) -> float | None:
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return {"low": 0.2, "medium": 0.5, "high": 0.8, "critical": 1.0}.get(str(value).lower())
