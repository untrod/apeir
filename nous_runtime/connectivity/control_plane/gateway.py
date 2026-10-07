# -*- coding: utf-8 -*-
"""
ControlPlaneGateway — minimal HTTP + message-based server for connectivity.

Uses asyncio for the event loop. Supports:
  - HTTP API for CLI (task submission, node management, inspector)
  - TCP message protocol for Node connections (transport abstraction)
  - Heartbeat processing
  - Task assignment delivery
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import struct
import threading
from dataclasses import dataclass

from .node_registry import NodeRegistry
from .session_registry import SessionRegistry
from .pairing_service import PairingService
from .task_coordinator import TaskCoordinator
from ..protocol.envelope import ProtocolEnvelope
from ..protocol.pairing import PairingRequest
from ..protocol.task import (
    TaskState,
    TaskSubmission,
    TaskAcknowledgement,
    TaskEvent,
    TaskResult,
)
from ..protocol.error import ErrorCode

_log = logging.getLogger("nous.control_plane.gateway")

# Transport protocol: 4-byte big-endian length prefix + JSON message
HEADER_FMT = "!I"
MAX_MESSAGE_BYTES = 1_048_576  # 1 MB


@dataclass(frozen=True)
class _DeliveryRoute:
    session_id: str
    queue: asyncio.Queue
    writer: asyncio.StreamWriter


class ControlPlaneGateway:
    """
    Minimal Control Plane Gateway.

    Handles:
      - HTTP API (basic, for CLI interactions)
      - TCP message protocol for Node connections
    """

    def __init__(
        self, host: str = "127.0.0.1", port: int = 9770, signing_key: str = ""
    ):
        self.host = host
        self.port = port
        self.signing_key = signing_key or os.environ.get(
            "NOUS_CONTROL_PLANE_SIGNING_KEY", ""
        )
        self.node_registry = NodeRegistry()
        self.session_registry = SessionRegistry()
        self.pairing = PairingService()
        self.task_coordinator = TaskCoordinator()
        self._server: asyncio.AbstractServer | None = None
        self._running = False
        self._start_error: Exception | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._delivery_routes: dict[str, _DeliveryRoute] = {}
        self._background_tasks: set[asyncio.Task] = set()
        self._connection_writers: set[asyncio.StreamWriter] = set()
        self._seen_message_ids: set[str] = set()
        self._seen_nonces: set[str] = set()
        self._last_sequence_by_source: dict[str, int] = {}

    @property
    def _node_writers(self) -> dict[str, asyncio.Queue]:
        """Compatibility projection of current transport routes, not authority."""
        return {
            node: route.queue for node, route in self._delivery_routes.copy().items()
        }

    # Lifecycle

    def start(self) -> None:
        """Start the gateway in a background thread."""
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()
        _log.info("Control Plane Gateway started on %s:%d", self.host, self.port)

    def stop(self) -> None:
        """Stop the gateway."""
        self._running = False
        if self._loop and self._loop.is_running():
            try:
                future = asyncio.run_coroutine_threadsafe(
                    self._shutdown_async(), self._loop
                )
                future.result(timeout=3.0)
            except Exception:
                pass
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=3.0)
        if (
            self._thread
            and self._thread.is_alive()
            and self._loop
            and self._loop.is_running()
        ):
            self._loop.call_soon_threadsafe(self._loop.stop)
            self._thread.join(timeout=1.0)
        _log.info("Control Plane Gateway stopped")

    def _run_loop(self) -> None:
        """Run the asyncio event loop."""
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        try:
            self._loop.run_until_complete(self._serve())
        except (RuntimeError, asyncio.CancelledError):
            pass  # Expected during shutdown
        except OSError as exc:
            self._start_error = exc
            self._running = False
            _log.error(
                "Control Plane Gateway failed to start on %s:%d: %s",
                self.host,
                self.port,
                exc,
            )
        finally:
            if self._loop:
                pending = [
                    task for task in asyncio.all_tasks(self._loop) if not task.done()
                ]
                for task in pending:
                    task.cancel()
                if pending:
                    self._loop.run_until_complete(
                        asyncio.gather(*pending, return_exceptions=True)
                    )
                self._loop.close()

    async def _shutdown_async(self) -> None:
        """Close server, active writers, and background tasks on the event loop."""
        if self._server:
            self._server.close()
            try:
                await self._server.wait_closed()
            except (OSError, RuntimeError, asyncio.CancelledError):
                pass
        for writer in list(self._connection_writers):
            writer.close()
            try:
                await writer.wait_closed()
            except (ConnectionError, OSError, RuntimeError, asyncio.CancelledError):
                pass
        self._connection_writers.clear()
        for task in list(self._background_tasks):
            task.cancel()
        if self._background_tasks:
            await asyncio.gather(*self._background_tasks, return_exceptions=True)
            self._background_tasks.clear()

    async def _serve(self) -> None:
        """Start the TCP server."""
        self._server = await asyncio.start_server(
            self._handle_connection, self.host, self.port
        )
        heartbeat_task = asyncio.create_task(self._heartbeat_checker())
        ack_task = asyncio.create_task(self._ack_timeout_checker())
        self._background_tasks.update({heartbeat_task, ack_task})
        try:
            await self._server.serve_forever()
        except asyncio.CancelledError:
            pass  # Expected during shutdown

    # Connection Handling

    async def _handle_connection(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        """Handle an incoming TCP connection from a Node."""
        addr = writer.get_extra_info("peername")
        self._connection_writers.add(writer)
        _log.info("Connection from %s", addr)
        node_id = None  # Set only after accepted HELLO
        route = None

        # Create an outgoing queue for pushing messages to this connection
        send_queue: asyncio.Queue[dict] = asyncio.Queue()

        async def _reader_loop():
            nonlocal node_id, route
            while self._running:
                msg = await self._read_message(reader)
                if msg is None:
                    break
                response = await self._dispatch(msg, addr)
                if response:
                    await send_queue.put(response)
                if response and response.get("message_type") == "WELCOME":
                    source = msg.get("source_id", "")
                    session = self.session_registry.get_by_node(source)
                    session_id = response.get("payload", {}).get("session_id", "")
                    if (
                        (node_id is None or node_id == source)
                        and session is not None
                        and session.status == "active"
                        and session.session_id == session_id
                        and not writer.is_closing()
                    ):
                        node_id = source
                        route = _DeliveryRoute(session_id, send_queue, writer)
                        self._delivery_routes[node_id] = route
                        # Only never-delivered tasks enter a newly ready route.
                        # WELCOME is already first in this connection's FIFO.
                        self.task_coordinator.check_deadlines()
                        for task in self.task_coordinator.list_all(
                            TaskState.QUEUED.value
                        ):
                            self._try_deliver(task)

        async def _writer_loop():
            while self._running:
                try:
                    msg = await asyncio.wait_for(send_queue.get(), timeout=1.0)
                    await self._send_message(writer, msg)
                except asyncio.TimeoutError:
                    continue

        reader_task = asyncio.create_task(_reader_loop())
        writer_task = asyncio.create_task(_writer_loop())
        try:
            await asyncio.wait(
                {reader_task, writer_task}, return_when=asyncio.FIRST_COMPLETED
            )
        except Exception as e:
            _log.warning("Connection error from %s: %s", addr, e)
        finally:
            for task in (reader_task, writer_task):
                task.cancel()
            await asyncio.gather(reader_task, writer_task, return_exceptions=True)
            if node_id and self._delivery_routes.get(node_id) is route:
                self._delivery_routes.pop(node_id, None)
            self._connection_writers.discard(writer)
            writer.close()
            try:
                await writer.wait_closed()
            except (ConnectionError, OSError, RuntimeError, asyncio.CancelledError):
                pass

    async def _read_message(self, reader: asyncio.StreamReader) -> dict | None:
        """Read a length-prefixed JSON message."""
        try:
            header = await reader.readexactly(4)
            length = struct.unpack(HEADER_FMT, header)[0]
            if length > MAX_MESSAGE_BYTES:
                _log.warning("Oversized message: %d bytes", length)
                return None
            data = await reader.readexactly(length)
            return json.loads(data.decode("utf-8"))
        except (asyncio.IncompleteReadError, ConnectionError):
            return None

    async def _send_message(self, writer: asyncio.StreamWriter, msg: dict) -> None:
        """Send a length-prefixed JSON message."""
        data = json.dumps(msg, ensure_ascii=False).encode("utf-8")
        writer.write(struct.pack(HEADER_FMT, len(data)) + data)
        await writer.drain()

    # Message Dispatch

    async def _dispatch(self, msg: dict, addr: tuple) -> dict | None:
        """Dispatch an incoming message to the appropriate handler."""
        try:
            envelope = ProtocolEnvelope.from_dict(msg)
        except Exception:
            return ProtocolEnvelope.error(
                ProtocolEnvelope(
                    message_type="UNKNOWN",
                    source_id="unknown",
                    target_id="control_plane",
                ),
                ErrorCode.INVALID_MESSAGE,
                "Failed to parse envelope",
            ).to_dict()

        valid, err = envelope.is_valid()
        if not valid:
            return ProtocolEnvelope.error(
                envelope, ErrorCode.INVALID_MESSAGE, err
            ).to_dict()

        if envelope.is_expired():
            return ProtocolEnvelope.error(
                envelope, ErrorCode.TASK_EXPIRED, "Message expired"
            ).to_dict()

        # Signature verification (if signing key is configured)
        if self.signing_key:
            # HELLO from unknown nodes is exempt (node hasn't been paired yet)
            is_hello = envelope.message_type == "HELLO"
            node_exists = bool(self.node_registry.get(envelope.source_id))
            skip_verify = is_hello and not node_exists

            if not skip_verify:
                if not envelope.signature:
                    _log.warning(
                        "Rejected unsigned message type=%s from=%s",
                        envelope.message_type,
                        envelope.source_id,
                    )
                    return ProtocolEnvelope.error(
                        envelope,
                        ErrorCode.INVALID_MESSAGE,
                        "Message signature required",
                    ).to_dict()
                if not envelope.verify(self.signing_key):
                    _log.warning(
                        "Rejected invalid signature type=%s from=%s",
                        envelope.message_type,
                        envelope.source_id,
                    )
                    return ProtocolEnvelope.error(
                        envelope,
                        ErrorCode.INVALID_MESSAGE,
                        "Message signature verification failed",
                    ).to_dict()

        replay_error = self._check_replay_and_sequence(envelope)
        if replay_error:
            return ProtocolEnvelope.error(
                envelope, replay_error[0], replay_error[1]
            ).to_dict()

        handlers = {
            "HELLO": self._handle_hello,
            "HEARTBEAT": self._handle_heartbeat,
            "PAIRING_REQUEST": self._handle_pairing_request,
            "TASK_ACKNOWLEDGEMENT": self._handle_task_ack,
            "TASK_EVENT": self._handle_task_event,
            "TASK_RESULT": self._handle_task_result,
        }

        handler = handlers.get(envelope.message_type)
        if handler:
            result = await handler(envelope, addr)
            return result.to_dict() if result else None

        return ProtocolEnvelope.error(
            envelope,
            ErrorCode.INVALID_MESSAGE,
            f"Unknown message type: {envelope.message_type}",
        ).to_dict()

    # Handlers

    def _check_replay_and_sequence(
        self, envelope: ProtocolEnvelope
    ) -> tuple[str, str] | None:
        """Reject duplicate message ids, duplicate nonces, and sequence rollback."""
        if envelope.message_id in self._seen_message_ids:
            return ErrorCode.TASK_DUPLICATE, "Duplicate message_id"
        if envelope.nonce:
            nonce_key = f"{envelope.source_id}:{envelope.nonce}"
            if nonce_key in self._seen_nonces:
                return ErrorCode.TASK_DUPLICATE, "Duplicate nonce"

        if envelope.sequence_number > 0 and envelope.source_id:
            last = self._last_sequence_by_source.get(envelope.source_id, 0)
            if envelope.sequence_number <= last:
                return ErrorCode.SEQUENCE_GAP, "Sequence number did not advance"
            self._last_sequence_by_source[envelope.source_id] = envelope.sequence_number

        self._seen_message_ids.add(envelope.message_id)
        if envelope.nonce:
            self._seen_nonces.add(f"{envelope.source_id}:{envelope.nonce}")
        return None

    async def _handle_hello(
        self, env: ProtocolEnvelope, addr: tuple
    ) -> ProtocolEnvelope:
        """Handle HELLO from a Node."""
        node_id = env.source_id
        node = self.node_registry.get(node_id)

        if not node:
            return ProtocolEnvelope.error(
                env, ErrorCode.NODE_UNKNOWN, f"Node {node_id} not registered"
            )

        if node.get("credential_status") == "revoked":
            return ProtocolEnvelope.error(
                env, ErrorCode.NODE_REVOKED, f"Node {node_id} is revoked"
            )

        session = self.session_registry.create_session(
            node_id=node_id,
            protocol_version=env.protocol_version,
            remote_address=f"{addr[0]}:{addr[1]}",
        )
        self.node_registry.set_online(node_id, True)

        return ProtocolEnvelope.response(
            env,
            "WELCOME",
            {
                "session_id": session.session_id,
                "protocol_version": session.protocol_version,
                "server_time": session.created_at,
                "heartbeat_interval_ms": 15000,
                "liveness_timeout_ms": 45000,
            },
        )

    async def _handle_heartbeat(
        self, env: ProtocolEnvelope, addr: tuple
    ) -> ProtocolEnvelope:
        """Handle HEARTBEAT from a Node."""
        payload = env.payload
        session_id = payload.get("session_id", "")
        session = self.session_registry.heartbeat(session_id)
        if not session:
            return ProtocolEnvelope.error(
                env, ErrorCode.SESSION_EXPIRED, "Session not found or expired"
            )

        self.node_registry.set_online(session.node_id, True)
        return ProtocolEnvelope.response(
            env,
            "HEARTBEAT_ACK",
            {
                "sequence_number": payload.get("sequence_number", 0),
                "server_time": session.last_heartbeat,
            },
        )

    async def _handle_pairing_request(
        self, env: ProtocolEnvelope, addr: tuple
    ) -> ProtocolEnvelope:
        """Handle PAIRING_REQUEST from a Node."""
        payload = env.payload
        request = PairingRequest.from_dict(payload)

        approval, reason = self.pairing.approve_pairing(request, request.pairing_code)
        if not approval:
            return ProtocolEnvelope.error(env, ErrorCode.PAIRING_FAILED, reason)

        # Parse and register node identity
        identity = request.node_identity
        from ..protocol.identity import NodeIdentity as NI

        node_identity = NI.from_dict(identity)

        self.node_registry.register(
            node_identity,
            credential_id=approval.credential_id,
            credential_expires_at=approval.expires_at,
        )

        return ProtocolEnvelope.response(env, "PAIRING_APPROVAL", approval.to_dict())

    async def _handle_task_ack(
        self, env: ProtocolEnvelope, addr: tuple
    ) -> ProtocolEnvelope | None:
        """Handle TASK_ACKNOWLEDGEMENT from a Node."""
        ack = TaskAcknowledgement.from_dict(env.payload)
        self.task_coordinator.acknowledge(ack)
        if ack.accepted:
            self.task_coordinator.transition(ack.task_id, TaskState.RUNNING)
            self.task_coordinator.add_event(ack.task_id, TaskEvent.started(ack.task_id))
        return None  # No response needed for ACK

    async def _handle_task_event(
        self, env: ProtocolEnvelope, addr: tuple
    ) -> ProtocolEnvelope | None:
        """Handle TASK_EVENT from a Node."""
        event = TaskEvent.from_dict(env.payload)
        self.task_coordinator.add_event(event.task_id, event)
        return None

    async def _handle_task_result(
        self, env: ProtocolEnvelope, addr: tuple
    ) -> ProtocolEnvelope | None:
        """Handle TASK_RESULT from a Node."""
        result = TaskResult.from_dict(env.payload)
        self.task_coordinator.complete(result.task_id, result)
        return None

    # Background Tasks

    async def _heartbeat_checker(self) -> None:
        """Periodically check for stale sessions."""
        try:
            while self._running:
                await asyncio.sleep(10)
                expired = self.session_registry.expire_stale()
                for node_id in expired:
                    self.node_registry.set_online(node_id, False)
                    _log.info("Node %s marked offline (heartbeat timeout)", node_id)
        except asyncio.CancelledError:
            pass

    async def _ack_timeout_checker(self) -> None:
        """Periodically check for ACK timeouts."""
        try:
            while self._running:
                await asyncio.sleep(5)
                self.task_coordinator.check_ack_timeouts()
                self.task_coordinator.check_deadlines()
        except asyncio.CancelledError:
            pass

    # CLI API Methods (synchronous, for CLI use)

    def submit_task(
        self,
        capability_id: str,
        params: dict,
        target_node: str = "",
        deadline: str = "",
        risk_level: str = "low",
    ) -> dict | None:
        """Submit a task via the gateway (synchronous)."""
        submission = TaskSubmission.create(
            capability_id=capability_id,
            params=params,
            target_node=target_node,
            deadline=deadline,
            risk_level=risk_level,
        )
        success, msg, task = self.task_coordinator.submit(submission)
        if success:
            # Try to deliver to a connected node
            self._try_deliver(task)
            return task
        _log.warning("Task submission failed: %s", msg)
        return None

    def _try_deliver(self, task: dict) -> bool:
        """Schedule delivery only to an actual current route.

        Cross-thread callers schedule a callback, not a delivered-state claim.
        Assignment and enqueue occur together on the gateway loop after a fresh
        route/session check. Losing a route before that callback leaves QUEUED.
        """
        if not task or not self._loop or not self._loop.is_running():
            return False
        node_id = task.get("target_node") or task.get("assigned_node", "")
        if not node_id:
            for session in self.session_registry.list_active():
                if (
                    session.node_id in self._delivery_routes
                    and self.node_registry.has_capability(
                        session.node_id, task["capability_id"]
                    )
                ):
                    node_id = session.node_id
                    break
        route = self._delivery_routes.get(node_id)
        if route is None:
            return False
        try:
            current_loop = asyncio.get_running_loop()
        except RuntimeError:
            current_loop = None
        if current_loop is self._loop:
            return self._enqueue_task(task["task_id"], node_id, route)
        try:
            self._loop.call_soon_threadsafe(
                self._enqueue_task, task["task_id"], node_id, route
            )
        except RuntimeError:
            return False
        return True

    def _enqueue_task(self, task_id: str, node_id: str, route: _DeliveryRoute) -> bool:
        """Revalidate and perform the existing assignment on its queue's loop."""
        if (
            not self._running
            or self._delivery_routes.get(node_id) is not route
            or route.writer.is_closing()
        ):
            return False
        session = self.session_registry.get_by_node(node_id)
        node = self.node_registry.get(node_id)
        self.task_coordinator.check_deadlines()
        task = self.task_coordinator.get(task_id)
        if (
            session is None
            or session.status != "active"
            or session.session_id != route.session_id
            or node is None
            or node.get("credential_status") == "revoked"
            or task is None
            or task["state"] != TaskState.QUEUED.value
            or (task.get("target_node") and task["target_node"] != node_id)
            or not self.node_registry.has_capability(node_id, task["capability_id"])
        ):
            return False
        session = self.session_registry.increment_sequence(session.session_id)
        if session is None:
            return False
        assignment = self.task_coordinator.assign(
            task_id, node_id, session.sequence_number, session_id=session.session_id
        )
        if assignment is None:
            return False
        envelope = ProtocolEnvelope(
            message_type="TASK_ASSIGNMENT",
            source_id="control_plane",
            target_id=node_id,
            sequence_number=session.sequence_number,
            payload=assignment.to_dict(),
        )
        route.queue.put_nowait(envelope.to_dict())
        return True

    def get_status(self) -> dict:
        """Get gateway status for CLI/Inspector."""
        return {
            "running": self._running,
            "host": self.host,
            "port": self.port,
            "nodes_registered": len(self.node_registry.list_all()),
            "nodes_online": len(
                [n for n in self.node_registry.list_all() if n.get("is_online")]
            ),
            "sessions_active": len(self.session_registry.list_active()),
            "tasks_queued": len(self.task_coordinator.list_all(TaskState.QUEUED.value)),
            "tasks_running": len(
                self.task_coordinator.list_all(TaskState.RUNNING.value)
            ),
            "tasks_completed": len(
                self.task_coordinator.list_all(TaskState.COMPLETED.value)
            ),
            "tasks_failed": len(self.task_coordinator.list_all(TaskState.FAILED.value)),
        }
