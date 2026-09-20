# -*- coding: utf-8 -*-
"""Capability resolver contract tests."""

from nous_runtime.capability.resolver import (
    resolve_capability,
    execute_capability,
    execute_capability_observation,
    ResolutionResult,
    ExecutionResult,
)


class TestCapabilityResolver:
    """Capability resolver must enforce the contract."""

    def test_resolve_nonexistent_capability(self):
        """Resolving a nonexistent capability returns unresolved."""
        result = resolve_capability("nonexistent.capability")
        assert isinstance(result, ResolutionResult)
        assert result.resolved is False
        assert result.error

    def test_resolution_result_structure(self):
        """ResolutionResult has the expected fields."""
        result = resolve_capability("nonexistent.capability")
        assert result.capability_id == "nonexistent.capability"
        assert result.provider_id == ""

    def test_execution_result_structure(self):
        """ExecutionResult has the expected fields."""
        result = ExecutionResult(
            ok=True,
            capability_id="test.cap",
            provider_id="test_prov",
            result={"data": "value"},
            duration_ms=1.5,
        )
        assert result.ok is True
        assert result.capability_id == "test.cap"
        assert result.provider_id == "test_prov"

    def test_execution_failure_structure(self):
        """Failed execution includes error code."""
        result = ExecutionResult(
            ok=False,
            capability_id="test.cap",
            provider_id="",
            error="Something went wrong",
            error_code="NOUS_CAPABILITY_NOT_FOUND",
        )
        assert result.ok is False
        assert result.error_code == "NOUS_CAPABILITY_NOT_FOUND"

    def test_execute_capability_observation_failure(self):
        """Capability execution has an Observation-first API."""
        from nous_runtime.planner.observation import Observation

        obs = execute_capability_observation("nonexistent.capability")

        assert isinstance(obs, Observation)
        assert obs.status == "failed"
        assert obs.capability == "nonexistent.capability"
        assert obs.metadata["error_code"] == "NOUS_CAPABILITY_NOT_FOUND"
        assert obs.errors

    def test_execution_result_from_observation(self):
        """Legacy ExecutionResult adapts from Observation."""
        from nous_runtime.planner.observation import Observation

        obs = Observation.success(
            "capability.execute",
            {"result": {"ok": True, "value": 1}},
            capability="test.cap",
            duration_ms=2.0,
            metadata={"provider_id": "test_provider"},
        )

        result = ExecutionResult.from_observation(obs)

        assert result.ok is True
        assert result.capability_id == "test.cap"
        assert result.provider_id == "test_provider"
        assert result.result == {"ok": True, "value": 1}

    def test_execute_capability_observation_success(self):
        """Resolver wraps provider output into a capability Observation."""
        from remote_terminal.nous_core.capability import unregister_capability
        from remote_terminal.nous_core.provider import Provider, register_adapter, unregister_adapter

        class EchoProvider(Provider):
            provider_id = "resolver_observation_test"
            provider_name = "Resolver Observation Test"

            def list_capabilities(self):
                return ["test.resolver_observation_echo"]

            def invoke(self, capability_id, **params):
                return {"ok": True, "value": params["value"]}

            def health(self):
                return {"status": "ok"}

        provider = EchoProvider()
        register_adapter(provider)
        try:
            obs = execute_capability_observation(
                "test.resolver_observation_echo",
                value=42,
            )
            result = execute_capability("test.resolver_observation_echo", value=42)
        finally:
            unregister_adapter(provider.provider_id)
            unregister_capability("test.resolver_observation_echo")

        assert obs.status == "success"
        assert obs.data["result"] == {"ok": True, "value": 42}
        assert obs.data["provider_observation"]["tool"] == "provider.invoke"
        assert result.ok is True
        assert result.provider_id == provider.provider_id
