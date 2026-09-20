"""SQLite-backed Conversation Runtime store."""

from __future__ import annotations

from contextlib import contextmanager
from collections.abc import Iterator

import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Any

from nous_runtime.conversation.models import Citation, Conversation, ConversationMessage, utc_now


EXPORT_SCHEMA = "nous.conversation.export"
EXPORT_VERSION = "2.0"


class ConversationStore:
    def __init__(self, root: str | Path = ".", *, active_window: int = 100, context_budget_chars: int = 32_000):
        self.root = Path(root).resolve()
        self.path = self.root / ".nous" / "conversations.db"
        self.active_window = max(1, active_window)
        self.context_budget_chars = max(1, context_budget_chars)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    @contextmanager
    def _db(self):
        connection = self._connect()
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()
    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA busy_timeout=30000")
        return connection

    def _initialize(self) -> None:
        with self._db() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS conversations (
                    conversation_id TEXT PRIMARY KEY,
                    workspace_id TEXT NOT NULL,
                    owner_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    summary TEXT NOT NULL DEFAULT '',
                    archived_count INTEGER NOT NULL DEFAULT 0,
                    deleted_at TEXT NOT NULL DEFAULT ''
                );
                CREATE TABLE IF NOT EXISTS messages (
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                    message_id TEXT NOT NULL UNIQUE,
                    conversation_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    event_id TEXT,
                    run_id TEXT NOT NULL DEFAULT '',
                    task_id TEXT NOT NULL DEFAULT '',
                    attachment_ids_json TEXT NOT NULL DEFAULT '[]',
                    citations_json TEXT NOT NULL DEFAULT '[]',
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    FOREIGN KEY(conversation_id) REFERENCES conversations(conversation_id) ON DELETE CASCADE,
                    UNIQUE(conversation_id, event_id)
                );
                CREATE INDEX IF NOT EXISTS idx_messages_conversation_sequence
                    ON messages(conversation_id, sequence);
                CREATE INDEX IF NOT EXISTS idx_conversations_workspace_owner
                    ON conversations(workspace_id, owner_id, updated_at);
                """
            )

    def create(self, workspace_id: str, owner_id: str, *, title: str = "", conversation_id: str = "") -> Conversation:
        conversation = Conversation(workspace_id=workspace_id, owner_id=owner_id, title=title, **({"conversation_id": conversation_id} if conversation_id else {}))
        if not workspace_id or not owner_id:
            raise ValueError("workspace_id and owner_id are required")
        with self._db() as connection:
            connection.execute(
                "INSERT INTO conversations VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (conversation.conversation_id, workspace_id, owner_id, title, conversation.created_at, conversation.updated_at, "", 0, ""),
            )
        return conversation

    def get(self, conversation_id: str, *, workspace_id: str = "", owner_id: str = "", include_deleted: bool = False) -> Conversation | None:
        clauses = ["conversation_id = ?"]
        values: list[Any] = [conversation_id]
        if workspace_id:
            clauses.append("workspace_id = ?")
            values.append(workspace_id)
        if owner_id:
            clauses.append("owner_id = ?")
            values.append(owner_id)
        if not include_deleted:
            clauses.append("deleted_at = ''")
        with self._db() as connection:
            row = connection.execute("SELECT * FROM conversations WHERE " + " AND ".join(clauses), values).fetchone()
        return self._conversation(row) if row else None

    def list(self, *, workspace_id: str = "", owner_id: str = "", limit: int = 50, offset: int = 0) -> list[Conversation]:
        clauses = ["deleted_at = ''"]
        values: list[Any] = []
        if workspace_id:
            clauses.append("workspace_id = ?")
            values.append(workspace_id)
        if owner_id:
            clauses.append("owner_id = ?")
            values.append(owner_id)
        values.extend([max(1, min(limit, 500)), max(0, offset)])
        with self._db() as connection:
            rows = connection.execute(
                "SELECT * FROM conversations WHERE " + " AND ".join(clauses) + " ORDER BY updated_at DESC LIMIT ? OFFSET ?",
                values,
            ).fetchall()
        return [self._conversation(row) for row in rows]

    def append(self, message: ConversationMessage) -> ConversationMessage:
        with self._db() as connection:
            connection.execute("BEGIN IMMEDIATE")
            conversation = connection.execute(
                "SELECT deleted_at FROM conversations WHERE conversation_id = ?", (message.conversation_id,)
            ).fetchone()
            if conversation is None or conversation["deleted_at"]:
                raise KeyError(f"conversation is unavailable: {message.conversation_id}")
            if message.event_id:
                existing = connection.execute(
                    "SELECT * FROM messages WHERE conversation_id = ? AND event_id = ?",
                    (message.conversation_id, message.event_id),
                ).fetchone()
                if existing:
                    return self._message(existing)
            connection.execute(
                """INSERT INTO messages (
                    message_id, conversation_id, role, content, created_at, event_id,
                    run_id, task_id, attachment_ids_json, citations_json, metadata_json
                ) VALUES (?, ?, ?, ?, ?, NULLIF(?, ''), ?, ?, ?, ?, ?)""",
                (
                    message.message_id, message.conversation_id, message.role, message.content,
                    message.created_at, message.event_id, message.run_id, message.task_id,
                    json.dumps(message.attachment_ids),
                    json.dumps([item.to_dict() for item in message.citations], ensure_ascii=False),
                    json.dumps(message.metadata, ensure_ascii=False),
                ),
            )
            now = utc_now()
            connection.execute("UPDATE conversations SET updated_at = ? WHERE conversation_id = ?", (now, message.conversation_id))
            count = int(connection.execute("SELECT COUNT(*) FROM messages WHERE conversation_id = ?", (message.conversation_id,)).fetchone()[0])
            archived = max(0, count - self.active_window)
            if archived:
                summary = self._summarize_locked(connection, message.conversation_id, archived)
                connection.execute(
                    "UPDATE conversations SET summary = ?, archived_count = ? WHERE conversation_id = ?",
                    (summary, archived, message.conversation_id),
                )
        return message

    def history(self, conversation_id: str, *, limit: int = 50, offset: int = 0, newest_first: bool = False) -> list[ConversationMessage]:
        direction = "DESC" if newest_first else "ASC"
        with self._db() as connection:
            rows = connection.execute(
                f"SELECT * FROM messages WHERE conversation_id = ? ORDER BY sequence {direction} LIMIT ? OFFSET ?",
                (conversation_id, max(1, min(limit, 1000)), max(0, offset)),
            ).fetchall()
        return [self._message(row) for row in rows]

    def search_messages(
        self,
        query: str,
        *,
        conversation_id: str = "",
        limit: int = 50,
        offset: int = 0,
    ) -> list[ConversationMessage]:
        """Search bounded conversation logs without exposing another store."""
        if not query.strip():
            return []
        clauses = ["instr(lower(content), lower(?)) > 0"]
        values: list[Any] = [query]
        if conversation_id:
            clauses.append("conversation_id = ?")
            values.append(conversation_id)
        values.extend([max(1, min(limit, 500)), max(0, offset)])
        with self._db() as connection:
            rows = connection.execute(
                "SELECT * FROM messages WHERE "
                + " AND ".join(clauses)
                + " ORDER BY sequence DESC LIMIT ? OFFSET ?",
                values,
            ).fetchall()
        return [self._message(row) for row in rows]

    def context_window(self, conversation_id: str) -> dict[str, Any]:
        conversation = self.get(conversation_id)
        if conversation is None:
            raise KeyError(conversation_id)
        messages = list(reversed(self.history(conversation_id, limit=self.active_window, newest_first=True)))
        selected: list[ConversationMessage] = []
        used = len(conversation.summary)
        for message in reversed(messages):
            if selected and used + len(message.content) > self.context_budget_chars:
                break
            selected.append(message)
            used += len(message.content)
        selected.reverse()
        return {"summary": conversation.summary, "messages": [item.to_dict() for item in selected], "used_chars": used, "budget_chars": self.context_budget_chars}

    def iter_messages(
        self,
        conversation_id: str,
        *,
        page_size: int = 500,
        last_sequence: int | None = None,
        cancel: Any = None,
    ) -> Iterator[ConversationMessage]:
        """Iterate a stable message snapshot using bounded keyset pages."""
        page_size = max(1, min(int(page_size), 1000))
        if last_sequence is None:
            _, last_sequence = self._export_bounds(conversation_id)
        cursor = 0
        while cursor < last_sequence and not self._cancelled(cancel):
            with self._db() as connection:
                rows = connection.execute(
                    """SELECT * FROM messages
                       WHERE conversation_id = ? AND sequence > ? AND sequence <= ?
                       ORDER BY sequence ASC LIMIT ?""",
                    (conversation_id, cursor, last_sequence, page_size),
                ).fetchall()
            if not rows:
                return
            for row in rows:
                if self._cancelled(cancel):
                    return
                cursor = int(row["sequence"])
                yield self._message(row)

    def iter_export(self, conversation_id: str, *, page_size: int = 500, cancel: Any = None) -> Iterator[dict[str, Any]]:
        """Yield a versioned export envelope, messages, and integrity summary."""
        conversation = self.get(conversation_id, include_deleted=True)
        if conversation is None:
            raise KeyError(conversation_id)
        expected_count, last_sequence = self._export_bounds(conversation_id)
        yield {
            "type": "metadata",
            "schema": EXPORT_SCHEMA,
            "version": EXPORT_VERSION,
            "generated_at": utc_now(),
            "conversation": conversation.to_dict(),
            "snapshot": {"message_count": expected_count, "last_sequence": last_sequence},
        }
        digest = hashlib.sha256()
        exported_count = 0
        first_message_id = ""
        last_message_id = ""
        for message in self.iter_messages(conversation_id, page_size=page_size, last_sequence=last_sequence, cancel=cancel):
            payload = message.to_dict()
            canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
            digest.update(canonical)
            digest.update(b"\n")
            exported_count += 1
            first_message_id = first_message_id or message.message_id
            last_message_id = message.message_id
            yield {"type": "message", "message": payload}
        cancelled = self._cancelled(cancel)
        yield {
            "type": "summary",
            "message_count": exported_count,
            "expected_message_count": expected_count,
            "first_message_id": first_message_id,
            "last_message_id": last_message_id,
            "content_sha256": digest.hexdigest(),
            "complete": not cancelled and exported_count == expected_count,
            "cancelled": cancelled,
        }

    def stream_export(self, conversation_id: str, *, page_size: int = 500, cancel: Any = None) -> Iterator[str]:
        """Stream a bounded-memory JSON Lines export."""
        for record in self.iter_export(conversation_id, page_size=page_size, cancel=cancel):
            yield json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"

    def export(self, conversation_id: str, *, page_size: int = 500, cancel: Any = None) -> dict[str, Any]:
        """Compatibility dictionary export without silent message truncation.

        Large callers should use ``stream_export`` to keep memory bounded.
        """
        metadata: dict[str, Any] | None = None
        summary: dict[str, Any] | None = None
        messages: list[dict[str, Any]] = []
        for record in self.iter_export(conversation_id, page_size=page_size, cancel=cancel):
            record_type = record["type"]
            if record_type == "metadata":
                metadata = record
            elif record_type == "message":
                messages.append(dict(record["message"]))
            else:
                summary = record
        if metadata is None or summary is None:
            raise RuntimeError("conversation export did not produce a complete envelope")
        return {
            "schema_version": EXPORT_VERSION,
            "export": {key: value for key, value in metadata.items() if key not in {"type", "conversation"}},
            "conversation": metadata["conversation"],
            "messages": messages,
            "integrity": {key: value for key, value in summary.items() if key != "type"},
        }

    def _export_bounds(self, conversation_id: str) -> tuple[int, int]:
        with self._db() as connection:
            row = connection.execute(
                "SELECT COUNT(*) AS message_count, COALESCE(MAX(sequence), 0) AS last_sequence FROM messages WHERE conversation_id = ?",
                (conversation_id,),
            ).fetchone()
        return int(row["message_count"]), int(row["last_sequence"])

    @staticmethod
    def _cancelled(cancel: Any) -> bool:
        if cancel is None:
            return False
        is_set = getattr(cancel, "is_set", None)
        return bool(is_set()) if callable(is_set) else bool(cancel()) if callable(cancel) else bool(cancel)

    def import_data(self, data: dict[str, Any], *, workspace_id: str, owner_id: str) -> Conversation:
        source = dict(data.get("conversation") or {})
        conversation = self.create(workspace_id, owner_id, title=str(source.get("title") or ""))
        for item in data.get("messages") or []:
            citations = tuple(Citation(**entry) for entry in item.get("citations") or [])
            self.append(ConversationMessage(conversation.conversation_id, str(item["role"]), str(item["content"]), event_id=str(item.get("event_id") or ""), run_id=str(item.get("run_id") or ""), task_id=str(item.get("task_id") or ""), attachment_ids=tuple(item.get("attachment_ids") or ()), citations=citations, metadata=dict(item.get("metadata") or {})))
        return conversation

    def delete(self, conversation_id: str, *, hard: bool = False) -> bool:
        with self._db() as connection:
            if hard:
                cursor = connection.execute("DELETE FROM conversations WHERE conversation_id = ?", (conversation_id,))
            else:
                cursor = connection.execute("UPDATE conversations SET deleted_at = ? WHERE conversation_id = ? AND deleted_at = ''", (utc_now(), conversation_id))
        return cursor.rowcount == 1

    def _summarize_locked(self, connection: sqlite3.Connection, conversation_id: str, archived: int) -> str:
        rows = connection.execute("SELECT role, content FROM messages WHERE conversation_id = ? ORDER BY sequence ASC LIMIT ?", (conversation_id, archived)).fetchall()
        text = "\n".join(f"{row['role']}: {row['content']}" for row in rows)
        return text[-8_000:]

    @staticmethod
    def _conversation(row: sqlite3.Row) -> Conversation:
        return Conversation(**dict(row))

    @staticmethod
    def _message(row: sqlite3.Row) -> ConversationMessage:
        return ConversationMessage(
            conversation_id=row["conversation_id"], role=row["role"], content=row["content"],
            message_id=row["message_id"], created_at=row["created_at"], event_id=row["event_id"] or "",
            run_id=row["run_id"], task_id=row["task_id"],
            attachment_ids=tuple(json.loads(row["attachment_ids_json"])),
            citations=tuple(Citation(**item) for item in json.loads(row["citations_json"])),
            metadata=dict(json.loads(row["metadata_json"])),
        )