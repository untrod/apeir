# -*- coding: utf-8 -*-
"""Tests for ContextStore — SQLite persistence."""

from __future__ import annotations

import os
import tempfile

import pytest

from nous_runtime.context.models import ContextItem, ContextSnapshot
from nous_runtime.context.store import ContextStore


@pytest.fixture
def temp_workspace():
    """Create a temporary .nous workspace directory."""
    with tempfile.TemporaryDirectory() as tmp:
        nous_dir = os.path.join(tmp, ".nous")
        os.makedirs(nous_dir, exist_ok=True)
        yield nous_dir


@pytest.fixture
def store(temp_workspace):
    """Create a ContextStore backed by a temp workspace."""
    return ContextStore(temp_workspace)


@pytest.fixture
def sample_snapshot():
    """A simple snapshot for testing."""
    items = (
        ContextItem(content="test item", source_type="memory", importance=0.8),
        ContextItem(content="project item", source_type="project", importance=0.9),
    )
    return ContextSnapshot(items=items, sources=("memory", "project"), confidence=0.85)


class TestContextStore:
    """15+ tests for ContextStore."""

    def test_save_and_get(self, store, sample_snapshot):
        store.save(sample_snapshot)
        restored = store.get(sample_snapshot.id)
        assert restored is not None
        assert restored.id == sample_snapshot.id
        assert restored.item_count == sample_snapshot.item_count

    def test_get_nonexistent(self, store):
        assert store.get("nonexistent_id") is None

    def test_list_empty(self, store):
        snapshots = store.list()
        assert snapshots == []

    def test_list_with_data(self, store, sample_snapshot):
        store.save(sample_snapshot)
        snapshots = store.list()
        assert len(snapshots) == 1
        assert snapshots[0].id == sample_snapshot.id

    def test_list_limit(self, store):
        for i in range(5):
            snap = ContextSnapshot(id=f"snap_{i}")
            store.save(snap)
        snapshots = store.list(limit=3)
        assert len(snapshots) == 3

    def test_list_offset(self, store):
        for i in range(5):
            snap = ContextSnapshot(id=f"snap_{i}")
            store.save(snap)
        all_snaps = store.list(limit=10)
        page2 = store.list(limit=10, offset=2)
        assert len(page2) == len(all_snaps) - 2

    def test_list_filter_by_status(self, store):
        snap1 = ContextSnapshot(id="s1", status="active")
        snap2 = ContextSnapshot(id="s2", status="archived")
        store.save(snap1)
        store.save(snap2)
        active = store.list(status="active")
        assert len(active) == 1
        assert active[0].id == "s1"

    def test_list_order_desc(self, store):
        snap1 = ContextSnapshot(id="s1", timestamp="2025-01-01T00:00:00Z")
        snap2 = ContextSnapshot(id="s2", timestamp="2025-01-02T00:00:00Z")
        store.save(snap1)
        store.save(snap2)
        snapshots = store.list(order="DESC")
        assert snapshots[0].id == "s2"  # Newest first

    def test_list_order_asc(self, store):
        snap1 = ContextSnapshot(id="s1", timestamp="2025-01-01T00:00:00Z")
        snap2 = ContextSnapshot(id="s2", timestamp="2025-01-02T00:00:00Z")
        store.save(snap1)
        store.save(snap2)
        snapshots = store.list(order="ASC")
        assert snapshots[0].id == "s1"  # Oldest first

    def test_delete(self, store, sample_snapshot):
        store.save(sample_snapshot)
        assert store.delete(sample_snapshot.id) is True
        assert store.get(sample_snapshot.id) is None

    def test_delete_nonexistent(self, store):
        assert store.delete("nonexistent") is False

    def test_restore(self, store, sample_snapshot):
        store.save(sample_snapshot)
        restored = store.restore(sample_snapshot.id)
        assert restored is not None
        assert restored.status == "restored"
        # Verify it was re-saved with restored status
        re_read = store.get(sample_snapshot.id)
        assert re_read.status == "restored"

    def test_restore_nonexistent(self, store):
        assert store.restore("nonexistent") is None

    def test_save_overwrites(self, store, sample_snapshot):
        store.save(sample_snapshot)
        # Modify and re-save
        from nous_runtime.context.schema import SnapshotStatus
        updated = sample_snapshot.with_status(SnapshotStatus.ARCHIVED)
        store.save(updated)
        re_read = store.get(sample_snapshot.id)
        assert re_read.status == "archived"

    def test_audit_record_and_retrieve(self, store, sample_snapshot):
        store.save(sample_snapshot)
        store.record_audit(sample_snapshot.id, "agent_01", "test purpose")
        entries = store.get_audit_log(snapshot_id=sample_snapshot.id)
        assert len(entries) >= 1
        assert entries[0]["actor"] == "agent_01"

    def test_audit_filter_by_actor(self, store, sample_snapshot):
        store.save(sample_snapshot)
        store.record_audit(sample_snapshot.id, "agent_a", "purpose 1")
        store.record_audit(sample_snapshot.id, "agent_b", "purpose 2")
        entries = store.get_audit_log(actor="agent_a")
        assert all(e["actor"] == "agent_a" for e in entries)

    def test_stats(self, store, sample_snapshot):
        store.save(sample_snapshot)
        stats = store.stats()
        assert stats["total_snapshots"] == 1
        assert stats["active_snapshots"] == 1
        assert "db_path" in stats

    def test_checksum_persisted(self, store, sample_snapshot):
        store.save(sample_snapshot)
        restored = store.get(sample_snapshot.id)
        assert restored.checksum() == sample_snapshot.checksum()
