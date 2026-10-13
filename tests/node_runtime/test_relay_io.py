"""Durable Relay I/O must preserve transport liveness and publication order."""

from __future__ import annotations

import asyncio
import contextvars
import json
import threading
import time

import pytest

from nous_runtime.node_runtime import relay
from nous_runtime.node_runtime.protocol import NodeProtocolEnvelope, NodeProtocolError
from nous_runtime.node_runtime.relay import NodeRelayClient, NodeRelayServer
from nous_runtime.node_runtime.service import NodeRuntimeConfig, NodeRuntimeService
from tests.node_runtime import test_relay_reconciliation as reconciliation_contracts


class RecordingSocket:
    def __init__(self, owner):
        self.owner = owner
        self.messages = []

    async def send(self, raw):
        envelope = NodeProtocolEnvelope.from_json(raw)
        public_key = (
            self.owner.public_key
            if isinstance(self.owner, NodeRelayServer)
            else self.owner.service.identity.public_key
        )
        assert envelope.verify(public_key)
        # A signed message must never be visible before its durable sequence.
        durable = json.loads(self.owner.sequence_path.read_text())["sequence"]
        assert durable >= envelope.sequence
        self.messages.append(envelope)


def _owner(tmp_path, owner_kind):
    service = NodeRuntimeService(NodeRuntimeConfig(tmp_path / "node"))
    server = NodeRelayServer(state_dir=tmp_path / "controller")
    server.register_node(service.identity.node_id, service.identity.public_key)
    if owner_kind == "controller":
        return server, service.identity.node_id
    return NodeRelayClient(service, "ws://127.0.0.1:9", server.public_key), ""


async def _send(owner, websocket, target, payload=None):
    payload = payload or {"acknowledged": "TEST"}
    if target:
        await owner._send(websocket, target, "ACK", payload)
    else:
        await owner._send(websocket, "ACK", payload)


@pytest.mark.parametrize("owner_kind", ["node", "controller"])
def test_durable_sequence_write_cannot_block_transport_callbacks(
    tmp_path, monkeypatch, owner_kind
):
    async def scenario():
        owner, target = _owner(tmp_path, owner_kind)
        websocket = RecordingSocket(owner)
        entered, release, finished = (threading.Event() for _ in range(3))
        observations = []
        atomic_json = relay._atomic_json
        loop = asyncio.get_running_loop()

        def held_write(path, value, **kwargs):
            if path == owner.sequence_path:
                entered.set()
                assert release.wait(3), "controlled sequence writer was not released"
                atomic_json(path, value, **kwargs)
                finished.set()
            else:
                atomic_json(path, value, **kwargs)

        def watchdog():
            if not entered.wait(3):
                release.set()
                return

            def transport_tick():
                observations.append(not finished.is_set())
                release.set()

            loop.call_soon_threadsafe(transport_tick)
            # Bounded cleanup only. The old implementation finishes its writer
            # before the loop can process this callback, and still fails below.
            if not release.wait(1):
                release.set()

        monkeypatch.setattr(relay, "_atomic_json", held_write)
        worker = threading.Thread(target=watchdog)
        worker.start()
        try:
            await _send(owner, websocket, target)
            await asyncio.sleep(0)
            assert observations == [True], observations
            assert len(websocket.messages) == 1
        finally:
            release.set()
            worker.join(timeout=3)
            assert not worker.is_alive()

    asyncio.run(scenario())


@pytest.mark.parametrize("owner_kind", ["node", "controller"])
def test_owner_rejects_concurrent_event_loops_before_allocating_sequence(
    tmp_path, owner_kind
):
    owner, target = _owner(tmp_path, owner_kind)
    entered, release = threading.Event(), threading.Event()
    failures, sockets = [], []

    async def original_loop():
        class HeldSocket(RecordingSocket):
            async def send(self, raw):
                entered.set()
                assert await asyncio.to_thread(release.wait, 3)
                await super().send(raw)

        websocket = HeldSocket(owner)
        sockets.append(websocket)
        await _send(owner, websocket, target)

    def run_original():
        try:
            asyncio.run(original_loop())
        except BaseException as exc:
            failures.append(exc)

    async def competing_loop():
        with pytest.raises(RuntimeError, match="another event loop"):
            await _send(owner, RecordingSocket(owner), target)
        assert owner._sequence == 1

    original = threading.Thread(target=run_original)
    original.start()
    try:
        assert entered.wait(3), "original loop did not reach its held send"
        asyncio.run(competing_loop())
    finally:
        release.set()
        original.join(timeout=3)
        assert not original.is_alive()
    assert failures == []
    assert [message.sequence for message in sockets[0].messages] == [1]
    assert owner._load_sequence() == 1


def test_cancelled_session_writer_cannot_overwrite_successor(tmp_path, monkeypatch):
    async def scenario():
        owner, _target = _owner(tmp_path, "node")
        entered, successor_started = asyncio.Event(), asyncio.Event()
        release = threading.Event()
        events = []
        loop = asyncio.get_running_loop()
        atomic_json = relay._atomic_json

        def held_write(path, value, **kwargs):
            if path == owner.session_path:
                session_id = value["session_id"]
                events.append(("start", session_id))
                if session_id == "original":
                    loop.call_soon_threadsafe(entered.set)
                    assert release.wait(3), "controlled session writer was not released"
                atomic_json(path, value, **kwargs)
                events.append(("finished", session_id))
            else:
                atomic_json(path, value, **kwargs)

        async def save_successor():
            successor_started.set()
            await owner._run_session_io(owner._save_session_id, "successor")

        monkeypatch.setattr(relay, "_atomic_json", held_write)
        original = asyncio.create_task(
            owner._run_session_io(owner._save_session_id, "original")
        )
        successor = None
        try:
            await asyncio.wait_for(entered.wait(), timeout=3)
            original.cancel()
            await asyncio.sleep(0)
            successor = asyncio.create_task(save_successor())
            await asyncio.wait_for(successor_started.wait(), timeout=3)
            original.cancel()
            await asyncio.sleep(0)
            assert not original.done()
            assert not successor.done()
            assert events == [("start", "original")]
            release.set()
            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(original, timeout=3)
            await asyncio.wait_for(successor, timeout=3)
            assert events == [
                ("start", "original"),
                ("finished", "original"),
                ("start", "successor"),
                ("finished", "successor"),
            ]
            assert owner._load_session_id() == "successor"
            assert owner._sequence == 0
        finally:
            release.set()
            await asyncio.gather(
                original, *([successor] if successor else []), return_exceptions=True
            )

    asyncio.run(scenario())


@pytest.mark.parametrize("delivery_semantics", ["idempotent", "at_most_once"])
def test_original_probe_failure_recovery_survives_slow_durable_sequences(
    tmp_path, monkeypatch, caplog, delivery_semantics
):
    atomic_json = relay._atomic_json

    def slow_sequence(path, value, **kwargs):
        if path.name == "relay-sequence.json" and path.parent == tmp_path / "node":
            # A controlled disk stall exceeds the original 0.1-second keepalive
            # timeout; the unchanged recovery assertions still must succeed.
            time.sleep(0.15)
        atomic_json(path, value, **kwargs)

    monkeypatch.setattr(relay, "_atomic_json", slow_sequence)
    reconciliation_contracts.test_recorded_result_reconciles_after_hostname_probe_failure(
        tmp_path, monkeypatch, caplog, delivery_semantics
    )


@pytest.mark.parametrize("owner_kind", ["node", "controller"])
@pytest.mark.parametrize("write_fails", [False, True])
def test_repeated_cancellation_drains_original_writer_before_next_send(
    tmp_path, monkeypatch, owner_kind, write_fails
):
    async def scenario():
        owner, target = _owner(tmp_path, owner_kind)
        websocket = RecordingSocket(owner)
        entered = asyncio.Event()
        second_started = asyncio.Event()
        release = threading.Event()
        events, loop_errors = [], []
        loop = asyncio.get_running_loop()
        loop.set_exception_handler(lambda _loop, context: loop_errors.append(context))
        atomic_json = relay._atomic_json

        def held_write(path, value, **kwargs):
            if path != owner.sequence_path:
                return atomic_json(path, value, **kwargs)
            sequence = value["sequence"]
            events.append(("start", sequence))
            if sequence == 1:
                loop.call_soon_threadsafe(entered.set)
                assert release.wait(3), "controlled writer was not released"
                if write_fails:
                    events.append(("failed", sequence))
                    raise OSError("controlled persistence failure")
            atomic_json(path, value, **kwargs)
            events.append(("finished", sequence))

        async def send_second():
            second_started.set()
            await _send(owner, websocket, target)

        monkeypatch.setattr(relay, "_atomic_json", held_write)
        first = asyncio.create_task(_send(owner, websocket, target))
        second = None
        try:
            await asyncio.wait_for(entered.wait(), timeout=3)
            first.cancel("original cancellation")
            await asyncio.sleep(0)
            second = asyncio.create_task(send_second())
            await asyncio.wait_for(second_started.wait(), timeout=3)
            first.cancel("second cancellation")
            await asyncio.sleep(0)
            assert not first.done()
            assert not second.done()
            assert events == [("start", 1)]
            assert websocket.messages == []
            release.set()
            with pytest.raises(asyncio.CancelledError, match="original cancellation"):
                await asyncio.wait_for(first, timeout=3)
            await asyncio.wait_for(second, timeout=3)
            assert events == [
                ("start", 1),
                ("failed" if write_fails else "finished", 1),
                ("start", 2),
                ("finished", 2),
            ]
            assert [message.sequence for message in websocket.messages] == [2]
            assert json.loads(owner.sequence_path.read_text())["sequence"] == 2
            assert loop_errors == []
        finally:
            release.set()
            await asyncio.gather(
                first, *([second] if second else []), return_exceptions=True
            )

    asyncio.run(scenario())


@pytest.mark.parametrize("owner_kind", ["node", "controller"])
def test_failed_sequence_persistence_publishes_no_frame(
    tmp_path, monkeypatch, owner_kind
):
    async def scenario():
        owner, target = _owner(tmp_path, owner_kind)
        websocket = RecordingSocket(owner)
        atomic_json = relay._atomic_json

        def failed_write(path, value, **kwargs):
            if path == owner.sequence_path:
                raise OSError("controlled persistence failure")
            return atomic_json(path, value, **kwargs)

        monkeypatch.setattr(relay, "_atomic_json", failed_write)
        with pytest.raises(OSError, match="controlled persistence failure"):
            await _send(owner, websocket, target)
        assert websocket.messages == []
        monkeypatch.setattr(relay, "_atomic_json", atomic_json)
        await _send(owner, websocket, target)
        assert [message.sequence for message in websocket.messages] == [2]
        assert owner._load_sequence() == 2

    asyncio.run(scenario())


@pytest.mark.parametrize("owner_kind", ["node", "controller"])
def test_send_guard_preserves_wire_order_payload_and_sequential_loop_reuse(
    tmp_path, owner_kind
):
    owner, target = _owner(tmp_path, owner_kind)
    published = []

    async def scenario():
        entered, second_started, release = (asyncio.Event() for _ in range(3))

        class HeldWireSocket(RecordingSocket):
            async def send(self, raw):
                if not self.messages:
                    entered.set()
                    await release.wait()
                await super().send(raw)

        websocket = HeldWireSocket(owner)
        original_sequence = owner._sequence
        payload = {"acknowledged": "TEST", "details": ["original"]}

        async def send_second():
            second_started.set()
            await _send(owner, websocket, target, payload)

        first = asyncio.create_task(_send(owner, websocket, target))
        second = None
        try:
            await asyncio.wait_for(entered.wait(), timeout=3)
            second = asyncio.create_task(send_second())
            await asyncio.wait_for(second_started.wait(), timeout=3)
            payload["details"].append("changed after enqueue")
            assert owner._sequence == original_sequence + 1
            assert (
                json.loads(owner.sequence_path.read_text())["sequence"]
                == original_sequence + 1
            )
            release.set()
            await asyncio.wait_for(asyncio.gather(first, second), timeout=3)
            assert [message.sequence for message in websocket.messages] == [
                original_sequence + 1,
                original_sequence + 2,
            ]
            assert websocket.messages[1].payload["details"] == ["original"]
            published.extend(message.sequence for message in websocket.messages)
        finally:
            release.set()
            await asyncio.gather(
                first, *([second] if second else []), return_exceptions=True
            )

    asyncio.run(scenario())
    asyncio.run(scenario())
    assert published == [1, 2, 3, 4]
    assert owner._load_sequence() == 4


@pytest.mark.parametrize("owner_kind", ["node", "controller"])
def test_sequence_writer_preserves_caller_context(tmp_path, monkeypatch, owner_kind):
    marker = contextvars.ContextVar("relay_test_context", default="missing")
    observed = []
    owner, target = _owner(tmp_path, owner_kind)
    atomic_json = relay._atomic_json

    def record_context(path, value, **kwargs):
        if path == owner.sequence_path:
            observed.append(marker.get())
        return atomic_json(path, value, **kwargs)

    async def scenario():
        token = marker.set("caller context")
        try:
            await _send(owner, RecordingSocket(owner), target)
        finally:
            marker.reset(token)

    monkeypatch.setattr(relay, "_atomic_json", record_context)
    asyncio.run(scenario())
    assert observed == ["caller context"]


@pytest.mark.parametrize("owner_kind", ["node", "controller"])
def test_loop_shutdown_waits_for_original_writer(tmp_path, monkeypatch, owner_kind):
    owner, target = _owner(tmp_path, owner_kind)
    entered, returned, release, finished = (threading.Event() for _ in range(4))
    observations = []
    atomic_json = relay._atomic_json

    def held_write(path, value, **kwargs):
        if path == owner.sequence_path:
            entered.set()
            assert release.wait(3), "controlled writer was not released"
            atomic_json(path, value, **kwargs)
            finished.set()
        else:
            atomic_json(path, value, **kwargs)

    def watchdog():
        if not entered.wait(3) or not returned.wait(3):
            release.set()
            return
        # A prematurely released guard wakes this watchdog before the writer
        # finishes. Bounded cleanup releases a correctly drained writer too.
        if not release.wait(1):
            release.set()

    async def scenario():
        loop = asyncio.get_running_loop()
        writer_entered = asyncio.Event()

        def signal_entered():
            assert entered.wait(3)
            loop.call_soon_threadsafe(writer_entered.set)

        async def send():
            try:
                await _send(owner, RecordingSocket(owner), target)
            finally:
                observations.append(finished.is_set())
                release.set()

        signal = threading.Thread(target=signal_entered)
        signal.start()
        task = asyncio.create_task(send())
        await asyncio.wait_for(writer_entered.wait(), timeout=3)
        signal.join(timeout=3)
        assert not signal.is_alive()
        returned.set()
        return task

    monkeypatch.setattr(relay, "_atomic_json", held_write)
    watcher = threading.Thread(target=watchdog)
    watcher.start()
    try:
        task = asyncio.run(scenario())
        assert task.cancelled()
        assert observations == [True]
        assert owner._load_sequence() == 1
        assert not owner._send_lock.locked()
    finally:
        release.set()
        watcher.join(timeout=3)
        assert not watcher.is_alive()


@pytest.mark.parametrize("change", ["revoked", "superseded"])
def test_controller_rechecks_trust_and_route_after_durable_write(
    tmp_path, monkeypatch, change
):
    async def scenario():
        server, node_id = _owner(tmp_path, "controller")
        await server.queue_workload(
            node_id, "original-work", "system.echo", {"message": "original"}
        )
        original = json.loads(json.dumps(server.pending[node_id]["original-work"]))
        old = RecordingSocket(server)
        current = RecordingSocket(server)
        server.connections[node_id] = old
        entered = asyncio.Event()
        release = threading.Event()
        atomic_json = relay._atomic_json
        loop = asyncio.get_running_loop()

        def held_write(path, value, **kwargs):
            if path == server.sequence_path and value["sequence"] == 1:
                loop.call_soon_threadsafe(entered.set)
                assert release.wait(3), "controlled writer was not released"
            return atomic_json(path, value, **kwargs)

        monkeypatch.setattr(relay, "_atomic_json", held_write)
        send = asyncio.create_task(server._send_workload(old, node_id, original))
        try:
            await asyncio.wait_for(entered.wait(), timeout=3)
            if change == "revoked":
                server.revoke_node(node_id, admit=lambda _: {"actor_id": "fake-human"})
            else:
                server.connections[node_id] = current
            release.set()
            with pytest.raises(NodeProtocolError, match="revoked|connection changed"):
                await asyncio.wait_for(send, timeout=3)
            assert old.messages == []
            assert server.pending[node_id]["original-work"] == original
            assert server.results == {}
            if change == "superseded":
                await server._send_workload(current, node_id, original)
                assert current.messages[0].sequence == 2
                assert current.messages[0].payload == original
                assert server.pending[node_id]["original-work"] == original
        finally:
            release.set()
            await asyncio.gather(send, return_exceptions=True)

    asyncio.run(scenario())


@pytest.mark.parametrize("phase", ["session-write", "initial-probe", "heartbeat-probe"])
def test_session_persistence_and_probes_cannot_block_transport_callbacks(
    tmp_path, monkeypatch, phase
):
    async def scenario():
        service = NodeRuntimeService(NodeRuntimeConfig(tmp_path / "node"))
        server = NodeRelayServer()
        server.register_node(service.identity.node_id, service.identity.public_key)
        url = await server.start()
        stop = asyncio.Event()
        client = NodeRelayClient(
            service, url, server.public_key, heartbeat_seconds=0.05
        )
        entered, release, finished = (threading.Event() for _ in range(3))
        observations = []
        loop = asyncio.get_running_loop()
        probes = 0

        def hold(operation, *args):
            entered.set()
            assert release.wait(3), "controlled Relay I/O was not released"
            result = operation(*args)
            finished.set()
            return result

        def static_status():
            nonlocal probes
            probes += 1
            return {
                "heartbeat_sequence": probes,
                "resources": {
                    "schema": "nous.node-resource-report/v1",
                    "measurement_source": "controlled-test-probe",
                },
                "devices": [],
            }

        if phase == "session-write":
            save_session = client._save_session_id
            monkeypatch.setattr(
                client,
                "_save_session_id",
                lambda session_id: hold(save_session, session_id),
            )
            monkeypatch.setattr(service, "run_once", static_status)
        else:

            def probe():
                should_hold = probes == (0 if phase == "initial-probe" else 1)
                return hold(static_status) if should_hold else static_status()

            monkeypatch.setattr(service, "run_once", probe)

        def watchdog():
            if not entered.wait(3):
                release.set()
                return

            def transport_tick():
                observations.append(not finished.is_set())
                stop.set()
                release.set()

            loop.call_soon_threadsafe(transport_tick)
            if not release.wait(1):
                release.set()

        watcher = threading.Thread(target=watchdog)
        watcher.start()
        task = asyncio.create_task(client.run_session(stop))
        try:
            await asyncio.wait_for(task, timeout=3)
            assert observations == [True], observations
            assert (
                client._load_session_id() == server.sessions[service.identity.node_id]
            )
        finally:
            stop.set()
            release.set()
            await asyncio.gather(task, return_exceptions=True)
            await server.stop()
            watcher.join(timeout=3)
            assert not watcher.is_alive()

    asyncio.run(scenario())
