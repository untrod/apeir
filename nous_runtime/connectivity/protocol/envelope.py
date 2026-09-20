# -*- coding: utf-8 -*-
"""
ProtocolEnvelope -unified message envelope for all connectivity messages.

Extends the existing nous_core.protocol.Envelope with:
  - schema_version / protocol_version
  - idempotency_key, sequence_number, nonce
  - expires_at
  - source_id / target_id (node-specific identifiers)
  - deterministic hash for integrity verification
"""

from __future__ import annotations

import hashlib
import hmac
import json
from dataclasses import dataclass, field
from typing import Any

from nous_runtime.compat import ids as _ids
from nous_runtime.compat import time as _time

from .serialization import deterministic_json, deterministic_hash, redacted_serialization

# Current protocol version — sourced from canonical version authority
from nous_runtime._version import PROTOCOL_VERSION

SCHEMA_VERSION = "1.0"  # envelope message format version

# Supported protocol versions for negotiation
SUPPORTED_VERSIONS = ["1.0"]

# Message types
MESSAGE_TYPES = {
    # Session
    "HELLO", "WELCOME", "HEARTBEAT", "HEARTBEAT_ACK", "GOODBYE",
    # Pairing
    "PAIRING_REQUEST", "PAIRING_APPROVAL", "PAIRING_REJECTION",
    # Task
    "TASK_SUBMISSION", "TASK_ASSIGNMENT", "TASK_ACKNOWLEDGEMENT",
    "TASK_EVENT", "TASK_RESULT", "TASK_CANCELLATION",
    # Error
    "PROTOCOL_ERROR",
}

# Maximum envelope size (without payload)
MAX_ENVELOPE_SIZE = 1024


@dataclass
class ProtocolEnvelope:
    """Versioned message envelope for all connectivity communication."""

    schema_version: str = SCHEMA_VERSION
    protocol_version: str = PROTOCOL_VERSION
    message_id: str = ""
    message_type: str = ""
    source_id: str = ""
    target_id: str = ""
    created_at: str = ""
    expires_at: str = ""
    sequence_number: int = 0
    idempotency_key: str = ""
    nonce: str = ""
    payload: dict[str, Any] = field(default_factory=dict)
    signature: str = ""

    def __post_init__(self):
        if not self.message_id:
            self.message_id = _ids.make_id("msg")
        if not self.created_at:
            self.created_at = _time.utc_now()

    # Serialization

    def to_dict(self) -> dict[str, Any]:
        """Convert to dict for serialization (includes all fields)."""
        return {
            "schema_version": self.schema_version,
            "protocol_version": self.protocol_version,
            "message_id": self.message_id,
            "message_type": self.message_type,
            "source_id": self.source_id,
            "target_id": self.target_id,
            "created_at": self.created_at,
            "expires_at": self.expires_at,
            "sequence_number": self.sequence_number,
            "idempotency_key": self.idempotency_key,
            "nonce": self.nonce,
            "payload": self.payload,
            "signature": self.signature,
        }

    def to_json(self) -> str:
        """Deterministic JSON serialization."""
        return deterministic_json(self.to_dict())

    def to_redacted_dict(self) -> dict[str, Any]:
        """Dict with secret fields redacted (safe for logs)."""
        return redacted_serialization(self.to_dict())

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ProtocolEnvelope:
        """Parse from dict."""
        return cls(
            schema_version=data.get("schema_version", SCHEMA_VERSION),
            protocol_version=data.get("protocol_version", PROTOCOL_VERSION),
            message_id=data.get("message_id", ""),
            message_type=data.get("message_type", ""),
            source_id=data.get("source_id", ""),
            target_id=data.get("target_id", ""),
            created_at=data.get("created_at", ""),
            expires_at=data.get("expires_at", ""),
            sequence_number=data.get("sequence_number", 0),
            idempotency_key=data.get("idempotency_key", ""),
            nonce=data.get("nonce", ""),
            payload=data.get("payload", {}),
            signature=data.get("signature", ""),
        )

    @classmethod
    def from_json(cls, data: str | bytes) -> ProtocolEnvelope:
        """Parse from JSON string or bytes."""
        if isinstance(data, bytes):
            data = data.decode("utf-8")
        return cls.from_dict(json.loads(data))

    # Signing

    def signing_string(self) -> str:
        """Build the string used for HMAC signing."""
        payload_json = deterministic_json(self.payload)
        signed_fields = {
            "schema_version": self.schema_version,
            "protocol_version": self.protocol_version,
            "message_id": self.message_id,
            "message_type": self.message_type,
            "source_id": self.source_id,
            "target_id": self.target_id,
            "created_at": self.created_at,
            "expires_at": self.expires_at,
            "sequence_number": self.sequence_number,
            "idempotency_key": self.idempotency_key,
            "nonce": self.nonce,
            "payload": payload_json,
        }
        return deterministic_json(signed_fields)

    def sign(self, signing_key: str) -> None:
        """Sign this envelope with HMAC-SHA256."""
        msg = self.signing_string()
        self.signature = hmac.new(
            signing_key.encode("utf-8"), msg.encode("utf-8"), hashlib.sha256
        ).hexdigest()

    def verify(self, signing_key: str) -> bool:
        """Verify the HMAC signature. Constant-time comparison."""
        if not self.signature:
            return False
        msg = self.signing_string()
        expected = hmac.new(
            signing_key.encode("utf-8"), msg.encode("utf-8"), hashlib.sha256
        ).hexdigest()
        return hmac.compare_digest(expected, self.signature)

    # Validation

    def is_valid(self) -> tuple[bool, str]:
        """
        Validate envelope structure.
        Returns (is_valid, error_message).
        """
        if not self.schema_version:
            return False, "missing schema_version"
        if self.schema_version not in SUPPORTED_VERSIONS:
            return False, f"unsupported schema_version: {self.schema_version}"

        if not self.protocol_version:
            return False, "missing protocol_version"
        if self.protocol_version not in SUPPORTED_VERSIONS:
            return False, f"unsupported protocol_version: {self.protocol_version}"

        if not self.message_id:
            return False, "missing message_id"
        if not self.message_type:
            return False, "missing message_type"
        if self.message_type not in MESSAGE_TYPES:
            return False, f"unknown message_type: {self.message_type}"

        if not self.source_id:
            return False, "missing source_id"
        if not self.target_id:
            return False, "missing target_id"
        if not self.created_at:
            return False, "missing created_at"

        return True, ""

    def is_expired(self) -> bool:
        """Check if envelope has expired."""
        if not self.expires_at:
            return False
        return _time.utc_now_epoch() > _time.parse_iso(self.expires_at)

    # Factory methods

    @classmethod
    def response(
        cls,
        original: ProtocolEnvelope,
        message_type: str,
        payload: dict[str, Any],
        sequence_number: int = 0,
    ) -> ProtocolEnvelope:
        """Create a response envelope for a request."""
        return cls(
            protocol_version=original.protocol_version,
            message_type=message_type,
            source_id=original.target_id,
            target_id=original.source_id,
            payload=payload,
            sequence_number=sequence_number,
        )

    @classmethod
    def error(
        cls,
        original: ProtocolEnvelope,
        error_code: str,
        error_message: str,
    ) -> ProtocolEnvelope:
        """Create an error response envelope."""
        return cls.response(
            original,
            "PROTOCOL_ERROR",
            {"error_code": error_code, "error_message": error_message},
        )

    def hash_message(self) -> str:
        """Deterministic SHA-256 hash of the signed message (for dedup)."""
        return deterministic_hash(self.to_dict())

