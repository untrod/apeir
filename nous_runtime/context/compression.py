# -*- coding: utf-8 -*-
"""Context Compression — three-tier system for managing context volume.

Tiers:
  Active Context   — currently in use, full fidelity.
  Project Context  — summarized, still accessible.
  Archive Context  — compressed to facts/experiences, audit only.

Transformation chain:
  Events → Summary → Facts → Experience
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from enum import Enum
from typing import Any

from nous_runtime.context.models import ContextItem, ContextSnapshot

_log = logging.getLogger("nous.context.compression")



# Tier


class CompressionTier(str, Enum):
    ACTIVE = "active"      # Full fidelity — everything retained
    PROJECT = "project"    # Summarised — key details only
    ARCHIVE = "archive"    # Compressed — facts and audit trail


TIER_LIMITS: dict[CompressionTier, int] = {
    CompressionTier.ACTIVE: 500,
    CompressionTier.PROJECT: 2000,
    CompressionTier.ARCHIVE: 10000,
}



# Compressed item


@dataclass(frozen=True)
class CompressedItem:
    """A compressed form of a context item."""
    summary: str = ""
    source_type: str = ""
    original_ids: tuple[str, ...] = ()
    compression_level: str = "summary"  # summary, fact, experience
    created_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "summary": self.summary,
            "source_type": self.source_type,
            "original_ids": list(self.original_ids),
            "compression_level": self.compression_level,
            "created_at": self.created_at,
        }



# Compressor


class ContextCompressor:
    """Three-tier context compressor.

    Usage::

        compressor = ContextCompressor()
        compressed = compressor.compress(items, tier=CompressionTier.PROJECT)
    """

    def __init__(self, limits: dict[CompressionTier, int] | None = None):
        self._limits = limits or dict(TIER_LIMITS)



    def compress(
        self,
        items: list[ContextItem],
        tier: CompressionTier = CompressionTier.PROJECT,
    ) -> list[CompressedItem]:
        """Compress context items to the specified tier.

        Args:
            items: Context items to compress.
            tier: Target compression tier.

        Returns:
            List of CompressedItem objects.
        """
        if tier == CompressionTier.ACTIVE:
            # No compression — wrap each item as-is
            return [
                CompressedItem(
                    summary=item.content,
                    source_type=item.source_type,
                    original_ids=(item.item_id,),
                    compression_level="summary",
                    created_at=item.created_at,
                )
                for item in items[: self._limits[tier]]
            ]

        if tier == CompressionTier.PROJECT:
            return self._compress_project(items)

        if tier == CompressionTier.ARCHIVE:
            return self._compress_archive(items)

        return []



    def _compress_project(self, items: list[ContextItem]) -> list[CompressedItem]:
        """Project-tier compression: group by source, summarise key items."""
        # Group items by source_type
        groups: dict[str, list[ContextItem]] = {}
        for item in items:
            groups.setdefault(item.source_type, []).append(item)

        compressed: list[CompressedItem] = []

        for source, group in groups.items():
            # Summarize each group
            if len(group) <= 3:
                # Small groups — keep as-is but mark as summary level
                for item in group:
                    compressed.append(CompressedItem(
                        summary=item.content,
                        source_type=source,
                        original_ids=(item.item_id,),
                        compression_level="summary",
                        created_at=item.created_at,
                    ))
            else:
                # Large groups — summarize
                summary = self._summarise_group(source, group)
                compressed.append(CompressedItem(
                    summary=summary,
                    source_type=source,
                    original_ids=tuple(i.item_id for i in group),
                    compression_level="fact",
                    created_at=group[0].created_at if group else "",
                ))

        return compressed[: self._limits[CompressionTier.PROJECT]]

    def _compress_archive(self, items: list[ContextItem]) -> list[CompressedItem]:
        """Archive-tier compression: maximum reduction."""
        groups: dict[str, list[ContextItem]] = {}
        for item in items:
            groups.setdefault(item.source_type, []).append(item)

        compressed: list[CompressedItem] = []

        for source, group in groups.items():
            # Archive — one summary per source
            summary = self._summarise_group(source, group)
            compressed.append(CompressedItem(
                summary=summary,
                source_type=source,
                original_ids=tuple(i.item_id for i in group),
                compression_level="experience",
                created_at=group[0].created_at if group else "",
            ))

        return compressed[: self._limits[CompressionTier.ARCHIVE]]



    @staticmethod
    def _summarise_group(source: str, items: list[ContextItem]) -> str:
        """Produce a human-readable summary of a group of context items."""
        if not items:
            return f"[{source}] (empty)"

        n = len(items)
        # Extract key topics from item contents
        topics = set()
        for item in items[:20]:  # Sample first 20 for topic extraction
            words = item.content.lower().split()
            for w in words:
                if len(w) > 4 and w not in ("context", "items", "source", "about"):
                    topics.add(w)

        top_topics = sorted(topics)[:5]
        topic_str = ", ".join(top_topics) if top_topics else "various"

        return f"[{source}] {n} items about: {topic_str}"


    # Stability check


    def compression_checksum(self, compressed: list[CompressedItem]) -> str:
        """Deterministic checksum of compressed items for integrity verification."""
        h = hashlib.sha256()
        for ci in sorted(compressed, key=lambda c: c.summary):
            h.update(ci.summary.encode())
            h.update(ci.source_type.encode())
            h.update(ci.compression_level.encode())
        return h.hexdigest()



# Convenience


def compress_context(
    snapshot: ContextSnapshot,
    tier: CompressionTier = CompressionTier.PROJECT,
) -> list[CompressedItem]:
    """Compress a snapshot's items to the given tier."""
    compressor = ContextCompressor()
    return compressor.compress(list(snapshot.items), tier=tier)
