# -*- coding: utf-8 -*-
"""
NodeDaemon — outbound connectivity client.

Connects to Control Plane over TCP message protocol.
Supports: connect, authenticate, heartbeat, task execution, reconnect.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import random
import struct
import threading
import time

from ..protocol.envelope import ProtocolEnvelope
from ..protocol.identity import NodeIdentity
from ..protocol.pairing import PairingRequest
from ..protocol.task import (
    TaskAssignment, TaskAcknowledgement,
    TaskResult, TaskCancellation,
)

_log = logging.getLogger("nous.node.daemon")

HEADER_FMT = "!I"
MAX_MESSAGE_BYTES = 1_048_576

# Reconnect config
RECONNECT_INITIAL_DELAY = 1.0
RECONNECT_MAX_DELAY = 60.0
RECONNECT_JITTER = 0.25


class NodeDaemon:
    """
    Nous Node daemon.

    Connects to a Control Plane, authenticates via pairing, maintains
    heartbeat, receives and executes task assignments.
    """

    def __init__(
        self,
        control_plane_host: str = "127.0.0.1",
        control_plane_port: int = 9770,
        node_name: str = "node",
        workspace_root: str = "",
    ):
        self.cp_host = control_plane_host
        self.cp_port = control_plane_port
        self.node_name = node_name
        self.workspace_root = workspace_root or os.getcwd()

        # Identity — set after generation or pairing
        self.node_id: str = ""
        self.identity: NodeIdentity | None = None
        self.signing_key: str = ""  # For message signing (simplified: HMAC secret)

        # Session
        self.session_id: str = ""
        self.session_seq: int = 0

        # State
        self._running = False
        self._connected = False
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None

        # Capability handlers
        self._capabilities: dict[str, callable] = {}
        self.register_capability("system.echo", self._handle_echo)

    # Capability Registration

    def register_capability(self, capability_id: str, handler: callable) -> None:
        """Register a capability handler."""
        self._capabilities[capability_id] = handler

    # Lifecycle

    def start(self) -> None:
        """Start the node daemon in a background thread."""
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()
        _log.info("Node daemon started")

    def stop(self) -> None:
        """Stop the node daemon."""
        self._running = False
        if self._loop and self._loop.is_running():
            try:
                future = asyncio.run_coroutine_threadsafe(self._close_writer(), self._loop)
                future.result(timeout=2.0)
            except Exception:
                pass
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=3.0)
        if self._thread and self._thread.is_alive() and self._loop and self._loop.is_running():
            self._loop.call_soon_threadsafe(self._loop.stop)
            self._thread.join(timeout=1.0)
        self._connected = False
        _log.info("Node daemon stopped")

    def _run_loop(self) -> None:
        """Main loop: connect, maintain session, reconnect."""
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        try:
            self._loop.run_until_complete(self._connection_loop())
        except (asyncio.CancelledError, RuntimeError):
            pass
        finally:
            self._connected = False
            if self._loop:
                pending = [task for task in asyncio.all_tasks(self._loop) if not task.done()]
                for task in pending:
                    task.cancel()
                if pending:
                    self._loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
                self._loop.close()


    async def _close_writer(self) -> None:
        """Close the active stream writer without tearing down the loop."""
        writer = self._writer
        self._writer = None
        self._reader = None
        self._connected = False
        if writer is None:
            return
        writer.close()
        try:
            await writer.wait_closed()
        except (ConnectionError, OSError, RuntimeError, asyncio.CancelledError):
            pass
    async def _connection_loop(self) -> None:
        """Connect and maintain session with reconnection."""
        delay = RECONNECT_INITIAL_DELAY
        while self._running:
            try:
                await self._connect_and_run()
                # Clean disconnect — reset delay
                delay = RECONNECT_INITIAL_DELAY
            except (ConnectionError, OSError, asyncio.TimeoutError) as e:
                _log.warning("Connection failed: %s (retry in %.1fs)", e, delay)
            if not self._running:
                break
            # Backoff with jitter
            jitter = delay * RECONNECT_JITTER * (random.random() * 2 - 1)
            await asyncio.sleep(delay + jitter)
            delay = min(delay * 2, RECONNECT_MAX_DELAY)

    async def _connect_and_run(self) -> None:
        """Connect to Control Plane and run the session loop."""
        _log.info("Connecting to %s:%d...", self.cp_host, self.cp_port)
        self._reader, self._writer = await asyncio.open_connection(
            self.cp_host, self.cp_port
        )
        self._connected = True

        try:
            # Send HELLO
            await self._send_hello()
            # Heartbeat + message receive loop
            await self._session_loop()
        finally:
            self._connected = False
            if self._loop:
                pending = [task for task in asyncio.all_tasks(self._loop) if not task.done()]
                for task in pending:
                    task.cancel()
                if pending:
                    self._loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
                self._loop.close()
            await self._close_writer()

    # Protocol Messages

    async def _send_hello(self) -> None:
        """Send HELLO to establish session."""
        env = ProtocolEnvelope(
            message_type="HELLO",
            source_id=self.node_id or "unpaired_node",
            target_id="control_plane",
            payload={
                "node_id": self.node_id or "unpaired_node",
                "node_name": self.node_name,
                "supported_protocol_versions": ["1.0"],
            },
        )
        await self._send_envelope(env)

        # Wait for WELCOME
        response = await self._receive_envelope(timeout=10.0)
        if not response or response.message_type != "WELCOME":
            raise ConnectionError("Failed to receive WELCOME")

        self.session_id = response.payload.get("session_id", "")
        _log.info("Session established: %s", self.session_id)

    async def _session_loop(self) -> None:
        """Main session loop: heartbeat + message processing."""
        heartbeat_interval = 15.0
        last_heartbeat = 0.0

        while self._running and self._connected:
            now = time.time()

            # Send heartbeat
            if now - last_heartbeat >= heartbeat_interval:
                await self._send_heartbeat()
                last_heartbeat = now

            # Receive messages (non-blocking, short timeout)
            try:
                env = await self._receive_envelope(timeout=1.0)
                if env:
                    await self._handle_message(env)
            except asyncio.TimeoutError:
                pass

    async def _send_heartbeat(self) -> None:
        """Send a HEARTBEAT message."""
        self.session_seq += 1
        env = ProtocolEnvelope(
            message_type="HEARTBEAT",
            source_id=self.node_id,
            target_id="control_plane",
            sequence_number=self.session_seq,
            payload={
                "session_id": self.session_id,
                "sequence_number": self.session_seq,
                "node_health": {
                    "status": "ok",
                    "load": 0.0,
                    "capabilities_healthy": len(self._capabilities),
                },
            },
        )
        await self._send_envelope(env)

    async def _handle_message(self, env: ProtocolEnvelope) -> None:
        """Handle an incoming message from the Control Plane."""
        handlers = {
            "HEARTBEAT_ACK": self._handle_hb_ack,
            "TASK_ASSIGNMENT": self._handle_task_assignment,
            "TASK_CANCELLATION": self._handle_task_cancellation,
            "PROTOCOL_ERROR": self._handle_protocol_error,
            "PAIRING_APPROVAL": self._handle_pairing_approval,
        }
        handler = handlers.get(env.message_type)
        if handler:
            await handler(env)

    async def _handle_hb_ack(self, env: ProtocolEnvelope) -> None:
        pass  # Heartbeat acknowledged — session alive

    async def _handle_task_assignment(self, env: ProtocolEnvelope) -> None:
        """Execute an assigned task."""
        assignment = TaskAssignment.from_dict(env.payload)
        task_id = assignment.task_id
        capability_id = assignment.capability_id

        # Check capability availability
        handler = self._capabilities.get(capability_id)
        if not handler:
            ack = TaskAcknowledgement(task_id=task_id, accepted=False,
                                       reject_reason=f"Unknown capability: {capability_id}")
            await self._send_ack(ack)
            return

        # ACK
        ack = TaskAcknowledgement(task_id=task_id, accepted=True)
        await self._send_ack(ack)

        # Execute
        try:
            result_data = await handler(assignment.params)
            result = TaskResult.success(task_id, result_data, self.node_id)
        except Exception as e:
            result = TaskResult.failure(task_id, str(e), self.node_id)

        await self._send_result(result)

    async def _handle_task_cancellation(self, env: ProtocolEnvelope) -> None:
        """Handle task cancellation."""
        cancellation = TaskCancellation.from_dict(env.payload)
        _log.info("Task %s cancelled: %s", cancellation.task_id, cancellation.reason)
        result = TaskResult.failure(cancellation.task_id,
                                     f"cancelled: {cancellation.reason}", self.node_id)
        await self._send_result(result)

    async def _handle_protocol_error(self, env: ProtocolEnvelope) -> None:
        _log.warning("Protocol error: %s", env.payload)

    async def _handle_pairing_approval(self, env: ProtocolEnvelope) -> None:
        """Store pairing approval."""
        from ..protocol.pairing import PairingApproval
        approval = PairingApproval.from_dict(env.payload)
        self.node_id = approval.node_id
        _log.info("Pairing approved: node_id=%s", self.node_id)

    # Capability Handlers

    async def _handle_echo(self, params: dict) -> dict:
        """system.echo — return the input message."""
        message = params.get("message", "")
        return {"echo": message}

    # Transport

    async def _send_envelope(self, env: ProtocolEnvelope) -> None:
        """Send an envelope over the transport."""
        if self.signing_key:
            env.sign(self.signing_key)
        data = env.to_json().encode("utf-8")
        self._writer.write(struct.pack(HEADER_FMT, len(data)) + data)
        await self._writer.drain()

    async def _receive_envelope(self, timeout: float = 30.0) -> ProtocolEnvelope | None:
        """Receive an envelope from the transport."""
        try:
            header = await asyncio.wait_for(self._reader.readexactly(4), timeout=timeout)
            length = struct.unpack(HEADER_FMT, header)[0]
            if length > MAX_MESSAGE_BYTES:
                _log.warning("Oversized message: %d bytes", length)
                return None
            data = await asyncio.wait_for(self._reader.readexactly(length), timeout=5.0)
            msg = json.loads(data.decode("utf-8"))
            return ProtocolEnvelope.from_dict(msg)
        except asyncio.TimeoutError:
            return None
        except (asyncio.IncompleteReadError, ConnectionError):
            self._connected = False
            return None

    async def _send_ack(self, ack: TaskAcknowledgement) -> None:
        env = ProtocolEnvelope(
            message_type="TASK_ACKNOWLEDGEMENT",
            source_id=self.node_id,
            target_id="control_plane",
            payload=ack.to_dict(),
        )
        await self._send_envelope(env)

    async def _send_result(self, result: TaskResult) -> None:
        env = ProtocolEnvelope(
            message_type="TASK_RESULT",
            source_id=self.node_id,
            target_id="control_plane",
            payload=result.to_dict(),
        )
        await self._send_envelope(env)

    # Public API (synchronous wrappers for CLI)

    def pair(self, pairing_code: str, identity: NodeIdentity) -> bool:
        """
        Pair with the Control Plane (blocks until complete or timeout).
        Must be called before start() or while daemon is running.
        """
        self.node_id = identity.node_id
        self.identity = identity

        async def _pair() -> bool:
            try:
                reader, writer = await asyncio.open_connection(self.cp_host, self.cp_port)
                env = ProtocolEnvelope(
                    message_type="PAIRING_REQUEST",
                    source_id=self.node_id,
                    target_id="control_plane",
                    payload=PairingRequest(
                        pairing_code=pairing_code,
                        node_identity=identity.to_dict(),
                    ).to_dict(),
                )
                data = env.to_json().encode("utf-8")
                writer.write(struct.pack(HEADER_FMT, len(data)) + data)
                await writer.drain()

                # Wait for response
                header = await asyncio.wait_for(reader.readexactly(4), timeout=10.0)
                length = struct.unpack(HEADER_FMT, header)[0]
                resp_data = await reader.readexactly(length)
                response = ProtocolEnvelope.from_dict(json.loads(resp_data.decode("utf-8")))

                writer.close()
                await writer.wait_closed()

                if response.message_type == "PAIRING_APPROVAL":
                    from ..protocol.pairing import PairingApproval
                    approval = PairingApproval.from_dict(response.payload)
                    _log.info("Paired successfully: %s", approval.node_id)
                    return True
                else:
                    _log.error("Pairing rejected: %s", response.payload)
                    return False
            except Exception as e:
                _log.error("Pairing failed: %s", e)
                return False

        loop = self._loop
        if loop and loop.is_running():
            future = asyncio.run_coroutine_threadsafe(_pair(), loop)
            return future.result(timeout=15.0)
        return asyncio.run(_pair())

    def is_connected(self) -> bool:
        return self._connected and self._running

    def get_status(self) -> dict:
        return {
            "connected": self._connected,
            "node_id": self.node_id,
            "node_name": self.node_name,
            "session_id": self.session_id,
            "control_plane": f"{self.cp_host}:{self.cp_port}",
            "capabilities": list(self._capabilities.keys()),
        }
