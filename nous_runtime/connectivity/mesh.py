# -*- coding: utf-8 -*-
"""
Node Mesh — distributed node communication and synchronization.

Implements §5.2-5.4 of the master plan:
- Heartbeat-based node monitoring
- Offline event buffering and replay
- Message deduplication
- Node state synchronization
- Lease-based exclusive access
- Primary node failover support
"""

from __future__ import annotations

import logging
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable

from nous_runtime.kernel.error_codes import ErrorCode, NousResult
from nous_runtime.kernel.identity import NodeConnectivity
from nous_runtime.kernel.node import Node
from nous_runtime.compat.ids import make_id

log = logging.getLogger("nous.connectivity.mesh")


# Message envelope for sync

@dataclass
class MeshMessage:
    """A message in the node mesh, with dedup and ordering."""
    message_id: str = field(default_factory=lambda: make_id(prefix="mesh"))
    source_node_id: str = ""
    target_node_id: str = ""             # "" = broadcast
    message_type: str = ""               # heartbeat, capability_report, task_update, etc.
    payload: dict[str, Any] = field(default_factory=dict)
    sequence_number: int = 0
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    signature: str = ""                  # HMAC signature

    def to_dict(self) -> dict[str, Any]:
        return {
            "message_id": self.message_id,
            "source_node_id": self.source_node_id,
            "target_node_id": self.target_node_id,
            "message_type": self.message_type,
            "payload": self.payload,
            "sequence_number": self.sequence_number,
            "timestamp": self.timestamp,
        }


# Dedup filter

class MessageDedupFilter:
    """Deduplicate messages by message_id within a time window."""

    def __init__(self, window_seconds: int = 300, max_entries: int = 10000):
        self._window = window_seconds
        self._seen: OrderedDict[str, float] = OrderedDict()
        self._max_entries = max_entries
        self._lock = threading.Lock()

    def is_duplicate(self, message_id: str) -> bool:
        with self._lock:
            self._prune()
            if message_id in self._seen:
                return True
            self._seen[message_id] = time.monotonic()
            if len(self._seen) > self._max_entries:
                self._seen.popitem(last=False)  # Remove oldest
            return False

    def _prune(self) -> None:
        now = time.monotonic()
        expired = [mid for mid, ts in self._seen.items()
                   if now - ts > self._window]
        for mid in expired:
            del self._seen[mid]


# Offline event buffer

@dataclass
class BufferedEvent:
    """An event buffered while a node was offline."""
    event_id: str = field(default_factory=lambda: make_id(prefix="bufev"))
    target_node_id: str = ""
    message: MeshMessage = field(default_factory=MeshMessage)
    buffered_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    delivered: bool = False


class OfflineEventBuffer:
    """Buffer events for offline nodes, replay on reconnect.

    Per §5.4: when a node goes offline, events destined for it are buffered.
    On reconnect, all buffered events are replayed in order.
    """

    def __init__(self, max_per_node: int = 1000):
        self._buffers: dict[str, list[BufferedEvent]] = {}
        self._max_per_node = max_per_node
        self._lock = threading.Lock()

    def buffer(self, target_node_id: str, message: MeshMessage) -> None:
        """Buffer a message for an offline node."""
        with self._lock:
            if target_node_id not in self._buffers:
                self._buffers[target_node_id] = []
            buf = self._buffers[target_node_id]
            if len(buf) >= self._max_per_node:
                buf.pop(0)  # Drop oldest
            buf.append(BufferedEvent(
                target_node_id=target_node_id,
                message=message,
            ))

    def get_and_clear(self, node_id: str) -> list[BufferedEvent]:
        """Get all buffered events for a node and clear the buffer."""
        with self._lock:
            events = self._buffers.pop(node_id, [])
            return events

    def count_for_node(self, node_id: str) -> int:
        with self._lock:
            return len(self._buffers.get(node_id, []))

    def total_buffered(self) -> int:
        with self._lock:
            return sum(len(b) for b in self._buffers.values())


# Node Mesh

class NodeMesh:
    """Manages the distributed mesh of Nous nodes.

    Handles:
    - Heartbeat monitoring and timeout detection
    - Offline event buffering and replay on reconnect
    - Message deduplication
    - Sequence number tracking per node
    """

    def __init__(self, primary_node_id: str = ""):
        self._primary_node_id = primary_node_id
        self._nodes: dict[str, Node] = {}
        self._sequences: dict[str, int] = {}  # node_id → last sequence
        self._dedup = MessageDedupFilter()
        self._offline_buffer = OfflineEventBuffer()
        self._lock = threading.RLock()

        # Callbacks
        self.on_node_offline: Callable[[str], None] | None = None
        self.on_node_online: Callable[[str], None] | None = None
        self.on_node_degraded: Callable[[str], None] | None = None

    # Node management

    def register_node(self, node: Node) -> NousResult[Node]:
        with self._lock:
            self._nodes[node.metadata.id] = node
            self._sequences[node.metadata.id] = 0
            return NousResult.ok(node)

    def remove_node(self, node_id: str) -> NousResult[None]:
        with self._lock:
            self._nodes.pop(node_id, None)
            self._sequences.pop(node_id, None)
            return NousResult.ok(None)

    def get_node(self, node_id: str) -> NousResult[Node]:
        with self._lock:
            node = self._nodes.get(node_id)
            if node is None:
                return NousResult.err(ErrorCode.NOT_FOUND, message=f"Node '{node_id}' not in mesh")
            return NousResult.ok(node)

    def list_nodes(self, online_only: bool = False) -> list[Node]:
        with self._lock:
            nodes = list(self._nodes.values())
            if online_only:
                nodes = [n for n in nodes if n.is_online]
            return nodes

    # Heartbeat

    def heartbeat(self, node_id: str) -> NousResult[Node]:
        with self._lock:
            result = self.get_node(node_id)
            if not result.ok:
                return result
            node = result.value
            was_offline = not node.is_online
            node.record_heartbeat()

            if node.connectivity in (NodeConnectivity.OFFLINE, NodeConnectivity.RECONNECTING):
                node.mark_online(reason="Heartbeat received")

            if was_offline and node.is_online and self.on_node_online:
                self.on_node_online(node_id)

            return NousResult.ok(node)

    def check_timeouts(self) -> list[str]:
        """Check all nodes and return IDs of timed-out nodes."""
        with self._lock:
            timed_out = []
            for node_id, node in self._nodes.items():
                if node.is_online and node.heartbeat_timed_out:
                    node.mark_offline(reason="Heartbeat timeout")
                    timed_out.append(node_id)
                    # Buffer events for offline node
                    if self.on_node_offline:
                        self.on_node_offline(node_id)
            return timed_out

    # Message sync

    def send(self, message: MeshMessage) -> NousResult[str]:
        """Send a message to a node, buffering if offline."""
        with self._lock:
            # Assign sequence number
            seq = self._sequences.get(message.source_node_id, 0) + 1
            self._sequences[message.source_node_id] = seq
            message.sequence_number = seq

            if message.target_node_id:
                target = self._nodes.get(message.target_node_id)
                if target and not target.is_online:
                    self._offline_buffer.buffer(message.target_node_id, message)
                    return NousResult.ok(message.message_id)

            return NousResult.ok(message.message_id)

    def broadcast(self, message_type: str, payload: dict[str, Any],
                  source_node_id: str = "") -> NousResult[list[str]]:
        """Broadcast a message to all online nodes."""
        message_ids = []
        with self._lock:
            for node_id in self._nodes:
                msg = MeshMessage(
                    source_node_id=source_node_id,
                    target_node_id=node_id,
                    message_type=message_type,
                    payload=payload,
                )
                result = self.send(msg)
                if result.ok:
                    message_ids.append(result.value)
        return NousResult.ok(message_ids)

    def replay_offline_events(self, node_id: str) -> NousResult[list[MeshMessage]]:
        """Replay buffered events for a reconnecting node."""
        events = self._offline_buffer.get_and_clear(node_id)
        messages = [e.message for e in events]
        log.info("Replayed %d events for node %s", len(messages), node_id)
        return NousResult.ok(messages)

    def dedup_check(self, message_id: str) -> bool:
        """Check if a message has already been seen. Returns True if duplicate."""
        return self._dedup.is_duplicate(message_id)

    # Status

    def status(self) -> dict[str, Any]:
        with self._lock:
            nodes = list(self._nodes.values())
            return {
                "total_nodes": len(nodes),
                "online": sum(1 for n in nodes if n.is_online),
                "offline": sum(1 for n in nodes if not n.is_online),
                "buffered_events": self._offline_buffer.total_buffered(),
                "buffered_by_node": {
                    nid: self._offline_buffer.count_for_node(nid)
                    for nid in self._nodes
                },
            }
