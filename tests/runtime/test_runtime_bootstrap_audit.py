from __future__ import annotations

from pathlib import Path

import pytest

from nous_runtime.model_runtime.compatibility import (
    reset_compatibility_observability,
)
from nous_runtime.runtime.audit import audit_runtime
from nous_runtime.runtime.bootstrap import (
    NousRuntime,
    RuntimeBootstrapState,
)


@pytest.fixture(autouse=True)
def reset_runtime():
    NousRuntime.reset_for_testing()
    reset_compatibility_observability()
    yield
    NousRuntime.reset_for_testing()
    reset_compatibility_observability()


def test_runtime_bootstrap_wires_existing_components_and_is_idempotent(
    tmp_path: Path,
):
    calls = []

    def load_providers() -> int:
        calls.append("loaded")
        return 0

    runtime = NousRuntime.bootstrap(
        workspace_root=str(tmp_path),
        provider_loader=load_providers,
    )
    same = NousRuntime.current()

    assert same is runtime
    assert calls == ["loaded"]
    assert runtime.state is RuntimeBootstrapState.READY
    snapshot = runtime.snapshot()
    assert snapshot.gateway_configured
    assert snapshot.router_ready
    assert snapshot.scheduler_ready
    assert snapshot.metrics_ready
    assert snapshot.trace_ready
    assert snapshot.context_ready
    assert runtime.components is not None
    assert runtime.components.state.get("artifacts", "registry") is not None
    assert any(
        event.event_type == "runtime.bootstrap.ready"
        for event in runtime.events
    )


def test_runtime_bootstrap_remains_usable_when_provider_loading_degrades(
    tmp_path: Path,
):
    def broken_loader() -> int:
        raise OSError("offline")

    runtime = NousRuntime.bootstrap(
        workspace_root=str(tmp_path),
        provider_loader=broken_loader,
    )

    assert runtime.state is RuntimeBootstrapState.DEGRADED
    assert runtime.snapshot().ready
    assert runtime.snapshot().gateway_configured
    assert "provider loading degraded" in runtime.warnings[0]


def test_runtime_audit_reports_clean_gateway_only_source(tmp_path: Path):
    source = tmp_path / "nous_runtime"
    source.mkdir()
    (source / "feature.py").write_text(
        "result = facade.invoke_sync(GatewayRequest())\n",
        encoding="utf-8",
    )
    runtime = NousRuntime.bootstrap(
        workspace_root=str(tmp_path),
        provider_loader=lambda: 0,
    )

    report = audit_runtime(
        tmp_path,
        runtime=runtime,
        source_roots=("nous_runtime",),
    )

    assert report.passed
    assert report.gateway_percentage == 100.0
    assert report.direct_provider_calls == 0
    assert report.to_dict()["security"] == "PASS"


def test_runtime_audit_finds_direct_provider_and_model_http(tmp_path: Path):
    runtime_root = tmp_path / "nous_runtime"
    terminal_root = tmp_path / "remote_terminal"
    runtime_root.mkdir()
    terminal_root.mkdir()
    (runtime_root / "feature.py").write_text(
        "result = provider.invoke('model.reason')\n",
        encoding="utf-8",
    )
    (terminal_root / "brain_llm.py").write_text(
        "data = post_json('/v1/chat/completions', payload, 30)\n",
        encoding="utf-8",
    )
    runtime = NousRuntime.bootstrap(
        workspace_root=str(tmp_path),
        provider_loader=lambda: 0,
    )

    report = audit_runtime(tmp_path, runtime=runtime)

    assert not report.passed
    assert report.direct_provider_calls == 2
    assert {
        item.category for item in report.findings
    } == {"direct_model_http", "direct_provider"}
