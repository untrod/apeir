"""Frozen replay evidence bundles for Runtime decisions."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from nous_runtime.intelligence.models import RuntimeDecision


class SnapshotCompleteness(str, Enum):
    COMPLETE = "COMPLETE"
    PARTIAL_LEGACY = "PARTIAL_LEGACY"
    MISSING_COMPONENTS = "MISSING_COMPONENTS"
    UNREPLAYABLE = "UNREPLAYABLE"


REQUIRED_COMPONENTS = (
    "decision_snapshot",
    "policy_snapshot",
    "scheduler_configuration",
    "candidate_set",
    "ranking",
    "model_profile_snapshot",
    "provider_profile_snapshot",
    "profile_mapping_version",
    "provider_health_snapshot",
    "model_health_snapshot",
    "circuit_state",
    "reliability_window",
    "fallback_plan",
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
    decision: RuntimeDecision,
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
        "decision_snapshot": decision.to_dict(),
        "policy_snapshot": {
            "policy_ids": list(decision.policy_ids),
            "policy_versions": dict(decision.policy_versions),
            "policy_sources": dict(decision.policy_sources),
            "policy_hashes": dict(decision.policy_hashes),
        },
        "scheduler_configuration": dict(decision.metadata.get("scheduler_configuration") or {"version": "unknown"}),
        "candidate_set": [candidate.to_dict() for candidate in decision.candidates],
        "ranking": [
            {"candidate_id": candidate.candidate_id, "score": candidate.score, "rank": index + 1}
            for index, candidate in enumerate(sorted(decision.candidates, key=lambda item: (-item.score, item.candidate_id)))
        ],
        "model_profile_snapshot": model_profile_snapshot,
        "provider_profile_snapshot": provider_profile_snapshot,
        "profile_mapping_version": decision.metadata.get("profile_mapping_version") or decision.metadata.get("_profile_mapping_version") or "",
        "provider_health_snapshot": provider_health_snapshot,
        "model_health_snapshot": model_health_snapshot,
        "circuit_state": circuit_state,
        "reliability_window": reliability_window,
        "pricing_snapshot": pricing_snapshot,
        "fallback_plan": decision.fallback_plan.__dict__,
    }
    missing = tuple(name for name in REQUIRED_COMPONENTS if not components.get(name))
    completeness = _completeness(missing, decision)
    hashes = {name: _hash(value) for name, value in components.items() if value not in (None, "", [], {})}
    return FrozenReplayBundle(
        bundle_id=_hash({"decision_id": decision.decision_id, "components": hashes}),
        decision_id=decision.decision_id,
        components=components,
        missing_components=missing,
        completeness=completeness,
        component_hashes=hashes,
    )


def frozen_replay_summary(decision: RuntimeDecision) -> dict[str, Any]:
    bundle_data = dict(decision.metadata.get("frozen_replay_bundle") or {})
    if bundle_data:
        return {
            "decision_id": decision.decision_id,
            "completeness": bundle_data.get("completeness", SnapshotCompleteness.MISSING_COMPONENTS.value),
            "missing_components": list(bundle_data.get("missing_components") or []),
            "component_hashes": dict(bundle_data.get("component_hashes") or {}),
        }
    legacy = bool(decision.inputs_snapshot or decision.context_snapshot or decision.candidate_snapshot)
    completeness = SnapshotCompleteness.PARTIAL_LEGACY if legacy else SnapshotCompleteness.UNREPLAYABLE
    return {
        "decision_id": decision.decision_id,
        "completeness": completeness.value,
        "missing_components": list(REQUIRED_COMPONENTS),
        "component_hashes": {},
    }


def _completeness(missing: tuple[str, ...], decision: RuntimeDecision) -> SnapshotCompleteness:
    if not missing:
        return SnapshotCompleteness.COMPLETE
    if decision.inputs_snapshot or decision.context_snapshot or decision.candidate_snapshot:
        return SnapshotCompleteness.MISSING_COMPONENTS
    return SnapshotCompleteness.PARTIAL_LEGACY


def _hash(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]
