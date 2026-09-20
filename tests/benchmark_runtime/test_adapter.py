from nous_runtime.evaluation import BenchmarkSuiteRunner, QualityScorer
from nous_runtime.evaluation.benchmark_runtime import (
    BenchmarkCase,
    BenchmarkEvidenceAdapter,
    BenchmarkSuite,
    ExactMatchEvaluator,
)


def test_benchmark_run_becomes_existing_evaluation_evidence() -> None:
    suite = BenchmarkSuite(
        "suite",
        "suite",
        (BenchmarkCase("case", "case", "ok", "ok"),),
    )
    run = BenchmarkSuiteRunner(
        executor=lambda case, attempt: case.input,
        evaluator=ExactMatchEvaluator(),
    ).run(suite, target_id="model")

    evidence = BenchmarkEvidenceAdapter().to_evidence(run)
    record = QualityScorer().score(
        target_type="model",
        target_id="model",
        evidence=list(evidence),
    )

    assert evidence[0].source == "benchmark_runtime"
    assert evidence[0].passed
    assert record.target_id == "model"
    assert "correctness" in record.criteria


def test_new_runner_is_available_without_replacing_legacy_runner() -> None:
    from nous_runtime.evaluation import BenchmarkRunner

    assert BenchmarkSuiteRunner.__name__ == "BenchmarkSuiteRunner"
    assert BenchmarkRunner.__name__ == "BenchmarkRunner"
