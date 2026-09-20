# -*- coding: utf-8 -*-
"""Tests for Pattern Discovery — 15 tests."""

from __future__ import annotations

import os
import tempfile

import pytest
from nous_runtime.experience.models import ExperienceRecord
from nous_runtime.experience.pattern import PatternEngine
from nous_runtime.experience.store import ExperienceStore


@pytest.fixture
def temp_workspace():
    with tempfile.TemporaryDirectory() as tmp:
        yield os.path.join(tmp, ".nous")


@pytest.fixture
def store(temp_workspace):
    return ExperienceStore(temp_workspace)


@pytest.fixture
def engine(store):
    return PatternEngine(store)


class TestPatternEngine:
    def test_discover_empty(self, engine):
        patterns = engine.discover()
        assert patterns == []

    def test_discover_success_pattern(self, store, engine):
        for i in range(5):
            store.save(ExperienceRecord(task_type="coding", action="refactor", result="success", success=True, confidence=0.9))
        patterns = engine.discover(min_frequency=3)
        success_pats = [p for p in patterns if p.pattern_type == "success"]
        assert len(success_pats) >= 1
        assert success_pats[0].frequency >= 3

    def test_discover_failure_pattern(self, store, engine):
        for i in range(5):
            store.save(ExperienceRecord(task_type="deploy", action="install", success=False, failure_reason="cuda mismatch", error_code="CUDA_ERR"))
        patterns = engine.discover(min_frequency=3)
        failure_pats = [p for p in patterns if p.pattern_type == "failure"]
        assert len(failure_pats) >= 1

    def test_discover_fix_pattern(self, store, engine):
        for i in range(5):
            store.save(ExperienceRecord(task_type="coding", action="refactor", success=True, lessons=("Use virtual env",)))
        patterns = engine.discover(min_frequency=3)
        fix_pats = [p for p in patterns if p.pattern_type == "fix"]
        assert len(fix_pats) >= 1

    def test_discover_below_threshold(self, store, engine):
        store.save(ExperienceRecord(task_type="coding", action="test", success=True))
        patterns = engine.discover(min_frequency=3)
        assert patterns == []

    def test_frequency_analysis_empty(self, engine):
        result = engine.frequency_analysis()
        assert result["total"] == 0

    def test_frequency_analysis(self, store, engine):
        for i in range(5):
            store.save(ExperienceRecord(task_type="coding", action="test", success=True, agent_id="agent_claude"))
        result = engine.frequency_analysis()
        assert result["total"] == 5
        assert result["success_rate"] == 1.0
