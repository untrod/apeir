import pytest

from nous_runtime.evaluation.benchmark_runtime import (
    BenchmarkCase,
    BenchmarkConfigurationError,
    BenchmarkExecution,
    BenchmarkSuite,
    ExactMatchEvaluator,
    MappingSubsetEvaluator,
    NumericToleranceEvaluator,
)


def case(expected):
    return BenchmarkCase("case", "case", input=None, expected=expected)


def test_exact_match_evaluator() -> None:
    evaluator = ExactMatchEvaluator()
    assert evaluator.evaluate(case("ok"), BenchmarkExecution("ok")).passed
    assert not evaluator.evaluate(
        case("ok"),
        BenchmarkExecution("bad"),
    ).passed


def test_numeric_tolerance_evaluator() -> None:
    evaluator = NumericToleranceEvaluator(absolute_tolerance=0.01)
    accepted = evaluator.evaluate(
        case(10.0),
        BenchmarkExecution(10.005),
    )
    rejected = evaluator.evaluate(
        case(10.0),
        BenchmarkExecution(11.0),
    )

    assert accepted.passed
    assert accepted.metrics["absolute_error"] == pytest.approx(0.005)
    assert not rejected.passed
    assert rejected.score == pytest.approx(0.9)


def test_mapping_subset_allows_additional_output() -> None:
    result = MappingSubsetEvaluator().evaluate(
        case({"answer": 42}),
        BenchmarkExecution({"answer": 42, "explanation": "computed"}),
    )
    assert result.passed
    assert result.score == 1


def test_invalid_case_and_suite_configuration_is_rejected() -> None:
    with pytest.raises(BenchmarkConfigurationError):
        BenchmarkCase("", "case", input=None)
    duplicate = BenchmarkCase("same", "case", input=None)
    with pytest.raises(BenchmarkConfigurationError, match="unique"):
        BenchmarkSuite(
            "suite",
            "suite",
            (duplicate, duplicate),
        )
