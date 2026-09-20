# -*- coding: utf-8 -*-
"""Context Runtime supporting types — lightweight dataclasses for transport."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class BuildRequest:
    """A request to build context for a specific intent."""

    intent: str = ""
    user_id: str = ""
    project_id: str = ""
    task_id: str = ""
    agent_id: str = ""
    device_id: str = ""
    max_items: int = 100
    sources: tuple[str, ...] = ()
    context_hint: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ContextScore:
    """Decomposed score for a single context item during resolution."""

    item_id: str = ""
    relevance: float = 0.0
    freshness: float = 0.0
    confidence: float = 0.0
    importance: float = 0.0
    composite: float = 0.0
    explanation: str = ""

    def __post_init__(self):
        # Clamp all scores to [0, 1]
        for name in ("relevance", "freshness", "confidence", "importance", "composite"):
            clamped = max(0.0, min(1.0, float(getattr(self, name))))
            if clamped != getattr(self, name):
                object.__setattr__(self, name, clamped)


@dataclass(frozen=True)
class RankedContext:
    """A context item with its rank and score."""

    item_id: str = ""
    source_type: str = ""
    content_summary: str = ""
    score: ContextScore = field(default_factory=lambda: ContextScore())
    rank: int = 0
    selected: bool = False
    selection_reason: str = ""


@dataclass(frozen=True)
class ContextExplanation:
    """Explainable output from context resolution."""

    selected_items: list[RankedContext] = field(default_factory=list)
    discarded_items: list[RankedContext] = field(default_factory=list)
    selection_summary: str = ""
    confidence: float = 0.0
    reasoning: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "selected_items": [r.__dict__ for r in self.selected_items],
            "discarded_items": [r.__dict__ for r in self.discarded_items],
            "selection_summary": self.selection_summary,
            "confidence": self.confidence,
            "reasoning": list(self.reasoning),
        }


@dataclass(frozen=True)
class ProviderHealth:
    """Health status of a single context provider."""

    source: str = ""
    available: bool = False
    item_count: int = 0
    last_collected_at: str = ""
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "available": self.available,
            "item_count": self.item_count,
            "last_collected_at": self.last_collected_at,
            "error": self.error,
        }


@dataclass(frozen=True)
class SnapshotMetadata:
    """Metadata attached to a stored snapshot."""

    checksum: str = ""
    compression: str = "none"  # none, gzip
    item_count: int = 0
    source_counts: dict[str, int] = field(default_factory=dict)
    build_duration_ms: int = 0
    schema_version: str = "1.0.0"

    def to_dict(self) -> dict[str, Any]:
        return {
            "checksum": self.checksum,
            "compression": self.compression,
            "item_count": self.item_count,
            "source_counts": dict(self.source_counts),
            "build_duration_ms": self.build_duration_ms,
            "schema_version": self.schema_version,
        }


@dataclass(frozen=True)
class RestoreResult:
    """Result of a snapshot restore operation."""

    snapshot_id: str = ""
    success: bool = False
    restored_items: int = 0
    missing_sources: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    duration_ms: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "snapshot_id": self.snapshot_id,
            "success": self.success,
            "restored_items": self.restored_items,
            "missing_sources": list(self.missing_sources),
            "errors": list(self.errors),
            "duration_ms": self.duration_ms,
        }
