# -*- coding: utf-8 -*-
"""
Unified error codes for the Nous Runtime.

Every operation in the Runtime returns a deterministic error code rather
than relying on exception type alone. This enables reliable retry logic,
circuit breaker decisions, and audit trail consistency.

Usage:
    from nous_runtime.kernel.error_codes import ErrorCode, NousResult

    result = some_operation()
    if result.code == ErrorCode.OK:
        ...
    elif result.code == ErrorCode.TIMEOUT:
        ...  # retry
    elif result.code == ErrorCode.PERMISSION_DENIED:
        ...  # escalate
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, ClassVar, Generic, TypeVar

T = TypeVar("T")


class ErrorCode(str, Enum):
    """Canonical error codes for all Nous Runtime operations."""

    # Success
    OK = "OK"
    ACCEPTED = "ACCEPTED"                # Queued but not yet complete
    PARTIAL = "PARTIAL"                   # Some parts succeeded

    # Client errors (4xx-class)
    INVALID_ARGUMENT = "INVALID_ARGUMENT"
    NOT_FOUND = "NOT_FOUND"
    ALREADY_EXISTS = "ALREADY_EXISTS"
    PERMISSION_DENIED = "PERMISSION_DENIED"
    UNAUTHENTICATED = "UNAUTHENTICATED"
    QUOTA_EXCEEDED = "QUOTA_EXCEEDED"
    BUDGET_EXCEEDED = "BUDGET_EXCEEDED"
    RATE_LIMITED = "RATE_LIMITED"
    CANCELLED = "CANCELLED"
    INVALID_STATE = "INVALID_STATE"       # Invalid transition

    # Server / provider errors (5xx-class)
    INTERNAL = "INTERNAL"
    UNAVAILABLE = "UNAVAILABLE"
    TIMEOUT = "TIMEOUT"
    OVERLOADED = "OVERLOADED"
    DEGRADED = "DEGRADED"
    CIRCUIT_OPEN = "CIRCUIT_OPEN"

    # Model-specific errors
    MODEL_UNAVAILABLE = "MODEL_UNAVAILABLE"
    MODEL_TIMEOUT = "MODEL_TIMEOUT"
    MODEL_REFUSED = "MODEL_REFUSED"       # Safety refusal
    MODEL_INVALID_OUTPUT = "MODEL_INVALID_OUTPUT"
    MODEL_CONTEXT_OVERFLOW = "MODEL_CONTEXT_OVERFLOW"

    # Node / network errors
    NODE_OFFLINE = "NODE_OFFLINE"
    NODE_UNREACHABLE = "NODE_UNREACHABLE"
    NODE_REVOKED = "NODE_REVOKED"
    NODE_DEGRADED = "NODE_DEGRADED"
    CONNECTION_LOST = "CONNECTION_LOST"
    HEARTBEAT_MISSED = "HEARTBEAT_MISSED"

    # Task / execution errors
    TASK_FAILED = "TASK_FAILED"
    VERIFICATION_FAILED = "VERIFICATION_FAILED"
    APPROVAL_DENIED = "APPROVAL_DENIED"
    APPROVAL_TIMEOUT = "APPROVAL_TIMEOUT"
    RECOVERY_FAILED = "RECOVERY_FAILED"
    ROLLBACK_FAILED = "ROLLBACK_FAILED"

    # Data errors
    DATA_CORRUPTED = "DATA_CORRUPTED"
    MIGRATION_FAILED = "MIGRATION_FAILED"
    CHECKPOINT_CORRUPTED = "CHECKPOINT_CORRUPTED"

    # Unknown
    UNKNOWN = "UNKNOWN"


# Retry hints

RETRYABLE_CODES: frozenset[ErrorCode] = frozenset({
    ErrorCode.TIMEOUT,
    ErrorCode.UNAVAILABLE,
    ErrorCode.OVERLOADED,
    ErrorCode.CIRCUIT_OPEN,
    ErrorCode.MODEL_UNAVAILABLE,
    ErrorCode.MODEL_TIMEOUT,
    ErrorCode.NODE_UNREACHABLE,
    ErrorCode.CONNECTION_LOST,
    ErrorCode.RATE_LIMITED,
})


def is_retryable(code: ErrorCode) -> bool:
    """Return True if the error code suggests a retry might succeed."""
    return code in RETRYABLE_CODES


# Severity classification

_ERROR_SEVERITY: dict[ErrorCode, int] = {
    ErrorCode.OK: 0,
    ErrorCode.ACCEPTED: 0,
    ErrorCode.PARTIAL: 1,
    ErrorCode.CANCELLED: 0,
    ErrorCode.INVALID_ARGUMENT: 1,
    ErrorCode.NOT_FOUND: 1,
    ErrorCode.ALREADY_EXISTS: 1,
    ErrorCode.PERMISSION_DENIED: 2,
    ErrorCode.UNAUTHENTICATED: 2,
    ErrorCode.QUOTA_EXCEEDED: 2,
    ErrorCode.BUDGET_EXCEEDED: 2,
    ErrorCode.RATE_LIMITED: 2,
    ErrorCode.INVALID_STATE: 2,
    ErrorCode.INTERNAL: 3,
    ErrorCode.UNAVAILABLE: 3,
    ErrorCode.TIMEOUT: 2,
    ErrorCode.OVERLOADED: 2,
    ErrorCode.DEGRADED: 2,
    ErrorCode.CIRCUIT_OPEN: 2,
    ErrorCode.MODEL_UNAVAILABLE: 2,
    ErrorCode.MODEL_TIMEOUT: 2,
    ErrorCode.MODEL_REFUSED: 2,
    ErrorCode.MODEL_INVALID_OUTPUT: 2,
    ErrorCode.MODEL_CONTEXT_OVERFLOW: 2,
    ErrorCode.NODE_OFFLINE: 2,
    ErrorCode.NODE_UNREACHABLE: 2,
    ErrorCode.NODE_REVOKED: 3,
    ErrorCode.NODE_DEGRADED: 2,
    ErrorCode.CONNECTION_LOST: 2,
    ErrorCode.HEARTBEAT_MISSED: 1,
    ErrorCode.TASK_FAILED: 2,
    ErrorCode.VERIFICATION_FAILED: 2,
    ErrorCode.APPROVAL_DENIED: 2,
    ErrorCode.APPROVAL_TIMEOUT: 2,
    ErrorCode.RECOVERY_FAILED: 3,
    ErrorCode.ROLLBACK_FAILED: 3,
    ErrorCode.DATA_CORRUPTED: 3,
    ErrorCode.MIGRATION_FAILED: 3,
    ErrorCode.CHECKPOINT_CORRUPTED: 3,
    ErrorCode.UNKNOWN: 2,
}


def severity(code: ErrorCode) -> int:
    """Return severity 0 (ok) to 3 (critical)."""
    return _ERROR_SEVERITY.get(code, 2)


# Result type

class _ResultOkDescriptor:
    """Expose ``NousResult.ok(value)`` and ``result.ok`` compatibly."""

    def __get__(self, instance, owner):
        if instance is None:
            def create(value=None, message: str = ""):
                return owner(code=ErrorCode.OK, value=value, message=message)
            return create
        return instance.code == ErrorCode.OK


@dataclass
class NousResult(Generic[T]):
    """A typed result carrying an error code and optional diagnostic data.

    Success:
        NousResult.ok(value)
    Failure:
        NousResult.err(ErrorCode.TIMEOUT, message="...")
    """

    code: ErrorCode
    value: T | None = None
    message: str = ""
    details: dict[str, Any] = field(default_factory=dict)
    retry_after_ms: int = 0
    trace_id: str = ""


    @classmethod
    def err(cls, code: ErrorCode, message: str = "",
            details: dict[str, Any] | None = None,
            retry_after_ms: int = 0) -> "NousResult[T]":
        return cls(
            code=code,
            message=message,
            details=details or {},
            retry_after_ms=retry_after_ms,
        )

    ok: ClassVar[_ResultOkDescriptor] = _ResultOkDescriptor()


    @property
    def retryable(self) -> bool:
        return is_retryable(self.code)

    def unwrap(self) -> T:
        """Return the value or raise if error."""
        if not self.ok:
            raise ValueError(f"NousResult error [{self.code.value}]: {self.message}")
        if self.value is None:
            raise ValueError("NousResult has no value")
        return self.value
