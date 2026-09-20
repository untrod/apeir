#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""BenchmarkRunner — executes task specs against baselines, collects traces and metrics."""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
SPECS_DIR = Path(__file__).resolve().parent / "task_specs"
VALIDATORS_DIR = Path(__file__).resolve().parent / "validators"


# ═══════════════════════════════════════════════════════════════════
# Data models
# ═══════════════════════════════════════════════════════════════════

@dataclass
class BenchmarkTask:
    """A single benchmark task specification."""
    task_id: str = ""
    task_type: str = ""
    description: str = ""
    input: dict[str, Any] = field(default_factory=dict)
    expected: dict[str, Any] = field(default_factory=dict)
    validators: list[str] = field(default_factory=list)
    timeout_seconds: int = 120
    risk_class: str = "low"
    tags: list[str] = field(default_factory=list)

    @classmethod
    def from_json(cls, path: str | Path) -> "BenchmarkTask":
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        return cls(**{k: data.get(k, v) for k, v in cls.__dataclass_fields__.items()})


@dataclass
class BenchmarkResult:
    """Result of a single benchmark execution."""
    task_id: str = ""
    task_type: str = ""
    baseline_name: str = ""
    model_id: str = ""
    status: str = ""                # "pass", "fail", "error", "timeout"
    latency_ms: float = 0.0
    cost_usd: float = 0.0
    verification_status: str = ""
    errors: list[str] = field(default_factory=list)
    trace_id: str = ""
    run_id: str = ""
    created_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class BenchmarkRun:
    """Complete benchmark run with all results."""
    run_id: str = ""
    started_at: str = ""
    completed_at: str = ""
    total_tasks: int = 0
    passed: int = 0
    failed: int = 0
    errors: int = 0
    timeouts: int = 0
    results: list[BenchmarkResult] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)


# ═══════════════════════════════════════════════════════════════════
# Benchmark Runner
# ═══════════════════════════════════════════════════════════════════

class BenchmarkRunner:
    """Executes benchmark tasks against baseline algorithms."""

    def __init__(
        self,
        *,
        baseline_registry: Any = None,
        trace_collector: Any = None,
    ) -> None:
        self._baselines = baseline_registry
        self._trace_collector = trace_collector

    def run(
        self,
        *,
        task_type: str = "",
        baseline_name: str = "",
        task_ids: list[str] | None = None,
        limit: int = 0,
        output_path: str = "",
    ) -> BenchmarkRun:
        """Execute benchmark tasks and collect results."""
        run = BenchmarkRun(
            run_id=f"bench_{uuid.uuid4().hex[:12]}",
            started_at=_utc_now(),
        )

        # Load tasks
        tasks = self._load_tasks(task_type=task_type, task_ids=task_ids)
        if limit > 0:
            tasks = tasks[:limit]
        run.total_tasks = len(tasks)

        if not tasks:
            print("No benchmark tasks found.")
            return run

        # Select baseline
        baseline = self._get_baseline(baseline_name) if baseline_name else None

        print(f"Benchmark Run: {run.run_id}")
        print(f"Tasks: {len(tasks)} (type={task_type or 'all'})")
        print(f"Baseline: {baseline_name or 'default'}")
        print(f"{'='*60}")

        for i, task in enumerate(tasks):
            label = f"[{i+1}/{len(tasks)}]"
            result = self._execute_task(task, baseline, run.run_id)

            if result.status == "pass":
                run.passed += 1
                icon = "✅"
            elif result.status == "timeout":
                run.timeouts += 1
                icon = "⏰"
            elif result.status == "error":
                run.errors += 1
                icon = "💥"
            else:
                run.failed += 1
                icon = "❌"

            print(f"  {label} {icon} {task.task_type}/{task.task_id}: {result.status} ({result.latency_ms:.0f}ms)")
            if result.errors:
                for e in result.errors[:2]:
                    print(f"         {e}")

            run.results.append(result)

        run.completed_at = _utc_now()

        # Compute aggregate metrics
        run.metrics = self._compute_run_metrics(run)

        # Save if output path provided
        if output_path:
            self._save_run(run, output_path)

        # Summary
        print(f"\n{'='*60}")
        print(f"Results: {run.passed} passed, {run.failed} failed, {run.errors} errors, {run.timeouts} timeouts")
        print(f"Success rate: {run.passed / max(run.total_tasks, 1):.1%}")
        print(f"Avg latency: {run.metrics.get('avg_latency_ms', 0):.0f}ms")
        print(f"Total cost: ${run.metrics.get('total_cost_usd', 0):.4f}")

        return run

    # ── Internal ──────────────────────────────────────────────────

    def _load_tasks(
        self,
        task_type: str = "",
        task_ids: list[str] | None = None,
    ) -> list[BenchmarkTask]:
        """Load task specs from the task_specs directory."""
        tasks: list[BenchmarkTask] = []

        if not SPECS_DIR.exists():
            # Create default tasks if no specs directory exists
            return self._create_default_tasks(task_type)

        for spec_file in sorted(SPECS_DIR.glob("*.json")):
            try:
                task = BenchmarkTask.from_json(spec_file)
                if task_type and task.task_type != task_type:
                    continue
                if task_ids and task.task_id not in task_ids:
                    continue
                tasks.append(task)
            except Exception as e:
                print(f"  Warning: failed to load {spec_file.name}: {e}")

        return tasks

    def _create_default_tasks(self, task_type: str = "") -> list[BenchmarkTask]:
        """Create a default set of 20 benchmark tasks."""
        from .task_specs import DEFAULT_TASKS
        tasks = [BenchmarkTask(**t) for t in DEFAULT_TASKS]
        if task_type:
            tasks = [t for t in tasks if t.task_type == task_type]
        return tasks

    def _get_baseline(self, name: str) -> Any:
        """Get a baseline policy by name."""
        if self._baselines is not None:
            record = self._baselines.get(name)
            if record is not None:
                return record.policy

        # Fallback: load from built-in baselines
        try:
            from nous_runtime.intelligence.baselines.implementations import ALL_BASELINES
            for b in ALL_BASELINES:
                if b.name == name:
                    return b
        except ImportError:
            pass
        return None

    def _execute_task(
        self,
        task: BenchmarkTask,
        baseline: Any,
        run_id: str,
    ) -> BenchmarkResult:
        """Execute a single benchmark task."""
        result = BenchmarkResult(
            task_id=task.task_id,
            task_type=task.task_type,
            baseline_name=baseline.name if baseline else "default",
            run_id=run_id,
            created_at=_utc_now(),
        )

        start_time = time.monotonic()

        try:
            # If baseline exists, use it to select model/node
            if baseline:
                available_models = task.input.get("available_models", [])
                selected = baseline.select_model(
                    {"task_type": task.task_type, "description": task.description, **task.input},
                    available_models,
                )
                if selected:
                    result.model_id = str(selected.get("model_id", ""))

            # Execute validators
            validation_errors = []
            for validator_name in task.validators:
                validator = self._load_validator(validator_name)
                if validator is not None:
                    ok, msg = validator(task.expected, task.input)
                    if not ok:
                        validation_errors.append(msg)

            if validation_errors:
                result.status = "fail"
                result.verification_status = "fail"
                result.errors = validation_errors
            else:
                result.status = "pass"
                result.verification_status = "pass"

        except Exception as e:
            result.status = "error"
            result.errors.append(str(e))

        result.latency_ms = (time.monotonic() - start_time) * 1000
        result.trace_id = f"bench_trace_{uuid.uuid4().hex[:12]}"

        # Record trace if collector available
        if self._trace_collector is not None:
            try:
                record = self._trace_collector.collect(
                    trace_id=result.trace_id,
                )
                record.task_info.task_type = task.task_type
                record.outcome.final_status = result.status
                record.outcome.verification_status = result.verification_status
                record.outcome.latency_ms = result.latency_ms
                record.outcome.cost_usd = result.cost_usd
                record.seal()
                # Store would persist here
            except Exception:
                pass

        return result

    def _load_validator(self, name: str) -> Any:
        """Load a validator function by name."""
        try:
            from . import validators
            return getattr(validators, name, None)
        except ImportError:
            pass
        return None

    def _compute_run_metrics(self, run: BenchmarkRun) -> dict[str, Any]:
        """Compute aggregate metrics from a benchmark run."""
        if not run.results:
            return {}

        latencies = [r.latency_ms for r in run.results if r.latency_ms > 0]
        costs = [r.cost_usd for r in run.results if r.cost_usd > 0]

        return {
            "total_tasks": run.total_tasks,
            "success_rate": run.passed / max(run.total_tasks, 1),
            "failure_rate": run.failed / max(run.total_tasks, 1),
            "error_rate": run.errors / max(run.total_tasks, 1),
            "timeout_rate": run.timeouts / max(run.total_tasks, 1),
            "verified_rate": sum(
                1 for r in run.results if r.verification_status == "pass"
            ) / max(run.total_tasks, 1),
            "avg_latency_ms": sum(latencies) / max(len(latencies), 1),
            "p50_latency_ms": _percentile(latencies, 50),
            "p95_latency_ms": _percentile(latencies, 95),
            "total_cost_usd": sum(costs),
            "avg_cost_usd": sum(costs) / max(len(costs), 1),
        }

    def _save_run(self, run: BenchmarkRun, output_path: str) -> None:
        """Save benchmark run to JSON."""
        data = {
            "run_id": run.run_id,
            "started_at": run.started_at,
            "completed_at": run.completed_at,
            "total_tasks": run.total_tasks,
            "passed": run.passed,
            "failed": run.failed,
            "errors": run.errors,
            "timeouts": run.timeouts,
            "metrics": run.metrics,
            "results": [r.to_dict() for r in run.results],
        }
        Path(output_path).write_text(
            json.dumps(data, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )


# ═══════════════════════════════════════════════════════════════════
# Convenience function
# ═══════════════════════════════════════════════════════════════════

def run_benchmark(
    task_type: str = "",
    baseline_name: str = "",
    limit: int = 0,
    output_path: str = "",
) -> BenchmarkRun:
    """Convenience function to run a benchmark."""
    runner = BenchmarkRunner()
    return runner.run(
        task_type=task_type,
        baseline_name=baseline_name,
        limit=limit,
        output_path=output_path,
    )


# ═══════════════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════════════

def main():
    import argparse

    parser = argparse.ArgumentParser(description="Nous Execution Benchmark Runner")
    parser.add_argument("--task-type", default="", help="Task type filter")
    parser.add_argument("--baseline", default="", help="Baseline algorithm name")
    parser.add_argument("--all", action="store_true", help="Run all baselines")
    parser.add_argument("--limit", type=int, default=0, help="Max tasks to run")
    parser.add_argument("--output", default="", help="Output JSON path")
    parser.add_argument("--list-tasks", action="store_true", help="List available tasks")
    parser.add_argument("--list-baselines", action="store_true", help="List available baselines")

    args = parser.parse_args()

    if args.list_tasks:
        print("Available task types:")
        from .task_specs import TASK_TYPES
        for tt in TASK_TYPES:
            print(f"  {tt['type']}: {tt['description']}")
        return

    if args.list_baselines:
        print("Available baselines:")
        from nous_runtime.intelligence.baselines.implementations import ALL_BASELINES
        for b in ALL_BASELINES:
            print(f"  {b.name}: {b.description}")
        return

    if args.all:
        from nous_runtime.intelligence.baselines.implementations import ALL_BASELINES
        runner = BenchmarkRunner()
        for baseline in ALL_BASELINES:
            print(f"\n{'='*60}")
            print(f"  Baseline: {baseline.name}")
            print(f"{'='*60}")
            runner.run(
                task_type=args.task_type,
                baseline_name=baseline.name,
                limit=args.limit,
            )
    else:
        run_benchmark(
            task_type=args.task_type,
            baseline_name=args.baseline,
            limit=args.limit,
            output_path=args.output,
        )


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    k = (pct / 100.0) * (len(s) - 1)
    f = int(k)
    c = min(f + 1, len(s) - 1)
    return s[f] + (k - f) * (s[c] - s[f])


if __name__ == "__main__":
    main()
