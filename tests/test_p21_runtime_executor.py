from __future__ import annotations

from nous_runtime.capability.runtime_executor import (
    execute_runtime_capability,
    list_runtime_capabilities,
)
from nous_runtime.capability.resolver import execute_capability_observation
from nous_runtime.chat.agent_tools import WorkspaceToolRuntime


def test_runtime_dispatcher_creates_a_real_document(tmp_path):
    result = execute_runtime_capability(
        "document.create",
        {
            "title": "P21 evidence",
            "blocks": [{"kind": "paragraph", "text": "Central dispatch executed."}],
        },
        workspace_root=tmp_path,
    )

    assert result["document_id"]
    assert result["artifact_id"]
    assert (tmp_path / ".nous" / "documents" / f"{result['document_id']}.json").is_file()


def test_generic_capability_entry_dispatches_runtime_service(tmp_path, monkeypatch):
    monkeypatch.setenv("NOUS_GOVERNANCE_MODE", "compatibility")
    from nous_runtime.api.document_routes import ensure_document_capabilities
    ensure_document_capabilities()

    observation = execute_capability_observation(
        "document.create",
        _workspace_root=str(tmp_path),
        title="Generic entry evidence",
        blocks=[{"kind": "paragraph", "text": "Resolver reached RuntimeCapabilityExecutor."}],
    )

    assert observation.status == "success"
    assert observation.metadata["execution_scope"] == "runtime-service"
    assert observation.metadata["kernel_traversed"] is False
    assert observation.data["result"]["document_id"]


def test_runtime_tool_surface_is_request_scoped(tmp_path):
    read_only = WorkspaceToolRuntime(str(tmp_path), allow_mutations=False)
    agent = WorkspaceToolRuntime(str(tmp_path), allow_mutations=True)
    read_names = {item["function"]["name"] for item in read_only.specifications()}
    agent_names = {item["function"]["name"] for item in agent.specifications()}

    assert "create_document" not in read_names
    assert "create_document" in agent_names
    assert "fetch_public_url" in agent_names
    assert "analyze_scientific_run" in agent_names
    assert set(list_runtime_capabilities()) >= {
        "document.create", "environment.run", "network.fetch",
        "simulation.run", "scientific.analyze",
    }


def test_kernel_status_without_endpoint_is_truthful(monkeypatch):
    monkeypatch.delenv("NOUS_KERNEL_ENDPOINT", raising=False)
    from nous_runtime.api.kernel_status import kernel_status

    status = kernel_status(cache_seconds=0)
    assert status["configured"] is False
    assert status["connected"] is False
    assert status["ready"] is False
    assert "token" not in status
