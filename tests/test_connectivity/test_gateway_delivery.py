"""Current transport readiness is required before legacy task assignment."""

import pytest

from nous_runtime.connectivity.control_plane.gateway import ControlPlaneGateway
from nous_runtime.connectivity.protocol.identity import NodeIdentity
from nous_runtime.connectivity.protocol.task import TaskState, TaskSubmission


def registered_gateway():
    gateway = ControlPlaneGateway()
    identity = NodeIdentity.create(
        node_name="delivery-probe",
        node_role="personal_node",
        platform_os="test",
        platform_os_version="test",
        platform_arch="test",
        platform_hostname="test",
        public_key="fake-local-delivery-key",
        capabilities=["system.echo"],
    )
    assert gateway.node_registry.register(identity, "fake-local-credential")
    session = gateway.session_registry.create_session(identity.node_id)
    submitted, _, task = gateway.task_coordinator.submit(
        TaskSubmission.create(
            capability_id="system.echo",
            params={"message": "original"},
            target_node=identity.node_id,
        )
    )
    assert submitted
    return gateway, identity, session, task


def test_missing_send_route_does_not_mark_delivered(desktop_workspace):
    gateway, identity, session, task = registered_gateway()
    gateway._loop = ScheduledLoop()
    gateway._running = True
    assert not gateway._try_deliver(task)
    persisted = gateway.task_coordinator.get(task["task_id"])
    assert persisted["state"] == TaskState.QUEUED.value
    assert persisted["assigned_node"] == ""
    assert persisted["sequence_number"] == 0
    assert gateway.session_registry.get(session.session_id).sequence_number == 0


class ScheduledLoop:
    def __init__(self):
        self.callbacks = []
        self.running = True

    def is_running(self):
        return self.running

    def call_soon_threadsafe(self, callback, *arguments):
        if not self.running:
            raise RuntimeError("loop closed")
        self.callbacks.append((callback, arguments))

    def flush(self):
        callbacks, self.callbacks = self.callbacks, []
        return [callback(*arguments) for callback, arguments in callbacks]


class OpenWriter:
    closing = False

    def is_closing(self):
        return self.closing


def ready_route(gateway, identity, session):
    import asyncio
    from nous_runtime.connectivity.control_plane.gateway import _DeliveryRoute

    gateway._running = True
    if not isinstance(gateway._loop, ScheduledLoop):
        gateway._loop = ScheduledLoop()
    route = _DeliveryRoute(session.session_id, asyncio.Queue(), OpenWriter())
    gateway._delivery_routes[identity.node_id] = route
    return route


def test_duplicate_schedules_assign_and_enqueue_original_only_once(desktop_workspace):
    gateway, identity, session, task = registered_gateway()
    route = ready_route(gateway, identity, session)
    for _ in range(20):
        assert gateway._try_deliver(task)
    assert (
        gateway.task_coordinator.get(task["task_id"])["state"] == TaskState.QUEUED.value
    )
    assert route.queue.qsize() == 0
    assert gateway._loop.flush() == [True] + [False] * 19
    assert route.queue.qsize() == 1
    assignment = route.queue.get_nowait()
    assert assignment["message_type"] == "TASK_ASSIGNMENT"
    assert assignment["target_id"] == identity.node_id
    assert assignment["payload"]["task_id"] == task["task_id"]
    assert assignment["payload"]["params"] == task["params"]
    assert gateway.session_registry.get(session.session_id).sequence_number == 1
    assert (
        gateway.task_coordinator.get(task["task_id"])["state"]
        == TaskState.DELIVERED.value
    )


@pytest.mark.parametrize(
    "fault",
    [
        "replacement-session",
        "replacement-route",
        "revoked",
        "closed-writer",
        "cancelled",
        "capability-mismatch",
        "deadline",
    ],
)
def test_callback_revalidates_before_assignment(desktop_workspace, fault):
    gateway, identity, session, task = registered_gateway()
    route = ready_route(gateway, identity, session)
    assert gateway._try_deliver(task)
    expected_state = TaskState.QUEUED.value
    if fault == "replacement-session":
        gateway.session_registry.create_session(identity.node_id)
    elif fault == "replacement-route":
        ready_route(gateway, identity, session)
    elif fault == "revoked":
        assert gateway.node_registry.revoke(identity.node_id)
    elif fault == "closed-writer":
        route.writer.closing = True
    elif fault == "cancelled":
        assert gateway.task_coordinator.cancel(task["task_id"])
        expected_state = TaskState.CANCELLED.value
    elif fault == "capability-mismatch":
        from nous_runtime.compat.db import connect

        with connect() as database:
            database.execute(
                "UPDATE connectivity_nodes SET capabilities = '[]' WHERE node_id = ?",
                (identity.node_id,),
            )
    elif fault == "deadline":
        from nous_runtime.compat.db import connect

        with connect() as database:
            database.execute(
                "UPDATE connectivity_tasks SET deadline = '2000-01-01T00:00:00Z' WHERE task_id = ?",
                (task["task_id"],),
            )
        expected_state = TaskState.EXPIRED.value
    assert gateway._loop.flush() == [False]
    assert route.queue.qsize() == 0
    assert gateway.task_coordinator.get(task["task_id"])["state"] == expected_state
    assert gateway.session_registry.get(session.session_id).sequence_number == 0


def test_closed_loop_leaves_task_queued(desktop_workspace):
    gateway, identity, session, task = registered_gateway()
    route = ready_route(gateway, identity, session)
    gateway._loop.running = False
    assert not gateway._try_deliver(task)
    assert (
        gateway.task_coordinator.get(task["task_id"])["state"] == TaskState.QUEUED.value
    )
    assert route.queue.empty()


def test_old_connection_cleanup_preserves_new_route_and_never_republishes(
    desktop_workspace, monkeypatch
):
    import asyncio
    from nous_runtime.connectivity.protocol.envelope import ProtocolEnvelope

    async def scenario():
        gateway, identity, _, original = registered_gateway()
        gateway._loop = asyncio.get_running_loop()
        gateway._running = True

        class Writer(OpenWriter):
            def __init__(self):
                self.messages = asyncio.Queue()
                self.closing = False

            def get_extra_info(self, key):
                return ("127.0.0.1", 12345)

            def close(self):
                self.closing = True

            async def wait_closed(self):
                pass

        async def read(reader):
            return await reader.get()

        async def send(writer, message):
            await writer.messages.put(message)

        monkeypatch.setattr(gateway, "_read_message", read)
        monkeypatch.setattr(gateway, "_send_message", send)
        readers = [asyncio.Queue(), asyncio.Queue()]
        writers = [Writer(), Writer()]
        connections = []
        try:
            for index in range(2):
                await readers[index].put(
                    ProtocolEnvelope(
                        message_type="HELLO",
                        source_id=identity.node_id,
                        target_id="control_plane",
                    ).to_dict()
                )
                connections.append(
                    asyncio.create_task(
                        gateway._handle_connection(readers[index], writers[index])
                    )
                )
                welcome = await asyncio.wait_for(writers[index].messages.get(), 3)
                assert welcome["message_type"] == "WELCOME"
                current = gateway._delivery_routes[identity.node_id]
                assert current.session_id == welcome["payload"]["session_id"]
                if index == 0:
                    assignment = await asyncio.wait_for(
                        writers[index].messages.get(), 3
                    )
                    assert assignment["payload"]["task_id"] == original["task_id"]
                    assert (
                        gateway.task_coordinator.get(original["task_id"])["state"]
                        == TaskState.DELIVERED.value
                    )
                else:
                    successor = current
                    assert writers[index].messages.empty()
            await readers[0].put(None)
            await asyncio.wait_for(connections[0], 3)
            assert gateway._delivery_routes[identity.node_id] is successor
            assert gateway._node_writers[identity.node_id] is successor.queue
            assert not gateway._try_deliver(original)
            assert writers[1].messages.empty()
            new_task = gateway.submit_task(
                "system.echo", {"message": "new"}, target_node=identity.node_id
            )
            assignment = await asyncio.wait_for(writers[1].messages.get(), 3)
            assert assignment["payload"]["task_id"] == new_task["task_id"]
            assert writers[1].messages.empty()
        finally:
            for reader in readers:
                await reader.put(None)
            await asyncio.gather(*connections)
            gateway._running = False
        assert gateway._delivery_routes == {}
        assert gateway._connection_writers == set()

    asyncio.run(scenario())


@pytest.mark.parametrize("fault", ["unknown", "revoked"])
def test_rejected_hello_cannot_publish_route(desktop_workspace, monkeypatch, fault):
    import asyncio
    from nous_runtime.connectivity.protocol.envelope import ProtocolEnvelope

    async def scenario():
        gateway, identity, _, task = registered_gateway()
        gateway._loop = asyncio.get_running_loop()
        gateway._running = True
        if fault == "revoked":
            assert gateway.node_registry.revoke(identity.node_id)
        source = "unknown-node" if fault == "unknown" else identity.node_id
        messages = asyncio.Queue()
        incoming = asyncio.Queue()
        writer = OpenWriter()
        writer.get_extra_info = lambda key: ("127.0.0.1", 12345)
        writer.close = lambda: setattr(writer, "closing", True)

        async def wait_closed():
            pass

        async def read(reader):
            return await reader.get()

        async def send(writer, message):
            await messages.put(message)

        writer.wait_closed = wait_closed
        monkeypatch.setattr(gateway, "_read_message", read)
        monkeypatch.setattr(gateway, "_send_message", send)
        await incoming.put(
            ProtocolEnvelope(
                message_type="HELLO", source_id=source, target_id="control_plane"
            ).to_dict()
        )
        connection = asyncio.create_task(gateway._handle_connection(incoming, writer))
        try:
            response = await asyncio.wait_for(messages.get(), 3)
            assert response["message_type"] == "PROTOCOL_ERROR"
            assert response["payload"]["error_code"] == (
                "NODE_UNKNOWN" if fault == "unknown" else "NODE_REVOKED"
            )
            assert gateway._delivery_routes == {}
            assert not gateway._try_deliver(task)
            assert (
                gateway.task_coordinator.get(task["task_id"])["state"]
                == TaskState.QUEUED.value
            )
        finally:
            await incoming.put(None)
            await asyncio.wait_for(connection, 3)
            gateway._running = False

    asyncio.run(scenario())


@pytest.mark.integration
def test_delayed_hello_delivers_original_queued_task_once(
    desktop_workspace, control_plane, monkeypatch
):
    import asyncio
    import threading
    import time
    from nous_runtime.connectivity.node.daemon import NodeDaemon
    from tests.test_connectivity.test_vertical_slice import _wait_for_welcome

    identity = NodeIdentity.create(
        node_name="late-hello-probe",
        node_role="personal_node",
        platform_os="test",
        platform_os_version="test",
        platform_arch="test",
        platform_hostname="test",
        public_key="fake-local-late-hello-key",
        capabilities=["system.echo"],
    )
    node = NodeDaemon(
        control_plane_host=control_plane.host, control_plane_port=control_plane.port
    )
    assert node.pair(control_plane.pairing.create_code(), identity)
    task = control_plane.submit_task(
        "system.echo", {"message": "original"}, target_node=identity.node_id
    )
    assert task["state"] == TaskState.QUEUED.value
    held, release = threading.Event(), threading.Event()
    dispatch = control_plane._dispatch

    async def delayed_hello(message, address):
        if message.get("message_type") == "HELLO":
            held.set()
            while not release.is_set():
                await asyncio.sleep(0.01)
        return await dispatch(message, address)

    monkeypatch.setattr(control_plane, "_dispatch", delayed_hello)
    calls = []

    async def echo(parameters):
        calls.append(parameters)
        return {"echo": parameters["message"]}

    node.register_capability("system.echo", echo)
    try:
        node.start()
        assert held.wait(10)
        # Force HELLO beyond the removed 0.5-second registration timer. This
        # wait injects the fault; readiness below uses actual protocol facts.
        assert not release.wait(0.65)
        assert control_plane._node_writers.get(identity.node_id) is None
        assert (
            control_plane.task_coordinator.get(task["task_id"])["state"]
            == TaskState.QUEUED.value
        )
        assert calls == []
        release.set()
        _wait_for_welcome(node, control_plane)
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            completed = control_plane.task_coordinator.get(task["task_id"])
            if completed["state"] == TaskState.COMPLETED.value:
                break
            time.sleep(0.01)
        assert completed["state"] == TaskState.COMPLETED.value
        assert completed["params"] == task["params"]
        assert calls == [task["params"]]
        prior_session, prior_queue = (
            node.session_id,
            control_plane._node_writers[identity.node_id],
        )
        node.stop()
        node.start()
        _wait_for_welcome(node, control_plane, prior_session, prior_queue)
        assert calls == [task["params"]]
        assert (
            control_plane.task_coordinator.get(task["task_id"])["state"]
            == TaskState.COMPLETED.value
        )
    finally:
        release.set()
        node.stop()
