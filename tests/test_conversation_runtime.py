from __future__ import annotations

import json
import threading

from nous_runtime.conversation import Citation, ConversationMessage, ConversationStore, ConversationStream, StreamChunk
from nous_runtime.runtime.session import RuntimeSessionStore


def test_conversation_lifecycle_isolated_and_paginated(tmp_path):
    store = ConversationStore(tmp_path, active_window=3)
    first = store.create("workspace-a", "user-a", title="First")
    second = store.create("workspace-b", "user-b", title="Second")
    for index in range(5):
        store.append(ConversationMessage(first.conversation_id, "user", f"message-{index}", event_id=f"event-{index}"))
    store.append(ConversationMessage(second.conversation_id, "user", "private"))

    page = store.history(first.conversation_id, limit=2, offset=2)
    assert [item.content for item in page] == ["message-2", "message-3"]
    assert [item.conversation_id for item in store.history(second.conversation_id)] == [second.conversation_id]
    restored = store.get(first.conversation_id)
    assert restored is not None
    assert restored.archived_count == 2
    assert "message-1" in restored.summary


def test_conversation_event_is_idempotent_and_context_is_bounded(tmp_path):
    store = ConversationStore(tmp_path, active_window=5, context_budget_chars=12)
    conversation = store.create("workspace", "user")
    first = ConversationMessage(conversation.conversation_id, "assistant", "abcdef", event_id="stream-1")
    assert store.append(first).message_id == first.message_id
    assert store.append(ConversationMessage(conversation.conversation_id, "assistant", "duplicate", event_id="stream-1")).message_id == first.message_id
    store.append(ConversationMessage(conversation.conversation_id, "assistant", "ghijkl", event_id="stream-2"))
    store.append(ConversationMessage(conversation.conversation_id, "assistant", "mnopqr", event_id="stream-3"))
    window = store.context_window(conversation.conversation_id)
    assert window["used_chars"] <= window["budget_chars"]
    assert len(store.history(conversation.conversation_id)) == 3


def test_conversation_export_import_delete_and_citations(tmp_path):
    store = ConversationStore(tmp_path)
    conversation = store.create("workspace", "user")
    store.append(ConversationMessage(conversation.conversation_id, "assistant", "answer", citations=(Citation("doc-1", "source"),), run_id="run-1", task_id="task-1"))
    exported = store.export(conversation.conversation_id)
    imported = store.import_data(exported, workspace_id="workspace-2", owner_id="user-2")
    message = store.history(imported.conversation_id)[0]
    assert message.citations[0].source_id == "doc-1"
    assert message.run_id == "run-1"
    assert store.delete(imported.conversation_id)
    assert store.get(imported.conversation_id) is None
    assert store.delete(imported.conversation_id, hard=True)


def test_conversation_export_streams_all_messages_with_integrity(tmp_path):
    store = ConversationStore(tmp_path, active_window=2_000)
    conversation = store.create("workspace", "user")
    # The test exercises export pagination beyond the 1,000-message history
    # limit. Seed its fixture in one transaction so platform-specific fsync
    # latency does not turn this into an append performance test.
    with store._db() as connection:
        connection.executemany(
            """INSERT INTO messages (
                message_id, conversation_id, role, content, created_at, event_id,
                run_id, task_id, attachment_ids_json, citations_json, metadata_json
            ) VALUES (?, ?, ?, ?, ?, NULL, '', '', '[]', '[]', '{}')""",
            [
                (
                    f"bulk-message-{index}",
                    conversation.conversation_id,
                    "user",
                    f"message-{index}",
                    "2026-01-01T00:00:00Z",
                )
                for index in range(1_005)
            ],
        )

    exported = store.export(conversation.conversation_id, page_size=37)
    assert exported["schema_version"] == "2.0"
    assert len(exported["messages"]) == 1_005
    assert exported["messages"][-1]["content"] == "message-1004"
    assert exported["integrity"]["complete"]
    assert exported["integrity"]["message_count"] == 1_005
    assert len(exported["integrity"]["content_sha256"]) == 64

    records = [json.loads(line) for line in store.stream_export(conversation.conversation_id, page_size=29)]
    assert records[0]["type"] == "metadata"
    assert records[0]["version"] == "2.0"
    assert sum(record["type"] == "message" for record in records) == 1_005
    assert records[-1]["type"] == "summary" and records[-1]["complete"]


def test_conversation_stream_export_cancellation_is_explicit(tmp_path):
    store = ConversationStore(tmp_path, active_window=100)
    conversation = store.create("workspace", "user")
    for index in range(20):
        store.append(ConversationMessage(conversation.conversation_id, "user", f"message-{index}"))
    cancel = threading.Event()
    stream = store.iter_export(conversation.conversation_id, page_size=4, cancel=cancel)
    assert next(stream)["type"] == "metadata"
    exported = [next(stream) for _ in range(5)]
    assert all(record["type"] == "message" for record in exported)
    cancel.set()
    remainder = list(stream)
    assert remainder[-1]["type"] == "summary"
    assert remainder[-1]["cancelled"] and not remainder[-1]["complete"]
    assert remainder[-1]["message_count"] == 5


def test_stream_deduplicates_and_bounds_visible_content():
    stream = ConversationStream(max_visible_chars=6)
    assert stream.accept(StreamChunk("1", "abc"))
    assert not stream.accept(StreamChunk("1", "abc"))
    assert stream.accept(StreamChunk("2", "def"))
    assert stream.accept(StreamChunk("3", "ghi", final=True))
    assert stream.render() == "defghi"
    assert stream.complete


def test_runtime_session_adapter_recovers_and_preserves_contract(tmp_path):
    first = RuntimeSessionStore(str(tmp_path))
    first.append_event("session-1", {"trace_id": "trace-1", "response_status": "ok"})
    first.append_event("session-1", {"trace_id": "trace-1", "response_status": "duplicate"})
    second = RuntimeSessionStore(str(tmp_path))
    sessions = second.list()
    assert sessions == [{"session_id": "session-1", "events": [{"trace_id": "trace-1", "response_status": "ok"}]}]
    assert second.explain("session-1")["event_count"] == 1


def test_runtime_session_does_not_collide_with_chat_conversation(tmp_path):
    conversations = ConversationStore(str(tmp_path))
    conversations.create(
        "workspace",
        "user",
        title="Chat",
        conversation_id="shared-session",
    )

    runtime = RuntimeSessionStore(str(tmp_path))
    runtime.append_event(
        "shared-session",
        {"trace_id": "trace-chat", "response_status": "ok"},
    )

    assert conversations.get(
        "shared-session",
        workspace_id="workspace",
        owner_id="user",
    ) is not None
    assert runtime.explain("shared-session")["event_count"] == 1
