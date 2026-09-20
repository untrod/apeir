"""In-memory reference backend for the Retrieval Fabric contract."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from nous_runtime.retrieval.filters import record_matches_filters, record_matches_scope
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


@dataclass
class LocalRetrievalBackend:
    records: dict[str, RetrievalRecord] = field(default_factory=dict)
    generation_records: dict[str, set[str]] = field(default_factory=dict)
    indexes: dict[str, IndexSpec] = field(default_factory=dict)
    write_generation_id: str = ""

    def manifest(self) -> RetrievalBackendManifest:
        return RetrievalBackendManifest(
            name="local",
            version="1.0",
            supports_dense=False,
            supports_sparse=False,
            supports_lexical=True,
            supports_filters=True,
            supports_upsert=True,
            supports_delete=True,
            multi_tenant=True,
            metadata={"storage": "memory", "reference": True},
        )

    def ensure_index(self, spec: IndexSpec) -> BackendWriteResult:
        self.indexes[spec.name] = spec
        self.write_generation_id = str(spec.metadata.get("generation_id") or self.write_generation_id)
        return BackendWriteResult(ok=True, count=1)

    def upsert(self, records: list[RetrievalRecord], generation_id: str | None = None) -> BackendWriteResult:
        gen = generation_id or self.write_generation_id
        for record in records:
            self.records[record.record_id] = record
            if gen:
                self.generation_records.setdefault(gen, set()).add(record.record_id)
        return BackendWriteResult(ok=True, count=len(records))

    def delete(self, record_ids: list[str], scope: RetrievalScope) -> BackendWriteResult:
        count = 0
        for record_id in record_ids:
            record = self.records.get(record_id)
            if record is None or not record_matches_scope(record, scope):
                continue
            del self.records[record_id]
            count += 1
        return BackendWriteResult(ok=True, count=count)

    def search(self, request: BackendSearchRequest) -> list[BackendSearchResult]:
        query = request.query
        terms = _terms(query.text)
        allowed_ids = self.generation_records.get(request.generation_id) if request.generation_id else None
        superseded_source_ids = {r.supersedes for r in self.records.values() if r.supersedes}
        scored: list[tuple[float, RetrievalRecord, dict[str, float]]] = []
        for record_id, record in self.records.items():
            if allowed_ids is not None and record_id not in allowed_ids:
                continue
            if not record_matches_scope(record, query.scope):
                continue
            if not record_matches_filters(record, query.filters, superseded_source_ids):
                continue
            score, explanation = _score_record(record, query.text, terms)
            if score <= 0 and query.text:
                continue
            scored.append((score, record, explanation))

        scored.sort(key=lambda item: (-item[0], item[1].updated_at, item[1].record_id))
        return [
            BackendSearchResult(
                record_id=record.record_id,
                score=min(1.0, score),
                raw_score=score,
                matched_text=_snippet(record, query.text),
                explanation=explanation,
                record=record,
            )
            for score, record, explanation in scored[: query.limit]
        ]

    def health(self) -> BackendHealth:
        return BackendHealth(ok=True, details={"records": len(self.records), "indexes": len(self.indexes)})

    def verify(self, spec: IndexSpec) -> IndexVerification:
        generation_id = str(spec.metadata.get("generation_id") or "")
        indexed_records = self.count(
            generation_id,
            RetrievalScope(
                workspace_id=str(spec.metadata.get("workspace_id") or ""),
                project_ids=(str(spec.metadata.get("project_id") or ""),),
            ),
        ) if generation_id and spec.metadata.get("workspace_id") and spec.metadata.get("project_id") else len(self.records)
        return IndexVerification(
            ok=spec.name in self.indexes,
            indexed_records=indexed_records,
            details={"index_name": spec.name, "backend": "local"},
        )

    def list_record_ids(self, generation_id: str, scope: RetrievalScope) -> list[str]:
        ids = self.generation_records.get(generation_id, set()) if generation_id else set(self.records)
        return sorted(
            record_id for record_id in ids
            if record_id in self.records and record_matches_scope(self.records[record_id], scope)
        )

    def count(self, generation_id: str, scope: RetrievalScope) -> int:
        return len(self.list_record_ids(generation_id, scope))

    def clear_generation(self, generation_id: str) -> BackendWriteResult:
        ids = self.generation_records.pop(generation_id, set())
        for record_id in ids:
            self.records.pop(record_id, None)
        return BackendWriteResult(ok=True, count=len(ids))

    def generation_exists(self, generation_id: str) -> bool:
        return bool(self.generation_records.get(generation_id))


def _score_record(record: RetrievalRecord, text: str, terms: list[str]) -> tuple[float, dict[str, float]]:
    query = text.lower().strip()
    haystack = f"{record.title or ''}\n{record.content}".lower()
    explanation: dict[str, float] = {}
    score = 0.0

    if not query:
        explanation["empty_query"] = 0.1
        return 0.1, explanation
    if query in {record.record_id.lower(), (record.stable_key or "").lower(), record.source_id.lower()}:
        explanation["exact_identifier"] = 1.0
        return 1.0, explanation
    if record.title and query in record.title.lower():
        score += 0.85
        explanation["title_phrase"] = 0.85
    if query in record.content.lower():
        score += 0.75
        explanation["content_phrase"] = 0.75
    if terms:
        matched = sum(1 for term in terms if term in haystack)
        coverage = matched / len(terms)
        token_score = coverage * 0.7
        score += token_score
        explanation["token_coverage"] = round(token_score, 4)
    if record.stable_key and query in record.stable_key.lower():
        score += 0.2
        explanation["stable_key"] = 0.2
    return min(1.0, score), explanation


def _terms(text: str) -> list[str]:
    return [term for term in re.split(r"\W+", text.lower()) if term]


def _snippet(record: RetrievalRecord, query: str) -> str:
    content = record.content
    if not query:
        return content[:160]
    pos = content.lower().find(query.lower())
    if pos < 0:
        return content[:160]
    start = max(0, pos - 48)
    end = min(len(content), pos + len(query) + 80)
    return content[start:end]
