# -*- coding: utf-8 -*-
"""ContextProvider — abstract interface all providers must implement."""

from __future__ import annotations

import logging
from typing import Protocol, runtime_checkable

from nous_runtime.context.models import ContextItem
from nous_runtime.context.types import ProviderHealth

_log = logging.getLogger("nous.context.provider")


@runtime_checkable
class ContextProvider(Protocol):
    """Interface for all context providers.

    Each provider reads from ONE source of truth and returns ContextItems.
    Providers MUST NOT mutate the underlying data.
    """

    source_type: str  # Must match a ContextSource value

    def collect(self, request_hint: str = "", limit: int = 100) -> list[ContextItem]:
        """Collect context items from this provider's source.

        Args:
            request_hint: Free-text hint about what context is needed (e.g. "continue project X").
            limit: Maximum number of items to return.

        Returns:
            List of ContextItem objects. Empty list if source is unavailable.
        """
        ...

    def explain(self, item_ids: list[str]) -> dict[str, str]:
        """Return human-readable explanations for specific items.

        Args:
            item_ids: List of ContextItem.item_id values to explain.

        Returns:
            Dict mapping item_id → explanation string.
        """
        ...

    def health(self) -> ProviderHealth:
        """Return health status of this provider."""
        ...
