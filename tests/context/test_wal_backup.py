"""Existing workspace backups must include committed Context/Governance WAL."""

import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from nous_runtime.backup.manager import BackupManager
from nous_runtime.context.store import ContextStore
from nous_runtime.governance.store import GovernanceStore


@pytest.mark.parametrize("owner", ["context", "governance"])
def test_existing_backup_contains_committed_audit_and_not_pending_transaction(
    tmp_path, monkeypatch, owner
):
    # The context snapshot hook is independent of the database copy being
    # qualified; do not let it checkpoint the original and hide missing WAL.
    monkeypatch.setattr(
        "nous_runtime.context.snapshot.create_snapshot", lambda **_: None
    )
    if owner == "context":
        original = ContextStore(tmp_path)
        assert original.record_audit("snapshot", "operator", "original")
        table, column = "context_audit", "purpose"
    else:
        original = GovernanceStore(tmp_path)
        with original.operation_transaction() as db:
            original.append_operation_audit(db, "original", {})
        table, column = "governance_audit", "event_type"
    # The live, idle reader keeps WAL present even on older CPython. No pool or
    # production connection policy is changed by this fixture.
    reader = sqlite3.connect(
        Path(original.db_path).absolute().as_uri() + "?mode=ro", uri=True
    )
    writer = sqlite3.connect(original.db_path)
    writer.row_factory = sqlite3.Row
    try:
        reader.execute(f"SELECT {column} FROM {table}").fetchall()
        writer.execute("BEGIN IMMEDIATE")
        if owner == "context":
            writer.execute(
                "INSERT INTO context_audit (snapshot_id, purpose) VALUES ('snapshot', 'pending')"
            )
        else:
            original.append_operation_audit(writer, "pending", {})
        assert Path(original.db_path + "-wal").is_file()
        report = BackupManager(str(tmp_path)).create_backup()
        assert report["errors"] == []
        backup = (
            tmp_path / "backups" / report["backup_name"] / Path(original.db_path).name
        )
        db = sqlite3.connect(backup)
        try:
            assert db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
            assert db.execute(f"SELECT {column} FROM {table}").fetchall() == [
                ("original",)
            ]
        finally:
            db.close()
        assert writer.in_transaction
    finally:
        writer.rollback()
        writer.close()
        reader.close()


def test_restore_retains_sqlite_inode_and_reports_original_audit(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "nous_runtime.context.snapshot.create_snapshot", lambda **_: None
    )
    original = ContextStore(tmp_path)
    assert original.record_audit("snapshot", "operator", "original")
    manager = BackupManager(str(tmp_path))
    report = manager.create_backup()
    assert report["errors"] == []
    assert original.record_audit("snapshot", "operator", "later")
    reader = sqlite3.connect(original.db_path)
    try:
        assert reader.execute("SELECT COUNT(*) FROM context_audit").fetchone()[0] == 2
        restored = manager.restore_backup(report["backup_name"])
        assert restored["success"] and restored["files_restored"] == 1
        assert restored["errors"] == []
        # The already-open connection sees the restored database, not an old
        # unlinked inode or stale WAL. Restoration is not a task execution.
        assert reader.execute("SELECT purpose FROM context_audit").fetchall() == [
            ("original",)
        ]
    finally:
        reader.close()


def test_corrupt_database_backup_publishes_no_partial_file(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "nous_runtime.context.snapshot.create_snapshot", lambda **_: None
    )
    (tmp_path / "context.db").write_bytes(b"not a sqlite database")
    report = BackupManager(str(tmp_path)).create_backup()
    assert report["errors"]
    assert report["files_backed_up"] == 0
    output = tmp_path / "backups" / report["backup_name"]
    assert {p.name for p in output.iterdir()} == {"manifest.json"}
    assert (tmp_path / "context.db").read_bytes() == b"not a sqlite database"


def test_same_second_backup_never_overwrites_the_original(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "nous_runtime.context.snapshot.create_snapshot", lambda **_: None
    )
    instant = datetime(2026, 11, 9, tzinfo=timezone.utc)
    monkeypatch.setattr(
        "nous_runtime.backup.manager.datetime", SimpleNamespace(now=lambda _: instant)
    )
    original = ContextStore(tmp_path)
    assert original.record_audit("snapshot", "operator", "original")
    manager = BackupManager(str(tmp_path))
    report = manager.create_backup("operator")
    path = tmp_path / "backups" / report["backup_name"]
    saved = {entry.name: entry.read_bytes() for entry in path.iterdir()}
    assert original.record_audit("snapshot", "operator", "later")
    with pytest.raises(FileExistsError):
        manager.create_backup("operator")
    assert {entry.name: entry.read_bytes() for entry in path.iterdir()} == saved


def test_restore_failure_does_not_report_success_or_change_original(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(
        "nous_runtime.context.snapshot.create_snapshot", lambda **_: None
    )
    original = ContextStore(tmp_path)
    assert original.record_audit("snapshot", "operator", "original")
    manager = BackupManager(str(tmp_path))
    report = manager.create_backup()
    backup = tmp_path / "backups" / report["backup_name"] / "context.db"
    backup.write_bytes(b"corrupted backup")
    restored = manager.restore_backup(report["backup_name"])
    assert not restored["success"]
    assert restored["files_restored"] == 0
    assert restored["errors"] == ["context.db: DatabaseError"]
    assert [row["purpose"] for row in original.get_audit_log()] == ["original"]


def test_restore_cannot_overwrite_an_original_active_writer(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "nous_runtime.context.snapshot.create_snapshot", lambda **_: None
    )
    original = ContextStore(tmp_path)
    assert original.record_audit("snapshot", "operator", "original")
    manager = BackupManager(str(tmp_path))
    report = manager.create_backup()
    assert original.record_audit("snapshot", "operator", "later")
    writer = sqlite3.connect(original.db_path)
    try:
        writer.execute("BEGIN IMMEDIATE")
        writer.execute(
            "INSERT INTO context_audit (snapshot_id, purpose) VALUES ('snapshot', 'pending')"
        )
        restored = manager.restore_backup(report["backup_name"])
        assert not restored["success"]
        assert restored["files_restored"] == 0
        assert restored["errors"] == ["context.db: TimeoutError"]
        assert writer.in_transaction
        assert writer.execute("SELECT COUNT(*) FROM context_audit").fetchone()[0] == 3
    finally:
        writer.rollback()
        writer.close()
    assert {row["purpose"] for row in original.get_audit_log()} == {"original", "later"}


@pytest.mark.parametrize(
    "name", ["../escape", "..\\escape", "..", "/outside", "C:outside"]
)
def test_backup_names_cannot_escape_existing_workspace(tmp_path, name):
    manager = BackupManager(str(tmp_path))
    with pytest.raises(ValueError, match="single name"):
        manager.create_backup(name)
    assert not manager.restore_backup(name)["success"]
    assert not (tmp_path / "backups").exists()
