# -*- coding: utf-8 -*-
"""Provider contract tests."""

import pytest
from remote_terminal.nous_core.provider import (
    Provider,
    register_adapter,
    unregister_adapter,
    list_providers,
    invoke_via_provider,
    invoke_via_provider_observation,
)


class TestProviderABC:
    """The Provider ABC must be enforced."""

    def test_abstract_class_cannot_instantiate(self):
        """Provider ABC cannot be instantiated directly."""
        with pytest.raises(TypeError):
            Provider()  # type: ignore

    def test_concrete_subclass(self, mock_provider):
        """Concrete Provider subclass is instantiable."""
        assert mock_provider.name == "mock"
        assert mock_provider.version == "1.0.0"

    def test_list_capabilities(self, mock_provider):
        """list_capabilities returns strings."""
        caps = mock_provider.list_capabilities()
        assert isinstance(caps, list)
        assert all(isinstance(c, str) for c in caps)
        assert "mock.test" in caps

    def test_invoke_returns_dict(self, mock_provider):
        """invoke returns a dict with 'ok' key."""
        result = mock_provider.invoke("mock.test", param1="value1")
        assert isinstance(result, dict)
        assert "ok" in result

    def test_health_returns_dict(self, mock_provider):
        """health returns a dict with 'status' key."""
        h = mock_provider.health()
        assert isinstance(h, dict)
        assert "status" in h


class TestProviderRegistry:
    """Provider registration must work."""

    def test_register_adapter(self, mock_provider):
        """register_adapter accepts a Provider."""
        ok = register_adapter(mock_provider)
        assert ok is True  # Returns True on success
        providers = list_providers()
        # list_providers returns list of dicts with provider_id
        provider_ids = [p["provider_id"] if isinstance(p, dict) else p for p in providers]
        assert mock_provider.provider_id in provider_ids

    def test_register_non_provider_rejected(self):
        """register_adapter rejects non-Provider objects."""
        with pytest.raises((TypeError, AttributeError)):
            register_adapter("not a provider")  # type: ignore

    def test_duplicate_provider(self, mock_provider):
        """Registering the same provider twice should be handled."""
        pid1 = register_adapter(mock_provider)
        # Second registration may overwrite or error — both OK
        pid2 = register_adapter(mock_provider)
        assert pid1 == pid2  # Same provider gets same ID

    def test_invoke_via_provider_observation(self, mock_provider):
        """Provider invocation has an Observation-first API."""
        from nous_runtime.planner.observation import Observation

        register_adapter(mock_provider)
        try:
            obs = invoke_via_provider_observation(
                mock_provider.provider_id,
                "mock.echo",
                {"text": "hello"},
            )
        finally:
            unregister_adapter(mock_provider.provider_id)

        assert isinstance(obs, Observation)
        assert obs.status == "success"
        assert obs.capability == "mock.echo"
        assert obs.metadata["provider_id"] == mock_provider.provider_id
        assert obs.data["result"]["params"] == {"text": "hello"}

    def test_legacy_invoke_via_provider_still_returns_dict(self, mock_provider):
        """Legacy provider invocation remains dict-compatible."""
        register_adapter(mock_provider)
        try:
            result = invoke_via_provider(
                mock_provider.provider_id,
                "mock.echo",
                {"text": "hello"},
            )
        finally:
            unregister_adapter(mock_provider.provider_id)

        assert result["ok"] is True
        assert result["params"] == {"text": "hello"}
        assert "_provider_duration_ms" in result
