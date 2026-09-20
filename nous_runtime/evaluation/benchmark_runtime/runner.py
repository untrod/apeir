"""Injected benchmark execution with deterministic aggregation."""

from __future__ import annotations

import json
import math
import time
from typing import Any, Callable

from nous_runtime.evaluation.benchmark_runtime.evaluators import CaseEvaluator
from nous_runtime.evaluation.benchmark_runtime.models import (
    BenchmarkAttempt,
    BenchmarkCase,
    BenchmarkCaseResult,
    BenchmarkCaseStatus,
    BenchmarkExecution,
    BenchmarkRun,
    BenchmarkSuite,
)


BenchmarkExecutor = Callable[[BenchmarkCase, int], BenchmarkExecution | Any]


class BenchmarkSuiteRunner:
    def __init__(
        self,
        *,
        executor: BenchmarkExecutor,
        evaluator: CaseEvaluator,
    ) -> None:
        self.executor = executor
        self.evaluator = evaluator

    def run(
        self,
        suite: BenchmarkSuite,
        *,
        target_id: str,
    ) -> BenchmarkRun:
        started = time.perf_counter()
        results = tuple(self._run_case(case, suite) for case in suite.cases)
        total_weight = sum(item.weight for item in suite.cases)
        weights = {item.case_id: item.weight for item in suite.cases}
        score = sum(
            result.score * weights[result.case_id] for result in results
        ) / total_weight
        passed_count = sum(
            1
            for item in results
            if item.status is BenchmarkCaseStatus.PASSED
        )
        pass_rate = passed_count / len(results)
        determinism = sum(item.determinism for item in results) / len(results)
        durations = sorted(
            attempt.duration_ms
            for result in results
            for attempt in result.attempts
        )
        metrics = {
            "score": score,
            "pass_rate": pass_rate,
            "determinism": determinism,
            "latency_mean_ms": sum(durations) / max(len(durations), 1),
            "latency_p95_ms": self._percentile(durations, 0.95),
            "error_rate": sum(
                1
                for result in results
                if result.status
                in {BenchmarkCaseStatus.ERROR, BenchmarkCaseStatus.TIMEOUT}
            )
            / len(results),
        }
        metric_values: dict[str, list[float]] = {}
        for result in results:
            for name, value in result.metrics.items():
                if math.isfinite(float(value)):
                    metric_values.setdefault(name, []).append(float(value))
        for name, values in metric_values.items():
            metrics[name] = sum(values) / len(values)
        return BenchmarkRun(
            suite_id=suite.suite_id,
            suite_version=suite.version,
            target_id=str(target_id),
            results=results,
            score=round(score, 6),
            pass_rate=round(pass_rate, 6),
            determinism=round(determinism, 6),
            duration_ms=int((time.perf_counter() - started) * 1000),
            metrics={key: round(value, 6) for key, value in metrics.items()},
            passed=score >= suite.min_score
            and pass_rate >= suite.min_pass_rate,
        )

    def _run_case(
        self,
        case: BenchmarkCase,
        suite: BenchmarkSuite,
    ) -> BenchmarkCaseResult:
        attempts = tuple(
            self._run_attempt(case, attempt)
            for attempt in range(1, suite.repetitions + 1)
        )
        completed = [
            item
            for item in attempts
            if item.status
            not in {BenchmarkCaseStatus.ERROR, BenchmarkCaseStatus.TIMEOUT}
        ]
        score = sum(item.score for item in attempts) / len(attempts)
        if any(item.status is BenchmarkCaseStatus.ERROR for item in attempts):
            status = BenchmarkCaseStatus.ERROR
        elif any(
            item.status is BenchmarkCaseStatus.TIMEOUT for item in attempts
        ):
            status = BenchmarkCaseStatus.TIMEOUT
        elif all(
            item.status is BenchmarkCaseStatus.PASSED for item in attempts
        ):
            status = BenchmarkCaseStatus.PASSED
        else:
            status = BenchmarkCaseStatus.FAILED
        canonical = [self._canonical(item.output) for item in completed]
        determinism = (
            max(canonical.count(item) for item in set(canonical))
            / len(canonical)
            if canonical
            else 0.0
        )
        metric_values: dict[str, list[float]] = {}
        for attempt in attempts:
            for name, value in attempt.metrics.items():
                metric_values.setdefault(name, []).append(float(value))
        return BenchmarkCaseResult(
            case_id=case.case_id,
            category=case.category,
            status=status,
            score=round(score, 6),
            duration_ms=sum(item.duration_ms for item in attempts),
            determinism=round(determinism, 6),
            attempts=attempts,
            metrics={
                name: round(sum(values) / len(values), 6)
                for name, values in metric_values.items()
            },
            reason="; ".join(
                item.reason for item in attempts if item.reason
            ),
        )

    def _run_attempt(
        self,
        case: BenchmarkCase,
        attempt: int,
    ) -> BenchmarkAttempt:
        started = time.perf_counter()
        try:
            raw = self.executor(case, attempt)
            execution = (
                raw if isinstance(raw, BenchmarkExecution)
                else BenchmarkExecution(output=raw)
            )
            duration_ms = int((time.perf_counter() - started) * 1000)
            if duration_ms > case.timeout_ms:
                return BenchmarkAttempt(
                    attempt,
                    BenchmarkCaseStatus.TIMEOUT,
                    output=execution.output,
                    duration_ms=duration_ms,
                    metrics=dict(execution.metrics),
                    reason="measured_timeout",
                )
            evaluation = self.evaluator.evaluate(case, execution)
            return BenchmarkAttempt(
                attempt,
                BenchmarkCaseStatus.PASSED
                if evaluation.passed
                else BenchmarkCaseStatus.FAILED,
                output=execution.output,
                score=evaluation.score,
                duration_ms=duration_ms,
                metrics={
                    **dict(execution.metrics),
                    **dict(evaluation.metrics),
                },
                reason=evaluation.reason,
            )
        except Exception as exc:
            return BenchmarkAttempt(
                attempt,
                BenchmarkCaseStatus.ERROR,
                duration_ms=int((time.perf_counter() - started) * 1000),
                error=str(exc),
                reason="executor_error",
            )

    @staticmethod
    def _canonical(value: Any) -> str:
        try:
            return json.dumps(
                value,
                sort_keys=True,
                ensure_ascii=False,
                separators=(",", ":"),
            )
        except (TypeError, ValueError):
            return repr(value)

    @staticmethod
    def _percentile(values: list[int], quantile: float) -> float:
        if not values:
            return 0.0
        index = max(
            0,
            min(len(values) - 1, math.ceil(quantile * len(values)) - 1),
        )
        return float(values[index])


__all__ = ["BenchmarkExecutor", "BenchmarkSuiteRunner"]
