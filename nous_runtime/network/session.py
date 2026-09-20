# -*- coding: utf-8 -*-
"""Agent Session — agent-to-agent communication session management."""

from __future__ import annotations

import logging
import uuid as _uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

_log = logging.getLogger("nous.network.session")


class MessageType(str, Enum):
    REQUEST = "task.request"
    RESPONSE = "task.response"
    EVENT = "event"
    STREAM = "stream"
    HEARTBEAT = "heartbeat"


@dataclass
class AgentMessage:
    """A message between two agents on the network."""
    id: str = ""
    msg_type: str = MessageType.REQUEST.value
    source_agent: str = ""
    target_agent: str = ""
    payload: dict[str, Any] = field(default_factory=dict)
    correlation_id: str = ""
    created_at: str = ""
    ttl_ms: int = 30000

    def __post_init__(self):
        if not self.id:
            self.id = f"amsg_{_uuid.uuid4().hex[:12]}"
        if not self.created_at:
            self.created_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id, "msg_type": self.msg_type,
            "source_agent": self.source_agent, "target_agent": self.target_agent,
            "payload": self.payload, "correlation_id": self.correlation_id,
            "created_at": self.created_at, "ttl_ms": self.ttl_ms,
        }

    @classmethod
    def request(cls, source: str, target: str, payload: dict) -> "AgentMessage":
        return cls(msg_type=MessageType.REQUEST.value, source_agent=source, target_agent=target, payload=payload)

    @classmethod
    def response(cls, request: "AgentMessage", payload: dict) -> "AgentMessage":
        return cls(msg_type=MessageType.RESPONSE.value,
                   source_agent=request.target_agent, target_agent=request.source_agent,
                   payload=payload, correlation_id=request.id)

    @classmethod
    def event(cls, source: str, event_type: str, data: dict) -> "AgentMessage":
        return cls(msg_type=MessageType.EVENT.value, source_agent=source,
                   payload={"event_type": event_type, "data": data})


@dataclass
class AgentSession:
    """A communication session between two agents."""
    session_id: str = ""
    agent_a: str = ""
    agent_b: str = ""
    created_at: str = ""
    last_active: str = ""
    message_count: int = 0
    status: str = "active"

    def __post_init__(self):
        if not self.session_id:
            self.session_id = f"asess_{_uuid.uuid4().hex[:12]}"
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        if not self.created_at:
            self.created_at = now
        if not self.last_active:
            self.last_active = now
