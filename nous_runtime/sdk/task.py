# -*- coding: utf-8 -*-
"""SDK Task — define and execute tasks on the Nous platform."""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

_log = logging.getLogger("nous.sdk.task")


@dataclass
class Task:
    """A task to be executed on the Nous platform.

    Usage:
        task = Task(goal="train model", target_agent="agent.claude", constraints={"max_time_ms": 60000})
        result = task.submit()
    """

    goal: str = ""
    target_agent: str = ""
    target_capability: str = ""
    params: dict[str, Any] = field(default_factory=dict)
    constraints: dict[str, Any] = field(default_factory=dict)
    task_id: str = ""
    created_at: str = ""
    status: str = "created"

    def __post_init__(self):
        if not self.task_id:
            self.task_id = f"task_{uuid.uuid4().hex[:16]}"
        if not self.created_at:
            self.created_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    def submit(self) -> dict[str, Any]:
        """Submit this task for execution."""
        return {
            "task_id": self.task_id, "goal": self.goal,
            "target_agent": self.target_agent, "status": "submitted",
            "created_at": self.created_at,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id, "goal": self.goal,
            "target_agent": self.target_agent, "target_capability": self.target_capability,
            "params": self.params, "constraints": self.constraints,
            "status": self.status, "created_at": self.created_at,
        }
