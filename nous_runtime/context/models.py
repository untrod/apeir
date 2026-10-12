# -*- coding: utf-8 -*-
"""Context Runtime core data models — ContextSnapshot and ContextItem.

All models are immutable frozen dataclasses. Context is a Read Model —
it aggregates data from sources of truth; it does not own them.
"""

from __future__ import annotations

import hashlib
import uuid as _uuid
from collections.abc import Mapping
from dataclasses import asdict, dataclass, field
from datetime import datetime as _dt, timezone as _tz
from typing import Any

from nous_runtime.context.schema import (
    CONTEXT_SCHEMA_VERSION,
    ContextSource,
    SnapshotStatus,
)


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
    source_type: str = ""  # ContextSource value, e.g. "memory"
    source_id: str = ""  # Id in the owning system (memory_id, project_id, …)
    created_at: str = ""
    importance: float = 0.5  # 0.0 – 1.0
    confidence: float = 0.5  # 0.0 – 1.0
    permission: str = "read"  # read, restricted, private
    item_id: str = ""
    schema_version: str = CONTEXT_SCHEMA_VERSION
    tags: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if isinstance(self.created_at, _dt):
            created_at = self.created_at
            if created_at.tzinfo is None:
                created_at = created_at.replace(tzinfo=_tz.utc)
            object.__setattr__(
                self,
                "created_at",
                created_at.astimezone(_tz.utc).isoformat().replace("+00:00", "Z"),
            )
        if not self.item_id:
            object.__setattr__(self, "item_id", f"ctx_{_uuid.uuid4().hex[:12]}")
        if not self.created_at:
            object.__setattr__(
                self, "created_at", _dt.now(_tz.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            )
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
            errors.append(
                f"source_type '{self.source_type}' is not a valid ContextSource"
            )
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

    @property
    def source_version_key(self) -> str:
        """Scope explicit file/source versions, or fallback per-item content hashes."""
        if self.metadata.get("source_version") or self.metadata.get("file_sha256"):
            return f"{self.source_type}:{self.source_id or self.item_id}"
        return f"{self.source_type}:item:{self.item_id}"

    @property
    def source_version(self) -> str:
        for name in ("source_version", "file_sha256", "original_content_sha256"):
            value = self.metadata.get(name)
            if value:
                return value if isinstance(value, str) else ""
        return ""

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
    sources: tuple[str, ...] = ()  # ContextSource values that contributed
    confidence: float = 0.0  # Aggregate confidence across items
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if not self.id:
            object.__setattr__(self, "id", f"snap_{_uuid.uuid4().hex[:16]}")
        if not self.timestamp:
            object.__setattr__(
                self, "timestamp", _dt.now(_tz.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            )
        object.__setattr__(
            self, "confidence", max(0.0, min(1.0, float(self.confidence)))
        )

    # computed properties

    @property
    def item_count(self) -> int:
        return len(self.items)

    @property
    def source_count(self) -> int:
        return len(self.sources)

    def checksum(self) -> str:
        """Bind ordered content, source versions, permissions and read identity."""
        return hashlib.sha256(_json_bytes(asdict(self))).hexdigest()

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
            "checksum_version": 2,
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
        for k in ("item_count", "checksum", "checksum_version"):
            d.pop(k, None)
        fields_attr = cls.__dataclass_fields__
        if callable(fields_attr):
            fields_attr = fields_attr()
        known = {f.name for f in fields_attr.values()}
        return cls(
            items=items, sources=sources, **{k: v for k, v in d.items() if k in known}
        )

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
        context_binding: Mapping[str, Any] | None = None,
        source_versions: Mapping[str, str] | None = None,
    ) -> "ContextSnapshot":
        """Patch a read model after current identity and source revalidation.

        Binding/version claims do not grant access. Delivery still requires the
        canonical ContextGuard. Unbound historical snapshots are generic data.
        """
        binding = self.metadata.get("context_binding")
        if binding is not None and (
            not isinstance(binding, Mapping)
            or not isinstance(context_binding, Mapping)
            or dict(binding) != dict(context_binding)
        ):
            from nous_runtime.context.exceptions import ContextPermissionError

            raise ContextPermissionError(
                "Incremental context identity, workspace or permissions changed"
            )
        removed = set(remove_item_ids)
        invalid_ids = set(invalidate_source_ids)
        invalid_types = set(invalidate_source_types)
        if binding is not None:
            if not isinstance(source_versions, Mapping):
                from nous_runtime.context.exceptions import ContextPermissionError

                raise ContextPermissionError(
                    "Incremental context needs current source versions"
                )
            for item in self.items:
                identity = item.source_version_key
                version = item.source_version
                if not version or source_versions.get(identity) != version:
                    removed.add(item.item_id)
        updates: dict[str, ContextItem] = {}
        for item in upsert:
            errors = item.validate()
            if errors:
                raise ValueError(f"Invalid context patch item {item.item_id}: {errors}")
            if (
                binding is not None
                and source_versions is not None
                and (
                    not item.source_version
                    or source_versions.get(item.source_version_key)
                    != item.source_version
                )
            ):
                raise ValueError("Context patch source version is missing or stale")
            original_digest = item.metadata.get("original_content_sha256")
            if (
                original_digest
                and original_digest
                != hashlib.sha256(item.content.encode("utf-8")).hexdigest()
            ):
                raise ValueError(
                    "Context patch content does not match source provenance"
                )
            updates[item.item_id] = item
        items: dict[str, ContextItem] = {}
        for item in self.items:
            if item.item_id in updates:
                # Source replacement occupies its existing source position.
                items[item.item_id] = updates.pop(item.item_id)
            elif (
                item.item_id not in removed
                and item.source_id not in invalid_ids
                and item.source_type not in invalid_types
            ):
                items[item.item_id] = item
        items.update(updates)
        ordered = tuple(items.values())
        project = dict(self.project)
        project.pop("summary", None)
        agent = dict(self.agent)
        agent.pop("agents", None)
        device = dict(self.device)
        device.pop("devices", None)
        for item in ordered:
            if (
                item.source_type == ContextSource.PROJECT.value
                and "project" in item.content.lower()
            ):
                project["summary"] = item.content
            elif item.source_type == ContextSource.AGENT.value:
                agent.setdefault("agents", []).append(item.content)
            elif item.source_type == ContextSource.DEVICE.value:
                device.setdefault("devices", []).append(item.content)
        confidence = (
            sum(item.confidence for item in ordered) / len(ordered) if ordered else 0.0
        )
        return ContextSnapshot(
            version=self.version + 1,
            status=SnapshotStatus.ACTIVE.value,
            schema_version=self.schema_version,
            user=dict(self.user),
            project=project,
            task=dict(self.task),
            agent=agent,
            device=device,
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
                "patch_removals": len(
                    {item.item_id for item in self.items} - set(items)
                ),
                "source_versions": {
                    item.source_version_key: item.source_version for item in ordered
                },
                "selection_required": True,
                "execution_authority": False,
            },
        )


def _json_bytes(value: Any) -> bytes:
    import json

    return json.dumps(
        value, sort_keys=True, ensure_ascii=False, separators=(",", ":")
    ).encode("utf-8")
