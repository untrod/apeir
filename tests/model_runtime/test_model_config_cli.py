from __future__ import annotations

import json

import yaml
from typer.testing import CliRunner

from nous_runtime.cli.main import app
from nous_runtime.model_runtime.registry import ModelRuntimeRegistry


def payload() -> dict:
    return {
        "schema_version": 1,
        "providers": {
            "local": {
                "kind": "local_service",
                "endpoint": "http://127.0.0.1:11434",
                "credential_ref": "env:NOUS_LOCAL_MODEL_KEY",
            }
        },
        "models": [
            {
                "model_id": "local/cli",
                "display_name": "CLI Model",
                "provider_id": "local",
                "endpoint_type": "local_service",
                "capabilities": ["reasoning"],
                "modalities": ["text"],
                "enabled": True,
            }
        ],
        "defaults": {"planner": "local/cli"},
    }


def test_config_cli_validate_plan_apply_export_and_remove(
    tmp_path,
    monkeypatch,
) -> None:
    workspace = tmp_path / ".nous"
    config_path = tmp_path / "models.yaml"
    exported_path = tmp_path / "exported.yaml"
    config_path.write_text(
        yaml.safe_dump(payload()),
        encoding="utf-8",
    )
    monkeypatch.setenv("NOUS_WORKSPACE_ROOT", str(workspace))
    runner = CliRunner()

    validated = runner.invoke(
        app,
        ["models", "config", "validate", str(config_path)],
    )
    assert validated.exit_code == 0
    assert json.loads(validated.stdout)["valid"] is True

    planned = runner.invoke(
        app,
        ["models", "config", "plan", str(config_path)],
    )
    assert planned.exit_code == 0
    assert json.loads(planned.stdout)["actions"][0]["action"] == "add"

    applied = runner.invoke(
        app,
        ["models", "config", "apply", str(config_path)],
    )
    assert applied.exit_code == 0
    registry = ModelRuntimeRegistry(
        workspace / "models" / "registry.json"
    )
    assert registry.require("local/cli").enabled is True

    exported = runner.invoke(
        app,
        [
            "models",
            "config",
            "export",
            "--output",
            str(exported_path),
        ],
    )
    assert exported.exit_code == 0
    text = exported_path.read_text(encoding="utf-8")
    assert "env:NOUS_LOCAL_MODEL_KEY" in text
    assert "api_key:" not in text

    verified = runner.invoke(
        app,
        ["models", "verify", "local/cli"],
    )
    assert verified.exit_code == 0
    assert json.loads(verified.stdout)["ok"] is True

    removed = runner.invoke(
        app,
        ["models", "remove", "local/cli", "--yes"],
    )
    assert removed.exit_code == 0
    assert ModelRuntimeRegistry(
        workspace / "models" / "registry.json"
    ).require("local/cli").state.value == "removed"


def test_configure_noninteractive_dry_run_and_secret_rejection(
    tmp_path,
    monkeypatch,
) -> None:
    workspace = tmp_path / ".nous"
    monkeypatch.setenv("NOUS_WORKSPACE_ROOT", str(workspace))
    runner = CliRunner()

    configured = runner.invoke(
        app,
        [
            "models",
            "configure",
            "--non-interactive",
            "--dry-run",
            "--model-id",
            "local/dry",
            "--provider",
            "local",
            "--endpoint",
            "http://127.0.0.1:11434",
        ],
    )
    assert configured.exit_code == 0
    assert json.loads(configured.stdout)["changed"] is True
    assert not (workspace / "models" / "registry.json").exists()

    bad = payload()
    bad["providers"]["local"]["api_key"] = "sk-plaintext"
    path = tmp_path / "bad.yaml"
    path.write_text(yaml.safe_dump(bad), encoding="utf-8")
    rejected = runner.invoke(
        app,
        ["models", "config", "validate", str(path)],
    )
    assert rejected.exit_code != 0
    assert "sk-plaintext" not in rejected.stdout
