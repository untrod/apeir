from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path

from nous_runtime.node_runtime.reliability import (
    NodeConnectivityState,
    project_node_connectivity,
)
from nous_runtime.node_runtime.relay import NodeRelayClient, NodeRelayServer
from nous_runtime.node_runtime.service import NodeRuntimeConfig, NodeRuntimeService


def _timestamp(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


def test_connectivity_projection_expires_without_claiming_live_transport() -> None:
    now = datetime(2026, 10, 2, tzinfo=timezone.utc)

    degraded = project_node_connectivity(
        connected=False,
        connection_phase="",
        last_observed_at=_timestamp(now - timedelta(seconds=10)),
        heartbeat_seconds=5,
        now=now,
    )
    stale = project_node_connectivity(
        connected=False,
        connection_phase="",
        last_observed_at=_timestamp(now - timedelta(seconds=20)),
        heartbeat_seconds=5,
        now=now,
    )
    offline = project_node_connectivity(
        connected=False,
        connection_phase="",
        last_observed_at=_timestamp(now - timedelta(seconds=31)),
        heartbeat_seconds=5,
        now=now,
    )

    assert degraded.state is NodeConnectivityState.DEGRADED
    assert degraded.lease_valid is True
    assert degraded.schedulable is True
    assert stale.state is NodeConnectivityState.STALE
    assert stale.lease_valid is False
    assert stale.schedulable is False
    assert offline.state is NodeConnectivityState.OFFLINE
    assert offline.schedulable is False


def test_connected_node_requires_reconciliation_before_online() -> None:
    now = datetime(2026, 10, 2, tzinfo=timezone.utc)
    reconnecting = project_node_connectivity(
        connected=True,
        connection_phase="RECONNECTING",
        last_observed_at="",
        heartbeat_seconds=5,
        now=now,
    )
    reconciling = project_node_connectivity(
        connected=True,
        connection_phase="RECONCILING",
        last_observed_at=_timestamp(now),
        heartbeat_seconds=5,
        now=now,
    )
    online = project_node_connectivity(
        connected=True,
        connection_phase="ONLINE",
        last_observed_at=_timestamp(now),
        heartbeat_seconds=5,
        now=now,
    )

    assert reconnecting.state is NodeConnectivityState.RECONNECTING
    assert reconnecting.schedulable is False
    assert reconciling.state is NodeConnectivityState.RECONCILING
    assert reconciling.schedulable is False
    assert online.state is NodeConnectivityState.ONLINE
    assert online.schedulable is True


def test_completed_work_is_delivered_after_transport_loss_without_reexecution(
    tmp_path: Path,
) -> None:
    class DisconnectOnceClient(NodeRelayClient):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.disconnected = False

        async def _send(self, websocket, message_type, payload, **kwargs):
            if message_type == "WORKLOAD_STATUS" and not self.disconnected:
                self.disconnected = True
                await websocket.close()
                raise OSError("simulated result transport loss")
            await super()._send(websocket, message_type, payload, **kwargs)

    async def scenario() -> None:
        service = NodeRuntimeService(NodeRuntimeConfig(state_dir=tmp_path / "node"))
        executions = 0

        def execute(arguments):
            nonlocal executions
            executions += 1
            return {"echo": arguments["message"]}

        service._handlers["system.echo"] = execute
        server = NodeRelayServer(heartbeat_seconds=0.05)
        server.register_node(service.identity.node_id, service.identity.public_key)
        await server.queue_workload(
            service.identity.node_id,
            "work-disconnect-result",
            "system.echo",
            {"message": "once"},
        )
        url = await server.start()
        stop = asyncio.Event()
        client = DisconnectOnceClient(
            service, url, server.public_key, heartbeat_seconds=0.05
        )
        task = asyncio.create_task(client.run_forever(stop))
        try:
            await _wait_for(lambda: "work-disconnect-result" in server.results)
            assert client.disconnected is True
            assert executions == 1
            await _wait_for(
                lambda: (
                    server.controller_status()["nodes"][0]["connectivity_state"]
                    == "ONLINE"
                )
            )
            live = server.controller_status()["nodes"][0]
            assert live["connectivity_lease_valid"] is True
            assert live["schedulable"] is True
            assert server.results["work-disconnect-result"]["output"] == {
                "echo": "once"
            }
            assert "work-disconnect-result" not in server.pending.get(
                service.identity.node_id, {}
            )
        finally:
            stop.set()
            await asyncio.wait_for(task, timeout=2)
            disconnected = server.controller_status()["nodes"][0]
            assert disconnected["connectivity_state"] == "DEGRADED"
            assert disconnected["connected"] is False
            assert disconnected["connectivity_lease_valid"] is True
            await server.stop()

    asyncio.run(scenario())


async def _wait_for(predicate, timeout: float = 5.0) -> None:
    deadline = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < deadline:
        if predicate():
            return
        await asyncio.sleep(0.01)
    raise AssertionError("reliability scenario did not converge")
