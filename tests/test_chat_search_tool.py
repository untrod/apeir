"""Chat web search reuses the existing governed network Capability."""

from types import SimpleNamespace

import pytest

from nous_runtime.chat.agent_tools import WorkspaceToolRuntime


def test_search_tool_forwards_only_bounded_inputs_to_existing_capability(
    tmp_path, monkeypatch
):
    received = []

    def observe(capability, **params):
        received.append((capability, params))
        return SimpleNamespace(
            status="success",
            metadata={},
            data={
                "result": {
                    "results": [],
                    "search_evidence": {"source_id": "source-original"},
                }
            },
        )

    monkeypatch.setattr(
        "nous_runtime.capability.resolver.execute_capability_observation", observe
    )
    runtime = WorkspaceToolRuntime(str(tmp_path), allow_mutations=True)
    assert "search_web" in {
        item["function"]["name"] for item in runtime.specifications()
    }
    result = runtime.execute(
        "search_web", {"query": "  public engineering  ", "max_results": 5}
    )
    assert (
        result["ok"]
        and result["result"]["search_evidence"]["source_id"] == "source-original"
    )
    capability, params = received[0]
    assert capability == "network.fetch"
    assert params["query"] == "public engineering" and params["max_results"] == 5
    assert params["_workspace_root"] == str(tmp_path)
    assert params["_governance_surface"] == "server"
    assert params["_authorization_context"] is None


@pytest.mark.parametrize(
    "arguments",
    [
        {"query": ""},
        {"query": "x" * 1001},
        {"query": "x", "max_results": True},
        {"query": "x", "max_results": 21},
        {"query": "x", "url": "http://127.0.0.1"},
        {"query": "x", "_authorization_context": {"approved": True}},
    ],
)
def test_invalid_search_cannot_override_scope_or_execute(
    tmp_path, monkeypatch, arguments
):
    monkeypatch.setattr(
        "nous_runtime.capability.resolver.execute_capability_observation",
        lambda *_args, **_kwargs: pytest.fail("Invalid input must not dispatch"),
    )
    runtime = WorkspaceToolRuntime(str(tmp_path), allow_mutations=True)
    assert runtime.execute("search_web", arguments)["ok"] is False


def test_read_only_chat_cannot_search_or_make_network_requests(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "nous_runtime.capability.resolver.execute_capability_observation",
        lambda *_args, **_kwargs: pytest.fail("Read-only scope cannot dispatch"),
    )
    runtime = WorkspaceToolRuntime(str(tmp_path), allow_mutations=False)
    assert "search_web" not in {
        item["function"]["name"] for item in runtime.specifications()
    }
    assert runtime.execute("search_web", {"query": "public engineering"})["ok"] is False


def test_search_without_authority_reaches_real_gate_without_network_egress(
    tmp_path, monkeypatch
):
    from nous_runtime.api.research_routes import ensure_network_capability
    from nous_runtime.evidence.web_gateway import WebGateway
    from nous_runtime.governance import ExecutionAuthorizationGate, GovernanceStore

    monkeypatch.setenv("NOUS_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("NOUS_DATA_DIR", str(tmp_path / "capabilities"))
    gate = ExecutionAuthorizationGate(GovernanceStore(tmp_path / "governance"))
    monkeypatch.setattr("nous_runtime.governance.get_gate", lambda: gate)
    monkeypatch.setattr(
        WebGateway,
        "_open_once",
        lambda *_args, **_kwargs: pytest.fail(
            "Missing authority must prevent network I/O"
        ),
    )
    ensure_network_capability()
    runtime = WorkspaceToolRuntime(
        str(tmp_path),
        allow_mutations=True,
        authorization_context={
            "subject_type": "agent",
            "subject_id": "unapproved-agent",
            "authn_method": "none",
            "authn_confidence": 0,
        },
    )
    result = runtime.execute("search_web", {"query": "public engineering"})
    assert result["ok"] is False
    assert result["capability_id"] == "network.fetch"
    assert result["error_code"] != "NOUS_CAPABILITY_NOT_FOUND"
