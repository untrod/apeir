from __future__ import annotations

from dataclasses import replace

import pytest

from nous_runtime.agent.manifest import build_agent_manifest
from nous_runtime.agent.models import (
    AgentBudget,
    AgentCapabilityBinding,
    AgentProfile,
    AgentState,
)


def make_profile(
    agent_id: str,
    capabilities: tuple[str, ...],
    *,
    reliability: float = 0.5,
    roles: tuple[str, ...] = (),
) -> AgentProfile:
    manifest = build_agent_manifest(
        agent_id.replace("agent.", "").replace(".", " ").title(),
        agent_id=agent_id,
        capabilities=capabilities,
    )
    bindings = tuple(
        AgentCapabilityBinding(
            capability_id=capability,
            provider_id="test-provider",
            model_id=f"model-{agent_id}",
        )
        for capability in capabilities
    )
    return AgentProfile(
        manifest=replace(
            manifest,
            capabilities=bindings,
            budget=AgentBudget(
                max_invocations=5,
                max_model_invocations=5,
                max_runtime_ms=60_000,
            ),
            metadata={"reliability": reliability, "roles": roles},
        ),
        state=AgentState.READY,
    )


@pytest.fixture
def collaboration_profiles() -> tuple[AgentProfile, ...]:
    return (
        make_profile(
            "agent.manager",
            ("planning",),
            reliability=0.9,
            roles=("manager",),
        ),
        make_profile(
            "agent.reviewer",
            ("verification",),
            reliability=0.9,
            roles=("reviewer",),
        ),
        make_profile(
            "agent.worker_a",
            ("coding",),
            reliability=0.8,
            roles=("worker",),
        ),
        make_profile(
            "agent.worker_b",
            ("coding", "mathematics"),
            reliability=0.7,
            roles=("worker",),
        ),
    )
