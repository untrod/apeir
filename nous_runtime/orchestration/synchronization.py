# -*- coding: utf-8 -*-
"""Concurrency Control & Synchronization for multi-agent orchestration.

Prevents: two agents overwriting the same file, reviewers inspecting stale
versions, downstream consumers using invalidated inputs.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any


@dataclass
class WriteLease:
    """Exclusive write lease for a resource."""
    lease_id: str = ""
    resource_id: str = ""       # file path, artifact_id, etc.
    holder_role: str = ""
    acquired_at: float = 0.0
    expires_at: float = 0.0
    version: int = 1
    metadata: dict[str, Any] = field(default_factory=dict)

    def is_expired(self) -> bool:
        return time.monotonic() > self.expires_at

    def is_held_by(self, role: str) -> bool:
        return self.holder_role == role and not self.is_expired()


class ConcurrencyController:
    """Optimistic concurrency control with write leases and version checks."""

    def __init__(self) -> None:
        self._leases: dict[str, WriteLease] = {}
        self._versions: dict[str, int] = {}  # resource_id → current version

    def acquire_lease(self, resource_id: str, holder_role: str, ttl_seconds: float = 60.0) -> WriteLease | None:
        """Try to acquire exclusive write lease. Returns None if resource is locked."""
        existing = self._leases.get(resource_id)
        if existing is not None and not existing.is_expired():
            if existing.holder_role != holder_role:
                return None  # locked by another agent
            # Same agent renewing
            existing.expires_at = time.monotonic() + ttl_seconds
            return existing

        current_version = self._versions.get(resource_id, 1)
        lease = WriteLease(
            lease_id=f"lease_{uuid.uuid4().hex[:8]}",
            resource_id=resource_id,
            holder_role=holder_role,
            acquired_at=time.monotonic(),
            expires_at=time.monotonic() + ttl_seconds,
            version=current_version + 1,
        )
        self._leases[resource_id] = lease
        return lease

    def release_lease(self, resource_id: str, holder_role: str, new_version: int | None = None) -> bool:
        """Release a write lease. Optionally bump version."""
        lease = self._leases.get(resource_id)
        if lease is None or lease.holder_role != holder_role:
            return False
        if new_version is not None:
            self._versions[resource_id] = new_version
        else:
            self._versions[resource_id] = lease.version
        del self._leases[resource_id]
        return True

    def get_version(self, resource_id: str) -> int:
        return self._versions.get(resource_id, 0)

    def check_conflict(self, resource_id: str, expected_version: int) -> bool:
        """True if actual version differs from expected (conflict)."""
        return self._versions.get(resource_id, 0) != expected_version

    def expire_stale_leases(self) -> int:
        """Remove expired leases. Returns count removed."""
        expired = [
            rid for rid, lease in self._leases.items()
            if lease.is_expired()
        ]
        for rid in expired:
            del self._leases[rid]
        return len(expired)


class ConflictDetector:
    """Detects conflicts between agent outputs."""

    def detect(
        self,
        output_a: dict[str, Any],
        output_b: dict[str, Any],
    ) -> dict[str, Any]:
        """Compare two agent outputs for conflicts."""
        conflicts = []

        # Value conflicts (same key, different value)
        all_keys = set(output_a.keys()) | set(output_b.keys())
        for key in all_keys:
            va = output_a.get(key)
            vb = output_b.get(key)
            if va != vb and va is not None and vb is not None:
                conflicts.append({
                    "type": "value_conflict",
                    "key": key,
                    "value_a": str(va)[:100],
                    "value_b": str(vb)[:100],
                })

        # Structural conflicts (one has key, other doesn't)
        for key in output_a.keys() - output_b.keys():
            conflicts.append({"type": "missing_in_b", "key": key})
        for key in output_b.keys() - output_a.keys():
            conflicts.append({"type": "missing_in_a", "key": key})

        return {
            "has_conflicts": len(conflicts) > 0,
            "conflict_count": len(conflicts),
            "conflicts": conflicts[:20],
        }
