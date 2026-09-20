# -*- coding: utf-8 -*-
"""Tests for Quality Scoring — 20 tests."""

from __future__ import annotations

import pytest

from nous_runtime.evaluation.models import EvaluationEvidence, EvaluationRecord
from nous_runtime.evaluation.schema import EvaluationDimension, EvaluationStatus
from nous_runtime.evaluation.scorer import QualityScorer, score_evaluation


@pytest.fixture
def scorer():
    return QualityScorer()


@pytest.fixture
def passing_evidence():
    """Evidence that all passes."""
    return [
        EvaluationEvidence(kind="test_result", dimension="correctness", summary="pytest: PASS", passed=True, score=1.0, source="pytest"),
        EvaluationEvidence(kind="lint_result", dimension="maintainability", summary="ruff: PASS", passed=True, score=1.0, source="ruff"),
        EvaluationEvidence(kind="security_scan", dimension="security", summary="Security: PASS", passed=True, score=1.0, source="security_scan"),
        EvaluationEvidence(kind="performance_metric", dimension="performance", summary="Latency: ok", passed=True, score=1.0, source="latency"),
        EvaluationEvidence(kind="automated_check", dimension="reliability", summary="Reliability: PASS", passed=True, score=1.0, source="flake_check"),
    ]


class TestQualityScorer:
    def test_score_returns_record(self, scorer, passing_evidence):
        record = scorer.score(target_type="task", target_id="t1", evidence=passing_evidence)
        assert isinstance(record, EvaluationRecord)
        assert record.target_type == "task"

    def test_score_with_all_passing(self, scorer, passing_evidence):
        record = scorer.score(target_type="task", target_id="t1", evidence=passing_evidence, input_summary="test")
        assert record.composite_score > 0.80
        assert record.status == EvaluationStatus.PASS.value

    def test_score_has_all_dimensions(self, scorer, passing_evidence):
        record = scorer.score(target_type="task", target_id="t1", evidence=passing_evidence)
        dim_names = {d.dimension for d in record.dimensions}
        for dim in EvaluationDimension:
            assert dim.value in dim_names, f"Missing dimension: {dim.value}"

    def test_score_empty_evidence(self, scorer):
        record = scorer.score(target_type="task", target_id="t1", evidence=[])
        assert record.composite_score == 0.0

    def test_score_failing_evidence(self, scorer):
        evidence = [
            EvaluationEvidence(kind="test_result", dimension="correctness", summary="pytest: FAIL", passed=False, score=0.0, source="pytest"),
            EvaluationEvidence(kind="lint_result", dimension="maintainability", summary="ruff: FAIL", passed=False, score=0.0, source="ruff"),
        ]
        record = scorer.score(target_type="task", target_id="t1", evidence=evidence)
        assert record.composite_score < 0.30
        assert record.status in (
            EvaluationStatus.FAIL.value, EvaluationStatus.WARNING.value,
            EvaluationStatus.RETRY_REQUIRED.value, EvaluationStatus.HUMAN_REVIEW.value,
        )

    def test_score_confidence(self, scorer, passing_evidence):
        record = scorer.score(target_type="task", target_id="t1", evidence=passing_evidence)
        assert 0.0 <= record.confidence <= 1.0

    def test_score_has_recommendation(self, scorer, passing_evidence):
        record = scorer.score(target_type="task", target_id="t1", evidence=passing_evidence)
        assert record.recommendation in ("accept", "improve", "retry", "reject", "review")

    def test_score_has_issues(self, scorer):
        evidence = [
            EvaluationEvidence(kind="test_result", dimension="correctness", summary="pytest: FAIL", passed=False, score=0.0, source="pytest"),
        ]
        record = scorer.score(target_type="task", target_id="t1", evidence=evidence)
        assert len(record.issues) > 0

    def test_score_with_evaluated_by(self, scorer, passing_evidence):
        record = scorer.score(target_type="task", target_id="t1", evidence=passing_evidence, evaluated_by="user_test")
        assert record.evaluated_by == "user_test"

    def test_score_duration_recorded(self, scorer, passing_evidence):
        record = scorer.score(target_type="task", target_id="t1", evidence=passing_evidence)
        assert record.duration_ms >= 0

    def test_convenience_function(self, passing_evidence):
        record = score_evaluation(target_type="task", target_id="t1", evidence=passing_evidence)
        assert isinstance(record, EvaluationRecord)

    def test_partial_evidence_scores_lower(self, scorer):
        """With only one dimension's evidence, score should be lower."""
        evidence = [
            EvaluationEvidence(kind="test_result", dimension="correctness", summary="ok", passed=True, score=1.0, source="pytest"),
        ]
        record = scorer.score(target_type="task", target_id="t1", evidence=evidence)
        # Only correctness dimension has evidence (weight 0.30)
        # Other dimensions score 0
        assert record.composite_score < 0.50

    def test_correctness_weight_applied(self, scorer):
        evidence = [
            EvaluationEvidence(kind="test_result", dimension="correctness", summary="ok", passed=True, score=1.0, source="pytest"),
        ]
        record = scorer.score(target_type="task", target_id="t1", evidence=evidence)
        # Max score = 0.30 (correctness at 100%) + 0 for others
        assert record.composite_score <= 0.35

    def test_metadata_passed_through(self, scorer, passing_evidence):
        record = scorer.score(target_type="task", target_id="t1", evidence=passing_evidence, metadata={"version": "1.0"})
        assert record.metadata.get("version") == "1.0"
