"""Stopping a relay during reconnect backoff must prevent another session."""

import asyncio

import pytest
from websockets.exceptions import ConnectionClosedError
from websockets.frames import Close

from nous_runtime.node_runtime.protocol import NodeProtocolError
from nous_runtime.node_runtime.relay import NodeRelayClient
from nous_runtime.node_runtime.service import NodeRuntimeConfig, NodeRuntimeService


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
