"""Canonical Retrieval Fabric data models."""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Mapping

from nous_runtime.retrieval.errors import RetrievalValidationError
from nous_runtime.retrieval.records.hashing import hash_content

SUPPORTED_RECORD_TYPES = (
    "memory_event",
    "memory_fact",
    "memory_decision",
    "memory_summary",
    "memory_experience",
    "memory_artifact",
    "task",
    "plan",
    "observation",
    "artifact",
    "document_chunk",
    "code_symbol",
    "device_record",
)

SUPPORTED_QUERY_MODES = ("exact", "lexical", "dense", "sparse", "hybrid", "structured")


@dataclass(frozen=True)
class AccessScope:
    workspace_id: str
    project_ids: tuple[str, ...]
    principal_ids: tuple[str, ...] = ()
    visibility: str = "project"

    def __post_init__(self) -> None:
        object.__setattr__(self, "workspace_id", _required(self.workspace_id, "workspace_id"))
        object.__setattr__(self, "project_ids", _normalize_tuple(self.project_ids, "project_ids"))
        object.__setattr__(self, "principal_ids", tuple(str(v) for v in self.principal_ids if str(v)))
        if self.visibility not in {"private", "project", "workspace"}:
            raise RetrievalValidationError("visibility must be private, project, or workspace")
        if self.visibility == "private" and not self.principal_ids:
            raise RetrievalValidationError("private access scope requires at least one principal_id")

    def to_dict(self) -> dict[str, Any]:
        return {
            "workspace_id": self.workspace_id,
            "project_ids": list(self.project_ids),
            "principal_ids": list(self.principal_ids),
            "visibility": self.visibility,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "AccessScope":
        return cls(
            workspace_id=str(data.get("workspace_id") or ""),
            project_ids=tuple(str(v) for v in data.get("project_ids") or ()),
            principal_ids=tuple(str(v) for v in data.get("principal_ids") or ()),
            visibility=str(data.get("visibility") or "project"),
        )


@dataclass(frozen=True)
class RetrievalRecord:
    record_id: str
    record_type: str
    workspace_id: str
    project_id: str
    source_id: str
    source_type: str
    content: str
    content_hash: str
    access_scope: AccessScope
    title: str | None = None
    stable_key: str | None = None
    version: int = 1
    supersedes: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: dict[str, Any] = field(default_factory=dict)
    embedding_status: str = "not_required"
    index_status: str = "pending"

    def __post_init__(self) -> None:
        object.__setattr__(self, "record_id", _required(self.record_id, "record_id"))
        object.__setattr__(self, "workspace_id", _required(self.workspace_id, "workspace_id"))
        object.__setattr__(self, "project_id", _required(self.project_id, "project_id"))
        object.__setattr__(self, "source_id", _required(self.source_id, "source_id"))
        object.__setattr__(self, "source_type", _required(self.source_type, "source_type"))
        object.__setattr__(self, "content", str(self.content or ""))
        if self.record_type not in SUPPORTED_RECORD_TYPES:
            raise RetrievalValidationError(f"unsupported record_type: {self.record_type}")
        if self.content_hash != hash_content(self.content):
            raise RetrievalValidationError("content_hash does not match content")
        if self.access_scope.workspace_id != self.workspace_id:
            raise RetrievalValidationError("access_scope workspace does not match record workspace")
        if self.project_id not in self.access_scope.project_ids:
            raise RetrievalValidationError("access_scope does not include record project")
        if self.version < 1:
            raise RetrievalValidationError("version must be greater than zero")
        _ensure_json_mapping(self.metadata, "metadata")

    @property
    def active(self) -> bool:
        return self.metadata.get("active", True) is not False

    def to_dict(self) -> dict[str, Any]:
        return {
            "record_id": self.record_id,
            "record_type": self.record_type,
            "workspace_id": self.workspace_id,
            "project_id": self.project_id,
            "source_id": self.source_id,
            "source_type": self.source_type,
            "title": self.title,
            "content": self.content,
            "content_hash": self.content_hash,
            "stable_key": self.stable_key,
            "version": self.version,
            "supersedes": self.supersedes,
            "created_at": _format_datetime(self.created_at),
            "updated_at": _format_datetime(self.updated_at),
            "metadata": dict(self.metadata),
            "access_scope": self.access_scope.to_dict(),
            "embedding_status": self.embedding_status,
            "index_status": self.index_status,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "RetrievalRecord":
        created_at = _parse_datetime(data.get("created_at")) or _utc_now()
        updated_at = _parse_datetime(data.get("updated_at")) or created_at
        return cls(
            record_id=str(data.get("record_id") or ""),
            record_type=str(data.get("record_type") or ""),
            workspace_id=str(data.get("workspace_id") or ""),
            project_id=str(data.get("project_id") or ""),
            source_id=str(data.get("source_id") or ""),
            source_type=str(data.get("source_type") or ""),
            title=data.get("title") if data.get("title") is None else str(data.get("title")),
            content=str(data.get("content") or ""),
            content_hash=str(data.get("content_hash") or ""),
            stable_key=data.get("stable_key") if data.get("stable_key") is None else str(data.get("stable_key")),
            version=int(data.get("version") or 1),
            supersedes=data.get("supersedes") if data.get("supersedes") is None else str(data.get("supersedes")),
            created_at=created_at,
            updated_at=updated_at,
            metadata=dict(data.get("metadata") or {}),
            access_scope=AccessScope.from_dict(data.get("access_scope") or {}),
            embedding_status=str(data.get("embedding_status") or "not_required"),
            index_status=str(data.get("index_status") or "pending"),
        )


@dataclass(frozen=True)
class RetrievalScope:
    workspace_id: str
    project_ids: tuple[str, ...]
    organization_id: str | None = None
    principal_id: str | None = None
    device_id: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "workspace_id", _required(self.workspace_id, "workspace_id"))
        object.__setattr__(self, "project_ids", _normalize_tuple(self.project_ids, "project_ids"))


@dataclass(frozen=True)
class RetrievalFilters:
    record_types: tuple[str, ...] = ()
    source_types: tuple[str, ...] = ()
    task_ids: tuple[str, ...] = ()
    capability_ids: tuple[str, ...] = ()
    provider_ids: tuple[str, ...] = ()
    metadata_equals: dict[str, Any] = field(default_factory=dict)
    created_after: datetime | None = None
    created_before: datetime | None = None
    active_only: bool = True

    def __post_init__(self) -> None:
        for attr in ("record_types", "source_types", "task_ids", "capability_ids", "provider_ids"):
            object.__setattr__(self, attr, tuple(str(v) for v in getattr(self, attr) if str(v)))
        invalid = set(self.record_types) - set(SUPPORTED_RECORD_TYPES)
        if invalid:
            raise RetrievalValidationError(f"unsupported record_types: {sorted(invalid)}")
        _ensure_json_mapping(self.metadata_equals, "metadata_equals")


@dataclass(frozen=True)
class RetrievalQuery:
    text: str
    scope: RetrievalScope
    query_id: str = field(default_factory=lambda: f"rq_{uuid.uuid4().hex[:12]}")
    filters: RetrievalFilters = field(default_factory=RetrievalFilters)
    limit: int = 10
    mode: str = "lexical"
    include_trace: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "query_id", _required(self.query_id, "query_id"))
        object.__setattr__(self, "text", str(self.text or ""))
        if self.mode not in SUPPORTED_QUERY_MODES:
            raise RetrievalValidationError(f"unsupported retrieval mode: {self.mode}")
        if self.limit < 1 or self.limit > 1000:
            raise RetrievalValidationError("limit must be between 1 and 1000")


@dataclass(frozen=True)
class RetrievalResult:
    query_id: str
    record: RetrievalRecord
    score: float
    rank: int
    matched_text: str = ""
    source_backend: str = ""
    explanation: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "query_id", _required(self.query_id, "query_id"))
        if self.score < 0 or self.score > 1:
            raise RetrievalValidationError("score must be between 0 and 1")
        if self.rank < 1:
            raise RetrievalValidationError("rank must be greater than zero")
        _ensure_json_mapping(self.explanation, "explanation")

    def to_dict(self) -> dict[str, Any]:
        return {
            "query_id": self.query_id,
            "record": self.record.to_dict(),
            "score": self.score,
            "rank": self.rank,
            "matched_text": self.matched_text,
            "source_backend": self.source_backend,
            "explanation": dict(self.explanation),
        }


def _required(value: str, field_name: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise RetrievalValidationError(f"{field_name} is required")
    return text


def _normalize_tuple(values: tuple[str, ...] | list[str], field_name: str) -> tuple[str, ...]:
    normalized = tuple(str(v).strip() for v in values if str(v).strip())
    if not normalized:
        raise RetrievalValidationError(f"{field_name} is required")
    return normalized


def _ensure_json_mapping(value: Mapping[str, Any], field_name: str) -> None:
    try:
        json.dumps(dict(value), ensure_ascii=False)
    except (TypeError, ValueError) as exc:
        raise RetrievalValidationError(f"{field_name} must be JSON serializable") from exc


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _format_datetime(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _parse_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if not value:
        return None
    text = str(value)
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)
