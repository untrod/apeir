"""Configuration mutations must reach the saved owner and current Gateway."""

import json

import pytest

from nous_runtime.cli.provider_setup import (
    load_providers_from_config,
    register_provider_from_config,
)
from nous_runtime.control_plane.routes import (
    handle_delete_provider,
    handle_update_provider,
)
from nous_runtime.model_runtime.factory import gateway_service
from nous_runtime.services.providers import clear_providers, get_provider


@pytest.fixture
def configured_workspace(tmp_path, monkeypatch):
    from nous_runtime.compat.provider import _providers, register_adapter

    previous = tuple(_providers.values())
    gateway = gateway_service.get(required=False)
    monkeypatch.setenv("NOUS_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.delenv("NOUS_NO_INTELLIGENCE", raising=False)
    clear_providers()
    gateway_service.clear()
    try:
        register_provider_from_config(
            "example",
            "Example",
            "https://provider.example.test/v1",
            credential_ref="env:FAKE_PROVIDER_KEY",
            model="original-model",
            capabilities=["Reasoning"],
        )
        yield tmp_path / ".nous" / "providers.json"
    finally:
        clear_providers()
        for provider in previous:
            register_adapter(provider)
        if gateway is None:
            gateway_service.clear()
        else:
            gateway_service.configure(gateway)


def _models():
    return {
        record.descriptor.model_id for record in gateway_service.get().registry.list()
    }


def test_delete_removes_saved_configuration_and_gateway_before_restart(
    configured_workspace,
):
    assert "example/original-model" in _models()
    result = handle_delete_provider("example")
    assert result["ok"] is True
    assert "example" not in json.loads(configured_workspace.read_text())
    assert get_provider("example") is None
    assert "example/original-model" not in _models()
    clear_providers()
    assert load_providers_from_config(configured_workspace.parent) == 0
    assert get_provider("example") is None


def test_patch_persists_model_endpoint_and_reference_and_refreshes_gateway(
    configured_workspace,
):
    result = handle_update_provider(
        "example",
        {
            "name": "Updated",
            "api_base_url": "https://updated.example.test/v1",
            "model": "updated-model",
            "credential_ref": "env:OTHER_FAKE_PROVIDER_KEY",
        },
    )
    assert result["ok"] is True
    saved = json.loads(configured_workspace.read_text())["example"]
    assert saved["model"] == "updated-model"
    assert saved["endpoint"] == "https://updated.example.test/v1/chat/completions"
    assert saved["credential_ref"] == "env:OTHER_FAKE_PROVIDER_KEY"
    assert _models() == {"example/updated-model"}
    clear_providers()
    assert load_providers_from_config(configured_workspace.parent) == 1
    assert get_provider("example").model == "updated-model"
    import subprocess
    import sys

    restored = subprocess.run(
        [
            sys.executable,
            "-c",
            "import json; from nous_runtime.cli.provider_setup import load_providers_from_config; from nous_runtime.services.providers import get_provider; load_providers_from_config(); print(json.dumps({'model': get_provider('example').model}))",
        ],
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert restored.returncode == 0, restored.stderr
    assert json.loads(restored.stdout)["model"] == "updated-model"


def test_invalid_patch_preserves_original_adapter_gateway_and_bytes(
    configured_workspace,
):
    original = configured_workspace.read_bytes()
    provider = get_provider("example")
    gateway = gateway_service.get()
    result = handle_update_provider("example", {"credential_ref": "plaintext-value"})
    assert result["ok"] is False
    assert "plaintext-value" not in json.dumps(result)
    assert get_provider("example") is provider
    assert gateway_service.get() is gateway
    assert configured_workspace.read_bytes() == original


@pytest.mark.parametrize(
    "patch", [{"enabled": False}, {"model": None}, {"capability_models": []}]
)
def test_unsupported_or_invalid_patch_cannot_claim_success(configured_workspace, patch):
    original = configured_workspace.read_bytes()
    result = handle_update_provider("example", patch)
    assert result["ok"] is False
    assert configured_workspace.read_bytes() == original


def test_corrupt_configuration_is_not_overwritten_by_create(configured_workspace):
    configured_workspace.write_text('{"example":')
    original = configured_workspace.read_bytes()
    with pytest.raises(ValueError):
        register_provider_from_config(
            "another", "Another", "https://other.example.test/v1"
        )
    assert configured_workspace.read_bytes() == original
    assert get_provider("example") is not None
    assert get_provider("another") is None


def test_patch_preserves_unedited_settings_and_other_providers(configured_workspace):
    from nous_runtime.cli.provider_setup import _save_provider_config

    original = json.loads(configured_workspace.read_text())["example"]
    original.update({"max_concurrency": 2, "context_window": 4096})
    _save_provider_config("example", original)
    register_provider_from_config(
        "other", "Other", "https://other.example.test/v1", model="other-model"
    )
    other = json.loads(configured_workspace.read_text())["other"]
    result = handle_update_provider("example", {"name": "Renamed"})
    assert result["ok"] is True
    saved = json.loads(configured_workspace.read_text())
    assert saved["other"] == other
    assert saved["example"] == {**original, "name": "Renamed"}
    assert get_provider("example").max_concurrency == 2
    assert _models() == {"example/original-model", "other/other-model"}


def test_configuration_refresh_does_not_probe_health_or_resolve_secrets(
    configured_workspace, monkeypatch
):
    from nous_runtime.provider.adapters.openai import OpenAIProvider

    monkeypatch.setattr(
        OpenAIProvider,
        "health",
        lambda *_: pytest.fail("Configuration must not probe Provider health"),
    )
    assert handle_update_provider("example", {"model": "metadata-model"})["ok"] is True
    assert _models() == {"example/metadata-model"}


def test_write_failure_keeps_original_registration_and_cleans_temporary_file(
    configured_workspace, monkeypatch
):
    import os

    previous = configured_workspace.read_bytes()
    provider = get_provider("example")
    gateway = gateway_service.get()
    replace = os.replace

    def fail_configuration_write(source, destination):
        if destination == configured_workspace:
            raise OSError("fixture write refused")
        return replace(source, destination)

    monkeypatch.setattr(os, "replace", fail_configuration_write)
    result = handle_update_provider("example", {"model": "new-model"})
    assert result["ok"] is False
    assert configured_workspace.read_bytes() == previous
    assert get_provider("example") is provider
    assert gateway_service.get() is gateway
    assert not list(configured_workspace.parent.glob(".providers-*.tmp"))


def test_refresh_failure_is_not_rollback_or_ready_and_does_not_expose_errors(
    configured_workspace, monkeypatch
):
    calls = []
    fake_value = "fixture-only-sensitive-value"

    def fail_refresh(*args, **kwargs):
        calls.append(True)
        raise RuntimeError(fake_value)

    monkeypatch.setattr(gateway_service, "configure_from_providers", fail_refresh)
    result = handle_update_provider("example", {"model": "new-model"})
    assert result["ok"] is False
    assert fake_value not in json.dumps(result)
    assert calls == [True]
    assert gateway_service.get(required=False) is None
    assert (
        json.loads(configured_workspace.read_text())["example"]["model"] == "new-model"
    )


def test_concurrent_process_writers_preserve_original_and_each_other(
    configured_workspace,
):
    from concurrent.futures import ThreadPoolExecutor
    import subprocess
    import sys

    program = """
import sys
from nous_runtime.cli.provider_setup import _save_provider_config
_save_provider_config(sys.argv[1], {"name": sys.argv[1], "model": sys.argv[1]})
"""

    def save(index):
        return subprocess.run(
            [sys.executable, "-c", program, f"writer-{index}"],
            capture_output=True,
            text=True,
            timeout=20,
        )

    with ThreadPoolExecutor(max_workers=4) as workers:
        results = list(workers.map(save, range(4)))
    assert all(result.returncode == 0 for result in results), [
        result.stderr for result in results
    ]
    saved = json.loads(configured_workspace.read_text())
    assert set(saved) == {"example", *(f"writer-{index}" for index in range(4))}
    assert saved["example"]["model"] == "original-model"
    for index in range(4):
        assert saved[f"writer-{index}"] == {
            "name": f"writer-{index}",
            "model": f"writer-{index}",
        }
    assert not list(configured_workspace.parent.glob(".providers-*.tmp"))


def test_authenticated_http_patch_uses_persistence_and_current_model_catalog(
    configured_workspace, monkeypatch
):
    import threading
    from urllib.error import HTTPError
    from urllib.request import Request, urlopen

    from nous_runtime.api.server import RuntimeAPIHandler, RuntimeHTTPServer
    from nous_runtime.services.lifecycle import run_migrations, seed_capabilities

    token = "provider.lifecycle.fake.session"
    monkeypatch.setenv("NOUS_API_TOKEN", token)
    monkeypatch.setenv("NOUS_RUNTIME_MODE", "strict")
    monkeypatch.setenv(
        "NOUS_DATA_DIR", str(configured_workspace.parent / "capability-data")
    )
    monkeypatch.setattr("nous_runtime.governance.gate._gate_instance", None)
    run_migrations()
    assert seed_capabilities() > 0
    server = RuntimeHTTPServer(("127.0.0.1", 0), RuntimeAPIHandler)
    owner = threading.Thread(target=server.serve_forever, daemon=True)
    owner.start()
    endpoint = f"http://127.0.0.1:{server.server_port}"
    try:
        with pytest.raises(HTTPError) as denied:
            urlopen(
                Request(
                    endpoint + "/api/v1/providers/example",
                    method="PATCH",
                    data=b'{"model":"unauthenticated-model"}',
                    headers={"Content-Type": "application/json"},
                ),
                timeout=5,
            )
        assert denied.value.code == 401
        denied.value.close()
        assert get_provider("example").model == "original-model"
        with urlopen(
            Request(
                endpoint + "/api/v1/providers",
                headers={"Authorization": "Bearer " + token},
            ),
            timeout=5,
        ) as response:
            metadata = json.load(response)["data"]
        assert metadata[0]["configuration"]["model"] == "original-model"
        assert metadata[0]["configuration"]["has_reference"] is True
        assert "FAKE_PROVIDER_KEY" not in json.dumps(metadata)
        with urlopen(
            Request(
                endpoint + "/api/v1/providers/example",
                method="PATCH",
                data=b'{"model":"http-model"}',
                headers={
                    "Content-Type": "application/json",
                    "Authorization": "Bearer " + token,
                },
            ),
            timeout=5,
        ) as response:
            result = json.load(response)
        assert result["ok"] is True
        assert (
            json.loads(configured_workspace.read_text())["example"]["model"]
            == "http-model"
        )
        with urlopen(
            Request(
                endpoint + "/api/v1/models",
                headers={"Authorization": "Bearer " + token},
            ),
            timeout=5,
        ) as response:
            catalog = json.load(response)["data"]["models"]
        assert [(model["model_id"], model["provider_model"]) for model in catalog] == [
            ("example/http-model", "http-model")
        ]
        with pytest.raises(HTTPError) as approval:
            urlopen(
                Request(
                    endpoint + "/api/v1/providers/example",
                    method="DELETE",
                    headers={"Authorization": "Bearer " + token},
                ),
                timeout=5,
            )
        assert approval.value.code == 403
        rejection = json.load(approval.value)
        approval.value.close()
        assert rejection["error"]["code"] == "NOUS_APPROVAL_REQUIRED"
        assert get_provider("example").model == "http-model"
        assert "example" in json.loads(configured_workspace.read_text())
    finally:
        server.shutdown()
        server.server_close()
        owner.join(timeout=5)
    assert not owner.is_alive()
