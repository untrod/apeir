from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from nous_runtime.cli.provider_experience import (
    diagnose_provider,
    render_provider_doctor,
    render_provider_status,
)
from nous_runtime.provider.credentials import (
    credential_fix_suggestion,
    credential_status,
    resolve_credential,
    validate_environment_variable_name,
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
    (workspace / "providers.json").write_text(json.dumps(data), encoding="utf-8")
    return workspace


def test_invalid_reference_error_is_safe_and_actionable():
    rejected = "bad name!"
    with pytest.raises(ValueError) as excinfo:
        resolve_credential(f"env:{rejected}")
    message = str(excinfo.value)
    assert "Invalid environment-variable reference" in message
    assert "nous provider add" in message
    assert "nous provider doctor" in message
    assert rejected not in message


def test_environment_variable_name_rejects_pasted_secret_without_echo():
    rejected = "sk-example-secret-value"
    with pytest.raises(ValueError) as excinfo:
        validate_environment_variable_name(rejected)
    assert "not the API key itself" in str(excinfo.value)
    assert rejected not in str(excinfo.value)


def test_credential_fix_suggestion_for_missing_env(monkeypatch):
    monkeypatch.delenv("NOUS_SESSION_PROVIDER_DEEPSEEK_KEY", raising=False)
    status = credential_status("env:NOUS_SESSION_PROVIDER_DEEPSEEK_KEY")
    assert status.available is False
    suggestion = credential_fix_suggestion(status)
    assert "NOUS_SESSION_PROVIDER_DEEPSEEK_KEY" in suggestion
    assert "nous provider add" in suggestion

    monkeypatch.setenv("NOUS_SESSION_PROVIDER_DEEPSEEK_KEY", "session-value")
    status = credential_status("env:NOUS_SESSION_PROVIDER_DEEPSEEK_KEY")
    assert status.available is True
    assert credential_fix_suggestion(status) == ""


def test_credential_fix_suggestion_for_unparseable_reference():
    status = credential_status("env:bad name!")
    assert status.available is False
    suggestion = credential_fix_suggestion(status)
    assert "nous provider add" in suggestion
    assert "nous provider doctor" in suggestion


def test_doctor_shows_reference_status_and_fix_for_missing_credential(
    monkeypatch,
    tmp_path,
):
    workspace = _write_config(
        tmp_path,
        {
            "credential-doctor": {
                "name": "Credential Doctor",
                "service": "deepseek",
                "kind": "openai-compatible",
                "endpoint": "https://provider.invalid/v1/chat/completions",
                "model": "doctor-model",
                "credential_ref": "env:MISSING_DOCTOR_KEY",
            }
        },
    )
    monkeypatch.delenv("MISSING_DOCTOR_KEY", raising=False)
    monkeypatch.setattr("urllib.request.urlopen", lambda request, timeout: _Response())

    result = diagnose_provider("credential-doctor", workspace)
    rendered = render_provider_doctor(result)

    assert result["credential_available"] is False
    assert "MISSING_DOCTOR_KEY" in result["credential_reference"]
    assert "MISSING_DOCTOR_KEY" in result["credential_fix"]
    assert "Reference" in rendered
    assert "MISSING_DOCTOR_KEY" in rendered
    assert "Cred status     Missing" in rendered
    assert "Fix" in rendered


def test_doctor_omits_fix_when_credential_available(monkeypatch, tmp_path):
    workspace = _write_config(
        tmp_path,
        {
            "healthy-doctor": {
                "name": "Healthy Doctor",
                "service": "deepseek",
                "kind": "openai-compatible",
                "endpoint": "https://provider.invalid/v1/chat/completions",
                "model": "doctor-model",
                "credential_ref": "env:HEALTHY_DOCTOR_KEY",
            }
        },
    )
    monkeypatch.setenv("HEALTHY_DOCTOR_KEY", "private-doctor-value")
    monkeypatch.setattr("urllib.request.urlopen", lambda request, timeout: _Response())

    result = diagnose_provider("healthy-doctor", workspace)
    rendered = render_provider_doctor(result)

    assert result["credential_available"] is True
    assert result["credential_fix"] == ""
    assert "Cred status     Available" in rendered
    assert "  Fix  " not in rendered
    assert "private-doctor-value" not in json.dumps(result)
    assert "private-doctor-value" not in rendered


def test_render_provider_status_lists_provider_fields():
    rendered = render_provider_status(
        [
            {
                "provider_id": "deepseek",
                "name": "DeepSeek",
                "model": "deepseek-v4-flash",
                "health": "ok",
                "latency_ms": 577,
                "credential": credential_status(""),
            }
        ]
    )
    assert "DeepSeek" in rendered
    assert "deepseek-v4-flash" in rendered
    assert "Health      ok" in rendered
    assert "577 ms" in rendered
    assert "Credential" in rendered

    assert "None configured" in render_provider_status([])


def test_provider_status_command(monkeypatch, tmp_path):
    from nous_runtime.cli.main import app

    _write_config(
        tmp_path,
        {
            "cli-status": {
                "name": "CLI Status",
                "kind": "openai-compatible",
                "model": "status-model",
                "credential_ref": "env:CLI_STATUS_KEY",
                "capability_mapping": ["model.reason"],
            }
        },
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("CLI_STATUS_KEY", "status-secret-value")
    monkeypatch.setattr(
        "nous_runtime.services.providers.list_provider_summaries",
        lambda: [],
    )

    result = CliRunner().invoke(app, ["provider", "status"])
    assert result.exit_code == 0
    assert "CLI Status" in result.stdout
    assert "status-model" in result.stdout
    assert "Health" in result.stdout
    assert "Credential" in result.stdout
    assert "status-secret-value" not in result.stdout

    json_result = CliRunner().invoke(app, ["provider", "status", "--json"])
    assert json_result.exit_code == 0
    payload = json.loads(json_result.stdout)
    assert payload[0]["provider_id"] == "cli-status"
    assert payload[0]["credential"]["available"] is True
    assert "status-secret-value" not in json_result.stdout


# DeepSeek credential reference regression tests


def test_deepseek_credential_available_when_env_set(monkeypatch):
    """DeepSeek env:NOUS_SESSION_PROVIDER_DEEPSEEK_KEY → Available."""
    monkeypatch.setenv("NOUS_SESSION_PROVIDER_DEEPSEEK_KEY", "deepseek-session-key")
    status = credential_status("env:NOUS_SESSION_PROVIDER_DEEPSEEK_KEY")
    assert status.available is True
    assert status.source == "Environment variable"
    assert status.detail == "Available"


def test_deepseek_credential_missing_when_env_unset(monkeypatch):
    """DeepSeek env:NOUS_SESSION_PROVIDER_DEEPSEEK_KEY (missing) → Missing."""
    monkeypatch.delenv("NOUS_SESSION_PROVIDER_DEEPSEEK_KEY", raising=False)
    status = credential_status("env:NOUS_SESSION_PROVIDER_DEEPSEEK_KEY")
    assert status.available is False
    assert status.source == "Environment variable"
    assert status.detail == "Missing"


def test_not_required_only_when_explicitly_declared():
    """Not required is only returned when authentication_required=False."""
    # Empty ref + no declaration → Not configured
    status = credential_status("")
    assert status.available is False
    assert status.detail == "Not configured"

    # Empty ref + explicit False → Not required
    status = credential_status("", authentication_required=False)
    assert status.available is True
    assert status.detail == "Not required"

    # Empty ref + explicit True → still Not configured
    status = credential_status("", authentication_required=True)
    assert status.available is False
    assert status.detail == "Not configured"


def test_deepseek_credential_never_shows_not_required():
    """DeepSeek should never display 'Not required' — it always needs auth."""
    # With a real env reference (even if env var missing)
    status = credential_status("env:DEEPSEEK_API_KEY")
    assert status.detail != "Not required"
    assert "Not required" not in status.detail

    # With session env reference (even if env var missing)
    status = credential_status("env:NOUS_SESSION_PROVIDER_DEEPSEEK_KEY")
    assert status.detail != "Not required"
    assert "Not required" not in status.detail


def test_credential_status_preserves_env_label():
    """Environment variable references show 'Environment variable' source."""
    status = credential_status("env:ANY_KEY_NAME")
    assert status.source == "Environment variable"


def test_credential_status_preserves_secret_store_label():
    """Secret store references show 'Secret store' source."""
    status = credential_status("secret:test-svc:test-account")
    # Will fail because keyring is not installed, but source label is correct
    assert status.source in ("Secret store", "secret-store")


def _write_raw_config(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


def test_legacy_api_key_config_detected_as_direct_credential(tmp_path, monkeypatch):
    """Legacy config with bare api_key → _has_direct_credential → secret ref."""
    from nous_runtime.cli.provider_experience import (
        _credential_ref,
        read_provider_configs,
    )

    workspace = tmp_path / ".nous"
    _write_raw_config(
        workspace / "providers.json",
        {
            "legacy-provider": {
                "name": "Legacy",
                "kind": "openai-compatible",
                "model": "old-model",
                "api_key": "sk-legacy-key-material",
            }
        },
    )
    monkeypatch.chdir(tmp_path)

    configs = read_provider_configs()
    assert "legacy-provider" in configs
    cfg = configs["legacy-provider"]
    # api_key must be stripped
    assert "api_key" not in cfg
    # _has_direct_credential must be set
    assert cfg.get("_has_direct_credential") is True
    # _credential_ref returns a secret-store reference
    ref = _credential_ref(cfg)
    assert ref == "secret:nous-legacy:direct-key"


def test_config_without_api_key_has_no_direct_credential_flag(tmp_path, monkeypatch):
    """Config with credential_ref but no bare api_key → no legacy flag."""
    from nous_runtime.cli.provider_experience import read_provider_configs

    workspace = tmp_path / ".nous"
    _write_raw_config(
        workspace / "providers.json",
        {
            "modern-provider": {
                "name": "Modern",
                "kind": "openai-compatible",
                "model": "new-model",
                "credential_ref": "env:MY_KEY",
            }
        },
    )
    monkeypatch.chdir(tmp_path)

    configs = read_provider_configs()
    cfg = configs["modern-provider"]
    assert cfg.get("_has_direct_credential") is None
    assert cfg.get("credential_ref") == "env:MY_KEY"


def test_register_provider_from_config_persists_reference_only(tmp_path, monkeypatch):
    from nous_runtime.cli import provider_setup

    monkeypatch.delenv("NOUS_WORKSPACE_ROOT", raising=False)
    (tmp_path / ".nous").mkdir()
    monkeypatch.chdir(tmp_path)
    registered: list[tuple[str, dict]] = []
    monkeypatch.setattr(
        provider_setup,
        "_register_provider_runtime",
        lambda provider_id, *, config: registered.append((provider_id, config)),
    )

    assert provider_setup.register_provider_from_config(
        provider_id="deepseek",
        name="DeepSeek",
        api_base_url="https://api.deepseek.com",
        credential_ref="env:DEEPSEEK_API_KEY",
        capabilities=["Reasoning", "Coding"],
    )

    config_path = tmp_path / ".nous" / "providers.json"
    payload = json.loads(config_path.read_text(encoding="utf-8"))
    saved = payload["deepseek"]
    assert saved["credential_ref"] == "env:DEEPSEEK_API_KEY"
    assert saved["api_key_env"] == "DEEPSEEK_API_KEY"
    assert saved["structured_output_mode"] == "json_object"
    assert "api_key" not in saved
    assert registered[0][0] == "deepseek"


def test_register_provider_from_config_rejects_secret_as_env_name(
    tmp_path, monkeypatch
):
    import pytest
    from nous_runtime.cli.provider_setup import register_provider_from_config

    monkeypatch.delenv("NOUS_WORKSPACE_ROOT", raising=False)
    monkeypatch.chdir(tmp_path)
    with pytest.raises(ValueError, match="environment-variable name"):
        register_provider_from_config(
            provider_id="deepseek",
            name="DeepSeek",
            api_base_url="https://api.deepseek.com",
            credential_ref="env:sk-not-a-variable-name",
            capabilities=["Reasoning"],
        )
