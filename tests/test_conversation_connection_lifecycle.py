"""Conversation connections retain WAL durability and explicit ownership."""

import sqlite3
from types import SimpleNamespace

import pytest

from nous_runtime.conversation import ConversationMessage, ConversationStore
from nous_runtime.conversation import store as store_module


@pytest.mark.parametrize(
    "phase", ["journal_mode", "foreign_keys", "busy_timeout", "checkpoint"]
)
def test_conversation_configuration_failure_closes_original_handle(
    tmp_path, monkeypatch, phase
):
    store = ConversationStore(tmp_path)
    original_connect = sqlite3.connect
    opened = []

    class Connection(sqlite3.Connection):
        closed = False

        def execute(self, sql, *args, **kwargs):
            if phase in sql:
                raise sqlite3.OperationalError("controlled configuration refusal")
            return super().execute(sql, *args, **kwargs)

        def setconfig(self, *_args):
            if phase == "checkpoint":
                raise sqlite3.OperationalError("controlled configuration refusal")

        def close(self):
            self.closed = True
            return super().close()

    def connect(*args, **kwargs):
        connection = original_connect(*args, factory=Connection, **kwargs)
        opened.append(connection)
        return connection

    monkeypatch.setattr(store_module.sqlite3, "connect", connect)
    monkeypatch.setattr(
        store_module.sqlite3, "SQLITE_DBCONFIG_NO_CKPT_ON_CLOSE", 1006, raising=False
    )
    try:
        with pytest.raises(sqlite3.OperationalError, match="configuration refusal"):
            store._connect()
        assert len(opened) == 1 and opened[0].closed
    finally:
        for connection in opened:
            connection.close()


@pytest.mark.parametrize("supported", [False, True])
def test_conversation_connection_policy_preserves_wal_and_original_deadline(
    tmp_path, monkeypatch, supported
):
    store = ConversationStore(tmp_path)
    original_connect = sqlite3.connect
    configured = []

    class Connection(sqlite3.Connection):
        def setconfig(self, *args):
            configured.append(args)
            setter = getattr(super(), "setconfig", None)
            if setter is not None:
                setter(*args)

    def connect(*args, **kwargs):
        assert kwargs["timeout"] == 30
        return original_connect(*args, factory=Connection, **kwargs)

    monkeypatch.setattr(store_module.sqlite3, "connect", connect)
    if supported:
        monkeypatch.setattr(
            store_module.sqlite3,
            "SQLITE_DBCONFIG_NO_CKPT_ON_CLOSE",
            1006,
            raising=False,
        )
    else:
        monkeypatch.delattr(
            store_module.sqlite3, "SQLITE_DBCONFIG_NO_CKPT_ON_CLOSE", raising=False
        )
    with store._db() as connection:
        assert connection.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
        assert connection.execute("PRAGMA synchronous").fetchone()[0] == 2
        assert connection.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        assert connection.execute("PRAGMA busy_timeout").fetchone()[0] == 30000
        assert connection.execute("PRAGMA wal_autocheckpoint").fetchone()[0] == 1000
    assert configured == ([(1006, True)] if supported else [])


@pytest.mark.parametrize("failure", ["body", "commit"])
def test_conversation_failed_transaction_rolls_back_and_closes(
    tmp_path, monkeypatch, failure
):
    store = ConversationStore(tmp_path)
    with store._db() as connection:
        connection.execute("CREATE TABLE lifecycle_probe (value TEXT)")
    original_connect = sqlite3.connect
    events = []

    class Connection(sqlite3.Connection):
        def commit(self):
            events.append("commit")
            if failure == "commit":
                raise sqlite3.OperationalError("controlled transaction refusal")
            return super().commit()

        def rollback(self):
            events.append("rollback")
            return super().rollback()

        def close(self):
            events.append("close")
            return super().close()

    monkeypatch.setattr(
        store_module.sqlite3,
        "connect",
        lambda *a, **kw: original_connect(*a, factory=Connection, **kw),
    )
    with pytest.raises(sqlite3.OperationalError, match="transaction refusal"):
        with store._db() as connection:
            connection.execute("INSERT INTO lifecycle_probe VALUES ('pending')")
            if failure == "body":
                raise sqlite3.OperationalError("controlled transaction refusal")
    assert events[-2:] == ["rollback", "close"]
    connection = original_connect(store.path)
    try:
        assert connection.execute("SELECT * FROM lifecycle_probe").fetchall() == []
    finally:
        connection.close()


def test_conversation_slow_phase_diagnostic_contains_no_message_or_path(
    monkeypatch, caplog
):
    ticks = iter([10.0, 11.2])
    monkeypatch.setattr(
        store_module, "time", SimpleNamespace(monotonic=lambda: next(ticks))
    )
    with caplog.at_level("WARNING", logger=store_module.__name__):
        with store_module._sqlite_phase("close"):
            pass
    assert "phase=close" in caplog.text and "elapsed_ms=" in caplog.text
    assert "SELECT" not in caplog.text and ".nous" not in caplog.text


def test_conversation_committed_history_recovers_after_connection_release(tmp_path):
    store = ConversationStore(tmp_path)
    conversation = store.create("workspace", "owner", title="Original")
    message = ConversationMessage(
        conversation.conversation_id, "user", "Original message", event_id="original"
    )
    store.append(message)
    restored = ConversationStore(tmp_path)
    restored.append(message)
    assert [
        item.message_id for item in restored.history(conversation.conversation_id)
    ] == [message.message_id]


def test_existing_backup_retains_committed_conversation_wal_only(tmp_path, monkeypatch):
    from nous_runtime.backup.manager import BackupManager

    monkeypatch.setattr(
        "nous_runtime.context.snapshot.create_snapshot", lambda **_: None
    )
    store = ConversationStore(tmp_path)
    conversation = store.create("workspace", "owner")
    store.append(ConversationMessage(conversation.conversation_id, "user", "first"))
    reader = sqlite3.connect(store.path)
    writer = sqlite3.connect(store.path)
    try:
        reader.execute("SELECT content FROM messages").fetchall()
        store.append(
            ConversationMessage(conversation.conversation_id, "user", "second")
        )
        writer.execute("BEGIN IMMEDIATE")
        writer.execute(
            "INSERT INTO messages (message_id, conversation_id, role, content, created_at) "
            "VALUES ('pending', ?, 'user', 'pending', '2026-11-09')",
            (conversation.conversation_id,),
        )
        assert store.path.with_name(store.path.name + "-wal").is_file()
        manager = BackupManager(str(store.path.parent))
        report = manager.create_backup("conversation")
        assert report["errors"] == [] and writer.in_transaction
        snapshot = sqlite3.connect(
            manager._backup_dir / report["backup_name"] / store.path.name
        )
        try:
            assert snapshot.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
            assert snapshot.execute(
                "SELECT content FROM messages ORDER BY sequence"
            ).fetchall() == [("first",), ("second",)]
        finally:
            snapshot.close()
    finally:
        writer.rollback()
        writer.close()
        reader.close()
