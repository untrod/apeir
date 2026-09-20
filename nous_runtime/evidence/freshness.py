# -*- coding: utf-8 -*-
"""Freshness Tracker — different TTLs for different source types.

Model prices, API limits, software versions, regulations, service status,
static papers, historical facts all have different freshness requirements.
Expired sources mark dependent claims as STALE.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from enum import Enum


class FreshnessClass(str, Enum):
    REALTIME = "realtime"          # seconds: service status
    HOURLY = "hourly"              # hours: model prices, API limits
    DAILY = "daily"                # days: software versions
    WEEKLY = "weekly"              # weeks: regulations
    MONTHLY = "monthly"            # months: research findings
    STATIC = "static"              # never: historical facts, papers


DEFAULT_TTLS: dict[FreshnessClass, float] = {
    FreshnessClass.REALTIME: 300,        # 5 minutes
    FreshnessClass.HOURLY: 3600,         # 1 hour
    FreshnessClass.DAILY: 86400,         # 1 day
    FreshnessClass.WEEKLY: 604800,       # 1 week
    FreshnessClass.MONTHLY: 2592000,     # 30 days
    FreshnessClass.STATIC: float("inf"), # never
}


@dataclass
class FreshnessPolicy:
    """Per-source-type freshness policy."""
    source_type: str = ""
    freshness_class: FreshnessClass = FreshnessClass.DAILY
    ttl_seconds: float = 86400.0
    on_expiry: str = "mark_stale"  # mark_stale, revalidate, alert
    auto_revalidate: bool = False


class FreshnessTracker:
    """Tracks freshness of sources and marks dependent claims stale."""

    def __init__(self) -> None:
        self._timestamps: dict[str, float] = {}  # source_id → retrieval_time
        self._policies: dict[str, FreshnessPolicy] = {}

    def record_retrieval(self, source_id: str, source_type: str = "web") -> None:
        self._timestamps[source_id] = time.monotonic()

    def set_policy(self, source_type: str, policy: FreshnessPolicy) -> None:
        self._policies[source_type] = policy

    def is_fresh(self, source_id: str, source_type: str = "web") -> tuple[bool, str]:
        """Check if a source is still fresh."""
        ts = self._timestamps.get(source_id)
        if ts is None:
            return False, "No retrieval timestamp"

        policy = self._policies.get(source_type)
        if policy is None:
            # Default policy based on type
            fc = {
                "model_price": FreshnessClass.HOURLY,
                "api_limit": FreshnessClass.DAILY,
                "software_version": FreshnessClass.DAILY,
                "regulation": FreshnessClass.WEEKLY,
                "service_status": FreshnessClass.REALTIME,
                "paper": FreshnessClass.STATIC,
                "historical_fact": FreshnessClass.STATIC,
                "web": FreshnessClass.DAILY,
            }.get(source_type, FreshnessClass.DAILY)
            ttl = DEFAULT_TTLS.get(fc, 86400)
        else:
            ttl = policy.ttl_seconds

        if ttl == float("inf"):
            return True, "Static (never expires)"

        elapsed = time.monotonic() - ts
        if elapsed > ttl:
            return False, f"Expired: {elapsed:.0f}s > {ttl:.0f}s TTL"
        return True, f"Fresh: {ttl - elapsed:.0f}s remaining"

    def get_stale_sources(self) -> list[str]:
        """Return all stale source IDs."""
        stale = []
        for source_id in self._timestamps:
            fresh, _ = self.is_fresh(source_id)
            if not fresh:
                stale.append(source_id)
        return stale
