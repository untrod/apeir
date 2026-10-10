"""Preview preflight reports prerequisites, never performs report execution."""

import json

import pytest

from scripts.acceptance import scientific_preview_preflight as preview


def inventory():
    return {
        name: {"available": True, "version": "test-version"}
        for name in preview.REQUIRED_PROVIDERS
    }


def strong_probe():
    return {
        "available": True,
        "hard_network_isolation": True,
        "filesystem_namespace_isolation": True,
        "evidence_level": "strong-vm",
    }


@pytest.mark.parametrize(
    "missing",
    [
        "available",
        "hard_network_isolation",
        "filesystem_namespace_isolation",
        "evidence_level",
    ],
)
def test_incomplete_strong_isolation_remains_blocked(monkeypatch, missing):
    probe = strong_probe()
    probe.pop(missing)
    monkeypatch.setattr(preview.LocalSandboxProvider, "probe", lambda self: probe)
    monkeypatch.setattr(preview, "provider_inventory", inventory)
    result = preview.preflight()
    assert result["status"] == "BLOCKED"
    assert result["execution_performed"] is False
    assert result["reports_created"] == []


@pytest.mark.parametrize(
    "value",
    [
        None,
        {"available": False, "version": "1"},
        {"available": True, "version": "unknown"},
        {"available": True, "version": None},
        {"available": True, "version": " "},
    ],
)
def test_missing_numerical_prerequisite_blocks_run(monkeypatch, value):
    providers = inventory()
    providers.pop("scipy")
    if value is not None:
        providers["scipy"] = value
    monkeypatch.setattr(
        preview.LocalSandboxProvider, "probe", lambda self: strong_probe()
    )
    monkeypatch.setattr(preview, "provider_inventory", lambda: providers)
    assert preview.preflight()["status"] == "BLOCKED"


def test_ready_prerequisites_do_not_claim_report_or_acceptance(monkeypatch, capsys):
    monkeypatch.setattr(
        preview.LocalSandboxProvider, "probe", lambda self: strong_probe()
    )
    monkeypatch.setattr(preview, "provider_inventory", inventory)
    assert preview.main() == 0
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "READY_FOR_GOVERNED_RUN"
    assert result["status"] != "PASS"
    assert result["execution_performed"] is False
    assert result["reports_created"] == []
    assert "not a formal proof" in result["claim_scope"]


def test_probe_error_fails_closed_without_copying_exception_material(
    monkeypatch, capsys
):
    def fail(self):
        raise RuntimeError("fake-sensitive-probe-value")

    monkeypatch.setattr(preview.LocalSandboxProvider, "probe", fail)
    assert preview.main() == 2
    output = capsys.readouterr().out
    assert "fake-sensitive-probe-value" not in output
    assert json.loads(output)["status"] == "BLOCKED"


def test_real_readonly_preflight_matches_current_provider_facts():
    result = preview.preflight()
    assert result["status"] in {"BLOCKED", "READY_FOR_GOVERNED_RUN"}
    assert result["execution_performed"] is False
    assert result["reports_created"] == []
    assert bool(result["blockers"]) == (result["status"] == "BLOCKED")
