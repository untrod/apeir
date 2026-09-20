"""Pack service facade used by public runtime surfaces."""

from __future__ import annotations

from typing import Any


def list_packs() -> list[dict[str, Any]]:
    """List installed packs."""
    from nous_runtime.pack.registry import registry

    return registry.list()


def install_pack(path: str) -> dict[str, Any]:
    """Install a pack and return public metadata."""
    from nous_runtime.pack.registry import registry

    pack = registry.install(path)
    return {"name": pack.manifest.name, "version": pack.manifest.version}


def remove_pack(name: str) -> None:
    """Remove an installed pack."""
    from nous_runtime.pack.registry import registry

    registry.remove(name)


def count_packs() -> int:
    """Return installed pack count."""
    from nous_runtime.pack.registry import registry

    return registry.count()

