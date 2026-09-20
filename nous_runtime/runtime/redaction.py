"""Compatibility wrapper for Runtime evidence redaction."""

from nous_runtime.core.redaction import REDACTED, redact_sensitive_data

redact_runtime_evidence = redact_sensitive_data

__all__ = ["REDACTED", "redact_runtime_evidence"]
