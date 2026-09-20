# -*- coding: utf-8 -*-
"""
Session and Conversation models for Nous Runtime.

Implements §7 (Continuous Session & Context System) and §8 (Unified Chat-to-Execution Loop)
of the master plan.

Sessions are long-lived user interaction contexts. Conversations contain messages
and tasks. The Context Builder assembles the appropriate context for each model call.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from nous_runtime.kernel.object_model import (
    NousObject,
)
from nous_runtime.compat.ids import make_id


# Session mode (internal, not exposed to user)

class InteractionMode(str, Enum):
    """Internal interaction mode (§8, §3.4).

    Users never see these modes — the Runtime automatically determines
    the appropriate mode based on user intent and task state.
    """
    DISCUSS = "discuss"              # Analysis, explanation only — no execution
    PROPOSE = "propose"              # Generate structured plan artifact
    AWAITING_APPROVAL = "awaiting_approval"  # Waiting for user to approve a plan
    EXECUTE = "execute"              # Executing approved plan on target node
    VERIFY = "verify"                # Verifying task completion


# Message

@dataclass
class Message:
    """A single message in a conversation."""

    message_id: str = field(default_factory=lambda: make_id(prefix="msg"))
    role: str = "user"               # user, assistant, system, tool
    content: str = ""
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    tool_results: list[dict[str, Any]] = field(default_factory=list)
    artifacts: list[str] = field(default_factory=list)  # Referenced artifact IDs
    task_id: str | None = None       # Associated task, if any
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    edited_at: str | None = None     # If message was edited
    retry_of: str | None = None      # message_id this is a retry of

    def to_dict(self) -> dict[str, Any]:
        return {
            "message_id": self.message_id,
            "role": self.role,
            "content": self.content,
            "tool_calls": self.tool_calls,
            "artifacts": self.artifacts,
            "task_id": self.task_id,
            "created_at": self.created_at,
            "edited_at": self.edited_at,
        }


# Conversation

@dataclass
class Conversation(NousObject):
    """A long-lived conversation between a user and the Runtime.

    Conversations survive across devices, restarts, and network changes.
    Each conversation can spawn multiple tasks.
    """

    kind: str = field(default="Conversation", init=False)

    user_id: str = ""
    title: str = "New Conversation"
    mode: InteractionMode = InteractionMode.DISCUSS

    # Messages
    messages: list[Message] = field(default_factory=list)
    message_count: int = 0

    # Associated tasks
    task_ids: list[str] = field(default_factory=list)

    # Context management (§7.2-7.3)
    summary: str = ""                 # Current conversation summary
    summary_generated_at: str = ""    # When last summary was generated
    token_estimate: int = 0           # Approximate token count

    # Device tracking
    active_device_id: str = ""        # Current device the user is on
    synced_devices: list[str] = field(default_factory=list)

    # Lifecycle
    last_active_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    expires_at: str = ""              # TTL-based expiry

    def add_message(self, message: Message) -> None:
        """Append a message to the conversation."""
        self.messages.append(message)
        self.message_count = len(self.messages)
        self.last_active_at = datetime.now(timezone.utc).isoformat()

    def add_task(self, task_id: str) -> None:
        """Associate a task with this conversation."""
        if task_id not in self.task_ids:
            self.task_ids.append(task_id)

    def recent_messages(self, n: int = 20) -> list[Message]:
        """Return the n most recent messages."""
        return self.messages[-n:]

    def to_dict(self) -> dict[str, Any]:
        base = super().to_dict()
        base["conversation"] = {
            "user_id": self.user_id,
            "title": self.title,
            "mode": self.mode.value,
            "message_count": self.message_count,
            "task_count": len(self.task_ids),
            "task_ids": self.task_ids,
            "summary": self.summary,
            "token_estimate": self.token_estimate,
            "last_active_at": self.last_active_at,
            "active_device_id": self.active_device_id,
        }
        return base


# Session

@dataclass
class Session(NousObject):
    """A user session that may span multiple conversations.

    Sessions track device binding, authentication state, and TTL.
    """

    kind: str = field(default="Session", init=False)

    user_id: str = ""
    device_id: str = ""
    node_id: str = ""                  # Primary node serving this session

    # Active conversations
    conversation_ids: list[str] = field(default_factory=list)
    active_conversation_id: str = ""

    # Authentication
    auth_token_hash: str = ""          # Hash of current auth token
    auth_expires_at: str = ""

    # TTL
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    last_active_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    ttl_seconds: int = 604800           # Default 7 days

    @property
    def is_expired(self) -> bool:
        if not self.last_active_at:
            return False
        last = datetime.fromisoformat(self.last_active_at.replace("Z", "+00:00"))
        elapsed = (datetime.now(timezone.utc) - last).total_seconds()
        return elapsed > self.ttl_seconds

    def touch(self) -> None:
        """Update last active timestamp."""
        self.last_active_at = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict[str, Any]:
        base = super().to_dict()
        base["session"] = {
            "user_id": self.user_id,
            "device_id": self.device_id,
            "conversation_count": len(self.conversation_ids),
            "active_conversation_id": self.active_conversation_id,
            "last_active_at": self.last_active_at,
            "is_expired": self.is_expired,
        }
        return base
