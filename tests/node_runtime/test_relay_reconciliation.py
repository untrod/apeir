"""Recorded Work remains deliverable without admitting work from failed probes."""

from __future__ import annotations

import asyncio
from copy import deepcopy
import json
import logging
import socket
import sys
from pathlib import Path

import pytest
from websockets.asyncio.client import connect
from websockets.exceptions import ConnectionClosed
from websockets.exceptions import ConnectionClosedError
from websockets.frames import Close

from nous_runtime.node_runtime.protocol import (
    NODE_PROTOCOL_VERSION,
    NodeProtocolEnvelope,
    NodeProtocolError,
)
from nous_runtime.artifact import ContentAddressedArtifactStore
from nous_runtime.node_runtime.distributed_work import (
    DistributedWork,
    DistributedWorkState,
    WorkExecutionPolicy,
    WorkRequirements,
)
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


async def _record_verified_result(tmp_path, monkeypatch, *, first_stop=False):
    state = tmp_path / "controller"
    server = NodeRelayServer(
        state_dir=state,
        artifact_store=ContentAddressedArtifactStore(state / "artifacts"),
    )
    node = NodeRuntimeService(NodeRuntimeConfig(tmp_path / "node"))
    node_id = node.identity.node_id
    server.register_node(node_id, node.identity.public_key)
    work_id = "original-terminal-evidence"
    assert server.work_store is not None
    server.work_store.create(
        DistributedWork(
            work_id=work_id,
            intent="Preserve original terminal evidence before effect verification",
            execution_capability="system.echo",
            requirements=WorkRequirements(capabilities=("system.echo",)),
            execution_arguments={"message": 1},
            execution_policy=WorkExecutionPolicy(require_effect_verification=True),
        )
    )
    server.work_store.transition(
        work_id, DistributedWorkState.SCHEDULED, reason="controlled placement"
    )
    server.work_store.assign(work_id, node_id)
    server.stage_work_dispatch(work_id)
    request = json.loads((state / "provider-requests" / f"{work_id}.json").read_text())
    await server.queue_workload(
        node_id,
        work_id,
        request["capability"],
        request["arguments"],
        delivery_semantics="at_most_once",
        binding=request["binding"],
    )
    result = node.execute_workload(
        work_id,
        request["capability"],
        request["arguments"],
        delivery_semantics="at_most_once",
        binding=request["binding"],
    )
    if first_stop:
        await server._queue_control(
            node_id, "WORKLOAD_STOP", {"workload_id": work_id}, work_id
        )
        result = node.stop_workload(work_id)
    first = NodeProtocolEnvelope(
        message_type="WORKLOAD_STATUS",
        source=node_id,
        target="control_plane",
        sequence=1,
        payload=result,
        idempotency_key=work_id,
    ).sign(node.load_private_key())
    assert first.verify(node.identity.public_key)
    acknowledgements = []

    async def record_ack(websocket, target, kind, payload, **kwargs):
        acknowledgements.append((target, kind, payload, kwargs))

    monkeypatch.setattr(server, "_send", record_ack)
    await server._handle_message(None, node_id, first)
    assert server.reconcile_work(work_id)["work"]["state"] == "VERIFIED"
    return server, node, first, request, acknowledgements


def test_repeated_terminal_result_preserves_first_envelope_and_verified_work(
    tmp_path, monkeypatch
):
    async def scenario():
        server, node, first, request, acknowledgements = await _record_verified_result(
            tmp_path, monkeypatch
        )
        work_id = first.idempotency_key
        node_id = node.identity.node_id
        state_path = server.state_dir / "workload-state.json"
        original_state = state_path.read_bytes()
        result_path = server.provider_results / f"{work_id}.json"
        original_result = result_path.read_bytes()
        repeated = NodeProtocolEnvelope(
            message_type="WORKLOAD_STATUS",
            source=node_id,
            target="control_plane",
            sequence=2,
            payload=deepcopy(first.payload),
            idempotency_key=work_id,
        ).sign(node.load_private_key())
        assert repeated.verify(node.identity.public_key)
        assert repeated.to_dict() != first.to_dict()
        await server._handle_message(None, node_id, repeated)
        assert server.result_envelopes[work_id] == first.to_dict()
        assert server.results[work_id] == first.payload
        assert state_path.read_bytes() == original_state
        assert result_path.read_bytes() == original_result
        assert acknowledgements[-1][1:3] == (
            "ACK",
            {"acknowledged": "WORKLOAD_STATUS"},
        )
        assert acknowledgements[-1][3]["reply_to"] == repeated.message_id
        # Transport retries cannot restore a completed delivery to the queue.
        await server.queue_workload(
            node_id,
            work_id,
            request["capability"],
            request["arguments"],
            delivery_semantics="at_most_once",
            binding=request["binding"],
        )
        assert work_id not in server.pending.get(node_id, {})
        assert not (server.provider_requests / f"{work_id}.json").exists()
        restarted = NodeRelayServer(
            state_dir=server.state_dir,
            artifact_store=ContentAddressedArtifactStore(
                server.state_dir / "artifacts"
            ),
        )
        reconciled = restarted.reconcile_work(work_id)
        assert reconciled["work"]["state"] == "VERIFIED"
        assert reconciled["idempotent"] is True
        assert restarted.result_envelopes[work_id] == first.to_dict()
        assert (
            node.execute_workload(
                work_id,
                request["capability"],
                request["arguments"],
                delivery_semantics="at_most_once",
                binding=request["binding"],
            )
            == first.payload
        )

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "change",
    ["state", "output", "receipt", "binding", "source", "key", "bool", "float", "stop"],
)
def test_conflicting_terminal_replay_preserves_original_evidence(
    tmp_path, monkeypatch, change
):
    async def scenario():
        server, node, first, _request, acknowledgements = await _record_verified_result(
            tmp_path, monkeypatch
        )
        payload = deepcopy(first.payload)
        sender = node
        idempotency_key = first.idempotency_key
        if change == "source":
            sender = NodeRuntimeService(NodeRuntimeConfig(tmp_path / "other-node"))
            server.register_node(sender.identity.node_id, sender.identity.public_key)
        elif change == "key":
            idempotency_key = "different-work"
        elif change == "state":
            payload["state"] = "FAILED"
        elif change == "output":
            payload["output"] = {"echo": "changed"}
        elif change == "receipt":
            payload["receipt"]["effect_digest"] = "0" * 64
        elif change in {"bool", "float"}:
            payload["output"]["echo"] = True if change == "bool" else 1.0
        elif change == "stop":
            payload["stop_result"] = "arbitrary-control-value"
        else:
            payload["binding"]["intent_id"] = "changed-intent"
        repeated = NodeProtocolEnvelope(
            message_type="WORKLOAD_STATUS",
            source=sender.identity.node_id,
            target="control_plane",
            sequence=2,
            payload=payload,
            idempotency_key=idempotency_key,
        ).sign(sender.load_private_key())
        assert repeated.verify(sender.identity.public_key)
        original_state = (server.state_dir / "workload-state.json").read_bytes()
        ack_count = len(acknowledgements)
        with pytest.raises(NodeProtocolError):
            await server._handle_message(None, sender.identity.node_id, repeated)
        assert server.result_envelopes[first.idempotency_key] == first.to_dict()
        assert server.results[first.idempotency_key] == first.payload
        assert (server.state_dir / "workload-state.json").read_bytes() == original_state
        assert len(acknowledgements) == ack_count
        assert (
            server.reconcile_work(first.idempotency_key)["work"]["state"] == "VERIFIED"
        )

    asyncio.run(scenario())


@pytest.mark.parametrize("pending_stop", [False, True])
def test_terminal_stop_response_preserves_execution_evidence(
    tmp_path, monkeypatch, pending_stop
):
    async def scenario():
        server, node, first, _request, acknowledgements = await _record_verified_result(
            tmp_path, monkeypatch
        )
        node_id = node.identity.node_id
        work_id = first.idempotency_key
        if pending_stop:
            await server._queue_control(
                node_id, "WORKLOAD_STOP", {"workload_id": work_id}, work_id
            )
        response = NodeProtocolEnvelope(
            message_type="WORKLOAD_STATUS",
            source=node_id,
            target="control_plane",
            sequence=2,
            payload=node.stop_workload(work_id),
            idempotency_key=work_id,
        ).sign(node.load_private_key())
        assert response.payload["stop_result"] == "ALREADY_TERMINAL"
        ack_count = len(acknowledgements)
        if pending_stop:
            await server._handle_message(None, node_id, response)
            assert node_id not in server.pending_controls
            assert len(acknowledgements) == ack_count + 1
        else:
            with pytest.raises(
                NodeProtocolError, match="recorded workload result changed"
            ):
                await server._handle_message(None, node_id, response)
            assert len(acknowledgements) == ack_count
        assert server.result_envelopes[work_id] == first.to_dict()
        assert server.results[work_id] == first.payload
        assert server.reconcile_work(work_id)["work"]["state"] == "VERIFIED"
        restarted = NodeRelayServer(state_dir=server.state_dir)
        assert node_id not in restarted.pending_controls
        assert restarted.result_envelopes[work_id] == first.to_dict()

    asyncio.run(scenario())


def test_terminal_stop_result_arrives_before_original_execution_response(
    tmp_path, monkeypatch
):
    async def scenario():
        server, node, first, request, _acks = await _record_verified_result(
            tmp_path, monkeypatch, first_stop=True
        )
        work_id = first.idempotency_key
        node_id = node.identity.node_id
        assert first.payload["stop_result"] == "ALREADY_TERMINAL"
        assert node_id not in server.pending_controls
        original_state = (server.state_dir / "workload-state.json").read_bytes()
        base_result = node.execute_workload(
            work_id,
            request["capability"],
            request["arguments"],
            delivery_semantics="at_most_once",
            binding=request["binding"],
        )
        assert "stop_result" not in base_result
        for sequence, payload in ((2, base_result), (3, deepcopy(first.payload))):
            repeated = NodeProtocolEnvelope(
                message_type="WORKLOAD_STATUS",
                source=node_id,
                target="control_plane",
                sequence=sequence,
                payload=payload,
                idempotency_key=work_id,
            ).sign(node.load_private_key())
            await server._handle_message(None, node_id, repeated)
            assert server.result_envelopes[work_id] == first.to_dict()
            assert server.results[work_id] == first.payload
            assert (
                server.state_dir / "workload-state.json"
            ).read_bytes() == original_state
            assert server.reconcile_work(work_id)["work"]["state"] == "VERIFIED"
        restarted = NodeRelayServer(
            state_dir=server.state_dir,
            artifact_store=ContentAddressedArtifactStore(
                server.state_dir / "artifacts"
            ),
        )
        assert restarted.result_envelopes[work_id] == first.to_dict()
        assert restarted.reconcile_work(work_id)["work"]["state"] == "VERIFIED"

    asyncio.run(scenario())


def test_socket_reconnect_retransmits_original_terminal_evidence(tmp_path, monkeypatch):
    async def scenario():
        server, node, first, _request, _acks = await _record_verified_result(
            tmp_path, monkeypatch
        )
        monkeypatch.setattr(server, "_send", NodeRelayServer._send.__get__(server))
        node_id = node.identity.node_id
        work_id = first.idempotency_key
        key = node.load_private_key()

        def signed(kind, sequence, payload, *, idempotency_key=""):
            return NodeProtocolEnvelope(
                message_type=kind,
                source=node_id,
                target="control_plane",
                sequence=sequence,
                payload=payload,
                idempotency_key=idempotency_key,
            ).sign(key)

        url = await server.start()
        session_id = ""
        try:
            for sequence in (10, 20):
                async with connect(url) as socket:
                    registration = signed(
                        "REGISTER",
                        sequence,
                        {
                            "node_id": node_id,
                            "identity": node.identity.to_dict(),
                            "supported_versions": [NODE_PROTOCOL_VERSION],
                            "resume_session_id": session_id,
                        },
                    )
                    await socket.send(registration.to_json())
                    welcome = NodeProtocolEnvelope.from_json(await socket.recv())
                    assert welcome.verify(server.public_key)
                    assert welcome.payload["resumed"] is bool(session_id)
                    session_id = welcome.payload["session_id"]
                    repeated = signed(
                        "WORKLOAD_STATUS",
                        sequence + 1,
                        deepcopy(first.payload),
                        idempotency_key=work_id,
                    )
                    await socket.send(repeated.to_json())
                    ack = NodeProtocolEnvelope.from_json(await socket.recv())
                    assert ack.verify(server.public_key)
                    assert ack.payload["acknowledged"] == "WORKLOAD_STATUS"
                    assert ack.reply_to == repeated.message_id
                    assert server.result_envelopes[work_id] == first.to_dict()
                    assert server.reconcile_work(work_id)["work"]["state"] == "VERIFIED"
                    if sequence == 20:
                        changed = deepcopy(first.payload)
                        changed["output"]["echo"] = True
                        await socket.send(
                            signed(
                                "WORKLOAD_STATUS",
                                sequence + 2,
                                changed,
                                idempotency_key=work_id,
                            ).to_json()
                        )
                        error = NodeProtocolEnvelope.from_json(await socket.recv())
                        assert error.message_type == "ERROR"
                        assert error.payload["code"] == "PROTOCOL_ERROR"
                        with pytest.raises(ConnectionClosed):
                            await socket.recv()
                        assert server.result_envelopes[work_id] == first.to_dict()
                        assert (
                            server.reconcile_work(work_id)["work"]["state"]
                            == "VERIFIED"
                        )
        finally:
            await server.stop()

    asyncio.run(scenario())


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


@pytest.mark.parametrize("winerror", [32, 33])
@pytest.mark.parametrize("probe_conflict", [False, True])
def test_original_signed_result_survives_transient_windows_read_conflict(
    tmp_path, monkeypatch, winerror, probe_conflict
):
    async def scenario():
        server, node, first, _, _ = await _record_verified_result(tmp_path, monkeypatch)
        path = server.state_dir / "workload-state.json"
        original_bytes = path.read_bytes()
        read_text = Path.read_text
        reads = []

        def temporarily_locked(target, *args, **kwargs):
            if target == path:
                reads.append(target)
                if len(reads) <= 2:
                    error = PermissionError(13, "private-unpublished-diagnostic")
                    error.winerror = winerror
                    raise error
            return read_text(target, *args, **kwargs)

        monkeypatch.setattr(Path, "read_text", temporarily_locked)
        if probe_conflict:
            exists = Path.exists

            def inaccessible_probe(target):
                if target == path:
                    error = PermissionError(13, "private-unpublished-diagnostic")
                    error.winerror = winerror
                    raise error
                return exists(target)

            monkeypatch.setattr(Path, "exists", inaccessible_probe)
        monkeypatch.setattr(
            node, "execute_workload", lambda *_a, **_k: pytest.fail("replayed effect")
        )
        reopened = NodeRelayServer(
            state_dir=server.state_dir, artifact_store=server.artifact_store
        )
        assert len(reads) == 3
        assert reopened.results[first.idempotency_key] == first.payload
        assert reopened.result_envelopes[first.idempotency_key] == first.to_dict()
        assert (
            reopened.reconcile_work(first.idempotency_key)["work"]["state"]
            == "VERIFIED"
        )
        assert path.read_bytes() == original_bytes

    asyncio.run(scenario())


@pytest.mark.parametrize("winerror,expected_reads", [(5, 1), (32, 6)])
def test_unavailable_original_relay_state_retains_read_cause_and_fails_closed(
    tmp_path, monkeypatch, winerror, expected_reads
):
    server = NodeRelayServer(state_dir=tmp_path)
    server._save_workload_state()
    path = tmp_path / "workload-state.json"
    original_bytes = path.read_bytes()
    read_text = Path.read_text
    reads = []
    error = PermissionError(13, "private-unpublished-diagnostic")
    error.winerror = winerror

    def unavailable(target, *args, **kwargs):
        if target == path:
            reads.append(target)
            raise error
        return read_text(target, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", unavailable)
    with pytest.raises(NodeProtocolError, match="read failed") as caught:
        NodeRelayServer(state_dir=tmp_path)
    assert caught.value.__cause__ is error
    assert len(reads) == expected_reads
    assert f"winerror={winerror}" in str(caught.value)
    assert "private-unpublished-diagnostic" not in str(caught.value)
    assert path.read_bytes() == original_bytes


@pytest.mark.parametrize("content", [b"{", b"[]", b"\xff"])
def test_corrupt_relay_snapshot_is_not_retried_or_replaced(
    tmp_path, monkeypatch, content
):
    server = NodeRelayServer(state_dir=tmp_path)
    server._save_workload_state()
    path = tmp_path / "workload-state.json"
    path.write_bytes(content)
    read_text = Path.read_text
    reads = []

    def counted(target, *args, **kwargs):
        if target == path:
            reads.append(target)
        return read_text(target, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", counted)
    with pytest.raises(NodeProtocolError):
        NodeRelayServer(state_dir=tmp_path)
    assert len(reads) == 1
    assert path.read_bytes() == content


def test_invalid_sequence_encoding_still_blocks_relay_restart(tmp_path):
    NodeRelayServer(state_dir=tmp_path)
    path = tmp_path / "relay-sequence.json"
    path.write_bytes(b"\xff")
    with pytest.raises(UnicodeError):
        NodeRelayServer(state_dir=tmp_path)
    assert path.read_bytes() == b"\xff"


@pytest.mark.skipif(
    sys.platform != "win32", reason="requires an actual Windows file handle"
)
def test_original_signed_result_recovers_from_native_windows_sharing_lock(
    tmp_path, monkeypatch
):
    import ctypes
    from ctypes import wintypes

    import nous_runtime.node_runtime.relay as relay

    server, _, first, _, _ = asyncio.run(_record_verified_result(tmp_path, monkeypatch))
    path = server.state_dir / "workload-state.json"
    original_bytes = path.read_bytes()
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    create = kernel32.CreateFileW
    create.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.LPVOID,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    ]
    create.restype = wintypes.HANDLE
    close = kernel32.CloseHandle
    close.argtypes = [wintypes.HANDLE]
    close.restype = wintypes.BOOL
    handle = create(str(path), 0x80000000, 0, None, 3, 0x80, None)
    assert handle != ctypes.c_void_p(-1).value, ctypes.WinError(ctypes.get_last_error())
    pauses = []
    sleep = relay.time.sleep

    def release_original_read_lock(seconds):
        nonlocal handle
        assert handle is not None
        assert close(handle)
        handle = None
        pauses.append(seconds)
        sleep(seconds)

    monkeypatch.setattr(relay.time, "sleep", release_original_read_lock)
    try:
        reopened = NodeRelayServer(state_dir=server.state_dir)
        assert pauses == [0.01]
        assert reopened.results[first.idempotency_key] == first.payload
        assert reopened.result_envelopes[first.idempotency_key] == first.to_dict()
        assert path.read_bytes() == original_bytes
    finally:
        if handle is not None:
            assert close(handle)
