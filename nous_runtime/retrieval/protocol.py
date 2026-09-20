"""Retrieval backend protocol and transport-neutral payloads."""

from __future__ import annotations

from dataclasses import dataclass, field
from collections.abc import Sequence
from typing import Any, Protocol

from nous_runtime.retrieval.models import RetrievalQuery, RetrievalRecord, RetrievalScope


@dataclass(frozen=True)
class RetrievalBackendManifest:
    name: str
    version: str
    supports_dense: bool = False
    supports_sparse: bool = False
    supports_lexical: bool = True
    supports_filters: bool = True
    supports_upsert: bool = True
    supports_delete: bool = True
    multi_tenant: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class IndexSpec:
    name: str
    record_types: tuple[str, ...] = ()
    embedding_model: str = ""
    distance_metric: str = "cosine"
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class BackendWriteResult:
    ok: bool
    count: int = 0
    errors: tuple[str, ...] = ()


@dataclass(frozen=True)
class BackendSearchRequest:
    query: RetrievalQuery
    index_name: str = "default"
    generation_id: str = ""
    trace: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class BackendSearchResult:
    record_id: str
    score: float
    matched_text: str = ""
    raw_score: float = 0.0
    explanation: dict[str, Any] = field(default_factory=dict)
    record: RetrievalRecord | None = None


@dataclass(frozen=True)
class BackendHealth:
    ok: bool
    status: str = "ok"
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class IndexVerification:
    ok: bool
    indexed_records: int = 0
    stale_records: int = 0
    missing_records: int = 0
    details: dict[str, Any] = field(default_factory=dict)


class RetrievalBackend(Protocol):
    def manifest(self) -> RetrievalBackendManifest:
        ...

    def ensure_index(self, spec: IndexSpec) -> BackendWriteResult:
        ...

    def upsert(self, records: list[RetrievalRecord], generation_id: str | None = None) -> BackendWriteResult:
        ...

    def delete(self, record_ids: list[str], scope: RetrievalScope) -> BackendWriteResult:
        ...

    def search(self, request: BackendSearchRequest) -> list[BackendSearchResult]:
        ...

    def health(self) -> BackendHealth:
        ...

    def verify(self, spec: IndexSpec) -> IndexVerification:
        ...

    def list_record_ids(self, generation_id: str, scope: RetrievalScope) -> Sequence[str]:
        ...

    def count(self, generation_id: str, scope: RetrievalScope) -> int:
        ...

    def clear_generation(self, generation_id: str) -> BackendWriteResult:
        ...

    def generation_exists(self, generation_id: str) -> bool:
        ...
