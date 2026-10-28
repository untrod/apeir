"""Saved configuration remains inspectable without enabling model execution."""

import json
import subprocess
import sys

import pytest

from nous_runtime.services.providers import list_provider_summaries


@pytest.fixture
def saved(tmp_path, monkeypatch):
    monkeypatch.setenv("NOUS_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("NOUS_NO_INTELLIGENCE", "1")
    from nous_runtime.provider.registry import registry

    monkeypatch.setattr(registry, "list_all", lambda: [])
    path = tmp_path / ".nous" / "providers.json"
    path.parent.mkdir()
    return path


def test_model_disabled_saved_configuration_has_no_secret_or_inference_claim(saved):
    config = {
        "name": "Local example",
        "base_endpoint": "http://127.0.0.1:11434/v1",
        "model": "selected-model",
        "credential_ref": "env:FAKE_PRIVATE_REFERENCE",
        "api_key": "PRIVATE_LEGACY_KEY",
        "secret": "PRIVATE_OLD_SECRET",
    }
    saved.write_text(json.dumps({"example": config}))
    original = saved.read_bytes()
    assert list_provider_summaries() == [
        {
            "id": "example",
            "name": "Local example",
            "capabilities": [],
            "health": {"status": "unknown"},
            "configuration": {
                "name": "Local example",
                "api_base_url": "http://127.0.0.1:11434/v1",
                "model": "selected-model",
                "has_reference": True,
            },
        }
    ]
    output = subprocess.run(
        [
            sys.executable,
            "-c",
            "import json; from nous_runtime.services.providers import list_provider_summaries; print(json.dumps(list_provider_summaries()))",
        ],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert output.returncode == 0, output.stderr
    assert json.loads(output.stdout) == list_provider_summaries()
    assert "PRIVATE" not in output.stdout
    assert saved.read_bytes() == original


@pytest.mark.parametrize(
    "endpoint",
    [
        "https://user:PRIVATE_PASSWORD@example.test/v1",
        "https://example.test/v1?key=PRIVATE_QUERY",
        "https://example.test/v1#PRIVATE_FRAGMENT",
        "https://example.test/v1\nPRIVATE_HEADER",
        ["https://example.test"],
        "http://[invalid",
    ],
)
def test_legacy_embedded_credentials_are_not_returned(saved, endpoint):
    saved.write_text(
        json.dumps(
            {"example": {"endpoint": endpoint, "credential_ref": "PRIVATE_INLINE"}}
        )
    )
    try:
        result = list_provider_summaries()
    except ValueError as exc:
        assert "PRIVATE" not in str(exc)
    else:
        assert result[0]["configuration"]["api_base_url"] == ""
        assert "PRIVATE" not in json.dumps(result)


@pytest.mark.parametrize("content", ["PRIVATE_CORRUPT", "[]", '{"example":null}'])
def test_invalid_saved_metadata_does_not_claim_no_providers(saved, content):
    saved.write_text(content)
    with pytest.raises(ValueError, match="metadata is unavailable") as error:
        list_provider_summaries()
    assert content not in str(error.value)
    assert saved.read_text() == content


def test_saved_metadata_is_bounded(saved):
    saved.write_bytes(b" " * (2 * 1024 * 1024 + 1))
    with pytest.raises(ValueError, match="metadata is unavailable"):
        list_provider_summaries()


@pytest.mark.parametrize("field", ["name", "model"])
def test_invalid_nested_fields_cannot_echo_legacy_credentials(saved, field):
    saved.write_text(json.dumps({"example": {field: {"api_key": "PRIVATE_OLD_KEY"}}}))
    with pytest.raises(ValueError, match="metadata is unavailable") as error:
        list_provider_summaries()
    assert "PRIVATE_OLD_KEY" not in str(error.value)


def test_missing_file_does_not_initialize_or_register_a_provider(saved):
    assert list_provider_summaries() == []
    assert not saved.exists()


def test_existing_registration_and_saved_configuration_keep_one_identity(
    saved, monkeypatch
):
    from nous_runtime.provider.registry import registry

    active = {
        "id": "example",
        "name": "Active",
        "capabilities": ["model.reason"],
        "health": {"status": "unknown"},
    }
    monkeypatch.setattr(registry, "list_all", lambda: [active])
    saved.write_text(json.dumps({"example": {"name": "Saved", "model": "version-2"}}))
    rows = list_provider_summaries()
    assert len(rows) == 1
    assert rows[0]["health"] == {"status": "unknown"}
    assert rows[0]["capabilities"] == ["model.reason"]
    assert rows[0]["configuration"]["model"] == "version-2"
    assert "configuration" not in active
