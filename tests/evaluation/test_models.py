# -*- coding: utf-8 -*-
"""Tests for Evaluation Models — 20 tests."""

from __future__ import annotations

import pytest

from nous_runtime.evaluation.models import (
    DimensionScore,
    EvaluationEvidence,
    EvaluationRecord,
)
from nous_runtime.evaluation.schema import (
    EvaluationStatus,
    TargetType,
)


class TestEvaluationEvidence:
    def test_create(self):
        ev = EvaluationEvidence(kind="test_result", dimension="correctness", summary="pytest: PASS", passed=True)
        assert ev.evidence_id.startswith("evid_")
        assert ev.passed is True

    def test_score_clamped(self):
        ev = EvaluationEvidence(kind="test", dimension="correctness", summary="test", score=1.5)
        assert ev.score == 1.0

    def test_to_dict_from_dict(self):
        ev = EvaluationEvidence(kind="test_result", dimension="correctness", summary="pass", passed=True, score=0.95)
        d = ev.to_dict()
        restored = EvaluationEvidence.from_dict(d)
        assert restored.passed == ev.passed
        assert restored.score == ev.score

    def test_auto_timestamp(self):
        ev = EvaluationEvidence(kind="test", dimension="correctness", summary="test")
        assert ev.created_at != ""


class TestDimensionScore:
    def test_create(self):
        ev = EvaluationEvidence(kind="test", dimension="correctness", summary="pass", passed=True, score=1.0)
        ds = DimensionScore(dimension="correctness", score=0.95, weight=0.30, evidence=(ev,))
        assert ds.score == 0.95
        assert ds.weighted == pytest.approx(0.285, 0.01)

    def test_passed_from_evidence(self):
        ev = EvaluationEvidence(kind="test", dimension="correctness", summary="pass", passed=True, score=1.0)
        ds = DimensionScore(dimension="correctness", score=1.0, weight=0.30, passed=True, evidence_count=1, evidence=(ev,))
        assert ds.passed is True

    def test_weighted_computed(self):
        ds = DimensionScore(dimension="security", score=0.80, weight=0.20)
        assert ds.weighted == pytest.approx(0.16, 0.01)

    def test_to_dict_from_dict(self):
        ev = EvaluationEvidence(kind="test", dimension="correctness", summary="ok", passed=True, score=1.0)
        ds = DimensionScore(dimension="correctness", score=0.90, weight=0.30, evidence=(ev,))
        restored = DimensionScore.from_dict(ds.to_dict())
        assert restored.score == ds.score
        assert restored.evidence_count == ds.evidence_count


class TestEvaluationRecord:
    def test_create_empty(self):
        rec = EvaluationRecord(target_type="task", target_id="t1")
        assert rec.id.startswith("eval_")
        assert rec.status == EvaluationStatus.PENDING.value

    def test_create_with_dimensions(self):
        ev = EvaluationEvidence(kind="test", dimension="correctness", summary="pass", passed=True, score=1.0)
        ds = DimensionScore(dimension="correctness", score=1.0, weight=0.30, evidence=(ev,), evidence_count=1)
        rec = EvaluationRecord(
            target_type="task", target_id="t1",
            dimensions=(ds,), composite_score=0.95, confidence=0.9,
        )
        assert rec.dimension_count == 1
        assert rec.passed is False  # status is still PENDING

    def test_passed_property(self):
        rec = EvaluationRecord(target_type="task", target_id="t1", status=EvaluationStatus.PASS.value)
        assert rec.passed is True

    def test_checksum_deterministic(self):
        ev = EvaluationEvidence(kind="test", dimension="correctness", summary="ok", passed=True, score=1.0, evidence_id="ev_001")
        ds = DimensionScore(dimension="correctness", score=1.0, weight=0.30, evidence=(ev,))
        rec1 = EvaluationRecord(id="eval_test", target_type="task", target_id="t1", dimensions=(ds,), composite_score=0.95)
        rec2 = EvaluationRecord(id="eval_test", target_type="task", target_id="t1", dimensions=(ds,), composite_score=0.95)
        assert rec1.checksum() == rec2.checksum()

    def test_to_dict_from_dict(self):
        ev = EvaluationEvidence(kind="test", dimension="correctness", summary="ok", passed=True, score=1.0)
        ds = DimensionScore(dimension="correctness", score=0.90, weight=0.30, evidence=(ev,))
        rec = EvaluationRecord(
            target_type="agent", target_id="a1",
            dimensions=(ds,), composite_score=0.90, confidence=0.85,
            recommendation="accept",
        )
        restored = EvaluationRecord.from_dict(rec.to_dict())
        assert restored.composite_score == rec.composite_score
        assert restored.recommendation == rec.recommendation

    def test_with_status(self):
        rec = EvaluationRecord(target_type="task", target_id="t1")
        passed = rec.with_status(EvaluationStatus.PASS)
        assert passed.status == EvaluationStatus.PASS.value
        assert rec.status == EvaluationStatus.PENDING.value  # Original unchanged

    def test_target_types(self):
        for tt in TargetType:
            rec = EvaluationRecord(target_type=tt.value, target_id="test")
            assert rec.target_type == tt.value

    def test_schema_version(self):
        rec = EvaluationRecord(target_type="task", target_id="t1")
        assert rec.schema_version != ""

    def test_issues_and_warnings(self):
        rec = EvaluationRecord(
            target_type="task", target_id="t1",
            issues=("test failure",), warnings=("borderline_score",),
        )
        assert len(rec.issues) == 1
        assert len(rec.warnings) == 1
