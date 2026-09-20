from types import SimpleNamespace

from nous_runtime.api import routes


def test_parameterized_route_matches_valid_segment(monkeypatch):
    monkeypatch.setenv("NOUS_API_TOKEN", "secret")
    monkeypatch.setitem(
        routes.ROUTES,
        ("DELETE", "/api/v1/packs/{name}"),
        lambda name: routes.ok_response({"removed": name}),
    )
    monkeypatch.setattr(routes, "_authorize_mutation_route", lambda *args, **kwargs: None)

    response = routes.route(
        "DELETE",
        "/api/v1/packs/example-pack",
        auth={"token": "secret"},
    )

    assert response == {"ok": True, "data": {"removed": "example-pack"}}


def test_parameterized_route_rejects_encoded_traversal(monkeypatch):
    monkeypatch.setenv("NOUS_API_TOKEN", "secret")

    response = routes.route(
        "DELETE",
        "/api/v1/packs/%2e%2e",
        auth={"token": "secret"},
    )

    assert response["ok"] is False
    assert response["error"]["code"] == "NOUS_INVALID_REQUEST"


def test_path_parameter_cannot_be_overridden(monkeypatch):
    monkeypatch.setenv("NOUS_API_TOKEN", "secret")
    monkeypatch.setattr(routes, "_authorize_mutation_route", lambda *args, **kwargs: None)

    response = routes.route(
        "DELETE",
        "/api/v1/packs/example-pack",
        params={"name": "other-pack"},
        auth={"token": "secret"},
    )

    assert response["ok"] is False
    assert response["error"]["code"] == "NOUS_INVALID_REQUEST"


def test_server_pack_mutation_is_governed_before_handler(monkeypatch):
    captured = {}

    class Gate:
        def evaluate(self, proposal, context):
            captured["proposal"] = proposal
            captured["context"] = context
            return SimpleNamespace(
                action_mode="ASK_APPROVAL",
                rule_class="USER_APPROVABLE",
                reason_code="APPROVAL_REQUIRED",
                reason_message="Approval required",
                decision_id="decision-a",
            )

    def unexpected_handler(body):
        raise AssertionError("handler must not run before approval")

    monkeypatch.setenv("NOUS_API_TOKEN", "secret")
    monkeypatch.setenv("NOUS_API_SUBJECT", "service-account-a")
    monkeypatch.setattr("nous_runtime.governance.get_gate", lambda: Gate())
    monkeypatch.setitem(routes.ROUTES, ("POST", "/api/v1/packs/install"), unexpected_handler)

    response = routes.route_server(
        "POST",
        "/api/v1/packs/install",
        body={"path": "./pack"},
        auth={"token": "secret"},
    )

    assert response["ok"] is False
    assert response["error"]["code"] == "NOUS_APPROVAL_REQUIRED"
    assert captured["proposal"].capability_id == "pack.install"
    assert captured["context"].subject_id == "service-account-a"


def test_authenticated_loopback_request_has_local_governance_context(monkeypatch):
    monkeypatch.setenv("NOUS_API_TOKEN", "secret")

    context = routes._authentication_context(
        {"token": "secret", "loopback": True},
        surface="server",
    )

    assert context is not None
    assert context.session_locality == "local"


def test_authenticated_non_loopback_request_remains_remote(monkeypatch):
    monkeypatch.setenv("NOUS_API_TOKEN", "secret")

    context = routes._authentication_context(
        {"token": "secret", "loopback": False},
        surface="server",
    )

    assert context is not None
    assert context.session_locality == "remote"


def test_project_cancel_uses_separate_destructive_capability(monkeypatch):
    captured = {}

    class Gate:
        def evaluate(self, proposal, context):
            captured["proposal"] = proposal
            return SimpleNamespace(
                action_mode="ASK_APPROVAL",
                rule_class="USER_APPROVABLE",
                reason_code="APPROVAL_REQUIRED",
                reason_message="Approval required",
                decision_id="decision-cancel",
            )

    monkeypatch.setenv("NOUS_API_TOKEN", "secret")
    monkeypatch.setattr("nous_runtime.governance.get_gate", lambda: Gate())

    response = routes.route_server(
        "POST",
        "/api/v1/developer/projects/project-a/action",
        body={"action": "cancel"},
        auth={"token": "secret", "loopback": True},
    )

    assert response["error"]["code"] == "NOUS_APPROVAL_REQUIRED"
    assert captured["proposal"].capability_id == "project.cancel"
    assert captured["proposal"].side_effect_class == "destructive"


def test_api_approval_request_issues_one_use_retry_lease(monkeypatch, tmp_path):
    from nous_runtime.governance.broker import ApprovalBroker
    from nous_runtime.governance.contracts import AuthorizationContext
    from nous_runtime.governance.gate import ExecutionAuthorizationGate
    from nous_runtime.governance.store import GovernanceStore

    monkeypatch.setenv("NOUS_DATA_DIR", str(tmp_path / "data"))
    store = GovernanceStore(tmp_path / "governance")
    broker = ApprovalBroker(store=store)
    gate = ExecutionAuthorizationGate(store=store)
    monkeypatch.setattr("nous_runtime.governance.get_gate", lambda: gate)
    monkeypatch.setattr("nous_runtime.governance.broker.get_broker", lambda: broker)
    context = AuthorizationContext(
        subject_type="user",
        subject_id="owner",
        authn_method="test",
        authn_confidence=1.0,
        session_locality="local",
        request_id="request-approval-retry",
    )
    body = {"path": "reviewed.txt", "content": "reviewed", "expected_sha256": ""}

    first = routes._authorize_mutation_route(
        "POST",
        "/api/v1/developer/workspace/write",
        body,
        {},
        context,
        surface="server",
    )
    request_id = first["error"]["details"]["approval_request_id"]
    broker.approve(request_id, approver_id="owner-confirmation")
    approved_retry = routes._authorize_mutation_route(
        "POST",
        "/api/v1/developer/workspace/write",
        body,
        {},
        context,
        surface="server",
    )
    exhausted_retry = routes._authorize_mutation_route(
        "POST",
        "/api/v1/developer/workspace/write",
        body,
        {},
        context,
        surface="server",
    )

    assert first["error"]["code"] == "NOUS_APPROVAL_REQUIRED"
    assert request_id.startswith("apr_")
    assert approved_retry is None
    assert exhausted_retry["error"]["code"] == "NOUS_APPROVAL_REQUIRED"
    assert exhausted_retry["error"]["details"]["approval_request_id"] != request_id