"""Reliability models for P5.7 — failure classification, circuit breaker, retry, fallback.

Immutable, versioned, hashable, JSON-serializable. No secrets. Explicit unknowns.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


from nous_runtime.schema_registry import RELIABILITY_SCHEMA_VERSION

# failure taxonomy

class FailureCategory(str, Enum):
    AUTHENTICATION = "authentication"
    AUTHORIZATION = "authorization"
    RATE_LIMIT = "rate_limit"
    TIMEOUT = "timeout"
    CONNECTION = "connection"
    SERVER_ERROR = "server_error"
    MALFORMED_RESPONSE = "malformed_response"
    OUTPUT_VALIDATION = "output_validation"
    CAPABILITY_UNSUPPORTED = "capability_unsupported"
    USER_INPUT = "user_input"
    POLICY_REJECTION = "policy_rejection"
    BUDGET_EXCEEDED = "budget_exceeded"
    RUNTIME_INTERNAL = "runtime_internal"
    CANCELLED = "cancelled"
    UNKNOWN = "unknown"


NON_RETRYABLE_CATEGORIES: frozenset[FailureCategory] = frozenset({
    FailureCategory.AUTHENTICATION,
    FailureCategory.AUTHORIZATION,
    FailureCategory.USER_INPUT,
    FailureCategory.POLICY_REJECTION,
    FailureCategory.CAPABILITY_UNSUPPORTED,
    FailureCategory.BUDGET_EXCEEDED,
    FailureCategory.CANCELLED,
    FailureCategory.OUTPUT_VALIDATION,
})


# circuit breaker states

class CircuitState(str, Enum):
    CLOSED = "closed"          # normal operation
    OPEN = "open"              # failing, no traffic allowed
    HALF_OPEN = "half_open"    # probing with limited traffic
    FORCED_OPEN = "forced_open"  # manually opened, requires explicit close
    DISABLED = "disabled"      # breaker bypassed


# Legal transitions
VALID_CIRCUIT_TRANSITIONS: dict[CircuitState, set[CircuitState]] = {
    CircuitState.CLOSED: {CircuitState.OPEN, CircuitState.FORCED_OPEN, CircuitState.DISABLED},
    CircuitState.OPEN: {CircuitState.HALF_OPEN, CircuitState.FORCED_OPEN, CircuitState.DISABLED},
    CircuitState.HALF_OPEN: {CircuitState.CLOSED, CircuitState.OPEN, CircuitState.FORCED_OPEN, CircuitState.DISABLED},
    CircuitState.FORCED_OPEN: {CircuitState.CLOSED, CircuitState.DISABLED},  # only trusted control
    CircuitState.DISABLED: {CircuitState.CLOSED, CircuitState.OPEN, CircuitState.HALF_OPEN, CircuitState.FORCED_OPEN},
}


# failure signal

@dataclass(frozen=True)
class FailureSignal:
    signal_id: str
    provider_id: str = ""
    model_id: str = ""
    capability_id: str = ""
    category: FailureCategory = FailureCategory.UNKNOWN
    provider_attributable: bool = True
    model_attributable: bool = False
    retryable: bool = False
    circuit_relevant: bool = True
    confidence: float = 1.0
    explanation: str = ""
    evidence: dict[str, Any] = field(default_factory=dict)
    occurred_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    schema_version: str = RELIABILITY_SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "signal_id": self.signal_id,
            "provider_id": self.provider_id,
            "model_id": self.model_id,
            "capability_id": self.capability_id,
            "category": self.category.value,
            "provider_attributable": self.provider_attributable,
            "model_attributable": self.model_attributable,
            "retryable": self.retryable,
            "circuit_relevant": self.circuit_relevant,
            "confidence": self.confidence,
            "explanation": self.explanation,
            "evidence": _sanitize(self.evidence),
            "occurred_at": _fmt_ts(self.occurred_at),
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "FailureSignal":
        return cls(
            signal_id=str(data.get("signal_id") or ""),
            provider_id=str(data.get("provider_id") or ""),
            model_id=str(data.get("model_id") or ""),
            capability_id=str(data.get("capability_id") or ""),
            category=FailureCategory(str(data.get("category") or "unknown")),
            provider_attributable=bool(data.get("provider_attributable", True)),
            model_attributable=bool(data.get("model_attributable", False)),
            retryable=bool(data.get("retryable", False)),
            circuit_relevant=bool(data.get("circuit_relevant", True)),
            confidence=float(data.get("confidence") or 1.0),
            explanation=str(data.get("explanation") or ""),
            evidence=dict(data.get("evidence") or {}),
            occurred_at=_parse_ts(data.get("occurred_at")) or datetime.now(timezone.utc),
            schema_version=str(data.get("schema_version") or RELIABILITY_SCHEMA_VERSION),
        )


# provider execution result

@dataclass(frozen=True)
class ProviderExecutionResult:
    execution_id: str
    success: bool = False
    provider_id: str = ""
    model_id: str = ""
    capability_id: str = ""
    failure: FailureSignal | None = None
    latency_ms: float = 0.0
    time_to_first_token_ms: float | None = None
    token_usage: dict[str, int] = field(default_factory=dict)
    cost: float | None = None
    provider_error_code: str = ""
    http_status: int | None = None
    retry_metadata: dict[str, Any] = field(default_factory=dict)
    validation_result: bool | None = None
    response_id: str = ""
    idempotency_key: str = ""
    occurred_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    schema_version: str = RELIABILITY_SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "execution_id": self.execution_id,
            "success": self.success,
            "provider_id": self.provider_id,
            "model_id": self.model_id,
            "capability_id": self.capability_id,
            "failure": self.failure.to_dict() if self.failure else None,
            "latency_ms": self.latency_ms,
            "time_to_first_token_ms": self.time_to_first_token_ms,
            "token_usage": dict(self.token_usage),
            "cost": self.cost,
            "provider_error_code": self.provider_error_code,
            "http_status": self.http_status,
            "retry_metadata": _sanitize(self.retry_metadata),
            "validation_result": self.validation_result,
            "response_id": self.response_id,
            "idempotency_key": self.idempotency_key,
            "occurred_at": _fmt_ts(self.occurred_at),
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ProviderExecutionResult":
        return cls(
            execution_id=str(data.get("execution_id") or ""),
            success=bool(data.get("success")),
            provider_id=str(data.get("provider_id") or ""),
            model_id=str(data.get("model_id") or ""),
            capability_id=str(data.get("capability_id") or ""),
            failure=FailureSignal.from_dict(data["failure"]) if data.get("failure") else None,
            latency_ms=float(data.get("latency_ms") or 0.0),
            time_to_first_token_ms=float(data["time_to_first_token_ms"]) if data.get("time_to_first_token_ms") is not None else None,
            token_usage=dict(data.get("token_usage") or {}),
            cost=float(data["cost"]) if data.get("cost") is not None else None,
            provider_error_code=str(data.get("provider_error_code") or ""),
            http_status=int(data["http_status"]) if data.get("http_status") is not None else None,
            retry_metadata=dict(data.get("retry_metadata") or {}),
            validation_result=data.get("validation_result") if isinstance(data.get("validation_result"), bool) else None,
            response_id=str(data.get("response_id") or ""),
            idempotency_key=str(data.get("idempotency_key") or ""),
            occurred_at=_parse_ts(data.get("occurred_at")) or datetime.now(timezone.utc),
            schema_version=str(data.get("schema_version") or RELIABILITY_SCHEMA_VERSION),
        )


# retry models

@dataclass(frozen=True)
class RetryPolicy:
    policy_id: str
    max_attempts: int = 3
    max_cumulative_delay_ms: float = 60000.0
    max_additional_cost: float = 0.0
    max_additional_tokens: int = 0
    allowed_categories: tuple[FailureCategory, ...] = ()
    base_backoff_ms: float = 1000.0
    max_backoff_ms: float = 30000.0
    backoff_multiplier: float = 2.0
    jitter_ratio: float = 0.1
    respect_retry_after: bool = True
    schema_version: str = RELIABILITY_SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "policy_id": self.policy_id,
            "max_attempts": self.max_attempts,
            "max_cumulative_delay_ms": self.max_cumulative_delay_ms,
            "max_additional_cost": self.max_additional_cost,
            "max_additional_tokens": self.max_additional_tokens,
            "allowed_categories": [c.value for c in self.allowed_categories],
            "base_backoff_ms": self.base_backoff_ms,
            "max_backoff_ms": self.max_backoff_ms,
            "backoff_multiplier": self.backoff_multiplier,
            "jitter_ratio": self.jitter_ratio,
            "respect_retry_after": self.respect_retry_after,
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "RetryPolicy":
        return cls(
            policy_id=str(data.get("policy_id") or ""),
            max_attempts=int(data.get("max_attempts") or 3),
            max_cumulative_delay_ms=float(data.get("max_cumulative_delay_ms") or 60000.0),
            max_additional_cost=float(data.get("max_additional_cost") or 0.0),
            max_additional_tokens=int(data.get("max_additional_tokens") or 0),
            allowed_categories=tuple(FailureCategory(c) for c in (data.get("allowed_categories") or ())),
            base_backoff_ms=float(data.get("base_backoff_ms") or 1000.0),
            max_backoff_ms=float(data.get("max_backoff_ms") or 30000.0),
            backoff_multiplier=float(data.get("backoff_multiplier") or 2.0),
            jitter_ratio=float(data.get("jitter_ratio") or 0.1),
            respect_retry_after=bool(data.get("respect_retry_after", True)),
            schema_version=str(data.get("schema_version") or RELIABILITY_SCHEMA_VERSION),
        )


DEFAULT_RETRY_POLICY = RetryPolicy(
    policy_id="default",
    max_attempts=3,
    max_cumulative_delay_ms=60000.0,
    allowed_categories=(
        FailureCategory.TIMEOUT,
        FailureCategory.CONNECTION,
        FailureCategory.SERVER_ERROR,
        FailureCategory.RATE_LIMIT,
    ),
)


@dataclass(frozen=True)
class RetryAttempt:
    attempt_id: str
    policy_id: str = ""
    execution_id: str = ""
    attempt_number: int = 0
    delay_ms: float = 0.0
    success: bool = False
    failure: FailureSignal | None = None
    occurred_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    schema_version: str = RELIABILITY_SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "attempt_id": self.attempt_id,
            "policy_id": self.policy_id,
            "execution_id": self.execution_id,
            "attempt_number": self.attempt_number,
            "delay_ms": self.delay_ms,
            "success": self.success,
            "failure": self.failure.to_dict() if self.failure else None,
            "occurred_at": _fmt_ts(self.occurred_at),
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "RetryAttempt":
        return cls(
            attempt_id=str(data.get("attempt_id") or ""),
            policy_id=str(data.get("policy_id") or ""),
            execution_id=str(data.get("execution_id") or ""),
            attempt_number=int(data.get("attempt_number") or 0),
            delay_ms=float(data.get("delay_ms") or 0.0),
            success=bool(data.get("success")),
            failure=FailureSignal.from_dict(data["failure"]) if data.get("failure") else None,
            occurred_at=_parse_ts(data.get("occurred_at")) or datetime.now(timezone.utc),
            schema_version=str(data.get("schema_version") or RELIABILITY_SCHEMA_VERSION),
        )


# fallback

@dataclass(frozen=True)
class FallbackExecution:
    fallback_id: str
    original_execution_id: str = ""
    depth: int = 0
    strategy: str = ""  # "same_model", "alternate_model", "alternate_provider", "degraded", "local", "escalate", "terminate"
    provider_id: str = ""
    model_id: str = ""
    capability_id: str = ""
    success: bool = False
    lost_capabilities: tuple[str, ...] = ()
    privacy_changed: bool = False
    locality_changed: bool = False
    cost_delta: float | None = None
    latency_delta_ms: float | None = None
    occurred_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    schema_version: str = RELIABILITY_SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "fallback_id": self.fallback_id,
            "original_execution_id": self.original_execution_id,
            "depth": self.depth,
            "strategy": self.strategy,
            "provider_id": self.provider_id,
            "model_id": self.model_id,
            "capability_id": self.capability_id,
            "success": self.success,
            "lost_capabilities": list(self.lost_capabilities),
            "privacy_changed": self.privacy_changed,
            "locality_changed": self.locality_changed,
            "cost_delta": self.cost_delta,
            "latency_delta_ms": self.latency_delta_ms,
            "occurred_at": _fmt_ts(self.occurred_at),
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "FallbackExecution":
        return cls(
            fallback_id=str(data.get("fallback_id") or ""),
            original_execution_id=str(data.get("original_execution_id") or ""),
            depth=int(data.get("depth") or 0),
            strategy=str(data.get("strategy") or ""),
            provider_id=str(data.get("provider_id") or ""),
            model_id=str(data.get("model_id") or ""),
            capability_id=str(data.get("capability_id") or ""),
            success=bool(data.get("success")),
            lost_capabilities=tuple(str(c) for c in (data.get("lost_capabilities") or ())),
            privacy_changed=bool(data.get("privacy_changed")),
            locality_changed=bool(data.get("locality_changed")),
            cost_delta=float(data["cost_delta"]) if data.get("cost_delta") is not None else None,
            latency_delta_ms=float(data["latency_delta_ms"]) if data.get("latency_delta_ms") is not None else None,
            occurred_at=_parse_ts(data.get("occurred_at")) or datetime.now(timezone.utc),
            schema_version=str(data.get("schema_version") or RELIABILITY_SCHEMA_VERSION),
        )


# health snapshot

@dataclass(frozen=True)
class ProviderHealthSnapshot:
    snapshot_id: str
    provider_id: str = ""
    model_id: str = ""
    status: str = "unknown"  # "ok", "degraded", "down"
    circuit_state: CircuitState = CircuitState.CLOSED
    failure_count: int = 0
    success_count: int = 0
    consecutive_failures: int = 0
    failure_rate: float | None = None
    timeout_rate: float | None = None
    rate_limit_count: int = 0
    latency_p50_ms: float | None = None
    latency_p95_ms: float | None = None
    window_size: int = 60
    sample_count: int = 0
    confidence: float = 0.0
    freshness: float = 1.0
    snapshot_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    schema_version: str = RELIABILITY_SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "snapshot_id": self.snapshot_id,
            "provider_id": self.provider_id,
            "model_id": self.model_id,
            "status": self.status,
            "circuit_state": self.circuit_state.value,
            "failure_count": self.failure_count,
            "success_count": self.success_count,
            "consecutive_failures": self.consecutive_failures,
            "failure_rate": self.failure_rate,
            "timeout_rate": self.timeout_rate,
            "rate_limit_count": self.rate_limit_count,
            "latency_p50_ms": self.latency_p50_ms,
            "latency_p95_ms": self.latency_p95_ms,
            "window_size": self.window_size,
            "sample_count": self.sample_count,
            "confidence": self.confidence,
            "freshness": self.freshness,
            "snapshot_at": _fmt_ts(self.snapshot_at),
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ProviderHealthSnapshot":
        return cls(
            snapshot_id=str(data.get("snapshot_id") or ""),
            provider_id=str(data.get("provider_id") or ""),
            model_id=str(data.get("model_id") or ""),
            status=str(data.get("status") or "unknown"),
            circuit_state=CircuitState(str(data.get("circuit_state") or "closed")),
            failure_count=int(data.get("failure_count") or 0),
            success_count=int(data.get("success_count") or 0),
            consecutive_failures=int(data.get("consecutive_failures") or 0),
            failure_rate=float(data["failure_rate"]) if data.get("failure_rate") is not None else None,
            timeout_rate=float(data["timeout_rate"]) if data.get("timeout_rate") is not None else None,
            rate_limit_count=int(data.get("rate_limit_count") or 0),
            latency_p50_ms=float(data["latency_p50_ms"]) if data.get("latency_p50_ms") is not None else None,
            latency_p95_ms=float(data["latency_p95_ms"]) if data.get("latency_p95_ms") is not None else None,
            window_size=int(data.get("window_size") or 60),
            sample_count=int(data.get("sample_count") or 0),
            confidence=float(data.get("confidence") or 0.0),
            freshness=float(data.get("freshness") or 1.0),
            snapshot_at=_parse_ts(data.get("snapshot_at")) or datetime.now(timezone.utc),
            schema_version=str(data.get("schema_version") or RELIABILITY_SCHEMA_VERSION),
        )


# circuit config and state record

@dataclass(frozen=True)
class CircuitConfig:
    config_id: str = "default"
    consecutive_failure_threshold: int = 5
    failure_rate_threshold: float = 0.5
    timeout_rate_threshold: float = 0.3
    rate_limit_threshold: int = 3
    min_sample_count: int = 10
    cooldown_seconds: float = 30.0
    half_open_call_limit: int = 1
    half_open_success_threshold: int = 2
    sliding_window_size: int = 60
    schema_version: str = RELIABILITY_SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "config_id": self.config_id,
            "consecutive_failure_threshold": self.consecutive_failure_threshold,
            "failure_rate_threshold": self.failure_rate_threshold,
            "timeout_rate_threshold": self.timeout_rate_threshold,
            "rate_limit_threshold": self.rate_limit_threshold,
            "min_sample_count": self.min_sample_count,
            "cooldown_seconds": self.cooldown_seconds,
            "half_open_call_limit": self.half_open_call_limit,
            "half_open_success_threshold": self.half_open_success_threshold,
            "sliding_window_size": self.sliding_window_size,
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CircuitConfig":
        return cls(
            config_id=str(data.get("config_id") or "default"),
            consecutive_failure_threshold=int(data.get("consecutive_failure_threshold") or 5),
            failure_rate_threshold=float(data.get("failure_rate_threshold") or 0.5),
            timeout_rate_threshold=float(data.get("timeout_rate_threshold") or 0.3),
            rate_limit_threshold=int(data.get("rate_limit_threshold") or 3),
            min_sample_count=int(data.get("min_sample_count") or 10),
            cooldown_seconds=float(data.get("cooldown_seconds") or 30.0),
            half_open_call_limit=int(data.get("half_open_call_limit") or 1),
            half_open_success_threshold=int(data.get("half_open_success_threshold") or 2),
            sliding_window_size=int(data.get("sliding_window_size") or 60),
            schema_version=str(data.get("schema_version") or RELIABILITY_SCHEMA_VERSION),
        )


DEFAULT_CIRCUIT_CONFIG = CircuitConfig()


@dataclass(frozen=True)
class CircuitStateRecord:
    record_id: str
    breaker_key: str = ""  # "{provider_id}:{model_id}" or "{provider_id}:*"
    state: CircuitState = CircuitState.CLOSED
    previous_state: CircuitState = CircuitState.CLOSED
    transition_reason: str = ""
    consecutive_failures: int = 0
    failure_count: int = 0
    success_count: int = 0
    opened_at: datetime | None = None
    half_open_at: datetime | None = None
    closed_at: datetime | None = None
    cooldown_until: datetime | None = None
    half_open_calls: int = 0
    half_open_successes: int = 0
    transitioned_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    schema_version: str = RELIABILITY_SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "record_id": self.record_id,
            "breaker_key": self.breaker_key,
            "state": self.state.value,
            "previous_state": self.previous_state.value,
            "transition_reason": self.transition_reason,
            "consecutive_failures": self.consecutive_failures,
            "failure_count": self.failure_count,
            "success_count": self.success_count,
            "opened_at": _fmt_ts(self.opened_at),
            "half_open_at": _fmt_ts(self.half_open_at),
            "closed_at": _fmt_ts(self.closed_at),
            "cooldown_until": _fmt_ts(self.cooldown_until),
            "half_open_calls": self.half_open_calls,
            "half_open_successes": self.half_open_successes,
            "transitioned_at": _fmt_ts(self.transitioned_at),
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CircuitStateRecord":
        return cls(
            record_id=str(data.get("record_id") or ""),
            breaker_key=str(data.get("breaker_key") or ""),
            state=CircuitState(str(data.get("state") or "closed")),
            previous_state=CircuitState(str(data.get("previous_state") or "closed")),
            transition_reason=str(data.get("transition_reason") or ""),
            consecutive_failures=int(data.get("consecutive_failures") or 0),
            failure_count=int(data.get("failure_count") or 0),
            success_count=int(data.get("success_count") or 0),
            opened_at=_parse_ts(data.get("opened_at")),
            half_open_at=_parse_ts(data.get("half_open_at")),
            closed_at=_parse_ts(data.get("closed_at")),
            cooldown_until=_parse_ts(data.get("cooldown_until")),
            half_open_calls=int(data.get("half_open_calls") or 0),
            half_open_successes=int(data.get("half_open_successes") or 0),
            transitioned_at=_parse_ts(data.get("transitioned_at")) or datetime.now(timezone.utc),
            schema_version=str(data.get("schema_version") or RELIABILITY_SCHEMA_VERSION),
        )


# reliability window

@dataclass(frozen=True)
class ReliabilityWindow:
    window_id: str
    provider_id: str = ""
    model_id: str = ""
    total_calls: int = 0
    successes: int = 0
    failures: int = 0
    timeouts: int = 0
    rate_limits: int = 0
    consecutive_failures: int = 0
    window_start: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    window_end: datetime | None = None
    schema_version: str = RELIABILITY_SCHEMA_VERSION

    @property
    def failure_rate(self) -> float:
        return self.failures / max(self.total_calls, 1)

    @property
    def success_rate(self) -> float:
        return self.successes / max(self.total_calls, 1)

    def to_dict(self) -> dict[str, Any]:
        return {
            "window_id": self.window_id,
            "provider_id": self.provider_id,
            "model_id": self.model_id,
            "total_calls": self.total_calls,
            "successes": self.successes,
            "failures": self.failures,
            "timeouts": self.timeouts,
            "rate_limits": self.rate_limits,
            "consecutive_failures": self.consecutive_failures,
            "window_start": _fmt_ts(self.window_start),
            "window_end": _fmt_ts(self.window_end),
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ReliabilityWindow":
        return cls(
            window_id=str(data.get("window_id") or ""),
            provider_id=str(data.get("provider_id") or ""),
            model_id=str(data.get("model_id") or ""),
            total_calls=int(data.get("total_calls") or 0),
            successes=int(data.get("successes") or 0),
            failures=int(data.get("failures") or 0),
            timeouts=int(data.get("timeouts") or 0),
            rate_limits=int(data.get("rate_limits") or 0),
            consecutive_failures=int(data.get("consecutive_failures") or 0),
            window_start=_parse_ts(data.get("window_start")) or datetime.now(timezone.utc),
            window_end=_parse_ts(data.get("window_end")),
            schema_version=str(data.get("schema_version") or RELIABILITY_SCHEMA_VERSION),
        )


# helpers

def snapshot_hash(data: dict[str, Any]) -> str:
    raw = json.dumps(_sanitize(data), ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


SENSITIVE_KEYS = {"api_key", "authorization", "cookie", "password", "private_key", "secret", "token"}


def _sanitize(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): "[redacted]" if _is_sensitive(str(k)) else _sanitize(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_sanitize(v) for v in value]
    if isinstance(value, tuple):
        return tuple(_sanitize(v) for v in value)
    return value


def _is_sensitive(key: str) -> bool:
    return any(part in key.lower() for part in SENSITIVE_KEYS)


def _fmt_ts(dt: datetime | None) -> str:
    if dt is None:
        return ""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _parse_ts(value: Any) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        dt = value
    else:
        text = str(value)
        if text.endswith("Z"):
            text = f"{text[:-1]}+00:00"
        try:
            dt = datetime.fromisoformat(text)
        except (ValueError, TypeError):
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)
