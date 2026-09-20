"""Benchmark baselines and regression gates."""

from __future__ import annotations

from typing import Mapping

from nous_runtime.evaluation.benchmark_runtime.models import (
    BenchmarkBaseline,
    BenchmarkComparison,
    BenchmarkGateStatus,
    BenchmarkRun,
    MetricDirection,
    MetricRegression,
)


class BenchmarkComparator:
    def __init__(
        self,
        *,
        tolerances: Mapping[str, float] | None = None,
        directions: Mapping[str, MetricDirection] | None = None,
    ) -> None:
        self.tolerances = {
            "score": 0.03,
            "pass_rate": 0.05,
            "determinism": 0.05,
            "latency_p95_ms": 0.10,
            **dict(tolerances or {}),
        }
        self.directions = {
            "score": MetricDirection.HIGHER_IS_BETTER,
            "pass_rate": MetricDirection.HIGHER_IS_BETTER,
            "determinism": MetricDirection.HIGHER_IS_BETTER,
            "latency_p95_ms": MetricDirection.LOWER_IS_BETTER,
            **dict(directions or {}),
        }

    def compare(
        self,
        baseline: BenchmarkBaseline,
        current: BenchmarkRun,
    ) -> BenchmarkComparison:
        baseline_metrics = {
            "score": baseline.score,
            "pass_rate": baseline.pass_rate,
            "determinism": baseline.determinism,
            **dict(baseline.metrics),
        }
        current_metrics = {
            "score": current.score,
            "pass_rate": current.pass_rate,
            "determinism": current.determinism,
            **dict(current.metrics),
        }
        compared = []
        regressions = []
        improvements = []
        for metric in sorted(set(baseline_metrics) & set(current_metrics)):
            before = float(baseline_metrics[metric])
            after = float(current_metrics[metric])
            direction = self.directions.get(
                metric,
                MetricDirection.HIGHER_IS_BETTER,
            )
            tolerance = max(0.0, float(self.tolerances.get(metric, 0.05)))
            raw_delta = after - before
            normalized = raw_delta / max(abs(before), 1e-12)
            effective = (
                normalized
                if direction is MetricDirection.HIGHER_IS_BETTER
                else -normalized
            )
            regressed = effective < -tolerance
            compared.append(
                MetricRegression(
                    metric,
                    before,
                    after,
                    round(raw_delta, 6),
                    regressed,
                    direction,
                    tolerance,
                )
            )
            if regressed:
                regressions.append(metric)
            elif effective > tolerance:
                improvements.append(metric)
        if regressions:
            status = BenchmarkGateStatus.BLOCK
        elif improvements:
            status = BenchmarkGateStatus.PASS
        else:
            status = BenchmarkGateStatus.WARN
        return BenchmarkComparison(
            baseline.run_id,
            current.run_id,
            status,
            tuple(compared),
            tuple(regressions),
            tuple(improvements),
        )


__all__ = ["BenchmarkComparator"]
