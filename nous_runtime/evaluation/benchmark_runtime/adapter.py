"""Bridge Benchmark Runtime results into existing Evaluation Evidence."""

from nous_runtime.evaluation.benchmark_runtime.models import BenchmarkRun
from nous_runtime.evaluation.models import EvaluationEvidence
from nous_runtime.evaluation.schema import EvaluationDimension, EvidenceKind


class BenchmarkEvidenceAdapter:
    def to_evidence(
        self,
        run: BenchmarkRun,
    ) -> tuple[EvaluationEvidence, ...]:
        correctness = EvaluationEvidence(
            kind=EvidenceKind.BENCHMARK.value,
            dimension=EvaluationDimension.CORRECTNESS.value,
            summary=(
                f"Benchmark {run.suite_id}: "
                f"score={run.score:.3f}, pass_rate={run.pass_rate:.3f}"
            ),
            passed=run.passed,
            score=run.score,
            source="benchmark_runtime",
            detail={
                "run_id": run.run_id,
                "suite_version": run.suite_version,
                "pass_rate": run.pass_rate,
                "determinism": run.determinism,
            },
        )
        performance_score = 1.0 / (
            1.0 + max(0.0, run.metrics.get("latency_p95_ms", 0.0)) / 1000.0
        )
        performance = EvaluationEvidence(
            kind=EvidenceKind.BENCHMARK.value,
            dimension=EvaluationDimension.PERFORMANCE.value,
            summary=(
                f"Benchmark p95 latency: "
                f"{run.metrics.get('latency_p95_ms', 0.0):.1f} ms"
            ),
            passed=run.metrics.get("error_rate", 0.0) == 0.0,
            score=performance_score,
            source="benchmark_runtime",
            detail={"run_id": run.run_id, **dict(run.metrics)},
        )
        return correctness, performance


__all__ = ["BenchmarkEvidenceAdapter"]
