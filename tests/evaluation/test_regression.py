# -*- coding: utf-8 -*-
"""Tests for Regression Evaluation — 20 tests."""

from __future__ import annotations

import pytest

from nous_runtime.evaluation.models import DimensionScore, EvaluationRecord
from nous_runtime.evaluation.regression import (
    Baseline,
    RegressionEvaluator,
    RegressionResult,
    check_regression,
)


@pytest.fixture
def evaluator():
    return RegressionEvaluator()


@pytest.fixture
def good_baseline():
    return Baseline(
        target_type="task", target_id="t1",
        composite_score=0.90,
        dimension_scores={
            "correctness": 0.95, "reliability": 0.90,
            "security": 0.85, "performance": 0.88, "maintainability": 0.92,
        },
    )


@pytest.fixture
def make_record():
    """Factory for test records."""
    def _make(composite=0.90, dim_scores=None):
        if dim_scores is None:
            dim_scores = {
                "correctness": 0.95, "reliability": 0.90,
                "security": 0.85, "performance": 0.88, "maintainability": 0.92,
            }
        dims = tuple(
            DimensionScore(dimension=k, score=v, weight=0.20)
            for k, v in dim_scores.items()
        )
        return EvaluationRecord(
            target_type="task", target_id="t1",
            dimensions=dims, composite_score=composite,
        )
    return _make


class TestBaseline:
    def test_create(self):
        b = Baseline(target_type="task", target_id="t1")
        assert b.target_type == "task"

    def test_from_record(self, make_record):
        record = make_record(composite=0.85)
        b = Baseline.from_record(record)
        assert b.composite_score == 0.85
        assert len(b.dimension_scores) > 0

    def test_to_dict(self, good_baseline):
        d = good_baseline.to_dict()
        assert d["target_type"] == "task"
        assert "dimension_scores" in d


class TestRegressionResult:
    def test_create(self):
        r = RegressionResult(passed=True, baseline_score=0.9, current_score=0.92, delta=0.02)
        assert r.passed is True
        assert r.delta > 0

    def test_to_dict(self):
        r = RegressionResult(passed=True, baseline_score=0.9, current_score=0.85, delta=-0.05)
        d = r.to_dict()
        assert "passed" in d
        assert "delta" in d


class TestRegressionEvaluator:
    def test_no_regression_improvement(self, evaluator, good_baseline, make_record):
        current = make_record(composite=0.95)  # Better than baseline
        result = evaluator.compare(good_baseline, current)
        assert result.passed is True

    def test_regression_detected(self, evaluator, good_baseline, make_record):
        current = make_record(composite=0.70)  # Much worse than baseline (0.90)
        result = evaluator.compare(good_baseline, current)
        assert result.passed is False
        assert len(result.regressions) > 0

    def test_same_score_no_regression(self, evaluator, good_baseline, make_record):
        current = make_record(composite=0.90)
        result = evaluator.compare(good_baseline, current)
        assert result.passed is True

    def test_dimension_regression(self, evaluator, good_baseline, make_record):
        current = make_record(composite=0.85, dim_scores={
            "correctness": 0.70,  # Dropped from 0.95 — regression!
            "reliability": 0.90, "security": 0.85,
            "performance": 0.88, "maintainability": 0.92,
        })
        result = evaluator.compare(good_baseline, current)
        assert not result.passed
        assert any("correctness" in r.lower() for r in result.regressions)

    def test_improvement_detected(self, evaluator, good_baseline, make_record):
        current = make_record(composite=0.98)
        result = evaluator.compare(good_baseline, current)
        assert len(result.improvements) > 0

    def test_recommendation_block(self, evaluator, good_baseline, make_record):
        current = make_record(composite=0.50)
        result = evaluator.compare(good_baseline, current)
        assert result.recommendation == "block"

    def test_recommendation_proceed(self, evaluator, good_baseline, make_record):
        current = make_record(composite=0.97)
        result = evaluator.compare(good_baseline, current)
        assert result.recommendation == "proceed"

    def test_compare_records(self, evaluator, make_record):
        baseline_rec = make_record(composite=0.90)
        current_rec = make_record(composite=0.85)
        result = evaluator.compare_records(baseline_rec, current_rec)
        assert isinstance(result, RegressionResult)

    def test_convenience_function(self, good_baseline, make_record):
        current = make_record(composite=0.92)
        result = check_regression(good_baseline, current)
        assert isinstance(result, RegressionResult)

    def test_delta_positive_improvement(self, evaluator, good_baseline, make_record):
        current = make_record(composite=0.95)
        result = evaluator.compare(good_baseline, current)
        assert result.delta > 0

    def test_delta_negative_regression(self, evaluator, good_baseline, make_record):
        current = make_record(composite=0.80)
        result = evaluator.compare(good_baseline, current)
        assert result.delta < 0

    def test_unknown_dimension_in_current(self, evaluator, good_baseline, make_record):
        """Dimensions only in current shouldn't cause errors."""
        current = make_record(composite=0.90, dim_scores={
            "correctness": 0.95, "reliability": 0.90,
            "security": 0.85, "performance": 0.88, "maintainability": 0.92,
            "new_dim": 0.99,  # Not in baseline
        })
        result = evaluator.compare(good_baseline, current)
        assert isinstance(result, RegressionResult)
