from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from nous_runtime.cli.provider_experience import (
    diagnose_provider,
    fetch_provider_models,
    normalize_capability_mapping,
    probe_provider_config,
    render_provider_dashboard,
    render_provider_doctor,
)
from nous_runtime.provider.adapters.anthropic import AnthropicProvider
from nous_runtime.provider.adapters.openai import OpenAIProvider
from nous_runtime.provider.credentials import (
    credential_status,
    describe_credential_reference,
    resolve_credential,
)


class _Response:
    status = 200

    def __init__(self, payload: dict | None = None):
        self.payload = payload or {"choices": [{"message": {"content": "OK"}}]}

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def read(self, limit: int = -1) -> bytes:
        return json.dumps(self.payload).encode("utf-8")


def _write_config(root: Path, data: dict) -> Path:
    workspace = root / ".nous"
    workspace.mkdir()
    (workspace / "providers.json").write_text(
        json.dumps(data),
        encoding="utf-8",
    )
    return workspace


def test_capability_mapping_accepts_product_names_without_inventing_ids():
    assert normalize_capability_mapping(
        ["Reasoning", "Coding", "Embedding", "Vision", "Speech", "Rerank"]
    ) == (
        "model.reason",
        "model.code",
        "model.embed",
        "model.vision",
        "model.transcribe",
        "model.rerank",
    )
    assert normalize_capability_mapping(["unknown"]) == ()


def test_environment_credential_reference_never_displays_value(monkeypatch):
    monkeypatch.setenv("SPRINT13_PROVIDER_KEY", "private-provider-value")

    assert resolve_credential("env:SPRINT13_PROVIDER_KEY") == "private-provider-value"
    assert describe_credential_reference("env:SPRINT13_PROVIDER_KEY") == (
        "Environment variable - SPRINT13_PROVIDER_KEY"
    )
    status = credential_status("env:SPRINT13_PROVIDER_KEY")
    assert status.available is True
    assert "private-provider-value" not in repr(status)


def test_provider_dashboard_marks_configured_but_unavailable_capabilities(
    monkeypatch,
    tmp_path,
):
    _write_config(
        tmp_path,
        {
            "local": {
                "name": "Local HTTP",
                "kind": "local-http",
                "endpoint": "http://127.0.0.1:8000/v1/chat/completions",
                "model": "local-model",
                "context_window": 32768,
                "capability_mapping": ["model.reason", "model.transcribe"],
            }
        },
    )
    monkeypatch.setattr(
        "nous_runtime.services.providers.list_provider_summaries",
        lambda: [],
    )

    rendered = render_provider_dashboard(tmp_path)

    assert "Configured Providers" in rendered
    assert "Local HTTP" in rendered
    assert "Reasoning" in rendered
    assert "Speech (configured only)" in rendered
    assert "32768" in rendered


def test_probe_uses_reference_and_returns_only_safe_metadata(monkeypatch):
    monkeypatch.setenv("SPRINT13_PROVIDER_KEY", "private-provider-value")
    captured = {}

    def urlopen(request, timeout):
        captured["request"] = request
        captured["timeout"] = timeout
        return _Response()

    monkeypatch.setattr("urllib.request.urlopen", urlopen)
    result = probe_provider_config(
        "example",
        {
            "kind": "openai-compatible",
            "endpoint": "https://provider.invalid/v1/chat/completions",
            "model": "example-model",
            "credential_ref": "env:SPRINT13_PROVIDER_KEY",
        },
        "test",
    )

    assert result["ok"] is True
    assert result["status"] == "healthy"
    assert result["credential"] == "Environment variable - SPRINT13_PROVIDER_KEY"
    assert "private-provider-value" not in json.dumps(result)
    assert captured["request"].get_header("Authorization") == (
        "Bearer private-provider-value"  # security-scan: fixture
    )


def test_openai_adapter_uses_per_provider_endpoint_and_embedding(monkeypatch):
    monkeypatch.setenv("SPRINT13_PROVIDER_KEY", "provider-key")
    captured = {}

    def urlopen(request, timeout):
        captured["url"] = request.full_url
        captured["body"] = json.loads(request.data)
        return _Response({"data": [{"embedding": [0.1, 0.2, 0.3]}]})

    monkeypatch.setattr("urllib.request.urlopen", urlopen)
    provider = OpenAIProvider(
        provider_id="example",
        endpoint="https://provider.invalid/v1/chat/completions",
        model="embed-model",
        credential_ref="env:SPRINT13_PROVIDER_KEY",
        capabilities=("model.embed",),
    )

    result = provider.invoke("model.embed", text="hello")

    assert result["ok"] is True
    assert result["vector_dim"] == 3
    assert captured["url"] == "https://provider.invalid/v1/embeddings"
    assert captured["body"]["input"] == "hello"


def test_anthropic_adapter_uses_messages_protocol(monkeypatch):
    monkeypatch.setenv("SPRINT13_ANTHROPIC_KEY", "anthropic-key")
    captured = {}

    def urlopen(request, timeout):
        captured["headers"] = dict(request.header_items())
        captured["body"] = json.loads(request.data)
        return _Response({"content": [{"type": "text", "text": "done"}]})

    monkeypatch.setattr("urllib.request.urlopen", urlopen)
    provider = AnthropicProvider(
        provider_id="anthropic-example",
        model="claude-example",
        credential_ref="env:SPRINT13_ANTHROPIC_KEY",
    )

    result = provider.invoke("model.reason", prompt="hello")

    assert result == {"ok": True, "content": "done", "model": "claude-example"}
    assert captured["body"]["messages"][0]["content"] == "hello"
    assert captured["headers"]["X-api-key"] == "anthropic-key"


def test_service_presets_map_brands_to_existing_provider_kinds():
    from nous_runtime.cli.provider_setup import SERVICE_PRESETS

    assert tuple(SERVICE_PRESETS) == (
        "openai",
        "deepseek",
        "claude",
        "ollama",
        "openrouter",
        "siliconflow",
        "moonshot",
        "azure-openai",
        "generic-openai-compatible",
        "local-http",
        "custom",
    )
    assert SERVICE_PRESETS["deepseek"]["kind"] == "openai-compatible"
    assert SERVICE_PRESETS["claude"]["kind"] == "anthropic-compatible"
    assert SERVICE_PRESETS["ollama"]["kind"] == "ollama"


def test_fetch_provider_models_accepts_openai_and_ollama_catalogs(monkeypatch):
    responses = iter(
        (
            _Response({"data": [{"id": "alpha"}, {"id": "beta"}]}),
            _Response({"models": [{"name": "qwen3:8b"}, {"model": "gemma3"}]}),
        )
    )
    monkeypatch.setattr("urllib.request.urlopen", lambda request, timeout: next(responses))

    assert fetch_provider_models({"models_endpoint": "https://example.invalid/models"}) == (
        "alpha",
        "beta",
    )
    assert fetch_provider_models({"models_endpoint": "http://localhost:11434/api/tags"}) == (
        "qwen3:8b",
        "gemma3",
    )


def test_provider_wizard_persists_reference_not_secret(monkeypatch, tmp_path):
    from nous_runtime.cli.provider_setup import run_provider_setup
    from nous_runtime.provider import unregister_adapter

    workspace = _write_config(tmp_path, {})
    monkeypatch.setattr(
        "nous_runtime.project.workspace.find_workspace",
        lambda: workspace,
    )
    monkeypatch.setattr(
        "nous_runtime.cli.provider_setup.fetch_provider_models",
        lambda config: ("deepseek-v4-flash", "deepseek-v4-pro"),
    )
    answers = iter(
        (
            "2",
            "wizard-provider",
            "http://localhost:9999/v1",
            "1",
            "WIZARD_PROVIDER_KEY",
            "2",
            "n",
            "Reasoning, Coding, Speech",
            "n",
        )
    )
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))

    result = run_provider_setup()

    try:
        data = json.loads((workspace / "providers.json").read_text(encoding="utf-8"))
        config = data["wizard-provider"]
        assert config["service"] == "deepseek"
        assert config["kind"] == "openai-compatible"
        assert config["endpoint"] == "http://localhost:9999/v1/chat/completions"
        assert config["model"] == "deepseek-v4-pro"
        assert config["credential_ref"] == "env:WIZARD_PROVIDER_KEY"
        assert config["api_key_env"] == "WIZARD_PROVIDER_KEY"
        assert "api_key" not in config
        assert "Provider saved." in result
        assert "model.transcribe" in config["capability_mapping"]
        assert "model.transcribe" not in config["executable_capabilities"]
    finally:
        unregister_adapter("wizard-provider")


def test_provider_wizard_rejects_pasted_secret_as_environment_name(
    monkeypatch,
    tmp_path,
    capsys,
):
    from nous_runtime.cli.provider_setup import run_provider_setup

    workspace = _write_config(tmp_path, {})
    monkeypatch.setattr(
        "nous_runtime.project.workspace.find_workspace",
        lambda: workspace,
    )
    rejected = "sk-example-secret-value"
    answers = iter(
        (
            "2",
            "unsafe-provider",
            "https://api.deepseek.com",
            "1",
            rejected,
        )
    )
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))

    result = run_provider_setup()

    data = json.loads((workspace / "providers.json").read_text(encoding="utf-8"))
    assert "credential configuration failed" in result
    assert "unsafe-provider" not in data
    assert rejected not in capsys.readouterr().out


def test_provider_wizard_does_not_save_failed_probe_by_default(
    monkeypatch,
    tmp_path,
):
    from nous_runtime.cli.provider_setup import run_provider_setup

    workspace = _write_config(tmp_path, {})
    monkeypatch.setattr(
        "nous_runtime.project.workspace.find_workspace",
        lambda: workspace,
    )
    monkeypatch.setattr(
        "nous_runtime.cli.provider_setup.fetch_provider_models",
        lambda config: ("deepseek-v4-flash", "deepseek-v4-pro"),
    )
    monkeypatch.setattr(
        "nous_runtime.cli.provider_setup.probe_provider_config",
        lambda provider_id, config, operation: {
            "ok": False,
            "provider_id": provider_id,
            "operation": operation,
            "error": "credential unavailable",
        },
    )
    answers = iter(
        (
            "2",
            "failed-provider",
            "https://api.deepseek.com",
            "1",
            "FAILED_PROVIDER_KEY",
            "1",
            "y",
            "y",
            "",
        )
    )
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))

    result = run_provider_setup()

    data = json.loads((workspace / "providers.json").read_text(encoding="utf-8"))
    assert "was not saved" in result
    assert "failed-provider" not in data

def test_provider_quick_keeps_entered_key_process_scoped(monkeypatch, tmp_path):
    from nous_runtime.cli.provider_setup import run_provider_setup
    from nous_runtime.provider import unregister_adapter

    workspace = _write_config(tmp_path, {})
    monkeypatch.setattr("nous_runtime.project.workspace.find_workspace", lambda: workspace)
    monkeypatch.setattr(
        "nous_runtime.cli.provider_setup.fetch_provider_models",
        lambda config: ("deepseek-v4-flash",),
    )
    monkeypatch.setattr(
        "nous_runtime.cli.provider_setup._prompt_secret",
        lambda label, default="": "temporary-secret",
    )
    monkeypatch.setattr("builtins.input", lambda prompt="": "2")

    result = run_provider_setup(quick=True)

    try:
        raw = (workspace / "providers.json").read_text(encoding="utf-8")
        config = json.loads(raw)["deepseek"]
        assert "temporary-secret" not in raw
        assert config["credential_scope"] == "process"
        assert config["credential_ref"] == "env:NOUS_SESSION_PROVIDER_DEEPSEEK_KEY"
        assert "Provider saved." in result
    finally:
        monkeypatch.delenv("NOUS_SESSION_PROVIDER_DEEPSEEK_KEY", raising=False)
        unregister_adapter("deepseek")


def test_provider_doctor_reports_safe_diagnostics(monkeypatch, tmp_path):
    workspace = _write_config(
        tmp_path,
        {
            "doctor-provider": {
                "name": "Doctor Provider",
                "service": "openai",
                "kind": "openai-compatible",
                "endpoint": "https://provider.invalid/v1/chat/completions",
                "models_endpoint": "https://provider.invalid/v1/models",
                "model": "doctor-model",
                "credential_ref": "env:DOCTOR_PROVIDER_KEY",
            }
        },
    )
    monkeypatch.setenv("DOCTOR_PROVIDER_KEY", "private-doctor-value")

    def urlopen(request, timeout):
        if request.full_url.endswith("/models"):
            return _Response({"data": [{"id": "doctor-model"}]})
        return _Response()

    monkeypatch.setattr("urllib.request.urlopen", urlopen)
    result = diagnose_provider("doctor-provider", workspace)
    rendered = render_provider_doctor(result)

    assert result["ok"] is True
    assert result["models_discovered"] == 1
    assert result["model_available"] is True
    assert "Authentication  passed" in rendered
    assert "protocol-supported; not exercised" in rendered
    assert "private-doctor-value" not in json.dumps(result)


def test_provider_cli_doctor_runs_safe_diagnostics(monkeypatch, tmp_path):
    from nous_runtime.cli.main import app

    _write_config(
        tmp_path,
        {
            "cli-doctor": {
                "name": "CLI Doctor",
                "service": "openai",
                "kind": "openai-compatible",
                "endpoint": "https://provider.invalid/v1/chat/completions",
                "models_endpoint": "https://provider.invalid/v1/models",
                "model": "doctor-model",
                "credential_ref": "env:CLI_DOCTOR_KEY",
            }
        },
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("CLI_DOCTOR_KEY", "private-cli-doctor-value")

    def urlopen(request, timeout):
        if request.full_url.endswith("/models"):
            return _Response({"data": [{"id": "doctor-model"}]})
        return _Response()

    monkeypatch.setattr("urllib.request.urlopen", urlopen)
    result = CliRunner().invoke(app, ["provider", "doctor", "cli-doctor"])

    assert result.exit_code == 0
    assert "Provider Doctor" in result.stdout
    assert "Authentication  passed" in result.stdout
    assert "private-cli-doctor-value" not in result.stdout

def test_provider_cli_dashboard_uses_configured_tree(monkeypatch, tmp_path):
    from nous_runtime.cli.main import app

    _write_config(
        tmp_path,
        {
            "cli-provider": {
                "name": "CLI Provider",
                "kind": "openai-compatible",
                "model": "cli-model",
                "capability_mapping": ["model.reason"],
            }
        },
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        "nous_runtime.services.providers.list_provider_summaries",
        lambda: [],
    )

    result = CliRunner().invoke(app, ["provider", "list"])

    assert result.exit_code == 0
    assert "Configured Providers" in result.stdout
    assert "CLI Provider" in result.stdout


def test_terminal_provider_completion_exposes_diagnostics():
    from nous_runtime.cli.shell_v2 import _command_suggestions

    assert [item.text for item in _command_suggestions("/provider p")] == [
        "/provider ping"
    ]
    assert [item.text for item in _command_suggestions("/provider h")] == [
        "/provider health"
    ]
    assert [item.text for item in _command_suggestions("/provider d")] == [
        "/provider doctor"
    ]
    assert [item.text for item in _command_suggestions("/provider q")] == [
        "/provider quick"
    ]

def test_provider_registry_returns_id_and_cleans_owned_capabilities(tmp_path, monkeypatch):
    from nous_runtime.provider.base import Provider
    from nous_runtime.provider.registry import ProviderRegistry
    from remote_terminal.nous_core.capability import get_capability

    class ReferenceProvider(Provider):
        provider_id = "reference-provider"
        provider_name = "Reference Provider"

        def list_capabilities(self):
            return ["reference.greet"]

        def invoke(self, capability_id, **params):
            return {"ok": capability_id == "reference.greet", "name": params.get("name", "World")}

        def health(self):
            return {"status": "ok"}

    monkeypatch.chdir(tmp_path)
    registry = ProviderRegistry()
    registry.remove(ReferenceProvider.provider_id)
    try:
        provider_id = registry.install(ReferenceProvider())
        assert provider_id == ReferenceProvider.provider_id
        assert get_capability("reference.greet")["provider"] == provider_id
    finally:
        registry.remove(ReferenceProvider.provider_id)

    assert get_capability("reference.greet") is None
