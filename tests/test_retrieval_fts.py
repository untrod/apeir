from nous_runtime.retrieval.backends.persistent_local import PersistentLocalRetrievalBackend
from nous_runtime.retrieval.models import AccessScope, RetrievalQuery, RetrievalRecord, RetrievalScope
from nous_runtime.retrieval.protocol import BackendSearchRequest
from nous_runtime.retrieval.records.hashing import hash_content


def _record(record_id: str, content: str, project_id: str = "project-a") -> RetrievalRecord:
    return RetrievalRecord(
        record_id=record_id,
        record_type="document_chunk",
        workspace_id="workspace-a",
        project_id=project_id,
        source_id=f"source-{record_id}",
        source_type="test",
        content=content,
        content_hash=hash_content(content),
        access_scope=AccessScope(workspace_id="workspace-a", project_ids=(project_id,)),
    )


def _request(text: str, generation_id: str = "generation-a") -> BackendSearchRequest:
    query = RetrievalQuery(
        text=text,
        scope=RetrievalScope(workspace_id="workspace-a", project_ids=("project-a",)),
    )
    return BackendSearchRequest(query=query, generation_id=generation_id)


def test_fts_search_preserves_generation_and_project_scope(tmp_path):
    backend = PersistentLocalRetrievalBackend(tmp_path)
    backend.upsert([_record("active", "needle current")], generation_id="generation-a")
    backend.upsert([_record("retired", "needle retired")], generation_id="generation-b")
    backend.upsert([_record("other-project", "needle private", "project-b")], generation_id="generation-a")

    results = backend.search(_request("needle"))

    assert backend._fts_available is True
    assert [result.record_id for result in results] == ["active"]
    assert results[0].record.content == "needle current"


def test_non_ascii_query_uses_substring_candidate_search(tmp_path):
    backend = PersistentLocalRetrievalBackend(tmp_path)
    backend.upsert([_record("chinese", "中文技术文档 runtime")], generation_id="generation-a")

    results = backend.search(_request("中文 技术 文档"))

    assert [result.record_id for result in results] == ["chinese"]

def test_fts_index_tracks_delete_and_clear_generation(tmp_path):
    backend = PersistentLocalRetrievalBackend(tmp_path)
    backend.upsert([_record("first", "needle first"), _record("second", "needle second")], generation_id="generation-a")
    scope = RetrievalScope(workspace_id="workspace-a", project_ids=("project-a",))

    assert backend.delete(["first"], scope).count == 1
    assert [result.record_id for result in backend.search(_request("needle"))] == ["second"]
    assert backend.clear_generation("generation-a").count == 1
    assert backend.search(_request("needle")) == []


def test_fts_upsert_replaces_existing_record_without_duplicate(tmp_path):
    backend = PersistentLocalRetrievalBackend(tmp_path)
    backend.upsert([_record("same", "old value")], generation_id="generation-a")
    backend.upsert([_record("same", "new needle value")], generation_id="generation-a")

    results = backend.search(_request("needle"))

    assert [result.record_id for result in results] == ["same"]
    assert results[0].record.content == "new needle value"

def test_fts_unavailable_falls_back_to_lexical_scan(tmp_path):
    backend = PersistentLocalRetrievalBackend(tmp_path)
    backend.upsert([_record("first", "fallback needle")], generation_id="generation-a")
    backend._fts_available = False

    results = backend.search(_request("needle"))

    assert [result.record_id for result in results] == ["first"]
