# -*- coding: utf-8 -*-
"""Tests for ExperienceStore — 20 tests."""

from __future__ import annotations

import os
import tempfile

import pytest
from nous_runtime.experience.models import ExperiencePattern, ExperienceRecord
from nous_runtime.experience.store import ExperienceStore


@pytest.fixture
def temp_workspace():
    with tempfile.TemporaryDirectory() as tmp:
        yield os.path.join(tmp, ".nous")


@pytest.fixture
def store(temp_workspace):
    return ExperienceStore(temp_workspace)


@pytest.fixture
def sample_record():
    return ExperienceRecord(task_type="coding", action="refactor", result="success", success=True, confidence=0.9)


class TestExperienceStore:
    def test_save_and_get(self, store, sample_record):
        assert store.save(sample_record) is True
        r = store.get(sample_record.id)
        assert r is not None
        assert r.task_type == "coding"

    def test_get_nonexistent(self, store):
        assert store.get("nonexistent") is None

    def test_list_empty(self, store):
        assert store.list() == []

    def test_list_with_data(self, store, sample_record):
        store.save(sample_record)
        records = store.list()
        assert len(records) == 1

    def test_list_filter_task_type(self, store):
        store.save(ExperienceRecord(task_type="coding", action="test"))
        store.save(ExperienceRecord(task_type="deploy", action="test"))
        coding = store.list(task_type="coding")
        assert len(coding) == 1

    def test_list_filter_status(self, store):
        store.save(ExperienceRecord(task_type="test", action="test", status="trusted"))
        store.save(ExperienceRecord(task_type="test", action="test", status="new"))
        trusted = store.list(status="trusted")
        assert len(trusted) == 1

    def test_list_filter_result(self, store):
        store.save(ExperienceRecord(task_type="test", action="a", success=True, result="success"))
        store.save(ExperienceRecord(task_type="test", action="b", success=False, result="failure"))
        successes = store.list(result="success")
        assert len(successes) == 1

    def test_search(self, store):
        store.save(ExperienceRecord(task_type="coding", task_summary="deploy jetson environment", action="install jetpack"))
        results = store.search("jetson")
        assert len(results) >= 1

    def test_search_no_match(self, store):
        store.save(ExperienceRecord(task_type="coding", task_summary="write tests"))
        results = store.search("nonexistent_query_xyz")
        assert len(results) == 0

    def test_update_status(self, store, sample_record):
        store.save(sample_record)
        assert store.update_status(sample_record.id, "validated") is True
        r = store.get(sample_record.id)
        assert r.status == "validated"

    def test_save_pattern(self, store):
        p = ExperiencePattern(pattern_type="success", name="Test", frequency=5)
        assert store.save_pattern(p) is True
        patterns = store.list_patterns()
        assert len(patterns) == 1

    def test_list_patterns_filter_type(self, store):
        store.save_pattern(ExperiencePattern(pattern_type="success", name="S", frequency=10))
        store.save_pattern(ExperiencePattern(pattern_type="failure", name="F", frequency=5))
        successes = store.list_patterns(pattern_type="success")
        assert len(successes) == 1

    def test_stats(self, store, sample_record):
        store.save(sample_record)
        s = store.stats()
        assert s["total_experiences"] == 1

    def test_stats_empty(self, store):
        s = store.stats()
        assert s["total_experiences"] == 0
