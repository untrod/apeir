"""Read-only retrieval gateway built on backend contracts."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any

from nous_runtime.retrieval.filters import record_matches_filters, record_matches_scope
from nous_runtime.retrieval.models import RetrievalQuery, RetrievalResult
from nous_runtime.retrieval.protocol import BackendSearchRequest
from nous_runtime.retrieval.registry import RetrievalBackendRegistry, registry
from nous_runtime.retrieval.store import IndexGenerationStore


@dataclass
class RetrievalGateway:
    backend_registry: RetrievalBackendRegistry = field(default_factory=lambda: registry)
    default_backend: str = "local"
    generation_store: IndexGenerationStore | None = None
    logical_index: str = "memory"

    def search(
        self,
        query: RetrievalQuery,
        backend_name: str | None = None,
        *,
        generation_id: str = "",
    ) -> list[RetrievalResult]:
        resolved_backend, resolved_generation = self._resolve_generation(query, backend_name, generation_id)
        backend = self.backend_registry.resolve(resolved_backend)
        manifest = backend.manifest()
        effective_query = query
        degraded_mode = ""
        if query.mode in {"dense", "hybrid"} and not manifest.supports_dense:
            if not manifest.supports_lexical:
                return []
            effective_query = replace(query, mode="lexical")
            degraded_mode = "lexical"
        backend_results = backend.search(
            BackendSearchRequest(
                query=effective_query,
                generation_id=resolved_generation,
                trace={
                    "workspace_id": query.scope.workspace_id,
                    "project_ids": list(query.scope.project_ids),
                    "principal_id": query.scope.principal_id or "",
                },
            )
        )
        records: dict[str, Any] | None = None
        candidates: list[tuple[Any, Any]] = []
        seen: set[str] = set()
        duplicates = 0
        for item in backend_results:
            record = item.record
            if record is None:
                if records is None:
                    candidate_records = getattr(backend, "records", {})
                    records = candidate_records if isinstance(candidate_records, dict) else {}
                record = records.get(item.record_id)
            if record is None:
                continue
            if not record_matches_scope(record, query.scope):
                continue
            if not record_matches_filters(record, query.filters):
                continue
            item_generation = str(item.explanation.get("generation_id") or "")
            if (
                resolved_generation
                and item_generation
                and item_generation != resolved_generation
            ):
                continue
            dedup_key = str(record.content_hash or record.record_id)
            if dedup_key in seen:
                duplicates += 1
                continue
            seen.add(dedup_key)
            candidates.append((item, record))

        results: list[RetrievalResult] = []
        for rank, (item, record) in enumerate(
            candidates[: query.limit], start=1
        ):
            explanation = _explanation(item.explanation, item.raw_score)
            explanation.update(
                {
                    "backend": manifest.name,
                    "generation_id": resolved_generation,
                    "workspace_id": query.scope.workspace_id,
                    "project_ids": list(query.scope.project_ids),
                    "principal_id": query.scope.principal_id or "",
                    "query_mode": effective_query.mode,
                    "degraded_from_mode": query.mode if degraded_mode else "",
                    "duplicate_chunks_suppressed": duplicates,
                    "citation": {
                        "record_id": record.record_id,
                        "source_id": record.source_id,
                        "source_type": record.source_type,
                        "metadata": record.metadata.get("citation")
                        or record.metadata.get("citations")
                        or {},
                    },
                }
            )
            results.append(
                RetrievalResult(
                    query_id=query.query_id,
                    record=record,
                    score=item.score,
                    rank=rank,
                    matched_text=item.matched_text,
                    source_backend=manifest.name,
                    explanation=explanation,
                )
            )
        return results

    def _resolve_generation(
        self,
        query: RetrievalQuery,
        backend_name: str | None,
        generation_id: str,
    ) -> tuple[str, str]:
        if generation_id or self.generation_store is None or len(query.scope.project_ids) != 1:
            return backend_name or self.default_backend, generation_id
        active = self.generation_store.active(
            self.logical_index,
            query.scope.workspace_id,
            query.scope.project_ids[0],
        )
        if active is None:
            return backend_name or self.default_backend, ""
        return backend_name or active.backend_id, active.generation_id


def _explanation(explanation: dict[str, Any], raw_score: float) -> dict[str, Any]:
    data = dict(explanation)
    data.setdefault("raw_score", raw_score)
    return data
