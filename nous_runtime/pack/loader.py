# -*- coding: utf-8 -*-
"""
Pack Loader -loads a pack from a directory using importlib.

A pack is a directory containing:
    pack.yaml          -manifest (required)
    __init__.py        -optional; if present, its register() function is called
    *.py               -arbitrary modules that the pack needs

Loading a pack:
    1. Parse pack.yaml ->PackManifest
    2. Check dependencies against installed packs
    3. Import the pack's Python module (if __init__.py exists)
    4. Call pack.register() if defined
    5. Register declared capabilities and providers
"""

from __future__ import annotations

import importlib.util
import logging
import os
import sys
from dataclasses import dataclass, field
from typing import Any

from nous_runtime.pack.manifest import PackManifest

log = logging.getLogger("nous.pack.loader")


@dataclass
class Pack:
    """A loaded pack instance."""

    manifest: PackManifest
    path: str
    module: Any = None          # The loaded Python module (if __init__.py exists)
    enabled: bool = True
    registered_capabilities: list[str] = field(default_factory=list)
    registered_providers: list[str] = field(default_factory=list)


def load_pack(pack_dir: str) -> Pack:
    """
    Load a pack from a directory.

    Args:
        pack_dir: Path to the pack directory.

    Returns:
        A loaded Pack instance.

    Raises:
        FileNotFoundError: If pack.yaml not found.
        ValueError: If manifest is invalid.
        ImportError: If the pack's Python module fails to import.
    """
    pack_dir = os.path.abspath(pack_dir)
    manifest = PackManifest.from_file(pack_dir)

    pack = Pack(manifest=manifest, path=pack_dir)

    # Load Python module if __init__.py exists
    init_path = os.path.join(pack_dir, "__init__.py")
    if os.path.isfile(init_path):
        module_name = f"nous_pack_{manifest.name}"
        try:
            spec = importlib.util.spec_from_file_location(module_name, init_path)
            if spec and spec.loader:
                module = importlib.util.module_from_spec(spec)
                sys.modules[module_name] = module
                spec.loader.exec_module(module)
                pack.module = module

                # Call register() if defined
                if hasattr(module, "register"):
                    module.register(pack)
                    log.info("Pack '%s' register() called", manifest.name)

        except Exception as e:
            log.error("Failed to load pack '%s': %s", manifest.name, e)
            raise ImportError(f"Failed to load pack '{manifest.name}': {e}") from e

    log.info("Pack loaded: %s v%s (%s)", manifest.name, manifest.version, pack_dir)
    return pack


def register_pack_capabilities(pack: Pack) -> list[str]:
    """
    Register a pack's declared capabilities with the Capability OS.

    Returns:
        List of registered capability IDs.

    Raises:
        RuntimeError: If any capability fails to register (partial registration rolled back).
    """
    registered = []
    try:
        from nous_runtime.compat.capability import register_capability
        for cap_id in pack.manifest.capabilities:
            cid = register_capability(
                name=cap_id,
                category="pack",
                provider=pack.manifest.name,
                description=f"Provided by {pack.manifest.name} v{pack.manifest.version}",
                risk="low",
            )
            registered.append(cid)
        pack.registered_capabilities = registered
        log.info("Pack '%s': %d capabilities registered", pack.manifest.name, len(registered))
    except Exception as e:
        log.error("Capability registration for pack '%s' failed: %s", pack.manifest.name, e)
        # Don't leave partial registrations -the pack install will be rolled back
        raise RuntimeError(
            f"Failed to register capabilities for '{pack.manifest.name}': {e}"
        ) from e
    return registered


def unregister_pack_capabilities(pack: Pack) -> None:
    """Remove a pack's capabilities from the Capability OS database.

    Uses ``unregister_capabilities_by_provider`` so that every
    capability whose *provider* column matches the pack name is
    deleted, not just those the pack declared at install time.
    """
    try:
        # Import lazily to avoid circular import issues at module level
        from nous_runtime.compat.capability import (
            unregister_capabilities_by_provider,
        )
        removed = unregister_capabilities_by_provider(pack.manifest.name)
        pack.registered_capabilities = []
        if removed:
            log.info(
                "Pack '%s': %d capability/capabilities unregistered",
                pack.manifest.name, removed,
            )
    except Exception as e:
        log.error(
            "Failed to unregister capabilities for pack '%s': %s",
            pack.manifest.name, e,
        )
        raise RuntimeError(
            f"Failed to unregister capabilities for '{pack.manifest.name}': {e}"
        ) from e
