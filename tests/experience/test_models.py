# -*- coding: utf-8 -*-
"""Tests for Experience Models — 20 tests."""

from __future__ import annotations

from nous_runtime.experience.models import ExperiencePattern, ExperienceRecord, PolicyProposal, Recommendation
from nous_runtime.experience.schema import ExperienceStatus


class TestExperienceRecord:
    def test_create(self):
        r = ExperienceRecord(task_type="coding", action="refactor", result="success", success=True)
        assert r.id.startswith("exp_")
        assert r.status == ExperienceStatus.NEW.value

    def test_confidence_clamped(self):
        r = ExperienceRecord(task_type="coding", action="test", confidence=1.5)
        assert r.confidence == 1.0

    def test_validate_valid(self):
        r = ExperienceRecord(task_type="coding", action="refactor")
        assert r.validate() == []

    def test_validate_missing_task_type(self):
        r = ExperienceRecord(action="refactor")
        errors = r.validate()
        assert any("task_type" in e for e in errors)

    def test_lessons(self):
        r = ExperienceRecord(task_type="coding", action="test", lessons=("learned A", "learned B"))
        assert len(r.lessons) == 2

    def test_checksum(self):
        r1 = ExperienceRecord(id="e1", task_type="coding", action="refactor", result="success")
        r2 = ExperienceRecord(id="e1", task_type="coding", action="refactor", result="success")
        assert r1.checksum() == r2.checksum()

    def test_to_dict_from_dict(self):
        r = ExperienceRecord(task_type="coding", action="test", lessons=("L1",), tags=("t1",))
        restored = ExperienceRecord.from_dict(r.to_dict())
        assert restored.task_type == r.task_type
        assert restored.lessons == r.lessons

    def test_failure_reason(self):
        r = ExperienceRecord(task_type="deploy", action="install", success=False, failure_reason="cuda mismatch")
        assert r.failure_reason == "cuda mismatch"
        assert not r.success

    def test_occurrence_count_default(self):
        r = ExperienceRecord(task_type="test", action="run")
        assert r.occurrence_count == 1


class TestExperiencePattern:
    def test_create(self):
        p = ExperiencePattern(pattern_type="success", name="Test pattern", frequency=10, success_rate=0.9)
        assert p.id.startswith("pat_")
        assert p.frequency == 10

    def test_to_dict_from_dict(self):
        p = ExperiencePattern(pattern_type="failure", name="Test", frequency=5, source_experiences=("e1", "e2"))
        restored = ExperiencePattern.from_dict(p.to_dict())
        assert restored.name == p.name
        assert restored.source_experiences == p.source_experiences


class TestPolicyProposal:
    def test_create(self):
        p = PolicyProposal(title="Prefer agent X", target_policy="agent_selection", proposed_change="Increase weight")
        assert p.id.startswith("pol_")
        assert p.status == "proposed"

    def test_to_dict_from_dict(self):
        p = PolicyProposal(title="Test", target_policy="test_policy", proposed_change="change", supporting_experiences=("e1",))
        restored = PolicyProposal.from_dict(p.to_dict())
        assert restored.title == p.title


class TestRecommendation:
    def test_create(self):
        r = Recommendation(recommendation_type="agent", title="Use agent X", confidence=0.85)
        assert r.id.startswith("rec_")

    def test_to_dict_from_dict(self):
        r = Recommendation(recommendation_type="agent", title="Test", supporting_experiences=("e1",))
        restored = Recommendation.from_dict(r.to_dict())
        assert restored.title == r.title

    def test_suggested_agent(self):
        r = Recommendation(recommendation_type="agent", title="Test", suggested_agent="claude_code")
        assert r.suggested_agent == "claude_code"
