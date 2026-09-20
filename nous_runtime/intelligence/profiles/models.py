"""Canonical profile models for P5.6 Model and Provider Intelligence.

Immutable, versioned, hashable, JSON-serializable dataclasses.
No secret persistence. Explicit unknown values. Deterministic field ordering.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from nous_runtime.version import __version__

from nous_runtime.schema_registry import PROFILE_SCHEMA_VERSION

# provenance states

class ValueProvenance(str, Enum):
    DECLARED = "declared"        # provider self-declared
    DISCOVERED = "discovered"    # found via discovery
    OBSERVED = "observed"        # seen in execution
    PROBED = "probed"           # verified by probe
    VERIFIED = "verified"       # independently confirmed
    INFERRED = "inferred"       # derived from other data
    UNKNOWN = "unknown"         # no information
    STALE = "stale"             # previously known, now expired


class ModelLifecycle(str, Enum):
    UNKNOWN = "unknown"
    DISCOVERED = "discovered"
    PROVISIONAL = "provisional"
    PROBING = "probing"
    VERIFIED = "verified"
    DEGRADED = "degraded"
    QUARANTINED = "quarantined"
    RETIRED = "retired"


class CapabilityState(str, Enum):
    DECLARED = "declared"
    PROBING = "probing"
    VERIFIED = "verified"
    FAILED = "failed"
    UNSUPPORTED = "unsupported"
    DEGRADED = "degraded"


# ProfileValue

@dataclass(frozen=True)
class ProfileValue:
    """Every important profile property carries provenance, confidence, and freshness."""

    value: Any
    unit: str = ""
    provenance: ValueProvenance = ValueProvenance.UNKNOWN
    confidence: float = 0.0
    observed_at: datetime | None = None
    expires_at: datetime | None = None
    evidence_refs: tuple[str, ...] = ()
    stale: bool = False

    def __post_init__(self) -> None:
        self._validate()

    def _validate(self) -> None:
        if not math.isfinite(self.confidence):
            object.__setattr__(self, "confidence", 0.0)
        elif self.confidence < 0.0:
            object.__setattr__(self, "confidence", 0.0)
        elif self.confidence > 1.0:
            object.__setattr__(self, "confidence", 1.0)
        if self.observed_at is not None and self.expires_at is not None:
            if self.expires_at < self.observed_at:
                object.__setattr__(self, "expires_at", None)

    def is_stale(self, *, now: datetime | None = None) -> bool:
        if self.stale:
            return True
        if self.expires_at is None:
            return False
        ref = now or datetime.now(timezone.utc)
        return ref > self.expires_at

    def effective_confidence(self, *, now: datetime | None = None) -> float:
        if self.is_stale(now=now):
            return self.confidence * 0.5
        return self.confidence

    def to_dict(self) -> dict[str, Any]:
        return {
            "value": self.value,
            "unit": self.unit,
            "provenance": self.provenance.value,
            "confidence": self.confidence,
            "observed_at": _fmt_ts(self.observed_at),
            "expires_at": _fmt_ts(self.expires_at),
            "evidence_refs": list(self.evidence_refs),
            "stale": self.stale,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ProfileValue":
        return cls(
            value=data.get("value"),
            unit=str(data.get("unit") or ""),
            provenance=ValueProvenance(str(data.get("provenance") or "unknown")),
            confidence=float(data.get("confidence") or 0.0),
            observed_at=_parse_ts(data.get("observed_at")),
            expires_at=_parse_ts(data.get("expires_at")),
            evidence_refs=tuple(str(r) for r in (data.get("evidence_refs") or ())),
            stale=bool(data.get("stale")),
        )


# capability models

@dataclass(frozen=True)
class CapabilityClaim:
    capability_id: str
    state: CapabilityState = CapabilityState.DECLARED
    provenance: ValueProvenance = ValueProvenance.DECLARED
    confidence: float = 0.5
    verified_at: datetime | None = None
    last_probed_at: datetime | None = None
    probe_results: tuple[str, ...] = ()  # probe_result_ids
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "capability_id": self.capability_id,
            "state": self.state.value,
            "provenance": self.provenance.value,
            "confidence": self.confidence,
            "verified_at": _fmt_ts(self.verified_at),
            "last_probed_at": _fmt_ts(self.last_probed_at),
            "probe_results": list(self.probe_results),
            "metadata": _sanitize(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CapabilityClaim":
        return cls(
            capability_id=str(data.get("capability_id") or ""),
            state=CapabilityState(str(data.get("state") or "declared")),
            provenance=ValueProvenance(str(data.get("provenance") or "declared")),
            confidence=float(data.get("confidence") or 0.5),
            verified_at=_parse_ts(data.get("verified_at")),
            last_probed_at=_parse_ts(data.get("last_probed_at")),
            probe_results=tuple(str(r) for r in (data.get("probe_results") or ())),
            metadata=dict(data.get("metadata") or {}),
        )


@dataclass(frozen=True)
class CapabilityObservation:
    observation_id: str
    capability_id: str
    model_id: str = ""
    provider_id: str = ""
    observed: bool = False
    success: bool | None = None
    error_category: str = ""
    latency_ms: float | None = None
    token_usage: dict[str, int] = field(default_factory=dict)
    output_valid: bool | None = None
    observed_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "observation_id": self.observation_id,
            "capability_id": self.capability_id,
            "model_id": self.model_id,
            "provider_id": self.provider_id,
            "observed": self.observed,
            "success": self.success,
            "error_category": self.error_category,
            "latency_ms": self.latency_ms,
            "token_usage": dict(self.token_usage),
            "output_valid": self.output_valid,
            "observed_at": _fmt_ts(self.observed_at),
            "metadata": _sanitize(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CapabilityObservation":
        return cls(
            observation_id=str(data.get("observation_id") or ""),
            capability_id=str(data.get("capability_id") or ""),
            model_id=str(data.get("model_id") or ""),
            provider_id=str(data.get("provider_id") or ""),
            observed=bool(data.get("observed")),
            success=data.get("success") if isinstance(data.get("success"), bool) else None,
            error_category=str(data.get("error_category") or ""),
            latency_ms=float(data["latency_ms"]) if data.get("latency_ms") is not None else None,
            token_usage=dict(data.get("token_usage") or {}),
            output_valid=data.get("output_valid") if isinstance(data.get("output_valid"), bool) else None,
            observed_at=_parse_ts(data.get("observed_at")) or datetime.now(timezone.utc),
            metadata=dict(data.get("metadata") or {}),
        )


# performance observation

@dataclass(frozen=True)
class PerformanceObservation:
    observation_id: str
    model_id: str = ""
    provider_id: str = ""
    capability_id: str = ""
    success: bool = True
    failure_category: str = ""
    latency_ms: float = 0.0
    time_to_first_token_ms: float | None = None
    token_usage: dict[str, int] = field(default_factory=dict)
    cost: float | None = None
    output_validated: bool | None = None
    task_type: str = ""
    fallback_used: bool = False
    retry_count: int = 0
    observed_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "observation_id": self.observation_id,
            "model_id": self.model_id,
            "provider_id": self.provider_id,
            "capability_id": self.capability_id,
            "success": self.success,
            "failure_category": self.failure_category,
            "latency_ms": self.latency_ms,
            "time_to_first_token_ms": self.time_to_first_token_ms,
            "token_usage": dict(self.token_usage),
            "cost": self.cost,
            "output_validated": self.output_validated,
            "task_type": self.task_type,
            "fallback_used": self.fallback_used,
            "retry_count": self.retry_count,
            "observed_at": _fmt_ts(self.observed_at),
            "metadata": _sanitize(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "PerformanceObservation":
        return cls(
            observation_id=str(data.get("observation_id") or ""),
            model_id=str(data.get("model_id") or ""),
            provider_id=str(data.get("provider_id") or ""),
            capability_id=str(data.get("capability_id") or ""),
            success=bool(data.get("success", True)),
            failure_category=str(data.get("failure_category") or ""),
            latency_ms=float(data.get("latency_ms") or 0.0),
            time_to_first_token_ms=float(data["time_to_first_token_ms"]) if data.get("time_to_first_token_ms") is not None else None,
            token_usage=dict(data.get("token_usage") or {}),
            cost=float(data["cost"]) if data.get("cost") is not None else None,
            output_validated=data.get("output_validated") if isinstance(data.get("output_validated"), bool) else None,
            task_type=str(data.get("task_type") or ""),
            fallback_used=bool(data.get("fallback_used")),
            retry_count=int(data.get("retry_count") or 0),
            observed_at=_parse_ts(data.get("observed_at")) or datetime.now(timezone.utc),
            metadata=dict(data.get("metadata") or {}),
        )


# aggregate performance

@dataclass(frozen=True)
class PerformanceAggregate:
    sample_count: int = 0
    p50_ms: float | None = None
    p95_ms: float | None = None
    p99_ms: float | None = None
    success_rate: float | None = None
    validation_rate: float | None = None
    ema_latency_ms: float | None = None
    window_start: datetime | None = None
    window_end: datetime | None = None
    freshness: float = 1.0  # 1.0 = fresh, 0.0 = fully decayed
    confidence: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "sample_count": self.sample_count,
            "p50_ms": self.p50_ms,
            "p95_ms": self.p95_ms,
            "p99_ms": self.p99_ms,
            "success_rate": self.success_rate,
            "validation_rate": self.validation_rate,
            "ema_latency_ms": self.ema_latency_ms,
            "window_start": _fmt_ts(self.window_start),
            "window_end": _fmt_ts(self.window_end),
            "freshness": self.freshness,
            "confidence": self.confidence,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "PerformanceAggregate":
        return cls(
            sample_count=int(data.get("sample_count") or 0),
            p50_ms=float(data["p50_ms"]) if data.get("p50_ms") is not None else None,
            p95_ms=float(data["p95_ms"]) if data.get("p95_ms") is not None else None,
            p99_ms=float(data["p99_ms"]) if data.get("p99_ms") is not None else None,
            success_rate=float(data["success_rate"]) if data.get("success_rate") is not None else None,
            validation_rate=float(data["validation_rate"]) if data.get("validation_rate") is not None else None,
            ema_latency_ms=float(data["ema_latency_ms"]) if data.get("ema_latency_ms") is not None else None,
            window_start=_parse_ts(data.get("window_start")),
            window_end=_parse_ts(data.get("window_end")),
            freshness=float(data.get("freshness") or 1.0),
            confidence=float(data.get("confidence") or 0.0),
        )


# pricing and rate limits

@dataclass(frozen=True)
class PricingProfile:
    input_cost_per_1k: ProfileValue = field(default_factory=lambda: ProfileValue(None))
    output_cost_per_1k: ProfileValue = field(default_factory=lambda: ProfileValue(None))
    currency: str = "USD"
    free_tier: bool = False
    observed_at: datetime | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "input_cost_per_1k": self.input_cost_per_1k.to_dict(),
            "output_cost_per_1k": self.output_cost_per_1k.to_dict(),
            "currency": self.currency,
            "free_tier": self.free_tier,
            "observed_at": _fmt_ts(self.observed_at),
            "metadata": _sanitize(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "PricingProfile":
        return cls(
            input_cost_per_1k=ProfileValue.from_dict(data.get("input_cost_per_1k") or {}),
            output_cost_per_1k=ProfileValue.from_dict(data.get("output_cost_per_1k") or {}),
            currency=str(data.get("currency") or "USD"),
            free_tier=bool(data.get("free_tier")),
            observed_at=_parse_ts(data.get("observed_at")),
            metadata=dict(data.get("metadata") or {}),
        )


@dataclass(frozen=True)
class RateLimitProfile:
    requests_per_minute: ProfileValue = field(default_factory=lambda: ProfileValue(None))
    tokens_per_minute: ProfileValue = field(default_factory=lambda: ProfileValue(None))
    concurrent_requests: ProfileValue = field(default_factory=lambda: ProfileValue(None))
    observed_at: datetime | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "requests_per_minute": self.requests_per_minute.to_dict(),
            "tokens_per_minute": self.tokens_per_minute.to_dict(),
            "concurrent_requests": self.concurrent_requests.to_dict(),
            "observed_at": _fmt_ts(self.observed_at),
            "metadata": _sanitize(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "RateLimitProfile":
        return cls(
            requests_per_minute=ProfileValue.from_dict(data.get("requests_per_minute") or {}),
            tokens_per_minute=ProfileValue.from_dict(data.get("tokens_per_minute") or {}),
            concurrent_requests=ProfileValue.from_dict(data.get("concurrent_requests") or {}),
            observed_at=_parse_ts(data.get("observed_at")),
            metadata=dict(data.get("metadata") or {}),
        )


# core profiles

@dataclass(frozen=True)
class ModelProfile:
    model_id: str
    schema_version: str = PROFILE_SCHEMA_VERSION
    runtime_version: str = __version__
    display_name: str = ""
    provider_family: str = ""
    lifecycle: ModelLifecycle = ModelLifecycle.UNKNOWN
    context_window: ProfileValue = field(default_factory=lambda: ProfileValue(None, unit="tokens"))
    max_output_tokens: ProfileValue = field(default_factory=lambda: ProfileValue(None, unit="tokens"))
    input_modalities: tuple[str, ...] = ()
    output_modalities: tuple[str, ...] = ()
    supports_streaming: ProfileValue = field(default_factory=lambda: ProfileValue(None))
    supports_tool_calling: ProfileValue = field(default_factory=lambda: ProfileValue(None))
    supports_structured_output: ProfileValue = field(default_factory=lambda: ProfileValue(None))
    supports_embedding: ProfileValue = field(default_factory=lambda: ProfileValue(None))
    capability_claims: tuple[CapabilityClaim, ...] = ()
    pricing: PricingProfile = field(default_factory=PricingProfile)
    rate_limits: RateLimitProfile = field(default_factory=RateLimitProfile)
    performance: PerformanceAggregate = field(default_factory=PerformanceAggregate)
    quality_estimate: ProfileValue = field(default_factory=lambda: ProfileValue(None))
    discovered_at: datetime | None = None
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    profile_hash: str = ""
    discovery_source: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.profile_hash:
            object.__setattr__(self, "profile_hash", self._compute_hash())

    def _compute_hash(self) -> str:
        raw = json.dumps({
            "model_id": self.model_id,
            "schema_version": self.schema_version,
            "lifecycle": self.lifecycle.value,
            "context_window": self.context_window.to_dict(),
            "capability_claims": [c.to_dict() for c in self.capability_claims],
        }, ensure_ascii=False, sort_keys=True, default=str)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]

    @property
    def is_provisional(self) -> bool:
        return self.lifecycle in (ModelLifecycle.UNKNOWN, ModelLifecycle.DISCOVERED, ModelLifecycle.PROVISIONAL)

    @property
    def is_verified(self) -> bool:
        return self.lifecycle == ModelLifecycle.VERIFIED

    @property
    def is_degraded_or_worse(self) -> bool:
        return self.lifecycle in (ModelLifecycle.DEGRADED, ModelLifecycle.QUARANTINED, ModelLifecycle.RETIRED)

    def verified_capabilities(self) -> tuple[str, ...]:
        return tuple(c.capability_id for c in self.capability_claims if c.state == CapabilityState.VERIFIED)

    def declared_capabilities(self) -> tuple[str, ...]:
        return tuple(c.capability_id for c in self.capability_claims)

    def to_dict(self) -> dict[str, Any]:
        return {
            "model_id": self.model_id,
            "schema_version": self.schema_version,
            "runtime_version": self.runtime_version,
            "display_name": self.display_name,
            "provider_family": self.provider_family,
            "lifecycle": self.lifecycle.value,
            "context_window": self.context_window.to_dict(),
            "max_output_tokens": self.max_output_tokens.to_dict(),
            "input_modalities": list(self.input_modalities),
            "output_modalities": list(self.output_modalities),
            "supports_streaming": self.supports_streaming.to_dict(),
            "supports_tool_calling": self.supports_tool_calling.to_dict(),
            "supports_structured_output": self.supports_structured_output.to_dict(),
            "supports_embedding": self.supports_embedding.to_dict(),
            "capability_claims": [c.to_dict() for c in self.capability_claims],
            "pricing": self.pricing.to_dict(),
            "rate_limits": self.rate_limits.to_dict(),
            "performance": self.performance.to_dict(),
            "quality_estimate": self.quality_estimate.to_dict(),
            "discovered_at": _fmt_ts(self.discovered_at),
            "updated_at": _fmt_ts(self.updated_at),
            "profile_hash": self.profile_hash,
            "discovery_source": self.discovery_source,
            "metadata": _sanitize(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ModelProfile":
        return cls(
            model_id=str(data.get("model_id") or ""),
            schema_version=str(data.get("schema_version") or PROFILE_SCHEMA_VERSION),
            runtime_version=str(data.get("runtime_version") or ""),
            display_name=str(data.get("display_name") or ""),
            provider_family=str(data.get("provider_family") or ""),
            lifecycle=_safe_enum(ModelLifecycle, data.get("lifecycle"), ModelLifecycle.UNKNOWN),
            context_window=ProfileValue.from_dict(data.get("context_window") or {}),
            max_output_tokens=ProfileValue.from_dict(data.get("max_output_tokens") or {}),
            input_modalities=tuple(str(m) for m in (data.get("input_modalities") or ())),
            output_modalities=tuple(str(m) for m in (data.get("output_modalities") or ())),
            supports_streaming=ProfileValue.from_dict(data.get("supports_streaming") or {}),
            supports_tool_calling=ProfileValue.from_dict(data.get("supports_tool_calling") or {}),
            supports_structured_output=ProfileValue.from_dict(data.get("supports_structured_output") or {}),
            supports_embedding=ProfileValue.from_dict(data.get("supports_embedding") or {}),
            capability_claims=tuple(CapabilityClaim.from_dict(c) for c in (data.get("capability_claims") or ())),
            pricing=PricingProfile.from_dict(data.get("pricing") or {}),
            rate_limits=RateLimitProfile.from_dict(data.get("rate_limits") or {}),
            performance=PerformanceAggregate.from_dict(data.get("performance") or {}),
            quality_estimate=ProfileValue.from_dict(data.get("quality_estimate") or {}),
            discovered_at=_parse_ts(data.get("discovered_at")),
            updated_at=_parse_ts(data.get("updated_at")) or datetime.now(timezone.utc),
            profile_hash=str(data.get("profile_hash") or ""),
            discovery_source=str(data.get("discovery_source") or ""),
            metadata=dict(data.get("metadata") or {}),
        )


@dataclass(frozen=True)
class ProviderProfile:
    provider_id: str
    schema_version: str = PROFILE_SCHEMA_VERSION
    runtime_version: str = __version__
    display_name: str = ""
    provider_type: str = ""  # e.g., "cloud", "local", "edge", "hybrid"
    models: tuple[str, ...] = ()  # model_ids
    locality: ProfileValue = field(default_factory=lambda: ProfileValue(None))  # geographic/political region
    privacy_level: ProfileValue = field(default_factory=lambda: ProfileValue(None))  # data handling: "local", "regional", "cloud"
    data_residency: ProfileValue = field(default_factory=lambda: ProfileValue(None))
    availability: ProfileValue = field(default_factory=lambda: ProfileValue(None))
    health_status: str = "unknown"  # "ok", "degraded", "down", "unknown"
    performance: PerformanceAggregate = field(default_factory=PerformanceAggregate)
    last_health_check: datetime | None = None
    discovered_at: datetime | None = None
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    profile_hash: str = ""
    discovery_source: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.profile_hash:
            object.__setattr__(self, "profile_hash", self._compute_hash())

    def _compute_hash(self) -> str:
        raw = json.dumps({
            "provider_id": self.provider_id,
            "schema_version": self.schema_version,
            "provider_type": self.provider_type,
            "models": sorted(self.models),
            "locality": self.locality.to_dict(),
        }, ensure_ascii=False, sort_keys=True, default=str)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider_id": self.provider_id,
            "schema_version": self.schema_version,
            "runtime_version": self.runtime_version,
            "display_name": self.display_name,
            "provider_type": self.provider_type,
            "models": list(self.models),
            "locality": self.locality.to_dict(),
            "privacy_level": self.privacy_level.to_dict(),
            "data_residency": self.data_residency.to_dict(),
            "availability": self.availability.to_dict(),
            "health_status": self.health_status,
            "performance": self.performance.to_dict(),
            "last_health_check": _fmt_ts(self.last_health_check),
            "discovered_at": _fmt_ts(self.discovered_at),
            "updated_at": _fmt_ts(self.updated_at),
            "profile_hash": self.profile_hash,
            "discovery_source": self.discovery_source,
            "metadata": _sanitize(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ProviderProfile":
        return cls(
            provider_id=str(data.get("provider_id") or ""),
            schema_version=str(data.get("schema_version") or PROFILE_SCHEMA_VERSION),
            runtime_version=str(data.get("runtime_version") or ""),
            display_name=str(data.get("display_name") or ""),
            provider_type=str(data.get("provider_type") or ""),
            models=tuple(str(m) for m in (data.get("models") or ())),
            locality=ProfileValue.from_dict(data.get("locality") or {}),
            privacy_level=ProfileValue.from_dict(data.get("privacy_level") or {}),
            data_residency=ProfileValue.from_dict(data.get("data_residency") or {}),
            availability=ProfileValue.from_dict(data.get("availability") or {}),
            health_status=str(data.get("health_status") or "unknown"),
            performance=PerformanceAggregate.from_dict(data.get("performance") or {}),
            last_health_check=_parse_ts(data.get("last_health_check")),
            discovered_at=_parse_ts(data.get("discovered_at")),
            updated_at=_parse_ts(data.get("updated_at")) or datetime.now(timezone.utc),
            profile_hash=str(data.get("profile_hash") or ""),
            discovery_source=str(data.get("discovery_source") or ""),
            metadata=dict(data.get("metadata") or {}),
        )


# snapshots and discovery

@dataclass(frozen=True)
class ProfileSnapshot:
    snapshot_id: str
    model_id: str = ""
    provider_id: str = ""
    snapshot_type: str = ""  # "model" or "provider"
    data: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    profile_hash: str = ""
    schema_version: str = PROFILE_SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "snapshot_id": self.snapshot_id,
            "model_id": self.model_id,
            "provider_id": self.provider_id,
            "snapshot_type": self.snapshot_type,
            "data": _sanitize(self.data),
            "created_at": _fmt_ts(self.created_at),
            "profile_hash": self.profile_hash,
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ProfileSnapshot":
        return cls(
            snapshot_id=str(data.get("snapshot_id") or ""),
            model_id=str(data.get("model_id") or ""),
            provider_id=str(data.get("provider_id") or ""),
            snapshot_type=str(data.get("snapshot_type") or ""),
            data=dict(data.get("data") or {}),
            created_at=_parse_ts(data.get("created_at")) or datetime.now(timezone.utc),
            profile_hash=str(data.get("profile_hash") or ""),
            schema_version=str(data.get("schema_version") or PROFILE_SCHEMA_VERSION),
        )


@dataclass(frozen=True)
class DiscoveryRecord:
    discovery_id: str
    source: str = ""  # "static_config", "provider_registry", "api_endpoint", "local_manifest"
    model_id: str = ""
    provider_id: str = ""
    endpoint: str = ""  # redacted
    discovered_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    raw_metadata: dict[str, Any] = field(default_factory=dict)
    error: str = ""
    schema_version: str = PROFILE_SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "discovery_id": self.discovery_id,
            "source": self.source,
            "model_id": self.model_id,
            "provider_id": self.provider_id,
            "endpoint": "[redacted]" if self.endpoint else "",
            "discovered_at": _fmt_ts(self.discovered_at),
            "raw_metadata": _sanitize(self.raw_metadata),
            "error": self.error,
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "DiscoveryRecord":
        return cls(
            discovery_id=str(data.get("discovery_id") or ""),
            source=str(data.get("source") or ""),
            model_id=str(data.get("model_id") or ""),
            provider_id=str(data.get("provider_id") or ""),
            endpoint=str(data.get("endpoint") or ""),
            discovered_at=_parse_ts(data.get("discovered_at")) or datetime.now(timezone.utc),
            raw_metadata=dict(data.get("raw_metadata") or {}),
            error=str(data.get("error") or ""),
            schema_version=str(data.get("schema_version") or PROFILE_SCHEMA_VERSION),
        )


# probe models

@dataclass(frozen=True)
class ProbeDefinition:
    probe_id: str
    probe_type: str  # "basic_completion", "structured_output", "tool_call", "streaming", "context_boundary", "embedding", "multimodal", "timeout_behavior"
    capability_id: str
    input_payload: dict[str, Any] = field(default_factory=dict)
    timeout_ms: int = 30000
    max_cost: float = 0.0
    max_tokens: int = 256
    risk_level: str = "low"  # "low", "medium", "high"
    expected_output_schema: dict[str, Any] = field(default_factory=dict)
    validation_rules: tuple[str, ...] = ()  # e.g., "valid_json", "has_tool_call", "non_empty"
    schema_version: str = PROFILE_SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "probe_id": self.probe_id,
            "probe_type": self.probe_type,
            "capability_id": self.capability_id,
            "input_payload": self.input_payload,
            "timeout_ms": self.timeout_ms,
            "max_cost": self.max_cost,
            "max_tokens": self.max_tokens,
            "risk_level": self.risk_level,
            "expected_output_schema": self.expected_output_schema,
            "validation_rules": list(self.validation_rules),
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ProbeDefinition":
        return cls(
            probe_id=str(data.get("probe_id") or ""),
            probe_type=str(data.get("probe_type") or ""),
            capability_id=str(data.get("capability_id") or ""),
            input_payload=dict(data.get("input_payload") or {}),
            timeout_ms=int(data.get("timeout_ms") or 30000),
            max_cost=float(data.get("max_cost") or 0.0),
            max_tokens=int(data.get("max_tokens") or 256),
            risk_level=str(data.get("risk_level") or "low"),
            expected_output_schema=dict(data.get("expected_output_schema") or {}),
            validation_rules=tuple(str(r) for r in (data.get("validation_rules") or ())),
            schema_version=str(data.get("schema_version") or PROFILE_SCHEMA_VERSION),
        )


@dataclass(frozen=True)
class ProbeResult:
    result_id: str
    probe_id: str
    model_id: str = ""
    provider_id: str = ""
    capability_id: str = ""
    success: bool = False
    output_valid: bool | None = None
    latency_ms: float = 0.0
    token_usage: dict[str, int] = field(default_factory=dict)
    cost: float | None = None
    error: str = ""
    error_category: str = ""  # "provider_failure", "capability_failure", "timeout", "budget_exceeded"
    output_summary: str = ""
    probed_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    schema_version: str = PROFILE_SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "result_id": self.result_id,
            "probe_id": self.probe_id,
            "model_id": self.model_id,
            "provider_id": self.provider_id,
            "capability_id": self.capability_id,
            "success": self.success,
            "output_valid": self.output_valid,
            "latency_ms": self.latency_ms,
            "token_usage": dict(self.token_usage),
            "cost": self.cost,
            "error": self.error,
            "error_category": self.error_category,
            "output_summary": self.output_summary,
            "probed_at": _fmt_ts(self.probed_at),
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ProbeResult":
        return cls(
            result_id=str(data.get("result_id") or ""),
            probe_id=str(data.get("probe_id") or ""),
            model_id=str(data.get("model_id") or ""),
            provider_id=str(data.get("provider_id") or ""),
            capability_id=str(data.get("capability_id") or ""),
            success=bool(data.get("success")),
            output_valid=data.get("output_valid") if isinstance(data.get("output_valid"), bool) else None,
            latency_ms=float(data.get("latency_ms") or 0.0),
            token_usage=dict(data.get("token_usage") or {}),
            cost=float(data["cost"]) if data.get("cost") is not None else None,
            error=str(data.get("error") or ""),
            error_category=str(data.get("error_category") or ""),
            output_summary=str(data.get("output_summary") or ""),
            probed_at=_parse_ts(data.get("probed_at")) or datetime.now(timezone.utc),
            schema_version=str(data.get("schema_version") or PROFILE_SCHEMA_VERSION),
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


def _safe_enum(enum_cls: Any, value: Any, default: Any) -> Any:
    try:
        return enum_cls(str(value or ""))
    except (ValueError, TypeError):
        return default


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
