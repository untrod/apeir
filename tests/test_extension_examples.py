from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from nous_runtime.plugins import PluginError, PluginManager, PluginManifest, package_checksum

ROOT = Path(__file__).resolve().parents[1]


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_provider_reference_registers_invokes_and_cleans_up(tmp_path, monkeypatch):
    from nous_runtime.provider.registry import ProviderRegistry
    from remote_terminal.nous_core.capability import get_capability

    monkeypatch.chdir(tmp_path)
    module = _load(ROOT / "examples/hello_provider/hello_provider.py", "hello_provider_example")
    registry = ProviderRegistry()
    provider_id = registry.install(module.HelloProvider())
    try:
        assert registry.get(provider_id).invoke("example.greet", name="Nous")["ok"]
        assert get_capability("example.greet")["provider"] == provider_id
    finally:
        registry.remove(provider_id)
    assert get_capability("example.greet") is None


def test_connector_reference_enforces_governance_and_cleans_up():
    module = _load(ROOT / "examples/hello_connector/run_example.py", "hello_connector_example")
    module.main()


def test_plugin_reference_manifest_permissions_lifecycle_and_cleanup(tmp_path):
    source = ROOT / "examples/hello_plugin"
    manifest = PluginManifest.load(source)
    assert manifest.permissions == ()
    assert manifest.package_checksum == package_checksum(source, manifest)

    manager = PluginManager(tmp_path, allow_unisolated_execution=True)
    installed = manager.install(source)
    manager.enable(installed.plugin_id)
    with pytest.raises(PluginError, match="UnifiedExtensionExecutor"):
        manager.invoke(installed.plugin_id, "example.echo", {"value": "Nous"})
    manager.disable(installed.plugin_id)
    assert manager.capabilities.get("example.echo") is None
    manager.uninstall(installed.plugin_id)
    assert manager.registry.get(installed.plugin_id) is None


def test_plugin_checksum_is_stable_across_text_line_endings(tmp_path):
    manifest = PluginManifest(
        plugin_id="line-ending-check",
        version="1.0.0",
        runtime_compatibility=">=2.0",
        entry_point="plugin_impl:run",
        capabilities=("example.echo",),
    )
    unix_root = tmp_path / "unix"
    windows_root = tmp_path / "windows"
    unix_root.mkdir()
    windows_root.mkdir()
    (unix_root / "plugin_impl.py").write_bytes(b"def run():\n    return True\n")
    (windows_root / "plugin_impl.py").write_bytes(b"def run():\r\n    return True\r\n")

    assert package_checksum(unix_root, manifest) == package_checksum(windows_root, manifest)


def test_sdk_and_vscode_reference_flows_use_server_runtime():
    python = (ROOT / "examples/sdk/python_quickstart.py").read_text(encoding="utf-8")
    typescript = (ROOT / "examples/sdk/typescript_quickstart.ts").read_text(encoding="utf-8")
    extension = (ROOT / "ide/vscode/src/extension.ts").read_text(encoding="utf-8")

    assert "runtime.workflow" in python
    assert "runtime.workflow" in typescript
    assert "/api/ide/runtime" in extension
    assert "approval.resolve" in extension
    assert "NOUS_API_TOKEN" in python and "NOUS_API_TOKEN" in typescript
