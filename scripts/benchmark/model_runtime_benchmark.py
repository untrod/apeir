"""Model Runtime deterministic selection benchmark."""

from __future__ import annotations

import argparse
import json
import statistics
import time
from pathlib import Path
from typing import Any

from nous_runtime.model import ModelRequest, ModelRuntime

REQUESTS = [
    ModelRequest(task_type="code", privacy="standard", quality=0.8),
    ModelRequest(task_type="runtime", privacy="standard", latency=100),
    ModelRequest(task_type="general", privacy="standard", cost=0.01),
    ModelRequest(task_type="engineering", privacy="local"),
]


def _summary(samples: list[float]) -> dict[str, float]:
    ordered = sorted(samples)
    return {
        "mean_ms": round(statistics.mean(samples), 4),
        "median_ms": round(statistics.median(samples), 4),
        "p95_ms": round(ordered[int(len(ordered) * 0.95) - 1], 4) if len(ordered) >= 20 else round(ordered[-1], 4),
        "max_ms": round(max(samples), 4),
    }


def run(rounds: int = 1000) -> dict[str, Any]:
    runtime = ModelRuntime()
    samples: list[float] = []
    selections: list[dict[str, Any]] = []
    for i in range(rounds):
        request = REQUESTS[i % len(REQUESTS)]
        start = time.perf_counter()
        selection = runtime.select(request)
        samples.append((time.perf_counter() - start) * 1000)
        if i < len(REQUESTS):
            selections.append({"request": request.to_dict(), "selection": selection.to_dict()})
    return {
        "benchmark": "model_runtime",
        "rounds": rounds,
        "latency": _summary(samples),
        "selections": selections,
        "note": "Deterministic selector baseline; provider network latency is not measured in v0.1.0-alpha.",
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rounds", type=int, default=1000)
    parser.add_argument("--output", default="")
    args = parser.parse_args()
    data = run(max(1, args.rounds))
    text = json.dumps(data, ensure_ascii=False, indent=2)
    if args.output:
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output).write_text(text + "\n", encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()