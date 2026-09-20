from nous_runtime.api.routes import route


def test_public_health_does_not_require_auth(monkeypatch):
    monkeypatch.setenv("NOUS_RUNTIME_MODE", "production")
    result = route("GET", "/api/v1/version")
    assert result["ok"] is True


def test_mutation_route_requires_auth_even_in_development(monkeypatch):
    monkeypatch.setenv("NOUS_RUNTIME_MODE", "development")
    result = route("POST", "/api/v1/capabilities/run", body={"capability_id": "system.echo"})
    assert result["ok"] is False
    assert result["error"]["code"] == "NOUS_UNAUTHENTICATED"


def test_mutation_route_rejects_query_token(monkeypatch):
    monkeypatch.setenv("NOUS_RUNTIME_MODE", "development")
    monkeypatch.setenv("NOUS_API_TOKEN", "secret")
    result = route(
        "POST",
        "/api/v1/capabilities/run",
        body={"capability_id": "system.echo"},
        auth={"query_token": "secret"},
    )
    assert result["ok"] is False
    assert result["error"]["code"] == "NOUS_UNAUTHENTICATED"


def test_mutation_route_accepts_header_token(monkeypatch):
    monkeypatch.setenv("NOUS_RUNTIME_MODE", "development")
    monkeypatch.setenv("NOUS_API_TOKEN", "secret")
    result = route(
        "POST",
        "/api/v1/capabilities/run",
        body={},
        auth={"headers": {"Authorization": "Bearer secret"}},
    )
    assert result["error"]["code"] == "NOUS_INVALID_REQUEST"


def test_production_inspector_requires_auth(monkeypatch):
    monkeypatch.setenv("NOUS_RUNTIME_MODE", "production")
    result = route("GET", "/api/inspector/runtime")
    assert result["ok"] is False
    assert result["error"]["code"] == "NOUS_UNAUTHENTICATED"
