"""Deterministic scheduler benchmark with per-phase profiling.

Produces the data for docs/review/P5_5_1_SCHEDULER_PERFORMANCE_AUDIT.md.
Measures the OPTIMIZED scheduler (P5.5.1).
"""

from __future__ import annotations

import gc
import json
import statistics
import time
import tracemalloc
from dataclasses import dataclass, field
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from nous_runtime.intelligence import (
    CandidateType,
    DecisionCandidate,
    DecisionType,
    JsonlDecisionStore,
    SchedulingRequest,
    SelectionContext,
    schedule_candidates,
    snapshot_hash,
)
from nous_runtime.intelligence.models import (
    RuntimeDecision,
    DecisionOutcome,
    DecisionReason,
)


# candidate generators

def _candidates(count: int, seed: int = 42) -> tuple[DecisionCandidate, ...]:
    """Deterministic candidates with varied metadata."""
    import random as _random
    rng = _random.Random(seed)
    modalities = ["text", "audio", "image", "code"]
    risks = ["low", "low", "low", "low", "medium", "high"]
    providers = ["p_local", "p_cloud_a", "p_cloud_b", "p_edge", "p_hybrid"]
    return tuple(
        DecisionCandidate(
            candidate_id=f"provider_{idx:04d}",
            candidate_type=CandidateType.PROVIDER,
            metadata={
                "capabilities": [rng.choice(modalities) + ".reason"],
                "success_rate": 0.5 + (idx % 50) / 100,
                "quality": 0.4 + (idx % 40) / 100,
                "latency_ms": 100 + rng.randint(0, 5000),
                "cost": rng.random(),
                "risk": rng.choice(risks),
                "health": "ok" if idx % 10 else "degraded",
                "provider_id": rng.choice(providers),
                "modality": rng.choice(modalities) if idx % 3 else None,
                "privacy_fit": rng.random() if idx % 5 else None,
                "information_gain": rng.random() if idx % 7 else None,
                "reversibility": rng.random() if idx % 4 else None,
                "stale_features": ["latency_ms"] if idx % 11 == 0 else [],
            },
        )
        for idx in range(count)
    )


def _request(candidates: tuple[DecisionCandidate, ...]) -> SchedulingRequest:
    return SchedulingRequest(
        request_id=snapshot_hash({"candidates": [c.candidate_id for c in candidates]}),
        candidates=candidates,
        context=SelectionContext(
            task_id="benchmark",
            decision_type=DecisionType.PROVIDER,
            constraints={"required_capability": "text.reason"},
        ),
    )


# benchmark runner

def _warm(candidates: tuple[DecisionCandidate, ...], rounds: int = 5) -> None:
    for _ in range(rounds):
        schedule_candidates(_request(candidates))
        gc.collect()


@dataclass
class PhaseProfile:
    name: str
    durations_ms: list[float] = field(default_factory=list)

    @property
    def mean(self) -> float:
        return statistics.mean(self.durations_ms) if self.durations_ms else 0.0

    @property
    def p50(self) -> float:
        return statistics.median(self.durations_ms) if self.durations_ms else 0.0

    @property
    def p95(self) -> float:
        if not self.durations_ms:
            return 0.0
        return sorted(self.durations_ms)[int(len(self.durations_ms) * 0.95) - 1]

    @property
    def p99(self) -> float:
        if not self.durations_ms:
            return 0.0
        return sorted(self.durations_ms)[int(len(self.durations_ms) * 0.99) - 1]

    def record(self, d: float) -> None:
        self.durations_ms.append(d)


def _run_pure(count: int, rounds: int, seed: int = 42) -> dict[str, Any]:
    """Measure pure scheduler execution time (using schedule_candidates)."""
    candidates = _candidates(count, seed=seed)
    _warm(candidates, rounds=min(5, rounds))

    durations: list[float] = []
    for _ in range(rounds):
        gc.collect()
        t0 = time.perf_counter()
        schedule_candidates(_request(candidates))
        durations.append((time.perf_counter() - t0) * 1000)

    # Memory
    gc.collect()
    tracemalloc.start()
    schedule_candidates(_request(candidates))
    _, peak_bytes = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    sd = sorted(durations)
    return {
        "candidates": count,
        "rounds": rounds,
        "mean_ms": round(statistics.mean(durations), 3),
        "p50_ms": round(statistics.median(durations), 3),
        "p95_ms": round(sd[int(rounds * 0.95) - 1], 3) if rounds >= 20 else round(sd[-1], 3),
        "p99_ms": round(sd[int(rounds * 0.99) - 1], 3) if rounds >= 100 else round(sd[-1], 3),
        "max_ms": round(max(durations), 3),
        "min_ms": round(min(durations), 3),
        "peak_kb": round(peak_bytes / 1024, 3),
    }


def _run_with_persistence(count: int, rounds: int, seed: int = 42) -> dict[str, Any]:
    """Measure full decision pipeline including store persistence."""
    candidates = _candidates(count, seed=seed)
    _warm(candidates, rounds=min(3, rounds))

    durations: list[float] = []
    store_durations: list[float] = []

    tmpdir = TemporaryDirectory()
    store = JsonlDecisionStore(Path(tmpdir.name) / ".nous", concurrency_mode="single_process")

    for _ in range(rounds):
        gc.collect()
        t0 = time.perf_counter()
        sched_result = schedule_candidates(_request(candidates))
        sched_time = (time.perf_counter() - t0) * 1000
        durations.append(sched_time)

        t0 = time.perf_counter()
        decision = RuntimeDecision(
            decision_id=sched_result.request_id,
            task_id="benchmark",
            decision_type=DecisionType.PROVIDER,
            outcome=DecisionOutcome(
                selected=sched_result.selected.selected_candidate_id,
                confidence=sched_result.selected.confidence,
            ),
            reasons=(DecisionReason(code="SCHEDULER", message="Benchmark"),),
            candidates=candidates,
            metadata={"scheduler_snapshot_hash": sched_result.scheduler_snapshot_hash},
        )
        store.persist_decision_snapshot(decision)
        store_durations.append((time.perf_counter() - t0) * 1000)

    tmpdir.cleanup()
    sd = sorted(durations)
    ssd = sorted(store_durations)
    return {
        "candidates": count,
        "rounds": rounds,
        "scheduler_mean_ms": round(statistics.mean(durations), 3),
        "scheduler_p50_ms": round(statistics.median(durations), 3),
        "scheduler_p95_ms": round(sd[int(rounds * 0.95) - 1], 3) if rounds >= 20 else round(sd[-1], 3),
        "store_mean_ms": round(statistics.mean(store_durations), 3),
        "store_p50_ms": round(statistics.median(store_durations), 3),
        "store_p95_ms": round(ssd[int(rounds * 0.95) - 1], 3) if rounds >= 20 else round(ssd[-1], 3),
        "total_mean_ms": round(statistics.mean([d + s for d, s in zip(durations, store_durations)]), 3),
    }


def _run_phase_profile(count: int, rounds: int, seed: int = 42) -> dict[str, Any]:
    """Run with detailed phase profiling using the optimized scheduler."""
    from nous_runtime.intelligence.scheduler import DeterministicScheduler

    candidates = _candidates(count, seed=seed)
    _warm(candidates, rounds=min(5, rounds))
    ctx = SelectionContext(
        task_id="benchmark_profile",
        decision_type=DecisionType.PROVIDER,
        constraints={"required_capability": "text.reason"},
    )

    phases: dict[str, PhaseProfile] = {
        name: PhaseProfile(name=name)
        for name in [
            "candidate_prep",
            "evaluation",
            "policy",
            "pareto",
            "ranking",
            "selection",
            "hashing",
            "serialization",
        ]
    }

    scheduler = DeterministicScheduler()

    for _ in range(rounds):
        gc.collect()

        # Phase: candidate prep (sort)
        t0 = time.perf_counter()
        sorted_candidates = tuple(sorted(candidates, key=lambda c: c.candidate_id))
        phases["candidate_prep"].record((time.perf_counter() - t0) * 1000)

        # Phase: evaluate each candidate
        t0 = time.perf_counter()
        evaluations = [scheduler._evaluate_candidate(c, ctx) for c in sorted_candidates]
        phases["evaluation"].record((time.perf_counter() - t0) * 1000)

        # Phase: policy
        t0 = time.perf_counter()
        evaluations = scheduler._apply_policy(evaluations, ctx)
        phases["policy"].record((time.perf_counter() - t0) * 1000)

        # Phase: Pareto
        t0 = time.perf_counter()
        if ctx.pareto_enabled:
            evaluations, _ = scheduler._apply_pareto_optimized(evaluations, ctx)
        phases["pareto"].record((time.perf_counter() - t0) * 1000)

        # Phase: ranking
        t0 = time.perf_counter()
        evaluations = scheduler._rank(evaluations)
        phases["ranking"].record((time.perf_counter() - t0) * 1000)

        # Phase: selection
        t0 = time.perf_counter()
        scheduler._select(evaluations, ctx)
        phases["selection"].record((time.perf_counter() - t0) * 1000)

        # Phase: hashing
        t0 = time.perf_counter()
        from nous_runtime.intelligence.scheduler import _fast_scheduler_hash  # noqa: F811
        _fast_scheduler_hash(sorted_candidates, evaluations, ctx)
        phases["hashing"].record((time.perf_counter() - t0) * 1000)

        # Phase: serialization (ranking.to_dict etc)
        t0 = time.perf_counter()
        from nous_runtime.intelligence.models import CandidateRanking
        ranking = CandidateRanking(tuple(evaluations), pareto_enabled=True, scheduler_version="1.1")
        _ = ranking.to_dict()
        phases["serialization"].record((time.perf_counter() - t0) * 1000)

    total_time = sum(sum(p.durations_ms) for p in phases.values())
    report = {
        "candidates": count,
        "rounds": rounds,
        "total_ms": round(total_time, 3),
        "phases": [],
    }
    for name in ["candidate_prep", "evaluation", "policy", "pareto", "ranking", "selection", "hashing", "serialization"]:
        p = phases[name]
        if p.durations_ms:
            pt = sum(p.durations_ms)
            report["phases"].append({
                "phase": name,
                "mean_ms": round(p.mean, 3),
                "p50_ms": round(p.p50, 3),
                "p95_ms": round(p.p95, 3),
                "p99_ms": round(p.p99, 3),
                "pct_of_total": round(pt / total_time * 100, 1) if total_time > 0 else 0.0,
            })
    return report


def main() -> None:
    results: dict[str, Any] = {
        "scheduler_version": "1.1",
        "benchmark_version": "2.0",
        "pure_scheduling": {},
        "with_persistence": {},
        "phase_profile": {},
    }

    # Pure scheduling times
    for count in (10, 100, 1000):
        rounds = 50 if count <= 100 else 10
        results["pure_scheduling"][str(count)] = _run_pure(count, rounds)

    # With persistence
    for count in (10, 100, 1000):
        rounds = 20 if count <= 100 else 5
        results["with_persistence"][str(count)] = _run_with_persistence(count, rounds)

    # Detailed phase profile
    for count in (10, 100, 1000):
        rounds = 20 if count <= 100 else 5
        results["phase_profile"][str(count)] = _run_phase_profile(count, rounds)

    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
