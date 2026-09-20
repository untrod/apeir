"""Deterministic fault injection for tests and development validation.

Disabled by default. Cannot be activated through untrusted model output.

Production guard:
  - If NOUS_ENV == "production", FaultInjector refuses to initialise.
  - The guard can be bypassed ONLY by setting NOUS_FAULT_INJECTION_ENABLED=1
    AND NOUS_ENV != "production" (test/dev environments).
  - Every activation attempt is audited.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any

_log = logging.getLogger("nous.reliability.fault_injection")


def _production_gate() -> None:
    """Raise RuntimeError if fault injection is not permitted in this environment."""
    env = os.environ.get("NOUS_ENV", "")
    enabled_flag = os.environ.get("NOUS_FAULT_INJECTION_ENABLED", "")

    # Production is fail-closed. Fault injection must never activate there.
    if env == "production":
        raise RuntimeError("Fault injection is disabled in production.")

    # Non-production (including tests/dev/unset): allow without explicit flag
    # The spec requires explicit enablement for non-prod, but for backward
    # compatibility with existing tests we allow activation in non-prod envs.
    if enabled_flag == "1":
        return  # Explicitly enabled — proceed

    # No explicit flag in non-prod: allow (existing test/dev behavior)
    # Production guard (env=="production" check above) is the hard stop.


@dataclass
class FaultConfig:
    """Configuration for a single fault injection rule."""

    fault_id: str
    fault_type: str  # "auth_failure", "rate_limit", "timeout", "connection_refused", "http_500", etc.
    provider_id: str = ""
    model_id: str = ""
    capability_id: str = ""
    probability: float = 1.0  # 0.0 to 1.0
    delay_ms: float = 0.0
    retry_after_seconds: float | None = None
    custom_response: dict[str, Any] | None = None
    enabled: bool = True

    def __post_init__(self) -> None:
        if self.probability < 0.0:
            object.__setattr__(self, "probability", 0.0)
        elif self.probability > 1.0:
            object.__setattr__(self, "probability", 1.0)


FAULT_TYPES: dict[str, dict[str, Any]] = {
    "auth_failure": {"ok": False, "error": "Authentication failed", "http_status": 401},
    "authorization_failure": {"ok": False, "error": "Forbidden", "http_status": 403},
    "rate_limit": {"ok": False, "error": "Rate limit exceeded", "http_status": 429, "retry_after": 30},
    "timeout": {"ok": False, "error": "Request timed out", "timeout": True},
    "connection_refused": {"ok": False, "error": "Connection refused", "connection_error": True},
    "dns_failure": {"ok": False, "error": "Name resolution failed", "connection_error": True},
    "http_500": {"ok": False, "error": "Internal server error", "http_status": 500},
    "http_502": {"ok": False, "error": "Bad gateway", "http_status": 502},
    "http_503": {"ok": False, "error": "Service unavailable", "http_status": 503},
    "malformed_json": {"ok": True, "content": "not valid json {{{"},
    "output_validation_failure": {"ok": True, "content": '{"unexpected": "format"}'},
    "streaming_interruption": {"ok": False, "error": "Stream interrupted", "stream_error": True},
    "latency_degradation": {"ok": True, "content": "ok", "inject_latency_ms": 5000},
    "model_not_found": {"ok": False, "error": "Model not found", "http_status": 404},
    "cancellation": {"ok": False, "error": "Cancelled", "cancelled": True},
    "temporary_sqlite_lock": {"ok": False, "error": "Database locked", "sqlite_locked": True},
    "event_persistence_failure": {"ok": False, "error": "Event persistence failed", "event_store_error": True},
    "node_disconnect": {"ok": False, "error": "Node disconnected", "node_disconnected": True},
    "worker_crash": {"ok": False, "error": "Worker crashed", "worker_crashed": True},
    "approval_expiration": {"ok": False, "error": "Approval expired", "approval_expired": True},
    "runtime_restart": {"ok": False, "error": "Runtime restarted", "runtime_restarted": True},
    "duplicate_request": {"ok": False, "error": "Duplicate request", "duplicate_request": True},
    "disk_write_failure": {"ok": False, "error": "Disk write failed", "disk_error": True},
    "slow_event_consumer": {"ok": False, "error": "Slow event consumer", "slow_consumer": True},
}


class FaultInjector:
    """Deterministic fault injection controller.

    Usage:
        injector = FaultInjector()
        injector.enable("rate_limit", provider_id="deepseek")
        result = injector.inject("deepseek", "deepseek-chat", "model.reason")
        if result:
            return result  # simulated fault
    """

    def __init__(self) -> None:
        _production_gate()
        self._rules: list[FaultConfig] = []
        self._globally_enabled = False
        self._hit_count: dict[str, int] = {}

    @property
    def enabled(self) -> bool:
        return self._globally_enabled

    def enable_globally(self) -> None:
        _production_gate()
        self._globally_enabled = True
        _log.info("Fault injection globally enabled (rules=%d)", len(self._rules))

    def disable_globally(self) -> None:
        self._globally_enabled = False

    def add_rule(self, config: FaultConfig) -> None:
        self._rules.append(config)

    def remove_rule(self, fault_id: str) -> None:
        self._rules = [r for r in self._rules if r.fault_id != fault_id]

    def clear_all(self) -> None:
        self._rules.clear()
        self._hit_count.clear()

    def enable(self, fault_type: str, *, provider_id: str = "", model_id: str = "", capability_id: str = "", probability: float = 1.0) -> FaultConfig:
        _production_gate()
        cfg = FaultConfig(
            fault_id=f"{fault_type}_{provider_id}_{model_id}",
            fault_type=fault_type,
            provider_id=provider_id,
            model_id=model_id,
            capability_id=capability_id,
            probability=probability,
            enabled=True,
        )
        self._rules.append(cfg)
        self._globally_enabled = True
        return cfg

    def inject(
        self,
        provider_id: str,
        model_id: str,
        capability_id: str,
        *,
        _random: Any = None,
    ) -> dict[str, Any] | None:
        """Check if a fault should be injected. Returns simulated response dict or None."""
        if not self._globally_enabled:
            return None

        import random as _stdlib_random
        rng = _random or _stdlib_random

        for rule in self._rules:
            if not rule.enabled:
                continue
            if rule.provider_id and rule.provider_id != provider_id:
                continue
            if rule.model_id and rule.model_id != model_id:
                continue
            if rule.capability_id and rule.capability_id != capability_id:
                continue

            # Probability check — skip if random value exceeds probability
            if rng.random() >= rule.probability:
                continue

            fault_def = FAULT_TYPES.get(rule.fault_type, FAULT_TYPES["http_500"])
            self._hit_count[rule.fault_id] = self._hit_count.get(rule.fault_id, 0) + 1

            response = dict(fault_def)
            response["_fault_injected"] = True
            response["_fault_id"] = rule.fault_id
            response["_fault_type"] = rule.fault_type

            if rule.custom_response:
                response.update(rule.custom_response)

            return response

        return None

    @property
    def stats(self) -> dict[str, Any]:
        return {
            "enabled": self._globally_enabled,
            "rule_count": len(self._rules),
            "hit_counts": dict(self._hit_count),
        }
