from __future__ import annotations

import json

from nous_runtime.cli.provider_setup import _save_provider_config
from nous_runtime.ecosystem.installer import CapabilityInstaller
from nous_runtime.ecosystem.manifest import CapabilityManifest


class _Registry:
    def __init__(self):
        self.installed = []

    def install(self, manifest):
        self.installed.append(manifest.name)
        return True

    def remove(self, name):
        return True

    def get(self, name):
        return None

    def list(self):
        return []


def test_provider_config_does_not_persist_secret(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "nous_runtime.project.workspace.find_workspace",
        lambda: str(tmp_path),
    )

    _save_provider_config(
        "example",
        {
            "endpoint": "https://provider.invalid/v1",
            "api_key": "private-test-value",
            "api_key_env": "EXAMPLE_API_KEY",
            "model": "example-model",
        },
    )

    raw = (tmp_path / "providers.json").read_text(encoding="utf-8")
    data = json.loads(raw)
    assert "private-test-value" not in raw
    assert "api_key" not in data["example"]
    assert data["example"]["api_key_env"] == "EXAMPLE_API_KEY"


def test_capability_installer_requires_dependency_authorization(monkeypatch):
    registry = _Registry()
    installer = CapabilityInstaller(registry=registry)
    called = []
    monkeypatch.setattr(
        installer,
        "_install_python_deps",
        lambda deps: called.append(deps) or True,
    )
    manifest = CapabilityManifest(
        name="example.plugin",
        version="1.0.0",
        python_dependencies=("example-dependency",),
    )

    assert installer.install_from_manifest(manifest) is False
    assert called == []
    assert registry.installed == []


def test_capability_installer_checks_authorized_install_result(monkeypatch):
    registry = _Registry()
    installer = CapabilityInstaller(
        registry=registry,
        allow_dependency_install=True,
    )
    monkeypatch.setattr(installer, "_install_python_deps", lambda deps: False)
    manifest = CapabilityManifest(
        name="example.plugin",
        version="1.0.0",
        python_dependencies=("example-dependency",),
    )

    assert installer.install_from_manifest(manifest) is False
    assert registry.installed == []
