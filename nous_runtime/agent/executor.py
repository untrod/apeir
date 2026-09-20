# -*- coding: utf-8 -*-
"""Governed Agent execution entry point."""

from __future__ import annotations

import getpass
import os
from typing import Any

from nous_runtime.agent.models import AgentState
from nous_runtime.agent.registry import AgentRegistry
from nous_runtime.agent.sandbox import AgentExecutionRequest, validate_request
from nous_runtime.governance import ActionProposal, AuthorizationContext, get_gate
from nous_runtime.governance.runtime_mode import should_fail_closed
from nous_runtime.planner.observation import Observation


def execute_agent_capability(
    agent_id: str,
    capability_id: str,
    *,
    params: dict[str, Any] | None = None,
    workspace_path: str = "",
    registry: AgentRegistry | None = None,
    context: AuthorizationContext | None = None,
    estimated_cost_usd: float = 0.0,
    estimated_tokens: int = 0,
    estimated_runtime_ms: int = 0,
) -> Observation:
    """Execute a bound capability as an Agent through the Governance Gate."""
    registry = registry or AgentRegistry(workspace_path or ".nous")
    profile = registry.require(agent_id)
    if profile.state == AgentState.REGISTERED:
        profile = registry.update_state(agent_id, AgentState.READY)

    request = AgentExecutionRequest(
        agent_id=agent_id,
        capability_id=capability_id,
        params=dict(params or {}),
        workspace_path=workspace_path,
        estimated_cost_usd=estimated_cost_usd,
        estimated_tokens=estimated_tokens,
        estimated_runtime_ms=estimated_runtime_ms,
    )

    try:
        binding = validate_request(profile, request)
    except Exception as exc:
        return Observation.failure(
            "agent.execute",
            [str(exc)],
            capability=capability_id,
            metadata={"agent_id": agent_id, "error_code": "NOUS_AGENT_BOUNDARY_DENIED"},
        )

    workspace = workspace_path or os.getcwd()
    proposal = ActionProposal(
        action_type="agent.execute",
        capability_id=capability_id,
        provider_id=binding.provider_id,
        model_id=binding.model_id,
        agent_id=agent_id,
        params=request.params,
        target_workspace=workspace,
        estimated_cost_usd=estimated_cost_usd,
        estimated_duration_ms=estimated_runtime_ms,
        required_permissions=binding.permissions,
        side_effect_class=_infer_side_effect(capability_id),
        reversibility=_infer_reversibility(capability_id),
        retry_behavior="idempotent",
        locality="local",
    )
    auth_context = context or AuthorizationContext(
        subject_type="agent",
        subject_id=agent_id,
        authn_method="agent_registry",
        authn_confidence=0.8,
        session_device=f"{getpass.getuser()}@{os.environ.get('COMPUTERNAME', 'localhost')}",
        session_locality="local",
    )

    try:
        decision = get_gate().evaluate(proposal, auth_context)
    except Exception as exc:
        if should_fail_closed(surface="local_cli"):
            return Observation.failure(
                "agent.execute",
                [f"Governance gate unavailable: {exc}"],
                capability=capability_id,
                metadata={
                    "agent_id": agent_id,
                    "error_code": "NOUS_AGENT_GOVERNANCE_UNAVAILABLE",
                    "gate_bypass_blocked": True,
                },
            )
    else:
        if decision.action_mode == "DENY" or (
            decision.action_mode in {"ASK_APPROVAL", "ESCALATE"} and should_fail_closed(surface="local_cli")
        ):
            return Observation.failure(
                "agent.execute",
                [decision.reason_message],
                capability=capability_id,
                metadata={
                    "agent_id": agent_id,
                    "error_code": "NOUS_AGENT_UNAUTHORIZED",
                    "gate_decision_id": decision.decision_id,
                    "gate_reason": decision.reason_code,
                },
            )

    profile = registry.update_state(agent_id, AgentState.RUNNING)
    try:
        from nous_runtime.capability.resolver import execute_capability_observation

        observation = execute_capability_observation(capability_id, **request.params)
        registry.update_state(agent_id, AgentState.READY if observation.status == "success" else AgentState.FAILED)
        observation.metadata = dict(observation.metadata or {})
        observation.metadata["agent_id"] = agent_id
        observation.metadata["agent_runtime"] = True
        return observation
    except Exception as exc:
        registry.update_state(agent_id, AgentState.FAILED, error=str(exc))
        return Observation.failure(
            "agent.execute",
            [str(exc)],
            capability=capability_id,
            metadata={"agent_id": agent_id, "error_code": "NOUS_AGENT_EXECUTION_FAILED"},
        )


def _infer_side_effect(capability_id: str) -> str:
    if capability_id in {"system.echo", "system.status"}:
        return "read_only"
    if "delete" in capability_id or "exec" in capability_id or "shell" in capability_id:
        return "destructive"
    if "write" in capability_id:
        return "local_write"
    if "read" in capability_id or "search" in capability_id:
        return "read_only"
    return "unknown"


def _infer_reversibility(capability_id: str) -> str:
    if capability_id in {"system.echo", "system.status"}:
        return "reversible"
    if "delete" in capability_id or "exec" in capability_id or "shell" in capability_id:
        return "irreversible"
    if "write" in capability_id:
        return "partially_reversible"
    return "unknown"
