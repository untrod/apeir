"""Agent Execution Runtime errors."""

from __future__ import annotations

from typing import Mapping

from nous_runtime.core.errors import NousError


class AgentRuntimeError(NousError):
    error_code = "agent_runtime_error"

    def __init__(self, message: str, *, context: Mapping[str, object] | None = None):
        super().__init__(message)
        self.context = dict(context or {})


class AgentLifecycleError(AgentRuntimeError):
    error_code = "agent_lifecycle_error"


class AgentBudgetError(AgentRuntimeError):
    error_code = "agent_budget_exceeded"


class AgentBoundaryError(AgentRuntimeError):
    error_code = "agent_invocation_denied"


class AgentCheckpointError(AgentRuntimeError):
    error_code = "agent_checkpoint_error"


class AgentTerminationError(AgentRuntimeError):
    error_code = "agent_termination_error"


class AgentCollaborationError(AgentRuntimeError):
    error_code = "agent_collaboration_error"


__all__ = [
    "AgentBoundaryError",
    "AgentBudgetError",
    "AgentCheckpointError",
    "AgentCollaborationError",
    "AgentLifecycleError",
    "AgentRuntimeError",
    "AgentTerminationError",
]
