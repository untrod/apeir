# -*- coding: utf-8 -*-
"""Tests for Context Builder 鈥?orchestrates providers into snapshots."""

from __future__ import annotations


from nous_runtime.context.builder import BuildRequest, ContextBuilder, build_context
from nous_runtime.context.models import ContextItem, ContextSnapshot
from nous_runtime.context.types import ProviderHealth



# Mock provider for controlled testing


class MockProvider:
    """A controllable context provider for testing."""
    source_type: str = "memory"

    def __init__(self, items: list[ContextItem] | None = None, source: str = "memory"):
        self._items = items or []
        self.source_type = source
        self.collect_called = False

    def collect(self, request_hint: str = "", limit: int = 100) -> list[ContextItem]:
        self.collect_called = True
        return self._items[:limit]

    def explain(self, item_ids: list[str]) -> dict[str, str]:
        return {iid: f"mock explanation for {iid}" for iid in item_ids}

    def health(self) -> ProviderHealth:
        return ProviderHealth(
            source=self.source_type,
            available=True,
            item_count=len(self._items),
        )


class FailingProvider:
    """A provider that raises on collect."""
    source_type: str = "device"

    def collect(self, request_hint: str = "", limit: int = 100) -> list[ContextItem]:
        raise RuntimeError("Simulated failure")

    def explain(self, item_ids: list[str]) -> dict[str, str]:
        return {}

    def health(self) -> ProviderHealth:
        return ProviderHealth(source="device", available=False, error="Simulated failure")


class PrivateProvider:
    """A provider that returns private items."""
    source_type: str = "memory"

    def __init__(self):
        self._items = [
            ContextItem(content="public data", source_type="memory", permission="read"),
            ContextItem(content="private data", source_type="memory", permission="private"),
            ContextItem(content="restricted data", source_type="memory", permission="restricted"),
        ]

    def collect(self, request_hint: str = "", limit: int = 100) -> list[ContextItem]:
        return self._items[:limit]

    def explain(self, item_ids: list[str]) -> dict[str, str]:
        return {iid: "explanation" for iid in item_ids}

    def health(self) -> ProviderHealth:
        return ProviderHealth(source="memory", available=True, item_count=len(self._items))



# Tests


class TestContextBuilder:
    """20 tests for ContextBuilder."""

    def test_builder_creates_snapshot(self):
        mock = MockProvider([
            ContextItem(content="test", source_type="memory", importance=0.9),
        ])
        builder = ContextBuilder(providers=[mock])
        snap = builder.build_context(BuildRequest(intent="test"))
        assert isinstance(snap, ContextSnapshot)
        assert snap.item_count >= 1

    def test_builder_collects_from_all_providers(self):
        mock1 = MockProvider([ContextItem(content="a", source_type="memory")], source="memory")
        mock2 = MockProvider([ContextItem(content="b", source_type="project")], source="project")
        builder = ContextBuilder(providers=[mock1, mock2])
        snap = builder.build_context(BuildRequest(intent="test"))
        assert snap.item_count >= 2

    def test_builder_applies_limit(self):
        items = [ContextItem(content=str(i), source_type="memory") for i in range(50)]
        mock = MockProvider(items)
        builder = ContextBuilder(providers=[mock])
        snap = builder.build_context(BuildRequest(intent="test", max_items=5))
        assert snap.item_count <= 5

    def test_builder_normalizes_duplicates(self):
        dup = ContextItem(content="duplicate", source_type="memory")
        mock = MockProvider([dup, dup, dup])
        builder = ContextBuilder(providers=[mock])
        snap = builder.build_context(BuildRequest(intent="test"))
        # Duplicates should be deduped
        assert snap.item_count == 1

    def test_builder_filters_private_items(self):
        mock = PrivateProvider()
        builder = ContextBuilder(providers=[mock])
        snap = builder.build_context(BuildRequest(intent="test"))
        # Private items should be filtered out
        for item in snap.items:
            assert item.permission != "private"

    def test_builder_handles_failing_provider(self):
        good = MockProvider([ContextItem(content="good", source_type="memory")])
        bad = FailingProvider()
        builder = ContextBuilder(providers=[good, bad])
        snap = builder.build_context(BuildRequest(intent="test"))
        # Should still get items from the good provider
        assert snap.item_count >= 1

    def test_builder_sets_metadata(self):
        mock = MockProvider([ContextItem(content="test", source_type="memory")])
        builder = ContextBuilder(providers=[mock])
        snap = builder.build_context(BuildRequest(intent="test"))
        assert "build_duration_ms" in snap.metadata
        assert "raw_count" in snap.metadata

    def test_builder_respects_source_filter(self):
        mock1 = MockProvider([ContextItem(content="mem", source_type="memory")], source="memory")
        mock2 = MockProvider([ContextItem(content="proj", source_type="project")], source="project")
        builder = ContextBuilder(providers=[mock1, mock2])
        snap = builder.build_context(BuildRequest(
            intent="test", sources=("memory",),
        ))
        sources = set(item.source_type for item in snap.items)
        assert "project" not in sources

    def test_builder_sets_aggregate_confidence(self):
        items = [ContextItem(content=str(i), source_type="memory", confidence=0.8) for i in range(5)]
        mock = MockProvider(items)
        builder = ContextBuilder(providers=[mock])
        snap = builder.build_context(BuildRequest(intent="test"))
        assert 0.7 <= snap.confidence <= 0.9

    def test_builder_ranks_items(self):
        items = [
            ContextItem(content="important", source_type="project", importance=1.0, confidence=1.0),
            ContextItem(content="unimportant", source_type="memory", importance=0.1, confidence=0.1),
        ]
        mock = MockProvider(items)
        builder = ContextBuilder(providers=[mock])
        snap = builder.build_context(BuildRequest(intent="test"))
        ranked = list(snap.items)
        # Project items should rank higher than generic memory
        assert ranked[0].source_type == "project"

    def test_builder_filters_low_importance(self):
        items = [
            ContextItem(content="hi", source_type="memory", importance=0.9),
            ContextItem(content="lo", source_type="memory", importance=0.0),
        ]
        mock = MockProvider(items)
        builder = ContextBuilder(providers=[mock])
        snap = builder.build_context(BuildRequest(
            intent="test", metadata={"min_importance": 0.5},
        ))
        assert snap.item_count == 1

    def test_builder_filters_low_confidence(self):
        items = [
            ContextItem(content="hi", source_type="memory", confidence=0.9),
            ContextItem(content="lo", source_type="memory", confidence=0.0),
        ]
        mock = MockProvider(items)
        builder = ContextBuilder(providers=[mock])
        snap = builder.build_context(BuildRequest(
            intent="test", metadata={"min_confidence": 0.5},
        ))
        assert snap.item_count == 1

    def test_builder_sets_sources(self):
        mock = MockProvider([ContextItem(content="test", source_type="memory")], source="memory")
        builder = ContextBuilder(providers=[mock])
        snap = builder.build_context(BuildRequest(intent="test"))
        assert "memory" in snap.sources

    def test_builder_populates_source_sections(self):
        mock = MockProvider([ContextItem(content="test", source_type="memory")], source="memory")
        builder = ContextBuilder(providers=[mock])
        snap = builder.build_context(BuildRequest(intent="test"))
        assert len(snap.memory) >= 1

    def test_builder_empty_providers(self):
        builder = ContextBuilder(providers=[])
        snap = builder.build_context(BuildRequest(intent="test"))
        assert snap.item_count == 0

    def test_builder_sets_user_project_context(self):
        mock = MockProvider([ContextItem(content="test", source_type="project")], source="project")
        builder = ContextBuilder(providers=[mock])
        snap = builder.build_context(BuildRequest(
            intent="test", user_id="user_1", project_id="proj_1",
        ))
        assert snap.user.get("user_id") == "user_1"
        assert snap.project.get("project_id") == "proj_1"

    def test_builder_runtime_context(self):
        mock = MockProvider([ContextItem(content="project context", source_type="project")])
        builder = ContextBuilder(providers=[mock])
        snap = builder.build_context(BuildRequest(intent="continue project X", context_hint="coding"))
        assert snap.runtime.get("intent") == "continue project X"

    def test_build_context_convenience(self):
        snap = build_context(BuildRequest(intent="test"), workspace="")
        assert isinstance(snap, ContextSnapshot)

    def test_builder_skips_invalid_items(self):
        # Items with empty content are invalid
        mock = MockProvider([
            ContextItem(content="", source_type="memory"),
            ContextItem(content="valid", source_type="memory"),
        ])
        builder = ContextBuilder(providers=[mock])
        snap = builder.build_context(BuildRequest(intent="test"))
        # The empty-content item should be skipped by normalize
        contents = [i.content for i in snap.items]
        assert "valid" in contents
