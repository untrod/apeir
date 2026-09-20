# -*- coding: utf-8 -*-
"""Context Runtime core data models — ContextSnapshot and ContextItem.

All models are immutable frozen dataclasses. Context is a Read Model —
it aggregates data from sources of truth; it does not own them.
"""

from __future__ import annotations

import hashlib
import uuid as _uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime as _dt, timezone as _tz
from typing import Any

from nous_runtime.context.schema import CONTEXT_SCHEMA_VERSION, ContextSource, SnapshotStatus



# ContextItem — the unified context unit


@dataclass(frozen=True)
class ContextItem:
    """A single unit of context from one source.

    Every context item MUST carry:
      - A source_type (ContextSource enum value) so its origin is always known.
      - A confidence score [0.0 – 1.0].
      - A permission tag for governance enforcement.
    """

    content: str = ""
    source_type: str = ""          # ContextSource value, e.g. "memory"
    source_id: str = ""             # Id in the owning system (memory_id, project_id, …)
    created_at: str = ""
    importance: float = 0.5         # 0.0 – 1.0
    confidence: float = 0.5         # 0.0 – 1.0
    permission: str = "read"        # read, restricted, private
    item_id: str = ""
    schema_version: str = CONTEXT_SCHEMA_VERSION
    tags: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if not self.item_id:
            object.__setattr__(self, "item_id", f"ctx_{_uuid.uuid4().hex[:12]}")
        if not self.created_at:
            object.__setattr__(self, "created_at", _dt.now(_tz.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))
        # Clamp
        for name in ("importance", "confidence"):
            clamped = max(0.0, min(1.0, float(getattr(self, name))))
            if clamped != getattr(self, name):
                object.__setattr__(self, name, clamped)

    def validate(self) -> list[str]:
        """Validate required fields. Returns list of error messages (empty = valid)."""
        errors: list[str] = []
        if not self.item_id:
            errors.append("item_id is required")
        if not self.source_type:
            errors.append("source_type is required")
        if self.source_type not in {s.value for s in ContextSource}:
            errors.append(f"source_type '{self.source_type}' is not a valid ContextSource")
        if not self.content:
            errors.append("content is required")
        if self.importance < 0 or self.importance > 1:
            errors.append("importance must be 0.0–1.0")
        if self.confidence < 0 or self.confidence > 1:
            errors.append("confidence must be 0.0–1.0")
        if self.permission not in ("read", "restricted", "private"):
            errors.append("permission must be read|restricted|private")
        return errors

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["tags"] = list(self.tags)
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ContextItem":
        d = dict(data)
        d["tags"] = tuple(d.get("tags") or ())
        d["metadata"] = d.get("metadata") or {}
        # Drop keys not in the constructor
        known = {f.name for f in cls.__dataclass_fields__.values()}
        return cls(**{k: v for k, v in d.items() if k in known})



# ContextSnapshot — immutable aggregate of context items


@dataclass(frozen=True)
class ContextSnapshot:
    """An immutable snapshot of contextual state at a point in time.

    Aggregates context items from multiple sources into one read-only
    structure.  The snapshot is what builders produce and resolvers consume.
    """

    id: str = ""
    version: int = 1
    timestamp: str = ""
    status: str = SnapshotStatus.ACTIVE.value
    schema_version: str = CONTEXT_SCHEMA_VERSION

    # Source-aligned sections (read from, not owned by, upstream modules)
    user: dict[str, Any] = field(default_factory=dict)
    project: dict[str, Any] = field(default_factory=dict)
    task: dict[str, Any] = field(default_factory=dict)
    agent: dict[str, Any] = field(default_factory=dict)
    device: dict[str, Any] = field(default_factory=dict)
    memory: list[dict[str, Any]] = field(default_factory=list)
    decision: list[dict[str, Any]] = field(default_factory=list)
    retrieval: list[dict[str, Any]] = field(default_factory=list)
    experience: list[dict[str, Any]] = field(default_factory=list)
    runtime: dict[str, Any] = field(default_factory=dict)

    # Aggregated context items
    items: tuple[ContextItem, ...] = ()

    # Provenance
    sources: tuple[str, ...] = ()            # ContextSource values that contributed
    confidence: float = 0.0                   # Aggregate confidence across items
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if not self.id:
            object.__setattr__(self, "id", f"snap_{_uuid.uuid4().hex[:16]}")
        if not self.timestamp:
            object.__setattr__(self, "timestamp", _dt.now(_tz.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))
        object.__setattr__(self, "confidence", max(0.0, min(1.0, float(self.confidence))))

    # computed properties

    @property
    def item_count(self) -> int:
        return len(self.items)

    @property
    def source_count(self) -> int:
        return len(self.sources)

    def checksum(self) -> str:
        """Deterministic SHA-256 checksum of snapshot content."""
        h = hashlib.sha256()
        h.update(self.id.encode())
        h.update(str(self.version).encode())
        h.update(self.timestamp.encode())
        h.update(str(sorted(self.sources)).encode())
        for item in sorted(self.items, key=lambda i: i.item_id):
            h.update(item.item_id.encode())
            h.update(item.content.encode())
            h.update(item.source_type.encode())
        return h.hexdigest()

    # serialization

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "version": self.version,
            "timestamp": self.timestamp,
            "status": self.status,
            "schema_version": self.schema_version,
            "user": dict(self.user),
            "project": dict(self.project),
            "task": dict(self.task),
            "agent": dict(self.agent),
            "device": dict(self.device),
            "memory": list(self.memory),
            "decision": list(self.decision),
            "retrieval": list(self.retrieval),
            "experience": list(self.experience),
            "runtime": dict(self.runtime),
            "items": [i.to_dict() for i in self.items],
            "sources": list(self.sources),
            "confidence": self.confidence,
            "metadata": dict(self.metadata),
            "item_count": self.item_count,
            "checksum": self.checksum(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ContextSnapshot":
        d = dict(data)
        # Restore items
        raw_items = d.pop("items", [])
        items = tuple(ContextItem.from_dict(i) for i in raw_items)
        # Restore sources
        sources = tuple(d.pop("sources", []))
        # Drop computed keys
        for k in ("item_count", "checksum"):
            d.pop(k, None)
        fields_attr = cls.__dataclass_fields__
        if callable(fields_attr):
            fields_attr = fields_attr()
        known = {f.name for f in fields_attr.values()}
        return cls(items=items, sources=sources, **{k: v for k, v in d.items() if k in known})

    # mutation (returns new instance — immutable)

    def with_status(self, status: SnapshotStatus) -> "ContextSnapshot":
        """Return a new snapshot with updated status."""
        return ContextSnapshot(
            id=self.id,
            version=self.version,
            timestamp=self.timestamp,
            status=status.value,
            schema_version=self.schema_version,
            user=dict(self.user),
            project=dict(self.project),
            task=dict(self.task),
            agent=dict(self.agent),
            device=dict(self.device),
            memory=list(self.memory),
            decision=list(self.decision),
            retrieval=list(self.retrieval),
            experience=list(self.experience),
            runtime=dict(self.runtime),
            items=self.items,
            sources=self.sources,
            confidence=self.confidence,
            metadata=dict(self.metadata),
        )

    def apply_patch(
        self,
        *,
        upsert: tuple[ContextItem, ...] = (),
        remove_item_ids: tuple[str, ...] = (),
        invalidate_source_ids: tuple[str, ...] = (),
        invalidate_source_types: tuple[str, ...] = (),
    ) -> "ContextSnapshot":
        """Create an immutable incremental snapshot with precise invalidation."""
        removed = set(remove_item_ids)
        invalid_ids = set(invalidate_source_ids)
        invalid_types = set(invalidate_source_types)
        items = {
            item.item_id: item
            for item in self.items
            if item.item_id not in removed
            and item.source_id not in invalid_ids
            and item.source_type not in invalid_types
        }
        for item in upsert:
            errors = item.validate()
            if errors:
                raise ValueError(
                    f"Invalid context patch item {item.item_id}: {errors}"
                )
            items[item.item_id] = item
        ordered = tuple(
            sorted(items.values(), key=lambda item: item.item_id)
        )
        confidence = (
            sum(item.confidence for item in ordered) / len(ordered)
            if ordered else 0.0
        )
        return ContextSnapshot(
            version=self.version + 1,
            status=SnapshotStatus.ACTIVE.value,
            schema_version=self.schema_version,
            user=dict(self.user),
            project=dict(self.project),
            task=dict(self.task),
            agent=dict(self.agent),
            device=dict(self.device),
            memory=[
                item.to_dict()
                for item in ordered
                if item.source_type == ContextSource.MEMORY.value
            ],
            decision=[
                item.to_dict()
                for item in ordered
                if item.source_type == ContextSource.DECISION.value
            ],
            retrieval=[
                item.to_dict()
                for item in ordered
                if item.source_type == ContextSource.RETRIEVAL.value
            ],
            experience=[
                item.to_dict()
                for item in ordered
                if item.source_type == ContextSource.EXPERIENCE.value
            ],
            runtime=dict(self.runtime),
            items=ordered,
            sources=tuple(sorted({item.source_type for item in ordered})),
            confidence=confidence,
            metadata={
                **self.metadata,
                "base_snapshot_id": self.id,
                "base_checksum": self.checksum(),
                "patch_upserts": len(upsert),
                "patch_removals": len(self.items) + len(upsert) - len(ordered),
            },
        )
