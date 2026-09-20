from __future__ import annotations

import json

from nous_runtime.deployment.first_launch import _save_provider_config


def test_first_launch_writes_standard_reference_only_provider_config(tmp_path):
    secret = "sk-example-plaintext-value"  # security-scan: fixture

    _save_provider_config(
        [
            {
                "provider_id": "deepseek",
                "credential_ref": "env:DEEPSEEK_API_KEY",
                "api_key": secret,
            }
        ],
        tmp_path,
    )

    path = tmp_path / "providers.json"
    raw = path.read_text(encoding="utf-8")
    config = json.loads(raw)["deepseek"]
    assert secret not in raw
    assert "api_key" not in config
    assert config["credential_ref"] == "env:DEEPSEEK_API_KEY"
    assert config["executable_capabilities"] == ["model.reason", "model.code"]


def test_first_launch_removes_legacy_plaintext_provider_file_after_migration(
    tmp_path,
):
    legacy = tmp_path / "config" / "providers.json"
    legacy.parent.mkdir()
    legacy.write_text(
        json.dumps({"deepseek": {"api_key": "legacy-secret"}}),
        encoding="utf-8",
    )

    _save_provider_config(
        [
            {
                "provider_id": "deepseek",
                "credential_ref": "env:DEEPSEEK_API_KEY",
            }
        ],
        tmp_path,
    )

    assert not legacy.exists()
    assert "legacy-secret" not in (tmp_path / "providers.json").read_text(
        encoding="utf-8"
    )
