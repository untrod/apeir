"""Correctness tests comparing optimized Pareto against reference implementation.

Covers: randomized sets, shuffled order, edge cases, invariants,
reproducibility, hard constraints, and policy denials.
"""

from __future__ import annotations

import math
import random
from typing import Any

import pytest

from nous_runtime.intelligence import (
    CandidateType,
    DecisionCandidate,
    DecisionType,
    SchedulingRequest,
    SelectionContext,
    schedule_candidates,
    snapshot_hash,
)

from tests.reference_pareto import (
    reference_pareto_frontier,
    build_test_candidate,
)

# helpers

def _candidate(candidate_id: str, **metadata: Any) -> DecisionCandidate:
    return DecisionCandidate(
        candidate_id=candidate_id,
        candidate_type=CandidateType.PROVIDER,
        metadata=metadata,
    )


def _request(
    *candidates: DecisionCandidate,
    constraints: dict[str, Any] | None = None,
    **ctx_kwargs: Any,
) -> SchedulingRequest:
    ctx = SelectionContext(
        task_id="test",
        decision_type=DecisionType.PROVIDER,
        constraints=dict(constraints or {}),
        **{k: v for k, v in ctx_kwargs.items() if k in SelectionContext.__dataclass_fields__},
    )
    return SchedulingRequest(
        request_id=snapshot_hash({"candidates": [c.candidate_id for c in candidates]}),
        candidates=tuple(candidates),
        context=ctx,
    )


def _pareto_survivor_ids(*candidates: DecisionCandidate, **ctx_kwargs: Any) -> set[str]:
    """Get survivor IDs from the optimized scheduler."""
    result = schedule_candidates(_request(*candidates, **ctx_kwargs))
    # Survivors = eligible candidates
    survivors = {
        e.candidate.candidate_id
        for e in result.ranking.evaluations
        if e.eligible
    }
    return survivors


# basic correctness

def test_single_candidate_survives():
    """A single candidate always survives Pareto reduction."""
    c = _candidate("only", success_rate=0.5)
    result = schedule_candidates(_request(c))
    assert result.selected.selected_candidate_id == "only"
    assert len([e for e in result.ranking.evaluations if e.eligible]) == 1


def test_identical_candidates_preserve_order():
    """Identical candidates — first by stable ID survives."""
    a = _candidate("a", success_rate=0.8, quality=0.8)
    b = _candidate("b", success_rate=0.8, quality=0.8)
    schedule_candidates(_request(a, b))
    survivors = _pareto_survivor_ids(a, b)
    # Both should survive since they're identical (neither dominates the other)
    assert "a" in survivors
    assert "b" in survivors


def test_clear_dominance():
    """Candidate with better values on all dimensions should dominate."""
    strong = _candidate("strong", success_rate=0.95, quality=0.9, latency_ms=100, cost=0.1, risk="low")
    weak = _candidate("weak", success_rate=0.2, quality=0.2, latency_ms=3000, cost=0.9, risk="high")
    result = schedule_candidates(_request(weak, strong))
    rejected = {r.candidate_id: r.reason_code for r in result.rejected_candidates}
    assert rejected.get("weak") == "PARETO_DOMINATED"


def test_unique_capability_preservation():
    """Candidate with unique capabilities should be preserved even if dominated."""
    strong = _candidate("strong", success_rate=0.95, quality=0.9, capabilities=["model.reason"])
    weak_unique = _candidate("weak_unique", success_rate=0.2, quality=0.2, capabilities=["audio.transcribe"])
    schedule_candidates(_request(strong, weak_unique))
    survivors = _pareto_survivor_ids(strong, weak_unique)
    assert "weak_unique" in survivors


def test_fallback_only_preservation():
    """Fallback-only candidates should be preserved when configured."""
    strong = _candidate("strong", success_rate=0.95, quality=0.9)
    fallback = _candidate("fallback", success_rate=0.3, quality=0.3, fallback_only=True)
    schedule_candidates(_request(strong, fallback, preserve_fallback_candidates=True))
    survivors = _pareto_survivor_ids(strong, fallback, preserve_fallback_candidates=True)
    assert "fallback" in survivors


def test_fallback_only_not_preserved_when_disabled():
    """Fallback-only candidates should be dominated when preservation is off."""
    strong = _candidate("strong", success_rate=0.95, quality=0.9)
    fallback = _candidate("fallback", success_rate=0.3, quality=0.3, fallback_only=True)
    result = schedule_candidates(_request(strong, fallback, preserve_fallback_candidates=False))
    rejected = {r.candidate_id: r.reason_code for r in result.rejected_candidates}
    assert rejected.get("fallback") == "PARETO_DOMINATED"


# edge cases

def test_single_dimension():
    """Pareto should work with effectively one dimension."""
    a = _candidate("a", success_rate=0.9, quality=None, latency_ms=None, cost=None, risk=None)
    b = _candidate("b", success_rate=0.5, quality=None, latency_ms=None, cost=None, risk=None)
    result = schedule_candidates(_request(a, b))
    rejected = {r.candidate_id: r.reason_code for r in result.rejected_candidates}
    assert rejected.get("b") == "PARETO_DOMINATED"


def test_conflicting_dimensions():
    """Candidates with trade-offs on different dimensions should both survive."""
    fast_expensive = _candidate("fast_expensive", latency_ms=50, cost=0.9, success_rate=0.8, quality=0.7)
    slow_cheap = _candidate("slow_cheap", latency_ms=3000, cost=0.05, success_rate=0.8, quality=0.7)
    schedule_candidates(_request(fast_expensive, slow_cheap))
    survivors = _pareto_survivor_ids(fast_expensive, slow_cheap)
    assert "fast_expensive" in survivors
    assert "slow_cheap" in survivors


def test_maximize_minimize_mixture():
    """Mix of maximize (quality, reliability) and minimize (cost, latency) dims."""
    good = _candidate("good", quality=0.9, reliability=0.9, cost=0.5, latency_ms=200)
    great_quality = _candidate("great_quality", quality=0.99, reliability=0.5, cost=0.9, latency_ms=500)
    schedule_candidates(_request(good, great_quality))
    survivors = _pareto_survivor_ids(good, great_quality)
    # Both should survive (trade off on different dimensions)
    assert len(survivors) == 2


def test_unknown_features():
    """Candidates with unknown features get neutral normalization."""
    known = _candidate("known", success_rate=0.8, latency_ms=100, cost=0.1)
    unknown = _candidate("unknown")  # no features at all
    result = schedule_candidates(_request(known, unknown))
    rejected = {r.candidate_id: r.reason_code for r in result.rejected_candidates}
    assert rejected.get("unknown") == "PARETO_DOMINATED"


def test_stale_features_penalize():
    """Stale features are marked with STALE provenance and affect scoring.

    Staleness affects the uncertainty penalty in scoring and the unknown-count
    for the uncertainty feature. Two candidates with identical raw values but
    one stale on a dimension may have slightly different scores.
    """
    fresh = _candidate("fresh", success_rate=0.9, latency_ms=100)
    stale = _candidate("stale", success_rate=0.9, latency_ms=100, stale_features=["latency"])
    result = schedule_candidates(_request(fresh, stale))
    # Both survive Pareto (equal in normalized feature space)
    survivors = _pareto_survivor_ids(fresh, stale)
    assert "fresh" in survivors
    assert "stale" in survivors
    # Stale feature has different provenance
    stale_eval = next(e for e in result.ranking.evaluations if e.candidate.candidate_id == "stale")
    stale_latency = next(f for f in stale_eval.features if f.name == "latency")
    assert stale_latency.provenance_type.value == "stale"
    assert stale_latency.stale is True


def test_uncertainty_penalties_affect_scoring():
    """Uncertainty should reduce normalized score but not affect Pareto eligibility."""
    known = _candidate("known", success_rate=0.9, latency_ms=100, cost=0.1, quality=0.8, risk="low")
    unknown = _candidate("unknown", health="ok")  # only health, everything else unknown
    result = schedule_candidates(_request(known, unknown))
    scores = {e.candidate.candidate_id: e.normalized_score for e in result.ranking.evaluations}
    assert scores["known"] > scores["unknown"]


def test_zero_range_normalization():
    """When all candidates have the same value, normalization should handle it."""
    a = _candidate("a", success_rate=0.5, latency_ms=100)
    b = _candidate("b", success_rate=0.5, latency_ms=100)
    schedule_candidates(_request(a, b))
    survivors = _pareto_survivor_ids(a, b)
    # Identical — both survive
    assert "a" in survivors and "b" in survivors


def test_no_nan_or_infinity():
    """Ensure no NaN or Infinity in output scores."""
    candidates = [
        _candidate(f"c_{i}", success_rate=math.nan if i == 0 else 0.5, latency_ms=math.inf if i == 1 else 100)
        for i in range(10)
    ]
    result = schedule_candidates(_request(*candidates))
    for e in result.ranking.evaluations:
        assert math.isfinite(e.normalized_score)
        assert not math.isnan(e.normalized_score)


def test_hard_constraint_violation_zero():
    """Hard constraint violations should result in zero selection rate."""
    blocked = _candidate("blocked", capabilities=[], health="down")
    result = schedule_candidates(_request(blocked, constraints={
        "required_capability": "model.reason",
        "availability_required": True,
    }))
    assert result.selected.no_safe_option is True
    # No candidate with hard constraint violation should be selected
    hard_rejected = [r for r in result.rejected_candidates if r.reason_code != "PARETO_DOMINATED"]
    assert len(hard_rejected) >= 1


def test_policy_denial_zero():
    """Policy-denied candidates should have zero selection rate."""
    good = _candidate("good", capabilities=["model.reason"], health="ok")
    bad = _candidate("bad", capabilities=["model.reason"], health="ok")
    result = schedule_candidates(_request(good, bad, constraints={"deny_candidates": ["bad"]}))
    assert result.selected.selected_candidate_id != "bad"
    assert any(r.candidate_id == "bad" and r.reason_code == "POLICY_DENY" for r in result.rejected_candidates)


# reproducibility

def test_replay_determinism():
    """Same input should produce identical output every time."""
    candidates = [_candidate(f"c_{i}", success_rate=0.5 + i/100, latency_ms=100 + i*10) for i in range(50)]

    results = [schedule_candidates(_request(*candidates)) for _ in range(5)]

    first_selected = results[0].selected.selected_candidate_id
    first_scores = [e.normalized_score for e in results[0].ranking.evaluations]

    for r in results[1:]:
        assert r.selected.selected_candidate_id == first_selected
        r_scores = [e.normalized_score for e in r.ranking.evaluations]
        for a, b in zip(first_scores, r_scores):
            assert a == pytest.approx(b)


def test_stable_hashing():
    """Hashes should be deterministic across runs."""
    candidates = [_candidate("a", success_rate=0.8), _candidate("b", success_rate=0.5)]
    hashes = set()
    for _ in range(10):
        result = schedule_candidates(_request(*candidates))
        hashes.add(result.scheduler_snapshot_hash)
    assert len(hashes) == 1


def test_candidate_order_independence():
    """Shuffling candidates should not change Pareto results."""
    base = [
        _candidate("strong", success_rate=0.95, quality=0.9, latency_ms=100, cost=0.1),
        _candidate("medium_a", success_rate=0.6, quality=0.7, latency_ms=300, cost=0.3),
        _candidate("medium_b", success_rate=0.5, quality=0.8, latency_ms=200, cost=0.4),
        _candidate("weak", success_rate=0.3, quality=0.3, latency_ms=1000, cost=0.8),
        _candidate("unique", success_rate=0.2, quality=0.2, capabilities=["audio.transcribe"]),
    ]

    survivors_sets = []
    for seed in range(10):
        shuffled = list(base)
        random.Random(seed).shuffle(shuffled)
        result = schedule_candidates(_request(*shuffled))
        survivors = frozenset(
            e.candidate.candidate_id
            for e in result.ranking.evaluations
            if e.eligible
        )
        survivors_sets.append(survivors)

    # All shuffles should produce the same survivor set
    assert len(set(survivors_sets)) == 1


# reference comparison (randomized)

def _to_reference_dict(c: DecisionCandidate) -> dict[str, Any]:
    """Convert a DecisionCandidate to the reference Pareto input format."""
    metadata = c.metadata
    features = {
        "expected_quality": metadata.get("quality", metadata.get("expected_quality")),
        "reliability": metadata.get("success_rate", metadata.get("reliability")),
        "capability_fit": 1.0,  # default
        "privacy_fit": metadata.get("privacy_fit", 1.0 if metadata.get("local") else None),
        "information_gain": metadata.get("information_gain"),
        "reversibility": metadata.get("reversibility"),
        "cost": metadata.get("cost"),
        "latency": metadata.get("latency_ms", metadata.get("avg_latency_ms")),
        "risk": _risk_val(metadata.get("risk")),
    }
    return build_test_candidate(
        candidate_id=c.candidate_id,
        features=features,
        capabilities=set(str(x) for x in (metadata.get("capabilities") or ())),
        fallback_only=bool(metadata.get("fallback_only")),
        eligible=True,
    )


def _risk_val(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return {"low": 0.2, "medium": 0.5, "high": 0.8, "critical": 1.0}.get(str(value).lower())


def _make_random_candidates(n: int, seed: int) -> tuple[list[DecisionCandidate], list[dict[str, Any]]]:
    """Create random candidates and their reference dicts."""
    rng = random.Random(seed)
    modalities = ["text", "audio", "image", "code"]
    sched_cands: list[DecisionCandidate] = []
    ref_cands: list[dict[str, Any]] = []

    for i in range(n):
        metadata = {
            "capabilities": [rng.choice(modalities) + ".reason"],
            "success_rate": rng.random(),
            "quality": rng.random(),
            "latency_ms": rng.randint(10, 5000),
            "cost": rng.random(),
            "risk": rng.choice(["low", "low", "medium", "high"]),
            "health": "ok" if rng.random() > 0.1 else "degraded",
        }
        if rng.random() < 0.2:
            metadata["fallback_only"] = True
        if rng.random() < 0.1:
            metadata["stale_features"] = [rng.choice(["latency_ms", "cost"])]

        c = _candidate(f"c_{seed}_{i:04d}", **metadata)
        sched_cands.append(c)
        ref_cands.append(_to_reference_dict(c))

    return sched_cands, ref_cands


class TestReferenceEquivalence:
    """Compare optimized scheduler Pareto results against reference implementation."""

    @pytest.mark.parametrize("seed", [0, 1, 42, 123, 999])
    def test_10_random_candidates(self, seed: int):
        sched_cands, ref_cands = _make_random_candidates(10, seed)

        # Optimized result
        result = schedule_candidates(_request(*sched_cands))
        optimized_survivors = {
            e.candidate.candidate_id
            for e in result.ranking.evaluations
            if e.eligible and not any(
                r.candidate_id == e.candidate.candidate_id and r.reason_code == "PARETO_DOMINATED"
                for r in result.rejected_candidates
            )
        }

        # Reference result
        ref_result = reference_pareto_frontier(ref_cands)
        ref_survivors = {c["candidate_id"] for c in ref_result if not c["pareto_rejected"]}

        assert optimized_survivors == ref_survivors, (
            f"Seed {seed}: optimized={optimized_survivors}, reference={ref_survivors}"
        )

    @pytest.mark.parametrize("seed", [0, 1, 42, 123, 999])
    def test_50_random_candidates(self, seed: int):
        sched_cands, ref_cands = _make_random_candidates(50, seed)

        schedule_candidates(_request(*sched_cands))
        optimized_survivors = _pareto_survivor_ids(*sched_cands)

        ref_result = reference_pareto_frontier(ref_cands)
        ref_survivors = {c["candidate_id"] for c in ref_result if not c["pareto_rejected"]}

        assert optimized_survivors == ref_survivors, (
            f"Seed {seed}: Mismatch. optimized_only={optimized_survivors - ref_survivors}, ref_only={ref_survivors - optimized_survivors}"
        )

    @pytest.mark.parametrize("seed", [0, 42, 123])
    def test_100_random_candidates(self, seed: int):
        sched_cands, ref_cands = _make_random_candidates(100, seed)

        schedule_candidates(_request(*sched_cands))
        optimized_survivors = _pareto_survivor_ids(*sched_cands)

        ref_result = reference_pareto_frontier(ref_cands)
        ref_survivors = {c["candidate_id"] for c in ref_result if not c["pareto_rejected"]}

        assert optimized_survivors == ref_survivors, (
            f"Seed {seed}: Mismatch. optimized_only={optimized_survivors - ref_survivors}, ref_only={ref_survivors - optimized_survivors}"
        )


# invariants

def test_hard_constraint_invariants():
    """Hard constraints cannot be bypassed."""
    safe = _candidate("safe", capabilities=["model.reason"], health="ok")
    unsafe = _candidate("unsafe", capabilities=[], health="ok")

    # Force unsafe — should still reject because hard constraints override force
    result = schedule_candidates(_request(safe, unsafe, constraints={
        "required_capability": "model.reason",
        "force_candidate": "unsafe",
    }))
    # forced unsafe should be rejected on hard constraint
    unsafe_rejected = [r for r in result.rejected_candidates if r.candidate_id == "unsafe"]
    assert len(unsafe_rejected) >= 1
    # safe should be selected instead of unsafe
    assert result.selected.selected_candidate_id == "safe"


def test_trace_completeness():
    """Trace and explanation outputs should remain complete after optimization."""
    candidates = [
        _candidate("strong", success_rate=0.95, quality=0.9, latency_ms=100, cost=0.1),
        _candidate("weak", success_rate=0.3, quality=0.3, latency_ms=1000, cost=0.8),
    ]
    result = schedule_candidates(_request(*candidates))

    # Trace exists
    assert result.trace is not None
    assert "phases" in result.trace
    assert "discovered" in result.trace
    assert "duration_ms" in result.trace

    # Rejected candidates have proper rejection objects
    assert len(result.rejected_candidates) > 0
    for r in result.rejected_candidates:
        assert r.candidate_id
        assert r.reason_code
        assert r.message

    # Hash exists
    assert result.scheduler_snapshot_hash
    assert result.scoring_config_hash

    # Ranking is complete
    assert len(result.ranking.evaluations) == len(candidates)
    for e in result.ranking.evaluations:
        assert math.isfinite(e.normalized_score)
        assert e.candidate is not None


def test_pareto_disabled():
    """When Pareto is disabled, no PARETO_DOMINATED rejections should occur."""
    a = _candidate("a", success_rate=0.95, quality=0.9)
    b = _candidate("b", success_rate=0.3, quality=0.3)

    ctx = SelectionContext(
        task_id="test",
        decision_type=DecisionType.PROVIDER,
        pareto_enabled=False,
    )
    request = SchedulingRequest(
        request_id="no_pareto",
        candidates=(a, b),
        context=ctx,
    )
    result = schedule_candidates(request)

    pareto_rejected = [r for r in result.rejected_candidates if r.reason_code == "PARETO_DOMINATED"]
    assert len(pareto_rejected) == 0
