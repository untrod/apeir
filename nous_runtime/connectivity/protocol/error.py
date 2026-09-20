# -*- coding: utf-8 -*-
"""ProtocolError -structured protocol error codes."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from nous_runtime.compat import time as _time

from .serialization import redacted_serialization


# Error codes
class ErrorCode:
    OK = "OK"
    AUTH_FAILED = "AUTH_FAILED"
    VERSION_MISMATCH = "VERSION_MISMATCH"
    INVALID_MESSAGE = "INVALID_MESSAGE"
    MESSAGE_TOO_LARGE = "MESSAGE_TOO_LARGE"
    SEQUENCE_GAP = "SEQUENCE_GAP"
    RATE_LIMITED = "RATE_LIMITED"
    NODE_UNKNOWN = "NODE_UNKNOWN"
    NODE_REVOKED = "NODE_REVOKED"
    CAPABILITY_DENIED = "CAPABILITY_DENIED"
    TASK_EXPIRED = "TASK_EXPIRED"
    TASK_DUPLICATE = "TASK_DUPLICATE"
    SESSION_EXPIRED = "SESSION_EXPIRED"
    PAIRING_FAILED = "PAIRING_FAILED"
    INTERNAL_ERROR = "INTERNAL_ERROR"

    _MESSAGES = {
        OK: "Success",
        AUTH_FAILED: "Authentication failed",
        VERSION_MISMATCH: "Unsupported protocol version",
        INVALID_MESSAGE: "Message failed validation",
        MESSAGE_TOO_LARGE: "Payload exceeds size limit",
        SEQUENCE_GAP: "Missing sequence numbers",
        RATE_LIMITED: "Too many requests",
        NODE_UNKNOWN: "Node not registered",
        NODE_REVOKED: "Node credential revoked",
        CAPABILITY_DENIED: "Capability not in node allowlist",
        TASK_EXPIRED: "Task deadline passed",
        TASK_DUPLICATE: "Duplicate task (idempotency key collision)",
        SESSION_EXPIRED: "Session timed out",
        PAIRING_FAILED: "Pairing failed",
        INTERNAL_ERROR: "Internal server error",
    }

    @classmethod
    def message(cls, code: str) -> str:
        return cls._MESSAGES.get(code, "Unknown error")


@dataclass(frozen=True)
class ProtocolError:
    """Structured protocol error."""

    error_code: str
    error_message: str
    details: dict[str, Any] = field(default_factory=dict)
    original_message_id: str = ""
    timestamp: str = ""

    def __post_init__(self):
        if not self.timestamp:
            object.__setattr__(self, "timestamp", _time.utc_now())

    @classmethod
    def create(
        cls,
        error_code: str,
        details: dict[str, Any] | None = None,
        original_message_id: str = "",
    ) -> ProtocolError:
        return cls(
            error_code=error_code,
            error_message=ErrorCode.message(error_code),
            details=details or {},
            original_message_id=original_message_id,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "error_code": self.error_code,
            "error_message": self.error_message,
            "details": self.details,
            "original_message_id": self.original_message_id,
            "timestamp": self.timestamp,
        }

    def to_redacted_dict(self) -> dict[str, Any]:
        return redacted_serialization(self.to_dict())

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ProtocolError:
        return cls(
            error_code=data.get("error_code", ErrorCode.INTERNAL_ERROR),
            error_message=data.get("error_message", ""),
            details=data.get("details", {}),
            original_message_id=data.get("original_message_id", ""),
            timestamp=data.get("timestamp", ""),
        )

