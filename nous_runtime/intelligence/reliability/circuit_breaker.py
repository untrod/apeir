"""Circuit Breaker state machine — CLOSED/OPEN/HALF_OPEN/FORCED_OPEN/DISABLED.

Sliding-window metrics, consecutive-failure threshold, cooldown, half-open
probing. Deterministic clock injection for tests. Transition event persistence.
"""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

from nous_runtime.intelligence.reliability.models import (
    CircuitConfig,
    CircuitState,
    CircuitStateRecord,
    DEFAULT_CIRCUIT_CONFIG,
    FailureCategory,
    FailureSignal,
    ProviderHealthSnapshot,
    VALID_CIRCUIT_TRANSITIONS,
    snapshot_hash,
)


@dataclass
class _SlidingWindow:
    """Internal sliding window of success/failure events."""
    events: deque[tuple[float, bool, FailureCategory | None]] = field(default_factory=deque)
    window_size: int = 60

    def record(self, success: bool, category: FailureCategory | None = None) -> None:
        self.events.append((time.monotonic(), success, category))
        self._prune()

    def _prune(self) -> None:
        cutoff = time.monotonic() - self.window_size
        while self.events and self.events[0][0] < cutoff:
            self.events.popleft()

    @property
    def total(self) -> int:
        self._prune()
        return len(self.events)

    @property
    def successes(self) -> int:
        self._prune()
        return sum(1 for _, ok, _ in self.events if ok)

    @property
    def failures(self) -> int:
        self._prune()
        return sum(1 for _, ok, _ in self.events if not ok)

    @property
    def timeouts(self) -> int:
        self._prune()
        return sum(1 for _, ok, cat in self.events if not ok and cat == FailureCategory.TIMEOUT)

    @property
    def rate_limits(self) -> int:
        self._prune()
        return sum(1 for _, ok, cat in self.events if not ok and cat == FailureCategory.RATE_LIMIT)

    @property
    def failure_rate(self) -> float:
        return self.failures / max(self.total, 1)

    @property
    def timeout_rate(self) -> float:
        return self.timeouts / max(self.total, 1)

    @property
    def consecutive_failures(self) -> int:
        self._prune()
        count = 0
        for _, ok, _ in reversed(self.events):
            if ok:
                break
            count += 1
        return count


class CircuitBreaker:
    """Per-provider or per-model circuit breaker.

    Breaker key format: "{provider_id}:*" for provider-level, "{provider_id}:{model_id}" for model-level.
    """

    def __init__(
        self,
        breaker_key: str,
        config: CircuitConfig | None = None,
        *,
        _clock: Any = None,  # injection point for tests
    ) -> None:
        self.breaker_key = breaker_key
        self.config = config or DEFAULT_CIRCUIT_CONFIG
        self._clock = _clock or time
        self._state = CircuitState.CLOSED
        self._window = _SlidingWindow(window_size=self.config.sliding_window_size)
        self._opened_at: datetime | None = None
        self._half_open_at: datetime | None = None
        self._closed_at: datetime | None = None
        self._cooldown_until: datetime | None = None
        self._half_open_calls = 0
        self._half_open_successes = 0
        self._transition_history: list[CircuitStateRecord] = []

    # public API

    @property
    def state(self) -> CircuitState:
        return self._state

    @property
    def is_open(self) -> bool:
        return self._state in (CircuitState.OPEN, CircuitState.FORCED_OPEN)

    @property
    def allows_traffic(self) -> bool:
        if self._state in (CircuitState.CLOSED, CircuitState.DISABLED):
            return True
        if self._state == CircuitState.HALF_OPEN:
            return self._half_open_calls < self.config.half_open_call_limit
        return False

    @property
    def cooldown_remaining_seconds(self) -> float:
        if self._cooldown_until is None:
            return 0.0
        remaining = (self._cooldown_until - datetime.now(timezone.utc)).total_seconds()
        return max(0.0, remaining)

    def record_success(self) -> CircuitStateRecord | None:
        if (
            self._state == CircuitState.OPEN
            and self._cooldown_until
            and datetime.now(timezone.utc) >= self._cooldown_until
        ):
            return self._transition_to(CircuitState.HALF_OPEN, "cooldown expired")
        self._window.record(True)
        return self._evaluate()

    def record_failure(self, signal: FailureSignal) -> CircuitStateRecord | None:
        if signal.circuit_relevant:
            self._window.record(False, signal.category)
        return self._evaluate()

    def force_open(self, reason: str = "") -> CircuitStateRecord:
        return self._transition_to(CircuitState.FORCED_OPEN, reason)

    def force_close(self, reason: str = "") -> CircuitStateRecord:
        if self._state != CircuitState.FORCED_OPEN:
            raise ValueError(f"Cannot force_close from {self._state.value}; only FORCED_OPEN can be explicitly closed")
        return self._transition_to(CircuitState.CLOSED, reason)

    def disable(self, reason: str = "") -> CircuitStateRecord:
        return self._transition_to(CircuitState.DISABLED, reason)

    def enable(self, reason: str = "") -> CircuitStateRecord:
        if self._state != CircuitState.DISABLED:
            raise ValueError(f"Cannot enable from {self._state.value}; only DISABLED can be enabled")
        return self._transition_to(CircuitState.CLOSED, reason)

    def half_open(self, reason: str = "") -> CircuitStateRecord:
        if self._state != CircuitState.OPEN:
            raise ValueError(f"Cannot half_open from {self._state.value}; only OPEN can go to HALF_OPEN")
        return self._transition_to(CircuitState.HALF_OPEN, reason)

    def snapshot(self) -> ProviderHealthSnapshot:
        parts = self.breaker_key.split(":")
        provider_id = parts[0] if len(parts) > 0 else ""
        model_id = parts[1] if len(parts) > 1 and parts[1] != "*" else ""

        status = "ok"
        if self._state in (CircuitState.OPEN, CircuitState.FORCED_OPEN):
            status = "down"
        elif self._state == CircuitState.HALF_OPEN:
            status = "degraded"

        return ProviderHealthSnapshot(
            snapshot_id=snapshot_hash({"breaker_key": self.breaker_key, "ts": datetime.now(timezone.utc).isoformat()}),
            provider_id=provider_id,
            model_id=model_id,
            status=status,
            circuit_state=self._state,
            failure_count=self._window.failures,
            success_count=self._window.successes,
            consecutive_failures=self._window.consecutive_failures,
            failure_rate=self._window.failure_rate if self._window.total > 0 else None,
            timeout_rate=self._window.timeout_rate if self._window.total > 0 else None,
            rate_limit_count=self._window.rate_limits,
            window_size=self.config.sliding_window_size,
            sample_count=self._window.total,
            confidence=min(1.0, self._window.total / max(self.config.min_sample_count, 1)),
            snapshot_at=datetime.now(timezone.utc),
        )

    def get_history(self, limit: int = 20) -> list[CircuitStateRecord]:
        return self._transition_history[-limit:]

    # state machine

    def _evaluate(self) -> CircuitStateRecord | None:
        w = self._window
        cfg = self.config

        if self._state == CircuitState.DISABLED:
            return None
        if self._state == CircuitState.FORCED_OPEN:
            return None

        if self._state == CircuitState.CLOSED:
            # Check open conditions
            if w.total >= cfg.min_sample_count:
                if w.consecutive_failures >= cfg.consecutive_failure_threshold:
                    return self._transition_to(CircuitState.OPEN, f"consecutive_failures={w.consecutive_failures} >= {cfg.consecutive_failure_threshold}")
                if w.failure_rate >= cfg.failure_rate_threshold:
                    return self._transition_to(CircuitState.OPEN, f"failure_rate={w.failure_rate:.2f} >= {cfg.failure_rate_threshold}")
                if w.timeout_rate >= cfg.timeout_rate_threshold:
                    return self._transition_to(CircuitState.OPEN, f"timeout_rate={w.timeout_rate:.2f} >= {cfg.timeout_rate_threshold}")
                if w.rate_limits >= cfg.rate_limit_threshold:
                    return self._transition_to(CircuitState.OPEN, f"rate_limits={w.rate_limits} >= {cfg.rate_limit_threshold}")

        elif self._state == CircuitState.OPEN:
            # Check cooldown → HALF_OPEN
            if self._cooldown_until and datetime.now(timezone.utc) >= self._cooldown_until:
                return self._transition_to(CircuitState.HALF_OPEN, "cooldown expired")

        elif self._state == CircuitState.HALF_OPEN:
            self._half_open_calls += 1
            if self._window.events and not self._window.events[-1][1]:
                self._half_open_successes = 0  # reset on failure
            else:
                self._half_open_successes += 1

            if self._half_open_successes >= cfg.half_open_success_threshold:
                return self._transition_to(CircuitState.CLOSED, f"half_open_successes={self._half_open_successes} >= {cfg.half_open_success_threshold}")
            if self._window.consecutive_failures >= 1:  # any failure in HALF_OPEN
                return self._transition_to(CircuitState.OPEN, "half_open failure")

        return None

    def _transition_to(self, new_state: CircuitState, reason: str) -> CircuitStateRecord:
        if new_state == self._state:
            # No-op transition
            record = CircuitStateRecord(
                record_id=snapshot_hash({"key": self.breaker_key, "from": self._state.value, "to": new_state.value, "reason": reason}),
                breaker_key=self.breaker_key,
                state=self._state,
                previous_state=self._state,
                transition_reason=reason,
                consecutive_failures=self._window.consecutive_failures,
                failure_count=self._window.failures,
                success_count=self._window.successes,
                opened_at=self._opened_at,
                half_open_at=self._half_open_at,
                closed_at=self._closed_at,
                cooldown_until=self._cooldown_until,
                half_open_calls=self._half_open_calls,
                half_open_successes=self._half_open_successes,
            )
            return record

        if new_state not in VALID_CIRCUIT_TRANSITIONS.get(self._state, set()):
            raise ValueError(f"Illegal circuit transition: {self._state.value} -> {new_state.value}")

        previous = self._state
        self._state = new_state
        now = datetime.now(timezone.utc)

        if new_state == CircuitState.OPEN:
            self._opened_at = now
            self._cooldown_until = now + timedelta(seconds=self.config.cooldown_seconds)
            self._half_open_calls = 0
            self._half_open_successes = 0
        elif new_state == CircuitState.HALF_OPEN:
            self._half_open_at = now
            self._half_open_calls = 0
            self._half_open_successes = 0
        elif new_state == CircuitState.CLOSED:
            self._closed_at = now
            self._cooldown_until = None
            self._opened_at = None
            self._half_open_at = None
            self._half_open_calls = 0
            self._half_open_successes = 0

        record = CircuitStateRecord(
            record_id=snapshot_hash({"key": self.breaker_key, "from": previous.value, "to": new_state.value, "reason": reason}),
            breaker_key=self.breaker_key,
            state=new_state,
            previous_state=previous,
            transition_reason=reason,
            consecutive_failures=self._window.consecutive_failures,
            failure_count=self._window.failures,
            success_count=self._window.successes,
            opened_at=self._opened_at,
            half_open_at=self._half_open_at,
            closed_at=self._closed_at,
            cooldown_until=self._cooldown_until,
            half_open_calls=self._half_open_calls,
            half_open_successes=self._half_open_successes,
        )
        self._transition_history.append(record)
        return record
