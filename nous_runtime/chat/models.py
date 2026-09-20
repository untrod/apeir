"""Chat Runtime routing contracts."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class ChatIntent(str, Enum):
    CONVERSATION = "conversation"
    KNOWLEDGE_QUERY = "knowledge_query"
    CODE_TASK = "code_task"
    WORKFLOW_REQUEST = "workflow_request"
    DEVICE_ACTION = "device_action"
    APPROVAL_RESPONSE = "approval_response"
    STATUS_QUERY = "status_query"


@dataclass(frozen=True)
class ChatRequest:
    text: str
    workspace_id: str
    owner_id: str
    conversation_id: str = ""
    attachment_ids: tuple[str, ...] = ()
    model_id: str = ""
    agent_mode: str = "agent"
    request_id: str = ""


@dataclass(frozen=True)
class ChatResponse:
    conversation_id: str
    intent: ChatIntent
    status: str
    message: str
    trace_id: str = ""
    task_promoted: bool = False
    requires_trusted_approval: bool = False
    data: dict[str, Any] = field(default_factory=dict)
