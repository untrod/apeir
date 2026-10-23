"""Setup/diagnostics cannot become a second model execution path."""

import json

import pytest

from nous_runtime.cli.provider_experience import (
    diagnose_provider,
    probe_provider_config,
)
from nous_runtime.cli.provider_setup import (
    build_provider_config,
    validate_provider_from_config,
)
from nous_runtime.control_plane.routes import handle_model_test_request


class ProbeResponse:
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def read(self, _limit=-1):
        return b'{"data":[{"id":"example-model"}]}'


@pytest.mark.parametrize(
    "endpoint",
    [
        "file:///tmp/model",
        "http://",
        "https://user:fixture-only-value@provider.example.test",
        "https://provider.example.test/v1?api_key=fixture-only-value",
        "https://provider.example.test/v1#fragment",
        "https://provider.example.test:0/v1",
    ],
)
def test_provider_base_url_cannot_store_embedded_credentials_or_unsupported_transport(
    endpoint,
):
    with pytest.raises(ValueError) as rejected:
        build_provider_config("example", "Example", endpoint)
    assert "fixture-only-value" not in str(rejected.value)


def test_unsaved_configuration_validation_is_not_model_execution(monkeypatch):
    monkeypatch.setattr(
        "nous_runtime.cli.provider_setup.probe_provider_config",
        lambda *_: pytest.fail("Configuration validation cannot dispatch a model"),
    )
    result = validate_provider_from_config(
        "example", "Example", "https://provider.example.test/v1", model="example-model"
    )
    assert result["ok"] is True
    assert result["validation_scope"] == "configuration"
    assert result["model_inference"] == "NOT_RUN"
    assert result["authentication"] == "UNKNOWN"
    assert result["latency_ms"] is None


def test_direct_provider_test_cannot_send_inference_or_resolve_credentials(monkeypatch):
    monkeypatch.setattr(
        "nous_runtime.model_runtime.factory.gateway_service.get", lambda **_: None
    )
    sent = []
    monkeypatch.setattr(
        "urllib.request.urlopen",
        lambda request, **_: sent.append(request) or ProbeResponse(),
    )
    monkeypatch.setattr(
        "nous_runtime.cli.provider_experience.resolve_credential",
        lambda *_: pytest.fail("Blocked inference cannot resolve a credential"),
    )
    result = probe_provider_config(
        "example",
        {
            "endpoint": "https://provider.example.test/v1/chat/completions",
            "model": "example-model",
        },
        "test",
    )
    assert result["ok"] is False
    assert result["code"] == "NOUS_PROVIDER_NKI_REQUIRED"
    assert result["model_inference"] == "NOT_RUN"
    assert sent == []


@pytest.fixture
def registered_kernel_gateway(monkeypatch):
    from nous_runtime.model_runtime.factory import build_gateway_from_providers
    from nous_runtime.provider.adapters.openai import OpenAIProvider

    provider = OpenAIProvider(
        provider_id="example",
        provider_name="Example",
        endpoint="https://provider.example.test/v1/chat/completions",
        model="example-model",
        credential_ref="env:FAKE_PROVIDER_KEY",
        capabilities=("model.reason",),
    )
    gateway = build_gateway_from_providers((provider,))
    monkeypatch.setattr(
        "nous_runtime.model_runtime.factory.gateway_service.get", lambda **_: gateway
    )
    monkeypatch.setattr(
        "nous_runtime.cli.provider_experience.resolve_credential",
        lambda *_: pytest.fail("Only Kernel may resolve inference credentials"),
    )
    return gateway, {
        "endpoint": provider.endpoint,
        "model": provider.model,
        "credential_ref": provider.credential_ref,
    }


def test_saved_provider_probe_reuses_original_kernel_gateway_and_accounting(
    registered_kernel_gateway, monkeypatch
):
    from nous_runtime.model_runtime.models import ModelResponse

    gateway, config = registered_kernel_gateway
    requests = []

    def invoke(request):
        requests.append(request)
        return ModelResponse(
            request_id=request.request_id,
            model_id="example/example-model",
            instance_id="example-default",
            content="OK",
            metadata={"execution_path": "kernel"},
        )

    monkeypatch.setattr(gateway, "invoke_sync", invoke)
    result = probe_provider_config("example", config, "test")
    assert result["ok"] is True
    assert result["model_inference"] == "COMPLETED"
    assert result["request_id"] == requests[0].request_id
    assert result["execution"]["path"] == "kernel"
    assert result["tokens_used"] is None and result["cost_usd"] is None
    assert len(requests) == 1
    assert requests[0].preferred_models == ("example/example-model",)
    assert requests[0].routing_mode.value == "locked"


@pytest.mark.parametrize(
    "changed",
    [
        "endpoint",
        "model",
        "credential_ref",
        "capability_models",
        "capability_endpoints",
    ],
)
def test_changed_proposed_provider_cannot_test_another_registered_configuration(
    registered_kernel_gateway, monkeypatch, changed
):
    gateway, config = registered_kernel_gateway
    monkeypatch.setattr(
        gateway,
        "invoke_sync",
        lambda *_: pytest.fail("Changed configuration must not dispatch"),
    )
    config[changed] = (
        {"chat": "other"} if changed.startswith("capability_") else "changed"
    )
    result = probe_provider_config("example", config, "test")
    assert result["ok"] is False
    assert result["code"] == "NOUS_PROVIDER_NKI_REQUIRED"


def test_compatibility_gateway_cannot_be_used_for_production_probe(
    registered_kernel_gateway, monkeypatch
):
    gateway, config = registered_kernel_gateway
    from nous_runtime.model_runtime.gateway import ModelGateway

    direct = ModelGateway(gateway.registry, gateway.adapters)
    monkeypatch.setattr(
        "nous_runtime.model_runtime.factory.gateway_service.get", lambda **_: direct
    )
    monkeypatch.setattr(
        direct,
        "invoke_sync",
        lambda *_: pytest.fail("Direct fallback must not dispatch"),
    )
    assert (
        probe_provider_config("example", config, "test")["code"]
        == "NOUS_PROVIDER_NKI_REQUIRED"
    )


def test_gateway_change_between_probe_binding_and_admission_does_not_dispatch(
    registered_kernel_gateway, monkeypatch
):
    gateway, config = registered_kernel_gateway
    calls = []

    def current(**_):
        calls.append(True)
        return gateway if len(calls) == 1 else object()

    monkeypatch.setattr(
        "nous_runtime.model_runtime.factory.gateway_service.get", current
    )
    monkeypatch.setattr(
        gateway,
        "invoke_sync",
        lambda *_: pytest.fail("Stale Gateway must not dispatch"),
    )
    result = probe_provider_config("example", config, "test")
    assert result["ok"] is False and result["model_inference"] == "NOT_RUN"
    assert len(calls) == 2


def test_doctor_only_reads_endpoint_metadata(tmp_path, monkeypatch):
    private = tmp_path / ".nous"
    private.mkdir()
    config = {
        "endpoint": "https://provider.example.test/v1/chat/completions",
        "models_endpoint": "https://provider.example.test/v1/models",
        "model": "example-model",
    }
    (private / "providers.json").write_text(json.dumps({"example": config}))
    sent = []
    monkeypatch.setattr(
        "urllib.request.urlopen",
        lambda request, **_: sent.append(request) or ProbeResponse(),
    )
    result = diagnose_provider("example", private)
    assert result["ok"] is True
    assert result["model_inference"] == "NOT_RUN"
    assert sent and all(
        request.get_method() == "GET" and request.data is None for request in sent
    )


@pytest.mark.parametrize(
    "finish,healthy", [("completed", True), ("UNKNOWN", False), ("", False)]
)
def test_model_test_requires_explicit_completion_and_keeps_missing_usage_unknown(
    monkeypatch, finish, healthy
):
    from nous_runtime.model_runtime.models import ModelResponse

    class Gateway:
        def invoke_sync(self, request):
            return ModelResponse(
                request_id=request.request_id,
                model_id="example/model",
                instance_id="example-instance",
                content="OK",
                finish_reason=finish,
            )

    monkeypatch.setattr(
        "nous_runtime.model_runtime.factory.gateway_service.get", lambda: Gateway()
    )
    result = handle_model_test_request({"model_id": "example/model"})["data"]
    assert result["healthy"] is healthy
    assert result["tokens_used"] is None
    assert result["request_id"].startswith("modelreq_")


def test_model_test_failure_keeps_original_request_without_echoing_provider_exception(
    monkeypatch,
):
    fake_value = "fixture-only-provider-error-value"
    requests = []

    class Gateway:
        def invoke_sync(self, request):
            requests.append(request.request_id)
            raise RuntimeError(fake_value)

    monkeypatch.setattr(
        "nous_runtime.model_runtime.factory.gateway_service.get", lambda: Gateway()
    )
    result = handle_model_test_request({"model_id": "example/model"})["data"]
    assert result["healthy"] is False
    assert result["request_id"] == requests[0]
    assert len(requests) == 1
    assert fake_value not in json.dumps(result)


def test_configuration_validation_over_authenticated_runtime_http(
    tmp_path, monkeypatch
):
    import threading
    from urllib.error import HTTPError
    from urllib.request import Request, urlopen

    from nous_runtime.api.server import RuntimeAPIHandler, RuntimeHTTPServer

    token = "provider.setup.fake.session"
    monkeypatch.setenv("NOUS_API_TOKEN", token)
    monkeypatch.setenv("NOUS_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setattr(
        "nous_runtime.cli.provider_experience._probe_request",
        lambda *_: pytest.fail("Setup must not send an inference or endpoint probe"),
    )
    server = RuntimeHTTPServer(("127.0.0.1", 0), RuntimeAPIHandler)
    owner = threading.Thread(target=server.serve_forever, daemon=True)
    owner.start()
    url = f"http://127.0.0.1:{server.server_port}/api/v1/providers/validate"
    payload = json.dumps(
        {
            "provider_id": "example",
            "name": "Example",
            "api_base_url": "https://provider.example.test/v1",
            "model": "example-model",
        }
    ).encode()
    try:
        with pytest.raises(HTTPError) as denied:
            urlopen(
                Request(
                    url, data=payload, headers={"Content-Type": "application/json"}
                ),
                timeout=5,
            )
        assert denied.value.code == 401
        denied.value.close()
        with urlopen(
            Request(
                url,
                data=payload,
                headers={
                    "Content-Type": "application/json",
                    "Authorization": "Bearer " + token,
                },
            ),
            timeout=5,
        ) as response:
            result = json.load(response)
        assert result["ok"] is True
        assert result["data"]["validation_scope"] == "configuration"
        assert result["data"]["model_inference"] == "NOT_RUN"
        assert result["data"]["authentication"] == "UNKNOWN"
        assert not (tmp_path / ".nous" / "providers.json").exists()
    finally:
        server.shutdown()
        server.server_close()
        owner.join(timeout=5)
    assert not owner.is_alive()
