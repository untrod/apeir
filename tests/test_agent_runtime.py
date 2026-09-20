# -*- coding: utf-8 -*-

from __future__ import annotations

import pytest

from nous_runtime.agent.executor import execute_agent_capability
from nous_runtime.agent.lifecycle import AgentLifecycleError, transition
from nous_runtime.agent.manifest import build_agent_manifest
from nous_runtime.agent.models import AgentState
from nous_runtime.agent.registry import AgentRegistry
from nous_runtime.agent.sandbox import AgentExecutionRequest, AgentSandboxError, validate_request
from nous_runtime.governance.contracts import AuthorizationContext


def test_agent_manifest_round_trip():
    manifest = build_agent_manifest(
        "Worker",
        agent_id="agent.worker",
        capabilities=("system.echo",),
        permissions=("capability.execute",),
        budget={"max_cost_usd": 1.0, "max_tokens": 100},
    )

    restored = manifest.from_dict(manifest.to_dict())

    assert restored.identity.agent_id == "agent.worker"
    assert restored.capabilities[0].capability_id == "system.echo"
    assert restored.permissions == ("capability.execute",)
    assert restored.validate() == []


def test_agent_registry_register_list_and_update(tmp_path):
    registry = AgentRegistry(tmp_path)
    manifest = build_agent_manifest("Worker", agent_id="agent.worker", capabilities=("system.echo",))

    profile = registry.register(manifest)
    updated = registry.update_state(profile.agent_id, AgentState.READY)

    assert registry.get("agent.worker") is not None
    assert [item.agent_id for item in registry.list()] == ["agent.worker"]
    assert updated.state == AgentState.READY


def test_agent_lifecycle_rejects_invalid_transition():
    manifest = build_agent_manifest("Worker", agent_id="agent.worker", capabilities=("system.echo",))
    from nous_runtime.agent.models import AgentProfile

    created = AgentProfile(manifest=manifest, state=AgentState.CREATED)

    with pytest.raises(AgentLifecycleError):
        transition(created, AgentState.RUNNING)


def test_agent_sandbox_requires_bound_capability(tmp_path):
    registry = AgentRegistry(tmp_path)
    profile = registry.register(build_agent_manifest("Worker", agent_id="agent.worker", capabilities=("system.echo",)))
    profile = registry.update_state(profile.agent_id, AgentState.READY)

    with pytest.raises(AgentSandboxError):
        validate_request(
            profile,
            AgentExecutionRequest(
                agent_id="agent.worker",
                capability_id="workspace.write",
                params={},
            ),
        )


def test_agent_sandbox_enforces_budget(tmp_path):
    registry = AgentRegistry(tmp_path)
    manifest = build_agent_manifest(
        "Worker",
        agent_id="agent.worker",
        capabilities=("system.echo",),
        budget={"max_cost_usd": 0.01},
    )
    profile = registry.register(manifest)
    profile = registry.update_state(profile.agent_id, AgentState.READY)

    with pytest.raises(AgentSandboxError):
        validate_request(
            profile,
            AgentExecutionRequest(
                agent_id="agent.worker",
                capability_id="system.echo",
                params={},
                estimated_cost_usd=1.0,
            ),
        )


def test_agent_executor_blocks_model_subject_self_authorization(tmp_path):
    registry = AgentRegistry(tmp_path)
    registry.register(build_agent_manifest("Worker", agent_id="agent.worker", capabilities=("system.echo",)))

    observation = execute_agent_capability(
        "agent.worker",
        "system.echo",
        params={"message": "hello"},
        workspace_path=str(tmp_path),
        registry=registry,
        context=AuthorizationContext(
            subject_type="model",
            subject_id="model.self",
            authn_method="test",
            authn_confidence=1.0,
        ),
    )

    assert observation.status == "failed"
    assert observation.metadata["error_code"] == "NOUS_AGENT_UNAUTHORIZED"
