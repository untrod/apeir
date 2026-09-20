from nous_runtime.retrieval.backends.qdrant import QdrantRetrievalBackend
from nous_runtime.retrieval.embeddings import HashEmbeddingProvider, embedding_registry
from nous_runtime.retrieval.evaluation import RetrievalEvalCase, evaluate_cases
from nous_runtime.retrieval.gateway import RetrievalGateway
from nous_runtime.retrieval.hybrid import HybridRetrievalEngine
from nous_runtime.retrieval.jobs import IndexingJobState, JsonlIndexingOutbox
from nous_runtime.retrieval.models import AccessScope, RetrievalQuery, RetrievalRecord, RetrievalScope
from nous_runtime.retrieval.ranking import pack_context
from nous_runtime.retrieval.records.hashing import hash_content
from nous_runtime.retrieval.registry import RetrievalBackendRegistry
from nous_runtime.retrieval.backends.local import LocalRetrievalBackend
from nous_runtime.retrieval.taskgraph import TaskGraphRetrievalBridge


def _record(record_id: str, content: str) -> RetrievalRecord:
    return RetrievalRecord(
        record_id=record_id,
        record_type="memory_fact",
        workspace_id="workspace_a",
        project_id="project_a",
        source_id=record_id.replace("retr_", "mem_"),
        source_type="memory",
        content=content,
        content_hash=hash_content(content),
        access_scope=AccessScope(workspace_id="workspace_a", project_ids=("project_a",)),
    )


def _gateway() -> RetrievalGateway:
    registry = RetrievalBackendRegistry()
    backend = LocalRetrievalBackend()
    backend.upsert([_record("retr_python", "python runtime memory"), _record("retr_android", "android watch device")])
    registry.register(backend)
    return RetrievalGateway(backend_registry=registry)


def test_embedding_registry_has_deterministic_local_manifest():
    provider = HashEmbeddingProvider(dimension=8)
    vectors = provider.embed(["hello", "hello"])

    assert provider.manifest().dimension == 8
    assert vectors[0] == vectors[1]
    assert embedding_registry.resolve("hash-embedding-v1").manifest().provider_id == "local.hash"


def test_outbox_job_lifecycle(tmp_path):
    outbox = JsonlIndexingOutbox(tmp_path / ".nous")
    job = outbox.enqueue("index.rebuild", {"logical_index": "memory"})
    leased = outbox.lease_next()
    done = outbox.complete(leased.job_id)

    assert job.state == IndexingJobState.PENDING
    assert leased.state == IndexingJobState.RUNNING
    assert done.state == IndexingJobState.SUCCEEDED
    assert outbox.pending() == []


def test_qdrant_adapter_is_optional_without_dependency():
    backend = QdrantRetrievalBackend()
    health = backend.health()

    assert health.status in {"ok", "unavailable"}
    assert backend.manifest().supports_dense is True


def test_hybrid_ranking_and_context_packing():
    gateway = _gateway()
    query = RetrievalQuery(text="python", scope=RetrievalScope(workspace_id="workspace_a", project_ids=("project_a",)))
    results = HybridRetrievalEngine(gateway).search(query)
    pack = pack_context(results, max_tokens=100)

    assert results[0].record.record_id == "retr_python"
    assert "python runtime memory" in pack.text


def test_retrieval_evaluation_and_task_bridge():
    gateway = _gateway()
    query = RetrievalQuery(text="android", scope=RetrievalScope(workspace_id="workspace_a", project_ids=("project_a",)))
    eval_results = evaluate_cases(gateway, [RetrievalEvalCase("android", query, ("retr_android",))])
    context = TaskGraphRetrievalBridge(gateway).build_task_context(
        task_id="task_1",
        query_text="android",
        workspace_id="workspace_a",
        project_id="project_a",
    )

    assert eval_results[0].passed is True
    assert context.metadata["result_count"] == 1
    assert "android watch device" in context.pack.text
