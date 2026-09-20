"""Runtime scheduler latency benchmark."""

from __future__ import annotations

import argparse
import json
import statistics
import time
from pathlib import Path
from typing import Any

from nous_runtime.intelligence import (
    CandidateType,
    DecisionCandidate,
    DecisionType,
    SchedulingRequest,
    SelectionContext,
    schedule_candidates,
)


def _candidates(count: int) -> tuple[DecisionCandidate, ...]:
    return tuple(
        DecisionCandidate(
            candidate_id=f"task_provider_{i:04d}",
            candidate_type=CandidateType.PROVIDER,
            metadata={
                "capabilities": ["runtime.execute", "code.reason" if i % 3 == 0 else "text.reason"],
                "success_rate": 0.55 + (i % 40) / 100,
                "quality": 0.5 + (i % 30) / 100,
                "latency_ms": 50 + (i % 500),
                "cost": (i % 20) / 100,
                "risk": "low" if i % 11 else "medium",
                "health": "ok" if i % 13 else "degraded",
            },
        )
        for i in range(count)
    )


def _summary(samples: list[float]) -> dict[str, float]:
    ordered = sorted(samples)
    return {
        "mean_ms": round(statistics.mean(samples), 3),
        "median_ms": round(statistics.median(samples), 3),
        "p95_ms": round(ordered[int(len(ordered) * 0.95) - 1], 3) if len(ordered) >= 20 else round(ordered[-1], 3),
        "p99_ms": round(ordered[int(len(ordered) * 0.99) - 1], 3) if len(ordered) >= 100 else round(ordered[-1], 3),
        "max_ms": round(max(samples), 3),
    }


def run(tasks: int = 100, rounds: int = 100) -> dict[str, Any]:
    candidates = _candidates(tasks)
    context = SelectionContext(
        task_id="scheduler_benchmark",
        decision_type=DecisionType.PROVIDER,
        constraints={"required_capability": "runtime.execute"},
    )
    request = SchedulingRequest(request_id="scheduler_benchmark", candidates=candidates, context=context)
    for _ in range(5):
        schedule_candidates(request)

    samples: list[float] = []
    selected: list[str] = []
    for _ in range(rounds):
        start = time.perf_counter()
        result = schedule_candidates(request)
        samples.append((time.perf_counter() - start) * 1000)
        selected.append(result.selected.selected_candidate_id)

    return {
        "benchmark": "scheduler",
        "tasks": tasks,
        "rounds": rounds,
        "target_submit_to_schedule_ms": 100,
        "latency": _summary(samples),
        "stable_selection": len(set(selected)) == 1,
        "selected": selected[-1] if selected else "",
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tasks", type=int, default=100)
    parser.add_argument("--rounds", type=int, default=100)
    parser.add_argument("--output", default="")
    args = parser.parse_args()
    data = run(max(1, args.tasks), max(1, args.rounds))
    text = json.dumps(data, ensure_ascii=False, indent=2)
    if args.output:
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output).write_text(text + "\n", encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()