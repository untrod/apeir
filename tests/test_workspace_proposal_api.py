"""Public proposal endpoints bind actors and delegate original execution authority."""

import pytest

from nous_runtime.api import developer_routes as routes
from nous_runtime.governance import (
    AuthorizationContext,
    ExecutionAuthorizationGate,
    GovernanceStore,
)
from nous_runtime.governance.cli import _build_context
from nous_runtime.governance.permission import PermissionEngine, PermissionRule
from nous_runtime.workspace.proposals import WorkspaceProposalService


@pytest.fixture
def api(tmp_path, monkeypatch):
    from nous_runtime.services.lifecycle import seed_capabilities

    monkeypatch.setenv("NOUS_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("NOUS_DATA_DIR", str(tmp_path / "capability-data"))
    assert seed_capabilities() > 0
    gate = ExecutionAuthorizationGate(
        store=GovernanceStore(tmp_path / ".nous"),
        permission_engine=PermissionEngine(
            (
                PermissionRule("*", "workspace.read", "*"),
                PermissionRule("*", "governance.approve", "*"),
                PermissionRule(
                    "runtime:workspace-proposals", "capability.execute", "workspace:*"
                ),
            )
        ),
    )
    service = WorkspaceProposalService(tmp_path, gate=gate)
    monkeypatch.setattr(routes, "_proposals", lambda: service)
    monkeypatch.setattr("nous_runtime.governance.get_gate", lambda: gate)
    monkeypatch.setattr("nous_runtime.governance.gate._gate_instance", gate)
    return tmp_path, gate, service


def test_human_intent_creates_service_request_without_grant_and_can_approve_once(api):
    root, gate, service = api
    human = _build_context()
    prepared = routes.handle_developer_proposal_prepare(
        {"files": [{"path": "code.py", "content": "value = 1\n"}]},
        authorization_context=human,
    )
    assert prepared["ok"]
    original = prepared["data"]
    assert original["subject_id"] == "runtime:workspace-proposals"
    assert original["requested_by"] == human.subject_id
    assert not (root / "code.py").exists()
    before = routes.handle_developer_proposal_action(
        original["proposal_id"], {"action": "apply"}, authorization_context=human
    )
    assert before["ok"] and before["data"]["applied"] is False
    service.broker.respond_operation(
        original["approval_request_id"], "approve", human, gate=gate
    )
    result = routes.handle_developer_proposal_action(
        original["proposal_id"], {"action": "apply"}, authorization_context=human
    )
    assert result["ok"] and result["data"]["applied"]
    assert result["data"]["verification"]["verdict"] == "MATCH"
    assert result["data"]["authorization_id"] == original["authorization_id"]
    assert (root / "code.py").read_text() == "value = 1\n"


@pytest.mark.parametrize(
    "extra",
    [
        "subject_id",
        "source_work_id",
        "agent_session_id",
        "authorization_context",
        "approved",
    ],
)
def test_browser_cannot_choose_identity_provenance_or_authority(api, extra):
    root, _, service = api
    result = routes.handle_developer_proposal_prepare(
        {"files": [{"path": "code.py", "content": "value = 1\n"}], extra: "forged"},
        authorization_context=_build_context(),
    )
    assert not result["ok"]
    assert service.list()["total"] == 0
    assert not (root / "code.py").exists()


def test_missing_read_authority_never_resolves_proposal_content(api):
    root, gate, service = api
    gate.permission_engine = PermissionEngine(())
    caller = AuthorizationContext(
        subject_type="agent",
        subject_id="unprivileged-agent",
        authn_method="runtime",
        authn_confidence=0.9,
    )
    result = routes.handle_developer_proposals(authorization_context=caller)
    assert not result["ok"] and result["error"]["code"] == "NOUS_FORBIDDEN"
    assert service.list()["total"] == 0


def test_action_cannot_replace_original_proposal_parameters(api):
    root, _, _ = api
    result = routes.handle_developer_proposal_action(
        "original",
        {"action": "apply", "files": [{"path": "other.py", "content": "changed"}]},
        authorization_context=_build_context(),
    )
    assert not result["ok"]
    assert not (root / "other.py").exists()


def test_protected_http_round_trip_recovers_original_file_evidence(api, monkeypatch):
    import json
    import threading
    from urllib.request import Request, urlopen
    from nous_runtime.api.server import RuntimeAPIHandler, RuntimeHTTPServer

    root, gate, service = api
    token = "APEIR_FAKE_ONLY_HTTP_TOKEN_82e4"
    monkeypatch.setenv("NOUS_API_TOKEN", token)
    server = RuntimeHTTPServer(("127.0.0.1", 0), RuntimeAPIHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    def call(path, body=None):
        request = Request(
            f"http://127.0.0.1:{server.server_port}" + path,
            data=json.dumps(body).encode() if body is not None else None,
            headers={
                "Authorization": "Bearer " + token,
                "Content-Type": "application/json",
            },
        )
        with urlopen(request, timeout=5) as response:
            return json.loads(response.read())

    try:
        original = call(
            "/api/v1/developer/workspace/proposals",
            {"files": [{"path": "http.py", "content": "value = 2\n"}]},
        )["data"]
        assert original["approval_required"] and not (root / "http.py").exists()
        detail = call(
            "/api/v1/developer/workspace/proposals/" + original["proposal_id"]
        )["data"]
        assert detail["manifest_ref"] == original["manifest_ref"]
        service.broker.respond_operation(
            original["approval_request_id"], "approve", _build_context(), gate=gate
        )
        response = call(
            "/api/v1/developer/workspace/proposals/"
            + original["proposal_id"]
            + "/action",
            {"action": "apply"},
        )["data"]
        assert response["applied"] and response["verification"]["verdict"] == "MATCH"
        fresh = call(
            "/api/v1/developer/workspace/proposals/"
            + original["proposal_id"]
            + "/action",
            {"action": "reconcile"},
        )["data"]
        assert (
            fresh["verification"]["verdict"] == "MATCH" and fresh["replayed"] is False
        )
        assert (root / "http.py").read_text() == "value = 2\n"
        assert service.artifacts.verify(fresh["verification"]["observation_ref"])
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
    assert not thread.is_alive()
