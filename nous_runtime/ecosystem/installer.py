# -*- coding: utf-8 -*-
"""Capability Installer — install capabilities from local or marketplace."""

from __future__ import annotations

import logging
import subprocess
from typing import Any

from nous_runtime.ecosystem.manifest import CapabilityManifest
from nous_runtime.ecosystem.registry import CapabilityRegistry

_log = logging.getLogger("nous.ecosystem.installer")


class CapabilityInstaller:
    """Installs capabilities and their dependencies.

    Usage::

        installer = CapabilityInstaller()
        installer.install_from_manifest(manifest)
    """

    def __init__(
        self,
        registry: CapabilityRegistry | None = None,
        workspace: str = "",
        *,
        allow_dependency_install: bool = False,
    ):
        self._registry = registry or CapabilityRegistry(workspace)
        self._workspace = workspace
        self._allow_dependency_install = allow_dependency_install

    def install_from_manifest(self, manifest: CapabilityManifest) -> bool:
        """Install a capability from its manifest."""
        # Validate
        if not manifest.name or not manifest.version:
            _log.error("Invalid manifest: missing name or version")
            return False

        # Check dependencies
        missing = self._check_requirements(manifest)
        if missing:
            _log.error("Missing requirements for %s: %s", manifest.name, missing)
            return False

        if manifest.python_dependencies:
            if not self._allow_dependency_install:
                _log.error(
                    "Dependency installation for %s requires explicit authorization",
                    manifest.name,
                )
                return False
            if not self._install_python_deps(manifest.python_dependencies):
                return False

        # Register
        return self._registry.install(manifest)

    def install_from_dict(self, data: dict[str, Any]) -> bool:
        """Install from a dict manifest."""
        return self.install_from_manifest(CapabilityManifest.from_dict(data))

    def uninstall(self, name: str) -> bool:
        return self._registry.remove(name)

    def is_installed(self, name: str) -> bool:
        return self._registry.get(name) is not None

    def list_installed(self) -> list[CapabilityManifest]:
        return self._registry.list()



    @staticmethod
    def _check_requirements(manifest: CapabilityManifest) -> list[str]:
        """Check system requirements."""
        missing: list[str] = []
        for req in manifest.requirements:
            # Check if the requirement is available (basic check)
            if req in ("cuda",):
                try:
                    subprocess.run(["nvcc", "--version"], capture_output=True, timeout=5)
                except Exception:
                    missing.append(req)
            elif req in ("git", "python", "pip", "docker"):
                try:
                    subprocess.run([req, "--version"], capture_output=True, timeout=5)
                except Exception:
                    missing.append(req)
        return missing

    @staticmethod
    def _install_python_deps(deps: tuple[str, ...]) -> bool:
        """Install Python dependencies via pip."""
        if not deps:
            return True
        try:
            result = subprocess.run(
                ["pip", "install", *deps],
                capture_output=True, text=True, timeout=300,
            )
            return result.returncode == 0
        except Exception as exc:
            _log.error("Failed to install Python deps: %s", exc)
            return False
