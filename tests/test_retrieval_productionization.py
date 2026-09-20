import json

from typer.testing import CliRunner

from nous_runtime.cli.main import app
from nous_runtime.project.memory import add_fact
from nous_runtime.retrieval import LogicalIndexSpec, RetrievalBackendRegistry, RetrievalIndexManager
from nous_runtime.retrieval.backends.persistent_local import PersistentLocalRetrievalBackend
from nous_runtime.retrieval.backends.qdrant import QdrantCollectionSpec, build_collection_name
from nous_runtime.retrieval.embeddings import FastEmbedEmbeddingProvider
from nous_runtime.retrieval.evaluation import RetrievalEvalCase, evaluate_report
from nous_runtime.retrieval.gateway import RetrievalGateway
from nous_runtime.retrieval.models import AccessScope, RetrievalQuery, RetrievalRecord, RetrievalScope
from nous_runtime.retrieval.protocol import IndexSpec
from nous_runtime.retrieval.ranking import pack_context
from nous_runtime.retrieval.records.hashing import hash_content
from nous_runtime.retrieval.taskgraph import RetrievalInjectionMode, TaskGraphRetrievalBridge


def _workspace(tmp_path):
    ws = tmp_path / ".nous"
    (ws / "memory").mkdir(parents=True)
    (ws / "project.json").write_text(json.dumps({"name": "project_a"}), encoding="utf-8")
    return ws


def test_persistent_local_backend_survives_new_manager_instance(tmp_path):
    ws = _workspace(tmp_path)
    add_fact(ws, "project.language", "python", "scan")
    registry = RetrievalBackendRegistry()
    registry.register(PersistentLocalRetrievalBackend(ws), name="local")
    first = RetrievalIndexManager(workspace_path=ws, backend_registry=registry)
    result = first.rebuild(
        LogicalIndexSpec(
            logical_index="memory",
            backend_id="local",
            workspace_id="workspace_a",
            project_id="project_a",
        )
    )

    second_registry = RetrievalBackendRegistry()
    second_registry.register(PersistentLocalRetrievalBackend(ws), name="local")
    second = RetrievalIndexManager(workspace_path=ws, backend_registry=second_registry)
    verification = second.verify_generation(result.generation_id)

    assert verification.valid is True
    assert verification.expected_count == 1
    assert verification.actual_count == 1


def test_cli_rebuild_then_verify_uses_persistent_local_backend(tmp_path, monkeypatch):
    ws = _workspace(tmp_path)
    add_fact(ws, "project.language", "python", "scan")
    monkeypatch.chdir(tmp_path)
    runner = CliRunner()

    rebuild = runner.invoke(app, ["retrieval", "index", "rebuild", "--workspace-id", "workspace_a", "--json"])
    generation_id = json.loads(rebuild.stdout)["generation_id"]
    verify = runner.invoke(app, ["retrieval", "index", "verify", generation_id, "--json"])

    assert rebuild.exit_code == 0
    assert verify.exit_code == 0
    assert json.loads(verify.stdout)["valid"] is True


def test_fastembed_provider_is_lazy_and_optional():
    provider = FastEmbedEmbeddingProvider("test-model", dimension=384)

    assert provider.manifest().dimension == 384
    assert provider.manifest().metadata["lazy_load"] is True


def test_qdrant_collection_spec_and_name_are_stable():
    name = build_collection_name("nous", "workspace with spaces", "memory", "gen_123")
    spec = QdrantCollectionSpec(
        collection_name=name,
        generation_id="gen_123",
        dense_vector_name="content_dense",
        dimension=384,
    )

    assert name.startswith("nous_workspace_with_spaces_memory_gen_123")
    assert len(name) <= 63
    assert spec.to_dict()["payload_indexes"]


def test_evaluation_report_and_context_decision_metrics():
    registry = RetrievalBackendRegistry()
    backend = PersistentLocalRetrievalBackend(_make_backend_workspace_record())
    registry.register(backend, name="local")
    gateway = RetrievalGateway(backend_registry=registry)
    query = RetrievalQuery(text="中文 技术 文档", scope=RetrievalScope(workspace_id="workspace_a", project_ids=("project_a",)))
    results = gateway.search(query)
    report = evaluate_report(gateway, [RetrievalEvalCase("zh", query, ("retr_zh",))])
    pack = pack_context(results, max_tokens=120)
    bridge = TaskGraphRetrievalBridge(gateway, mode=RetrievalInjectionMode.DISABLED)
    context = bridge.build_task_context(
        task_id="task_1",
        query_text="中文 技术 文档",
        workspace_id="workspace_a",
        project_id="project_a",
    )

    assert report.recall_at_5 == 1.0
    assert report.mrr == 1.0
    assert "中文技术文档" in pack.text
    assert context.metadata["decision"].enabled is False


def _make_backend_workspace_record():
    import tempfile
    from pathlib import Path

    ws = Path(tempfile.mkdtemp()) / ".nous"
    backend = PersistentLocalRetrievalBackend(ws)
    record = RetrievalRecord(
        record_id="retr_zh",
        record_type="memory_fact",
        workspace_id="workspace_a",
        project_id="project_a",
        source_id="mem_zh",
        source_type="memory",
        content="中文技术文档 runtime retrieval",
        content_hash=hash_content("中文技术文档 runtime retrieval"),
        access_scope=AccessScope(workspace_id="workspace_a", project_ids=("project_a",)),
    )
    backend.ensure_index(IndexSpec(name="memory", metadata={"generation_id": "gen_zh"}))
    backend.upsert([record], generation_id="gen_zh")
    return ws
