from nous_runtime.cli.provider_setup import build_provider_config
from nous_runtime.control_plane.routes import (
    handle_list_models,
    handle_model_test_request,
)
from nous_runtime.model_runtime.factory import build_gateway_from_providers
from nous_runtime.model_runtime.models import ModelDescriptor, ModelEndpointType
from nous_runtime.model_runtime.registry import ModelRuntimeRegistry


def test_desktop_provider_config_preserves_selected_model_routes():
    config = build_provider_config(
        provider_id="deepseek",
        name="DeepSeek",
        api_base_url="https://api.deepseek.com/v1",
        credential_ref="env:DEEPSEEK_API_KEY",
        capabilities=("chat", "reasoning"),
        model="deepseek-chat",
        capability_models={
            "chat": "deepseek-chat",
            "reasoning": "deepseek-reasoner",
        },
    )

    assert config["model"] == "deepseek-chat"
    assert config["capability_models"] == {
        "chat": "deepseek-chat",
        "reasoning": "deepseek-reasoner",
    }
    assert config["credential_ref"] == "env:DEEPSEEK_API_KEY"
    assert "api_key" not in config


def test_body_safe_model_test_uses_the_configured_gateway(monkeypatch):
    captured = {}

    class Response:
        content = "NOUS_OK"
        finish_reason = "completed"
        usage = {"total_tokens": 2}

    class Gateway:
        def invoke_sync(self, request):
            captured["models"] = request.preferred_models
            captured["routing_mode"] = request.routing_mode.value
            return Response()

    from nous_runtime.model_runtime.factory import gateway_service

    monkeypatch.setattr(gateway_service, "get", lambda: Gateway())
    result = handle_model_test_request(
        {
            "model_id": "deepseek/deepseek-chat",
            "prompt": "Reply with NOUS_OK",
        }
    )

    assert result["ok"] is True
    assert result["data"]["healthy"] is True
    assert result["data"]["response_preview"] == "NOUS_OK"
    assert result["data"]["request_id"].startswith("modelreq_")
    assert result["data"]["execution"]["path"] == "gateway"
    assert captured["models"] == ("deepseek/deepseek-chat",)
    assert captured["routing_mode"] == "locked"


def test_model_catalog_reads_the_active_gateway_registry(monkeypatch):
    registry = ModelRuntimeRegistry()
    registry.register(
        ModelDescriptor(
            model_id="deepseek/deepseek-chat",
            display_name="DeepSeek Chat",
            provider_id="deepseek",
            endpoint_type=ModelEndpointType.CLOUD_API,
            capabilities=frozenset({"chat", "reasoning"}),
        )
    )
    registry.enable("deepseek/deepseek-chat")

    class Gateway:
        pass

    gateway = Gateway()
    gateway.registry = registry

    from nous_runtime.model_runtime.factory import gateway_service

    monkeypatch.setattr(gateway_service, "get", lambda **_kwargs: gateway)
    result = handle_list_models()

    assert result["ok"] is True
    assert result["data"]["total_count"] == 1
    model = result["data"]["models"][0]
    assert model["model_id"] == "deepseek/deepseek-chat"
    assert model["id"] == "deepseek/deepseek-chat"
    assert model["state"] == "enabled"
    assert model["health"] == "healthy"


def test_sidecar_bundles_the_top_level_nki_client():
    from pathlib import Path

    spec = Path("nous-sidecar.spec").read_text(encoding="utf-8")

    assert '"compat.nki_client"' in spec
    assert 'collect_submodules("compat")' not in spec


def test_gateway_catalog_registers_capability_specific_models():
    class Provider:
        provider_id = "deepseek"
        provider_name = "DeepSeek"
        model = "deepseek-chat"

        def __init__(self):
            self.capability_models = {
                "chat": "deepseek-chat",
                "reasoning": "deepseek-reasoner",
            }

        @staticmethod
        def list_capabilities():
            return ["model.reason", "model.code"]

    gateway = build_gateway_from_providers([Provider()])

    chat = gateway.registry.require("deepseek/deepseek-chat").descriptor
    reasoner = gateway.registry.require("deepseek/deepseek-reasoner").descriptor
    assert "chat" in chat.capabilities
    assert "reasoning" not in chat.capabilities
    assert reasoner.capabilities == frozenset({"chat", "reasoning"})
    assert reasoner.metadata["provider_model"] == "deepseek-reasoner"
