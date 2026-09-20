"""Deterministic profile-to-scheduler feature mapping.

Converts ModelProfile + ProviderProfile into the metadata dictionary
the scheduler expects. Includes source profile hashes, mapping version,
no NaN/Infinity, explicit missing-value behavior.
"""

from __future__ import annotations

from typing import Any

from nous_runtime.intelligence.profiles.models import (
    ModelLifecycle,
    ModelProfile,
    ProviderProfile,
    ValueProvenance,
)

MAPPING_VERSION = "1.0"

# Dimension classification — must match scheduler
POSITIVE_DIMS = {"expected_quality", "reliability", "capability_fit", "privacy_fit", "information_gain", "reversibility"}
NEGATIVE_DIMS = {"cost", "latency", "risk", "uncertainty"}


def profiles_to_scheduler_metadata(
    model: ModelProfile | None,
    provider: ProviderProfile | None,
    *,
    required_capability: str = "",
) -> dict[str, Any]:
    """Convert profiles into the metadata dict the scheduler expects.

    Returns a dict with all keys the scheduler reads from candidate.metadata.
    Source profile hashes are included. Unknown values are explicit (None).
    Conservative defaults are applied when data is missing.
    """
    meta: dict[str, Any] = {
        "_profile_mapping_version": MAPPING_VERSION,
        "_model_profile_hash": model.profile_hash if model else "",
        "_provider_profile_hash": provider.profile_hash if provider else "",
    }

    # identity
    if model:
        meta["model"] = model.model_id
        meta["provider_family"] = model.provider_family
    if provider:
        meta["provider_id"] = provider.provider_id

    # capabilities
    if model:
        meta["capabilities"] = list(model.declared_capabilities())
        meta["tool_calling"] = _safe_bool(model.supports_tool_calling.value)
        meta["structured_output"] = _safe_bool(model.supports_structured_output.value)
        meta["modality"] = _primary_modality(model)
    elif provider:
        meta["capabilities"] = []

    # performance
    if model and model.performance.sample_count > 0:
        perf = model.performance
        meta["success_rate"] = perf.success_rate if perf.success_rate is not None else None
        meta["reliability"] = perf.success_rate if perf.success_rate is not None else None
        meta["latency_ms"] = perf.p50_ms
        meta["avg_latency_ms"] = perf.ema_latency_ms
    elif provider and provider.performance.sample_count > 0:
        perf = provider.performance
        meta["success_rate"] = perf.success_rate
        meta["latency_ms"] = perf.p50_ms

    # quality
    if model:
        q = model.quality_estimate
        meta["quality"] = q.value
        meta["expected_quality"] = q.value if q.provenance != ValueProvenance.UNKNOWN else None

    # cost
    if model:
        input_cost = model.pricing.input_cost_per_1k
        if input_cost.value is not None:
            meta["cost"] = float(input_cost.value) / 1000.0  # per-token approx

    # risk
    meta["risk"] = _lifecycle_risk(model.lifecycle if model else ModelLifecycle.UNKNOWN)

    # privacy / locality
    if provider:
        meta["local"] = provider.provider_type == "local"
        meta["privacy_fit"] = _privacy_fit(provider)
        meta["locality"] = provider.locality.value
        meta["data_residency"] = provider.data_residency.value
        meta["privacy"] = provider.privacy_level.value

    # health
    if provider:
        meta["health"] = provider.health_status
        meta["status"] = provider.health_status

    # freshness
    if model:
        meta["stale_features"] = _stale_feature_names(model)

    # lifecycle
    if model:
        meta["fallback_only"] = model.lifecycle in (ModelLifecycle.DEGRADED, ModelLifecycle.QUARANTINED)
        if model.lifecycle in (ModelLifecycle.QUARANTINED, ModelLifecycle.RETIRED):
            meta["health"] = "down"
            meta["status"] = "down"

    # uncertainty (computed by scheduler from feature values)
    meta["information_gain"] = _information_gain(model)
    meta["reversibility"] = None  # not modeled yet

    return meta  # keep None values — unknown is explicit


# helpers

def _safe_bool(value: Any) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.lower() in ("true", "1", "yes")
    return bool(value)


def _primary_modality(model: ModelProfile) -> str | None:
    if model.input_modalities:
        return model.input_modalities[0]
    return None


def _lifecycle_risk(lifecycle: ModelLifecycle) -> str:
    mapping = {
        ModelLifecycle.UNKNOWN: "high",
        ModelLifecycle.DISCOVERED: "high",
        ModelLifecycle.PROVISIONAL: "high",
        ModelLifecycle.PROBING: "medium",
        ModelLifecycle.VERIFIED: "low",
        ModelLifecycle.DEGRADED: "medium",
        ModelLifecycle.QUARANTINED: "critical",
        ModelLifecycle.RETIRED: "critical",
    }
    return mapping.get(lifecycle, "high")


def _privacy_fit(provider: ProviderProfile) -> float | None:
    pv = provider.privacy_level
    if pv.value is None:
        return None
    privacy_map = {"local": 1.0, "regional": 0.7, "cloud": 0.3, "unknown": 0.5}
    val = privacy_map.get(str(pv.value).lower(), 0.5)
    if pv.stale:
        val *= 0.7
    return val


def _stale_feature_names(model: ModelProfile) -> list[str]:
    """Determine which scheduler features should be marked stale based on profile."""
    stale: list[str] = []

    checks = [
        ("latency", model.performance, model.performance.ema_latency_ms is not None),
        ("reliability", model.performance, model.performance.success_rate is not None),
        ("cost", model.pricing.input_cost_per_1k, model.pricing.input_cost_per_1k.value is not None),
    ]
    for name, pv, has_data in checks:
        if has_data:
            if isinstance(pv, __import__("datetime").timedelta):
                continue
            try:
                if hasattr(pv, 'is_stale') and pv.is_stale():
                    stale.append(name)
            except Exception:
                pass

    # Check overall freshness
    if model.performance.freshness < 0.3:
        if "latency" not in stale:
            stale.append("latency")
        if "reliability" not in stale:
            stale.append("reliability")

    return stale


def _information_gain(model: ModelProfile | None) -> float | None:
    if model is None:
        return None
    if model.lifecycle == ModelLifecycle.VERIFIED:
        return 0.8
    if model.lifecycle == ModelLifecycle.PROVISIONAL:
        return 0.3
    if model.performance.sample_count > 10:
        return 0.6
    return 0.4
