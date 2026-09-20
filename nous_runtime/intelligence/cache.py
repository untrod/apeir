"""Safe caching for scheduler computations.

Cache keys include all relevant inputs (candidate snapshot hash, selection context
hash, policy snapshot hash, scoring config hash, scheduler version).

Only immutable or snapshot-addressed computations are cached.
Volatile provider health or stale observations are NOT cached without
expiration and snapshot-aware keys.
"""

from __future__ import annotations

import hashlib
import json
import threading
import time
from typing import Any

from nous_runtime.intelligence.models import SCHEDULING_SCHEMA_VERSION


# Cache entry

class _CacheEntry:
    __slots__ = ("key", "value", "created_at", "expires_at")

    def __init__(self, key: str, value: Any, ttl_seconds: float | None = None) -> None:
        self.key = key
        self.value = value
        self.created_at = time.monotonic()
        self.expires_at = self.created_at + ttl_seconds if ttl_seconds is not None else float("inf")

    @property
    def expired(self) -> bool:
        return time.monotonic() > self.expires_at


# Scheduler cache

class SchedulerCache:
    """Thread-safe cache for scheduler computations.

    Cache keys are compound hashes that include all relevant inputs.
    """

    def __init__(self, max_size: int = 256, default_ttl_seconds: float = 300.0) -> None:
        self._lock = threading.RLock()
        self._entries: dict[str, _CacheEntry] = {}
        self._max_size = max_size
        self._default_ttl = default_ttl_seconds
        self._hits = 0
        self._misses = 0

    def get(self, key: str) -> Any | None:
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                self._misses += 1
                return None
            if entry.expired:
                del self._entries[key]
                self._misses += 1
                return None
            self._hits += 1
            return entry.value

    def set(self, key: str, value: Any, ttl_seconds: float | None = None) -> None:
        with self._lock:
            if len(self._entries) >= self._max_size:
                # Evict oldest entries
                expired = [k for k, e in self._entries.items() if e.expired]
                for k in expired:
                    del self._entries[k]
                if len(self._entries) >= self._max_size:
                    # Evict oldest by creation time
                    oldest = min(self._entries.items(), key=lambda item: item[1].created_at)
                    del self._entries[oldest[0]]
            ttl = ttl_seconds if ttl_seconds is not None else self._default_ttl
            self._entries[key] = _CacheEntry(key, value, ttl)

    def invalidate(self) -> None:
        with self._lock:
            self._entries.clear()

    @property
    def stats(self) -> dict[str, Any]:
        with self._lock:
            total = self._hits + self._misses
            return {
                "size": len(self._entries),
                "max_size": self._max_size,
                "hits": self._hits,
                "misses": self._misses,
                "hit_rate": round(self._hits / max(total, 1), 3),
                "expired": sum(1 for e in self._entries.values() if e.expired),
            }


# Cache key builders

def feature_extraction_cache_key(
    candidate_hash: str,
    context_hash: str,
    policy_hash: str,
    scoring_config_hash: str,
) -> str:
    """Build cache key for static candidate feature extraction."""
    return _compound_hash(
        "feature_v2",
        candidate_hash,
        context_hash,
        policy_hash,
        scoring_config_hash,
        SCHEDULING_SCHEMA_VERSION,
    )


def capability_signature_cache_key(metadata: dict[str, Any]) -> str:
    """Build cache key for capability signature computation."""
    caps = tuple(sorted(str(c) for c in (metadata.get("capabilities") or ())))
    return _compound_hash("cap_sig_v1", caps)


def normalized_vector_cache_key(
    candidate_hash: str,
    stale_features: tuple[str, ...],
    context_hash: str,
) -> str:
    """Build cache key for normalized feature vector."""
    return _compound_hash(
        "norm_vec_v1",
        candidate_hash,
        tuple(sorted(stale_features)),
        context_hash,
        SCHEDULING_SCHEMA_VERSION,
    )


def eligibility_cache_key(
    candidate_hash: str,
    context_hash: str,
) -> str:
    """Build cache key for policy-independent eligibility checks."""
    return _compound_hash("eligibility_v1", candidate_hash, context_hash)


# Helpers

def _compound_hash(*parts: Any) -> str:
    raw = json.dumps(parts, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


# Module-level cache instance

_scheduler_cache = SchedulerCache(max_size=512, default_ttl_seconds=300.0)


def get_cache() -> SchedulerCache:
    return _scheduler_cache


def clear_cache() -> None:
    _scheduler_cache.invalidate()


def cache_stats() -> dict[str, Any]:
    return _scheduler_cache.stats
