from types import SimpleNamespace

from nous_runtime.api.routes import route_server


def test_server_capability_uses_configured_subject_and_remote_surface(monkeypatch):
    captured = {}

    def execute(capability_id, **kwargs):
        captured["capability_id"] = capability_id
        captured.update(kwargs)
        return SimpleNamespace(
            ok=True,
            capability_id=capability_id,
            provider_id="provider-a",
            result={"ok": True},
            error="",
            error_code="",
            duration_ms=1.0,
        )

    monkeypatch.setenv("NOUS_API_TOKEN", "server-secret")
    monkeypatch.setenv("NOUS_API_SUBJECT", "service-account-a")
    monkeypatch.setattr("nous_runtime.capability.resolver.execute_capability", execute)

    response = route_server(
        "POST",
        "/api/v1/capabilities/run",
        body={"capability_id": "system.echo", "params": {"message": "hello"}},
        auth={"headers": {"Authorization": "Bearer server-secret"}},
    )

    context = captured["_authorization_context"]
    assert response["ok"] is True
    assert context.subject_id == "service-account-a"
    assert context.authn_method == "api_bearer_token"
    assert context.session_locality == "remote"
    assert captured["_governance_surface"] == "server"


def test_capability_request_cannot_override_internal_authorization(monkeypatch):
    monkeypatch.setenv("NOUS_API_TOKEN", "server-secret")

    response = route_server(
        "POST",
        "/api/v1/capabilities/run",
        body={
            "capability_id": "system.echo",
            "params": {"_authorization_context": {"subject_id": "attacker"}},
        },
        auth={"token": "server-secret"},
    )

    assert response["ok"] is False
    assert response["error"]["code"] == "NOUS_INVALID_REQUEST"


def test_runtime_request_cannot_spoof_authenticated_user(monkeypatch):
    captured = {}

    class FakeResponse:
        def to_dict(self):
            return {"request_id": "request-a", "trace_id": "trace-a"}

    class FakeOrchestrator:
        def run(self, request):
            captured["request"] = request
            return FakeResponse()

    monkeypatch.setenv("NOUS_API_TOKEN", "server-secret")
    monkeypatch.setenv("NOUS_API_SUBJECT", "service-account-a")
    monkeypatch.setattr("nous_runtime.runtime.orchestrator.RuntimeOrchestrator", FakeOrchestrator)

    response = route_server(
        "POST",
        "/api/runtime/run",
        body={"user_input": "status", "user_id": "attacker"},
        auth={"token": "server-secret"},
    )

    request = captured["request"]
    assert response["ok"] is True
    assert request.user_id == "service-account-a"
    assert request.authorization_context["subject_id"] == "service-account-a"
    assert request.governance_surface == "server"
