# -*- coding: utf-8 -*-
"""
Control Plane WebSocket — real-time event streaming for desktop clients.

Provides WS /api/v1/events — WebSocket endpoint for subscribing to
runtime events with pattern-based filtering and backfill support.

The WebSocket is UPGRADED from the existing HTTP server via an upgrade
handler. Events are sourced from the RuntimeEventBus and pushed to
connected clients with sequence-based ordering.
"""

from __future__ import annotations

import asyncio
import json
import logging
import threading
from typing import Any

log = logging.getLogger("nous.control_plane.ws")


class WsClientState:
    """Per-client WebSocket state."""
    def __init__(self, client_id: str):
        self.client_id = client_id
        self.subscriptions: list[str] = []     # event type patterns
        self.task_ids: list[str] = []          # filtered task IDs
        self.since_sequence: int = 0           # for backfill
        self.connected: bool = True
        self.last_event_sequence: int = 0
        self.message_queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=2048)


class WebSocketEventBridge:
    """
    Bridges RuntimeEventBus events to WebSocket clients.

    This is a singleton that:
    1. Subscribes to the RuntimeEventBus for all events
    2. Maintains a registry of connected WebSocket clients
    3. Filters and forwards events based on client subscriptions
    4. Supports backfill for missed events on reconnect
    """

    _instance: WebSocketEventBridge | None = None
    _lock = threading.Lock()

    def __init__(self):
        self._clients: dict[str, WsClientState] = {}
        self._global_sequence: int = 0
        self._event_buffer: list[dict[str, Any]] = []  # ring buffer, max 10000
        self._max_buffer = 10000
        self._started = False

    @classmethod
    def get(cls) -> WebSocketEventBridge:
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    def start(self):
        """Start listening to the RuntimeEventBus."""
        if self._started:
            return
        try:
            from nous_runtime.events.bus import get_event_bus
            bus = get_event_bus()
            bus.subscribe("*", self._on_event)
            self._started = True
            log.info("WebSocket event bridge started")
        except ImportError:
            log.warning("RuntimeEventBus not available — WebSocket events will be empty")

    def stop(self):
        """Stop listening."""
        self._started = False

    def _on_event(self, event: dict[str, Any]):
        """Callback from RuntimeEventBus. Thread-safe."""
        self._global_sequence += 1
        envelope = {
            "event_id": event.get("event_id", f"evt_{self._global_sequence}"),
            "event_type": event.get("event_type", "unknown"),
            "domain": event.get("domain", "system"),
            "source": event.get("source", "runtime"),
            "timestamp": event.get("timestamp", ""),
            "sequence": self._global_sequence,
            "payload": event.get("payload", {}),
            "task_id": event.get("task_id"),
            "node_id": event.get("node_id"),
        }
        # Ring buffer
        self._event_buffer.append(envelope)
        if len(self._event_buffer) > self._max_buffer:
            self._event_buffer = self._event_buffer[-self._max_buffer:]

        # Push to matching clients (fire-and-forget via asyncio queues)
        for client_id, state in list(self._clients.items()):
            if not state.connected:
                continue
            if self._matches(envelope, state):
                try:
                    state.message_queue.put_nowait(envelope)
                    state.last_event_sequence = envelope["sequence"]
                except asyncio.QueueFull:
                    # Drop oldest to make room
                    try:
                        state.message_queue.get_nowait()
                        state.message_queue.put_nowait(envelope)
                    except (asyncio.QueueEmpty, asyncio.QueueFull):
                        pass

    def _matches(self, event: dict[str, Any], state: WsClientState) -> bool:
        """Check if an event matches a client's subscriptions."""
        event_type = event.get("event_type", "")
        event_task_id = event.get("task_id", "")

        # Task ID filter
        if state.task_ids and event_task_id and event_task_id not in state.task_ids:
            return False

        # Pattern filter
        if not state.subscriptions:
            return True  # No filter = all events

        for pattern in state.subscriptions:
            if pattern == "*":
                return True
            if pattern.endswith("*") and event_type.startswith(pattern[:-1]):
                return True
            if pattern == event_type:
                return True
        return False

    def register(self, client_id: str) -> WsClientState:
        """Register a new WebSocket client."""
        state = WsClientState(client_id)
        self._clients[client_id] = state
        log.info("WebSocket client registered: %s", client_id)
        return state

    def unregister(self, client_id: str):
        """Remove a disconnected client."""
        self._clients.pop(client_id, None)
        log.info("WebSocket client unregistered: %s", client_id)

    def get_backfill(self, since_sequence: int, limit: int = 500) -> list[dict[str, Any]]:
        """Get events since a given sequence number for reconnection backfill."""
        if since_sequence <= 0:
            return list(self._event_buffer[-limit:])

        backfill = []
        for event in reversed(self._event_buffer):
            if event["sequence"] <= since_sequence:
                break
            backfill.append(event)
        backfill.reverse()
        return backfill[:limit]

    def update_subscriptions(self, client_id: str, patterns: list[str], task_ids: list[str], since_sequence: int = 0):
        """Update a client's subscription filters."""
        state = self._clients.get(client_id)
        if state:
            state.subscriptions = patterns
            state.task_ids = task_ids
            state.since_sequence = since_sequence



# HTTP Upgrade Handler (for integration with ThreadingHTTPServer)


def handle_websocket_upgrade(path: str, headers: dict, conn) -> bool:
    """
    Attempt to upgrade an HTTP request to WebSocket.

    Returns True if the upgrade was handled (the request was for WebSocket).
    Returns False if it's a normal HTTP request that should be routed normally.

    This is called from the HTTP server dispatch when a request with
    Upgrade: websocket header is detected.
    """
    if headers.get("upgrade", "").lower() != "websocket":
        return False

    # Validate the WebSocket handshake
    import hashlib
    import base64

    ws_key = headers.get("sec-websocket-key", "")
    if not ws_key:
        return False

    # Accept key
    magic = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
    accept = base64.b64encode(hashlib.sha1((ws_key + magic).encode()).digest()).decode()

    # Send upgrade response
    response = (
        "HTTP/1.1 101 Switching Protocols\r\n"
        "Upgrade: websocket\r\n"
        "Connection: Upgrade\r\n"
        f"Sec-WebSocket-Accept: {accept}\r\n"
        "\r\n"
    )
    conn.send(response.encode())

    # Start WebSocket handler in a new thread
    bridge = WebSocketEventBridge.get()
    bridge.start()

    client_id = f"ws_{id(conn)}"
    state = bridge.register(client_id)

    ws_thread = threading.Thread(
        target=_ws_handler,
        args=(conn, client_id, state, bridge),
        daemon=True,
    )
    ws_thread.start()
    return True


def _ws_handler(conn, client_id: str, state: WsClientState, bridge: WebSocketEventBridge):
    """Handle a WebSocket connection."""
    import select

    try:
        # Send backfill events
        backfill = bridge.get_backfill(state.since_sequence)
        for event in backfill:
            _ws_send(conn, event)

        # Event push loop (non-blocking check, async-inspired)
        buffer = b""
        while state.connected:
            # Check for incoming WebSocket frames (non-blocking)
            ready, _, _ = select.select([conn], [], [], 0.1)
            if ready:
                try:
                    data = conn.recv(4096)
                    if not data:
                        break
                    buffer += data
                    buffer = _ws_handle_frame(conn, buffer, client_id, state, bridge)
                except (ConnectionError, OSError):
                    break

            # Push queued events
            try:
                while True:
                    event = state.message_queue.get_nowait()
                    _ws_send(conn, event)
            except asyncio.QueueEmpty:
                pass
    except Exception:
        pass
    finally:
        state.connected = False
        bridge.unregister(client_id)
        try:
            conn.close()
        except Exception:
            pass


def _ws_handle_frame(conn, buffer: bytes, client_id: str, state: WsClientState, bridge: WebSocketEventBridge) -> bytes:
    """Parse WebSocket frames from the buffer."""
    import struct

    while len(buffer) >= 2:
        # Minimum frame: 2 bytes header
        byte1, byte2 = buffer[0], buffer[1]
        opcode = byte1 & 0x0F
        masked = (byte2 & 0x80) != 0
        payload_len = byte2 & 0x7F

        if opcode == 0x8:  # Close
            state.connected = False
            _ws_send_close(conn)
            return b""

        if opcode == 0x9:  # Ping
            _ws_send_pong(conn, buffer)
            return b""

        # Calculate header length
        header_len = 2
        if payload_len == 126:
            if len(buffer) < 4:
                return buffer
            payload_len = struct.unpack(">H", buffer[2:4])[0]
            header_len = 4
        elif payload_len == 127:
            if len(buffer) < 10:
                return buffer
            payload_len = struct.unpack(">Q", buffer[2:10])[0]
            header_len = 10

        mask_offset = header_len
        if masked:
            header_len += 4

        frame_len = header_len + payload_len
        if len(buffer) < frame_len:
            return buffer  # Incomplete frame

        if opcode == 0x1:  # Text
            payload = buffer[mask_offset + (4 if masked else 0):frame_len]
            if masked:
                mask_key = buffer[mask_offset:mask_offset + 4]
                payload = bytes(b ^ mask_key[i % 4] for i, b in enumerate(payload))
            try:
                msg = json.loads(payload.decode("utf-8"))
                action = msg.get("action", "")
                if action == "subscribe":
                    bridge.update_subscriptions(
                        client_id,
                        msg.get("patterns", ["*"]),
                        msg.get("task_ids", []),
                        msg.get("since_sequence", 0),
                    )
                elif action == "unsubscribe":
                    bridge.update_subscriptions(client_id, [], [], 0)
            except (json.JSONDecodeError, UnicodeDecodeError):
                pass

        buffer = buffer[frame_len:]

    return buffer


def _ws_send(conn, data: dict[str, Any]) -> None:
    """Send a JSON message over WebSocket (text frame)."""
    import struct
    payload = json.dumps(data, ensure_ascii=False).encode("utf-8")
    frame = bytearray()
    frame.append(0x81)  # FIN + Text opcode
    length = len(payload)
    if length < 126:
        frame.append(length)
    elif length < 65536:
        frame.append(126)
        frame.extend(struct.pack(">H", length))
    else:
        frame.append(127)
        frame.extend(struct.pack(">Q", length))
    frame.extend(payload)
    try:
        conn.sendall(bytes(frame))
    except (ConnectionError, OSError):
        pass


def _ws_send_close(conn, code: int = 1000) -> None:
    """Send a WebSocket close frame."""
    import struct
    frame = bytearray([0x88, 0x02])
    frame.extend(struct.pack(">H", code))
    try:
        conn.sendall(bytes(frame))
    except Exception:
        pass


def _ws_send_pong(conn, ping_data: bytes) -> None:
    """Send a WebSocket pong frame."""
    frame = bytearray([0x8A])
    payload = ping_data[2:] if len(ping_data) > 2 else b""
    frame.append(len(payload))
    frame.extend(payload)
    try:
        conn.sendall(bytes(frame))
    except Exception:
        pass
