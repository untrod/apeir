"""Credential-safe recursive serialization shared by durable subsystems."""

from __future__ import annotations

import re
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
}
_SECRET_VALUE_PATTERNS = (
    re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"),
    re.compile(r"\bAKIA[A-Z0-9]{16}\b"),
    re.compile(r"\bBearer\s+[A-Za-z0-9._~+/-]{16,}\b", re.IGNORECASE),
    re.compile(r"\beyJ[A-Za-z0-9_-]+\.eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b"),
    re.compile(
        r"(?i)(?:api[_-]?key|access[_-]?token|password|secret)=([^&\s]{8,})"
    ),
)


def redact_sensitive_data(value: Any) -> Any:
    """Return a JSON-safe copy with credential material removed."""
    if isinstance(value, Mapping):
        redacted: dict[str, Any] = {}
        for key, item in value.items():
            normalized = str(key).casefold()
            numeric_token_counter = (
                normalized == "tokens" or normalized.endswith("_tokens")
            ) and isinstance(item, (int, float))
            if (
                normalized not in _SAFE_REFERENCE_KEYS
                and not numeric_token_counter
                and any(
                    marker in normalized for marker in _SENSITIVE_MARKERS
                )
            ):
                redacted[str(key)] = REDACTED
            else:
                redacted[str(key)] = redact_sensitive_data(item)
        return redacted
    if isinstance(value, (list, tuple, set, frozenset)):
        return [redact_sensitive_data(item) for item in value]
    if isinstance(value, str) and any(
        pattern.search(value) for pattern in _SECRET_VALUE_PATTERNS
    ):
        return REDACTED
    return value


__all__ = ["REDACTED", "redact_sensitive_data"]
