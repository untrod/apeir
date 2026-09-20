from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from nous_runtime.model_runtime.configuration import (
    DeclarativeModelConfigService,
)
from nous_runtime.model_runtime.errors import ModelRuntimeError
from nous_runtime.model_runtime.registry import ModelRuntimeRegistry


def config(
    *,
    model_id: str = "local/reason",
    credential_ref: str = "env:NOUS_TEST_KEY",
) -> dict:
    return {
        "schema_version": 1,
        "providers": {
            "local": {
                "kind": "local_service",
                "endpoint": "http://127.0.0.1:11434",
                "credential_ref": credential_ref,
            }
        },
        "models": [
            {
                "model_id": model_id,
                "display_name": "Reason",
                "provider_id": "local",
                "endpoint_type": "local_service",
                "modalities": ["text"],
                "capabilities": ["reasoning"],
                "enabled": True,
                "route_priority": 10,
                "fallback": [],
            }
        ],
        "defaults": {"planner": model_id},
    }


def service(tmp_path) -> DeclarativeModelConfigService:
    return DeclarativeModelConfigService(
        tmp_path / "models" / "registry.json"
    )


def test_yaml_validation_plan_dry_run_apply_and_export(tmp_path) -> None:
    manager = service(tmp_path)
    path = tmp_path / "models.yaml"
    path.write_text(yaml.safe_dump(config()), encoding="utf-8")
    loaded = manager.load(path)

    dry_run = manager.apply(loaded, dry_run=True)
    assert dry_run.changed is True
    assert dry_run.actions[0].action == "add"
    assert not manager.registry_path.exists()

    applied = manager.apply(loaded)
    assert applied.changed is True
    record = ModelRuntimeRegistry(manager.registry_path).require(
        "local/reason"
    )
    assert record.enabled is True
    assert record.metadata["credential_ref"] == "env:NOUS_TEST_KEY"
    assert manager.defaults.read()["planner"] == "local/reason"

    exported = manager.export()
    serialized = yaml.safe_dump(exported)
    assert "NOUS_TEST_KEY" in serialized
    assert "sk-" not in serialized
    assert manager.plan(exported).changed is False


def test_plaintext_credentials_and_unknown_versions_are_rejected(
    tmp_path,
) -> None:
    manager = service(tmp_path)
    raw = config(credential_ref="")
    raw["providers"]["local"]["api_key"] = "sk-plaintext"
    with pytest.raises(ModelRuntimeError, match="cannot contain a secret"):
        manager.validate(raw)

    raw = config()
    raw["schema_version"] = 99
    with pytest.raises(ModelRuntimeError, match="schema version"):
        manager.validate(raw)


def test_apply_failure_restores_registry_and_defaults(
    tmp_path,
    monkeypatch,
) -> None:
    manager = service(tmp_path)
    manager.apply(config())
    original_registry = manager.registry_path.read_bytes()
    original_defaults = manager.defaults.path.read_bytes()
    replacement = config(model_id="local/new")

    import nous_runtime.model_runtime.configuration as module

    real_replace = module.os.replace

    def fail_defaults(source, destination):
        source_path = Path(source)
        destination_path = Path(destination)
        if (
            destination_path == manager.defaults.path
            and ".staged" in source_path.name
        ):
            raise OSError("injected defaults commit failure")
        return real_replace(source, destination)

    monkeypatch.setattr(module.os, "replace", fail_defaults)
    with pytest.raises(ModelRuntimeError, match="rolled back"):
        manager.apply(replacement)

    assert manager.registry_path.read_bytes() == original_registry
    assert manager.defaults.path.read_bytes() == original_defaults
    payload = json.loads(
        manager.registry_path.read_text(encoding="utf-8")
    )
    assert payload["models"][0]["descriptor"]["model_id"] == "local/reason"
