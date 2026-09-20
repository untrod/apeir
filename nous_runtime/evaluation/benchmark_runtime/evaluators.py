"""Deterministic benchmark case evaluators."""

from __future__ import annotations

import math
from typing import Mapping, Protocol

from nous_runtime.evaluation.benchmark_runtime.models import (
    BenchmarkCase,
    BenchmarkExecution,
    CaseEvaluation,
)
from nous_runtime.evaluation.benchmark_runtime.errors import (
    BenchmarkConfigurationError,
)


class CaseEvaluator(Protocol):
    def evaluate(
        self,
        case: BenchmarkCase,
        execution: BenchmarkExecution,
    ) -> CaseEvaluation: ...


class ExactMatchEvaluator:
    def evaluate(self, case, execution) -> CaseEvaluation:
        passed = execution.output == case.expected
        return CaseEvaluation(
            passed=passed,
            score=1.0 if passed else 0.0,
            reason="exact_match" if passed else "exact_mismatch",
        )


class NumericToleranceEvaluator:
    def __init__(
        self,
        *,
        absolute_tolerance: float = 0.0,
        relative_tolerance: float = 1e-6,
    ) -> None:
        if absolute_tolerance < 0 or relative_tolerance < 0:
            raise BenchmarkConfigurationError(
                "numeric tolerances must be non-negative"
            )
        self.absolute_tolerance = absolute_tolerance
        self.relative_tolerance = relative_tolerance

    def evaluate(self, case, execution) -> CaseEvaluation:
        try:
            actual = float(execution.output)
            expected = float(case.expected)
        except (TypeError, ValueError):
            return CaseEvaluation(False, 0.0, "non_numeric_output")
        passed = math.isclose(
            actual,
            expected,
            rel_tol=self.relative_tolerance,
            abs_tol=self.absolute_tolerance,
        )
        error = abs(actual - expected)
        denominator = max(abs(expected), self.absolute_tolerance, 1e-12)
        score = max(0.0, 1.0 - error / denominator)
        return CaseEvaluation(
            passed,
            score,
            "within_tolerance" if passed else "outside_tolerance",
            {"absolute_error": error},
        )


class MappingSubsetEvaluator:
    """Require expected mapping values while allowing extra output fields."""

    def evaluate(self, case, execution) -> CaseEvaluation:
        if not isinstance(case.expected, Mapping) or not isinstance(
            execution.output,
            Mapping,
        ):
            return CaseEvaluation(False, 0.0, "mapping_required")
        expected = dict(case.expected)
        matched = sum(
            1
            for key, value in expected.items()
            if key in execution.output and execution.output[key] == value
        )
        score = matched / max(len(expected), 1)
        return CaseEvaluation(
            matched == len(expected),
            score,
            "mapping_subset_match"
            if matched == len(expected)
            else "mapping_subset_mismatch",
            {"matched_fields": matched, "expected_fields": len(expected)},
        )


__all__ = [
    "CaseEvaluator",
    "ExactMatchEvaluator",
    "MappingSubsetEvaluator",
    "NumericToleranceEvaluator",
]
