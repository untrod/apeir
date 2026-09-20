"""Conversation Runtime contracts."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


@dataclass(frozen=True)
class Citation:
    source_id: str
    snippet: str = ""
    uri: str = ""

    def to_dict(self) -> dict[str, str]:
        return {"source_id": self.source_id, "snippet": self.snippet, "uri": self.uri}


@dataclass(frozen=True)
class ConversationMessage:
    conversation_id: str
    role: str
    content: str
    message_id: str = field(default_factory=lambda: new_id("msg"))
    created_at: str = field(default_factory=utc_now)
    event_id: str = ""
    run_id: str = ""
    task_id: str = ""
    attachment_ids: tuple[str, ...] = ()
    citations: tuple[Citation, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.role not in {"system", "user", "assistant", "tool"}:
            raise ValueError(f"invalid conversation role: {self.role}")
        if not self.conversation_id:
            raise ValueError("conversation_id is required")
        if not self.content:
            raise ValueError("message content is required")

    def to_dict(self) -> dict[str, Any]:
        return {
            "message_id": self.message_id,
            "conversation_id": self.conversation_id,
            "role": self.role,
            "content": self.content,
            "created_at": self.created_at,
            "event_id": self.event_id,
            "run_id": self.run_id,
            "task_id": self.task_id,
            "attachment_ids": list(self.attachment_ids),
            "citations": [item.to_dict() for item in self.citations],
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class Conversation:
    workspace_id: str
    owner_id: str
    conversation_id: str = field(default_factory=lambda: new_id("conv"))
    title: str = ""
    created_at: str = field(default_factory=utc_now)
    updated_at: str = field(default_factory=utc_now)
    summary: str = ""
    archived_count: int = 0
    deleted_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return dict(self.__dict__)