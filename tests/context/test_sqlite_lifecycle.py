"""Context persistence retains audits without leaking or reopening a writer."""

import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

from nous_runtime.context import store
from nous_runtime.context.exceptions import ContextStoreError


@pytest.mark.parametrize("readonly", [False, True])
@pytest.mark.parametrize(
    "phase", ["busy_timeout", "journal_mode", "foreign_keys", "checkpoint"]
)
def test_configuration_failure_closes_original_connection(
    tmp_path, monkeypatch, readonly, phase
):
    path = tmp_path / "context.db"
    original_connect = sqlite3.connect
    original_connect(path).close()
    opened = []

    class Connection(sqlite3.Connection):
        closed = False

        def execute(self, sql, *args, **kwargs):
            if phase in sql:
                raise sqlite3.OperationalError("injected configuration failure")
            return super().execute(sql, *args, **kwargs)

        def setconfig(self, *_args):
            if phase == "checkpoint":
                raise sqlite3.OperationalError("injected configuration failure")

        def close(self):
            self.closed = True
            return super().close()

    def connect(*args, **kwargs):
        connection = original_connect(*args, factory=Connection, **kwargs)
        opened.append(connection)  # Do not let GC conceal lost ownership.
        return connection

    # Exercise the supported SQLite configuration path on every Python version.
    monkeypatch.setattr(
        store.sqlite3, "SQLITE_DBCONFIG_NO_CKPT_ON_CLOSE", 1006, raising=False
    )
    monkeypatch.setattr(store.sqlite3, "connect", connect)
    try:
        if readonly and phase == "journal_mode":
            with store._db_connect(str(path), readonly=True):
                pass
        else:
            with pytest.raises(sqlite3.OperationalError, match="configuration failure"):
                with store._db_connect(str(path), readonly=readonly):
                    pytest.fail("failed configuration admitted an operation")
        assert len(opened) == 1
        assert opened[0].closed
    finally:
        for connection in opened:
            connection.close()


def test_initialized_context_reopens_without_competing_for_original_writer(tmp_path):
    original = store.ContextStore(tmp_path)
    with store._db_connect(original.db_path) as writer:
        writer.execute("BEGIN IMMEDIATE")
        writer.execute(
            "INSERT INTO context_audit (snapshot_id, actor, purpose) "
            "VALUES ('original', 'operator', 'pending audit')"
        )
        reopened = store.ContextStore(tmp_path)
        assert reopened.get_audit_log() == []
        assert writer.in_transaction
    assert [row["purpose"] for row in reopened.get_audit_log()] == ["pending audit"]


def test_initial_schema_and_marker_publish_in_one_transaction(tmp_path, monkeypatch):
    original_connect = sqlite3.connect
    statements = []
    publication = []

    def connect(*args, **kwargs):
        connection = original_connect(*args, **kwargs)

        def trace(sql):
            statement = sql.strip().rstrip(";").upper()
            if statement.startswith(("BEGIN", "COMMIT", "ROLLBACK")):
                statements.append(statement)
            if statement.startswith(("CREATE ", "INSERT ")):
                publication.append(connection.in_transaction)

        connection.set_trace_callback(trace)
        return connection

    monkeypatch.setattr(store.sqlite3, "connect", connect)
    store.ContextStore(tmp_path)
    assert publication and all(publication)
    assert statements == ["BEGIN IMMEDIATE", "COMMIT"]


def test_failed_marker_rolls_back_schema_without_losing_previous_data(
    tmp_path, monkeypatch
):
    path = str(tmp_path / "context.db")
    with store._db_connect(path) as db:
        db.execute("CREATE TABLE retained (value TEXT)")
        db.execute("INSERT INTO retained VALUES ('original')")
    original_connect = sqlite3.connect

    class Connection(sqlite3.Connection):
        def execute(self, sql, *args, **kwargs):
            if sql.startswith("INSERT OR IGNORE INTO context_snapshots"):
                raise sqlite3.OperationalError("injected schema marker failure")
            return super().execute(sql, *args, **kwargs)

    def connect(*args, **kwargs):
        return original_connect(*args, factory=Connection, **kwargs)

    with monkeypatch.context() as fault:
        fault.setattr(store.sqlite3, "connect", connect)
        with pytest.raises(ContextStoreError, match="schema marker failure"):
            store.ContextStore(tmp_path)
    with store._db_connect(path, readonly=True) as db:
        assert db.execute("SELECT value FROM retained").fetchone()[0] == "original"
        assert not db.execute(
            "SELECT name FROM sqlite_master WHERE name LIKE 'context_%'"
        ).fetchall()
        assert db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"


@pytest.mark.parametrize("missing", ["idx_audit_snapshot", "__schema__"])
def test_reopening_repairs_missing_schema_entry_and_retains_audit(tmp_path, missing):
    original = store.ContextStore(tmp_path)
    assert original.record_audit("snapshot", "operator", "retained")
    with store._db_connect(original.db_path) as db:
        if missing == "__schema__":
            db.execute("DELETE FROM context_snapshots WHERE id='__schema__'")
        else:
            db.execute("DROP INDEX idx_audit_snapshot")
    reopened = store.ContextStore(tmp_path)
    assert [row["purpose"] for row in reopened.get_audit_log()] == ["retained"]
    with store._db_connect(reopened.db_path, readonly=True) as db:
        assert db.execute(
            "SELECT 1 FROM sqlite_master WHERE name='idx_audit_snapshot'"
        ).fetchone()
        assert db.execute(
            "SELECT 1 FROM context_snapshots WHERE id='__schema__'"
        ).fetchone()


def test_reopening_restores_wal_and_preserves_existing_schema_version(tmp_path):
    original = store.ContextStore(tmp_path)
    # A legacy marker must retain the original INSERT OR IGNORE behavior.
    with store._db_connect(original.db_path) as db:
        db.execute(
            "UPDATE context_snapshots SET schema_version='legacy' WHERE id='__schema__'"
        )
    # An ordinary external connection checkpoints on close, allowing this
    # explicit legacy-journal setup without altering production policy.
    db = sqlite3.connect(original.db_path)
    try:
        assert db.execute("PRAGMA journal_mode=DELETE").fetchone()[0] == "delete"
    finally:
        db.close()
    reopened = store.ContextStore(tmp_path)
    with store._db_connect(reopened.db_path, readonly=True) as db:
        assert db.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
        assert (
            db.execute(
                "SELECT schema_version FROM context_snapshots WHERE id='__schema__'"
            ).fetchone()[0]
            == "legacy"
        )


@pytest.mark.parametrize(
    "migration",
    [
        "ALTER TABLE context_audit ADD COLUMN future_value TEXT",
        "DELETE FROM context_audit",
    ],
)
def test_readiness_never_skips_future_non_create_migrations(tmp_path, migration):
    original = store.ContextStore(tmp_path)
    assert not store._schema_already_initialized(
        original.db_path,
        "BEGIN IMMEDIATE; CREATE TABLE IF NOT EXISTS context_audit "
        "(id INTEGER PRIMARY KEY); " + migration + ";",
    )


def test_reopen_preserves_original_refusal_of_malformed_schema_marker(tmp_path):
    original = store.ContextStore(tmp_path)
    with store._db_connect(original.db_path) as db:
        db.execute("ALTER TABLE context_snapshots DROP COLUMN confidence")
    # CREATE IF NOT EXISTS would not validate columns, but the original marker
    # INSERT did. The read-only reopening shortcut must preserve that refusal.
    with pytest.raises(ContextStoreError, match="confidence"):
        store.ContextStore(tmp_path)


@pytest.mark.parametrize("failure", ["commit", "rollback"])
def test_transaction_failure_still_releases_original_handle(
    tmp_path, monkeypatch, failure
):
    original = store.ContextStore(tmp_path)
    original_connect = sqlite3.connect
    opened = []

    class Connection(sqlite3.Connection):
        closed = False

        def commit(self):
            if failure == "commit":
                raise sqlite3.OperationalError("injected commit failure")
            return super().commit()

        def rollback(self):
            if failure == "rollback":
                raise sqlite3.OperationalError("injected rollback failure")
            return super().rollback()

        def close(self):
            self.closed = True
            return super().close()

    def connect(*args, **kwargs):
        db = original_connect(*args, factory=Connection, **kwargs)
        opened.append(db)
        return db

    with monkeypatch.context() as fault:
        fault.setattr(store.sqlite3, "connect", connect)
        if failure == "commit":
            assert not original.record_audit("snapshot", "operator", "failed")
        else:
            with pytest.raises(sqlite3.OperationalError, match="rollback failure"):
                with store._db_connect(original.db_path) as db:
                    db.execute(
                        "INSERT INTO context_audit (snapshot_id) VALUES ('rolled-back')"
                    )
                    raise ValueError("original operation failed")
    assert len(opened) == 1
    assert opened[0].closed
    assert store.ContextStore(tmp_path).get_audit_log() == []


def test_older_python_keeps_wal_policy_and_releases_handle(tmp_path, monkeypatch):
    monkeypatch.delattr(
        store.sqlite3, "SQLITE_DBCONFIG_NO_CKPT_ON_CLOSE", raising=False
    )
    original = store.ContextStore(tmp_path)
    assert original.record_audit("snapshot", "operator", "retained")
    with store._db_connect(original.db_path) as db:
        assert db.execute("PRAGMA synchronous").fetchone()[0] == 2
        assert db.execute("PRAGMA wal_autocheckpoint").fetchone()[0] == 1000
    with pytest.raises(sqlite3.ProgrammingError):
        db.execute("SELECT 1")
    assert [row["purpose"] for row in store.ContextStore(tmp_path).get_audit_log()] == [
        "retained"
    ]


@pytest.mark.parametrize("commit", [False, True])
def test_abrupt_process_exit_recovers_only_original_durable_audits(tmp_path, commit):
    original = store.ContextStore(tmp_path)
    assert original.record_audit("snapshot", "operator", "original")
    script = """
import os, sys
from nous_runtime.context.store import _db_connect
with _db_connect(sys.argv[1]) as db:
    db.execute("INSERT INTO context_audit (snapshot_id, actor, purpose) "
               "VALUES ('snapshot', 'operator', 'next')")
    if sys.argv[2] == "committed":
        db.commit()
    os._exit(23)
"""
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            script,
            original.db_path,
            "committed" if commit else "open",
        ],
        cwd=Path(__file__).resolve().parents[2],
        capture_output=True,
        timeout=10,
        check=False,
    )
    assert result.returncode == 23, result.stderr.decode(errors="replace")
    # get_audit_log orders by timestamp; the injected next row deliberately
    # uses the legacy empty default, below the original timestamped audit.
    assert [row["purpose"] for row in store.ContextStore(tmp_path).get_audit_log()] == (
        ["original", "next"] if commit else ["original"]
    )
    with store._db_connect(original.db_path, readonly=True) as db:
        assert db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"


def test_readonly_lookup_does_not_create_parent_or_allow_writes(tmp_path):
    missing = tmp_path / "missing" / "context.db"
    with pytest.raises(sqlite3.OperationalError):
        with store._db_connect(str(missing), readonly=True):
            pytest.fail("missing database admitted a read")
    assert not missing.parent.exists()
    original = store.ContextStore(tmp_path)
    with store._db_connect(original.db_path, readonly=True) as db:
        with pytest.raises(sqlite3.OperationalError, match="readonly"):
            db.execute("DELETE FROM context_audit")


def test_durable_audit_commit_and_rollback_keep_sqlite_policy(tmp_path):
    original = store.ContextStore(tmp_path)
    assert original.record_audit("snapshot", "operator", "original")
    with pytest.raises(ValueError, match="rollback original"):
        with store._db_connect(original.db_path) as db:
            assert db.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
            assert db.execute("PRAGMA synchronous").fetchone()[0] == 2
            assert db.execute("PRAGMA wal_autocheckpoint").fetchone()[0] == 1000
            assert db.execute("PRAGMA busy_timeout").fetchone()[0] == 5000
            assert db.execute("PRAGMA foreign_keys").fetchone()[0] == 1
            db.execute("INSERT INTO context_audit (snapshot_id) VALUES ('rolled-back')")
            raise ValueError("rollback original")
    with pytest.raises(sqlite3.ProgrammingError):
        db.execute("SELECT 1")
    assert [row["purpose"] for row in store.ContextStore(tmp_path).get_audit_log()] == [
        "original"
    ]


@pytest.mark.skipif(
    not hasattr(sqlite3.Connection, "setconfig")
    or not hasattr(sqlite3, "SQLITE_DBCONFIG_NO_CKPT_ON_CLOSE"),
    reason="SQLite connection configuration requires supported CPython/SQLite",
)
def test_supported_connection_retains_committed_wal_without_last_close_checkpoint(
    tmp_path,
):
    original = store.ContextStore(tmp_path)
    assert original.record_audit("snapshot", "operator", "durable")
    assert Path(original.db_path + "-wal").is_file()
    assert [row["purpose"] for row in store.ContextStore(tmp_path).get_audit_log()] == [
        "durable"
    ]
