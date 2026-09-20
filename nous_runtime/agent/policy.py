# -*- coding: utf-8 -*-
"""Agent policy helpers."""

from __future__ import annotations

from nous_runtime.agent.models import AgentProfile
from nous_runtime.agent.sandbox import find_binding


class AgentPolicyError(RuntimeError):
    """Raised when an Agent policy check fails."""


def require_capability(profile: AgentProfile, capability_id: str) -> None:
    if find_binding(profile, capability_id) is None:
        raise AgentPolicyError(f"capability not allowed for agent: {capability_id}")


def require_no_self_approval(subject_type: str) -> None:
    if subject_type == "model":
        raise AgentPolicyError("model subjects cannot authorize Agent execution")
