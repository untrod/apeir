# -*- coding: utf-8 -*-
"""
Experience Optimizer — makes the Runtime improve from history.

Uses execution experience to:
    - Rank providers by success rate
    - Detect degradation (success rate dropping)
    - Recommend provider switches
    - Generate optimization suggestions
"""

from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger("nous.experience.optimizer")


def provider_rankings(capability_id: str = "") -> list[dict[str, Any]]:
    """Rank providers by success rate for a capability."""
    from nous_runtime.learning.experience import _experiences

    providers: dict[str, list[dict]] = {}
    for e in _experiences:
        if capability_id and e["capability_id"] != capability_id:
            continue
        providers.setdefault(e["provider_id"], []).append(e)

    rankings = []
    for pid, records in providers.items():
        if len(records) < 3:
            continue
        success_rate = sum(1 for r in records if r["ok"]) / len(records)
        avg_duration = sum(r["duration_ms"] for r in records) / len(records)
        rankings.append({
            "provider_id": pid,
            "success_rate": round(success_rate, 4),
            "avg_duration_ms": round(avg_duration, 1),
            "sample_size": len(records),
        })

    rankings.sort(key=lambda r: r["success_rate"], reverse=True)
    return rankings


def detect_degradation(provider_id: str, window: int = 20) -> dict[str, Any] | None:
    """
    Detect if a provider's recent performance is degrading.

    Compares the last `window` executions against the overall average.
    """
    from nous_runtime.learning.experience import _experiences

    records = [e for e in _experiences if e["provider_id"] == provider_id]
    if len(records) < window:
        return None

    overall_rate = sum(1 for r in records if r["ok"]) / len(records)
    recent = records[-window:]
    recent_rate = sum(1 for r in recent if r["ok"]) / window

    if recent_rate < overall_rate - 0.15:  # 15% drop = degradation
        return {
            "provider_id": provider_id,
            "overall_success_rate": round(overall_rate, 4),
            "recent_success_rate": round(recent_rate, 4),
            "drop": round(overall_rate - recent_rate, 4),
            "severity": "high" if recent_rate < 0.5 else "medium",
            "recommendation": "Consider switching provider or investigating",
        }
    return None


def optimization_suggestions() -> list[dict[str, Any]]:
    """Generate optimization suggestions based on experience."""
    suggestions = []

    # 1. Check for degraded providers
    from nous_runtime.learning.experience import _experiences
    providers = set(e["provider_id"] for e in _experiences)
    for pid in providers:
        degradation = detect_degradation(pid)
        if degradation:
            suggestions.append({
                "type": "provider_degradation",
                "provider_id": pid,
                "detail": degradation,
            })

    # 2. Check for slow providers
    for pid in providers:
        records = [e for e in _experiences if e["provider_id"] == pid]
        if len(records) >= 5:
            avg_dur = sum(r["duration_ms"] for r in records) / len(records)
            if avg_dur > 3000:
                suggestions.append({
                    "type": "slow_provider",
                    "provider_id": pid,
                    "avg_duration_ms": round(avg_dur, 0),
                    "recommendation": "Consider a faster provider or local model",
                })

    # 3. Check for underutilized fast providers
    fast_providers = []
    for pid in providers:
        records = [e for e in _experiences if e["provider_id"] == pid]
        if len(records) >= 5:
            avg_dur = sum(r["duration_ms"] for r in records) / len(records)
            success = sum(1 for r in records if r["ok"]) / len(records)
            if avg_dur < 500 and success > 0.9:
                fast_providers.append(pid)
    if fast_providers:
        suggestions.append({
            "type": "fast_providers_available",
            "providers": fast_providers,
            "recommendation": "Route more traffic to these fast, reliable providers",
        })

    return suggestions
