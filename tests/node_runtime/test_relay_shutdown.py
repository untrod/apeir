"""Stopping a relay during reconnect backoff must prevent another session."""

import asyncio

import pytest
from websockets.exceptions import ConnectionClosedError
from websockets.frames import Close

from nous_runtime.node_runtime.protocol import NodeProtocolError
from nous_runtime.node_runtime.relay import NodeRelayClient
from nous_runtime.node_runtime.relay import NodeRelayServer
from nous_runtime.node_runtime.service import NodeRuntimeConfig, NodeRuntimeService
from tests.node_runtime.test_node_protocol import _wait_for


@pytest.mark.parametrize(
    "error",
    [
        OSError,
        TimeoutError,
        NodeProtocolError,
        pytest.param(
            lambda message: ConnectionClosedError(None, Close(1011, message)),
            id="keepalive-close",
        ),
    ],
)
def test_stop_interrupts_reconnect_backoff(tmp_path, monkeypatch, error):
    async def scenario():
        service = NodeRuntimeService(NodeRuntimeConfig(tmp_path / "node"))
        client = NodeRelayClient(service, "ws://127.0.0.1:9", "00" * 32)
        failed = asyncio.Event()
        stop = asyncio.Event()
        calls = []

        async def fail_session(stop_event):
            calls.append(stop_event)
            failed.set()
            raise error("controlled connection failure")

        monkeypatch.setattr(client, "run_session", fail_session)
        task = asyncio.create_task(client.run_forever(stop))
        try:
            await asyncio.wait_for(failed.wait(), 1)
            # run_forever yielded in its first backoff (at least1s), rather
            # than returning while the failure signal was still being set.
            stop.set()
            await asyncio.wait_for(task, 0.5)
            assert calls == [stop]
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    asyncio.run(scenario())


def test_reconnect_still_waits_before_retry_when_not_stopped(tmp_path, monkeypatch):
    async def scenario():
        service = NodeRuntimeService(NodeRuntimeConfig(tmp_path / "node"))
        client = NodeRelayClient(service, "ws://127.0.0.1:9", "00" * 32)
        stop = asyncio.Event()
        calls = []

        async def reconnect(stop_event):
            calls.append(asyncio.get_running_loop().time())
            if len(calls) == 1:
                raise OSError("controlled disconnect")
            stop_event.set()

        monkeypatch.setattr(client, "run_session", reconnect)
        monkeypatch.setattr("nous_runtime.node_runtime.relay.random.random", lambda: 0)
        await asyncio.wait_for(client.run_forever(stop), 3)
        assert len(calls) == 2
        assert calls[1] - calls[0] >= 1

    asyncio.run(scenario())


def test_cancellation_during_backoff_propagates_without_reconnect(
    tmp_path, monkeypatch
):
    async def scenario():
        service = NodeRuntimeService(NodeRuntimeConfig(tmp_path / "node"))
        client = NodeRelayClient(service, "ws://127.0.0.1:9", "00" * 32)
        failed = asyncio.Event()
        stop = asyncio.Event()
        calls = []

        async def reconnect(stop_event):
            calls.append(stop_event)
            failed.set()
            raise OSError("controlled disconnect")

        monkeypatch.setattr(client, "run_session", reconnect)
        task = asyncio.create_task(client.run_forever(stop))
        await asyncio.wait_for(failed.wait(), 1)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert task.cancelled()
        assert not stop.is_set()
        assert calls == [stop]

    asyncio.run(scenario())


@pytest.mark.parametrize("buffered", [False, True], ids=["idle", "full-receive-buffer"])
def test_stop_wakes_idle_receive_and_closes_without_admitting_buffered_work(
    tmp_path, monkeypatch, buffered
):
    async def scenario():
        service = NodeRuntimeService(NodeRuntimeConfig(tmp_path / "node"))
        server = NodeRelayServer(
            state_dir=tmp_path / "controller", heartbeat_seconds=60
        )
        server.register_node(service.identity.node_id, service.identity.public_key)
        url = await server.start()
        stop, entered, release = asyncio.Event(), asyncio.Event(), asyncio.Event()
        client = NodeRelayClient(service, url, server.public_key, heartbeat_seconds=60)
        handle, send = client._handle_message, client._send
        captured, executions = {}, []

        async def remember_socket(websocket, *args, **kwargs):
            captured["socket"] = websocket
            return await send(websocket, *args, **kwargs)

        async def after_initial_reports(websocket, envelope, **kwargs):
            result = await handle(websocket, envelope, **kwargs)
            if (
                envelope.message_type == "ACK"
                and envelope.payload.get("acknowledged") == "DEVICE_REPORT"
            ):
                entered.set()
                if buffered:
                    await release.wait()
            return result

        def forbidden_execution(*args, **kwargs):
            executions.append(args)
            raise AssertionError("Stopping transport admitted queued Work")

        monkeypatch.setattr(client, "_send", remember_socket)
        monkeypatch.setattr(client, "_handle_message", after_initial_reports)
        monkeypatch.setattr(service, "execute_workload", forbidden_execution)
        task = asyncio.create_task(client.run_forever(stop))
        try:
            await asyncio.wait_for(entered.wait(), 5)
            if buffered:
                connection = server.connections[service.identity.node_id]
                for _ in range(32):
                    await server._send(
                        connection,
                        service.identity.node_id,
                        "ACK",
                        {"acknowledged": "BUFFERED"},
                    )
                await server.queue_workload(
                    service.identity.node_id,
                    "unadmitted-original-work",
                    "qualification.no_execution",
                )
                # Observe actual transport backpressure, without sleeping until
                # a guessed race window or changing the WebSocket queue bound.
                await _wait_for(lambda: not captured["socket"].transport.is_reading())
            stop.set()
            release.set()
            # Preserve the original Artifact/control acceptance's exit bound.
            await asyncio.wait_for(task, 2)
            assert captured["socket"].close_code == 1000
            assert not [
                pending
                for pending in asyncio.all_tasks()
                if pending is not asyncio.current_task()
                and pending.get_name().startswith("apeir-relay-")
                and not pending.done()
            ]
            assert executions == []
            assert service._workloads == {}
            if buffered:
                assert (
                    "unadmitted-original-work"
                    in server.pending[service.identity.node_id]
                )
                assert "unadmitted-original-work" not in server.results
        finally:
            stop.set()
            release.set()
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            await server.stop()

    asyncio.run(scenario())
