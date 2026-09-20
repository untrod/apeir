"""Optional Qdrant backend adapter.

This module has no hard dependency on qdrant-client. It becomes operational
only when the package is installed and an explicit client or URL is provided.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from typing import Any

from nous_runtime.retrieval.errors import RetrievalBackendError
from nous_runtime.retrieval.models import RetrievalRecord, RetrievalScope
from nous_runtime.retrieval.protocol import (
    BackendHealth,
    BackendSearchRequest,
    BackendSearchResult,
    BackendWriteResult,
    IndexSpec,
    IndexVerification,
    RetrievalBackendManifest,
)


@dataclass(frozen=True)
class QdrantCollectionSpec:
    collection_name: str
    generation_id: str
    dense_vector_name: str
    sparse_vector_name: str = ""
    dimension: int = 0
    distance_metric: str = "cosine"
    payload_indexes: tuple[str, ...] = (
        "record_id",
        "generation_id",
        "workspace_id",
        "project_id",
        "record_type",
        "source_type",
        "stable_key",
        "active",
        "content_hash",
        "created_at",
    )
    sharding_policy: str = "default"
    replication_factor: int = 1
    on_disk: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "collection_name": self.collection_name,
            "generation_id": self.generation_id,
            "dense_vector_name": self.dense_vector_name,
            "sparse_vector_name": self.sparse_vector_name,
            "dimension": self.dimension,
            "distance_metric": self.distance_metric,
            "payload_indexes": list(self.payload_indexes),
            "sharding_policy": self.sharding_policy,
            "replication_factor": self.replication_factor,
            "on_disk": self.on_disk,
        }


@dataclass
class QdrantRetrievalBackend:
    url: str = ""
    collection_prefix: str = "nous"
    client: object | None = None
    embedding_provider: object | None = None
    collection_specs: dict[str, QdrantCollectionSpec] = field(default_factory=dict)
    write_generation_id: str = ""

    def manifest(self) -> RetrievalBackendManifest:
        return RetrievalBackendManifest(
            name="qdrant",
            version="1.0",
            supports_dense=True,
            supports_sparse=False,
            supports_lexical=False,
            supports_filters=True,
            supports_upsert=True,
            supports_delete=True,
            multi_tenant=True,
            metadata={"optional_dependency": "qdrant-client"},
        )

    def ensure_index(self, spec: IndexSpec) -> BackendWriteResult:
        client = self._client()
        if client is None:
            return BackendWriteResult(ok=False, errors=("qdrant-client is not available",))
        generation_id = str(spec.metadata.get("generation_id") or "")
        workspace_id = str(spec.metadata.get("workspace_id") or "")
        dimension = int(spec.metadata.get("dimension") or spec.metadata.get("embedding_dimension") or 0)
        if self.embedding_provider is not None:
            dimension = int(getattr(self.embedding_provider.manifest(), "dimension", dimension))
        if not generation_id:
            return BackendWriteResult(ok=False, errors=("generation_id is required",))
        if dimension < 1:
            return BackendWriteResult(ok=False, errors=("embedding dimension is required",))
        collection = build_collection_name(self.collection_prefix, workspace_id, spec.name, generation_id)
        collection_spec = QdrantCollectionSpec(
            collection_name=collection,
            generation_id=generation_id,
            dense_vector_name="content_dense",
            dimension=dimension,
            distance_metric=spec.distance_metric,
        )
        self.collection_specs[generation_id] = collection_spec
        self.write_generation_id = generation_id
        self._ensure_collection(client, collection_spec)
        return BackendWriteResult(ok=True, count=1)

    def upsert(self, records: list[RetrievalRecord], generation_id: str | None = None) -> BackendWriteResult:
        client = self._client()
        if client is None:
            return BackendWriteResult(ok=False, errors=("qdrant-client is not available",))
        provider = self.embedding_provider
        if provider is None:
            return BackendWriteResult(ok=False, errors=("embedding provider is required for Qdrant upsert",))
        gen = generation_id or self.write_generation_id
        collection = self.collection_specs.get(gen)
        if collection is None:
            return BackendWriteResult(ok=False, errors=("Qdrant collection is not initialized for generation",))
        vectors = provider.embed_documents([record.content for record in records])
        points = []
        for record, vector in zip(records, vectors, strict=True):
            points.append(
                {
                    "id": _point_id(record.record_id),
                    "vector": {collection.dense_vector_name: vector},
                    "payload": _payload(record, gen),
                }
            )
        if hasattr(client, "upsert"):
            client.upsert(collection_name=collection.collection_name, points=points)
            return BackendWriteResult(ok=True, count=len(points))
        raise RetrievalBackendError("Qdrant client does not expose upsert")

    def delete(self, record_ids: list[str], scope: RetrievalScope) -> BackendWriteResult:
        if self._client() is None:
            return BackendWriteResult(ok=False, errors=("qdrant-client is not available",))
        return BackendWriteResult(ok=False, errors=("delete by record IDs is not implemented for this Qdrant client"))

    def search(self, request: BackendSearchRequest) -> list[BackendSearchResult]:
        client = self._client()
        if client is None:
            return []
        provider = self.embedding_provider
        if provider is None:
            return []
        collection = self.collection_specs.get(request.generation_id)
        if collection is None:
            return []
        vector = provider.embed_query(request.query.text)
        query_filter = _qdrant_filter(request.generation_id, request.query.scope, request.query.filters)
        if hasattr(client, "search"):
            rows = client.search(
                collection_name=collection.collection_name,
                query_vector=(collection.dense_vector_name, vector),
                query_filter=query_filter,
                limit=request.query.limit,
            )
            return [_search_result(row) for row in rows]
        if hasattr(client, "query_points"):
            rows = client.query_points(
                collection_name=collection.collection_name,
                query=vector,
                using=collection.dense_vector_name,
                query_filter=query_filter,
                limit=request.query.limit,
            )
            points = getattr(rows, "points", rows)
            return [_search_result(row) for row in points]
        raise RetrievalBackendError("Qdrant client does not expose a supported search method")

    def health(self) -> BackendHealth:
        available = self._client() is not None
        return BackendHealth(
            ok=available,
            status="ok" if available else "unavailable",
            details={"backend": "qdrant", "dependency": "qdrant-client"},
        )

    def verify(self, spec: IndexSpec) -> IndexVerification:
        generation_id = str(spec.metadata.get("generation_id") or "")
        collection = self.collection_specs.get(generation_id)
        return IndexVerification(
            ok=self._client() is not None and collection is not None,
            indexed_records=0,
            details={"index_name": spec.name, "generation_id": generation_id, "collection": collection.collection_name if collection else ""},
        )

    def list_record_ids(self, generation_id: str, scope: RetrievalScope) -> list[str]:
        return []

    def count(self, generation_id: str, scope: RetrievalScope) -> int:
        client = self._client()
        collection = self.collection_specs.get(generation_id)
        if client is None or collection is None:
            return 0
        query_filter = _qdrant_filter(generation_id, scope, None)
        if hasattr(client, "count"):
            result = client.count(collection_name=collection.collection_name, count_filter=query_filter, exact=True)
            return int(getattr(result, "count", result if isinstance(result, int) else 0))
        return 0

    def clear_generation(self, generation_id: str) -> BackendWriteResult:
        client = self._client()
        collection = self.collection_specs.get(generation_id)
        if client is None or collection is None:
            return BackendWriteResult(ok=False, errors=("Qdrant collection is unavailable",))
        if hasattr(client, "delete_collection"):
            client.delete_collection(collection.collection_name)
            self.collection_specs.pop(generation_id, None)
            return BackendWriteResult(ok=True, count=1)
        return BackendWriteResult(ok=False, errors=("Qdrant client does not expose delete_collection",))

    def generation_exists(self, generation_id: str) -> bool:
        return generation_id in self.collection_specs

    def _client(self):
        if self.client is not None:
            return self.client
        try:
            from qdrant_client import QdrantClient
        except Exception:
            return None
        if not self.url:
            return None
        self.client = QdrantClient(url=self.url)
        return self.client

    def _ensure_collection(self, client, spec: QdrantCollectionSpec) -> None:
        if hasattr(client, "collection_exists") and client.collection_exists(spec.collection_name):
            return
        try:
            from qdrant_client import models
        except Exception:
            models = None
        if hasattr(client, "create_collection") and models is not None:
            distance = getattr(models.Distance, spec.distance_metric.upper(), models.Distance.COSINE)
            client.create_collection(
                collection_name=spec.collection_name,
                vectors_config={
                    spec.dense_vector_name: models.VectorParams(
                        size=spec.dimension,
                        distance=distance,
                        on_disk=spec.on_disk,
                    )
                },
            )


def build_collection_name(prefix: str, workspace_id: str, logical_index: str, generation_id: str) -> str:
    base = _safe_name(f"{prefix}_{workspace_id}_{logical_index}_{generation_id}")
    suffix = hashlib.sha1(base.encode("utf-8")).hexdigest()[:8]
    trimmed = base[:54].strip("_")
    return f"{trimmed}_{suffix}"


def _safe_name(value: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_]+", "_", value).strip("_").lower() or "nous_index"


def _payload(record: RetrievalRecord, generation_id: str) -> dict[str, Any]:
    data = record.to_dict()
    return {
        "record_id": record.record_id,
        "generation_id": generation_id,
        "workspace_id": record.workspace_id,
        "project_id": record.project_id,
        "record_type": record.record_type,
        "source_type": record.source_type,
        "stable_key": record.stable_key or "",
        "active": record.active,
        "content_hash": record.content_hash,
        "created_at": data["created_at"],
        "access_visibility": record.access_scope.visibility,
        "access_restricted": bool(record.access_scope.principal_ids) or record.access_scope.visibility == "private",
        "access_principal_ids": list(record.access_scope.principal_ids),
        "record": data,
        "metadata": record.metadata,
    }


def _point_id(record_id: str) -> int:
    return int(hashlib.sha1(record_id.encode("utf-8")).hexdigest()[:15], 16)


def _qdrant_filter(generation_id: str, scope: RetrievalScope, filters) -> Any:
    must = [
        _field_condition("generation_id", generation_id),
        _field_condition("workspace_id", scope.workspace_id),
        _match_any("project_id", list(scope.project_ids)),
        _acl_condition(scope),
    ]
    if filters is not None:
        if filters.active_only:
            must.append(_field_condition("active", True))
        if filters.record_types:
            must.append(_match_any("record_type", list(filters.record_types)))
        if filters.source_types:
            must.append(_match_any("source_type", list(filters.source_types)))
    try:
        from qdrant_client import models
    except Exception:
        return {"must": must}
    return models.Filter(must=must)


def _acl_condition(scope: RetrievalScope) -> Any:
    unrestricted = _field_condition("access_restricted", False)
    if not scope.principal_id:
        return unrestricted
    principal_match = _match_any("access_principal_ids", [scope.principal_id])
    try:
        from qdrant_client import models
    except Exception:
        return {"should": [unrestricted, principal_match]}
    return models.Filter(should=[unrestricted, principal_match])

def _field_condition(key: str, value: Any) -> Any:
    try:
        from qdrant_client import models
    except Exception:
        return {"key": key, "match": {"value": value}}
    return models.FieldCondition(key=key, match=models.MatchValue(value=value))


def _match_any(key: str, values: list[str]) -> Any:
    try:
        from qdrant_client import models
    except Exception:
        return {"key": key, "match": {"any": values}}
    return models.FieldCondition(key=key, match=models.MatchAny(any=values))


def _search_result(row: Any) -> BackendSearchResult:
    payload = getattr(row, "payload", {}) or (row.get("payload", {}) if isinstance(row, dict) else {})
    score = float(getattr(row, "score", row.get("score", 0.0) if isinstance(row, dict) else 0.0))
    record_data = payload.get("record")
    record = RetrievalRecord.from_dict(record_data) if isinstance(record_data, dict) else None
    return BackendSearchResult(
        record_id=str(payload.get("record_id") or ""),
        score=max(0.0, min(1.0, score)),
        raw_score=score,
        matched_text="",
        explanation={"backend": "qdrant"},
        record=record,
    )
