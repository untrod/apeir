from nous_runtime.retrieval.backends.persistent_local import PersistentLocalRetrievalBackend
from nous_runtime.retrieval.backends.qdrant import _payload, _search_result
from nous_runtime.retrieval.gateway import RetrievalGateway
from nous_runtime.retrieval.indexing import IndexGeneration, IndexGenerationState
from nous_runtime.retrieval.models import AccessScope, RetrievalQuery, RetrievalRecord, RetrievalScope
from nous_runtime.retrieval.records.hashing import hash_content
from nous_runtime.retrieval.registry import RetrievalBackendRegistry


def _record(content: str) -> RetrievalRecord:
    return RetrievalRecord(
        record_id="shared-record",
        record_type="memory_fact",
        workspace_id="workspace-a",
        project_id="project-a",
        source_id="source-a",
        source_type="memory",
        content=content,
        content_hash=hash_content(content),
        access_scope=AccessScope(workspace_id="workspace-a", project_ids=("project-a",)),
    )


class _GenerationStore:
    def __init__(self, active: IndexGeneration):
        self._active = active

    def active(self, logical_index, workspace_id, project_id):
        if (logical_index, workspace_id, project_id) == ("memory", "workspace-a", "project-a"):
            return self._active
        return None


def test_gateway_uses_active_generation_and_direct_backend_record(tmp_path):
    backend = PersistentLocalRetrievalBackend(tmp_path)
    backend.upsert([_record("old generation content")], generation_id="old")
    backend.upsert([_record("new generation content")], generation_id="active")
    registry = RetrievalBackendRegistry()
    registry.register(backend, name="local")
    active = IndexGeneration(
        generation_id="active",
        logical_index="memory",
        backend_id="local",
        workspace_id="workspace-a",
        project_id="project-a",
        state=IndexGenerationState.ACTIVE,
        schema_version="1",
    )
    gateway = RetrievalGateway(backend_registry=registry, generation_store=_GenerationStore(active))
    query = RetrievalQuery(
        text="generation",
        scope=RetrievalScope(workspace_id="workspace-a", project_ids=("project-a",)),
    )

    results = gateway.search(query)

    assert len(results) == 1
    assert results[0].record.content == "new generation content"


def test_qdrant_search_result_carries_canonical_record():
    record = _record("qdrant result content")
    row = {"payload": _payload(record, "active"), "score": 0.91}

    result = _search_result(row)

    assert result.record == record
    assert result.record_id == record.record_id
