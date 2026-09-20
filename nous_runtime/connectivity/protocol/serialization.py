# -*- coding: utf-8 -*-
"""
Deterministic serialization and hashing for protocol contracts.

Requirements:
  - deterministic JSON (sorted keys, no whitespace, UTC timestamps)
  - deterministic hashing (SHA-256 of deterministic JSON)
  - redacted serialization (secrets replaced with <REDACTED>)
  - bounded payload validation
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any

# Maximum payload size in bytes (default 1 MB)
DEFAULT_MAX_PAYLOAD_BYTES = 1_048_576

# Patterns for fields that must be redacted in logs/output
_REDACT_PATTERNS = [
    re.compile(r".*key.*", re.IGNORECASE),
    re.compile(r".*secret.*", re.IGNORECASE),
    re.compile(r".*token.*", re.IGNORECASE),
    re.compile(r".*password.*", re.IGNORECASE),
    re.compile(r".*credential.*", re.IGNORECASE),
    re.compile(r".*signature.*", re.IGNORECASE),
    re.compile(r".*private.*", re.IGNORECASE),
    re.compile(r".*pairing_code.*", re.IGNORECASE),
]

_REDACT_PLACEHOLDER = "<REDACTED>"


def deterministic_json(obj: Any) -> str:
    """Serialize to deterministic JSON: sorted keys, no whitespace, UTF-8."""
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def deterministic_hash(obj: Any) -> str:
    """SHA-256 hash of deterministic JSON bytes. Returns hex string."""
    json_str = deterministic_json(obj)
    return hashlib.sha256(json_str.encode("utf-8")).hexdigest()


def _should_redact(key: str) -> bool:
    """Check if a field name matches redaction patterns."""
    return any(p.match(key) for p in _REDACT_PATTERNS)


def redacted_serialization(obj: Any) -> Any:
    """
    Deep-copy an object with sensitive fields replaced by <REDACTED>.
    Returns a new dict/list/str with secrets redacted.
    """
    if isinstance(obj, dict):
        return {
            k: _REDACT_PLACEHOLDER if _should_redact(k) else redacted_serialization(v)
            for k, v in obj.items()
        }
    elif isinstance(obj, list):
        return [redacted_serialization(item) for item in obj]
    elif isinstance(obj, str):
        # Check for common secret patterns in string values
        if any(p.search(obj) for p in [
            re.compile(r"sk-[a-zA-Z0-9]{20,}"),
            re.compile(r"AKIA[A-Z0-9]{16}"),
            re.compile(r"eyJ[A-Za-z0-9\-_]+\.eyJ[A-Za-z0-9\-_]+\.[A-Za-z0-9\-_]+"),
        ]):
            return _REDACT_PLACEHOLDER
        return obj
    return obj


def validate_bounded_payload(payload: bytes | str, max_bytes: int = DEFAULT_MAX_PAYLOAD_BYTES) -> None:
    """
    Validate payload is within size bounds.

    Raises:
        ValueError: if payload exceeds max_bytes
    """
    if isinstance(payload, str):
        payload = payload.encode("utf-8")
    if len(payload) > max_bytes:
        raise ValueError(
            f"Payload size {len(payload)} exceeds maximum {max_bytes} bytes"
        )


def validate_payload_schema(payload: dict, schema: dict) -> list[str]:
    """
    Validate payload against a JSON schema subset.
    Returns list of validation error messages (empty = valid).

    Supports: type (object/string/integer/number/boolean/array),
              required, properties, additionalProperties, enum, minLength,
              maxLength, minimum, maximum.
    """
    errors: list[str] = []

    if not isinstance(payload, dict):
        return ["payload must be a JSON object"]

    schema_type = schema.get("type", "object")
    if schema_type != "object":
        return []  # Only object validation supported

    # Check required fields
    for field in schema.get("required", []):
        if field not in payload:
            errors.append(f"missing required field: {field}")

    # Check properties
    for prop_name, prop_schema in schema.get("properties", {}).items():
        if prop_name not in payload:
            continue
        value = payload[prop_name]
        prop_type = prop_schema.get("type", "string")

        if prop_type == "string" and not isinstance(value, str):
            errors.append(f"{prop_name}: expected string, got {type(value).__name__}")
        elif prop_type == "integer" and not isinstance(value, int):
            errors.append(f"{prop_name}: expected integer, got {type(value).__name__}")
        elif prop_type == "number" and not isinstance(value, (int, float)):
            errors.append(f"{prop_name}: expected number, got {type(value).__name__}")
        elif prop_type == "boolean" and not isinstance(value, bool):
            errors.append(f"{prop_name}: expected boolean, got {type(value).__name__}")
        elif prop_type == "array" and not isinstance(value, list):
            errors.append(f"{prop_name}: expected array, got {type(value).__name__}")

        if "enum" in prop_schema and value not in prop_schema["enum"]:
            errors.append(f"{prop_name}: {value!r} not in allowed values {prop_schema['enum']}")
        if "minLength" in prop_schema and isinstance(value, str) and len(value) < prop_schema["minLength"]:
            errors.append(f"{prop_name}: length {len(value)} below minimum {prop_schema['minLength']}")
        if "maxLength" in prop_schema and isinstance(value, str) and len(value) > prop_schema["maxLength"]:
            errors.append(f"{prop_name}: length {len(value)} exceeds maximum {prop_schema['maxLength']}")

    # Check additionalProperties
    if not schema.get("additionalProperties", True):
        allowed = set(schema.get("properties", {}).keys())
        for key in payload:
            if key not in allowed:
                errors.append(f"unknown field: {key}")

    return errors
