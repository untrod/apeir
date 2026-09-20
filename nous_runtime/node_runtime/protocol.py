"""Nous Node Protocol v1 envelopes, signatures, and replay protection."""

from __future__ import annotations

import json
import secrets
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)

NODE_PROTOCOL = "nous-node"
NODE_PROTOCOL_VERSION = "1.0"
MAX_MESSAGE_BYTES = 1_048_576
MAX_CLOCK_SKEW_SECONDS = 120

MESSAGE_TYPES = frozenset(
    {
        "REGISTER",
        "HEARTBEAT",
        "RESOURCE_REPORT",
        "WORKLOAD_START",
        "WORKLOAD_STOP",
        "WORKLOAD_STATUS",
        "LEASE_ACQUIRE",
        "LEASE_RELEASE",
        "ARTIFACT_FETCH",
        "ARTIFACT_READY",
        "DEVICE_REPORT",
        "TELEMETRY",
        "ERROR",
        "ACK",
    }
)

PAYLOAD_REQUIRED = {
    "REGISTER": {"node_id", "identity", "supported_versions"},
    "HEARTBEAT": {"node_id", "status", "heartbeat_sequence"},
    "RESOURCE_REPORT": {"schema", "measurement_source"},
    "WORKLOAD_START": {"workload_id", "capability", "arguments", "timeout_seconds"},
    "WORKLOAD_STOP": {"workload_id"},
    "WORKLOAD_STATUS": {"workload_id", "state"},
    "LEASE_ACQUIRE": {"lease_id", "resource_id", "ttl_seconds"},
    "LEASE_RELEASE": {"lease_id", "resource_id"},
    "ARTIFACT_FETCH": {"digest"},
    "ARTIFACT_READY": {"digest", "state"},
    "DEVICE_REPORT": {"devices"},
    "TELEMETRY": {"event_type"},
    "ERROR": {"code"},
    "ACK": {"acknowledged"},
}

IDEMPOTENT_OPERATION_TYPES = frozenset(
    {"WORKLOAD_START", "WORKLOAD_STOP", "LEASE_ACQUIRE", "LEASE_RELEASE", "ARTIFACT_FETCH"}
)


class NodeProtocolError(ValueError):
    """A fail-closed wire protocol validation error."""


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise NodeProtocolError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


@dataclass
class NodeProtocolEnvelope:
    message_type: str
    source: str
    target: str
    sequence: int
    payload: dict[str, Any] = field(default_factory=dict)
    message_id: str = field(default_factory=lambda: f"msg_{secrets.token_hex(16)}")
    idempotency_key: str = ""
    reply_to: str = ""
    created_at: str = field(default_factory=_utc_now)
    expires_at: str = ""
    protocol: str = NODE_PROTOCOL
    protocol_version: str = NODE_PROTOCOL_VERSION
    signature: str = ""

    def unsigned_dict(self) -> dict[str, Any]:
        return {
            "created_at": self.created_at,
            "expires_at": self.expires_at,
            "idempotency_key": self.idempotency_key,
            "message_id": self.message_id,
            "message_type": self.message_type,
            "payload": self.payload,
            "protocol": self.protocol,
            "protocol_version": self.protocol_version,
            "reply_to": self.reply_to,
            "sequence": self.sequence,
            "source": self.source,
            "target": self.target,
        }

    def to_dict(self) -> dict[str, Any]:
        return {**self.unsigned_dict(), "signature": self.signature}

    def sign(self, private_key: Ed25519PrivateKey) -> NodeProtocolEnvelope:
        self.signature = private_key.sign(_canonical(self.unsigned_dict())).hex()
        return self

    def verify(self, public_key_hex: str) -> bool:
        try:
            public_key = Ed25519PublicKey.from_public_bytes(bytes.fromhex(public_key_hex))
            public_key.verify(bytes.fromhex(self.signature), _canonical(self.unsigned_dict()))
        except (InvalidSignature, ValueError):
            return False
        return True

    def validate(self, *, check_time: bool = True) -> None:
        if self.protocol != NODE_PROTOCOL:
            raise NodeProtocolError("unsupported protocol")
        if self.protocol_version != NODE_PROTOCOL_VERSION:
            raise NodeProtocolError("unsupported protocol version")
        if self.message_type not in MESSAGE_TYPES:
            raise NodeProtocolError("unsupported message type")
        if not self.message_id or not self.source or not self.target:
            raise NodeProtocolError("message identity and route are required")
        if isinstance(self.sequence, bool) or not isinstance(self.sequence, int) or self.sequence < 1:
            raise NodeProtocolError("sequence must be a positive integer")
        if not isinstance(self.payload, dict):
            raise NodeProtocolError("payload must be an object")
        missing_payload = sorted(PAYLOAD_REQUIRED[self.message_type] - self.payload.keys())
        if missing_payload:
            raise NodeProtocolError(
                f"{self.message_type} payload missing: {', '.join(missing_payload)}"
            )
        if self.message_type in IDEMPOTENT_OPERATION_TYPES and not self.idempotency_key:
            raise NodeProtocolError(
                f"{self.message_type} requires an idempotency_key"
            )
        if not self.signature:
            raise NodeProtocolError("signature is required")
        if check_time:
            created = _parse_time(self.created_at)
            now = datetime.now(timezone.utc)
            if abs((now - created).total_seconds()) > MAX_CLOCK_SKEW_SECONDS:
                raise NodeProtocolError("message timestamp is outside allowed clock skew")
            if self.expires_at and now >= _parse_time(self.expires_at):
                raise NodeProtocolError("message has expired")

    def to_json(self) -> str:
        self.validate()
        encoded = _canonical(self.to_dict())
        if len(encoded) > MAX_MESSAGE_BYTES:
            raise NodeProtocolError("message exceeds size limit")
        return encoded.decode("utf-8")

    @classmethod
    def from_json(cls, raw: str | bytes, *, check_time: bool = True) -> NodeProtocolEnvelope:
        encoded = raw.encode("utf-8") if isinstance(raw, str) else raw
        if len(encoded) > MAX_MESSAGE_BYTES:
            raise NodeProtocolError("message exceeds size limit")
        try:
            value = json.loads(encoded.decode("utf-8"), object_pairs_hook=_reject_duplicate_keys)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise NodeProtocolError("message is not valid UTF-8 JSON") from exc
        if not isinstance(value, dict):
            raise NodeProtocolError("message must be an object")
        required = {
            "message_type", "source", "target", "sequence", "payload", "message_id",
            "created_at", "protocol", "protocol_version", "signature",
        }
        missing = sorted(required - value.keys())
        if missing:
            raise NodeProtocolError(f"missing fields: {', '.join(missing)}")
        envelope = cls(
            message_type=value["message_type"],
            source=value["source"],
            target=value["target"],
            sequence=value["sequence"],
            payload=value["payload"],
            message_id=value["message_id"],
            idempotency_key=value.get("idempotency_key", ""),
            reply_to=value.get("reply_to", ""),
            created_at=value["created_at"],
            expires_at=value.get("expires_at", ""),
            protocol=value["protocol"],
            protocol_version=value["protocol_version"],
            signature=value["signature"],
        )
        envelope.validate(check_time=check_time)
        return envelope


class ReplayWindow:
    """Bounded duplicate and monotonic-sequence protection per source."""

    def __init__(self, capacity: int = 4096):
        if capacity < 1:
            raise ValueError("capacity must be positive")
        self.capacity = capacity
        self._order: deque[str] = deque()
        self._seen: set[str] = set()
        self._last_sequence: dict[str, int] = {}

    def accept(self, envelope: NodeProtocolEnvelope) -> None:
        if envelope.message_id in self._seen:
            raise NodeProtocolError("duplicate message_id")
        last = self._last_sequence.get(envelope.source, 0)
        if envelope.sequence <= last:
            raise NodeProtocolError("sequence did not advance")
        self._last_sequence[envelope.source] = envelope.sequence
        self._seen.add(envelope.message_id)
        self._order.append(envelope.message_id)
        while len(self._order) > self.capacity:
            self._seen.discard(self._order.popleft())


def _parse_time(raw: str) -> datetime:
    try:
        value = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except (AttributeError, ValueError) as exc:
        raise NodeProtocolError("invalid timestamp") from exc
    if value.tzinfo is None:
        raise NodeProtocolError("timestamp must include a timezone")
    return value.astimezone(timezone.utc)
