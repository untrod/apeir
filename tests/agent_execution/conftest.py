from dataclasses import replace

import pytest

from nous_runtime.agent.manifest import build_agent_manifest
from nous_runtime.agent.models import (
    AgentCapabilityBinding,
    AgentProfile,
    AgentState,
)


@pytest.fixture
def agent_profile() -> AgentProfile:
    manifest = build_agent_manifest(
        "Execution Worker",
        agent_id="agent.execution_worker",
        capabilities=("tool.echo", "model.reason"),
        budget={
            "max_cost_usd": 10.0,
            "max_tokens": 10_000,
            "max_runtime_ms": 60_000,
            "max_invocations": 10,
            "max_tool_invocations": 5,
            "max_model_invocations": 5,
            "max_checkpoints": 3,
            "max_steps": 10,
        },
    )
    bindings = (
        AgentCapabilityBinding(capability_id="tool.echo"),
        AgentCapabilityBinding(
            capability_id="model.reason",
            provider_id="test-provider",
            model_id="test-model",
        ),
    )
    return AgentProfile(
        manifest=replace(manifest, capabilities=bindings),
        state=AgentState.READY,
    )
