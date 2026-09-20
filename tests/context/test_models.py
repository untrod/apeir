# -*- coding: utf-8 -*-
"""Tests for Context Data Model — ContextItem and ContextSnapshot."""

from __future__ import annotations

import pytest

from nous_runtime.context.models import ContextItem, ContextSnapshot
from nous_runtime.context.schema import CONTEXT_SCHEMA_VERSION, SnapshotStatus



# ContextItem


class TestContextItem:
    """15 tests for ContextItem."""

    def test_create_minimal(self):
        item = ContextItem(content="test", source_type="memory")
        assert item.item_id.startswith("ctx_")
        assert item.content == "test"
        assert item.source_type == "memory"

    def test_create_with_all_fields(self):
        item = ContextItem(
            content="project context",
            source_type="project",
            source_id="proj_001",
            importance=0.9,
            confidence=0.95,
            permission="read",
            tags=("project", "active"),
        )
        assert item.importance == 0.9
        assert item.confidence == 0.95
        assert item.permission == "read"
        assert "project" in item.tags

    def test_item_id_is_unique(self):
        a = ContextItem(content="a", source_type="memory")
        b = ContextItem(content="b", source_type="memory")
        assert a.item_id != b.item_id

    def test_created_at_auto_set(self):
        item = ContextItem(content="test", source_type="memory")
        assert item.created_at != ""
        assert "T" in item.created_at

    def test_importance_clamped(self):
        item = ContextItem(content="test", source_type="memory", importance=1.5)
        assert item.importance == 1.0
        item2 = ContextItem(content="test", source_type="memory", importance=-0.5)
        assert item2.importance == 0.0

    def test_confidence_clamped(self):
        item = ContextItem(content="test", source_type="memory", confidence=2.0)
        assert item.confidence == 1.0
        item2 = ContextItem(content="test", source_type="memory", confidence=-1.0)
        assert item2.confidence == 0.0

    def test_validate_valid_item(self):
        item = ContextItem(content="valid", source_type="memory")
        errors = item.validate()
        assert errors == []

    def test_validate_missing_content(self):
        item = ContextItem(content="", source_type="memory")
        errors = item.validate()
        assert any("content" in e for e in errors)

    def test_validate_bad_source_type(self):
        item = ContextItem(content="test", source_type="invalid_source")
        errors = item.validate()
        assert any("source_type" in e for e in errors)

    def test_validate_bad_permission(self):
        item = ContextItem(content="test", source_type="memory", permission="admin")
        errors = item.validate()
        assert any("permission" in e for e in errors)

    def test_validate_importance_range(self):
        item = ContextItem(content="test", source_type="memory", importance=1.5)
        # Post-init clamping fixes it, so validate should pass
        errors = item.validate()
        assert not any("importance" in e for e in errors)

    def test_to_dict(self):
        item = ContextItem(content="test", source_type="memory", tags=("a", "b"))
        d = item.to_dict()
        assert d["content"] == "test"
        assert d["source_type"] == "memory"
        assert d["tags"] == ["a", "b"]

    def test_from_dict(self):
        d = {"content": "restored", "source_type": "project", "importance": 0.8}
        item = ContextItem.from_dict(d)
        assert item.content == "restored"
        assert item.source_type == "project"
        assert item.importance == 0.8

    def test_from_dict_roundtrip(self):
        original = ContextItem(content="roundtrip", source_type="decision", importance=0.7)
        restored = ContextItem.from_dict(original.to_dict())
        assert restored.content == original.content
        assert restored.source_type == original.source_type
        assert restored.importance == original.importance

    def test_schema_version_default(self):
        item = ContextItem(content="test", source_type="memory")
        assert item.schema_version == CONTEXT_SCHEMA_VERSION

    def test_frozen_immutable(self):
        item = ContextItem(content="test", source_type="memory")
        with pytest.raises(Exception):
            item.content = "modified"  # type: ignore



# ContextSnapshot


class TestContextSnapshot:
    """15 tests for ContextSnapshot."""

    def test_create_empty(self):
        snap = ContextSnapshot()
        assert snap.id.startswith("snap_")
        assert snap.version == 1
        assert snap.item_count == 0

    def test_create_with_items(self):
        items = (
            ContextItem(content="a", source_type="memory"),
            ContextItem(content="b", source_type="project"),
        )
        snap = ContextSnapshot(items=items, sources=("memory", "project"))
        assert snap.item_count == 2
        assert snap.source_count == 2

    def test_timestamp_auto_set(self):
        snap = ContextSnapshot()
        assert snap.timestamp != ""
        assert "T" in snap.timestamp

    def test_default_status_active(self):
        snap = ContextSnapshot()
        assert snap.status == SnapshotStatus.ACTIVE.value

    def test_checksum_deterministic(self):
        items = (ContextItem(content="x", source_type="memory"),)
        snap1 = ContextSnapshot(id="test1", items=items, sources=("memory",))
        snap2 = ContextSnapshot(id="test1", items=items, sources=("memory",))
        assert snap1.checksum() == snap2.checksum()

    def test_checksum_differs_on_content(self):
        items_a = (ContextItem(content="a", source_type="memory"),)
        items_b = (ContextItem(content="b", source_type="memory"),)
        snap_a = ContextSnapshot(id="s1", items=items_a)
        snap_b = ContextSnapshot(id="s1", items=items_b)
        assert snap_a.checksum() != snap_b.checksum()

    def test_to_dict_includes_computed(self):
        snap = ContextSnapshot()
        d = snap.to_dict()
        assert "id" in d
        assert "checksum" in d
        assert "item_count" in d
        assert d["item_count"] == 0

    def test_from_dict_restores_items(self):
        items = (ContextItem(content="restored", source_type="memory"),)
        snap = ContextSnapshot(items=items, sources=("memory",))
        restored = ContextSnapshot.from_dict(snap.to_dict())
        assert restored.item_count == 1
        assert restored.items[0].content == "restored"

    def test_confidence_clamped(self):
        snap = ContextSnapshot(confidence=1.5)
        assert snap.confidence == 1.0

    def test_with_status_returns_new_instance(self):
        snap = ContextSnapshot(status="active")
        archived = snap.with_status(SnapshotStatus.ARCHIVED)
        assert archived.status == SnapshotStatus.ARCHIVED.value
        assert snap.status == "active"  # Original unchanged

    def test_source_aligned_sections(self):
        snap = ContextSnapshot(
            project={"name": "test_project"},
            user={"user_id": "u1"},
            task={"task_id": "t1"},
        )
        assert snap.project["name"] == "test_project"
        assert snap.user["user_id"] == "u1"
        assert snap.task["task_id"] == "t1"

    def test_memory_section(self):
        snap = ContextSnapshot(memory=[{"key": "val"}])
        assert snap.memory == [{"key": "val"}]

    def test_frozen_immutable(self):
        snap = ContextSnapshot()
        with pytest.raises(Exception):
            snap.id = "changed"  # type: ignore

    def test_schema_version(self):
        snap = ContextSnapshot()
        assert snap.schema_version == CONTEXT_SCHEMA_VERSION

    def test_item_count_matches_items(self):
        items = tuple(ContextItem(content=str(i), source_type="memory") for i in range(10))
        snap = ContextSnapshot(items=items)
        assert snap.item_count == 10
