# -*- coding: utf-8 -*-
"""Marketplace Registry — capability search and discovery."""

from __future__ import annotations

import logging
from typing import Any

from nous_runtime.ecosystem.registry import CapabilityRegistry

_log = logging.getLogger("nous.marketplace")


class MarketplaceRegistry:
    """Search and browse capabilities in the marketplace.

    Usage:
        market = MarketplaceRegistry()
        results = market.search("computer vision")
        market.install("yolo.detect")
    """

    def __init__(self, registry: CapabilityRegistry | None = None):
        self._local = registry or CapabilityRegistry()

    def search(self, query: str, category: str = "") -> list[dict[str, Any]]:
        """Search installed capabilities."""
        all_caps = self._local.list(category=category, limit=100)
        query_lower = query.lower()
        results = []
        for cap in all_caps:
            text = f"{cap.name} {cap.description} {cap.category}".lower()
            if not query or query_lower in text:
                results.append({
                    "name": cap.name, "version": cap.version,
                    "description": cap.description, "category": cap.category,
                    "risk_level": cap.risk_level, "trust": cap.trust,
                    "author": cap.author,
                })
        return results

    def install(self, name: str) -> bool:
        """Install a capability by name (from local registry)."""
        cap = self._local.get(name)
        if cap is None:
            _log.warning("Capability not found: %s", name)
            return False
        return True  # Already installed

    def uninstall(self, name: str) -> bool:
        return self._local.remove(name)

    def list_categories(self) -> list[str]:
        caps = self._local.list(limit=500)
        cats = {c.category for c in caps if c.category}
        return sorted(cats)
