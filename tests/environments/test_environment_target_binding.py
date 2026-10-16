"""Environment routing keeps execution bound to the reviewed target."""

import json
from threading import Thread
from types import SimpleNamespace
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from nous_runtime.api import environment_routes, routes
from nous_runtime.api.server import RuntimeAPIHandler, RuntimeHTTPServer
from nous_runtime.governance.contracts import AuthorizationDecision

FAKE_SERVICE_TOKEN = "fake-environment-target-service-token"


@pytest.fixture
def execution_boundary(monkeypatch, tmp_path):
    executions, proposals = [], []

    def execute(capability, arguments, **kwargs):
        executions.append((capability, arguments, kwargs))
        return {"environment_id": arguments["environment_id"], "ok": True}

    class Gate:
        def evaluate(self, proposal, context):
            proposals.append(proposal)
            return AuthorizationDecision(
                action_mode="EXECUTE",
                allowed=True,
                proposal_hash=proposal.proposal_hash,
                context_id=context.context_id,
            )

    monkeypatch.setenv("NOUS_API_TOKEN", FAKE_SERVICE_TOKEN)
    monkeypatch.setenv("NOUS_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setattr("nous_runtime.governance.get_gate", lambda: Gate())
    monkeypatch.setattr(
        "nous_runtime.capability.runtime_executor.execute_runtime_capability", execute
    )
    monkeypatch.setattr(
        environment_routes, "_runtime", lambda: SimpleNamespace(root=tmp_path)
    )
    return executions, proposals


@pytest.mark.parametrize("body_target", ["env_other", "", None, True, {}])
def test_direct_handler_rejects_conflicting_target_before_dispatch(
    execution_boundary, body_target
):
    result = environment_routes.handle_environment_run(
        "env_selected", {"argv": ["python", "-V"], "environment_id": body_target}
    )
    assert not result["ok"]
    assert result["error"]["code"] == "NOUS_INVALID_REQUEST"
    assert execution_boundary[0] == []


@pytest.mark.parametrize("body_target", ["env_other", "", None, True, {}])
def test_route_rejects_conflicting_target_before_governance_or_dispatch(
    execution_boundary, body_target
):
    result = routes.route_server(
        "POST",
        "/api/v1/environments/env_selected/run",
        body={"argv": ["python", "-V"], "environment_id": body_target},
        auth={"token": FAKE_SERVICE_TOKEN, "loopback": True},
    )
    assert not result["ok"]
    assert result["error"]["code"] == "NOUS_INVALID_REQUEST"
    assert execution_boundary == ([], [])


@pytest.mark.parametrize("body_target", ["env_other", "", None, True, {}])
def test_actual_http_rejects_conflicting_target(execution_boundary, body_target):
    server = RuntimeHTTPServer(("127.0.0.1", 0), RuntimeAPIHandler)
    thread = Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01})
    thread.start()
    try:
        request = Request(
            f"http://127.0.0.1:{server.server_port}/api/v1/environments/env_selected/run",
            data=json.dumps(
                {"argv": ["python", "-V"], "environment_id": body_target}
            ).encode(),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {FAKE_SERVICE_TOKEN}",
            },
            method="POST",
        )
        try:
            response = urlopen(request, timeout=2)
        except HTTPError as exc:
            response = exc
        with response:
            result = json.load(response)
        assert not result["ok"]
        assert result["error"]["code"] == "NOUS_INVALID_REQUEST"
        assert execution_boundary == ([], [])
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
        assert not thread.is_alive()


@pytest.mark.parametrize("explicit_target", [False, True])
def test_valid_route_retains_exact_reviewed_target_and_arguments(
    execution_boundary, explicit_target
):
    body = {"argv": ["python", "-V"], "cwd": "src"}
    if explicit_target:
        body["environment_id"] = "env_selected"
    result = routes.route_server(
        "POST",
        "/api/v1/environments/env_selected/run",
        body=body,
        auth={"token": FAKE_SERVICE_TOKEN, "loopback": True},
    )
    assert result["ok"], result
    executions, proposals = execution_boundary
    assert len(executions) == len(proposals) == 1
    assert executions[0][0] == "environment.run"
    assert executions[0][1] == {**body, "environment_id": "env_selected"}
    assert proposals[0].affected_resources == ("env_selected",)
    assert proposals[0].params["body"] == body


def test_invalid_target_does_not_bypass_authentication(execution_boundary):
    result = routes.route_server(
        "POST",
        "/api/v1/environments/env_selected/run",
        body={"argv": ["python", "-V"], "environment_id": "env_other"},
        auth={"token": "fake-invalid-service-token", "loopback": True},
    )
    assert not result["ok"]
    assert result["error"]["code"] == "NOUS_UNAUTHENTICATED"
    assert execution_boundary == ([], [])
