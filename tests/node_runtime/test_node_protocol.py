from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from nous_runtime.node_runtime.protocol import (
    NodeProtocolEnvelope,
    NodeProtocolError,
    ReplayWindow,
)
from nous_runtime.node_runtime.relay import (
    NodeRelayClient,
    NodeRelayServer,
    public_key_hex,
    remote_execution_receipt,
)
from nous_runtime.node_runtime.service import NodeRuntimeConfig, NodeRuntimeService
from nous_runtime.artifact import ArtifactType, ContentAddressedArtifactStore


def _signed(sequence: int = 1) -> tuple[NodeProtocolEnvelope, str]:
    key = Ed25519PrivateKey.generate()
    envelope = NodeProtocolEnvelope(
        message_type="HEARTBEAT",
        source="node-1",
        target="control_plane",
        sequence=sequence,
        payload={"status": "ONLINE"},
    ).sign(key)
    return envelope, public_key_hex(key)


def test_protocol_signature_detects_tampering_and_duplicate_json_keys():
    envelope, public = _signed()
    assert envelope.verify(public)
    envelope.payload["status"] = "TAMPERED"
    assert not envelope.verify(public)

    raw = '{"message_type":"ACK","message_type":"ERROR"}'
    with pytest.raises(NodeProtocolError, match="duplicate JSON key"):
        NodeProtocolEnvelope.from_json(raw)


def test_replay_window_rejects_duplicates_and_sequence_rollback():
    guard = ReplayWindow()
    first, _public = _signed(1)
    guard.accept(first)
    with pytest.raises(NodeProtocolError, match="duplicate"):
        guard.accept(first)
    second, _public = _signed(1)
    with pytest.raises(NodeProtocolError, match="sequence"):
        guard.accept(second)


def test_message_specific_payload_and_idempotency_are_fail_closed():
    key = Ed25519PrivateKey.generate()
    incomplete = NodeProtocolEnvelope(
        message_type="WORKLOAD_START",
        source="control_plane",
        target="node-1",
        sequence=1,
        payload={"workload_id": "work-1"},
    ).sign(key)
    with pytest.raises(NodeProtocolError, match="payload missing"):
        incomplete.to_json()

    missing_idempotency = NodeProtocolEnvelope(
        message_type="ARTIFACT_FETCH",
        source="node-1",
        target="control_plane",
        sequence=1,
        payload={"digest": "sha256:" + "0" * 64},
    ).sign(key)
    with pytest.raises(NodeProtocolError, match="idempotency_key"):
        missing_idempotency.to_json()


def test_remote_plaintext_websocket_is_rejected(tmp_path: Path):
    service = NodeRuntimeService(NodeRuntimeConfig(state_dir=tmp_path / "node"))
    with pytest.raises(ValueError, match="require wss"):
        NodeRelayClient(service, "ws://192.0.2.1:9770", "00" * 32)
    with pytest.raises(ValueError, match="requires TLS"):
        NodeRelayServer(host="0.0.0.0", port=9770)


def test_relay_identity_and_explicit_node_trust_are_durable(tmp_path: Path):
    state = tmp_path / "relay"
    first = NodeRelayServer(state_dir=state)
    first.register_node("node-1", "01" * 32)

    restarted = NodeRelayServer(state_dir=state)

    assert restarted.public_key == first.public_key
    assert restarted.node_keys == {"node-1": "01" * 32}


def test_relay_pending_assignment_and_signed_result_survive_restart(tmp_path: Path):
    async def scenario() -> None:
        state = tmp_path / "relay"
        service = NodeRuntimeService(NodeRuntimeConfig(state_dir=tmp_path / "node"))
        server = NodeRelayServer(state_dir=state, heartbeat_seconds=0.05)
        node_id = service.identity.node_id
        server.register_node(node_id, service.identity.public_key)
        await server.queue_workload(
            node_id, "work-durable-1", "system.echo", {"message": "durable"}
        )

        restarted = NodeRelayServer(state_dir=state, heartbeat_seconds=0.05)
        assert restarted.pending[node_id]["work-durable-1"]["arguments"] == {
            "message": "durable"
        }
        url = await restarted.start()
        stop = asyncio.Event()
        client = NodeRelayClient(
            service, url, restarted.public_key, heartbeat_seconds=0.05
        )
        task = asyncio.create_task(client.run_forever(stop))
        try:
            await _wait_for(lambda: "work-durable-1" in restarted.results)
        finally:
            stop.set()
            await asyncio.wait_for(task, timeout=2)
            await restarted.stop()

        recovered = NodeRelayServer(state_dir=state)
        assert "work-durable-1" not in recovered.pending[node_id]
        assert recovered.results["work-durable-1"]["output"] == {"echo": "durable"}
        signed = recovered.result_envelopes["work-durable-1"]
        envelope = NodeProtocolEnvelope.from_json(json.dumps(signed), check_time=False)
        assert envelope.verify(service.identity.public_key)
        assert envelope.source == node_id

        state_path = state / "workload-state.json"
        value = json.loads(state_path.read_text(encoding="utf-8"))
        value["results"]["work-durable-1"]["output"] = {"echo": "tampered"}
        state_path.write_text(json.dumps(value), encoding="utf-8")
        with pytest.raises(NodeProtocolError, match="signature is invalid"):
            NodeRelayServer(state_dir=state)

    asyncio.run(scenario())


def test_at_most_once_remote_receipt_is_bound_to_assignment(tmp_path: Path):
    async def scenario() -> None:
        service = NodeRuntimeService(NodeRuntimeConfig(state_dir=tmp_path / "node"))
        server = NodeRelayServer(state_dir=tmp_path / "relay", heartbeat_seconds=0.05)
        node_id = service.identity.node_id
        server.register_node(node_id, service.identity.public_key)
        binding = {
            "intent_id": "intent-remote-1",
            "effect_contract_digest": "c" * 64,
            "target_ref": "node://arm64-lab/service/test-api",
            "target_binding_digest": "7" * 64,
            "workload_id": "workload-remote-1",
            "request_digest": "8" * 64,
            "provider_revision": "provider-1",
        }
        await server.queue_workload(
            node_id,
            "effect-remote-1",
            "system.echo",
            {"message": "B"},
            delivery_semantics="at_most_once",
            binding=binding,
        )
        url = await server.start()
        stop = asyncio.Event()
        client = NodeRelayClient(
            service, url, server.public_key, heartbeat_seconds=0.05
        )
        task = asyncio.create_task(client.run_forever(stop))
        try:
            await _wait_for(lambda: "effect-remote-1" in server.results)
        finally:
            stop.set()
            await asyncio.wait_for(task, timeout=2)
            await server.stop()
        result = server.results["effect-remote-1"]
        assert result["receipt"]["intent_id"] == binding["intent_id"]
        assert (
            result["receipt"]["effect_contract_digest"]
            == binding["effect_contract_digest"]
        )
        assert result["receipt"]["node_id"] == node_id
        signed = NodeProtocolEnvelope.from_json(
            json.dumps(server.result_envelopes["effect-remote-1"]), check_time=False
        )
        assert signed.verify(service.identity.public_key)
        assert signed.payload == result
        remote = remote_execution_receipt(
            server.result_envelopes["effect-remote-1"],
            expected_operation_id="effect-remote-1",
        )
        assert remote["workload_id"] == binding["workload_id"]
        assert remote["request_digest"] == binding["request_digest"]
        assert remote["target_binding_digest"] == binding["target_binding_digest"]
        assert remote["signed_envelope"]["signature"] == signed.signature
        assert len(remote["signed_envelope_digest"]) == 64
        with pytest.raises(NodeProtocolError, match="result binding changed"):
            await server.queue_workload(
                node_id,
                "effect-remote-1",
                "system.echo",
                {"message": "C"},
                delivery_semantics="at_most_once",
                binding=binding,
            )

    asyncio.run(scenario())


def test_relay_rejects_status_from_wrong_trusted_node(tmp_path: Path):
    async def scenario() -> None:
        first = NodeRuntimeService(NodeRuntimeConfig(state_dir=tmp_path / "first"))
        second = NodeRuntimeService(NodeRuntimeConfig(state_dir=tmp_path / "second"))
        server = NodeRelayServer(state_dir=tmp_path / "relay")
        server.register_node(first.identity.node_id, first.identity.public_key)
        server.register_node(second.identity.node_id, second.identity.public_key)
        await server.queue_workload(
            first.identity.node_id, "work-bound-1", "system.echo"
        )
        signed = NodeProtocolEnvelope(
            message_type="WORKLOAD_STATUS",
            source=second.identity.node_id,
            target="control_plane",
            sequence=1,
            idempotency_key="work-bound-1",
            payload={"workload_id": "work-bound-1", "state": "COMPLETED"},
        ).sign(second.load_private_key())
        with pytest.raises(NodeProtocolError, match="no matching node assignment"):
            await server._handle_message(None, second.identity.node_id, signed)
        assert "work-bound-1" in server.pending[first.identity.node_id]
        assert "work-bound-1" not in server.results

    asyncio.run(scenario())


def test_stop_and_pending_execution_are_persisted_atomically(tmp_path: Path):
    async def scenario() -> None:
        state = tmp_path / "relay"
        service = NodeRuntimeService(NodeRuntimeConfig(state_dir=tmp_path / "node"))
        server = NodeRelayServer(state_dir=state)
        node_id = service.identity.node_id
        server.register_node(node_id, service.identity.public_key)
        await server.queue_workload(node_id, "work-stop-durable", "system.echo")
        await server.queue_workload_stop(node_id, "work-stop-durable")

        recovered = NodeRelayServer(state_dir=state)
        assert "work-stop-durable" not in recovered.pending[node_id]
        assert recovered.pending_controls[node_id] == [
            {
                "message_type": "WORKLOAD_STOP",
                "payload": {"workload_id": "work-stop-durable"},
                "idempotency_key": "work-stop-durable",
            }
        ]

    asyncio.run(scenario())


def test_real_websocket_registration_workload_and_reconnect_idempotency(tmp_path: Path):
    async def scenario() -> None:
        service = NodeRuntimeService(NodeRuntimeConfig(state_dir=tmp_path / "node"))
        server = NodeRelayServer(heartbeat_seconds=0.05)
        server.register_node(service.identity.node_id, service.identity.public_key)
        url = await server.start()
        try:
            await server.queue_workload(
                service.identity.node_id,
                "work-r2-1",
                "system.echo",
                {"message": "first"},
            )
            stop = asyncio.Event()
            client = NodeRelayClient(
                service, url, server.public_key, heartbeat_seconds=0.05
            )
            task = asyncio.create_task(client.run_forever(stop))
            await _wait_for(lambda: "work-r2-1" in server.results)
            stop.set()
            await asyncio.wait_for(task, timeout=2)
            await _wait_for(lambda: service.identity.node_id not in server.connections)

            first = server.results["work-r2-1"]
            assert first["state"] == "COMPLETED"
            assert first["output"] == {"echo": "first"}
            assert first["receipt"]["operation_id"] == "work-r2-1"
            assert (
                server.reports[service.identity.node_id]["RESOURCE_REPORT"][
                    "measurement_source"
                ]
                == "host-os"
            )

            await server.queue_workload(
                service.identity.node_id,
                "work-r2-1",
                "system.echo",
                {"message": "must-not-reexecute"},
            )
            stop2 = asyncio.Event()
            restarted_service = NodeRuntimeService(
                NodeRuntimeConfig(state_dir=tmp_path / "node")
            )
            restarted_client = NodeRelayClient(
                restarted_service, url, server.public_key, heartbeat_seconds=0.05
            )
            task2 = asyncio.create_task(restarted_client.run_forever(stop2))
            await _wait_for(
                lambda: (
                    server.results.get("work-r2-1", {}).get("output")
                    == {"echo": "first"}
                    and "work-r2-1" not in server.pending[service.identity.node_id]
                )
            )
            stop2.set()
            await asyncio.wait_for(task2, timeout=2)
            assert server.results["work-r2-1"]["output"] == {"echo": "first"}
            session = json.loads(client.session_path.read_text(encoding="utf-8"))
            assert session["session_id"] == server.sessions[service.identity.node_id]
        finally:
            await server.stop()

    asyncio.run(scenario())


def test_relay_transfers_verified_artifact_and_executes_lease_and_stop_controls(
    tmp_path: Path,
):
    async def scenario() -> None:
        relay_store = ContentAddressedArtifactStore(tmp_path / "relay-artifacts")
        payload = (b"apeir-remote-artifact-" * 30_000) + b"end"
        stored = relay_store.store_bytes(
            payload,
            artifact_type=ArtifactType.BINARY,
            name="remote.bin",
            produced_by="test",
        )
        digest = stored["artifact"]["digest"]
        service = NodeRuntimeService(NodeRuntimeConfig(state_dir=tmp_path / "node"))
        server = NodeRelayServer(
            heartbeat_seconds=0.05,
            artifact_store=relay_store,
        )
        server.register_node(service.identity.node_id, service.identity.public_key)
        await server.queue_artifact(service.identity.node_id, digest)
        await server.queue_lease_acquire(
            service.identity.node_id, "lease-remote-1", "gpu:0", 60
        )
        await server.queue_workload_stop(service.identity.node_id, "work-cancelled-1")
        url = await server.start()
        stop = asyncio.Event()
        client = NodeRelayClient(
            service, url, server.public_key, heartbeat_seconds=0.05
        )
        task = asyncio.create_task(client.run_forever(stop))
        try:
            await _wait_for(
                lambda: server.artifact_results.get(digest, {}).get("state") == "READY"
            )
            await _wait_for(
                lambda: (
                    server.lease_results.get("lease-remote-1", {}).get("state")
                    == "ACTIVE"
                )
            )
            await _wait_for(
                lambda: (
                    server.results.get("work-cancelled-1", {}).get("state")
                    == "CANCELLED"
                )
            )
            assert service.artifact_store.resolve(digest).read_bytes() == payload
            assert server.lease_results["lease-remote-1"]["fencing_token"] == 1
            assert server.pending_controls.get(service.identity.node_id, []) == []
        finally:
            stop.set()
            await asyncio.wait_for(task, timeout=2)
            await server.stop()

    asyncio.run(scenario())


def test_control_remains_pending_when_initial_delivery_fails(tmp_path: Path):
    class FailingConnection:
        async def send(self, _payload: str) -> None:
            raise OSError("simulated disconnect")

    async def scenario() -> None:
        service = NodeRuntimeService(NodeRuntimeConfig(state_dir=tmp_path / "node"))
        server = NodeRelayServer()
        node_id = service.identity.node_id
        server.register_node(node_id, service.identity.public_key)
        server.connections[node_id] = FailingConnection()

        with pytest.raises(OSError, match="simulated disconnect"):
            await server.queue_lease_acquire(node_id, "lease-retry-1", "gpu:0", 60)

        assert server.pending_controls[node_id] == [
            {
                "message_type": "LEASE_ACQUIRE",
                "payload": {
                    "lease_id": "lease-retry-1",
                    "resource_id": "gpu:0",
                    "ttl_seconds": 60,
                },
                "idempotency_key": "lease-retry-1",
            }
        ]

    asyncio.run(scenario())


async def _wait_for(predicate, timeout: float = 20.0) -> None:
    """Wait for relay convergence without assuming workstation-speed I/O.

    Hosted Windows runners can take more than five seconds to copy and verify the
    artifact while the complete test suite is under load. The assertion remains
    fail-closed; this only gives the asynchronous relay enough time to report its
    final state.
    """
    deadline = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < deadline:
        if predicate():
            return
        await asyncio.sleep(0.02)
    raise AssertionError("timed out waiting for relay state")
