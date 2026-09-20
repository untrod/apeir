"""Dynamic performance observation aggregation.

Conservative aggregations: sample count, p50/p95/p99, success rate,
validation rate, exponential moving average, observation window.
No online RL. No fabricated metrics.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from nous_runtime.intelligence.profiles.models import (
    PerformanceAggregate,
    PerformanceObservation,
)


def aggregate_observations(
    observations: list[PerformanceObservation],
    *,
    window_days: int = 30,
    min_samples: int = 3,
    alpha: float = 0.1,  # EMA smoothing factor
) -> PerformanceAggregate:
    """Compute conservative performance aggregates from observations.

    Returns aggregates with explicit confidence and freshness.
    When sample count is below min_samples, confidence is proportionally reduced.
    """
    if not observations:
        return PerformanceAggregate(
            sample_count=0,
            freshness=0.0,
            confidence=0.0,
        )

    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=window_days)

    # Filter to window
    in_window = [o for o in observations if o.observed_at >= cutoff]
    if not in_window:
        # Use all if nothing in window
        in_window = observations[-100:]

    n = len(in_window)

    # Success rate
    success_count = sum(1 for o in in_window if o.success)
    success_rate = success_count / n if n > 0 else None

    # Validation rate
    validated = [o for o in in_window if o.output_validated is not None]
    validation_rate = sum(1 for o in validated if o.output_validated) / len(validated) if validated else None

    # Latency percentiles
    latencies = sorted(o.latency_ms for o in in_window if o.latency_ms > 0)
    p50 = _percentile(latencies, 50) if latencies else None
    p95 = _percentile(latencies, 95) if len(latencies) >= 20 else None
    p99 = _percentile(latencies, 99) if len(latencies) >= 100 else None

    # EMA latency
    ema = _compute_ema(latencies, alpha) if latencies else None

    # Freshness — how recent is the data
    newest = max(o.observed_at for o in in_window)
    age_days = (now - newest).total_seconds() / 86400.0
    freshness = max(0.0, 1.0 - age_days / window_days)

    # Confidence — proportional to sample count
    confidence = min(1.0, n / max(min_samples, 1))

    return PerformanceAggregate(
        sample_count=n,
        p50_ms=round(p50, 2) if p50 is not None else None,
        p95_ms=round(p95, 2) if p95 is not None else None,
        p99_ms=round(p99, 2) if p99 is not None else None,
        success_rate=round(success_rate, 4) if success_rate is not None else None,
        validation_rate=round(validation_rate, 4) if validation_rate is not None else None,
        ema_latency_ms=round(ema, 2) if ema is not None else None,
        window_start=in_window[0].observed_at if in_window else None,
        window_end=newest,
        freshness=round(freshness, 4),
        confidence=round(confidence, 4),
    )


def record_observation(
    model_id: str,
    provider_id: str,
    capability_id: str,
    success: bool,
    latency_ms: float,
    *,
    failure_category: str = "",
    token_usage: dict[str, int] | None = None,
    cost: float | None = None,
    output_validated: bool | None = None,
    task_type: str = "",
    fallback_used: bool = False,
    retry_count: int = 0,
) -> PerformanceObservation:
    """Create a PerformanceObservation from execution results."""
    from nous_runtime.intelligence.profiles.models import snapshot_hash

    obs_id = snapshot_hash({
        "model": model_id,
        "provider": provider_id,
        "capability": capability_id,
        "ts": datetime.now(timezone.utc).isoformat(),
        "latency": latency_ms,
    })
    return PerformanceObservation(
        observation_id=obs_id,
        model_id=model_id,
        provider_id=provider_id,
        capability_id=capability_id,
        success=success,
        failure_category=failure_category,
        latency_ms=latency_ms,
        token_usage=dict(token_usage or {}),
        cost=cost,
        output_validated=output_validated,
        task_type=task_type,
        fallback_used=fallback_used,
        retry_count=retry_count,
    )


# helpers

def _percentile(sorted_values: list[float], pct: float) -> float:
    if not sorted_values:
        return 0.0
    idx = int(len(sorted_values) * pct / 100.0)
    idx = max(0, min(idx, len(sorted_values) - 1))
    return sorted_values[idx]


def _compute_ema(values: list[float], alpha: float) -> float:
    if not values:
        return 0.0
    ema = values[0]
    for v in values[1:]:
        ema = alpha * v + (1 - alpha) * ema
    return ema
