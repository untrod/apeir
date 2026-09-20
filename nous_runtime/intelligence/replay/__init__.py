# -*- coding: utf-8 -*-
"""Deterministic and approximate replay system.

Consolidated: original replay.py (FrozenReplayBundle, build_frozen_replay_bundle,
frozen_replay_summary) + new ReplayEngine (7 replay types) + ReplayComparator.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


# Original replay.py content (consolidated to fix module/package shadow)


class SnapshotCompleteness(str, Enum):
    COMPLETE = "COMPLETE"
    PARTIAL_LEGACY = "PARTIAL_LEGACY"
    MISSING_COMPONENTS = "MISSING_COMPONENTS"
    UNREPLAYABLE = "UNREPLAYABLE"


REQUIRED_COMPONENTS = (
    "decision_snapshot", "policy_snapshot", "scheduler_configuration",
    "candidate_set", "ranking", "model_profile_snapshot",
    "provider_profile_snapshot", "profile_mapping_version",
    "provider_health_snapshot", "model_health_snapshot",
    "circuit_state", "reliability_window", "fallback_plan",
)


@dataclass(frozen=True)
class FrozenReplayBundle:
    bundle_id: str
    decision_id: str
    components: dict[str, Any] = field(default_factory=dict)
    missing_components: tuple[str, ...] = ()
    completeness: SnapshotCompleteness = SnapshotCompleteness.MISSING_COMPONENTS
    component_hashes: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "bundle_id": self.bundle_id,
            "decision_id": self.decision_id,
            "components": self.components,
            "missing_components": list(self.missing_components),
            "completeness": self.completeness.value,
            "component_hashes": dict(self.component_hashes),
        }


def build_frozen_replay_bundle(
    decision: Any,  # RuntimeDecision
    *,
    model_profile_snapshot: dict[str, Any] | None = None,
    provider_profile_snapshot: dict[str, Any] | None = None,
    provider_health_snapshot: dict[str, Any] | None = None,
    model_health_snapshot: dict[str, Any] | None = None,
    circuit_state: dict[str, Any] | None = None,
    reliability_window: dict[str, Any] | None = None,
    pricing_snapshot: dict[str, Any] | None = None,
) -> FrozenReplayBundle:
    components: dict[str, Any] = {
        "decision_snapshot": decision.to_dict() if hasattr(decision, 'to_dict') else {},
        "policy_snapshot": {
            "policy_ids": list(getattr(decision, 'policy_ids', [])),
            "policy_versions": dict(getattr(decision, 'policy_versions', {})),
            "policy_sources": dict(getattr(decision, 'policy_sources', {})),
            "policy_hashes": dict(getattr(decision, 'policy_hashes', {})),
        },
        "scheduler_configuration": dict(getattr(decision, 'metadata', {}).get("scheduler_configuration") or {"version": "unknown"}),
        "candidate_set": [c.to_dict() if hasattr(c, 'to_dict') else {} for c in getattr(decision, 'candidates', [])],
        "ranking": [
            {"candidate_id": getattr(c, 'candidate_id', ''), "score": getattr(c, 'score', 0), "rank": i + 1}
            for i, c in enumerate(sorted(getattr(decision, 'candidates', []), key=lambda x: -getattr(x, 'score', 0)))
        ],
        "model_profile_snapshot": model_profile_snapshot,
        "provider_profile_snapshot": provider_profile_snapshot,
        "profile_mapping_version": getattr(decision, 'metadata', {}).get("profile_mapping_version", ""),
        "provider_health_snapshot": provider_health_snapshot,
        "model_health_snapshot": model_health_snapshot,
        "circuit_state": circuit_state,
        "reliability_window": reliability_window,
        "pricing_snapshot": pricing_snapshot,
        "fallback_plan": getattr(getattr(decision, 'fallback_plan', None), '__dict__', {}),
    }
    missing = tuple(name for name in REQUIRED_COMPONENTS if not components.get(name))
    completeness = SnapshotCompleteness.PARTIAL_LEGACY if missing else SnapshotCompleteness.COMPLETE
    hashes = {name: _replay_hash(value) for name, value in components.items() if value not in (None, "", [], {})}
    return FrozenReplayBundle(
        bundle_id=_replay_hash({"decision_id": getattr(decision, 'decision_id', ''), "components": hashes}),
        decision_id=getattr(decision, 'decision_id', ''),
        components=components,
        missing_components=missing,
        completeness=completeness,
        component_hashes=hashes,
    )


def frozen_replay_summary(decision: Any) -> dict[str, Any]:
    bundle_data = dict(getattr(decision, 'metadata', {}).get("frozen_replay_bundle") or {})
    if bundle_data:
        return {
            "decision_id": getattr(decision, 'decision_id', ''),
            "completeness": bundle_data.get("completeness", SnapshotCompleteness.MISSING_COMPONENTS.value),
            "missing_components": list(bundle_data.get("missing_components") or []),
            "component_hashes": dict(bundle_data.get("component_hashes") or {}),
        }
    legacy = bool(getattr(decision, 'inputs_snapshot', None))
    completeness = SnapshotCompleteness.PARTIAL_LEGACY if legacy else SnapshotCompleteness.UNREPLAYABLE
    return {
        "decision_id": getattr(decision, 'decision_id', ''),
        "completeness": completeness.value,
        "missing_components": list(REQUIRED_COMPONENTS),
        "component_hashes": {},
    }


def _replay_hash(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]



# New ReplayEngine + ReplayComparator


from .engine import ReplayEngine, ReplayType  # noqa: E402
from .comparator import ReplayComparator, ReplayDiff  # noqa: E402

__all__ = [
    "FrozenReplayBundle",
    "build_frozen_replay_bundle",
    "frozen_replay_summary",
    "SnapshotCompleteness",
    "ReplayEngine",
    "ReplayType",
    "ReplayComparator",
    "ReplayDiff",
]
