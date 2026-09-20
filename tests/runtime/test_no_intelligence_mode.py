from __future__ import annotations

import os
from pathlib import Path

import pytest
from typer.testing import CliRunner

from nous_runtime.cli.main import app
from nous_runtime.compat.provider import (
    Provider,
    _providers,
    get_provider,
    invoke_via_provider_observation,
    list_providers,
    register_adapter,
    unregister_adapter,
)
from nous_runtime.runtime.bootstrap import NousRuntime
from nous_runtime.runtime.no_intelligence import activate_no_intelligence


class _Provider(Provider):
    provider_id = "must-not-run"
    provider_name = "Must Not Run"

    def __init__(self):
        self.calls = 0

    def list_capabilities(self):
        return ["model.reason"]

    def invoke(self, capability_id, **params):
        self.calls += 1
        return {"ok": True}

    def health(self):
        return {"status": "ok"}


@pytest.fixture(autouse=True)
def _reset(monkeypatch):
    monkeypatch.delenv("NOUS_NO_INTELLIGENCE", raising=False)
    NousRuntime.reset_for_testing()
    for provider_id in list(_providers):
        unregister_adapter(provider_id)
    yield
    NousRuntime.reset_for_testing()
    for provider_id in list(_providers):
        unregister_adapter(provider_id)
    os.environ.pop("NOUS_NO_INTELLIGENCE", None)


def test_mode_removes_existing_provider_and_blocks_registration_and_invocation():
    provider = _Provider()
    assert register_adapter(provider)
    assert get_provider(provider.provider_id) is provider

    activate_no_intelligence()

    assert list_providers() == []
    assert get_provider(provider.provider_id) is None
    assert not register_adapter(_Provider())
    observation = invoke_via_provider_observation(
        provider.provider_id,
        "model.reason",
        {"prompt": "must not leave the process"},
    )
    assert observation.metadata["error_code"] == "NOUS_INTELLIGENCE_DISABLED"
    assert provider.calls == 0


def test_runtime_bootstrap_is_healthy_without_loading_any_provider(
    monkeypatch, tmp_path: Path
):
    monkeypatch.setenv("NOUS_NO_INTELLIGENCE", "1")

    def forbidden_loader():
        raise AssertionError("provider loader must not run")

    runtime = NousRuntime.bootstrap(
        workspace_root=str(tmp_path),
        provider_loader=forbidden_loader,
        no_intelligence=True,
        force=True,
    )
    snapshot = runtime.snapshot()

    assert snapshot.ready
    assert snapshot.provider_count == 0
    assert snapshot.model_count == 0
    assert snapshot.gateway_configured
    assert snapshot.intelligence_enabled is False


def test_cli_no_intelligence_reports_honest_reality_baseline(monkeypatch):
    monkeypatch.setattr("nous_runtime.cli.shell_v2.run", lambda **_: None)
    monkeypatch.setattr(
        "nous_runtime.api.kernel_status.kernel_status",
        lambda **_: {"ready": True, "state": "READY"},
    )

    result = CliRunner().invoke(app, ["--no-intelligence"])

    assert result.exit_code == 0, result.output
    assert "Intelligence providers: 0" in result.output
    assert "Runtime: healthy" in result.output
    assert "Kernel: healthy" in result.output


def test_health_endpoint_exposes_disabled_mode(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("NOUS_NO_INTELLIGENCE", "1")
    monkeypatch.setenv("NOUS_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setattr(
        "nous_runtime.api.kernel_status.kernel_status",
        lambda: {"configured": True, "ready": True},
    )
    activate_no_intelligence()
    from nous_runtime.api.health_endpoints import handle_health_detailed

    result = handle_health_detailed()

    assert result["ok"] is True
    assert result["data"]["provider_count"] == 0
    assert result["data"]["intelligence_mode"] == "disabled"


def test_terminal_banner_does_not_contradict_healthy_llm_off_runtime(
    monkeypatch, tmp_path: Path
):
    monkeypatch.setenv("NOUS_NO_INTELLIGENCE", "1")
    NousRuntime.bootstrap(
        workspace_root=str(tmp_path), no_intelligence=True, force=True
    )
    from nous_runtime.cli import shell_v2

    shell_v2._ensure_providers()
    banner = shell_v2._banner()

    assert "Runtime    Online" in banner
    assert "Provider   Disabled" in banner
    assert "Model      Disabled" in banner
