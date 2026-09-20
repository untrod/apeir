from __future__ import annotations

import hashlib
import json
import threading
import time
from types import SimpleNamespace

import pytest

from nous_runtime.api import routes
from nous_runtime.environments import EnvironmentRuntime, EnvironmentValidationError
from nous_runtime.events import EventStream
from nous_runtime.simulations import (
    SimulationRuntime,
    SimulationSpec,
    SimulationValidationError,
)
from nous_runtime.simulations.worker import (
    SimulationCancelled,
    execute_payload,
)
from nous_runtime.kernel.windows_sandbox import executable_path


requires_strong_sandbox = pytest.mark.skipif(
    executable_path() is None,
    reason="Windows Sandbox requires the post-feature-enable reboot",
)


def _spec(**overrides):
    value = {
        "model_ref": "spacecraft-thermal/v1",
        "initial_state": {"initial_temperature": 290.0},
        "boundary_conditions": {"external_temperature": 3.0},
        "parameters": {
            "solar_flux": 1361.0,
            "surface_area": 2.0,
            "emissivity": 0.8,
            "thermal_capacity": 10000.0,
            "absorptivity": 0.7,
            "max_safe_temperature": 373.15,
        },
        "solver": "explicit-euler",
        "time_step": 1.0,
        "duration": 30.0,
        "seed": 42,
        "network_policy": {"mode": "none"},
        "resource_budget": {
            "cpu_limit": 1.0,
            "memory_limit_mb": 256,
            "wall_time_seconds": 60,
            "max_cases": 8,
            "max_retries": 0,
            "max_output_bytes": 2_000_000,
        },
    }
    value.update(overrides)
    return value


def _environment_spec():
    return {
        "environment_type": "local_sandbox",
        "provider": "local-sandbox",
        "network_policy": {"mode": "none"},
        "workspace_mounts": [],
        "device_policy": {"gpu": "none", "devices": []},
    }


def test_simulation_contract_is_strict_bounded_and_deterministic():
    spec = SimulationSpec.from_mapping(
        _spec(parameter_space={"solar_flux": [900.0, 1361.0]}),
        new_identity=True,
    )
    assert spec.schema_version == "nous.simulation/v1"
    assert spec.network_policy == {"mode": "none"}
    assert spec.resource_budget.max_retries == 0
    assert [case["solar_flux"] for case in spec.cases()] == [900.0, 1361.0]
    assert spec.digest() == SimulationSpec.from_mapping(spec.to_dict()).digest()

    with pytest.raises(SimulationValidationError, match="unknown simulation fields"):
        SimulationSpec.from_mapping({**_spec(), "host_python": True}, new_identity=True)
    with pytest.raises(SimulationValidationError, match="network must be none"):
        SimulationSpec.from_mapping(
            _spec(network_policy={"mode": "http"}), new_identity=True
        )
    with pytest.raises(SimulationValidationError, match="exceeds"):
        SimulationSpec.from_mapping(
            _spec(
                parameter_space={"a": list(range(4)), "b": list(range(4))},
                resource_budget={"max_cases": 8},
            ),
            new_identity=True,
        )
    with pytest.raises(SimulationValidationError, match="max_retries"):
        SimulationSpec.from_mapping(
            _spec(resource_budget={"max_retries": 4}), new_identity=True
        )


@requires_strong_sandbox
def test_environment_runtime_stages_and_collects_only_bounded_relative_files(tmp_path):
    runtime = EnvironmentRuntime(tmp_path)
    created = runtime.create(_environment_spec())
    environment_id = created["environment_id"]
    runtime.start(environment_id)

    staged = runtime.stage_file(environment_id, "input/spec.json", b"{}\n")
    assert staged["sha256"] == hashlib.sha256(b"{}\n").hexdigest()
    assert runtime.read_file(environment_id, "input/spec.json") == b"{}\n"

    with pytest.raises(EnvironmentValidationError, match="environment-relative"):
        runtime.stage_file(environment_id, "../escape", b"x")
    with pytest.raises(EnvironmentValidationError, match="forward slashes"):
        runtime.stage_file(environment_id, "..\\escape", b"x")
    with pytest.raises(EnvironmentValidationError, match="bounded size"):
        runtime.stage_file(environment_id, "too-large", b"xx", max_bytes=1)
    with pytest.raises(EnvironmentValidationError, match="forward slashes"):
        runtime.read_file(environment_id, "input\\spec.json")

    runtime.destroy(environment_id)
    with pytest.raises(EnvironmentValidationError, match="ready or running"):
        runtime.read_file(environment_id, "input/spec.json")


def test_reference_worker_is_deterministic_and_cancellable(tmp_path):
    spec = SimulationSpec.from_mapping(
        _spec(parameter_space={"solar_flux": [1000.0, 1361.0]}),
        new_identity=True,
    )
    first = execute_payload(spec.to_dict(), tmp_path / "first")
    second = execute_payload(spec.to_dict(), tmp_path / "second")
    assert first["result_digest"] == second["result_digest"]
    assert first["case_count"] == 2
    assert (tmp_path / "first" / "series.csv").is_file()
    assert (
        (tmp_path / "first" / "temperature.svg")
        .read_text(encoding="utf-8")
        .startswith("<svg")
    )

    marker = tmp_path / "cancel.flag"
    marker.write_text("cancel\n", encoding="utf-8")
    with pytest.raises(SimulationCancelled):
        execute_payload(spec.to_dict(), tmp_path / "cancelled", marker)


@requires_strong_sandbox
def test_runtime_executes_sweep_publishes_artifacts_and_verifies_replay(tmp_path):
    runtime = SimulationRuntime(tmp_path)
    created = runtime.create(_spec(parameter_space={"solar_flux": [1000.0, 1361.0]}))
    run = runtime.run(created["simulation_id"])

    assert run["state"] == "completed"
    assert run["case_count"] == 2
    assert len(run["execution_attempts"]) == 1
    assert len(run["artifacts"]) == 3
    assert runtime.environments.get(run["environment_id"])["state"] == "destroyed"
    for artifact in run["artifacts"]:
        content = (tmp_path / artifact["location"]).read_bytes()
        assert hashlib.sha256(content).hexdigest() == artifact["sha256"]
    reproducibility = run["reproducibility"]
    for key in (
        "code_hash",
        "model_hash",
        "input_hash",
        "parameter_hash",
        "spec_hash",
        "environment_fingerprint",
        "dependency_versions",
        "seed",
        "runtime_version",
        "kernel_version",
        "cpu",
        "gpu",
        "architecture",
        "captured_at",
    ):
        assert key in reproducibility

    replay = runtime.replay(run["simulation_run_id"])
    assert replay["result_digest"] == run["result_digest"]
    assert replay["replay"] == {
        "verified": True,
        "matching_contract": True,
        "within_tolerance": True,
        "maximum_absolute_error": 0.0,
        "absolute_tolerance": 1e-09,
        "relative_tolerance": 1e-09,
    }

    events = EventStream(str(tmp_path)).load_events(run["event_run_id"])
    event_types = [event.event_type for event in events]
    assert event_types[:4] == [
        "run.created",
        "command.proposed",
        "run.started",
        "simulation.started",
    ]
    assert event_types.count("artifact.created") == 4
    assert event_types[-2:] == ["simulation.completed", "run.completed"]


@requires_strong_sandbox
def test_retry_policy_is_bounded_and_audited(monkeypatch, tmp_path):
    runtime = SimulationRuntime(tmp_path)
    created = runtime.create(
        _spec(resource_budget={**_spec()["resource_budget"], "max_retries": 1})
    )
    original_run = runtime.environments.run
    calls = 0

    def flaky(environment_id, command):
        nonlocal calls
        calls += 1
        if calls == 1:
            return {
                "ok": False,
                "exit_code": 9,
                "stderr": "transient",
                "timed_out": False,
            }
        return original_run(environment_id, command)

    monkeypatch.setattr(runtime.environments, "run", flaky)
    run = runtime.run(created["simulation_id"])
    assert [item["ok"] for item in run["execution_attempts"]] == [False, True]
    events = EventStream(str(tmp_path)).load_events(run["event_run_id"])
    assert "simulation.retrying" in [event.event_type for event in events]


@requires_strong_sandbox
def test_worker_failure_is_persisted_and_environment_is_destroyed(tmp_path):
    runtime = SimulationRuntime(tmp_path)
    bad = _spec()
    bad["parameters"] = {
        key: value for key, value in bad["parameters"].items() if key != "solar_flux"
    }
    created = runtime.create(bad)
    with pytest.raises(SimulationValidationError, match="worker failed"):
        runtime.run(created["simulation_id"])
    failed = runtime.list_runs(simulation_id=created["simulation_id"])[0]
    assert failed["state"] == "failed"
    assert failed["execution_attempts"][0]["exit_code"] == 2
    assert runtime.environments.get(failed["environment_id"])["state"] == "destroyed"
    events = EventStream(str(tmp_path)).load_events(failed["event_run_id"])
    assert [event.event_type for event in events][-2:] == [
        "simulation.failed",
        "run.failed",
    ]


@requires_strong_sandbox
def test_active_simulation_can_be_cancelled(tmp_path):
    runtime = SimulationRuntime(tmp_path)
    created = runtime.create(
        _spec(duration=10.0, time_step=0.0001, output_schema=["json"])
    )
    holder = {}

    def execute():
        try:
            holder["result"] = runtime.run(created["simulation_id"])
        except Exception as exc:
            holder["error"] = exc

    thread = threading.Thread(target=execute)
    thread.start()
    active = (
        tmp_path
        / ".nous"
        / "simulations"
        / "active"
        / f"{created['simulation_id']}.json"
    )
    deadline = time.monotonic() + 10
    while not active.is_file() and thread.is_alive() and time.monotonic() < deadline:
        time.sleep(0.01)
    assert active.is_file()
    request = runtime.cancel(created["simulation_id"])
    assert request["cancellation_requested"] is True
    thread.join(timeout=20)
    assert not thread.is_alive()
    assert "error" not in holder
    assert holder["result"]["state"] == "cancelled"
    assert holder["result"]["execution_attempts"][0]["exit_code"] == 130


def test_persisted_contract_and_run_tampering_fail_closed(tmp_path):
    runtime = SimulationRuntime(tmp_path)
    created = runtime.create(_spec())
    spec_path = (
        tmp_path
        / ".nous"
        / "simulations"
        / "specs"
        / f"{created['simulation_id']}.json"
    )
    value = json.loads(spec_path.read_text(encoding="utf-8"))
    value["duration"] = 999.0
    spec_path.write_text(json.dumps(value), encoding="utf-8")
    with pytest.raises(SimulationValidationError, match="digest mismatch"):
        runtime.get(created["simulation_id"])


def test_simulation_routes_are_governed_before_handler(monkeypatch, tmp_path):
    captured = {}

    class Gate:
        def evaluate(self, proposal, context):
            captured["proposal"] = proposal
            return SimpleNamespace(
                action_mode="ASK_APPROVAL",
                rule_class="USER_APPROVABLE",
                reason_code="APPROVAL_REQUIRED",
                reason_message="Approval required",
                decision_id="decision-simulation",
            )

    monkeypatch.setenv("NOUS_API_TOKEN", "secret")
    monkeypatch.setenv("NOUS_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setattr("nous_runtime.governance.get_gate", lambda: Gate())

    response = routes.route_server(
        "POST",
        "/api/v1/simulations",
        body=_spec(),
        auth={"token": "secret", "loopback": True},
    )
    assert response["error"]["code"] == "NOUS_APPROVAL_REQUIRED"
    proposal = captured["proposal"]
    assert proposal.capability_id == "simulation.create"
    assert proposal.required_permissions == ("runtime.execute", "simulation.compute")
    assert not (tmp_path / ".nous" / "simulations" / "specs").exists()
