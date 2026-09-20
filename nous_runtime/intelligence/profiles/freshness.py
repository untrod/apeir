"""Time decay and freshness for profile information.

Configurable expiration for: provider availability, latency, reliability,
rate limits, pricing, model capability claims, probe results.

Stale values: remain auditable, produce reduced confidence, influence
scheduler uncertainty, not silently discarded.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from nous_runtime.intelligence.profiles.models import (
    ModelProfile,
    ProfileValue,
    ProviderProfile,
    ValueProvenance,
)

# default TTLs (seconds)

DEFAULT_TTLS: dict[str, float] = {
    "provider_availability": 300.0,     # 5 minutes
    "latency": 900.0,                    # 15 minutes
    "reliability": 3600.0,              # 1 hour
    "rate_limits": 86400.0,             # 24 hours
    "pricing": 604800.0,                # 7 days
    "capability_claim": 2592000.0,      # 30 days
    "probe_result": 604800.0,           # 7 days
    "static_identity": float("inf"),    # never expires
}


def apply_staleness(profile_value: ProfileValue, *, category: str = "latency", now: datetime | None = None) -> ProfileValue:
    """Check and apply staleness to a ProfileValue.

    Returns the original if still fresh, or a new ProfileValue with
    stale=True and reduced confidence if expired.
    """
    if profile_value.stale:
        return profile_value

    if profile_value.expires_at is None:
        # No expiration set — infer from observed_at + TTL
        ttl = DEFAULT_TTLS.get(category, 3600.0)
        if ttl == float("inf") or profile_value.observed_at is None:
            return profile_value
        expires = profile_value.observed_at + timedelta(seconds=ttl)
    else:
        expires = profile_value.expires_at

    ref = now or datetime.now(timezone.utc)
    if ref <= expires:
        return profile_value

    # Stale — reduce confidence, mark, but preserve value
    return ProfileValue(
        value=profile_value.value,
        unit=profile_value.unit,
        provenance=ValueProvenance.STALE,
        confidence=profile_value.confidence * 0.5,
        observed_at=profile_value.observed_at,
        expires_at=profile_value.expires_at,
        evidence_refs=profile_value.evidence_refs,
        stale=True,
    )


def profile_staleness_report(
    profile: ModelProfile | ProviderProfile,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Generate a staleness report for a profile.

    Returns dict with per-field freshness state and overall staleness score.
    """
    ref = now or datetime.now(timezone.utc)
    fields: dict[str, dict[str, Any]] = {}
    stale_count = 0
    total_count = 0

    if isinstance(profile, ModelProfile):
        checks = [
            ("context_window", profile.context_window),
            ("max_output_tokens", profile.max_output_tokens),
            ("supports_streaming", profile.supports_streaming),
            ("supports_tool_calling", profile.supports_tool_calling),
            ("supports_structured_output", profile.supports_structured_output),
            ("quality_estimate", profile.quality_estimate),
        ]
    else:
        checks = [
            ("locality", profile.locality),
            ("privacy_level", profile.privacy_level),
            ("availability", profile.availability),
        ]

    for name, pv in checks:
        total_count += 1
        is_stale = pv.is_stale(now=ref)
        fields[name] = {
            "stale": is_stale,
            "confidence": pv.effective_confidence(now=ref),
            "observed_at": pv.observed_at.isoformat() if pv.observed_at else None,
            "expires_at": pv.expires_at.isoformat() if pv.expires_at else None,
        }
        if is_stale:
            stale_count += 1

    return {
        "profile_id": profile.model_id if isinstance(profile, ModelProfile) else profile.provider_id,
        "profile_type": "model" if isinstance(profile, ModelProfile) else "provider",
        "lifecycle": profile.lifecycle.value if isinstance(profile, ModelProfile) else "n/a",
        "checked_at": ref.isoformat(),
        "fields": fields,
        "stale_count": stale_count,
        "total_fields": total_count,
        "staleness_ratio": round(stale_count / max(total_count, 1), 3),
        "overall_fresh": stale_count == 0,
    }


def compute_confidence_decay(
    profile_value: ProfileValue,
    *,
    half_life_seconds: float = 3600.0,
    now: datetime | None = None,
) -> float:
    """Compute exponential confidence decay based on age.

    confidence(t) = confidence_initial * 0.5^(age / half_life)
    """
    if profile_value.observed_at is None:
        return profile_value.confidence

    ref = now or datetime.now(timezone.utc)
    age_seconds = (ref - profile_value.observed_at).total_seconds()
    if age_seconds <= 0:
        return profile_value.confidence

    decay_factor = 0.5 ** (age_seconds / half_life_seconds)
    return profile_value.confidence * decay_factor
