# -*- coding: utf-8 -*-
"""Experience engine tests."""

from nous_runtime.learning.experience import (
    record,
    query,
    stats,
    best_provider,
    count,
    clear,
)


class TestExperienceEngine:
    """Experience Engine must record and retrieve execution experience."""

    def setup_method(self):
        clear()

    def test_record_and_count(self):
        """Recording increases count."""
        assert count() == 0
        record(capability_id="test.cap", provider_id="test_prov", ok=True, duration_ms=100)
        assert count() == 1

    def test_query_all(self):
        """Query without filters returns all records."""
        record(capability_id="a.test", provider_id="p1", ok=True, duration_ms=50)
        record(capability_id="b.test", provider_id="p2", ok=False, duration_ms=200,
               error_code="NOUS_TIMEOUT")
        results = query(limit=10)
        assert len(results) == 2

    def test_query_filtered(self):
        """Query with filters returns matching records."""
        record(capability_id="a.test", provider_id="p1", ok=True)
        record(capability_id="a.test", provider_id="p2", ok=False)
        record(capability_id="b.test", provider_id="p1", ok=True)

        # Filter by capability
        a_results = query(capability_id="a.test")
        assert len(a_results) == 2

        # Filter by provider
        p1_results = query(provider_id="p1")
        assert len(p1_results) == 2

    def test_stats(self):
        """Statistics aggregate correctly."""
        record(capability_id="test.cap", provider_id="p1", ok=True, score=0.9, duration_ms=100)
        record(capability_id="test.cap", provider_id="p1", ok=False, score=0.1, duration_ms=300,
               error_code="NOUS_TIMEOUT")

        s = stats(provider_id="p1")
        assert s["total"] == 2
        assert s["success_rate"] == 0.5
        assert s["avg_duration_ms"] == 200.0
        assert "NOUS_TIMEOUT" in s["error_counts"]

    def test_empty_stats(self):
        """Empty experience returns zero stats."""
        s = stats()
        assert s["total"] == 0
        assert s["success_rate"] == 0.0

    def test_best_provider(self):
        """Best provider is selected by success rate."""
        # p1: 100% success
        for _ in range(3):
            record(capability_id="test.cap", provider_id="p1", ok=True, duration_ms=50)
        # p2: 33% success
        record(capability_id="test.cap", provider_id="p2", ok=True, duration_ms=10)
        record(capability_id="test.cap", provider_id="p2", ok=False, duration_ms=500)
        record(capability_id="test.cap", provider_id="p2", ok=False, duration_ms=500)

        best = best_provider("test.cap")
        assert best == "p1"

    def test_best_provider_none(self):
        """No experience returns None."""
        assert best_provider("nonexistent") is None
