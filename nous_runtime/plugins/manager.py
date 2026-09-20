"""Plugin validation, installation, lifecycle, and isolated invocation."""

from __future__ import annotations

import ast
import json
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any, Callable

from nous_runtime.ecosystem.manifest import CapabilityManifest
from nous_runtime.ecosystem.registry import CapabilityRegistry
from nous_runtime.plugins.models import PluginManifest
from nous_runtime.plugins.registry import PluginRegistry
from nous_runtime.plugins.security import SignatureVerifier, validate_package
from nous_runtime.version import __version__

PLUGIN_API_VERSION = "0.1"


class PluginError(RuntimeError):
    pass


class PluginManager:
    def __init__(self, root: str | Path = ".", *, allowed_permissions: set[str] | None = None, enforceable_permissions: set[str] | None = None, verifier: SignatureVerifier | None = None, allow_unisolated_execution: bool = False):
        self.root = Path(root).resolve()
        self.registry = PluginRegistry(self.root)
        self.capabilities = CapabilityRegistry(str(self.root))
        self.allowed_permissions = set(allowed_permissions or {"filesystem.read"})
        self.enforceable_permissions = set(enforceable_permissions or {"filesystem.read"})
        self.verifier = verifier
        self.allow_unisolated_execution = allow_unisolated_execution
        self.install_root = self.root / ".nous" / "plugins"

    def validate(self, source: str | Path) -> tuple[PluginManifest, list[str]]:
        package = Path(source).resolve()
        if not package.is_dir():
            raise PluginError("plugin source must be a directory")
        manifest = PluginManifest.load(package)
        errors = validate_package(package, manifest, verifier=self.verifier)
        if not self._compatible(manifest.runtime_compatibility):
            errors.append(f"runtime {__version__} is incompatible with {manifest.runtime_compatibility}")
        undeclared = self._discover_undeclared_capabilities(package, manifest)
        if undeclared:
            errors.append("undeclared capabilities: " + ", ".join(undeclared))
        undeclared_permissions = self._discover_undeclared_permissions(package, manifest)
        if undeclared_permissions:
            errors.append("undeclared permissions: " + ", ".join(undeclared_permissions))
        return manifest, errors

    def install(self, source: str | Path, *, approve_permissions: Callable[[tuple[str, ...]], bool] | None = None) -> PluginManifest:
        package = Path(source).resolve()
        manifest, errors = self.validate(package)
        if errors:
            raise PluginError("; ".join(errors))
        denied = set(manifest.permissions) - self.allowed_permissions
        if denied and (approve_permissions is None or not approve_permissions(tuple(sorted(denied)))):
            raise PluginError("plugin permissions were not approved: " + ", ".join(sorted(denied)))
        unsupported = set(manifest.permissions) - self.enforceable_permissions
        if unsupported:
            raise PluginError("plugin permissions cannot be enforced by the configured isolation backend: " + ", ".join(sorted(unsupported)))
        if manifest.dependencies:
            raise PluginError("automatic plugin dependency installation is disabled")
        destination = self.install_root / manifest.plugin_id / manifest.version
        self.install_root.parent.mkdir(parents=True, exist_ok=True)
        staging = Path(tempfile.mkdtemp(prefix="plugin-", dir=str(self.install_root.parent)))
        try:
            shutil.copytree(package, staging / "package", dirs_exist_ok=True)
            copied_manifest, copied_errors = self.validate(staging / "package")
            if copied_errors:
                raise PluginError("copied package validation failed: " + "; ".join(copied_errors))
            if destination.exists():
                raise PluginError("plugin version is already installed")
            destination.parent.mkdir(parents=True, exist_ok=True)
            os.replace(staging / "package", destination)
            self.registry.put(copied_manifest, destination, state="disabled")
            return copied_manifest
        finally:
            shutil.rmtree(staging, ignore_errors=True)

    def enable(self, plugin_id: str) -> None:
        record = self._require(plugin_id)
        manifest: PluginManifest = record["manifest"]
        installed: list[str] = []
        for capability in manifest.capabilities:
            existing = self.capabilities.get(capability)
            if existing is not None and existing.metadata.get("plugin_id") != plugin_id:
                self._remove_capabilities(installed)
                raise PluginError(f"capability is already owned by another package: {capability}")
            capability_manifest = CapabilityManifest(name=capability, version=manifest.version, category="plugin", permissions=manifest.permissions, risk_level="medium", trust="community", entry_point=manifest.entry_point, metadata={"plugin_id": plugin_id})
            if not self.capabilities.install(capability_manifest):
                self._remove_capabilities(installed)
                raise PluginError(f"failed to register plugin capability: {capability}")
            installed.append(capability)
        self.registry.set_state(plugin_id, "enabled")

    def disable(self, plugin_id: str) -> None:
        record = self._require(plugin_id)
        self._remove_capabilities(record["manifest"].capabilities)
        self.registry.set_state(plugin_id, "disabled")

    def uninstall(self, plugin_id: str) -> None:
        record = self._require(plugin_id)
        self.disable(plugin_id)
        package_path: Path = record["package_path"]
        try:
            package_path.relative_to(self.install_root.resolve())
        except ValueError as exc:
            raise PluginError("refusing to remove plugin outside install root") from exc
        if package_path.exists():
            shutil.rmtree(package_path)
        self.registry.remove(plugin_id)

    def invoke(self, plugin_id: str, capability: str, payload: dict[str, Any], *, timeout: float = 30.0) -> dict[str, Any]:
        del plugin_id, capability, payload, timeout
        raise PluginError(
            "legacy direct plugin invocation was removed; import the plugin into "
            "ExtensionRegistry and execute it through UnifiedExtensionExecutor"
        )

    def _isolate_failure(self, plugin_id: str, manifest: PluginManifest, error: str) -> None:
        self._remove_capabilities(manifest.capabilities)
        self.registry.set_state(plugin_id, "failed", error=error[-2000:])

    def _remove_capabilities(self, capabilities: Any) -> None:
        for capability in capabilities:
            existing = self.capabilities.get(str(capability))
            if existing is not None and existing.metadata.get("plugin_id"):
                self.capabilities.remove(str(capability))

    def _require(self, plugin_id: str) -> dict[str, Any]:
        record = self.registry.get(plugin_id)
        if record is None:
            raise PluginError(f"plugin is not installed: {plugin_id}")
        return record

    @staticmethod
    def _compatible(spec: str) -> bool:
        if spec in {"*", "any"}:
            return True
        supported = {part.strip() for part in spec.replace(">=", "").split(",")}
        return PLUGIN_API_VERSION in supported

    @staticmethod
    def _discover_undeclared_capabilities(package: Path, manifest: PluginManifest) -> list[str]:
        declared_file = package / "capabilities.json"
        if not declared_file.is_file():
            return []
        data = json.loads(declared_file.read_text(encoding="utf-8"))
        return sorted(set(str(item) for item in data) - set(manifest.capabilities))
    @staticmethod
    def _discover_undeclared_permissions(package: Path, manifest: PluginManifest) -> list[str]:
        """Reject obvious permission use omitted from the manifest.

        This is defense in depth, not an OS sandbox. Untrusted invocation stays
        disabled unless an isolation backend is configured.
        """
        required: set[str] = set()
        network_modules = {"aiohttp", "http", "httpx", "requests", "socket", "urllib"}
        process_modules = {"multiprocessing", "subprocess"}
        write_methods = {"mkdir", "rename", "replace", "rmdir", "touch", "unlink", "write_bytes", "write_text"}
        read_methods = {"glob", "iterdir", "open", "read_bytes", "read_text", "rglob", "stat"}
        for path in package.rglob("*.py"):
            if "__pycache__" in path.parts:
                continue
            try:
                tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
            except (OSError, SyntaxError, UnicodeError):
                continue
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    modules = {alias.name.split(".", 1)[0] for alias in node.names}
                    if modules & network_modules:
                        required.add("network")
                    if modules & process_modules:
                        required.add("process")
                elif isinstance(node, ast.ImportFrom) and node.module:
                    module = node.module.split(".", 1)[0]
                    if module in network_modules:
                        required.add("network")
                    if module in process_modules:
                        required.add("process")
                elif isinstance(node, ast.Call):
                    if isinstance(node.func, ast.Name) and node.func.id == "open":
                        mode = "r"
                        if len(node.args) > 1 and isinstance(node.args[1], ast.Constant):
                            mode = str(node.args[1].value)
                        for keyword in node.keywords:
                            if keyword.arg == "mode" and isinstance(keyword.value, ast.Constant):
                                mode = str(keyword.value.value)
                        required.add("filesystem.write" if any(flag in mode for flag in "wax+") else "filesystem.read")
                    elif isinstance(node.func, ast.Attribute):
                        if node.func.attr in write_methods:
                            required.add("filesystem.write")
                        elif node.func.attr in read_methods:
                            required.add("filesystem.read")
                        elif node.func.attr in {"Popen", "run", "call", "check_call", "check_output", "system"}:
                            required.add("process")
        declared = set(manifest.permissions)
        if "filesystem.write" in declared:
            declared.add("filesystem.read")
        return sorted(required - declared)
