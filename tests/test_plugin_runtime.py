from __future__ import annotations

import json
from pathlib import Path

import pytest

from nous_runtime.plugins import PluginError, PluginManager, PluginManifest, package_checksum


def make_plugin(root: Path, *, plugin_id="example.plugin", compatibility="0.1", permissions=("filesystem.read",), capabilities=("example.echo",), failing=False, dependencies=()):
    root.mkdir(parents=True)
    code = "def invoke(capability, payload):\n    " + ("raise RuntimeError('failure')\n" if failing else "return {'capability': capability, 'echo': payload.get('value', '')}\n")
    (root / "plugin_impl.py").write_text(code, encoding="utf-8")
    manifest = PluginManifest(plugin_id, "1.0.0", compatibility, "plugin_impl:invoke", tuple(capabilities), tuple(permissions), tuple(dependencies))
    manifest = PluginManifest.from_dict({**manifest.to_dict(), "package_checksum": package_checksum(root, manifest)})
    (root / "plugin.json").write_text(json.dumps(manifest.to_dict(), indent=2), encoding="utf-8")
    return manifest


def test_valid_plugin_install_enable_direct_invoke_is_blocked_disable_uninstall(tmp_path):
    source = tmp_path / "source"
    make_plugin(source)
    manager = PluginManager(tmp_path / "runtime", allow_unisolated_execution=True)
    installed = manager.install(source)
    assert installed.plugin_id == "example.plugin"
    manager.enable(installed.plugin_id)
    assert manager.capabilities.get("example.echo") is not None
    with pytest.raises(PluginError, match="UnifiedExtensionExecutor"):
        manager.invoke(installed.plugin_id, "example.echo", {"value": "ok"})
    manager.disable(installed.plugin_id)
    assert manager.capabilities.get("example.echo") is None
    manager.uninstall(installed.plugin_id)
    assert manager.registry.get(installed.plugin_id) is None


def test_invalid_manifest_and_incompatible_runtime_are_rejected(tmp_path):
    source = tmp_path / "invalid"
    make_plugin(source, plugin_id="Invalid ID")
    manager = PluginManager(tmp_path / "runtime")
    with pytest.raises(PluginError, match="invalid plugin_id"):
        manager.install(source)
    other = tmp_path / "other"
    make_plugin(other, compatibility="9.9")
    with pytest.raises(PluginError, match="incompatible"):
        manager.install(other)


def test_undeclared_capability_is_rejected(tmp_path):
    source = tmp_path / "source"
    make_plugin(source)
    (source / "capabilities.json").write_text('["example.echo", "hidden.network"]', encoding="utf-8")
    manifest = PluginManifest.load(source)
    updated = PluginManifest.from_dict({**manifest.to_dict(), "package_checksum": package_checksum(source, manifest)})
    (source / "plugin.json").write_text(json.dumps(updated.to_dict()), encoding="utf-8")
    with pytest.raises(PluginError, match="undeclared capabilities"):
        PluginManager(tmp_path / "runtime").install(source)


def test_permission_rejection_and_explicit_review(tmp_path):
    source = tmp_path / "source"
    make_plugin(source, permissions=("network",))
    manager = PluginManager(tmp_path / "runtime")
    with pytest.raises(PluginError, match="not approved"):
        manager.install(source)
    with pytest.raises(PluginError, match="cannot be enforced"):
        manager.install(source, approve_permissions=lambda permissions: permissions == ("network",))


def test_tampered_package_is_rejected(tmp_path):
    source = tmp_path / "source"
    make_plugin(source)
    (source / "plugin_impl.py").write_text("def invoke(*args): return {'tampered': True}\n", encoding="utf-8")
    with pytest.raises(PluginError, match="checksum mismatch"):
        PluginManager(tmp_path / "runtime").install(source)


def test_dependency_install_is_never_automatic(tmp_path):
    source = tmp_path / "source"
    make_plugin(source, dependencies=("unknown-package>=1",))
    with pytest.raises(PluginError, match="automatic plugin dependency installation is disabled"):
        PluginManager(tmp_path / "runtime").install(source)


def test_legacy_plugin_failure_path_cannot_bypass_kernel(tmp_path):
    source = tmp_path / "source"
    make_plugin(source, failing=True)
    manager = PluginManager(tmp_path / "runtime", allow_unisolated_execution=True)
    installed = manager.install(source)
    manager.enable(installed.plugin_id)
    with pytest.raises(PluginError, match="UnifiedExtensionExecutor"):
        manager.invoke(installed.plugin_id, "example.echo", {})
    record = manager.registry.get(installed.plugin_id)
    assert record is not None and record["state"] == "enabled"


def test_hidden_network_and_filesystem_permissions_are_rejected(tmp_path):
    network = tmp_path / "network"
    manifest = make_plugin(network)
    (network / "plugin_impl.py").write_text("import socket\n\ndef invoke(capability, payload):\n    return {}\n", encoding="utf-8")
    manifest = PluginManifest.from_dict({**manifest.to_dict(), "package_checksum": package_checksum(network, manifest)})
    (network / "plugin.json").write_text(json.dumps(manifest.to_dict()), encoding="utf-8")
    with pytest.raises(PluginError, match="undeclared permissions: network"):
        PluginManager(tmp_path / "runtime-network").install(network)

    filesystem = tmp_path / "filesystem"
    manifest = make_plugin(filesystem, permissions=())
    (filesystem / "plugin_impl.py").write_text("def invoke(capability, payload):\n    return {'value': open('hidden.txt').read()}\n", encoding="utf-8")
    manifest = PluginManifest.from_dict({**manifest.to_dict(), "package_checksum": package_checksum(filesystem, manifest)})
    (filesystem / "plugin.json").write_text(json.dumps(manifest.to_dict()), encoding="utf-8")
    with pytest.raises(PluginError, match="undeclared permissions: filesystem.read"):
        PluginManager(tmp_path / "runtime-filesystem").install(filesystem)


def test_plugin_invocation_denied_without_isolation_backend(tmp_path):
    source = tmp_path / "source"
    make_plugin(source)
    manager = PluginManager(tmp_path / "runtime")
    installed = manager.install(source)
    manager.enable(installed.plugin_id)
    with pytest.raises(PluginError, match="UnifiedExtensionExecutor"):
        manager.invoke(installed.plugin_id, "example.echo", {})
