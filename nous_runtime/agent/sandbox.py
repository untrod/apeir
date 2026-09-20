# -*- coding: utf-8 -*-
"""Agent execution boundary checks."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from nous_runtime.agent.budget import AgentBudgetError, require_budget
from nous_runtime.agent.errors import AgentBoundaryError
from nous_runtime.agent.models import AgentCapabilityBinding, AgentProfile, AgentState


class AgentSandboxError(AgentBoundaryError):
    """Raised when an Agent request violates its execution boundary."""


@dataclass(frozen=True)
class AgentExecutionRequest:
    agent_id: str
    capability_id: str
    params: dict[str, Any]
    workspace_path: str = ""
    estimated_cost_usd: float = 0.0
    estimated_tokens: int = 0
    estimated_runtime_ms: int = 0


def find_binding(profile: AgentProfile, capability_id: str) -> AgentCapabilityBinding | None:
    for binding in profile.manifest.capabilities:
        if binding.capability_id == capability_id:
            return binding
    return None


def validate_request(profile: AgentProfile, request: AgentExecutionRequest) -> AgentCapabilityBinding:
    if profile.agent_id != request.agent_id:
        raise AgentSandboxError("agent identity mismatch")
    if profile.state not in {AgentState.READY, AgentState.RUNNING, AgentState.WAITING}:
        raise AgentSandboxError(f"agent is not ready: {profile.state.value}")

    binding = find_binding(profile, request.capability_id)
    if binding is None:
        raise AgentSandboxError(f"capability not bound to agent: {request.capability_id}")

    try:
        require_budget(
            profile.manifest.budget,
            cost_usd=request.estimated_cost_usd,
            tokens=request.estimated_tokens,
            runtime_ms=request.estimated_runtime_ms,
        )
    except AgentBudgetError as exc:
        raise AgentSandboxError(str(exc)) from exc

    return binding
