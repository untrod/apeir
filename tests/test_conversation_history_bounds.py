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
