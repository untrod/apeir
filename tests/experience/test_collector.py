# -*- coding: utf-8 -*-
"""Tests for Experience Collector — 20 tests."""

from __future__ import annotations

import os
import tempfile

import pytest
from nous_runtime.experience.collector import ExperienceCollector
from nous_runtime.experience.schema import ExperienceSource


@pytest.fixture
def temp_workspace():
    with tempfile.TemporaryDirectory() as tmp:
        yield os.path.join(tmp, ".nous")


@pytest.fixture
def collector(temp_workspace):
    return ExperienceCollector(temp_workspace)


class MockEvalRecord:
    def __init__(self, **kwargs):
        self.id = kwargs.get("id", "eval_001")
        self.target_type = kwargs.get("target_type", "task")
        self.target_id = kwargs.get("target_id", "t1")
        self.composite_score = kwargs.get("composite_score", 0.95)
        self.passed = kwargs.get("passed", True)
        self.issues = kwargs.get("issues", ())
        self.recommendation = kwargs.get("recommendation", "accept")
        self.confidence = kwargs.get("confidence", 0.9)


class TestExperienceCollector:
    def test_collect_from_evaluation_success(self, collector):
        eval_rec = MockEvalRecord(passed=True, composite_score=0.95)
        exps = collector.collect_from_evaluation(eval_rec)
        assert len(exps) >= 1
        assert exps[0].success is True
        assert exps[0].source_type == ExperienceSource.EVALUATION.value

    def test_collect_from_evaluation_failure(self, collector):
        eval_rec = MockEvalRecord(passed=False, composite_score=0.3, issues=("test failure",))
        exps = collector.collect_from_evaluation(eval_rec)
        assert len(exps) >= 1
        assert exps[0].success is False

    def test_collect_from_evaluation_sets_lessons(self, collector):
        eval_rec = MockEvalRecord(passed=True, composite_score=0.92)
        exps = collector.collect_from_evaluation(eval_rec)
        assert len(exps[0].lessons) >= 1

    def test_collect_from_evaluation_sets_evaluation_id(self, collector):
        eval_rec = MockEvalRecord(id="eval_abc123")
        exps = collector.collect_from_evaluation(eval_rec)
        assert exps[0].evaluation_id == "eval_abc123"

    def test_collect_from_evaluation_sets_tags(self, collector):
        eval_rec = MockEvalRecord(target_type="agent", recommendation="accept")
        exps = collector.collect_from_evaluation(eval_rec)
        assert "agent" in exps[0].tags or any("agent" in t for t in exps[0].tags)

    def test_collect_from_agent_success(self, collector):
        exps = collector.collect_from_agent("agent_claude", "model.reason", success=True)
        assert len(exps) == 1
        assert exps[0].success is True
        assert exps[0].agent_id == "agent_claude"

    def test_collect_from_agent_failure(self, collector):
        exps = collector.collect_from_agent("agent_test", "code.analyze", success=False, error="timeout")
        assert exps[0].success is False
        assert "timeout" in exps[0].failure_reason

    def test_collect_from_agent_sets_source(self, collector):
        exps = collector.collect_from_agent("a", "c", success=True)
        assert exps[0].source_type == ExperienceSource.AGENT.value

    def test_collect_from_agent_duration_recorded(self, collector):
        exps = collector.collect_from_agent("a", "c", success=True, duration_ms=500)
        assert exps[0].metadata.get("duration_ms") == 500

    def test_collect_from_agent_capability_set(self, collector):
        exps = collector.collect_from_agent("a", "model.reason", success=True)
        assert exps[0].capability_id == "model.reason"

    def test_collect_and_persist_returns_count(self, collector):
        count = collector.collect_and_persist(sources=[])
        assert count == 0  # No sources = no collection
