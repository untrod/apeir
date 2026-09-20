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
from nous_runtime.node_runtime.relay import NodeRelayClient, NodeRelayServer, public_key_hex
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
            await _wait_for(
                lambda: service.identity.node_id not in server.connections
            )

            first = server.results["work-r2-1"]
            assert first["state"] == "COMPLETED"
            assert first["output"] == {"echo": "first"}
            assert first["receipt"]["operation_id"] == "work-r2-1"
            assert server.reports[service.identity.node_id]["RESOURCE_REPORT"][
                "measurement_source"
            ] == "host-os"

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
                lambda: server.results.get("work-r2-1", {}).get("output")
                == {"echo": "first"}
                and "work-r2-1" not in server.pending[service.identity.node_id]
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
        client = NodeRelayClient(service, url, server.public_key, heartbeat_seconds=0.05)
        task = asyncio.create_task(client.run_forever(stop))
        try:
            await _wait_for(
                lambda: server.artifact_results.get(digest, {}).get("state") == "READY"
            )
            await _wait_for(
                lambda: server.lease_results.get("lease-remote-1", {}).get("state")
                == "ACTIVE"
            )
            await _wait_for(
                lambda: server.results.get("work-cancelled-1", {}).get("state")
                == "CANCELLED"
            )
            assert service.artifact_store.resolve(digest).read_bytes() == payload
            assert server.lease_results["lease-remote-1"]["fencing_token"] == 1
        finally:
            stop.set()
            await asyncio.wait_for(task, timeout=2)
            await server.stop()

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
