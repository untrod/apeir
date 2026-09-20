import json

from nous_runtime.project.memory import add_fact
from nous_runtime.retrieval import LocalRetrievalBackend, LogicalIndexSpec, RetrievalBackendRegistry, RetrievalIndexManager
from nous_runtime.retrieval.indexing import IndexGenerationState
from nous_runtime.retrieval.store import JsonlIndexGenerationStore


def _workspace(tmp_path):
    ws = tmp_path / ".nous"
    (ws / "memory").mkdir(parents=True)
    (ws / "project.json").write_text(json.dumps({"name": "project_a"}), encoding="utf-8")
    return ws


def test_retrieval_index_rebuild_verifies_and_activates(tmp_path):
    ws = _workspace(tmp_path)
    add_fact(ws, "project.language", "python", "scan")
    backend = LocalRetrievalBackend()
    registry = RetrievalBackendRegistry()
    registry.register(backend)
    manager = RetrievalIndexManager(workspace_path=ws, backend_registry=registry)

    result = manager.rebuild(
        LogicalIndexSpec(
            logical_index="memory",
            backend_id="local",
            workspace_id="workspace_a",
            project_id="project_a",
        )
    )

    generations = manager.status("memory")
    assert result.ok is True
    assert result.exported_records == 1
    assert len(backend.records) == 1
    assert generations[-1].state == IndexGenerationState.ACTIVE
    assert generations[-1].verified is True


def test_index_store_keeps_latest_generation_state(tmp_path):
    ws = _workspace(tmp_path)
    store = JsonlIndexGenerationStore(ws)
    backend = LocalRetrievalBackend()
    registry = RetrievalBackendRegistry()
    registry.register(backend)
    manager = RetrievalIndexManager(workspace_path=ws, backend_registry=registry, store=store)
    generation = manager.create_generation(
        LogicalIndexSpec(
            logical_index="memory",
            backend_id="local",
            workspace_id="workspace_a",
            project_id="project_a",
        )
    )

    failed = store.update_state(generation.generation_id, IndexGenerationState.FAILED, failure_reason="test")

    assert store.get(generation.generation_id).state == IndexGenerationState.FAILED
    assert failed.failure_reason == "test"


def test_retrieval_verify_reports_missing_records(tmp_path):
    ws = _workspace(tmp_path)
    add_fact(ws, "project.language", "python", "scan")
    registry = RetrievalBackendRegistry()
    registry.register(LocalRetrievalBackend())
    manager = RetrievalIndexManager(workspace_path=ws, backend_registry=registry)
    generation = manager.create_generation(
        LogicalIndexSpec(
            logical_index="memory",
            backend_id="local",
            workspace_id="workspace_a",
            project_id="project_a",
        )
    )
    shadow = generation.with_build_result(
        state=IndexGenerationState.SHADOW,
        record_count=1,
        content_hash="hash",
        source_revision="rev",
    )
    manager.store.update(shadow)

    verification = manager.verify_generation(generation.generation_id)

    assert verification.valid is False
    assert verification.findings[0].code == "INDEX_MISSING_RECORDS"
