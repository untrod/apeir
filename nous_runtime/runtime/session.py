"""Compatibility adapter from Runtime sessions to Conversation Runtime."""

from __future__ import annotations

import json
from pathlib import Path

from nous_runtime.conversation import ConversationMessage, ConversationStore


class RuntimeSessionStore:
    """Preserve the Phase 8 session API while ConversationStore owns state."""

    _CONVERSATION_PREFIX = "runtime:"

    def __init__(self, root: str = ""):
        self.root = Path(root or ".").resolve()
        self.store = ConversationStore(self.root)
        self._migrate_legacy()

    def list(self) -> list[dict]:
        sessions: list[dict] = []
        for conversation in self.store.list(workspace_id="runtime", owner_id="local", limit=500):
            events = [dict(message.metadata.get("runtime_event") or {}) for message in self.store.history(conversation.conversation_id, limit=1000)]
            session_id = conversation.conversation_id
            if session_id.startswith(self._CONVERSATION_PREFIX):
                session_id = session_id[len(self._CONVERSATION_PREFIX):]
            sessions.append({"session_id": session_id, "events": events})
        return sessions

    def append_event(self, session_id: str, event: dict) -> None:
        conversation_id = self._runtime_conversation_id(session_id)
        if self.store.get(conversation_id, workspace_id="runtime", owner_id="local") is None:
            self.store.create("runtime", "local", title="Runtime session", conversation_id=conversation_id)
        event_id = str(event.get("event_id") or event.get("trace_id") or event.get("request", {}).get("request_id") or "")
        self.store.append(
            ConversationMessage(
                conversation_id=conversation_id,
                role="tool",
                content=json.dumps(event, ensure_ascii=False, sort_keys=True),
                event_id=event_id,
                run_id=str(event.get("run_id") or ""),
                task_id=str(event.get("task_id") or ""),
                metadata={"runtime_event": dict(event)},
            )
        )

    def explain(self, session_id: str) -> dict:
        conversation_id = self._runtime_conversation_id(session_id)
        conversation = self.store.get(conversation_id, workspace_id="runtime", owner_id="local")
        if conversation is None:
            # Preserve access to Runtime sessions created before namespacing.
            conversation_id = session_id
            conversation = self.store.get(conversation_id, workspace_id="runtime", owner_id="local")
        if conversation is None:
            return {"session_id": session_id, "event_count": 0, "last_event": {}}
        messages = self.store.history(conversation_id, limit=1, newest_first=True)
        last_event = dict(messages[0].metadata.get("runtime_event") or {}) if messages else {}
        total = conversation.archived_count + min(len(self.store.history(conversation_id, limit=self.store.active_window)), self.store.active_window)
        return {"session_id": session_id, "event_count": total, "last_event": last_event}

    @classmethod
    def _runtime_conversation_id(cls, session_id: str) -> str:
        return f"{cls._CONVERSATION_PREFIX}{session_id}"

    def _migrate_legacy(self) -> None:
        path = self.root / ".nous" / "runtime_sessions.json"
        marker = self.root / ".nous" / ".runtime_sessions_migrated"
        if not path.is_file() or marker.exists():
            return
        try:
            data = json.loads(path.read_text(encoding="utf-8") or "{}")
            for session in data.get("sessions") or []:
                session_id = str(session.get("session_id") or "")
                if not session_id:
                    continue
                for event in session.get("events") or []:
                    self.append_event(session_id, dict(event))
            marker.write_text("migrated\n", encoding="utf-8")
        except (OSError, ValueError, TypeError):
            return
