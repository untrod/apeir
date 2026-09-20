# -*- coding: utf-8 -*-
"""Regression Evaluation — detect degradation between versions.

Prevents: "upgrade made things worse."

Compares: before vs after metrics → alerts if quality drops.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from nous_runtime.evaluation.models import EvaluationRecord

_log = logging.getLogger("nous.evaluation.regression")



# Baseline


@dataclass
class Baseline:
    """A snapshot of metrics used as comparison baseline."""
    target_type: str = ""
    target_id: str = ""
    composite_score: float = 0.0
    dimension_scores: dict[str, float] = field(default_factory=dict)
    metrics: dict[str, float] = field(default_factory=dict)
    created_at: str = ""
    record_id: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "target_type": self.target_type,
            "target_id": self.target_id,
            "composite_score": self.composite_score,
            "dimension_scores": dict(self.dimension_scores),
            "metrics": dict(self.metrics),
            "created_at": self.created_at,
            "record_id": self.record_id,
        }

    @classmethod
    def from_record(cls, record: EvaluationRecord) -> "Baseline":
        return cls(
            target_type=record.target_type,
            target_id=record.target_id,
            composite_score=record.composite_score,
            dimension_scores={d.dimension: d.score for d in record.dimensions},
            metrics={"confidence": record.confidence, "duration_ms": record.duration_ms},
            created_at=record.created_at,
            record_id=record.id,
        )



# Regression result


@dataclass
class RegressionResult:
    """Result of a regression comparison."""
    passed: bool = True
    baseline_score: float = 0.0
    current_score: float = 0.0
    delta: float = 0.0              # Positive = improvement
    regressions: list[str] = field(default_factory=list)
    improvements: list[str] = field(default_factory=list)
    details: dict[str, Any] = field(default_factory=dict)
    recommendation: str = ""        # "proceed", "block", "warn"

    def to_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "baseline_score": self.baseline_score,
            "current_score": self.current_score,
            "delta": self.delta,
            "regressions": self.regressions,
            "improvements": self.improvements,
            "details": self.details,
            "recommendation": self.recommendation,
        }



# Regression Evaluator


class RegressionEvaluator:
    """Compares current evaluation against baselines to detect regressions.

    Usage::

        evaluator = RegressionEvaluator()
        baseline = Baseline.from_record(previous_eval)
        result = evaluator.compare(baseline, current_eval)
        if not result.passed:
            print("BLOCKED: regression detected")
    """

    def __init__(
        self,
        composite_threshold: float = 0.05,     # 5% drop = regression
        dimension_threshold: float = 0.10,      # 10% per-dim drop = regression
        metric_threshold: float = 0.15,         # 15% metric drop = regression
    ):
        self._composite_threshold = composite_threshold
        self._dimension_threshold = dimension_threshold
        self._metric_threshold = metric_threshold



    def compare(
        self,
        baseline: Baseline,
        current: EvaluationRecord,
    ) -> RegressionResult:
        """Compare current evaluation against a baseline.

        Returns RegressionResult with pass/fail and details.
        """
        regressions: list[str] = []
        improvements: list[str] = []
        details: dict[str, Any] = {}

        # 1. Composite score comparison
        delta = current.composite_score - baseline.composite_score
        details["composite"] = {
            "baseline": baseline.composite_score,
            "current": current.composite_score,
            "delta": round(delta, 4),
        }

        if delta < -self._composite_threshold:
            regressions.append(
                f"Composite score dropped {abs(delta):.1%} "
                f"(baseline: {baseline.composite_score:.2f}, current: {current.composite_score:.2f})"
            )
        elif delta > self._composite_threshold:
            improvements.append(f"Composite score improved {delta:.1%}")

        # 2. Per-dimension comparison
        current_dims = {d.dimension: d.score for d in current.dimensions}
        details["dimensions"] = {}

        for dim_name, baseline_score in baseline.dimension_scores.items():
            current_score = current_dims.get(dim_name, 0.0)
            dim_delta = current_score - baseline_score
            details["dimensions"][dim_name] = {
                "baseline": baseline_score,
                "current": current_score,
                "delta": round(dim_delta, 4),
            }

            if dim_delta < -self._dimension_threshold:
                regressions.append(f"[{dim_name}] dropped {abs(dim_delta):.1%}")
            elif dim_delta > self._dimension_threshold:
                improvements.append(f"[{dim_name}] improved {dim_delta:.1%}")

        # 3. Recommendation
        if regressions:
            recommendation = "block"
            passed = False
        elif improvements and delta > 0:
            recommendation = "proceed"
            passed = True
        else:
            recommendation = "warn"
            passed = True  # No regressions, just not much improvement

        return RegressionResult(
            passed=passed,
            baseline_score=baseline.composite_score,
            current_score=current.composite_score,
            delta=round(delta, 4),
            regressions=regressions,
            improvements=improvements,
            details=details,
            recommendation=recommendation,
        )



    def compare_records(
        self,
        baseline_record: EvaluationRecord,
        current_record: EvaluationRecord,
    ) -> RegressionResult:
        """Compare two EvaluationRecords directly."""
        return self.compare(
            Baseline.from_record(baseline_record),
            current_record,
        )



# Convenience


def check_regression(
    baseline: Baseline,
    current: EvaluationRecord,
) -> RegressionResult:
    """One-shot regression check."""
    return RegressionEvaluator().compare(baseline, current)
