from __future__ import annotations

from nous_runtime.retrieval.gateway import RetrievalGateway
from nous_runtime.retrieval.models import (
    AccessScope,
    RetrievalQuery,
    RetrievalRecord,
    RetrievalScope,
)
from nous_runtime.retrieval.protocol import (
    BackendSearchResult,
    RetrievalBackendManifest,
)
from nous_runtime.retrieval.records.hashing import hash_content
from nous_runtime.retrieval.registry import RetrievalBackendRegistry


def _record(
    record_id,
    content,
    *,
    workspace="workspace-a",
    project="project-a",
    principals=(),
):
    return RetrievalRecord(
        record_id=record_id,
        record_type="memory_fact",
        workspace_id=workspace,
        project_id=project,
        source_id=f"source-{record_id}",
        source_type="memory",
        content=content,
        content_hash=hash_content(content),
        access_scope=AccessScope(
            workspace_id=workspace,
            project_ids=(project,),
            principal_ids=principals,
            visibility="private" if principals else "workspace",
        ),
        metadata={"citation": {"page": 1}},
    )


class LeakyLexicalBackend:
    def __init__(self, results):
        self.results = results
        self.last_request = None

    def manifest(self):
        return RetrievalBackendManifest(
            name="leaky",
            version="1",
            supports_dense=False,
            supports_lexical=True,
        )

    def search(self, request):
        self.last_request = request
        return self.results


def test_gateway_isolation_or_recall_dedup_generation_and_explanation():
    first = _record("one", "duplicate content")
    duplicate = _record("two", "duplicate content")
    project_b = _record(
        "project-b",
        "project b result",
        project="project-b",
    )
    wrong_workspace = _record(
        "wrong-workspace",
        "must not leak",
        workspace="workspace-b",
    )
    wrong_principal = _record(
        "wrong-principal",
        "must not leak",
        principals=("user-b",),
    )
    wrong_generation = _record("old", "old generation")
    records = [
        BackendSearchResult(
            record_id=first.record_id,
            record=first,
            score=0.9,
            raw_score=9,
        ),
        BackendSearchResult(
            record_id=duplicate.record_id,
            record=duplicate,
            score=0.8,
            raw_score=8,
        ),
        BackendSearchResult(
            record_id=project_b.record_id,
            record=project_b,
            score=0.7,
            raw_score=7,
        ),
        BackendSearchResult(
            record_id=wrong_workspace.record_id,
            record=wrong_workspace,
            score=0.6,
        ),
        BackendSearchResult(
            record_id=wrong_principal.record_id,
            record=wrong_principal,
            score=0.6,
        ),
        BackendSearchResult(
            record_id=wrong_generation.record_id,
            record=wrong_generation,
            score=0.6,
            explanation={"generation_id": "old"},
        ),
    ]
    backend = LeakyLexicalBackend(records)
    registry = RetrievalBackendRegistry()
    registry.register(backend, "leaky")
    gateway = RetrievalGateway(
        backend_registry=registry,
        default_backend="leaky",
    )
    query = RetrievalQuery(
        text="result",
        mode="dense",
        scope=RetrievalScope(
            workspace_id="workspace-a",
            project_ids=("project-a", "project-b"),
            principal_id="user-a",
        ),
    )

    results = gateway.search(query, generation_id="active")

    assert [result.record.record_id for result in results] == [
        "one",
        "project-b",
    ]
    assert backend.last_request.query.mode == "lexical"
    assert backend.last_request.generation_id == "active"
    assert results[0].explanation["degraded_from_mode"] == "dense"
    assert results[0].explanation["duplicate_chunks_suppressed"] == 1
    assert results[0].explanation["citation"]["source_id"] == "source-one"
    assert results[0].explanation["project_ids"] == [
        "project-a",
        "project-b",
    ]
