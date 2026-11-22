"""Long conversation excerpts preserve history without rereading all payloads."""

import sqlite3

import pytest

from nous_runtime.conversation.models import ConversationMessage
from nous_runtime.conversation.store import ConversationStore


@pytest.mark.parametrize(
    "contents",
    [
        ["hello", "world"],
        [],
        [" ", "\n", "\t"],
        ["a" * 7990, "next"],
        ["中🙂" * 9000, "last message"],
        ["left\0right" * 2000, "tail\0more"],
        ["a\nb\n", "中文\nmore\n", "\n"],
    ],
)
def test_archived_excerpt_is_byte_compatible_and_survives_restart(tmp_path, contents):
    store = ConversationStore(tmp_path, active_window=1)
    conversation = store.create("workspace", "user")
    other = store.create("other-workspace", "other-user")
    store.append(ConversationMessage(other.conversation_id, "user", "PRIVATE_OTHER"))
    for content in [*contents, "active message"]:
        store.append(ConversationMessage(conversation.conversation_id, "user", content))
    expected = "\n".join(f"user: {content}" for content in contents)[-8000:]
    restored = ConversationStore(tmp_path, active_window=1)
    assert restored.get(conversation.conversation_id).summary == expected
    assert (
        "PRIVATE_OTHER"
        not in restored.context_window(conversation.conversation_id)["summary"]
    )
    assert restored.get(conversation.conversation_id).archived_count == len(contents)


def test_large_archive_reads_only_the_needed_message_payloads(tmp_path):
    store = ConversationStore(tmp_path, active_window=1)
    conversation = store.create("workspace", "user")
    with store._db() as connection:
        connection.executemany(
            "INSERT INTO messages (message_id, conversation_id, role, content, created_at) "
            "VALUES (?, ?, 'user', ?, '')",
            (
                (
                    f"message-{index}",
                    conversation.conversation_id,
                    f"{index:04d}:" + "🙂" * 500,
                )
                for index in range(5000)
            ),
        )
        fetched_rows = []

        def record_payload_read(cursor, row):
            fetched_rows.append(1)
            return sqlite3.Row(cursor, row)

        connection.row_factory = record_payload_read
        actual = store._summarize_locked(connection, conversation.conversation_id, 4999)
    expected = "\n".join(f"user: {index:04d}:" + "🙂" * 500 for index in range(4999))[
        -8000:
    ]
    assert actual == expected
    # Count real SQLite row materializations, not elapsed time on a busy runner.
    assert len(fetched_rows) <= 32


def test_optional_archive_cannot_displace_recent_input_or_overrun_budget(tmp_path):
    store = ConversationStore(tmp_path, active_window=1, context_budget_chars=12)
    conversation = store.create("workspace", "user")
    store.append(
        ConversationMessage(
            conversation.conversation_id, "user", "historical context " * 20
        )
    )
    store.append(ConversationMessage(conversation.conversation_id, "user", "latest"))
    persisted = store.get(conversation.conversation_id).summary
    window = store.context_window(conversation.conversation_id)
    assert window["used_chars"] <= window["budget_chars"]
    assert window["messages"][-1]["content"] == "latest"
    assert window["summary"] == persisted[-6:]
    assert window["selection"]["summary_characters_total"] == len(persisted)
    assert window["selection"]["summary_kind"] == "historical_excerpt"
    assert window["selection"]["budget_exceeded"] is False
    assert (
        ConversationStore(tmp_path).get(conversation.conversation_id).summary
        == persisted
    )
    assert len(store.history(conversation.conversation_id)) == 2


def test_oversized_latest_intent_is_whole_and_explicitly_flagged(tmp_path):
    store = ConversationStore(tmp_path, context_budget_chars=12)
    conversation = store.create("workspace", "user")
    original = "Do not change the public interface. " * 10
    store.append(ConversationMessage(conversation.conversation_id, "user", original))
    window = store.context_window(conversation.conversation_id)
    assert window["messages"][-1]["content"] == original
    assert window["summary"] == ""
    assert window["used_chars"] == len(original)
    assert window["selection"]["budget_exceeded"] is True
    assert window["selection"]["latest_message_preserved"] is True


@pytest.mark.parametrize("suffix", ["", "-wal", "-shm", "-journal"])
def test_conversation_rejects_linked_state_before_sqlite_open(
    tmp_path, monkeypatch, suffix
):
    import os

    state = tmp_path / ".nous"
    state.mkdir()
    victim = tmp_path / "outside-state"
    victim.write_bytes(b"outside state must remain untouched")
    os.link(victim, state / ("conversations.db" + suffix))
    monkeypatch.setattr(
        sqlite3, "connect", lambda *_a, **_k: pytest.fail("linked state reached SQLite")
    )
    with pytest.raises(PermissionError, match="unlinked"):
        ConversationStore(tmp_path)
    assert victim.read_bytes() == b"outside state must remain untouched"


def test_context_selection_reads_one_wal_snapshot_during_append(tmp_path, monkeypatch):
    store = ConversationStore(tmp_path, active_window=1)
    conversation = store.create("workspace", "user")
    store.append(
        ConversationMessage(conversation.conversation_id, "user", "old archive")
    )
    store.append(
        ConversationMessage(conversation.conversation_id, "user", "current message")
    )
    writer = ConversationStore(tmp_path, active_window=1)
    original_connect = store._connect
    appended = False

    def connect_with_concurrent_append():
        connection = original_connect()

        def trace(statement):
            nonlocal appended
            if not appended and statement.startswith("SELECT * FROM messages"):
                appended = True
                writer.append(
                    ConversationMessage(
                        conversation.conversation_id, "user", "later message"
                    )
                )

        connection.set_trace_callback(trace)
        return connection

    monkeypatch.setattr(store, "_connect", connect_with_concurrent_append)
    window = store.context_window(conversation.conversation_id)
    assert appended
    assert window["messages"][-1]["content"] == "current message"
    assert "old archive" in window["summary"]
    assert "current message" not in window["summary"]
    assert writer.history(conversation.conversation_id)[0].content == "old archive"
    assert (
        writer.context_window(conversation.conversation_id)["messages"][-1]["content"]
        == "later message"
    )
