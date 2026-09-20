import pytest

from nous_runtime.retrieval.backends.local import LocalRetrievalBackend
from nous_runtime.retrieval.backends.persistent_local import PersistentLocalRetrievalBackend
from nous_runtime.retrieval.backends.qdrant import _payload, _qdrant_filter
from nous_runtime.retrieval.errors import RetrievalValidationError
from nous_runtime.retrieval.models import AccessScope, RetrievalQuery, RetrievalRecord, RetrievalScope
from nous_runtime.retrieval.protocol import BackendSearchRequest
from nous_runtime.retrieval.records.hashing import hash_content


def _private_record() -> RetrievalRecord:
    content = "private runtime memory"
    return RetrievalRecord(
        record_id="private-record",
        record_type="memory_fact",
        workspace_id="workspace-a",
        project_id="project-a",
        source_id="memory-private",
        source_type="memory",
        content=content,
        content_hash=hash_content(content),
        access_scope=AccessScope(
            workspace_id="workspace-a",
            project_ids=("project-a",),
            principal_ids=("user-a",),
            visibility="private",
        ),
    )


def _scope(principal_id: str | None = None) -> RetrievalScope:
    return RetrievalScope(
        workspace_id="workspace-a",
        project_ids=("project-a",),
        principal_id=principal_id,
    )


def test_private_scope_requires_principal():
    with pytest.raises(RetrievalValidationError):
        AccessScope(workspace_id="workspace-a", project_ids=("project-a",), visibility="private")


def test_local_backend_private_record_requires_matching_principal():
    backend = LocalRetrievalBackend()
    backend.upsert([_private_record()])

    def search(principal_id: str | None):
        query = RetrievalQuery(text="private", scope=_scope(principal_id))
        return backend.search(BackendSearchRequest(query=query))

    assert search(None) == []
    assert search("user-b") == []
    assert [item.record_id for item in search("user-a")] == ["private-record"]
    assert backend.delete(["private-record"], _scope()).count == 0
    assert backend.delete(["private-record"], _scope("user-a")).count == 1


def test_persistent_backend_applies_acl_to_search_list_count_and_delete(tmp_path):
    backend = PersistentLocalRetrievalBackend(tmp_path)
    backend.upsert([_private_record()], generation_id="generation-a")

    query = RetrievalQuery(text="private", scope=_scope())
    assert backend.search(BackendSearchRequest(query=query, generation_id="generation-a")) == []
    assert backend.list_record_ids("generation-a", _scope()) == []
    assert backend.count("generation-a", _scope()) == 0
    assert backend.delete(["private-record"], _scope()).count == 0

    assert backend.list_record_ids("generation-a", _scope("user-a")) == ["private-record"]
    assert backend.count("generation-a", _scope("user-a")) == 1
    assert backend.delete(["private-record"], _scope("user-a")).count == 1


def test_qdrant_payload_and_filters_preserve_acl():
    record = _private_record()
    payload = _payload(record, "generation-a")
    anonymous_filter = _qdrant_filter("generation-a", _scope(), None)
    principal_filter = _qdrant_filter("generation-a", _scope("user-a"), None)

    assert payload["access_restricted"] is True
    assert payload["access_principal_ids"] == ["user-a"]
    assert "access_restricted" in str(anonymous_filter)
    assert "access_principal_ids" in str(principal_filter)
