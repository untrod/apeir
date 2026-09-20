# -*- coding: utf-8 -*-
"""Agent lifecycle transition rules."""

from __future__ import annotations

from nous_runtime.agent.models import AgentProfile, AgentState
from nous_runtime.agent.errors import AgentLifecycleError


_ALLOWED: dict[AgentState, set[AgentState]] = {
    AgentState.CREATED: {AgentState.REGISTERED, AgentState.TERMINATED},
    AgentState.REGISTERED: {AgentState.READY, AgentState.TERMINATED},
    AgentState.READY: {AgentState.RUNNING, AgentState.TERMINATED},
    AgentState.RUNNING: {AgentState.READY, AgentState.WAITING, AgentState.FAILED, AgentState.TERMINATED},
    AgentState.WAITING: {AgentState.READY, AgentState.FAILED, AgentState.TERMINATED},
    AgentState.FAILED: {AgentState.RECOVERING, AgentState.TERMINATED},
    AgentState.RECOVERING: {AgentState.READY, AgentState.FAILED, AgentState.TERMINATED},
    AgentState.TERMINATED: set(),
}


def can_transition(current: AgentState, target: AgentState) -> bool:
    return target in _ALLOWED.get(current, set())


def transition(profile: AgentProfile, target: AgentState, *, error: str = "") -> AgentProfile:
    if profile.state == target:
        return profile
    if not can_transition(profile.state, target):
        raise AgentLifecycleError(f"invalid agent transition: {profile.state.value} -> {target.value}")
    return profile.with_state(target, error=error)
