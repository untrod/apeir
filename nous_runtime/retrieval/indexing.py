"""Index generation models for Retrieval Fabric."""

from __future__ import annotations

import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Mapping

from nous_runtime.inspector.models import DiagnosticFinding


class IndexGenerationState(str, Enum):
    BUILDING = "building"
    SHADOW = "shadow"
    ACTIVE = "active"
    DRAINING = "draining"
    RETIRED = "retired"
    FAILED = "failed"


_TRANSITIONS: dict[IndexGenerationState, set[IndexGenerationState]] = {
    IndexGenerationState.BUILDING: {IndexGenerationState.SHADOW, IndexGenerationState.FAILED},
    IndexGenerationState.SHADOW: {IndexGenerationState.ACTIVE, IndexGenerationState.FAILED, IndexGenerationState.RETIRED},
    IndexGenerationState.ACTIVE: {IndexGenerationState.DRAINING, IndexGenerationState.RETIRED},
    IndexGenerationState.DRAINING: {IndexGenerationState.RETIRED},
    IndexGenerationState.RETIRED: set(),
    IndexGenerationState.FAILED: {IndexGenerationState.RETIRED},
}


@dataclass(frozen=True)
class LogicalIndexSpec:
    logical_index: str
    backend_id: str
    workspace_id: str
    project_id: str
    record_types: tuple[str, ...] = ()
    vector_fields: tuple[str, ...] = ("content",)
    schema_version: int = 1
    embedding_model_id: str | None = None
    dimension: int | None = None
    distance_metric: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for field_name in ("logical_index", "backend_id", "workspace_id", "project_id"):
            if not str(getattr(self, field_name) or "").strip():
                raise ValueError(f"{field_name} is required")
        if self.schema_version < 1:
            raise ValueError("schema_version must be greater than zero")
        object.__setattr__(self, "record_types", tuple(str(v) for v in self.record_types if str(v)))
        object.__setattr__(self, "vector_fields", tuple(str(v) for v in self.vector_fields if str(v)))
        object.__setattr__(self, "metadata", dict(self.metadata))

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["record_types"] = list(self.record_types)
        data["vector_fields"] = list(self.vector_fields)
        data["metadata"] = dict(self.metadata)
        return data

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "LogicalIndexSpec":
        return cls(
            logical_index=str(data.get("logical_index") or ""),
            backend_id=str(data.get("backend_id") or ""),
            workspace_id=str(data.get("workspace_id") or ""),
            project_id=str(data.get("project_id") or ""),
            record_types=tuple(str(v) for v in data.get("record_types") or ()),
            vector_fields=tuple(str(v) for v in data.get("vector_fields") or ("content",)),
            schema_version=int(data.get("schema_version") or 1),
            embedding_model_id=_optional_str(data.get("embedding_model_id")),
            dimension=_optional_int(data.get("dimension")),
            distance_metric=_optional_str(data.get("distance_metric")),
            metadata=dict(data.get("metadata") or {}),
        )


@dataclass(frozen=True)
class IndexGeneration:
    generation_id: str
    logical_index: str
    backend_id: str
    workspace_id: str
    project_id: str
    state: IndexGenerationState
    schema_version: int
    source_revision: str | None = None
    record_count: int = 0
    content_hash: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    activated_at: datetime | None = None
    retired_at: datetime | None = None
    failure_reason: str | None = None
    verified: bool = False
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def with_state(
        self,
        state: IndexGenerationState,
        *,
        failure_reason: str | None = None,
        verified: bool | None = None,
    ) -> "IndexGeneration":
        if not is_valid_transition(self.state, state):
            raise ValueError(f"invalid index generation transition: {self.state.value} -> {state.value}")
        now = datetime.now(timezone.utc)
        return IndexGeneration(
            generation_id=self.generation_id,
            logical_index=self.logical_index,
            backend_id=self.backend_id,
            workspace_id=self.workspace_id,
            project_id=self.project_id,
            state=state,
            schema_version=self.schema_version,
            source_revision=self.source_revision,
            record_count=self.record_count,
            content_hash=self.content_hash,
            created_at=self.created_at,
            activated_at=now if state == IndexGenerationState.ACTIVE else self.activated_at,
            retired_at=now if state == IndexGenerationState.RETIRED else self.retired_at,
            failure_reason=failure_reason if failure_reason is not None else self.failure_reason,
            verified=self.verified if verified is None else verified,
            metadata=dict(self.metadata),
        )

    def with_build_result(
        self,
        *,
        state: IndexGenerationState,
        record_count: int,
        content_hash: str | None,
        source_revision: str | None,
        verified: bool = False,
        failure_reason: str | None = None,
        metadata_update: Mapping[str, Any] | None = None,
    ) -> "IndexGeneration":
        if not is_valid_transition(self.state, state):
            raise ValueError(f"invalid index generation transition: {self.state.value} -> {state.value}")
        return IndexGeneration(
            generation_id=self.generation_id,
            logical_index=self.logical_index,
            backend_id=self.backend_id,
            workspace_id=self.workspace_id,
            project_id=self.project_id,
            state=state,
            schema_version=self.schema_version,
            source_revision=source_revision,
            record_count=record_count,
            content_hash=content_hash,
            created_at=self.created_at,
            activated_at=self.activated_at,
            retired_at=self.retired_at,
            failure_reason=failure_reason,
            verified=verified,
            metadata={**dict(self.metadata), **dict(metadata_update or {})},
        )

    def with_metadata(self, metadata_update: Mapping[str, Any]) -> "IndexGeneration":
        return IndexGeneration(
            generation_id=self.generation_id,
            logical_index=self.logical_index,
            backend_id=self.backend_id,
            workspace_id=self.workspace_id,
            project_id=self.project_id,
            state=self.state,
            schema_version=self.schema_version,
            source_revision=self.source_revision,
            record_count=self.record_count,
            content_hash=self.content_hash,
            created_at=self.created_at,
            activated_at=self.activated_at,
            retired_at=self.retired_at,
            failure_reason=self.failure_reason,
            verified=self.verified,
            metadata={**dict(self.metadata), **dict(metadata_update)},
        )

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["state"] = self.state.value
        data["created_at"] = _format_datetime(self.created_at)
        data["activated_at"] = _format_datetime(self.activated_at) if self.activated_at else None
        data["retired_at"] = _format_datetime(self.retired_at) if self.retired_at else None
        data["metadata"] = dict(self.metadata)
        return data

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "IndexGeneration":
        return cls(
            generation_id=str(data.get("generation_id") or ""),
            logical_index=str(data.get("logical_index") or ""),
            backend_id=str(data.get("backend_id") or ""),
            workspace_id=str(data.get("workspace_id") or ""),
            project_id=str(data.get("project_id") or ""),
            state=IndexGenerationState(str(data.get("state") or IndexGenerationState.BUILDING.value)),
            schema_version=int(data.get("schema_version") or 1),
            source_revision=_optional_str(data.get("source_revision")),
            record_count=int(data.get("record_count") or 0),
            content_hash=_optional_str(data.get("content_hash")),
            created_at=_parse_datetime(data.get("created_at")),
            activated_at=_parse_optional_datetime(data.get("activated_at")),
            retired_at=_parse_optional_datetime(data.get("retired_at")),
            failure_reason=_optional_str(data.get("failure_reason")),
            verified=bool(data.get("verified", False)),
            metadata=dict(data.get("metadata") or {}),
        )


@dataclass(frozen=True)
class ExportCursor:
    source_type: str
    last_timestamp: datetime | None = None
    last_record_id: str | None = None
    source_revision: str | None = None


@dataclass(frozen=True)
class ExportBatch:
    records: tuple[Any, ...]
    cursor: ExportCursor
    source_revision: str | None = None


@dataclass(frozen=True)
class IndexBuildOptions:
    batch_size: int = 128
    fail_fast: bool = False
    max_errors: int = 100
    verify_after_build: bool = True

    def __post_init__(self) -> None:
        if self.batch_size < 1:
            raise ValueError("batch_size must be greater than zero")
        if self.max_errors < 0:
            raise ValueError("max_errors must be zero or greater")


@dataclass(frozen=True)
class IndexBuildResult:
    generation_id: str
    exported_records: int
    indexed_records: int
    skipped_records: int
    failed_records: int
    batch_count: int
    duration_ms: float
    errors: tuple[str, ...] = ()

    @property
    def ok(self) -> bool:
        return self.failed_records == 0


@dataclass(frozen=True)
class RetrievalIndexVerification:
    generation_id: str
    valid: bool
    expected_count: int
    actual_count: int
    missing_record_ids: tuple[str, ...] = ()
    orphan_record_ids: tuple[str, ...] = ()
    duplicate_record_ids: tuple[str, ...] = ()
    hash_mismatches: tuple[str, ...] = ()
    findings: tuple[DiagnosticFinding, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "generation_id": self.generation_id,
            "valid": self.valid,
            "expected_count": self.expected_count,
            "actual_count": self.actual_count,
            "missing_record_ids": list(self.missing_record_ids),
            "orphan_record_ids": list(self.orphan_record_ids),
            "duplicate_record_ids": list(self.duplicate_record_ids),
            "hash_mismatches": list(self.hash_mismatches),
            "findings": [f.to_dict() for f in self.findings],
        }


@dataclass(frozen=True)
class BackendBinding:
    backend_resource_id: str
    backend_schema_hash: str
    embedding_model_id: str | None = None
    embedding_model_revision: str | None = None
    dimension: int | None = None
    distance_metric: str | None = None
    record_count: int = 0
    last_verified_at: datetime | None = None
    verification_hash: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "backend_resource_id": self.backend_resource_id,
            "backend_schema_hash": self.backend_schema_hash,
            "embedding_model_id": self.embedding_model_id,
            "embedding_model_revision": self.embedding_model_revision,
            "dimension": self.dimension,
            "distance_metric": self.distance_metric,
            "record_count": self.record_count,
            "last_verified_at": _format_datetime(self.last_verified_at) if self.last_verified_at else None,
            "verification_hash": self.verification_hash,
        }


class RebuildCheckpointState(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass(frozen=True)
class RebuildCheckpoint:
    generation_id: str
    state: RebuildCheckpointState
    last_processed_record_id: str = ""
    processed_batches: int = 0
    indexed_records: int = 0
    failed_records: int = 0
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["state"] = self.state.value
        data["started_at"] = _format_datetime(self.started_at)
        data["updated_at"] = _format_datetime(self.updated_at)
        return data


def new_generation_id() -> str:
    return f"gen_{uuid.uuid4().hex[:12]}"


def is_valid_transition(current: IndexGenerationState, new: IndexGenerationState) -> bool:
    return current == new or new in _TRANSITIONS[current]


def _format_datetime(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _parse_datetime(value: Any) -> datetime:
    parsed = _parse_optional_datetime(value)
    return parsed or datetime.now(timezone.utc)


def _parse_optional_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    else:
        text = str(value or "")
        if not text:
            return None
        if text.endswith("Z"):
            text = f"{text[:-1]}+00:00"
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _optional_str(value: Any) -> str | None:
    if value in ("", None):
        return None
    return str(value)


def _optional_int(value: Any) -> int | None:
    if value in ("", None):
        return None
    return int(value)
