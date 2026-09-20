"""Non-invasive state container for Runtime Foundation consumers."""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Any

from nous_runtime.core.errors import RuntimeStateError

RUNTIME_STATE_DOMAINS = ("tasks", "providers", "decisions", "memory", "artifacts")


@dataclass
class RuntimeState:
    """Thread-safe in-memory entry point for foundation state.

    This container does not replace any existing Runtime store. It provides a
    common contract that later integrations can adopt one domain at a time.
    """

    tasks: dict[str, Any] = field(default_factory=dict)
    providers: dict[str, Any] = field(default_factory=dict)
    decisions: dict[str, Any] = field(default_factory=dict)
    memory: dict[str, Any] = field(default_factory=dict)
    artifacts: dict[str, Any] = field(default_factory=dict)
    _lock: threading.RLock = field(
        default_factory=threading.RLock,
        init=False,
        repr=False,
        compare=False,
    )

    def register(self, domain: str, key: str, value: Any) -> Any:
        """Register or replace a value and return it."""
        normalized = self._normalize_domain(domain)
        identifier = self._normalize_key(key)
        with self._lock:
            getattr(self, normalized)[identifier] = value
        return value

    def get(self, domain: str, key: str, default: Any = None) -> Any:
        """Return a registered value, or ``default`` when it is absent."""
        normalized = self._normalize_domain(domain)
        identifier = self._normalize_key(key)
        with self._lock:
            return getattr(self, normalized).get(identifier, default)

    def remove(self, domain: str, key: str) -> Any:
        """Remove and return a value, or ``None`` when it is absent."""
        normalized = self._normalize_domain(domain)
        identifier = self._normalize_key(key)
        with self._lock:
            return getattr(self, normalized).pop(identifier, None)

    @staticmethod
    def _normalize_domain(domain: str) -> str:
        normalized = str(domain or "").strip().lower()
        if normalized not in RUNTIME_STATE_DOMAINS:
            choices = ", ".join(RUNTIME_STATE_DOMAINS)
            raise RuntimeStateError(
                f"unknown Runtime state domain '{domain}'; expected one of: {choices}"
            )
        return normalized

    @staticmethod
    def _normalize_key(key: str) -> str:
        normalized = str(key or "").strip()
        if not normalized:
            raise RuntimeStateError("Runtime state key is required")
        return normalized


__all__ = ["RUNTIME_STATE_DOMAINS", "RuntimeState"]
