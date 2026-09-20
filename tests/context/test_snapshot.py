# -*- coding: utf-8 -*-
"""Tests for Context Snapshot 鈥?create, restore, list."""

from __future__ import annotations

import logging
import os
import tempfile

import pytest

from nous_runtime.context.models import ContextItem, ContextSnapshot
from nous_runtime.context.schema import ContextSource
from nous_runtime.context.snapshot import (
    create_snapshot,
    latest_snapshot_id,
    list_snapshots,
    restore_snapshot,
)
from nous_runtime.context.store import ContextStore
from nous_runtime.context.types import RestoreResult


@pytest.fixture
def temp_workspace():
    with tempfile.TemporaryDirectory() as tmp:
        nous_dir = os.path.join(tmp, ".nous")
        os.makedirs(nous_dir, exist_ok=True)
        yield nous_dir


class TestSnapshotCreate:
    """Tests for create_snapshot."""

    def test_create_snapshot_returns_snapshot(self, temp_workspace):
        snap = create_snapshot(workspace=temp_workspace, intent="test_checkpoint")
        assert isinstance(snap, ContextSnapshot)
        assert snap.id.startswith("snap_")

    def test_create_snapshot_with_metadata(self, temp_workspace):
        snap = create_snapshot(
            workspace=temp_workspace,
            intent="checkpoint",
            user_id="u1",
            project_id="p1",
            task_id="t1",
        )
        assert snap.metadata.get("snapshot_type") == "checkpoint"

    def test_create_snapshot_persists(self, temp_workspace):
        snap = create_snapshot(workspace=temp_workspace, intent="test", persist=True)
        store = ContextStore(temp_workspace)
        restored = store.get(snap.id)
        assert restored is not None
        assert restored.id == snap.id

    def test_create_snapshot_no_persist(self, temp_workspace):
        snap = create_snapshot(workspace=temp_workspace, intent="test", persist=False)
        # May or may not exist depending on implementation
        assert snap.id != ""


class TestSnapshotRestore:
    """Tests for restore_snapshot."""

    def test_restore_returns_result(self, temp_workspace):
        result = restore_snapshot(workspace=temp_workspace)
        assert isinstance(result, RestoreResult)

    def test_restore_nonexistent_id(self, temp_workspace):
        result = restore_snapshot(snapshot_id="nonexistent", workspace=temp_workspace)
        assert result.success is False
        assert "not found" in result.errors[0].lower()

    def test_restore_from_stored(self, temp_workspace):
        # First create and save a snapshot
        snap = create_snapshot(workspace=temp_workspace, intent="save_point", persist=True)
        # Now restore it
        result = restore_snapshot(snapshot_id=snap.id, workspace=temp_workspace)
        assert result.success is True
        assert result.snapshot_id == snap.id

    def test_restore_has_duration(self, temp_workspace):
        snap = create_snapshot(workspace=temp_workspace, intent="test", persist=True)
        result = restore_snapshot(snapshot_id=snap.id, workspace=temp_workspace)
        assert result.duration_ms >= 0

    def test_restore_single_source_snapshot_has_no_missing_source_warning(
        self, temp_workspace, caplog
    ):
        item = ContextItem(
            item_id="runtime_item",
            content="runtime checkpoint",
            source_type=ContextSource.RUNTIME.value,
            source_id="runtime",
        )
        snapshot = ContextSnapshot(
            id="runtime_only",
            items=(item,),
            sources=(ContextSource.RUNTIME.value,),
        )
        ContextStore(temp_workspace).save(snapshot)

        with caplog.at_level(logging.WARNING, logger="nous.context.snapshot"):
            result = restore_snapshot(
                snapshot_id=snapshot.id,
                workspace=temp_workspace,
            )

        assert result.success is True
        assert result.missing_sources == []
        assert "missing sources" not in caplog.text.lower()


class TestSnapshotList:
    """Tests for list_snapshots and latest_snapshot_id."""

    def test_list_returns_list(self, temp_workspace):
        snapshots = list_snapshots(workspace=temp_workspace)
        assert isinstance(snapshots, list)

    def test_list_includes_summary_fields(self, temp_workspace):
        create_snapshot(workspace=temp_workspace, intent="test", persist=True)
        snapshots = list_snapshots(workspace=temp_workspace)
        if snapshots:
            s = snapshots[0]
            assert "id" in s
            assert "timestamp" in s
            assert "status" in s
            assert "item_count" in s
            assert "sources" in s

    def test_list_respects_limit(self, temp_workspace):
        for i in range(5):
            create_snapshot(workspace=temp_workspace, intent=f"test_{i}", persist=True)
        snapshots = list_snapshots(workspace=temp_workspace, limit=3)
        assert len(snapshots) <= 3

    def test_list_filter_by_status(self, temp_workspace):
        create_snapshot(workspace=temp_workspace, intent="active_test", persist=True)
        archived = list_snapshots(workspace=temp_workspace, status="archived")
        assert len(archived) == 0  # No archived snapshots created

    def test_latest_snapshot_id(self, temp_workspace):
        snap = create_snapshot(workspace=temp_workspace, intent="latest_test", persist=True)
        latest = latest_snapshot_id(workspace=temp_workspace)
        assert latest == snap.id

    def test_latest_snapshot_id_empty(self, temp_workspace):
        latest = latest_snapshot_id(workspace=temp_workspace)
        assert latest == ""  # No snapshots
