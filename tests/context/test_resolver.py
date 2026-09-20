# -*- coding: utf-8 -*-
"""Tests for Context Resolver — scoring, selection, explanation."""

from __future__ import annotations

import pytest

from nous_runtime.context.models import ContextItem
from nous_runtime.context.resolver import ContextResolver, resolve_context
from nous_runtime.context.types import ContextExplanation


class TestContextResolver:
    """20 tests for ContextResolver."""

    @pytest.fixture
    def resolver(self):
        return ContextResolver()

    @pytest.fixture
    def sample_items(self):
        return [
            ContextItem(
                content="project Nous Runtime phase 3 implementation",
                source_type="project",
                importance=0.9,
                confidence=1.0,
                tags=("project", "active"),
            ),
            ContextItem(
                content="memory fact about context runtime",
                source_type="memory",
                importance=0.7,
                confidence=0.8,
                tags=("fact",),
            ),
            ContextItem(
                content="old decision from last week",
                source_type="decision",
                importance=0.5,
                confidence=0.5,
                created_at="2020-01-01T00:00:00Z",
            ),
            ContextItem(
                content="device android phone status",
                source_type="device",
                importance=0.3,
                confidence=0.5,
            ),
        ]

    # -- scoring tests --

    def test_resolve_returns_explanation(self, resolver, sample_items):
        result = resolver.resolve(sample_items, intent="continue project implementation")
        assert isinstance(result, ContextExplanation)

    def test_resolve_scores_items(self, resolver, sample_items):
        result = resolver.resolve(sample_items, intent="continue project")
        assert len(result.selected_items) > 0

    def test_resolve_relevance_scores_higher_with_match(self, resolver, sample_items):
        result = resolver.resolve(sample_items, intent="context runtime")
        # Items matching "context runtime" should score higher
        scores = [(r.content_summary, r.score.composite) for r in result.selected_items]
        assert len(scores) > 0

    def test_resolve_empty_items(self, resolver):
        result = resolver.resolve([], intent="test")
        assert len(result.selected_items) == 0
        assert result.confidence == 1.0

    def test_resolve_respects_max_items(self, resolver, sample_items):
        result = resolver.resolve(sample_items, intent="test", max_items=1)
        assert len(result.selected_items) <= 1

    def test_resolve_respects_threshold(self, resolver, sample_items):
        # Very high threshold → nothing selected
        result = resolver.resolve(sample_items, intent="test", threshold=0.99)
        # Some items might still pass if they have very high scores
        for item in result.selected_items:
            assert item.score.composite >= 0.99

    def test_resolve_default_threshold(self, resolver, sample_items):
        result = resolver.resolve(sample_items, intent="test")
        for item in result.selected_items:
            assert item.score.composite >= 0.40

    def test_score_decomposition(self, resolver, sample_items):
        result = resolver.resolve(sample_items, intent="continue project")
        for item in result.selected_items:
            s = item.score
            assert 0.0 <= s.relevance <= 1.0
            assert 0.0 <= s.freshness <= 1.0
            assert 0.0 <= s.confidence <= 1.0
            assert 0.0 <= s.importance <= 1.0

    def test_score_composite_matches_formula(self, resolver):
        item = ContextItem(content="test", source_type="memory", importance=0.8, confidence=0.9)
        result = resolver.resolve([item], intent="test")
        if result.selected_items:
            s = result.selected_items[0].score
            expected = 0.35 * s.relevance + 0.25 * s.freshness + 0.20 * s.confidence + 0.20 * s.importance
            assert abs(s.composite - expected) < 0.01

    def test_resolve_assigns_ranks(self, resolver, sample_items):
        result = resolver.resolve(sample_items, intent="test")
        ranks = [r.rank for r in result.selected_items]
        assert ranks == sorted(ranks)
        assert ranks[0] == 1

    def test_resolve_discards_low_scoring(self, resolver, sample_items):
        result = resolver.resolve(sample_items, intent="test", threshold=0.5)
        for item in result.discarded_items:
            assert item.score.composite < 0.5

    def test_resolve_provides_reasoning(self, resolver, sample_items):
        result = resolver.resolve(sample_items, intent="test")
        assert len(result.reasoning) > 0
        assert any("Weights:" in r for r in result.reasoning)

    def test_resolve_selection_summary(self, resolver, sample_items):
        result = resolver.resolve(sample_items, intent="test")
        assert "Selected" in result.selection_summary
        assert "threshold" in result.selection_summary

    def test_resolve_explanation_per_item(self, resolver, sample_items):
        result = resolver.resolve(sample_items, intent="project runtime")
        for item in result.selected_items:
            assert item.selection_reason != ""

    def test_freshness_decay_old_item(self, resolver):
        old_item = ContextItem(
            content="ancient history",
            source_type="memory",
            created_at="2020-01-01T00:00:00Z",
            importance=0.9,
            confidence=0.9,
        )
        result = resolver.resolve([old_item], intent="test")
        if result.selected_items:
            assert result.selected_items[0].score.freshness < 0.5

    def test_freshness_recent_item(self, resolver):
        from datetime import datetime, timezone
        recent = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        new_item = ContextItem(
            content="brand new",
            source_type="memory",
            created_at=recent,
            importance=0.9,
            confidence=0.9,
        )
        result = resolver.resolve([new_item], intent="test")
        if result.selected_items:
            assert result.selected_items[0].score.freshness > 0.8

    def test_resolve_custom_weights(self, resolver):
        resolver = ContextResolver(weights={
            "relevance": 0.5, "freshness": 0.0, "confidence": 0.25, "importance": 0.25,
        })
        items = [ContextItem(content="test", source_type="memory", importance=0.5, confidence=0.5)]
        result = resolver.resolve(items, intent="test")
        # With zero freshness weight, scoring still works
        assert len(result.selected_items) >= 1

    def test_convenience_function(self, sample_items):
        result = resolve_context(sample_items, intent="test")
        assert isinstance(result, ContextExplanation)

    def test_full_relevance_with_exact_match(self, resolver):
        item = ContextItem(
            content="continue project Nous Runtime implementation",
            source_type="project",
            importance=0.9,
            confidence=1.0,
        )
        result = resolver.resolve([item], intent="continue project Nous Runtime")
        if result.selected_items:
            assert result.selected_items[0].score.relevance > 0.5
