"""Recorded Work remains deliverable without admitting work from failed probes."""

from __future__ import annotations

import asyncio
import json
import logging
import socket
from pathlib import Path

import pytest
from websockets.exceptions import ConnectionClosedError
from websockets.frames import Close

from nous_runtime.node_runtime.protocol import NodeProtocolEnvelope, NodeProtocolError
from nous_runtime.node_runtime.relay import NodeRelayClient, NodeRelayServer
from nous_runtime.node_runtime.service import NodeRuntimeConfig, NodeRuntimeService


def _binding(workload_id: str) -> dict[str, str]:
    return {
        "intent_id": "intent-original",
        "effect_contract_digest": "a" * 64,
        "target_ref": "node://fake/service/echo",
        "target_binding_digest": "b" * 64,
        "workload_id": workload_id,
        "request_digest": "c" * 64,
        "provider_revision": "fake-1",
    }


@pytest.mark.parametrize("delivery_semantics", ["idempotent", "at_most_once"])
def test_recorded_result_reconciles_after_hostname_probe_failure(
    tmp_path: Path, monkeypatch, caplog, delivery_semantics: str
) -> None:
    async def scenario() -> None:
        state_dir = tmp_path / "node"
        service = NodeRuntimeService(NodeRuntimeConfig(state_dir))
        workload_id = "original-work"
        binding = _binding(workload_id) if delivery_semantics == "at_most_once" else {}
        arguments = {"message": "original"}
        executions = 0

        def execute(arguments):
            nonlocal executions
            executions += 1
            return {"echo": arguments["message"]}

        service._handlers["system.echo"] = execute
        original = service.execute_workload(
            workload_id,
            "system.echo",
            arguments,
            delivery_semantics=delivery_semantics,
            binding=binding,
        )
        # A response loss/restart retains the original Node journal and identity.
        restarted = NodeRuntimeService(NodeRuntimeConfig(state_dir))
        restarted._handlers["system.echo"] = execute
        assert restarted.identity == service.identity
        server = NodeRelayServer(heartbeat_seconds=0.05)
        server.register_node(restarted.identity.node_id, restarted.identity.public_key)
        await server.queue_workload(
            restarted.identity.node_id,
            workload_id,
            "system.echo",
            arguments,
            delivery_semantics=delivery_semantics,
            binding=binding,
        )
        delivered, healthy = asyncio.Event(), asyncio.Event()
        handle_message = server._handle_message

        async def observe_result(websocket, node_id, envelope):
            await handle_message(websocket, node_id, envelope)
            if envelope.message_type == "WORKLOAD_STATUS":
                delivered.set()
            elif envelope.message_type == "RESOURCE_REPORT":
                healthy.set()

        monkeypatch.setattr(server, "_handle_message", observe_result)
        url = await server.start()
        getaddrinfo = socket.getaddrinfo
        hostname = socket.gethostname()

        def failed_hostname_probe(host, port, *args, **kwargs):
            if host == hostname and port is None:
                raise socket.gaierror("fake-sensitive-probe-detail")
            return getaddrinfo(host, port, *args, **kwargs)

        monkeypatch.setattr(socket, "getaddrinfo", failed_hostname_probe)
        stop = asyncio.Event()
        client = NodeRelayClient(
            restarted, url, server.public_key, heartbeat_seconds=0.05
        )
        task = asyncio.create_task(client.run_forever(stop))
        try:
            await asyncio.wait_for(delivered.wait(), timeout=5.0)
            assert executions == 1
            assert server.results[workload_id] == original
            assert (
                json.loads(restarted.workloads_path.read_text())[workload_id]
                == original
            )
            envelope = NodeProtocolEnvelope.from_json(
                json.dumps(server.result_envelopes[workload_id])
            )
            assert envelope.verify(restarted.identity.public_key)
            assert envelope.source == service.identity.node_id
            assert envelope.idempotency_key == workload_id
            assert envelope.payload["receipt"]["operation_id"] == workload_id
            assert envelope.payload["receipt"]["actor"] == service.identity.node_id
            if delivery_semantics == "at_most_once":
                assert envelope.payload["binding"] == binding
                assert envelope.payload["request_digest"] == original["request_digest"]
            assert workload_id not in server.pending.get(service.identity.node_id, {})
            status = server.controller_status()["nodes"][0]
            assert status["connectivity_state"] == "RECONCILING"
            assert status["schedulable"] is False
            assert status["has_resource_report"] is False
            assert status["has_device_report"] is False
            assert "gaierror" in caplog.text
            assert "fake-sensitive-probe-detail" not in caplog.text
            monkeypatch.setattr(
                restarted,
                "probe_resources",
                lambda: {
                    "schema": "nous.node-resource-report/v1",
                    "measurement_source": "fake",
                },
            )
            monkeypatch.setattr(restarted, "probe_devices", lambda: [])
            monkeypatch.setattr(restarted, "probe_execution_host", lambda *_: {})
            await asyncio.wait_for(healthy.wait(), timeout=5.0)
            status = server.controller_status()["nodes"][0]
            assert status["connectivity_state"] == "ONLINE"
            assert status["schedulable"] is True
            assert status["connectivity_lease_valid"] is True
            assert executions == 1
        finally:
            stop.set()
            try:
                await asyncio.wait_for(task, timeout=2)
            finally:
                await server.stop()

    caplog.set_level(logging.WARNING, logger="nous_runtime.node_runtime.relay")
    asyncio.run(scenario())


def test_relay_rejects_unrecorded_work_when_host_probe_fails(tmp_path, monkeypatch):
    async def scenario():
        service = NodeRuntimeService(NodeRuntimeConfig(tmp_path / "node"))
        executions = []
        service._handlers["system.echo"] = lambda arguments: executions.append(
            arguments
        )

        def probe_failure():
            raise OSError("controlled host probe failure")

        monkeypatch.setattr(service, "probe_resources", probe_failure)
        server = NodeRelayServer(heartbeat_seconds=0.05)
        server.register_node(service.identity.node_id, service.identity.public_key)
        await server.queue_workload(
            service.identity.node_id, "new-work", "system.echo", {"message": "new"}
        )
        url = await server.start()
        stop = asyncio.Event()
        client = NodeRelayClient(
            service, url, server.public_key, heartbeat_seconds=0.05
        )
        try:
            with pytest.raises(PermissionError, match="report unavailable"):
                await asyncio.wait_for(client.run_session(stop), timeout=5.0)
            assert executions == []
            assert service._workloads == {}
            assert not service.workloads_path.exists()
            assert server.results == {}
            assert "new-work" in server.pending[service.identity.node_id]
            assert server.controller_status()["nodes"][0]["schedulable"] is False
        finally:
            stop.set()
            await server.stop()

    asyncio.run(scenario())


def test_revocation_fences_cached_result_during_probe_failure(tmp_path, monkeypatch):
    async def scenario():
        service = NodeRuntimeService(NodeRuntimeConfig(tmp_path / "node"))
        workload_id = "revoked-original-work"
        binding = _binding(workload_id)
        executions = []
        service._handlers["system.echo"] = lambda arguments: (
            executions.append(arguments) or {"echo": arguments["message"]}
        )
        original = service.execute_workload(
            workload_id,
            "system.echo",
            {"message": "original"},
            delivery_semantics="at_most_once",
            binding=binding,
        )

        def failed_probe():
            raise OSError("controlled host probe failure")

        monkeypatch.setattr(service, "probe_resources", failed_probe)
        server = NodeRelayServer(
            state_dir=tmp_path / "controller", heartbeat_seconds=0.05
        )
        server.register_node(service.identity.node_id, service.identity.public_key)
        await server.queue_workload(
            service.identity.node_id,
            workload_id,
            "system.echo",
            {"message": "original"},
            delivery_semantics="at_most_once",
            binding=binding,
        )
        prepared, acknowledged, release, denied = (asyncio.Event() for _ in range(4))
        handle_message = server._handle_message
        require_trust = server._require_node_trust

        async def observe_ack(websocket, node_id, envelope):
            await handle_message(websocket, node_id, envelope)
            if (
                envelope.message_type == "ACK"
                and envelope.payload.get("acknowledged") == "WORKLOAD_START"
            ):
                acknowledged.set()

        def observe_trust(node_id, public_key=""):
            try:
                require_trust(node_id, public_key)
            except NodeProtocolError:
                if node_id in server._trust_document.get("revoked", {}):
                    denied.set()
                raise

        monkeypatch.setattr(server, "_handle_message", observe_ack)
        monkeypatch.setattr(server, "_require_node_trust", observe_trust)

        class HoldResultClient(NodeRelayClient):
            async def _send(self, websocket, message_type, payload, **kwargs):
                if message_type == "WORKLOAD_STATUS":
                    assert payload == original
                    prepared.set()
                    await release.wait()
                await super()._send(websocket, message_type, payload, **kwargs)

        url = await server.start()
        stop = asyncio.Event()
        client = HoldResultClient(
            service, url, server.public_key, heartbeat_seconds=0.05
        )
        task = asyncio.create_task(client.run_forever(stop))
        try:
            await asyncio.wait_for(prepared.wait(), timeout=5.0)
            await asyncio.wait_for(acknowledged.wait(), timeout=5.0)
            revoked = server.revoke_node(
                service.identity.node_id, admit=lambda _: {"actor_id": "fake-human"}
            )
            assert revoked["trust_status"] == "REVOKED"
            stop.set()
            release.set()
            await asyncio.wait_for(denied.wait(), timeout=5.0)
            await asyncio.wait_for(task, timeout=2)
            assert server.results == {}
            assert server.result_envelopes == {}
            assert (
                server.pending[service.identity.node_id][workload_id]["binding"]
                == binding
            )
            assert service._workloads[workload_id] == original
            assert (
                json.loads(service.workloads_path.read_text())[workload_id] == original
            )
            assert len(executions) == 1
            status = server.controller_status()["nodes"][0]
            assert status["trust_status"] == "REVOKED"
            assert status["connected"] is False
            assert status["schedulable"] is False
        finally:
            stop.set()
            release.set()
            try:
                await asyncio.wait_for(task, timeout=2)
            finally:
                await server.stop()

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "error",
    [
        OSError,
        socket.gaierror,
        TimeoutError,
        NodeProtocolError,
        pytest.param(
            lambda text: ConnectionClosedError(None, Close(1011, text)),
            id="keepalive-close",
        ),
    ],
)
def test_reconnect_failures_record_safe_diagnostics(
    tmp_path, monkeypatch, caplog, error
):
    async def scenario():
        service = NodeRuntimeService(NodeRuntimeConfig(tmp_path / "node"))
        client = NodeRelayClient(service, "ws://127.0.0.1:9", "00" * 32)
        stop = asyncio.Event()
        failure = error("fake-sensitive-relay-detail")

        async def fail_session(stop_event):
            stop_event.set()
            raise failure

        monkeypatch.setattr(client, "run_session", fail_session)
        await client.run_forever(stop)
        assert type(failure).__name__ in caplog.text
        assert "fake-sensitive-relay-detail" not in caplog.text
        assert "ws://127.0.0.1:9" not in caplog.text
        assert "00" * 32 not in caplog.text

    caplog.set_level(logging.WARNING, logger="nous_runtime.node_runtime.relay")
    asyncio.run(scenario())


def test_reconciliation_does_not_admit_new_execution(tmp_path):
    service = NodeRuntimeService(NodeRuntimeConfig(tmp_path / "node"))
    calls = []
    service._handlers["system.echo"] = lambda arguments: calls.append(arguments)
    with pytest.raises(PermissionError, match="report unavailable"):
        service.execute_workload(
            "never-executed", "system.echo", {"message": "new"}, reconcile_only=True
        )
    assert calls == []
    assert service._workloads == {}
    assert not service.workloads_path.exists()


@pytest.mark.parametrize("delivery_semantics", ["idempotent", "at_most_once"])
@pytest.mark.parametrize("changed", ["arguments", "capability", "binding"])
def test_reconciliation_requires_original_recorded_binding(
    tmp_path, delivery_semantics, changed
):
    service = NodeRuntimeService(NodeRuntimeConfig(tmp_path / "node"))
    workload_id = "original-work"
    arguments = {"message": "original"}
    binding = _binding(workload_id) if delivery_semantics == "at_most_once" else {}
    executions = 0

    def execute(arguments):
        nonlocal executions
        executions += 1
        return {"echo": arguments["message"]}

    service._handlers["system.echo"] = execute
    original = service.execute_workload(
        workload_id,
        "system.echo",
        arguments,
        delivery_semantics=delivery_semantics,
        binding=binding,
    )
    capability = "system.echo"
    if changed == "arguments":
        arguments = {"message": "changed"}
    elif changed == "capability":
        capability = "node.resource-report"
    else:
        binding = {**binding, "target_ref": "node://changed/service/echo"}
    with pytest.raises(ValueError, match="binding"):
        service.execute_workload(
            workload_id,
            capability,
            arguments,
            delivery_semantics=delivery_semantics,
            binding=binding,
            reconcile_only=True,
        )
    assert executions == 1
    assert service._workloads[workload_id] == original
    assert json.loads(service.workloads_path.read_text())[workload_id] == original


def test_reconciliation_preserves_uncertain_original_execution(tmp_path):
    service = NodeRuntimeService(NodeRuntimeConfig(tmp_path / "node"))
    workload_id = "uncertain-work"
    binding = _binding(workload_id)
    calls = []

    def interrupted(arguments):
        calls.append(arguments)
        raise SystemExit("controlled interrupted effect")

    service._handlers["system.echo"] = interrupted
    with pytest.raises(SystemExit):
        service.execute_workload(
            workload_id,
            "system.echo",
            {},
            delivery_semantics="at_most_once",
            binding=binding,
        )
    recorded = json.loads(service.workloads_path.read_text())[workload_id]
    result = service.execute_workload(
        workload_id,
        "system.echo",
        {},
        delivery_semantics="at_most_once",
        binding=binding,
        reconcile_only=True,
    )
    assert result["state"] == "RECOVERY_REQUIRED"
    assert result["error_code"] == "NOUS_NODE_UNCERTAIN_EFFECT"
    assert result["binding"] == recorded["binding"]
    assert result["request_digest"] == recorded["request_digest"]
    assert service._workloads[workload_id] == recorded
    assert len(calls) == 1
