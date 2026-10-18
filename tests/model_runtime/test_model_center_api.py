import pytest

from nous_runtime.api import routes
from nous_runtime.model_runtime.models import (
    ModelDescriptor,
    ModelEndpointType,
)
from nous_runtime.model_runtime.registry import ModelRuntimeRegistry


def test_model_center_api_uses_shared_workspace(monkeypatch, tmp_path):
    monkeypatch.setenv("NOUS_WORKSPACE_ROOT", str(tmp_path))
    registry = ModelRuntimeRegistry(tmp_path / "models" / "registry.json")
    registry.register(
        ModelDescriptor(
            model_id="model",
            display_name="Model",
            provider_id="mock",
            endpoint_type=ModelEndpointType.LOCAL_SERVICE,
            capabilities=frozenset({"reasoning"}),
        )
    )
    listed = routes.handle_model_center()
    assert listed["ok"] is True
    assert listed["data"]["summary"]["total"] == 1
    model = listed["data"]["models"][0]
    assert model["id"] == model["model_id"] == "model"
    assert model["provider_id"] == "mock"
    assert model["endpoint_type"] == "local_service"
    assert "avg_latency_ms" not in model
    assert "cost_per_1k_tokens_usd" not in model
    enabled = routes.handle_model_center_action(
        {"action": "enable", "model_id": "model"}
    )
    assert enabled["ok"] is True
    assert enabled["data"]["id"] == enabled["data"]["model_id"] == "model"
    assert enabled["data"]["state"] == "enabled"


def test_model_center_api_rejects_unknown_actions(monkeypatch, tmp_path):
    monkeypatch.setenv("NOUS_WORKSPACE_ROOT", str(tmp_path))
    result = routes.handle_model_center_action(
        {"action": "erase-host", "model_id": "model"}
    )
    assert result["ok"] is False
    assert result["error"]["code"] == "NOUS_INVALID_REQUEST"


def test_protected_http_model_snapshot_preserves_persisted_identities(
    monkeypatch, tmp_path
):
    import json
    from threading import Thread
    from urllib.error import HTTPError
    from urllib.request import Request, urlopen

    from nous_runtime.api.server import RuntimeAPIHandler, RuntimeHTTPServer
    from nous_runtime.model_runtime.adapters import ModelAdapterRegistry
    from nous_runtime.model_runtime.factory import ModelGatewayService
    from nous_runtime.model_runtime.gateway import ModelGateway
    from nous_runtime.model_runtime.models import ModelLifecycleState

    token = "APEIR_FAKE_ONLY_MODEL_CENTER_HTTP_TOKEN_31d9"
    monkeypatch.setenv("NOUS_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("NOUS_API_TOKEN", token)
    registry_path = tmp_path / "models" / "registry.json"
    registry = ModelRuntimeRegistry(registry_path)
    for model_id in ("registered-model", "enabled-model"):
        registry.register(
            ModelDescriptor(
                model_id=model_id,
                display_name=model_id,
                provider_id="fake-model-center",
                endpoint_type=ModelEndpointType.LOCAL_SERVICE,
                capabilities=frozenset({"reasoning"}),
            )
        )
    registry.enable("enabled-model")
    # The protected public route projects the active Gateway's registry.
    gateway_service = ModelGatewayService()
    monkeypatch.setattr(
        "nous_runtime.model_runtime.factory.gateway_service", gateway_service
    )
    gateway_service.configure(ModelGateway(registry, ModelAdapterRegistry()))
    server = RuntimeHTTPServer(("127.0.0.1", 0), RuntimeAPIHandler)
    thread = Thread(
        target=lambda: server.serve_forever(poll_interval=0.01), daemon=True
    )
    thread.start()
    url = f"http://127.0.0.1:{server.server_port}/api/v1/models"

    def snapshot():
        request = Request(url, headers={"Authorization": "Bearer " + token})
        with urlopen(request, timeout=5) as response:
            assert response.status == 200
            envelope = json.load(response)
        assert envelope["ok"] is True
        return envelope["data"]

    try:
        with pytest.raises(HTTPError) as denied:
            urlopen(Request(url), timeout=5)
        with denied.value as response:
            assert response.code == 401
            assert json.load(response)["ok"] is False
        original = snapshot()
        assert original["total_count"] == 2
        models = {model["model_id"]: model for model in original["models"]}
        assert set(models) == {"registered-model", "enabled-model"}
        assert {model["id"] for model in models.values()} == set(models)
        assert models["registered-model"]["state"] == "registered"
        assert models["enabled-model"]["state"] == "enabled"
        for model_id, model in models.items():
            assert model["id"] == model_id
            assert model["provider_id"] == "fake-model-center"
            assert model["endpoint_type"] == "local_service"
            assert model["health"] == "unknown"
            assert model["avg_latency_ms"] is None
            assert model["cost_per_1k_tokens_usd"] is None
        assert sum(model["state"] == "enabled" for model in models.values()) == 1

        registry.disable("enabled-model")
        registry.transition("registered-model", ModelLifecycleState.REMOVED)
        # Reopen the persisted registry through the same canonical Gateway
        # boundary. This public route excludes removed lifecycle records.
        gateway_service.configure(
            ModelGateway(ModelRuntimeRegistry(registry_path), ModelAdapterRegistry())
        )
        current = snapshot()
        assert current["total_count"] == 1
        assert {
            model["id"]: (model["model_id"], model["state"])
            for model in current["models"]
        } == {
            "enabled-model": ("enabled-model", "disabled"),
        }
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
    assert not thread.is_alive()


@pytest.mark.parametrize(
    "value",
    [
        None,
        -1,
        float("nan"),
        float("inf"),
        -float("inf"),
        True,
        False,
        "0.25",
        "invalid",
    ],
)
def test_public_model_adapter_does_not_invent_measurements(value):
    from nous_runtime.control_plane.routes import _adapt_model_record
    from nous_runtime.model_runtime.models import ModelLifecycleState
    from nous_runtime.model_runtime.registry import ModelRecord

    record = ModelRecord(
        descriptor=ModelDescriptor(
            model_id="fake-model",
            provider_id="fake",
            display_name="Fake",
            endpoint_type=ModelEndpointType.LOCAL_SERVICE,
        ),
        state=ModelLifecycleState.ENABLED,
        benchmark={"avg_latency_ms": value, "cost_per_1k_tokens_usd": value},
    )
    model = _adapt_model_record(record)
    assert model["avg_latency_ms"] is None
    assert model["cost_per_1k_tokens_usd"] is None
    assert model["health"] == "unknown"


@pytest.mark.parametrize("value", [0, 0.25, 12])
def test_public_model_adapter_retains_explicit_measurements_and_health(value):
    from nous_runtime.control_plane.routes import _adapt_model_record
    from nous_runtime.model_runtime.registry import ModelRecord

    record = ModelRecord(
        descriptor=ModelDescriptor(
            model_id="fake-model",
            provider_id="fake",
            display_name="Fake",
            endpoint_type=ModelEndpointType.LOCAL_SERVICE,
        ),
        benchmark={"avg_latency_ms": value, "cost_per_1k_tokens_usd": value},
        health={"status": "unhealthy"},
    )
    model = _adapt_model_record(record)
    assert model["avg_latency_ms"] == value
    assert model["cost_per_1k_tokens_usd"] == value
    assert model["health"] == "unhealthy"
