"""Declarative contract, real Registry/CAS lifecycle and original Runtime host."""

from copy import deepcopy
import json
from pathlib import Path

import pytest

from nous_runtime.extensions.presentation import StudioExtensionHost
from nous_runtime.extensions.presentation_contract import (
    FIELDS,
    component_type,
    validate_presentation,
)
from nous_runtime.extensions.registry import ExtensionRegistry

EXAMPLE = (
    Path(__file__).parents[2]
    / "examples"
    / "studio_system_monitor"
    / "nous.extension.json"
)


def manifest():
    return json.loads(EXAMPLE.read_text(encoding="utf-8"))


def install(host, value=None):
    source = json.dumps(value or manifest())
    reviewed = host.review(source)
    return host.install(
        source,
        expected_digest=reviewed["digest"],
        expected_previous_digest=reviewed["previous_digest"],
    )


def enable(host, record, enabled=True):
    return host.configure(
        record["extension_id"],
        enabled=enabled,
        expected_digest=record["digest"],
        expected_version=record["version"],
    )


def test_real_registry_install_enable_update_disable_remove_and_restart(
    tmp_path, monkeypatch
):
    host = StudioExtensionHost(tmp_path)
    record = install(host)
    assert (
        record["enabled"] is False
        and record["authority"] == "none"
        and record["granted_capabilities"] == []
    )
    assert record["artifact_ref"].startswith("sha256:")
    component = record["contributions"][1]["type"]
    with pytest.raises(PermissionError):
        host.read_data(component, record["digest"], "runtime.status")
    enabled = enable(host, record)
    assert enabled["enabled"] and enabled["granted_capabilities"] == []
    # Contract fixture only: actual status is exercised through CLI/HTTP/Chromium.
    monkeypatch.setattr(
        StudioExtensionHost,
        "_status",
        staticmethod(lambda: {key: None for key in FIELDS}),
    )
    assert (
        set(host.read_data(component, record["digest"], "runtime.status")["values"])
        == FIELDS
    )
    with pytest.raises(PermissionError):
        host.read_data(component, record["digest"], "credential.store")
    enable(host, record, False)
    with pytest.raises(PermissionError):
        host.read_data(component, record["digest"], "runtime.status")
    enable(host, record)
    changed = manifest()
    changed["version"] = "1.1.0"
    updated = install(host, changed)
    assert not updated["enabled"] and updated["digest"] != record["digest"]
    assert updated["contributions"][1]["type"] == component
    with pytest.raises(PermissionError):
        enable(host, record)
    enable(host, updated)
    restarted = StudioExtensionHost(tmp_path)
    assert restarted.record(record["extension_id"])["enabled"]
    assert restarted.remove(
        updated["extension_id"],
        expected_digest=updated["digest"],
        expected_version=updated["version"],
    )["removed"]
    with pytest.raises(PermissionError):
        restarted.read_data(component, updated["digest"], "runtime.status")
    assert restarted.records() == ([], [])


def test_immutable_ui_version_and_review_digest_do_not_get_replaced(tmp_path):
    host = StudioExtensionHost(tmp_path)
    record = install(host)
    changed = manifest()
    changed["description"] = "Different bytes, same version"
    with pytest.raises(ValueError, match="version"):
        host.review(json.dumps(changed))
    original = json.dumps(manifest())
    with pytest.raises(PermissionError, match="digest"):
        host.install(
            original,
            expected_digest="sha256:" + "0" * 64,
            expected_previous_digest=record["digest"],
        )
    assert host.registry.verify(record["extension_id"]).version == "1.0.0"


@pytest.mark.parametrize(
    "mutate",
    [
        lambda d: d["metadata"]["apeir_studio"].update(javascript="alert(1)"),
        lambda d: d["metadata"]["apeir_studio"]["contributions"][0].update(
            module_url="https://example.test/module.js"
        ),
        lambda d: d["metadata"]["apeir_studio"]["contributions"][0]["view"]["children"][
            0
        ].update(field="private.key"),
        lambda d: d["metadata"]["apeir_studio"]["contributions"][0].update(
            subscriptions=["credential.store"]
        ),
        lambda d: d["metadata"].update(module_url="file:///private.js"),
        lambda d: d.update(compatibility_level=5),
        lambda d: d.update(entry_points=[{"kind": "process", "target": "host-shell"}]),
        lambda d: d["metadata"]["apeir_studio"]["contributions"].append(
            deepcopy(d["metadata"]["apeir_studio"]["contributions"][0])
        ),
    ],
)
def test_malicious_or_unsupported_configuration_fails_before_install(tmp_path, mutate):
    value = manifest()
    mutate(value)
    with pytest.raises((ValueError, TypeError)):
        StudioExtensionHost(tmp_path).review(json.dumps(value))
    assert not (tmp_path / ".nous" / "extensions" / "registry.json").exists()


def test_disabled_and_modified_content_cannot_read_or_self_authorize(tmp_path):
    host = StudioExtensionHost(tmp_path)
    record = install(host)
    enable(host, record)
    component = record["contributions"][1]["type"]
    with pytest.raises(PermissionError):
        host.request_action(
            component,
            record["digest"],
            "device.firmware.update",
            idempotency_key="original",
        )
    package = host.registry.package_path(record["extension_id"])
    (package / "nous.extension.json").write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError):
        host.read_data(component, record["digest"], "runtime.status")


def test_presentation_lock_changes_are_not_silently_accepted(tmp_path):
    host = StudioExtensionHost(tmp_path)
    record = install(host)
    index = json.loads(host.registry.index_path.read_text())
    index["extensions"][record["extension_id"]]["presentation_enabled"] = True
    host.registry.index_path.write_text(json.dumps(index))
    with pytest.raises(ValueError, match="presentation"):
        host.registry.verify(record["extension_id"])


def test_declarative_html_is_data_and_component_identity_is_stable():
    value = manifest()["metadata"]["apeir_studio"]
    value["contributions"][0]["view"] = {
        "kind": "text",
        "text": "<script>literal only</script>",
    }
    assert validate_presentation(value) == value
    assert component_type(
        "examples/studio-system-monitor", "runtime-status"
    ).startswith("ui:")
    assert len(component_type("x" * 128, "y" * 32)) <= 80


def test_existing_non_ui_extensions_are_not_replaced_by_presentation_import(tmp_path):
    package = tmp_path / "non-ui"
    package.mkdir()
    old = manifest()
    old["metadata"] = {}
    old["version"] = "0.9.0"
    (package / "nous.extension.json").write_text(json.dumps(old))
    host = StudioExtensionHost(tmp_path)
    ExtensionRegistry(host.registry.root).install(package)
    with pytest.raises(PermissionError, match="migration"):
        host.review(json.dumps(manifest()))


def test_public_schema_accepts_the_actual_reference_contract():
    from jsonschema import Draft202012Validator
    from nous_runtime.schema_registry import STUDIO_UI_SCHEMA_VERSION

    schema = json.loads(
        (
            EXAMPLE.parents[2] / "spec" / "extensions" / "v1" / "studio-ui.schema.json"
        ).read_text()
    )
    Draft202012Validator.check_schema(schema)
    value = manifest()["metadata"]["apeir_studio"]
    Draft202012Validator(schema).validate(value)
    assert schema["properties"]["schema"]["const"] == STUDIO_UI_SCHEMA_VERSION
