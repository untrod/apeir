"""Passive OCI discovery must not invent execution or containment qualification."""

from pathlib import Path
import os

import pytest

from nous_runtime.environments import EnvironmentProviderRegistry, EnvironmentRuntime
from nous_runtime.environments.models import ExecutionEnvironment
from nous_runtime.environments.providers import (
    OCIContainerProvider,
    ProviderExecutionResult,
    _default_runner,
)


def engine(tmp_path: Path) -> str:
    path = tmp_path / ("docker.exe" if os.name == "nt" else "docker")
    path.write_text("#!/bin/sh\nexit 99\n", encoding="utf-8")
    path.chmod(0o755)
    return str(path)


def security(monkeypatch, *, strong=False):
    policies = []

    def report(sandbox):
        policies.append(sandbox.policy)
        return {
            "strong": strong,
            "grade": "strong_vm" if strong else "resource_only",
            "enforced_controls": ("timeout", "output_limit"),
            "unenforced_controls": ()
            if strong
            else ("filesystem_scope", "network_egress"),
        }

    monkeypatch.setattr(
        "nous_runtime.environments.providers.ProcessSandbox.security_report", report
    )
    return policies


def test_engine_discovery_does_not_admit_resource_only_control(tmp_path, monkeypatch):
    policies = security(monkeypatch)
    status = OCIContainerProvider(engine_path=engine(tmp_path)).probe()
    assert status["available"] is False
    assert status["engine_detected"] is True
    assert status["control_admission"] == "blocked"
    assert status["control_security_grade"] == "resource_only"
    assert status["hard_network_isolation"] is False
    assert status["filesystem_namespace_isolation"] is False
    assert status["engine_health"] == "unknown"
    assert status["workload_qualification"] == "not_run"
    assert status["evidence_level"] == "static"
    assert len(policies) == 1
    assert policies[0].max_processes == 64
    assert policies[0].network_allowed is False
    assert policies[0].require_strong_isolation is True
    assert "No ordinary host-process fallback" in " ".join(status["limitations"])


def test_strong_control_preflight_is_not_container_qualification(tmp_path, monkeypatch):
    security(monkeypatch, strong=True)
    status = OCIContainerProvider(engine_path=engine(tmp_path)).probe()
    assert status["available"] is True
    assert status["control_admission"] == "ready"
    assert status["engine_health"] == "unknown"
    assert status["workload_qualification"] == "not_run"
    assert status["hard_network_isolation"] is False
    assert status["filesystem_namespace_isolation"] is False
    assert status["evidence_level"] == "static"


def test_injected_runner_is_not_automatic_qualification(tmp_path, monkeypatch):
    security(monkeypatch, strong=True)
    calls = []
    provider = OCIContainerProvider(
        engine_path=engine(tmp_path), runner=lambda *args: calls.append(args)
    )
    status = provider.probe()
    assert calls == []
    assert status["available"] is False
    assert status["engine_detected"] is True
    assert status["control_admission"] == "unknown"
    assert status["workload_qualification"] == "not_run"
    assert not status["hard_network_isolation"]
    assert not status["filesystem_namespace_isolation"]


def test_missing_explicit_engine_cannot_pass_preflight(tmp_path, monkeypatch):
    policies = security(monkeypatch, strong=True)
    status = OCIContainerProvider(engine_path=str(tmp_path / "missing-docker")).probe()
    assert status["available"] is False
    assert status["engine_detected"] is False
    assert status["control_admission"] == "blocked"
    assert not policies


def test_probe_never_runs_engine_and_reflects_backend_changes(tmp_path, monkeypatch):
    provider = OCIContainerProvider(engine_path=engine(tmp_path))
    security(monkeypatch, strong=True)

    def forbidden(*args, **kwargs):
        raise AssertionError("passive readiness ran an executable")

    monkeypatch.setattr(
        "nous_runtime.environments.providers.ProcessSandbox.run", forbidden
    )
    first = provider.probe()
    security(monkeypatch, strong=False)
    second = provider.probe()
    assert first["available"] is True
    assert second["available"] is False
    assert second["control_admission"] == "blocked"


@pytest.mark.parametrize("strong", ["true", 1, None])
def test_non_boolean_control_proof_cannot_admit_execution(
    tmp_path, monkeypatch, strong
):
    security(monkeypatch, strong=strong)
    status = OCIContainerProvider(engine_path=engine(tmp_path)).probe()
    assert status["available"] is False
    assert status["control_admission"] == "blocked"


def test_failed_control_probe_retains_unknown_without_raw_exception(
    tmp_path, monkeypatch
):
    def failed(_sandbox):
        raise RuntimeError("fake private diagnostic: must not reach status")

    monkeypatch.setattr(
        "nous_runtime.environments.providers.ProcessSandbox.security_report", failed
    )
    status = OCIContainerProvider(engine_path=engine(tmp_path)).probe()
    assert status["available"] is False
    assert status["control_admission"] == "unknown"
    assert "fake private diagnostic" not in str(status)


def test_existing_injected_reference_runner_can_prepare_without_probe_qualification(
    tmp_path, monkeypatch
):
    security(monkeypatch)
    calls = []

    def owned_runner(argv, cwd, timeout, output, env):
        calls.append(argv)
        return ProviderExecutionResult(ok=True, exit_code=0)

    provider = OCIContainerProvider(engine_path=engine(tmp_path), runner=owned_runner)
    assert provider.probe()["available"] is False
    environment = ExecutionEnvironment.from_mapping(
        {
            "provider": "oci",
            "environment_type": "oci_container",
            "image": "reviewed-reference",
        },
        new_identity=True,
    )
    handle = provider.prepare(environment, tmp_path)
    provider.start(environment, handle)
    assert [call[1] for call in calls] == ["create", "start"]
    assert calls[0][calls[0].index("--pids-limit") + 1] == "64"
    assert "--read-only" in calls[0]
    assert calls[0][calls[0].index("--network") + 1] == "none"


def test_runtime_status_carries_original_blocked_readiness(tmp_path, monkeypatch):
    security(monkeypatch)
    provider = OCIContainerProvider(engine_path=engine(tmp_path))
    runtime = EnvironmentRuntime(
        tmp_path, providers=EnvironmentProviderRegistry({"oci": provider})
    )
    status = runtime.status()["providers"][0]
    assert status["available"] is False
    assert status["control_admission"] == "blocked"
    assert status["workload_qualification"] == "not_run"
    assert runtime.list_environments() == []


def test_default_execution_remains_fail_closed_without_strong_backend(
    tmp_path, monkeypatch
):
    security(monkeypatch)
    result = _default_runner([engine(tmp_path), "version"], str(tmp_path), 1, 1024)
    assert result.ok is False
    assert result.availability_state == "unavailable"
    assert result.security_grade == "resource_only"
    assert "STRICT_SANDBOX_UNAVAILABLE" in result.stderr
