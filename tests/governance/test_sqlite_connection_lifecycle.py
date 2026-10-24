"""The original Governance SQLite owner closes every admitted connection."""

import sqlite3
from types import SimpleNamespace

import pytest

from nous_runtime.governance import store


def test_schema_initialization_is_one_atomic_write_transaction(tmp_path, monkeypatch):
    original_connect = sqlite3.connect
    ddl_transactions = []
    transaction_boundaries = []

    def connect(*args, **kwargs):
        connection = original_connect(*args, **kwargs)

        def trace(sql):
            statement = sql.strip().rstrip(";").upper()
            if statement.startswith("CREATE "):
                ddl_transactions.append(connection.in_transaction)
            if statement.startswith(("BEGIN", "COMMIT", "ROLLBACK")):
                transaction_boundaries.append(statement)

        connection.set_trace_callback(trace)
        return connection

    with monkeypatch.context() as trace:
        trace.setattr(store.sqlite3, "connect", connect)
        governance = store.GovernanceStore(tmp_path)
    assert ddl_transactions and all(ddl_transactions)
    # Older CPython executescript() calls commit() even without an active
    # transaction. Trace actual SQLite boundaries rather than that no-op call.
    assert transaction_boundaries == ["BEGIN IMMEDIATE", "COMMIT"]
    with store._db_connect(governance.db_path, readonly=True) as connection:
        assert connection.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
        assert connection.execute("PRAGMA synchronous").fetchone()[0] == 2
        assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"


def test_late_schema_failure_rolls_back_all_ddl_and_preserves_existing_data(
    tmp_path, monkeypatch
):
    path = tmp_path / "governance.db"
    with store._db_connect(str(path)) as connection:
        connection.execute("CREATE TABLE retained (value TEXT)")
        connection.execute("INSERT INTO retained VALUES ('original')")
    original_connect = sqlite3.connect

    class Connection(sqlite3.Connection):
        def executescript(self, script):
            return super().executescript(script + "\nINVALID SCHEMA STATEMENT;")

    def connect(*args, **kwargs):
        return original_connect(*args, factory=Connection, **kwargs)

    raised = False
    with monkeypatch.context() as fault:
        fault.setattr(store.sqlite3, "connect", connect)
        try:
            store.GovernanceStore(tmp_path)
        except sqlite3.DatabaseError:
            raised = True
    with store._db_connect(str(path), readonly=True) as connection:
        assert not connection.execute(
            "SELECT name FROM sqlite_master WHERE name LIKE 'governance_%'"
        ).fetchall()
        assert (
            connection.execute("SELECT value FROM retained").fetchone()[0] == "original"
        )
        assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    assert raised, "failed schema initialization returned a usable GovernanceStore"


def test_schema_failure_propagates_without_logging_private_error(
    tmp_path, monkeypatch, caplog
):
    original_connect = sqlite3.connect
    marker = "FAKE_ONLY_PRIVATE_SCHEMA_ERROR"

    class Connection(sqlite3.Connection):
        def executescript(self, script):
            raise sqlite3.OperationalError(marker)

    def connect(*args, **kwargs):
        return original_connect(*args, factory=Connection, **kwargs)

    monkeypatch.setattr(store.sqlite3, "connect", connect)
    with pytest.raises(sqlite3.OperationalError):
        store.GovernanceStore(tmp_path)
    assert marker not in caplog.text
    assert str(tmp_path) not in caplog.text


def test_readonly_missing_database_does_not_initialize_directories(tmp_path):
    parent = tmp_path / "removed-workspace" / ".nous"
    with pytest.raises(sqlite3.OperationalError):
        with store._db_connect(str(parent / "governance.db"), readonly=True):
            pytest.fail("missing database admitted a read")
    assert not parent.exists()


def test_readonly_existing_database_needs_no_directory_creation(tmp_path, monkeypatch):
    path = tmp_path / "governance.db"
    with store._db_connect(str(path)) as connection:
        connection.execute("CREATE TABLE entries (value TEXT)")
        connection.execute("INSERT INTO entries VALUES ('recorded')")

    def mkdir(*_args, **_kwargs):
        pytest.fail("read-only lookup attempted directory initialization")

    with monkeypatch.context() as readonly:
        readonly.setattr(store.Path, "mkdir", mkdir)
        with store._db_connect(str(path), readonly=True) as connection:
            assert (
                connection.execute("SELECT value FROM entries").fetchone()[0]
                == "recorded"
            )


@pytest.mark.parametrize(
    "pragma",
    ["PRAGMA busy_timeout=5000", "PRAGMA journal_mode=WAL", "PRAGMA foreign_keys=ON"],
)
def test_failed_connection_setup_closes_before_propagating(
    tmp_path, monkeypatch, pragma
):
    original_connect = sqlite3.connect
    opened = []

    class Connection(sqlite3.Connection):
        closed = False

        def execute(self, sql, *args, **kwargs):
            if sql == pragma:
                raise sqlite3.OperationalError("injected setup failure")
            return super().execute(sql, *args, **kwargs)

        def close(self):
            self.closed = True
            return super().close()

    def connect(*args, **kwargs):
        connection = original_connect(*args, factory=Connection, **kwargs)
        opened.append(connection)  # retain it: GC cannot hide missing ownership
        return connection

    monkeypatch.setattr(store.sqlite3, "connect", connect)
    try:
        with pytest.raises(sqlite3.OperationalError, match="injected setup failure"):
            with store._db_connect(str(tmp_path / "governance.db")):
                pytest.fail("failed setup admitted transaction body")
        assert len(opened) == 1
        assert opened[0].closed
    finally:
        for connection in opened:
            connection.close()


@pytest.mark.parametrize("readonly", [False, True])
def test_failed_setup_closes_readonly_connection(tmp_path, monkeypatch, readonly):
    path = tmp_path / "governance.db"
    connection = sqlite3.connect(path)
    connection.close()
    original_connect = sqlite3.connect
    opened = []

    class Connection(sqlite3.Connection):
        closed = False

        def execute(self, sql, *args, **kwargs):
            raise sqlite3.OperationalError("injected setup failure")

        def close(self):
            self.closed = True
            return super().close()

    def connect(*args, **kwargs):
        connection = original_connect(*args, factory=Connection, **kwargs)
        opened.append(connection)
        return connection

    monkeypatch.setattr(store.sqlite3, "connect", connect)
    with pytest.raises(sqlite3.OperationalError):
        with store._db_connect(str(path), readonly=readonly):
            pytest.fail("failed setup admitted body")
    assert opened[0].closed


def test_failed_commit_rolls_back_and_closes_original_connection(tmp_path, monkeypatch):
    path = tmp_path / "governance.db"
    with store._db_connect(str(path)) as connection:
        connection.execute("CREATE TABLE entries (value TEXT)")
    original_connect = sqlite3.connect
    lifecycle = []

    class Connection(sqlite3.Connection):
        def commit(self):
            lifecycle.append("commit")
            raise sqlite3.OperationalError("injected commit failure")

        def rollback(self):
            lifecycle.append("rollback")
            return super().rollback()

        def close(self):
            lifecycle.append("close")
            return super().close()

    def connect(*args, **kwargs):
        return original_connect(*args, factory=Connection, **kwargs)

    with monkeypatch.context() as fault:
        fault.setattr(store.sqlite3, "connect", connect)
        with pytest.raises(sqlite3.OperationalError, match="commit failure"):
            with store._db_connect(str(path)) as connection:
                connection.execute("INSERT INTO entries VALUES ('original')")
    assert lifecycle == ["commit", "rollback", "close"]
    with store._db_connect(str(path), readonly=True) as connection:
        assert connection.execute("SELECT COUNT(*) FROM entries").fetchone()[0] == 0


def test_close_failure_preserves_committed_fact_without_replaying_body(
    tmp_path, monkeypatch
):
    path = tmp_path / "governance.db"
    original_connect = sqlite3.connect
    calls = []

    class Connection(sqlite3.Connection):
        def close(self):
            super().close()
            raise sqlite3.OperationalError("injected post-close failure")

    def connect(*args, **kwargs):
        return original_connect(*args, factory=Connection, **kwargs)

    with monkeypatch.context() as fault:
        fault.setattr(store.sqlite3, "connect", connect)
        with pytest.raises(sqlite3.OperationalError, match="post-close failure"):
            with store._db_connect(str(path)) as connection:
                calls.append("original")
                connection.execute("CREATE TABLE entries (value TEXT)")
                connection.execute("INSERT INTO entries VALUES ('original')")
    assert calls == ["original"]
    with store._db_connect(str(path), readonly=True) as connection:
        assert (
            connection.execute("SELECT value FROM entries").fetchall()[0][0]
            == "original"
        )


@pytest.mark.parametrize(
    "phase", ["connect", "configure", "commit", "rollback", "close"]
)
def test_slow_phase_diagnostics_exclude_sql_path_values_and_errors(
    tmp_path, monkeypatch, caplog, phase
):
    private = "FAKE_ONLY_PRIVATE_DB_MARKER"
    path = tmp_path / (private + ".db")
    original_connect = sqlite3.connect
    clock = [100.0]

    def delayed(name):
        if phase == name:
            clock[0] += 1.5

    class Connection(sqlite3.Connection):
        def execute(self, sql, *args, **kwargs):
            if sql == "PRAGMA busy_timeout=5000":
                delayed("configure")
            return super().execute(sql, *args, **kwargs)

        def commit(self):
            delayed("commit")
            return super().commit()

        def rollback(self):
            delayed("rollback")
            return super().rollback()

        def close(self):
            delayed("close")
            return super().close()

    def connect(*args, **kwargs):
        delayed("connect")
        return original_connect(*args, factory=Connection, **kwargs)

    monkeypatch.setattr(store, "time", SimpleNamespace(monotonic=lambda: clock[0]))
    monkeypatch.setattr(store.sqlite3, "connect", connect)
    with caplog.at_level("WARNING", logger="nous.governance.store"):
        if phase == "rollback":
            with pytest.raises(ValueError, match=private):
                with store._db_connect(str(path)):
                    raise ValueError(private)
        else:
            with store._db_connect(str(path)) as connection:
                connection.execute("CREATE TABLE entries (value TEXT)")
                connection.execute("INSERT INTO entries VALUES (?)", (private,))
    records = [r for r in caplog.records if r.name == "nous.governance.store"]
    assert [r.getMessage() for r in records] == [
        f"Slow governance SQLite phase: phase={phase} elapsed_ms=1500.000 readonly=False"
    ]
    assert private not in caplog.text
    assert str(path) not in caplog.text
    assert "INSERT" not in caplog.text
    assert "CREATE" not in caplog.text
