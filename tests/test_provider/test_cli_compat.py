# -*- coding: utf-8 -*-
"""Provider CLI compatibility tests — prevent regression of #008."""


class TestProviderListCompat:
    """Provider list must work with 0, 1, or many providers without .items() crash."""

    def test_list_empty_providers(self):
        """List with zero providers returns empty list without crashing."""
        from nous_runtime.provider.registry import registry
        result = registry.list_all()
        assert isinstance(result, list)

    def test_health_empty_providers(self):
        """Health with zero providers returns valid status."""
        from nous_runtime.provider.registry import registry
        result = registry.health_all()
        assert "status" in result
        assert result["status"] in ("ok", "degraded", "down", "unknown")


class TestCapabilityListCompat:
    """Capability list must auto-seed without brain.py running."""

    def test_list_capabilities_nonempty(self):
        """Capability list must return results (auto-seed if empty)."""
        from remote_terminal.nous_core.capability import list_capabilities
        caps = list_capabilities()
        assert isinstance(caps, list)
        # Should have seeded capabilities (model.*, device.*, etc.)
        assert len(caps) > 0, "No capabilities found — auto-seed may have failed"
