"""Placement requires resources observed after the current signed registration."""

from __future__ import annotations

import asyncio
from copy import deepcopy
from datetime import datetime, timedelta, timezone

import pytest
from websockets.asyncio.client import connect
from websockets.exceptions import ConnectionClosed

from nous_runtime.node_runtime import relay, reliability
from nous_runtime.node_runtime.protocol import (
    NODE_PROTOCOL_VERSION,
    NodeProtocolEnvelope,
)
from nous_runtime.node_runtime.relay import NodeRelayClient, NodeRelayServer
from nous_runtime.node_runtime.service import NodeRuntimeConfig, NodeRuntimeService


def _registration(service):
    return {
        "node_id": service.identity.node_id,
        "identity": service.identity.to_dict(),
        "supported_versions": [NODE_PROTOCOL_VERSION],
    }


def _resources():
    return {
        "schema": "nous.node-resource-report/v1",
        "measurement_source": "controlled-test-probe",
        "memory_total_bytes": 1024**3,
        "memory_available_bytes": 1024**3,
    }


def _message(service, kind, sequence, payload):
    return NodeProtocolEnvelope(
        message_type=kind,
        source=service.identity.node_id,
        target="control_plane",
        sequence=sequence,
        payload=payload,
    ).sign(service.load_private_key())


async def _exchange(websocket, envelope):
    await websocket.send(envelope.to_json())
    response = NodeProtocolEnvelope.from_json(await websocket.recv())
    assert response.message_type == "ACK"
    assert response.payload["acknowledged"] == envelope.message_type
    return response


def _observe_disconnect(server, monkeypatch):
    disconnected = asyncio.Event()
    handle_connection = server._handle_connection

    async def observe(websocket):
        try:
            await handle_connection(websocket)
        finally:
            if not server.connections:
                disconnected.set()

    monkeypatch.setattr(server, "_handle_connection", observe)
    return disconnected


class ControllerClock:
    def __init__(self, monkeypatch):
        self.current = datetime.now(timezone.utc)
        clock = self

        class ControlledDatetime(datetime):
            @classmethod
            def now(cls, tz=None):
                return (
                    clock.current.astimezone(tz)
                    if tz
                    else clock.current.replace(tzinfo=None)
                )

        monkeypatch.setattr(reliability, "datetime", ControlledDatetime)
        monkeypatch.setattr(relay, "_utc_now", self.timestamp)

    def timestamp(self):
        return self.current.isoformat().replace("+00:00", "Z")

    def advance(self, seconds):
        self.current += timedelta(seconds=seconds)


def test_registration_without_resources_never_becomes_schedulable_on_cleanup(
    tmp_path, monkeypatch
):
    async def scenario():
        service = NodeRuntimeService(NodeRuntimeConfig(tmp_path / "node"))
        server = NodeRelayServer(heartbeat_seconds=5)
        server.register_node(service.identity.node_id, service.identity.public_key)
        disconnected = _observe_disconnect(server, monkeypatch)
        url = await server.start()
        try:
            async with connect(url) as websocket:
                await _exchange(
                    websocket, _message(service, "REGISTER", 1, _registration(service))
                )
                status = server.controller_status()["nodes"][0]
                assert status["trust_status"] == "TRUSTED"
                assert status["connected"] is True
                assert status["connectivity_state"] == "RECONCILING"
                assert status["connectivity_lease_valid"] is True
                assert status["schedulable"] is False
                assert status["has_resource_report"] is False

            await asyncio.wait_for(disconnected.wait(), timeout=5)
            status = server.controller_status()["nodes"][0]
            assert status["connected"] is False
            assert status["connectivity_state"] == "DEGRADED"
            assert status["connectivity_lease_valid"] is True
            assert status["schedulable"] is False
            assert status["has_resource_report"] is False
            assert server.select_node({})["selected_node"] == ""
        finally:
            await server.stop()

    asyncio.run(scenario())


@pytest.mark.parametrize("message_type", ["HEARTBEAT", "DEVICE_REPORT"])
def test_reconnect_requires_resources_from_current_authenticated_connection(
    tmp_path, message_type
):
    async def scenario():
        service = NodeRuntimeService(NodeRuntimeConfig(tmp_path / "node"))
        server = NodeRelayServer(heartbeat_seconds=5)
        node_id = service.identity.node_id
        server.register_node(node_id, service.identity.public_key)
        url = await server.start()
        try:
            async with connect(url) as old, connect(url) as current:
                welcome = await _exchange(
                    old, _message(service, "REGISTER", 1, _registration(service))
                )
                await _exchange(
                    old, _message(service, "RESOURCE_REPORT", 2, _resources())
                )
                assert server.controller_status()["nodes"][0]["schedulable"] is True

                registration = {
                    **_registration(service),
                    "resume_session_id": welcome.payload["session_id"],
                }
                resumed = await _exchange(
                    current, _message(service, "REGISTER", 3, registration)
                )
                assert resumed.payload["resumed"] is True
                assert resumed.payload["session_id"] == welcome.payload["session_id"]
                status = server.controller_status()["nodes"][0]
                assert status["connectivity_state"] == "RECONCILING"
                assert status["has_resource_report"] is True
                assert status["schedulable"] is False
                payload = (
                    {"node_id": node_id, "status": "ONLINE", "heartbeat_sequence": 1}
                    if message_type == "HEARTBEAT"
                    else {"devices": []}
                )
                await _exchange(current, _message(service, message_type, 4, payload))
                status = server.controller_status()["nodes"][0]
                assert status["schedulable"] is False
                assert status["connectivity_state"] == "RECONCILING"
                assert status["resource_report_current"] is False

                # Old traffic cannot establish readiness or consume the sequence
                # that belongs to the current authenticated connection.
                observation = deepcopy(server.reports[node_id])
                await old.send(
                    _message(service, "RESOURCE_REPORT", 5, _resources()).to_json()
                )
                rejected = NodeProtocolEnvelope.from_json(await old.recv())
                assert rejected.message_type == "ERROR"
                assert "superseded" in rejected.payload["message"]
                with pytest.raises(ConnectionClosed):
                    await old.recv()
                assert server.reports[node_id] == observation

                await _exchange(
                    current, _message(service, "RESOURCE_REPORT", 5, _resources())
                )
                status = server.controller_status()["nodes"][0]
                assert status["connected"] is True
                assert status["connectivity_state"] == "ONLINE"
                assert status["resource_report_current"] is True
                assert status["resource_report_fresh"] is True
                assert status["schedulable"] is True
        finally:
            await server.stop()

    asyncio.run(scenario())


def test_resource_freshness_expires_independently_of_heartbeat_and_transport(
    tmp_path, monkeypatch
):
    clock = ControllerClock(monkeypatch)

    async def scenario():
        service = NodeRuntimeService(NodeRuntimeConfig(tmp_path / "node"))
        server = NodeRelayServer(state_dir=tmp_path / "controller", heartbeat_seconds=5)
        node_id = service.identity.node_id
        server.register_node(node_id, service.identity.public_key)
        disconnected = _observe_disconnect(server, monkeypatch)
        url = await server.start()
        try:
            async with connect(url) as websocket:
                await _exchange(
                    websocket, _message(service, "REGISTER", 1, _registration(service))
                )
                await _exchange(
                    websocket, _message(service, "RESOURCE_REPORT", 2, _resources())
                )
                observed_at = clock.timestamp()
                clock.advance(14)
                heartbeat = {
                    "node_id": node_id,
                    "status": "ONLINE",
                    "heartbeat_sequence": 1,
                }
                await _exchange(websocket, _message(service, "HEARTBEAT", 3, heartbeat))
                assert server.controller_status()["nodes"][0]["schedulable"] is True

                clock.advance(2)
                await _exchange(websocket, _message(service, "HEARTBEAT", 4, heartbeat))
                status = server.controller_status()["nodes"][0]
                assert status["schedulable"] is False
                assert status["connected"] is True
                assert status["trust_status"] == "TRUSTED"
                assert status["connectivity_state"] == "ONLINE"
                assert status["connectivity_lease_valid"] is True
                assert status["resource_report_current"] is True
                assert status["resource_report_fresh"] is False
                assert status["resource_observed_at"] == observed_at
                assert server.select_node({})["selected_node"] == ""

                await _exchange(
                    websocket, _message(service, "DEVICE_REPORT", 5, {"devices": []})
                )
                assert server.controller_status()["nodes"][0]["schedulable"] is False
                await _exchange(
                    websocket, _message(service, "RESOURCE_REPORT", 6, _resources())
                )
                assert server.controller_status()["nodes"][0]["schedulable"] is True

            await asyncio.wait_for(disconnected.wait(), timeout=5)
            status = server.controller_status()["nodes"][0]
            assert status["connectivity_state"] == "DEGRADED"
            assert status["resource_report_fresh"] is True
            assert status["schedulable"] is True
            restored = NodeRelayServer(state_dir=server.state_dir, heartbeat_seconds=5)
            assert restored.controller_status()["nodes"][0]["schedulable"] is True
            clock.advance(16)
            status = restored.controller_status()["nodes"][0]
            assert status["connectivity_state"] == "STALE"
            assert status["resource_report_fresh"] is False
            assert status["schedulable"] is False
        finally:
            await server.stop()

    asyncio.run(scenario())


def test_successful_static_probes_renew_resource_report_before_placement(
    tmp_path, monkeypatch
):
    clock = ControllerClock(monkeypatch)

    async def scenario():
        service = NodeRuntimeService(NodeRuntimeConfig(tmp_path / "node"))
        probes = 0

        def static_status():
            nonlocal probes
            probes += 1
            # Advance past the old lease without waiting for wall-clock time.
            clock.advance(1)
            return {
                "heartbeat_sequence": probes,
                "resources": _resources(),
                "devices": [],
            }

        monkeypatch.setattr(service, "run_once", static_status)
        server = NodeRelayServer(heartbeat_seconds=0.05)
        server.register_node(service.identity.node_id, service.identity.public_key)
        renewed = asyncio.Event()
        reports = []
        stop = asyncio.Event()
        handle_message = server._handle_message

        async def observe(websocket, node_id, envelope):
            await handle_message(websocket, node_id, envelope)
            if envelope.message_type == "RESOURCE_REPORT":
                reports.append(envelope)
                assert server.controller_status()["nodes"][0]["schedulable"] is True
                if len(reports) == 3:
                    stop.set()
                    renewed.set()

        monkeypatch.setattr(server, "_handle_message", observe)
        url = await server.start()
        client = NodeRelayClient(
            service, url, server.public_key, heartbeat_seconds=0.05
        )
        task = asyncio.create_task(client.run_session(stop))
        try:
            await asyncio.wait_for(renewed.wait(), timeout=5)
            await asyncio.wait_for(task, timeout=2)
            assert probes == 3
            assert len(reports) == 3
            assert all(report.payload == reports[0].payload for report in reports)
            assert len({report.message_id for report in reports}) == 3
        finally:
            stop.set()
            try:
                await asyncio.wait_for(task, timeout=2)
            finally:
                await server.stop()

    asyncio.run(scenario())
