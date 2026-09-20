from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from nous_runtime.api import routes
from nous_runtime.environments import (
    CompatibilityHandshake,
    EnvironmentCommand,
    EnvironmentCompatibilityError,
    EnvironmentProviderError,
    EnvironmentProviderRegistry,
    EnvironmentRuntime,
    EnvironmentValidationError,
    ExecutionEnvironment,
    LocalSandboxProvider,
    OCIContainerProvider,
    ProviderExecutionResult,
)
from nous_runtime.events import EventStream
from nous_runtime.kernel.windows_sandbox import executable_path
from nous_runtime.schema_registry import ENVIRONMENT_PROVIDER_SCHEMA_VERSION


requires_strong_sandbox = pytest.mark.skipif(
    executable_path() is None,
    reason="Windows Sandbox requires the post-feature-enable reboot",
)


class FakeProvider:
    provider_id = "local-sandbox"
    contract_version = ENVIRONMENT_PROVIDER_SCHEMA_VERSION

    def __init__(self, *, fail_prepare: bool = False, fail_destroy: bool = False) -> None:
        self.fail_prepare = fail_prepare
        self.fail_destroy = fail_destroy
        self.stopped = False
        self.destroyed = False

    def probe(self):
        return {
            "provider_id": self.provider_id,
            "contract_version": self.contract_version,
            "available": True,
            "environment_type": "local_sandbox",
            "evidence_level": "simulated",
        }

    def prepare(self, environment, workspace_root):
        if self.fail_prepare:
            raise EnvironmentProviderError("prepare failure")
        path = Path(workspace_root) / ".nous" / "fake" / environment.environment_id
        path.mkdir(parents=True, exist_ok=True)
        return str(path)

    def start(self, environment, handle):
        assert Path(handle).is_dir()

    def execute(self, environment, handle, command):
        return ProviderExecutionResult(
            ok=True,
            exit_code=0,
            stdout="environment-ok\n",
            wall_time_seconds=0.01,
            peak_memory_bytes=1024,
        )

    def stop(self, environment, handle):
        self.stopped = True

    def destroy(self, environment, handle):
        if self.fail_destroy:
            raise EnvironmentProviderError("cleanup failure")
        self.destroyed = True

    def logs(self, environment, handle):
        return "fake environment log"


def _runtime(tmp_path, provider=None):
    provider = provider or FakeProvider()
    registry = EnvironmentProviderRegistry({"local-sandbox": provider})
    return EnvironmentRuntime(tmp_path, providers=registry), provider


def _spec():
    return {
        "environment_type": "local_sandbox",
        "provider": "local-sandbox",
        "cpu_limit": 1.5,
        "memory_limit_mb": 256,
        "network_policy": {"mode": "none"},
        "filesystem_policy": {"read_only_root": True, "temporary_filesystem_mb": 32},
        "device_policy": {"gpu": "none", "devices": []},
        "workspace_mounts": [],
        "lifetime_seconds": 600,
        "task_id": "task-environment-test",
        "trace_id": "trace-environment-test",
    }


def test_environment_contract_defaults_are_bounded_and_network_off():
    environment = ExecutionEnvironment.from_mapping(_spec(), new_identity=True)
    assert environment.environment_id.startswith("env_")
    assert environment.network_policy.mode == "none"
    assert environment.filesystem_policy.read_only_root is True
    assert environment.workspace_mounts == ()
    with pytest.raises(EnvironmentValidationError, match="workspace-relative"):
        ExecutionEnvironment.from_mapping(
            {**_spec(), "workspace_mounts": [{"source": "../outside", "target": "/model-workspace"}]},
            new_identity=True,
        )
    with pytest.raises(EnvironmentValidationError, match="below artifacts"):
        ExecutionEnvironment.from_mapping(
            {
                **_spec(),
                "workspace_mounts": [
                    {
                        "source": ".",
                        "target": "/model-workspace/output",
                        "mode": "artifact-output-only",
                    }
                ],
            },
            new_identity=True,
        )
    with pytest.raises(EnvironmentValidationError, match="engine sockets"):
        ExecutionEnvironment.from_mapping(
            {
                **_spec(),
                "workspace_mounts": [
                    {"source": "docker.sock", "target": "/model-workspace/docker.sock"}
                ],
            },
            new_identity=True,
        )


def test_create_cannot_spoof_lifecycle_or_zero_limits(tmp_path):
    runtime, _provider = _runtime(tmp_path)
    created = runtime.create(
        {
            **_spec(),
            "state": "ready",
            "provider_handle": "forged-handle",
            "last_error": "forged-error",
        }
    )
    assert created["state"] == "created"
    assert created["provider_handle"] == ""
    assert created["last_error"] == ""
    with pytest.raises(EnvironmentValidationError, match="cpu_limit"):
        ExecutionEnvironment.from_mapping({**_spec(), "cpu_limit": 0}, new_identity=True)
    with pytest.raises(EnvironmentValidationError, match="memory_limit_mb"):
        ExecutionEnvironment.from_mapping({**_spec(), "memory_limit_mb": 0}, new_identity=True)
    with pytest.raises(EnvironmentValidationError, match="lifetime_seconds"):
        ExecutionEnvironment.from_mapping({**_spec(), "lifetime_seconds": 0}, new_identity=True)


def test_provider_type_confusion_is_rejected(tmp_path):
    runtime, _provider = _runtime(tmp_path)
    with pytest.raises(EnvironmentValidationError, match="does not support"):
        runtime.create(
            {
                **_spec(),
                "environment_type": "oci_container",
                "provider": "local-sandbox",
                "image": "ubuntu:24.04",
            }
        )

def test_escape_and_resource_exhaustion_inputs_fail_closed():
    with pytest.raises(EnvironmentValidationError, match="unknown environment fields"):
        ExecutionEnvironment.from_mapping({**_spec(), "privileged": True}, new_identity=True)
    with pytest.raises(EnvironmentValidationError, match="network_policy.mode"):
        ExecutionEnvironment.from_mapping(
            {**_spec(), "network_policy": {"mode": "host"}},
            new_identity=True,
        )
    with pytest.raises(EnvironmentValidationError, match="cwd"):
        EnvironmentCommand.from_mapping({"argv": ["python", "-V"], "cwd": "../escape"})
    with pytest.raises(EnvironmentValidationError, match="memory_limit_mb"):
        ExecutionEnvironment.from_mapping({**_spec(), "memory_limit_mb": 999999}, new_identity=True)
    with pytest.raises(EnvironmentValidationError, match="unknown command fields"):
        EnvironmentCommand.from_mapping({"argv": ["python"], "shell": True})

def test_environment_command_rejects_inline_secrets_and_shell_strings():
    with pytest.raises(EnvironmentValidationError, match="non-empty array"):
        EnvironmentCommand.from_mapping({"argv": "python -V"})
    with pytest.raises(EnvironmentValidationError, match="inline secret"):
        EnvironmentCommand.from_mapping(
            {"argv": ["python", "-V"], "env": {"API_TOKEN": "secret"}}
        )


def test_provider_compatibility_handshake_fails_closed():
    provider = FakeProvider()
    provider.contract_version = "future/v99"
    handshake = CompatibilityHandshake.for_provider(provider)
    assert handshake.compatible is False
    with pytest.raises(EnvironmentCompatibilityError, match="incompatible"):
        handshake.require_compatible()


def test_oci_command_is_default_deny_and_has_no_implicit_host_mount(tmp_path):
    provider = OCIContainerProvider(engine_path="docker")
    environment = ExecutionEnvironment.from_mapping(
        {
            "environment_type": "oci_container",
            "provider": "oci",
            "image": "ubuntu@sha256:" + "a" * 64,
            "cpu_limit": 2,
            "memory_limit_mb": 512,
            "network_policy": {"mode": "none"},
            "filesystem_policy": {"read_only_root": True, "temporary_filesystem_mb": 64},
            "device_policy": {"gpu": "none", "devices": []},
            "workspace_mounts": [],
        },
        new_identity=True,
    )
    argv = provider.build_create_command(environment, tmp_path)
    joined = " ".join(argv)
    assert "--network none" in joined
    assert "--read-only" in argv
    assert "--cap-drop ALL" in joined
    assert "--security-opt no-new-privileges" in joined
    assert "--user 65532:65532" in joined
    assert "--privileged" not in argv
    assert "--pid=host" not in argv
    assert "--network=host" not in argv
    assert "--volume" not in argv
    assert "docker.sock" not in joined


def test_oci_mount_is_explicit_bounded_and_network_allowlist_fails_closed(tmp_path):
    (tmp_path / "project").mkdir()
    provider = OCIContainerProvider(engine_path="podman")
    environment = ExecutionEnvironment.from_mapping(
        {
            "environment_type": "oci_container",
            "provider": "oci",
            "image": "ubuntu:24.04",
            "workspace_mounts": [
                {
                    "source": "project",
                    "target": "/model-workspace/project",
                    "mode": "read-only",
                }
            ],
        },
        new_identity=True,
    )
    argv = provider.build_create_command(environment, tmp_path)
    mount_value = argv[argv.index("--volume") + 1]
    assert mount_value.endswith(":/model-workspace/project:ro")

    networked = ExecutionEnvironment.from_mapping(
        {
            "environment_type": "oci_container",
            "provider": "oci",
            "image": "ubuntu:24.04",
            "network_policy": {"mode": "http", "allowed_hosts": ["pypi.org"]},
        },
        new_identity=True,
    )
    with pytest.raises(EnvironmentProviderError, match="egress proxy"):
        provider.build_create_command(networked, tmp_path)


def test_oci_provider_without_engine_is_explicitly_unavailable(monkeypatch):
    monkeypatch.setattr("nous_runtime.environments.providers.shutil.which", lambda _name: None)
    provider = OCIContainerProvider()
    assert provider.probe()["available"] is False
    environment = ExecutionEnvironment.from_mapping(
        {
            "environment_type": "oci_container",
            "provider": "oci",
            "image": "ubuntu:24.04",
        },
        new_identity=True,
    )
    with pytest.raises(EnvironmentProviderError, match="unavailable"):
        provider.build_create_command(environment, Path.cwd())


def test_local_mount_namespace_and_expired_lifetime_fail_closed(tmp_path):
    provider = LocalSandboxProvider()
    runtime = EnvironmentRuntime(
        tmp_path,
        providers=EnvironmentProviderRegistry({"local-sandbox": provider}),
    )
    mounted = runtime.create(
        {
            **_spec(),
            "workspace_mounts": [
                {
                    "source": ".",
                    "target": "/model-workspace",
                    "mode": "read-only",
                }
            ],
        }
    )
    with pytest.raises(EnvironmentProviderError, match="mount namespace"):
        runtime.start(mounted["environment_id"])

    created = runtime.create(_spec())
    value = runtime.get(created["environment_id"])
    value.pop("sha256")
    value.pop("expired")
    value["created_at"] = "2000-01-01T00:00:00.000Z"
    expired = ExecutionEnvironment.from_mapping(value)
    runtime._write_environment(runtime._environment_path(expired.environment_id), expired)
    assert runtime.get(expired.environment_id)["expired"] is True
    with pytest.raises(EnvironmentValidationError, match="lifetime has expired"):
        runtime.start(expired.environment_id)

@requires_strong_sandbox
def test_real_local_sandbox_executes_through_process_sandbox(tmp_path):
    provider = LocalSandboxProvider()
    runtime = EnvironmentRuntime(
        tmp_path,
        providers=EnvironmentProviderRegistry({"local-sandbox": provider}),
    )
    created = runtime.create(_spec())
    runtime.start(created["environment_id"])
    result = runtime.run(
        created["environment_id"],
        {
            "argv": [sys.executable, "-c", "print('local-sandbox-ok')"],
            "timeout_seconds": 10,
        },
    )
    assert result["ok"] is True
    assert result["stdout"].strip() == "local-sandbox-ok"
    assert result["peak_memory_bytes"] >= 0
    destroyed = runtime.destroy(created["environment_id"])
    assert destroyed["state"] == "destroyed"

@requires_strong_sandbox
def test_local_timeout_kills_process_and_preserves_ready_environment(tmp_path):
    provider = LocalSandboxProvider()
    runtime = EnvironmentRuntime(
        tmp_path,
        providers=EnvironmentProviderRegistry({"local-sandbox": provider}),
    )
    created = runtime.create(_spec())
    runtime.start(created["environment_id"])
    result = runtime.run(
        created["environment_id"],
        {
            "argv": [sys.executable, "-c", "import time; time.sleep(30)"],
            "timeout_seconds": 1,
        },
    )
    assert result["ok"] is False
    assert result["timed_out"] is True
    assert runtime.get(created["environment_id"])["state"] == "ready"
    runtime.destroy(created["environment_id"])

def test_environment_lifecycle_persists_events_artifact_and_restart(tmp_path):
    runtime, provider = _runtime(tmp_path)
    created = runtime.create(_spec())
    environment_id = created["environment_id"]
    assert created["state"] == "created"
    assert created["compatibility"]["compatible"] is True

    started = EnvironmentRuntime(
        tmp_path,
        providers=EnvironmentProviderRegistry({"local-sandbox": provider}),
    ).start(environment_id)
    assert started["state"] == "ready"

    result = EnvironmentRuntime(
        tmp_path,
        providers=EnvironmentProviderRegistry({"local-sandbox": provider}),
    ).run(
        environment_id,
        {"argv": ["python", "-c", "print('ok')"], "timeout_seconds": 5},
    )
    assert result["ok"] is True
    assert result["state"] == "ready"
    assert (tmp_path / result["artifact"]["location"]).is_file()

    stopped = runtime.stop(environment_id)
    assert stopped["state"] == "stopped"
    destroyed = runtime.destroy(environment_id)
    assert destroyed["state"] == "destroyed"
    assert provider.stopped is True
    assert provider.destroyed is True

    destroy_events = EventStream(str(tmp_path)).load_events(destroyed["operation_run_id"])
    assert [event.event_type for event in destroy_events] == [
        "run.created",
        "command.proposed",
        "run.started",
        "environment.destroyed",
        "run.completed",
    ]

    start_events = EventStream(str(tmp_path)).load_events(started["operation_run_id"])
    assert [event.event_type for event in start_events] == [
        "run.created",
        "command.proposed",
        "run.started",
        "environment.preparing",
        "environment.ready",
        "environment.started",
        "run.completed",
    ]
    run_events = EventStream(str(tmp_path)).load_events(result["operation_run_id"])
    assert "artifact.created" in [event.event_type for event in run_events]
    assert run_events[-1].event_type == "run.completed"


def test_environment_contract_tamper_fails_closed(tmp_path):
    runtime, _provider = _runtime(tmp_path)
    created = runtime.create(_spec())
    path = (
        tmp_path
        / ".nous"
        / "environments"
        / "records"
        / f"{created['environment_id']}.json"
    )
    value = json.loads(path.read_text(encoding="utf-8"))
    value["memory_limit_mb"] = 8192
    path.write_text(json.dumps(value), encoding="utf-8")
    with pytest.raises(EnvironmentValidationError, match="digest mismatch"):
        runtime.get(created["environment_id"])


def test_provider_failure_moves_environment_to_failed_and_records_event(tmp_path):
    runtime, _provider = _runtime(tmp_path, FakeProvider(fail_prepare=True))
    created = runtime.create(_spec())
    with pytest.raises(EnvironmentProviderError, match="prepare failure"):
        runtime.start(created["environment_id"])
    assert runtime.get(created["environment_id"])["state"] == "failed"
    all_events = []
    for run in EventStream(str(tmp_path)).list_runs():
        all_events.extend(EventStream(str(tmp_path)).load_events(run.run_id))
    assert "environment.failed" in [event.event_type for event in all_events]


def test_cleanup_failure_is_audited_and_fails_environment(tmp_path):
    runtime, _provider = _runtime(tmp_path, FakeProvider(fail_destroy=True))
    created = runtime.create(_spec())
    runtime.start(created["environment_id"])
    with pytest.raises(EnvironmentProviderError, match="cleanup failure"):
        runtime.destroy(created["environment_id"])
    assert runtime.get(created["environment_id"])["state"] == "failed"
    events = []
    stream = EventStream(str(tmp_path))
    for run in stream.list_runs():
        events.extend(stream.load_events(run.run_id))
    assert "environment.failed" in [event.event_type for event in events]
    assert any(event.event_type == "run.failed" for event in events)

def test_local_provider_reports_isolation_truthfully():
    status = LocalSandboxProvider().probe()
    ready = executable_path() is not None
    assert status["available"] is ready
    assert status["evidence_level"] == ("strong-vm" if ready else "unavailable")
    assert status["hard_network_isolation"] is ready
    assert status["filesystem_namespace_isolation"] is ready
    assert status["resource_isolation"] == (
        "strong_vm" if ready else "resource_only"
    )
    assert bool(status["limitations"]) is (not ready)


def test_environment_routes_are_governed_before_handler(monkeypatch, tmp_path):
    captured = {}

    class Gate:
        def evaluate(self, proposal, context):
            captured["proposal"] = proposal
            return SimpleNamespace(
                action_mode="ASK_APPROVAL",
                rule_class="USER_APPROVABLE",
                reason_code="APPROVAL_REQUIRED",
                reason_message="Approval required",
                decision_id="decision-environment",
            )

    monkeypatch.setenv("NOUS_API_TOKEN", "secret")
    monkeypatch.setenv("NOUS_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setattr("nous_runtime.governance.get_gate", lambda: Gate())

    response = routes.route_server(
        "POST",
        "/api/v1/environments",
        body=_spec(),
        auth={"token": "secret", "loopback": True},
    )
    assert response["error"]["code"] == "NOUS_APPROVAL_REQUIRED"
    assert captured["proposal"].capability_id == "environment.create"
    assert captured["proposal"].side_effect_class == "local_write"
    assert captured["proposal"].required_permissions == ("runtime.execute",)
