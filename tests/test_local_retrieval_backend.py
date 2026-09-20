from nous_runtime.retrieval.backends.local import LocalRetrievalBackend
from nous_runtime.retrieval.gateway import RetrievalGateway
from nous_runtime.retrieval.models import AccessScope, RetrievalFilters, RetrievalQuery, RetrievalRecord, RetrievalScope
from nous_runtime.retrieval.records.hashing import hash_content
from nous_runtime.retrieval.registry import RetrievalBackendRegistry


def _record(
    record_id: str,
    content: str,
    project_id: str = "project_a",
    workspace_id: str = "workspace_a",
    source_id: str | None = None,
    supersedes: str | None = None,
    active: bool = True,
) -> RetrievalRecord:
    source = source_id or record_id.replace("retr_", "mem_")
    return RetrievalRecord(
        record_id=record_id,
        record_type="memory_fact",
        workspace_id=workspace_id,
        project_id=project_id,
        source_id=source,
        source_type="memory",
        title="project.files.total",
        content=content,
        content_hash=hash_content(content),
        stable_key="project.files.total",
        supersedes=supersedes,
        metadata={"active": active},
        access_scope=AccessScope(workspace_id=workspace_id, project_ids=(project_id,)),
    )


def test_local_backend_searches_lexically_with_scope_isolation():
    backend = LocalRetrievalBackend()
    backend.upsert(
        [
            _record("retr_a", "project.files.total: 12"),
            _record("retr_b", "project.files.total: 99", project_id="project_b"),
        ]
    )

    query = RetrievalQuery(
        text="files",
        scope=RetrievalScope(workspace_id="workspace_a", project_ids=("project_a",)),
    )
    results = backend.search(request=_request(query))

    assert [result.record_id for result in results] == ["retr_a"]


def test_local_backend_excludes_superseded_and_inactive_records_by_default():
    backend = LocalRetrievalBackend()
    old = _record("retr_old", "project.files.total: 10", source_id="mem_old")
    new = _record("retr_new", "project.files.total: 12", source_id="mem_new", supersedes="mem_old")
    inactive = _record("retr_inactive", "project.files.total: 14", source_id="mem_inactive", active=False)
    backend.upsert([old, new, inactive])

    query = RetrievalQuery(
        text="project.files.total",
        scope=RetrievalScope(workspace_id="workspace_a", project_ids=("project_a",)),
    )
    results = backend.search(_request(query))

    assert [result.record_id for result in results] == ["retr_new"]


def test_local_backend_allows_historical_records_when_requested():
    backend = LocalRetrievalBackend()
    old = _record("retr_old", "project.files.total: 10", source_id="mem_old")
    new = _record("retr_new", "project.files.total: 12", source_id="mem_new", supersedes="mem_old")
    backend.upsert([old, new])

    query = RetrievalQuery(
        text="project.files.total",
        scope=RetrievalScope(workspace_id="workspace_a", project_ids=("project_a",)),
        filters=RetrievalFilters(active_only=False),
    )

    assert {result.record_id for result in backend.search(_request(query))} == {"retr_old", "retr_new"}


def test_gateway_wraps_backend_results_as_canonical_results():
    registry = RetrievalBackendRegistry()
    backend = LocalRetrievalBackend()
    backend.upsert([_record("retr_a", "python project memory")])
    registry.register(backend)

    gateway = RetrievalGateway(backend_registry=registry)
    results = gateway.search(
        RetrievalQuery(
            text="python",
            scope=RetrievalScope(workspace_id="workspace_a", project_ids=("project_a",)),
        )
    )

    assert results[0].record.record_id == "retr_a"
    assert results[0].source_backend == "local"
    assert results[0].score > 0


def _request(query: RetrievalQuery):
    from nous_runtime.retrieval.protocol import BackendSearchRequest

    return BackendSearchRequest(query=query)
