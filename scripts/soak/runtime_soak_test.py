"""Long-running Nous Runtime soak test harness.

The default command is intentionally short for local validation. Use
`--duration-seconds 86400` for the 24-hour release soak.
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.soak.failure_collector import FailureCollector  # noqa: E402
from scripts.soak.resource_monitor import ResourceMonitor, sqlite_integrity, summarize  # noqa: E402


def _exercise_runtime(workspace: Path, iteration: int) -> bool:
    from nous_runtime.context.models import ContextItem, ContextSnapshot
    from nous_runtime.context.schema import ContextSource
    from nous_runtime.context.store import ContextStore
    from nous_runtime.daemon.service import DaemonService
    from nous_runtime.experience.models import ExperienceRecord
    from nous_runtime.experience.schema import ExperienceSource
    from nous_runtime.experience.store import ExperienceStore
    from nous_runtime.intelligence import (
        CandidateType,
        DecisionCandidate,
        DecisionType,
        SchedulingRequest,
        SelectionContext,
        schedule_candidates,
    )
    from nous_runtime.network.registry import NetworkRegistry

    daemon = DaemonService(workspace=str(workspace))
    if not daemon.start():
        raise RuntimeError("daemon failed to start")

    candidates = tuple(
        DecisionCandidate(
            candidate_id=f"soak_provider_{idx}",
            candidate_type=CandidateType.PROVIDER,
            metadata={"capabilities": ["runtime.execute"], "success_rate": 0.7, "quality": 0.7, "latency_ms": 100 + idx},
        )
        for idx in range(8)
    )
    schedule_candidates(
        SchedulingRequest(
            request_id=f"soak_{iteration}",
            candidates=candidates,
            context=SelectionContext(task_id="soak", decision_type=DecisionType.PROVIDER),
        )
    )

    context_store = ContextStore(workspace)
    item = ContextItem(
        item_id=f"soak_ctx_{iteration}",
        content=f"soak context iteration {iteration}",
        source_type=ContextSource.RUNTIME.value,
        source_id="soak",
    )
    snapshot = ContextSnapshot(id=f"soak_snap_{iteration}", items=(item,), sources=(ContextSource.RUNTIME.value,))
    context_store.save(snapshot)
    context_store.restore(snapshot.id)

    experience_store = ExperienceStore(workspace)
    experience_store.save(
        ExperienceRecord(
            id=f"soak_exp_{iteration}",
            source_type=ExperienceSource.SYSTEM.value,
            task_type="soak",
            task_summary="long running runtime validation",
            action="exercise runtime services",
            result="success",
            success=True,
            confidence=0.8,
        )
    )
    experience_store.search("runtime", limit=5)

    # Network registry smoke keeps this local and deterministic.
    registry = NetworkRegistry(str(workspace))
    registry.list()

    daemon.stop()
    return True


def run(duration_seconds: float, interval_seconds: float, workspace: Path | None = None) -> dict[str, Any]:
    owns_workspace = workspace is None
    temp_dir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True) if owns_workspace else None
    root = Path(temp_dir.name) / ".nous" if temp_dir else Path(workspace or ".nous")
    root.mkdir(parents=True, exist_ok=True)

    monitor = ResourceMonitor(root)
    failures = FailureCollector()
    samples = []
    iterations = 0
    successes = 0
    restarts = 0
    started = time.time()
    deadline = started + duration_seconds

    try:
        while time.time() < deadline:
            iterations += 1
            samples.append(monitor.sample())
            try:
                if _exercise_runtime(root, iterations):
                    successes += 1
                    restarts += 1
            except Exception as exc:
                failures.capture("iteration", exc)
            time.sleep(max(0.0, interval_seconds))
        samples.append(monitor.sample())
        integrity = sqlite_integrity(root)
        summary = summarize(samples)
        memory_leak = bool(summary.get("rss_growth_mb") and float(summary["rss_growth_mb"] or 0) > 50.0)
        return {
            "benchmark": "runtime_soak",
            "duration_seconds": round(time.time() - started, 3),
            "iterations": iterations,
            "successes": successes,
            "task_success_rate": round(successes / max(iterations, 1), 4),
            "restart_count": restarts,
            "error_count": failures.count,
            "memory_leak_detected": memory_leak,
            "unexpected_crash_count": failures.count,
            "data_corruption_detected": not bool(integrity.get("ok", True)),
            "resources": summary,
            "sqlite_integrity": integrity,
            "failures": failures.to_list(),
        }
    finally:
        if temp_dir is not None:
            temp_dir.cleanup()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--duration-seconds", type=float, default=10.0)
    parser.add_argument("--interval-seconds", type=float, default=1.0)
    parser.add_argument("--workspace", default="")
    parser.add_argument("--output", default="")
    args = parser.parse_args()

    workspace = Path(args.workspace) if args.workspace else None
    data = run(max(1.0, args.duration_seconds), max(0.0, args.interval_seconds), workspace)
    text = json.dumps(data, ensure_ascii=False, indent=2)
    if args.output:
        out = Path(args.output)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text + "\n", encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
