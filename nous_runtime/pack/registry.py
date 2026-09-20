# -*- coding: utf-8 -*-
"""
Pack Registry — SQLite-backed registry for installed packs.

Provides: install, remove, list, enable, disable.
"""

from __future__ import annotations

import logging
import os
from typing import Any

from nous_runtime.pack.manifest import PackManifest
from nous_runtime.pack.loader import Pack, load_pack, register_pack_capabilities, unregister_pack_capabilities

log = logging.getLogger("nous.pack.registry")

# Default pack installation directory
DEFAULT_PACK_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))), "packs")


PACK_REGISTRY_FILE = os.path.join(
    os.environ.get("NOUS_HOME", os.path.join(os.path.expanduser("~"), ".nous")),
    "pack_registry.json",
)


def _registry_file() -> str:
    """Return the configured registry path at operation time.

    Reading the override lazily lets isolated workers and CLI subprocesses use
    independent registries without changing the production default.
    """
    return os.environ.get("NOUS_PACK_REGISTRY_FILE", PACK_REGISTRY_FILE)


class PackRegistry:
    """
    Registry for installed packs. Persists to JSON file.

    Usage:
        reg = PackRegistry()
        reg.install("/path/to/my_pack")
        for pack in reg.list():
            print(pack.manifest.name, pack.manifest.version)
        reg.remove("my_pack")
    """

    def __init__(self, pack_dir: str | None = None):
        self._packs: dict[str, Pack] = {}
        self._pack_dir = pack_dir or DEFAULT_PACK_DIR
        self._load()

    # install

    def install(self, pack_path: str) -> Pack:
        """
        Install a pack from a directory path. Atomic: rolls back on failure.

        Args:
            pack_path: Path to the pack directory.

        Returns:
            The loaded Pack instance.

        Raises:
            FileNotFoundError: If pack.yaml not found.
            ValueError: If manifest invalid or already installed.
            RuntimeError: If capability registration fails.
        """
        manifest = PackManifest.from_file(pack_path)
        if manifest.name in self._packs:
            raise ValueError(f"Pack '{manifest.name}' is already installed. Remove it first.")

        pack = load_pack(pack_path)
        try:
            register_pack_capabilities(pack)
        except Exception:
            # Rollback: remove pack from memory, don't save
            log.error("Pack install rolled back: %s", manifest.name)
            raise

        self._packs[manifest.name] = pack
        self._save()
        log.info("Pack installed: %s v%s", manifest.name, manifest.version)
        return pack

    # remove

    def remove(self, name: str) -> None:
        """
        Remove an installed pack.

        Args:
            name: Pack name.

        Raises:
            KeyError: If pack not installed.
        """
        if name not in self._packs:
            raise KeyError(f"Pack '{name}' is not installed")
        pack = self._packs[name]
        unregister_pack_capabilities(pack)
        del self._packs[name]
        self._save()
        log.info("Pack removed: %s", name)

    # list

    def list(self) -> list[dict[str, Any]]:
        """List all installed packs."""
        return [
            {
                "name": p.manifest.name,
                "version": p.manifest.version,
                "description": p.manifest.description,
                "enabled": p.enabled,
                "capabilities": p.registered_capabilities,
                "path": p.path,
            }
            for p in self._packs.values()
        ]

    # enable / disable

    def enable(self, name: str) -> None:
        """Enable a disabled pack."""
        if name not in self._packs:
            raise KeyError(f"Pack '{name}' is not installed")
        self._packs[name].enabled = True
        log.info("Pack enabled: %s", name)

    def disable(self, name: str) -> None:
        """Disable a pack without uninstalling it."""
        if name not in self._packs:
            raise KeyError(f"Pack '{name}' is not installed")
        self._packs[name].enabled = False
        log.info("Pack disabled: %s", name)

    def get(self, name: str) -> dict[str, Any] | None:
        """Get details of an installed pack."""
        pack = self._packs.get(name)
        if not pack:
            return None
        return {
            "name": pack.manifest.name,
            "version": pack.manifest.version,
            "description": pack.manifest.description,
            "enabled": pack.enabled,
            "capabilities": pack.registered_capabilities,
            "dependencies": pack.manifest.dependencies,
            "config": pack.manifest.config,
        }

    def count(self) -> int:
        return len(self._packs)

    # persistence

    def _save(self) -> None:
        """Persist registry to JSON file."""
        import json as _json
        try:
            registry_file = _registry_file()
            os.makedirs(os.path.dirname(registry_file), exist_ok=True)
            data = {
                name: {
                    "name": p.manifest.name,
                    "version": p.manifest.version,
                    "description": p.manifest.description,
                    "path": p.path,
                    "enabled": p.enabled,
                }
                for name, p in self._packs.items()
            }
            tmp = registry_file + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                _json.dump(data, f, indent=2)
            os.replace(tmp, registry_file)
        except Exception as e:
            log.warning("Failed to save pack registry: %s", e)

    def _load(self) -> None:
        """Load registry from JSON file."""
        import json as _json
        try:
            registry_file = _registry_file()
            if os.path.isfile(registry_file):
                with open(registry_file, encoding="utf-8") as f:
                    data = _json.load(f)
                for name, info in data.items():
                    path = info.get("path", "")
                    if os.path.isdir(path):
                        try:
                            pack = load_pack(path)
                            register_pack_capabilities(pack)
                            pack.enabled = info.get("enabled", True)
                            self._packs[name] = pack
                        except Exception as e:
                            log.warning("Failed to reload pack '%s': %s", name, e)
        except Exception as e:
            log.warning("Failed to load pack registry: %s", e)


# Module-level singleton
registry = PackRegistry()
