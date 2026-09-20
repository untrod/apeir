# -*- coding: utf-8 -*-
"""Agent manifest construction helpers."""

from __future__ import annotations

from typing import Any

from nous_runtime.agent.models import AgentCapabilityBinding, AgentBudget, AgentIdentity, AgentManifest, new_agent_id


def build_agent_manifest(
    name: str,
    *,
    agent_id: str = "",
    description: str = "",
    capabilities: list[str] | tuple[str, ...] = (),
    permissions: list[str] | tuple[str, ...] = (),
    version: str = "1.0.0",
    trust_level: str = "local",
    budget: dict[str, Any] | None = None,
) -> AgentManifest:
    identity = AgentIdentity(
        agent_id=agent_id or new_agent_id(name),
        name=name,
        version=version,
        trust_level=trust_level,
    )
    bindings = tuple(AgentCapabilityBinding(capability_id=str(item)) for item in capabilities)
    return AgentManifest(
        identity=identity,
        description=description,
        capabilities=bindings,
        permissions=tuple(str(item) for item in permissions),
        budget=AgentBudget.from_dict(budget),
    )
