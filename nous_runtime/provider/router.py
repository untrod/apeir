# -*- coding: utf-8 -*-
"""
Intelligent Provider Router -auto-selects the best provider for a capability.

Removes the need for manual provider selection. The router considers:
    - Health status
    - Historical success rate
    - Latency (avg execution time)
    - Cost (if available)
    - Privacy requirements (local vs cloud)
    - Security policy
    - User preferences

Usage:
    from nous_runtime.provider.router import route

    provider_id = route("model.reason", preferences={"privacy": "high"})
    # Returns "ollama" instead of "openai" when privacy is prioritized
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

log = logging.getLogger("nous.provider.router")


@dataclass
class RoutingPreference:
    """User-specified preferences for provider selection."""
    speed: str = "balanced"      # "fastest" | "balanced" | "cheapest"
    quality: str = "balanced"    # "highest" | "balanced"
    privacy: str = "balanced"    # "high" (local only) | "balanced" | "any"
    cost: str = "balanced"       # "lowest" | "balanced" | "unlimited"
    location: str = ""           # Preferred region (e.g., "us", "eu")


@dataclass
class RoutingScore:
    """Scored provider for routing decision."""
    provider_id: str
    score: float = 0.0
    health: str = "unknown"
    success_rate: float = 0.0
    avg_latency_ms: float = 0.0
    is_local: bool = False
    reasons: list[str] = field(default_factory=list)


def route(
    capability_id: str,
    preferences: RoutingPreference | None = None,
) -> str | None:
    """
    Select the best provider for a capability.

    Args:
        capability_id: The capability to execute.
        preferences: Optional routing preferences.

    Returns:
        Provider ID, or None if no suitable provider found.
    """
    prefs = preferences or RoutingPreference()

    # 1. Find candidate providers
    candidates = _find_candidates(capability_id)
    if not candidates:
        log.warning("No providers found for '%s'", capability_id)
        return None

    # 2. Score each candidate
    scored = []
    for pid in candidates:
        s = _score_provider(pid, capability_id, prefs)
        if s:
            scored.append(s)

    if not scored:
        return None

    # 3. Select best
    scored.sort(key=lambda s: s.score, reverse=True)
    best = scored[0]

    log.info(
        "Router selected '%s' for '%s' (score=%.2f, reasons: %s)",
        best.provider_id, capability_id, best.score, best.reasons,
    )
    return best.provider_id


def route_with_explanation(
    capability_id: str,
    preferences: RoutingPreference | None = None,
) -> dict[str, Any]:
    """Route and return detailed explanation."""
    prefs = preferences or RoutingPreference()
    candidates = _find_candidates(capability_id)
    scored = [_score_provider(pid, capability_id, prefs) for pid in candidates]
    scored = [s for s in scored if s is not None]
    scored.sort(key=lambda s: s.score, reverse=True)

    return {
        "capability_id": capability_id,
        "selected": scored[0].provider_id if scored else None,
        "candidates": [
            {
                "provider_id": s.provider_id,
                "score": round(s.score, 2),
                "success_rate": s.success_rate,
                "avg_latency_ms": s.avg_latency_ms,
                "health": s.health,
                "reasons": s.reasons,
            }
            for s in scored
        ],
    }


def _find_candidates(capability_id: str) -> list[str]:
    """Find all providers that can execute a capability."""
    try:
        from nous_runtime.compat.provider import list_providers
        providers = list_providers()  # returns list[dict], not dict
        candidates = []
        for entry in providers:
            try:
                pid = entry.get("provider_id", entry.get("name", ""))
                caps = entry.get("capabilities", [])
                if capability_id in caps or any(
                    capability_id.startswith(c.replace("*", ""))
                    for c in caps
                ):
                    candidates.append(pid)
            except Exception:
                continue
        return candidates
    except Exception:
        return []


def _score_provider(
    provider_id: str,
    capability_id: str,
    prefs: RoutingPreference,
) -> RoutingScore | None:
    """Score a provider for a capability."""
    score = RoutingScore(provider_id=provider_id)
    total = 0.0

    # 1. Health (weight: 0.25)
    provider = None
    try:
        from nous_runtime.compat.provider import get_provider
        provider = get_provider(provider_id)
        if provider:
            h = provider.health()
            score.health = h.get("status", "unknown")
            if score.health == "ok":
                total += 0.25
                score.reasons.append("healthy")
            elif score.health == "degraded":
                total += 0.10
                score.reasons.append("degraded")
            else:
                return None  # Down provider = not considered
    except Exception:
        score.health = "unknown"
        total += 0.10

    # 2. Experience: success rate (weight: 0.35)
    try:
        from nous_runtime.learning.experience import stats
        exp = stats(provider_id=provider_id, capability_id=capability_id)
        if exp["total"] > 0:
            score.success_rate = exp["success_rate"]
            score.avg_latency_ms = exp["avg_duration_ms"]
            total += exp["success_rate"] * 0.35
            if exp["success_rate"] > 0.9:
                score.reasons.append("high success rate")
        else:
            total += 0.15  # Neutral for unknown
    except Exception:
        total += 0.15

    # 3. Latency (weight: 0.15)
    if score.avg_latency_ms > 0:
        # Normalize: <500ms = full points, >5000ms = 0
        latency_score = max(0, 1 - (score.avg_latency_ms - 500) / 4500)
        total += latency_score * 0.15
        if score.avg_latency_ms < 1000:
            score.reasons.append(f"fast ({score.avg_latency_ms:.0f}ms)")

    # 4. Privacy preference (weight: 0.15)
    # v0.2.0: Check locality from provider metadata first, then name heuristics
    score.is_local = _provider_is_local(provider_id, provider)
    if prefs.privacy == "high" and score.is_local:
        total += 0.15
        score.reasons.append("local (privacy)")
    elif prefs.privacy != "high":
        total += 0.10

    # 5. Speed preference (weight: 0.10)
    if prefs.speed == "fastest" and score.avg_latency_ms > 0:
        total += score.avg_latency_ms < 1000 and 0.10 or 0.0

    score.score = round(min(total, 1.0), 4)
    return score


def _provider_is_local(provider_id: str, provider: Any = None) -> bool:
    """Determine whether a provider is local.

    v0.2.0: Checks provider metadata (locality field) first, then falls
    back to name-based heuristics for backward compatibility.
    """
    # 1. Check declared locality in provider metadata
    if provider is not None:
        locality = str(getattr(provider, "locality", "") or "")
        if locality == "local":
            return True
        if locality in ("remote", "embedded", "cloud"):
            return False
        # Check capability manifest metadata
        try:
            meta = getattr(provider, "metadata", None) or {}
            if isinstance(meta, dict):
                loc = str(meta.get("locality", "") or "")
                if loc == "local":
                    return True
                if loc in ("remote", "embedded", "cloud"):
                    return False
        except Exception:
            pass

    # 2. Legacy name-based heuristics
    lowered = str(provider_id or "").lower()
    return "ollama" in lowered or "local" in lowered
