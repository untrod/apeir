"""Credential-safe recursive serialization shared by durable subsystems."""

from __future__ import annotations

import re
import logging
import threading
import traceback
from collections.abc import Mapping
from typing import Any


REDACTED = "<REDACTED>"
_SENSITIVE_MARKERS = (
    "api_key",
    "apikey",
    "access_token",
    "auth_token",
    "authorization",
    "cookie",
    "credential",
    "password",
    "private_key",
    "secret",
    "session_token",
    "signing_key",
    "token",
)
_SAFE_REFERENCE_KEYS = {
    "authorization_context",
    "credential_env",
    "credential_ref",
    "token_disclosed",
    "token_length",
    "secret_handle",
    "secret_handles",
    "credential_lease_id",
    "credential_lease_ids",
    "authorization_id",
    "authorization_context_id",
}

# Protected matcher memory, never serialized into Runtime evidence. Values remain
# registered for late logs/errors after a lease closes; clearing them would leak.
_known_values: set[str] = set()
_value_lock = threading.RLock()
_logging_installed = False


def contains_sensitive_value(value: str | bytes) -> bool:
    with _value_lock:
        return any(
            (secret.encode() if isinstance(value, bytes) else secret) in value
            for secret in _known_values
        )


def sensitive_overlap_bytes() -> int:
    """Overlap required to scan streamed content without exporting matchers."""
    with _value_lock:
        return max((len(secret.encode()) for secret in _known_values), default=1) - 1


def redact_sensitive_text(value: str) -> str:
    with _value_lock:
        for secret in sorted(_known_values, key=len, reverse=True):
            value = value.replace(secret, REDACTED)
    if any(pattern.search(value) for pattern in _SECRET_VALUE_PATTERNS):
        return REDACTED
    return value


def _sanitize_record(record: logging.LogRecord) -> None:
    record.msg = redact_sensitive_text(record.getMessage())
    record.args = ()
    if record.exc_info:
        record.exc_text = redact_sensitive_text(
            "".join(traceback.format_exception(*record.exc_info))
        )
        record.exc_info = None
    for key, item in tuple(record.__dict__.items()):
        if isinstance(item, (str, dict, list, tuple)):
            record.__dict__[key] = redact_sensitive_data(item)


def register_sensitive_value(value: str) -> None:
    """Register resolved material inside the protected credential boundary."""
    global _logging_installed
    if not value:
        raise ValueError("Secret material is empty")
    with _value_lock:
        _known_values.add(value)
        if _logging_installed:
            return
        factory = logging.getLogRecordFactory()
        handle = logging.Handler.handle

        def safe_factory(*args, **kwargs):
            record = factory(*args, **kwargs)
            _sanitize_record(record)
            return record

        def safe_handle(handler, record):
            # Extra fields are attached after the LogRecord factory runs.
            _sanitize_record(record)
            return handle(handler, record)

        logging.setLogRecordFactory(safe_factory)
        logging.Handler.handle = safe_handle
        _logging_installed = True


_SECRET_VALUE_PATTERNS = (
    re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"),
    re.compile(r"\bAKIA[A-Z0-9]{16}\b"),
    re.compile(r"\bBearer\s+[A-Za-z0-9._~+/-]{16,}\b", re.IGNORECASE),
    re.compile(r"\beyJ[A-Za-z0-9_-]+\.eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b"),
    re.compile(r"(?i)(?:api[_-]?key|access[_-]?token|password|secret)=([^&\s]{8,})"),
)


def redact_sensitive_data(value: Any) -> Any:
    """Return a JSON-safe copy with credential material removed."""
    if isinstance(value, Mapping):
        redacted: dict[str, Any] = {}
        for key, item in value.items():
            safe_key = redact_sensitive_text(str(key))
            normalized = safe_key.casefold()
            numeric_token_counter = (
                normalized == "tokens" or normalized.endswith("_tokens")
            ) and isinstance(item, (int, float))
            if (
                normalized not in _SAFE_REFERENCE_KEYS
                and not numeric_token_counter
                and any(marker in normalized for marker in _SENSITIVE_MARKERS)
            ):
                redacted[safe_key] = REDACTED
            else:
                redacted[safe_key] = redact_sensitive_data(item)
        return redacted
    if isinstance(value, (list, tuple, set, frozenset)):
        return [redact_sensitive_data(item) for item in value]
    if isinstance(value, str):
        return redact_sensitive_text(value)
    if isinstance(value, bytes) and contains_sensitive_value(value):
        return REDACTED
    if getattr(value, "_sensitive_execution_context", False):
        return REDACTED
    return value


__all__ = ["REDACTED", "redact_sensitive_data"]
