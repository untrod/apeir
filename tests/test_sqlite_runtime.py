from __future__ import annotations

import sqlite3
from contextlib import contextmanager

import pytest

from nous_runtime.sqlite_runtime import SQLiteRuntime


def test_sqlite_runtime_wal_foreign_keys_batch_plan_and_metrics(tmp_path):
    runtime = SQLiteRuntime(tmp_path / "runtime.db")
    with runtime.connect() as connection:
        assert connection.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
        assert connection.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        connection.execute(
            "CREATE TABLE items (id INTEGER PRIMARY KEY, value TEXT NOT NULL)"
        )

    assert runtime.batch(
        "INSERT INTO items(id, value) VALUES (?, ?)",
        [(1, "one"), (2, "two")],
    ) == 2
    plan = runtime.explain_query_plan(
        "SELECT value FROM items WHERE id = ?", (1,)
    )
    checkpoint = runtime.checkpoint()
    runtime.record_backup()
    metrics = runtime.metrics()

    assert plan
    assert checkpoint["duration_ms"] >= 0
    assert metrics["database_size"] > 0
    assert metrics["integrity_status"] == "ok"
    assert metrics["transaction_p95_ms"] >= 0
    assert metrics["last_backup_age_seconds"] is not None
    with pytest.raises(ValueError, match="read queries"):
        runtime.explain_query_plan("DELETE FROM items")


def test_sqlite_runtime_recovers_from_temporary_lock_with_bounded_retry(
    tmp_path, monkeypatch
):
    runtime = SQLiteRuntime(tmp_path / "runtime.db", busy_timeout_ms=10)
    runtime.execute("CREATE TABLE items (id INTEGER PRIMARY KEY)")
    original_connect = runtime.connect
    injected_locks = 0

    @contextmanager
    def connect_with_one_lock(*, readonly=False):
        nonlocal injected_locks
        if not readonly and injected_locks == 0:
            injected_locks += 1
            raise sqlite3.OperationalError("database is locked")
        with original_connect(readonly=readonly) as connection:
            yield connection

    monkeypatch.setattr(runtime, "connect", connect_with_one_lock)
    runtime.execute(
        "INSERT INTO items(id) VALUES (?)",
        (1,),
        retries=10,
    )

    with runtime.connect(readonly=True) as connection:
        assert connection.execute("SELECT COUNT(*) FROM items").fetchone()[0] == 1
    assert injected_locks == 1
    assert runtime.metrics()["busy_retries"] == 1
