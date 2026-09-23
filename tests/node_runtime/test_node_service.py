from __future__ import annotations

import json
import threading
import time
from pathlib import Path

import pytest
from typer.testing import CliRunner

from nous_runtime.cli.main import app as nous_app
from nous_runtime.node_runtime.cli import node_daemon_app
from nous_runtime.node_runtime.service import NodeRuntimeConfig, NodeRuntimeService


def test_node_identity_is_cryptographic_and_stable_across_restart(tmp_path: Path):
    state = tmp_path / "node"
    first = NodeRuntimeService(NodeRuntimeConfig(state_dir=state, node_name="edge-1"))
    second = NodeRuntimeService(NodeRuntimeConfig(state_dir=state, node_name="ignored"))

    assert first.identity.node_id == second.identity.node_id
    assert first.identity.public_key == second.identity.public_key
    assert len(first.identity.public_key) == 64
    assert first.identity.node_name == "edge-1"
    assert first.private_key_path.is_file()
    assert "PRIVATE KEY" not in first.identity_path.read_text(encoding="utf-8")


def test_heartbeat_sequence_continues_across_process_restart(tmp_path: Path):
    state = tmp_path / "node"
    first = NodeRuntimeService(NodeRuntimeConfig(state_dir=state))
    assert first.run_once()["heartbeat_sequence"] == 1

    restarted = NodeRuntimeService(NodeRuntimeConfig(state_dir=state))

    assert restarted.run_once()["heartbeat_sequence"] == 2


def test_run_once_reads_real_host_resources_and_devices_without_llm(
    monkeypatch, tmp_path: Path
):
    monkeypatch.setenv("NOUS_NO_INTELLIGENCE", "1")
    service = NodeRuntimeService(NodeRuntimeConfig(state_dir=tmp_path / "node"))

    status = service.run_once()

    resources = status["resources"]
    assert status["state"] == "ONLINE"
    assert status["intelligence_providers"] == 0
    assert resources["os"]
    assert resources["architecture"]
    assert resources["cpu_logical"] >= 1
    assert resources["memory_total_bytes"] > 0
    assert resources["disk_total_bytes"] > 0
    assert isinstance(resources["network_addresses"], list)
    assert resources["measurement_source"] == "host-os"
    assert status["execution_host"]["tools"]["python"]["available"] is True
    assert status["execution_host"]["grants_capabilities"] is False
    assert status["devices"]
    assert status["artifact_cache"]["objects"] == 0
    assert status["registration"]["authority"] == "none"


def test_node_workload_is_bounded_and_idempotent(tmp_path: Path):
    service = NodeRuntimeService(NodeRuntimeConfig(state_dir=tmp_path / "node"))

    first = service.execute_workload("work-1", "system.echo", {"message": "真实节点"})
    duplicate = service.execute_workload(
        "work-1", "system.echo", {"message": "must-not-reexecute"}
    )
    unavailable = service.execute_workload("work-2", "process.shell", {})

    assert first == duplicate
    assert first["state"] == "COMPLETED"
    assert first["output"] == {"echo": "真实节点"}
    assert unavailable["state"] == "FAILED"
    assert unavailable["error_code"] == "NOUS_NODE_CAPABILITY_UNAVAILABLE"
    assert first["receipt"]["input_digest"]

    restarted = NodeRuntimeService(NodeRuntimeConfig(state_dir=tmp_path / "node"))
    persisted = restarted.execute_workload(
        "work-1", "system.echo", {"message": "must-not-reexecute"}
    )
    assert persisted == first


def test_at_most_once_workload_fails_closed_after_uncertain_crash(tmp_path: Path):
    state = tmp_path / "node"
    service = NodeRuntimeService(NodeRuntimeConfig(state_dir=state))
    binding = {
        "intent_id": "intent-1",
        "effect_contract_digest": "a" * 64,
        "target_ref": "node://arm64-lab/service/test-api",
        "target_binding_digest": "1" * 64,
        "workload_id": "workload-1",
        "request_digest": "2" * 64,
        "provider_revision": "provider-1",
    }
    calls = 0

    def interrupted(_arguments: dict[str, object]) -> dict[str, object]:
        nonlocal calls
        calls += 1
        raise SystemExit("simulated process loss after possible effect")

    service._handlers["test.interrupted"] = interrupted
    with pytest.raises(SystemExit, match="simulated process loss"):
        service.execute_workload(
            "effect-1",
            "test.interrupted",
            {"version": "B"},
            delivery_semantics="at_most_once",
            binding=binding,
        )
    restarted = NodeRuntimeService(NodeRuntimeConfig(state_dir=state))
    restarted._handlers["test.interrupted"] = interrupted
    recovered = restarted.execute_workload(
        "effect-1",
        "test.interrupted",
        {"version": "B"},
        delivery_semantics="at_most_once",
        binding=binding,
    )
    assert recovered["state"] == "RECOVERY_REQUIRED"
    assert recovered["error_code"] == "NOUS_NODE_UNCERTAIN_EFFECT"
    assert calls == 1
    with pytest.raises(ValueError, match="binding collision"):
        restarted.execute_workload(
            "effect-1",
            "test.interrupted",
            {"version": "C"},
            delivery_semantics="at_most_once",
            binding=binding,
        )


def test_at_most_once_receipt_binds_signed_node_operation(tmp_path: Path):
    service = NodeRuntimeService(NodeRuntimeConfig(state_dir=tmp_path / "node"))
    binding = {
        "intent_id": "intent-2",
        "effect_contract_digest": "b" * 64,
        "target_ref": "node://arm64-lab/service/test-api",
        "target_binding_digest": "3" * 64,
        "workload_id": "workload-2",
        "request_digest": "4" * 64,
        "provider_revision": "provider-1",
    }
    result = service.execute_workload(
        "effect-2",
        "system.echo",
        {"message": "B"},
        delivery_semantics="at_most_once",
        binding=binding,
    )
    assert result["state"] == "COMPLETED"
    assert result["receipt"]["node_id"] == service.identity.node_id
    assert result["receipt"]["intent_id"] == binding["intent_id"]
    assert (
        result["receipt"]["effect_contract_digest"] == binding["effect_contract_digest"]
    )
    assert result["receipt"]["target_ref"] == binding["target_ref"]
    assert result["receipt"]["request_digest"] == result["request_digest"]


def test_concurrent_at_most_once_delivery_does_not_call_handler_twice(tmp_path: Path):
    service = NodeRuntimeService(NodeRuntimeConfig(state_dir=tmp_path / "node"))
    binding = {
        "intent_id": "intent-concurrent",
        "effect_contract_digest": "d" * 64,
        "target_ref": "node://arm64-lab/service/test-api",
        "target_binding_digest": "5" * 64,
        "workload_id": "workload-concurrent",
        "request_digest": "6" * 64,
        "provider_revision": "provider-1",
    }
    entered = threading.Event()
    release = threading.Event()
    calls = 0
    result_holder: list[dict[str, object]] = []

    def effect(_arguments: dict[str, object]) -> dict[str, object]:
        nonlocal calls
        calls += 1
        entered.set()
        assert release.wait(timeout=5)
        return {"version": "B"}

    service._handlers["test.concurrent"] = effect

    def first_delivery() -> None:
        result_holder.append(
            service.execute_workload(
                "effect-concurrent",
                "test.concurrent",
                {"version": "B"},
                delivery_semantics="at_most_once",
                binding=binding,
            )
        )

    worker = threading.Thread(target=first_delivery)
    worker.start()
    try:
        assert entered.wait(timeout=5)
        second = service.execute_workload(
            "effect-concurrent",
            "test.concurrent",
            {"version": "B"},
            delivery_semantics="at_most_once",
            binding=binding,
        )
        assert second["state"] == "RECOVERY_REQUIRED"
        assert (
            service.stop_workload("effect-concurrent")["stop_result"]
            == "EFFECT_IN_FLIGHT"
        )
        assert calls == 1
    finally:
        release.set()
        worker.join(timeout=5)
    assert result_holder[0]["state"] == "COMPLETED"
    assert calls == 1


def test_resource_leases_are_exclusive_durable_and_fenced(tmp_path: Path):
    state = tmp_path / "node"
    service = NodeRuntimeService(NodeRuntimeConfig(state_dir=state))

    first = service.acquire_lease("lease-1", "gpu:0", 60)
    duplicate = service.acquire_lease("lease-1", "gpu:0", 60)

    assert duplicate == first
    assert first["state"] == "ACTIVE"
    assert first["authority"] == "none"
    assert first["kernel_traversed"] is False
    assert first["resource_enforced"] is False
    assert first["fencing_token"] == 1
    with pytest.raises(ValueError, match="already leased"):
        service.acquire_lease("lease-2", "gpu:0", 60)

    restarted = NodeRuntimeService(NodeRuntimeConfig(state_dir=state))
    assert restarted.acquire_lease("lease-1", "gpu:0", 60) == first
    released = restarted.release_lease("lease-1", "gpu:0")
    second = restarted.acquire_lease("lease-2", "gpu:0", 60)
    assert released["state"] == "RELEASED"
    assert second["fencing_token"] == 2


@pytest.mark.parametrize("ttl", [float("nan"), float("inf"), float("-inf"), True])
def test_node_lease_rejects_invalid_ttl(tmp_path, ttl):
    service = NodeRuntimeService(NodeRuntimeConfig(state_dir=tmp_path / "node"))
    with pytest.raises(ValueError):
        service.acquire_lease("lease-1", "gpu:0", ttl)
    assert not service.leases_path.exists()


@pytest.mark.parametrize(
    "stored", ["broken", "{}", "[]", '{"counter": true}', '{"counter": -1}']
)
def test_corrupt_fencing_counter_cannot_reset_to_one(tmp_path, stored):
    service = NodeRuntimeService(NodeRuntimeConfig(state_dir=tmp_path / "node"))
    service.lease_counter_path.write_text(stored, encoding="utf-8")
    with pytest.raises(ValueError, match="fencing counter"):
        service.acquire_lease("lease-1", "gpu:0", 60)
    assert service.lease_counter_path.read_text(encoding="utf-8") == stored


def test_workload_stop_is_prestart_idempotent_and_never_claims_to_stop_terminal_work(
    tmp_path: Path,
):
    service = NodeRuntimeService(NodeRuntimeConfig(state_dir=tmp_path / "node"))

    cancelled = service.stop_workload("work-before-start")
    repeated = service.stop_workload("work-before-start")
    completed = service.execute_workload(
        "work-complete", "system.echo", {"message": "ok"}
    )
    stopped_terminal = service.stop_workload("work-complete")

    assert cancelled["state"] == "CANCELLED"
    assert repeated["state"] == "CANCELLED"
    assert completed["state"] == "COMPLETED"
    assert stopped_terminal["state"] == "COMPLETED"
    assert stopped_terminal["stop_result"] == "ALREADY_TERMINAL"


def test_node_daemon_heartbeats_watchdog_and_graceful_shutdown(tmp_path: Path):
    service = NodeRuntimeService(
        NodeRuntimeConfig(state_dir=tmp_path / "node", heartbeat_seconds=0.05)
    )
    thread = threading.Thread(
        target=service.run_forever,
        kwargs={"install_signal_handlers": False},
    )
    thread.start()
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        if service.status_path.is_file():
            status = json.loads(service.status_path.read_text(encoding="utf-8"))
            if status.get("heartbeat_sequence", 0) >= 2:
                break
        time.sleep(0.02)
    service.stop()
    thread.join(timeout=3)

    assert not thread.is_alive()
    final = json.loads(service.status_path.read_text(encoding="utf-8"))
    assert final["state"] == "STOPPED"
    assert final["watchdog"]["healthy"] is True
    events = [
        json.loads(line)
        for line in service.telemetry_path.read_text(encoding="utf-8").splitlines()
    ]
    assert {event["event_type"] for event in events} >= {
        "node.started",
        "node.heartbeat",
        "node.stopped",
    }


def test_nous_node_cli_once_emits_machine_readable_status(tmp_path: Path):
    result = CliRunner().invoke(
        node_daemon_app,
        [
            "--state-dir",
            str(tmp_path / "node"),
            "--name",
            "cli-node",
            "--once",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["node_name"] == "cli-node"
    assert payload["state"] == "ONLINE"
    assert payload["resources"]["measurement_source"] == "host-os"


def test_main_node_status_and_list_show_durable_local_node(tmp_path: Path):
    state = tmp_path / "node"
    service = NodeRuntimeService(
        NodeRuntimeConfig(state_dir=state, node_name="visible-node")
    )
    service.run_once()
    runner = CliRunner()

    status = runner.invoke(
        nous_app, ["node", "status", "--state-dir", str(state), "--json"]
    )
    listed = runner.invoke(
        nous_app, ["node", "list", "--state-dir", str(state), "--json"]
    )

    assert status.exit_code == 0, status.output
    assert listed.exit_code == 0, listed.output
    assert json.loads(status.output)["local_node"]["state"] == "ONLINE"
    entries = json.loads(listed.output)
    assert entries[0]["node_id"] == service.identity.node_id
    assert entries[0]["is_online"] is True
