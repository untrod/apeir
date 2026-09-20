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
    enabled = routes.handle_model_center_action(
        {"action": "enable", "model_id": "model"}
    )
    assert enabled["ok"] is True
    assert enabled["data"]["state"] == "enabled"


def test_model_center_api_rejects_unknown_actions(monkeypatch, tmp_path):
    monkeypatch.setenv("NOUS_WORKSPACE_ROOT", str(tmp_path))
    result = routes.handle_model_center_action(
        {"action": "erase-host", "model_id": "model"}
    )
    assert result["ok"] is False
    assert result["error"]["code"] == "NOUS_INVALID_REQUEST"
