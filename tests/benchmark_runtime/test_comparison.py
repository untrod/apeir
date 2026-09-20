from dataclasses import replace

from nous_runtime.evaluation.benchmark_runtime import (
    BenchmarkBaseline,
    BenchmarkCase,
    BenchmarkComparator,
    BenchmarkGateStatus,
    BenchmarkSuite,
    BenchmarkSuiteRunner,
    ExactMatchEvaluator,
    MetricDirection,
)


def make_run(*, output="ok", target="model"):
    suite = BenchmarkSuite(
        "suite",
        "suite",
        (BenchmarkCase("case", "case", None, "ok"),),
    )
    return BenchmarkSuiteRunner(
        executor=lambda case, attempt: output,
        evaluator=ExactMatchEvaluator(),
    ).run(suite, target_id=target)


def test_comparator_blocks_quality_regression() -> None:
    baseline_run = make_run()
    current = make_run(output="bad")
    comparison = BenchmarkComparator().compare(
        BenchmarkBaseline.from_run(baseline_run),
        current,
    )

    assert comparison.status is BenchmarkGateStatus.BLOCK
    assert "score" in comparison.regressions
    score = next(item for item in comparison.metrics if item.metric == "score")
    assert score.direction is MetricDirection.HIGHER_IS_BETTER


def test_comparator_treats_latency_as_lower_is_better() -> None:
    baseline = BenchmarkBaseline.from_run(make_run())
    baseline = replace(
        baseline,
        metrics={**baseline.metrics, "latency_p95_ms": 100},
    )
    current = make_run()
    current = replace(
        current,
        metrics={**current.metrics, "latency_p95_ms": 200},
    )

    comparison = BenchmarkComparator().compare(baseline, current)

    assert comparison.status is BenchmarkGateStatus.BLOCK
    assert "latency_p95_ms" in comparison.regressions


def test_comparator_warns_when_within_tolerance() -> None:
    baseline = BenchmarkBaseline.from_run(make_run())
    current = make_run()

    comparison = BenchmarkComparator().compare(baseline, current)

    assert comparison.status is BenchmarkGateStatus.WARN
    assert not comparison.regressions
