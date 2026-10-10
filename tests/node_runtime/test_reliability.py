from __future__ import annotations

import asyncio
import json
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

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
            await _wait_for(lambda: service.identity.node_id not in server.connections)
            disconnected = server.controller_status()["nodes"][0]
            assert disconnected["connectivity_state"] == "DEGRADED"
            assert disconnected["connected"] is False
            assert disconnected["connectivity_lease_valid"] is True
            await server.stop()

    asyncio.run(scenario())


def test_node_reconnects_after_durable_controller_restart(tmp_path: Path) -> None:
    async def scenario() -> None:
        state_dir = tmp_path / "controller"
        service = NodeRuntimeService(NodeRuntimeConfig(state_dir=tmp_path / "node"))
        server = NodeRelayServer(state_dir=state_dir, heartbeat_seconds=0.05)
        server.register_node(service.identity.node_id, service.identity.public_key)
        url = await server.start()
        port = int(url.rsplit(":", 1)[1])
        stop = asyncio.Event()
        client = NodeRelayClient(
            service, url, server.public_key, heartbeat_seconds=0.05
        )
        task = asyncio.create_task(client.run_forever(stop))
        restarted: NodeRelayServer | None = None
        try:
            await _wait_for(
                lambda: (
                    server.controller_status()["nodes"][0]["connectivity_state"]
                    == "ONLINE"
                )
            )
            first_sequence = json.loads(
                (state_dir / "relay-sequence.json").read_text(encoding="utf-8")
            )["sequence"]

            await server.stop()
            restarted = NodeRelayServer(
                host="127.0.0.1",
                port=port,
                state_dir=state_dir,
                heartbeat_seconds=0.05,
            )
            assert await restarted.start() == url
            await _wait_for(
                lambda: (
                    restarted.controller_status()["nodes"][0]["connectivity_state"]
                    == "ONLINE"
                )
            )
            assert (
                json.loads(
                    (state_dir / "relay-sequence.json").read_text(encoding="utf-8")
                )["sequence"]
                > first_sequence
            )
        finally:
            stop.set()
            await asyncio.wait_for(task, timeout=2)
            if restarted is not None:
                await restarted.stop()
            else:
                await server.stop()

    asyncio.run(scenario())


def test_workload_handler_cannot_block_the_authenticated_transport_loop(tmp_path):
    async def scenario():
        service = NodeRuntimeService(NodeRuntimeConfig(state_dir=tmp_path / "node"))
        server = NodeRelayServer(heartbeat_seconds=0.05)
        server.register_node(service.identity.node_id, service.identity.public_key)
        entered, release, finished = (threading.Event() for _ in range(3))
        observations = []
        executions = 0
        loop = asyncio.get_running_loop()

        def handler(arguments):
            nonlocal executions
            executions += 1
            entered.set()
            assert release.wait(3), "controlled handler was not released"
            finished.set()
            return {"echo": arguments["message"]}

        def watchdog():
            if not entered.wait(3):
                release.set()
                return
            scheduled = time.monotonic()

            def transport_tick():
                observations.append(
                    {
                        "before_handler_finished": not finished.is_set(),
                        "elapsed_seconds": time.monotonic() - scheduled,
                    }
                )
                release.set()

            loop.call_soon_threadsafe(transport_tick)
            # Bounded cleanup for the defective implementation; no sleep or
            # enlarged production deadline makes that implementation pass.
            if not release.wait(1):
                release.set()

        service._handlers["system.echo"] = handler
        await server.queue_workload(
            service.identity.node_id,
            "transport-responsive",
            "system.echo",
            {"message": "once"},
        )
        url = await server.start()
        stop = asyncio.Event()
        client = NodeRelayClient(
            service, url, server.public_key, heartbeat_seconds=0.05
        )
        task = asyncio.create_task(client.run_forever(stop))
        worker = threading.Thread(target=watchdog)
        worker.start()
        try:
            await _wait_for(lambda: "transport-responsive" in server.results)
            assert observations and observations[0]["before_handler_finished"], (
                observations
            )
            assert executions == 1
            assert server.results["transport-responsive"]["state"] == "COMPLETED"
            assert server.result_envelopes["transport-responsive"]["signature"]
        finally:
            release.set()
            stop.set()
            await asyncio.wait_for(task, timeout=2)
            await server.stop()
            worker.join(timeout=3)
            assert not worker.is_alive()

    asyncio.run(scenario())


def test_cancelled_transport_preserves_inflight_effect_and_delivers_original_result(
    tmp_path: Path,
) -> None:
    async def scenario():
        service = NodeRuntimeService(NodeRuntimeConfig(state_dir=tmp_path / "node"))
        server = NodeRelayServer(heartbeat_seconds=0.05)
        server.register_node(service.identity.node_id, service.identity.public_key)
        entered, release = threading.Event(), threading.Event()
        executions = 0
        workload_id = "transport-cancelled"
        binding = {
            "intent_id": "intent-transport-cancelled",
            "effect_contract_digest": "a" * 64,
            "target_ref": "node://test/service/echo",
            "target_binding_digest": "b" * 64,
            "workload_id": workload_id,
            "request_digest": "c" * 64,
            "provider_revision": "test-1",
        }

        def handler(arguments):
            nonlocal executions
            executions += 1
            entered.set()
            assert release.wait(3), "controlled handler was not released"
            return {"echo": arguments["message"]}

        service._handlers["system.echo"] = handler
        await server.queue_workload(
            service.identity.node_id,
            workload_id,
            "system.echo",
            {"message": "once"},
            delivery_semantics="at_most_once",
            binding=binding,
        )
        url = await server.start()
        stop = asyncio.Event()
        client = NodeRelayClient(
            service, url, server.public_key, heartbeat_seconds=0.05
        )
        task = asyncio.create_task(client.run_forever(stop))
        resumed = None
        try:
            await _wait_for(entered.is_set)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            assert (
                json.loads(service.workloads_path.read_text())[workload_id]["state"]
                == "EXECUTING"
            )
            uncertain = service.execute_workload(
                workload_id,
                "system.echo",
                {"message": "once"},
                delivery_semantics="at_most_once",
                binding=binding,
            )
            assert uncertain["state"] == "RECOVERY_REQUIRED"
            assert uncertain["error_code"] == "NOUS_NODE_UNCERTAIN_EFFECT"
            assert executions == 1
            release.set()
            await _wait_for(
                lambda: (
                    json.loads(service.workloads_path.read_text())[workload_id]["state"]
                    == "COMPLETED"
                )
            )
            original = json.loads(service.workloads_path.read_text())[workload_id]
            resumed = asyncio.create_task(client.run_forever(stop))
            await _wait_for(lambda: workload_id in server.results)
            assert server.results[workload_id] == original
            assert server.result_envelopes[workload_id]["signature"]
            assert executions == 1
        finally:
            release.set()
            stop.set()
            if not task.done():
                task.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await task
            if resumed is not None:
                await asyncio.wait_for(resumed, timeout=2)
            await server.stop()

    asyncio.run(scenario())


async def _wait_for(predicate, timeout: float = 5.0) -> None:
    deadline = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < deadline:
        if predicate():
            return
        await asyncio.sleep(0.01)
    raise AssertionError("reliability scenario did not converge")
