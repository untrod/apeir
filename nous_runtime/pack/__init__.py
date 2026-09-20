# -*- coding: utf-8 -*-
"""
Pack System — installable domain knowledge modules.

A Pack bundles capabilities, providers, knowledge data, and configuration
into a single installable unit. The Runtime never contains domain knowledge;
all domain knowledge is provided by Packs.

Usage:
    from nous_runtime.pack import PackRegistry
    reg = PackRegistry()
    reg.install("packs/examples/study_pack")
    reg.list()
"""

from __future__ import annotations

from nous_runtime.pack.manifest import PackManifest
from nous_runtime.pack.loader import Pack, load_pack
from nous_runtime.pack.registry import PackRegistry, registry

__all__ = [
    "PackManifest",
    "Pack",
    "load_pack",
    "PackRegistry",
    "registry",
]
