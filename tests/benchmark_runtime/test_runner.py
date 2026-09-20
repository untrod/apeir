from __future__ import annotations

import time

from nous_runtime.evaluation.benchmark_runtime import (
    BenchmarkCase,
    BenchmarkCaseStatus,
    BenchmarkExecution,
    BenchmarkSuite,
    BenchmarkSuiteRunner,
    ExactMatchEvaluator,
)


def suite(*cases, repetitions=1, min_score=0.7, min_pass_rate=0.8):
    return BenchmarkSuite(
        "suite",
        "Runtime suite",
        tuple(cases),
        repetitions=repetitions,
        min_score=min_score,
        min_pass_rate=min_pass_rate,
    )


def test_runner_executes_and_aggregates_weighted_scores() -> None:
    cases = (
        BenchmarkCase("heavy", "heavy", "a", "a", weight=3),
        BenchmarkCase("light", "light", "b", "expected", weight=1),
    )
    runner = BenchmarkSuiteRunner(
        executor=lambda case, attempt: BenchmarkExecution(
            output=case.input,
            metrics={"tokens": 10},
        ),
        evaluator=ExactMatchEvaluator(),
    )

    run = runner.run(
        suite(*cases, min_score=0.7, min_pass_rate=0.5),
        target_id="model.a",
    )

    assert run.score == 0.75
    assert run.pass_rate == 0.5
    assert run.metrics["tokens"] == 10
    assert run.passed


def test_repetitions_measure_output_determinism() -> None:
    outputs = {1: "A", 2: "B", 3: "A"}
    runner = BenchmarkSuiteRunner(
        executor=lambda case, attempt: outputs[attempt],
        evaluator=ExactMatchEvaluator(),
    )
    run = runner.run(
        suite(
            BenchmarkCase("repeat", "repeat", None, "A"),
            repetitions=3,
            min_pass_rate=0,
        ),
        target_id="model",
    )

    result = run.results[0]
    assert result.determinism == 0.666667
    assert result.status is BenchmarkCaseStatus.FAILED
    assert [item.score for item in result.attempts] == [1, 0, 1]


def test_executor_exception_is_contained_as_case_error() -> None:
    def fail(case, attempt):
        raise RuntimeError("provider unavailable")

    run = BenchmarkSuiteRunner(
        executor=fail,
        evaluator=ExactMatchEvaluator(),
    ).run(
        suite(
            BenchmarkCase("error", "error", None),
            min_score=0,
            min_pass_rate=0,
        ),
        target_id="model",
    )

    assert run.results[0].status is BenchmarkCaseStatus.ERROR
    assert run.results[0].attempts[0].error == "provider unavailable"
    assert run.metrics["error_rate"] == 1


def test_measured_timeout_is_explicit() -> None:
    def slow(case, attempt):
        time.sleep(0.01)
        return "done"

    run = BenchmarkSuiteRunner(
        executor=slow,
        evaluator=ExactMatchEvaluator(),
    ).run(
        suite(
            BenchmarkCase(
                "slow",
                "slow",
                None,
                "done",
                timeout_ms=1,
            ),
            min_score=0,
            min_pass_rate=0,
        ),
        target_id="model",
    )

    attempt = run.results[0].attempts[0]
    assert attempt.status is BenchmarkCaseStatus.TIMEOUT
    assert attempt.reason == "measured_timeout"


def test_case_order_and_results_are_deterministic() -> None:
    cases = (
        BenchmarkCase("z", "z", "z", "z"),
        BenchmarkCase("a", "a", "a", "a"),
    )
    run = BenchmarkSuiteRunner(
        executor=lambda case, attempt: case.input,
        evaluator=ExactMatchEvaluator(),
    ).run(suite(*cases), target_id="target")

    assert [item.case_id for item in run.results] == ["z", "a"]
    assert run.determinism == 1
