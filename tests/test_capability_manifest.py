# -*- coding: utf-8 -*-
"""Capability manifest export tests."""


class TestCapabilityManifest:
    def test_manifest_from_capability_filters_sensitive_metadata(self):
        from nous_runtime.capability.manifest import CapabilityManifest

        manifest = CapabilityManifest.from_capability(
            {
                "name": "test.echo",
                "category": "tool",
                "provider": "test_provider",
                "description": "Echo test capability",
                "risk": "high",
                "timeout_ms": 5000,
                "max_retries": 2,
                "requires_auth": True,
                "requires_device": False,
                "depends_on": '["test.prepare"]',
                "metadata": {
                    "tags": ["test", "echo"],
                    "input_schema": {"type": "object"},
                    "output_schema": {"type": "object"},
                    "api_key": "secret",
                    "token": "secret",
                    "version": "1.2.3",
                },
            },
            availability={"status": "available"},
        )

        data = manifest.to_dict()

        assert data["capability_id"] == "test.echo"
        assert data["risk_level"] == "high"
        assert data["requires_approval"] is True
        assert data["requires_auth"] is True
        assert data["depends_on"] == ["test.prepare"]
        assert data["tags"] == ["test", "echo"]
        assert data["availability"] == "available"
        assert "api_key" not in data["metadata"]
        assert "token" not in data["metadata"]
        assert manifest.validate() == []

    def test_manifest_validation_reports_invalid_fields(self):
        from nous_runtime.capability.manifest import CapabilityManifest

        manifest = CapabilityManifest(
            capability_id="bad",
            risk_level="danger",
            timeout_ms=0,
        )

        errors = manifest.validate()

        assert any("capability_id" in e for e in errors)
        assert any("risk_level" in e for e in errors)
        assert any("timeout_ms" in e for e in errors)

    def test_export_registered_capability_manifest(self, monkeypatch, tmp_path):
        monkeypatch.setenv("NOUS_DATA_DIR", str(tmp_path))

        from remote_terminal.nous_core.db import run_migrations
        from remote_terminal.nous_core.capability import register_capability, unregister_capability
        from nous_runtime.capability.manifest import get_capability_manifest

        run_migrations()
        register_capability(
            "test.manifest",
            category="test",
            provider="test_provider",
            description="Manifest test capability",
            risk="low",
            metadata={"tags": ["manifest"]},
        )
        try:
            manifest = get_capability_manifest("test.manifest", include_availability=False)
        finally:
            unregister_capability("test.manifest")

        assert manifest is not None
        assert manifest.capability_id == "test.manifest"
        assert manifest.category == "test"
        assert manifest.tags == ["manifest"]
