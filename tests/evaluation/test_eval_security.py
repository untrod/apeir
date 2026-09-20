# -*- coding: utf-8 -*-
"""Tests for Evaluation Security — 20 tests."""

from __future__ import annotations


import pytest

from nous_runtime.evaluation.models import (
    DimensionScore,
    EvaluationEvidence,
    EvaluationRecord,
)
from nous_runtime.evaluation.security import (
    EvaluationAccessDecision,
    EvaluationAccessRequest,
    EvaluationGuard,
    authorize_evaluation_access,
)


@pytest.fixture
def guard():
    return EvaluationGuard()


@pytest.fixture
def sample_record():
    ev = EvaluationEvidence(kind="test", dimension="correctness", summary="ok", passed=True, score=1.0)
    ds = DimensionScore(dimension="correctness", score=0.95, weight=0.30, evidence=(ev,))
    return EvaluationRecord(
        target_type="task", target_id="t1",
        dimensions=(ds,), composite_score=0.95, confidence=0.9,
        evaluated_by="system",
    )


class TestEvaluationAccessRequest:
    def test_create(self):
        req = EvaluationAccessRequest(actor="agent_01", actor_type="agent", action="read")
        assert req.actor == "agent_01"

    def test_defaults(self):
        req = EvaluationAccessRequest()
        assert req.action == ""


class TestEvaluationAccessDecision:
    def test_create(self):
        dec = EvaluationAccessDecision(allowed=True, reason="granted")
        assert dec.allowed is True

    def test_timestamp_auto(self):
        dec = EvaluationAccessDecision()
        assert dec.timestamp != ""


class TestEvaluationGuard:
    def test_system_can_read(self, guard):
        dec = guard.authorize(EvaluationAccessRequest(actor="system", actor_type="system", action="read"))
        assert dec.allowed is True

    def test_system_can_create(self, guard):
        dec = guard.authorize(EvaluationAccessRequest(actor="system", actor_type="system", action="create"))
        assert dec.allowed is True

    def test_system_can_modify(self, guard):
        dec = guard.authorize(EvaluationAccessRequest(actor="system", actor_type="system", action="modify"))
        assert dec.allowed is True

    def test_agent_can_read(self, guard):
        dec = guard.authorize(EvaluationAccessRequest(actor="agent_coding", actor_type="agent", action="read"))
        assert dec.allowed is True

    def test_agent_cannot_modify(self, guard):
        dec = guard.authorize(EvaluationAccessRequest(
            actor="agent_coding", actor_type="agent",
            action="modify", record_id="eval_001",
        ))
        assert dec.allowed is False

    def test_agent_cannot_delete(self, guard):
        dec = guard.authorize(EvaluationAccessRequest(actor="agent_coding", actor_type="agent", action="delete"))
        assert dec.allowed is False

    def test_agent_cannot_create(self, guard):
        dec = guard.authorize(EvaluationAccessRequest(actor="agent_coding", actor_type="agent", action="create"))
        assert dec.allowed is False

    def test_user_can_read(self, guard):
        dec = guard.authorize(EvaluationAccessRequest(actor="user_1", actor_type="user", action="read"))
        assert dec.allowed is True

    def test_user_can_create(self, guard):
        dec = guard.authorize(EvaluationAccessRequest(actor="user_1", actor_type="user", action="create"))
        assert dec.allowed is True

    def test_user_cannot_modify(self, guard):
        dec = guard.authorize(EvaluationAccessRequest(actor="user_1", actor_type="user", action="modify"))
        assert dec.allowed is False

    def test_unknown_actor_type(self, guard):
        dec = guard.authorize(EvaluationAccessRequest(actor="bot", actor_type="bot", action="read"))
        assert dec.allowed is False

    def test_verify_record_integrity_clean(self, guard, sample_record):
        violations = guard.verify_record_integrity(sample_record)
        assert violations == []

    def test_verify_evidence_immutable_clean(self, guard, sample_record):
        violations = guard.verify_evidence_immutable(sample_record, sample_record)
        assert violations == []

    def test_verify_evidence_immutable_modified(self, guard, sample_record):
        # Create a modified record with different evidence score
        ev2 = EvaluationEvidence(kind="test", dimension="correctness", summary="ok", passed=True, score=0.5)
        ds2 = DimensionScore(dimension="correctness", score=0.50, weight=0.30, evidence=(ev2,))
        modified = EvaluationRecord(
            target_type="task", target_id="t1",
            dimensions=(ds2,), composite_score=0.50, confidence=0.5,
        )
        violations = guard.verify_evidence_immutable(sample_record, modified)
        # The evidence IDs will differ, so at least one violation
        assert len(violations) >= 1

    def test_convenience_function(self):
        dec = authorize_evaluation_access(actor="agent_test", actor_type="agent", action="read")
        assert isinstance(dec, EvaluationAccessDecision)

    def test_permissions_dict_complete(self, guard):
        assert "system" in guard.PERMISSIONS
        assert "agent" in guard.PERMISSIONS
        assert "user" in guard.PERMISSIONS
