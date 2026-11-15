"""Actual Gate/Registry HTTP routing; installation grants no Kernel authority."""

import json

import pytest

from nous_runtime.extensions.registry import ExtensionRegistry
from tests.extensions.test_extension_executor import make_openapi
from tests.extensions.test_studio_presentation_api import client as client_fixture

client = client_fixture
BASE = "/api/v1/studio/extensions/tools"


def install(call, text):
    reviewed = call("POST", BASE + "/review", {"source_manifest": text})
    assert reviewed["ok"], reviewed
    review = reviewed["data"]
    body = {
        "source_manifest": text,
        "expected_digest": review["digest"],
        "expected_previous_digest": review["previous_digest"],
    }
    denied = call("POST", BASE + "/install", body)
    assert not denied["ok"] and denied["error"]["code"] == "NOUS_APPROVAL_REQUIRED"
    installed = call("POST", BASE + "/install", body, approve=True)
    assert installed["ok"], installed
    return installed["data"]


def test_review_install_enable_disable_update_remove_keeps_original_evidence(
    client, tmp_path
):
    call, gate, root = client
    source = tmp_path / "api.json"
    make_openapi(source)
    record = install(call, source.read_text())
    assert record["authority"] == "none" and record["enabled"] is False
    assert record["status"] == "NEEDS_AUTHORIZATION"
    body = {
        "extension_id": record["extension_id"],
        "enabled": True,
        "expected_digest": record["digest"],
        "expected_version": record["version"],
    }
    changed = call("POST", BASE + "/configure", body, approve=True)
    assert changed["ok"] and changed["data"]["authority"] == "none"
    registry = ExtensionRegistry(root / ".nous" / "extensions")
    assert registry.verify(record["extension_id"])
    view = call("GET", "/api/v1/studio/extensions")["data"]
    assert view["tool_extensions"]["records"][0]["enabled"] is True
    assert not view["extensions"]
    body["enabled"] = False
    assert call("POST", BASE + "/configure", body, approve=True)["ok"]
    artifact = registry.get_record(record["extension_id"])["artifact_ref"]
    value = json.loads(source.read_text())
    value["info"]["version"] = "1.1.0"
    updated = install(call, json.dumps(value))
    assert updated["enabled"] is False and updated["authority"] == "none"
    assert not call("POST", BASE + "/configure", body, approve=True)["ok"]
    assert call(
        "POST",
        BASE + "/remove",
        {
            "extension_id": updated["extension_id"],
            "expected_digest": updated["digest"],
            "expected_version": updated["version"],
        },
        approve=True,
    )["ok"]
    assert not registry.list()
    from nous_runtime.artifact.content_store import ContentAddressedArtifactStore

    assert ContentAddressedArtifactStore(root / ".nous" / "artifacts").verify(artifact)
    audit = json.dumps(gate.store.list_pending_approvals())
    assert "source_manifest" not in audit and "api.example.test" not in audit


@pytest.mark.parametrize(
    "body",
    [
        {
            "mcpServers": {
                "bad": {
                    "command": "python",
                    "env": {"API_KEY": "APEIR_FAKE_ONLY_SECRET_NOT_A_REAL_KEY"},
                }
            }
        },
        {"script": "globalThis.__unsafe = true"},
        {
            "mcpServers": {
                "bad": {
                    "url": "https://api.example.test/mcp?key=APEIR_FAKE_ONLY_QUERY_SECRET"
                }
            }
        },
        {"openapi": "3.1.0", "info": {"title": "Invalid"}, "paths": {}},
    ],
)
def test_unsafe_or_unsupported_import_never_installs(client, body):
    call, _, root = client
    result = call("POST", BASE + "/review", {"source_manifest": json.dumps(body)})
    assert not result["ok"]
    assert not ExtensionRegistry(root / ".nous" / "extensions").list()


def test_wrong_source_identity_and_missing_auth_cannot_install(client, tmp_path):
    call, _, root = client
    source = tmp_path / "api.json"
    make_openapi(source)
    text = source.read_text()
    assert not call(
        "POST", BASE + "/review", {"source_manifest": text}, authenticated=False
    )["ok"]
    review = call("POST", BASE + "/review", {"source_manifest": text})["data"]
    body = {
        "source_manifest": text,
        "expected_digest": "sha256:" + "a" * 64,
        "expected_previous_digest": review["previous_digest"],
    }
    assert not call("POST", BASE + "/install", body, approve=True)["ok"]
    assert not ExtensionRegistry(root / ".nous" / "extensions").list()


def test_openapi_documentation_and_example_urls_are_not_operational_endpoints(
    client, tmp_path
):
    call, _, _ = client
    source = tmp_path / "documented-api.json"
    make_openapi(source)
    value = json.loads(source.read_text())
    value["externalDocs"] = {"url": "https://docs.example.test/api?view=stable#items"}
    value["components"] = {
        "schemas": {
            "Status": {
                "type": "object",
                "example": {"endpoint": "logical-service-name"},
            }
        }
    }
    reviewed = call("POST", BASE + "/review", {"source_manifest": json.dumps(value)})
    assert reviewed["ok"], reviewed
