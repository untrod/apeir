"""Safety checks for equivalent provider fallback execution."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from nous_runtime.intelligence.reliability.models import CircuitState


RISK_ORDER = {"low": 0, "medium": 1, "high": 2, "critical": 3}


@dataclass(frozen=True)
class FallbackBoundary:
    capability_id: str
    modality: str = ""
    privacy_level: str = ""
    locality: str = ""
    output_guarantees: tuple[str, ...] = ()
    permissions: tuple[str, ...] = ()
    side_effects: tuple[str, ...] = ()
    risk_level: str = ""
    cost_budget: float | None = None
    latency_budget_ms: float | None = None
    max_depth: int = 1


@dataclass(frozen=True)
class FallbackCompatibility:
    candidate_provider_id: str
    candidate_model_id: str = ""
    capability_id: str = ""
    modality: str = ""
    privacy_level: str = ""
    locality: str = ""
    output_guarantees: tuple[str, ...] = ()
    permissions: tuple[str, ...] = ()
    side_effects: tuple[str, ...] = ()
    risk_level: str = ""
    estimated_cost: float | None = None
    estimated_latency_ms: float | None = None
    profile_confidence: float | None = None
    circuit_state: str = "closed"
    scheduler_allowed: bool = True


@dataclass(frozen=True)
class FallbackExecutionPolicy:
    max_depth: int = 1
    require_known_properties: bool = True
    min_profile_confidence: float = 0.5
    allow_privacy_change: bool = False
    allow_locality_change: bool = False
    allow_capability_degradation: bool = False


@dataclass(frozen=True)
class FallbackSafetyAssessment:
    allowed: bool
    reason_code: str = ""
    message: str = ""
    boundary: FallbackBoundary | None = None
    compatibility: FallbackCompatibility | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "allowed": self.allowed,
            "reason_code": self.reason_code,
            "message": self.message,
            "boundary": self.boundary.__dict__ if self.boundary else None,
            "compatibility": self.compatibility.__dict__ if self.compatibility else None,
            "metadata": dict(self.metadata),
        }


def assess_fallback_safety(
    boundary: FallbackBoundary,
    candidate: FallbackCompatibility,
    *,
    policy: FallbackExecutionPolicy | None = None,
    depth: int = 0,
    visited: tuple[str, ...] = (),
) -> FallbackSafetyAssessment:
    policy = policy or FallbackExecutionPolicy(max_depth=boundary.max_depth)
    target = f"{candidate.candidate_provider_id}:{candidate.candidate_model_id}"
    if depth >= min(policy.max_depth, boundary.max_depth):
        return _reject("FALLBACK_DEPTH_LIMIT", "Fallback depth limit reached.", boundary, candidate)
    if target in visited or candidate.candidate_provider_id in visited:
        return _reject("FALLBACK_LOOP", "Fallback loop detected.", boundary, candidate)
    if not candidate.scheduler_allowed:
        return _reject("SCHEDULER_REJECTED", "Candidate does not pass scheduler constraints.", boundary, candidate)
    if candidate.circuit_state in {CircuitState.OPEN.value, CircuitState.FORCED_OPEN.value, CircuitState.HALF_OPEN.value}:
        return _reject("CIRCUIT_BLOCKED", "Candidate circuit does not allow normal traffic.", boundary, candidate)
    if candidate.capability_id != boundary.capability_id:
        return _reject("CAPABILITY_MISMATCH", "Fallback candidate does not provide the same required capability.", boundary, candidate)
    if _unknown_required(boundary, candidate, policy):
        return _reject("UNKNOWN_COMPATIBILITY", "Required fallback compatibility property is unknown.", boundary, candidate)
    if boundary.modality and candidate.modality != boundary.modality:
        return _reject("MODALITY_MISMATCH", "Fallback candidate changes required modality.", boundary, candidate)
    if not set(boundary.output_guarantees).issubset(set(candidate.output_guarantees)):
        return _reject("OUTPUT_GUARANTEE_DOWNGRADE", "Fallback candidate reduces mandatory output guarantees.", boundary, candidate)
    if boundary.privacy_level and candidate.privacy_level != boundary.privacy_level and not policy.allow_privacy_change:
        return _reject("PRIVACY_DOWNGRADE", "Fallback candidate changes privacy boundary.", boundary, candidate)
    if boundary.locality and candidate.locality != boundary.locality and not policy.allow_locality_change:
        return _reject("LOCALITY_CHANGE", "Fallback candidate changes locality boundary.", boundary, candidate)
    if not set(candidate.permissions).issubset(set(boundary.permissions)):
        return _reject("NEW_PERMISSION", "Fallback candidate requires additional permissions.", boundary, candidate)
    if set(candidate.side_effects) - set(boundary.side_effects):
        return _reject("NEW_SIDE_EFFECT", "Fallback candidate introduces an external side effect.", boundary, candidate)
    if _risk(candidate.risk_level) > _risk(boundary.risk_level):
        return _reject("RISK_INCREASE", "Fallback candidate increases risk level.", boundary, candidate)
    if boundary.cost_budget is not None and candidate.estimated_cost is not None and candidate.estimated_cost > boundary.cost_budget:
        return _reject("COST_BUDGET_EXCEEDED", "Fallback candidate exceeds cost budget.", boundary, candidate)
    if boundary.latency_budget_ms is not None and candidate.estimated_latency_ms is not None and candidate.estimated_latency_ms > boundary.latency_budget_ms:
        return _reject("LATENCY_BUDGET_EXCEEDED", "Fallback candidate exceeds latency budget.", boundary, candidate)
    if candidate.profile_confidence is not None and candidate.profile_confidence < policy.min_profile_confidence:
        return _reject("PROFILE_CONFIDENCE_LOW", "Fallback candidate profile confidence is insufficient.", boundary, candidate)
    return FallbackSafetyAssessment(True, "EQUIVALENT_FALLBACK", "Fallback candidate is equivalent within the current safety envelope.", boundary, candidate)


def _unknown_required(boundary: FallbackBoundary, candidate: FallbackCompatibility, policy: FallbackExecutionPolicy) -> bool:
    if not policy.require_known_properties:
        return False
    checks = (
        (boundary.modality, candidate.modality),
        (boundary.privacy_level, candidate.privacy_level),
        (boundary.locality, candidate.locality),
        (boundary.risk_level, candidate.risk_level),
    )
    if any(required and not actual for required, actual in checks):
        return True
    return candidate.profile_confidence is None


def _risk(value: str) -> int:
    return RISK_ORDER.get(str(value or "").lower(), 99)


def _reject(code: str, message: str, boundary: FallbackBoundary, candidate: FallbackCompatibility) -> FallbackSafetyAssessment:
    return FallbackSafetyAssessment(False, code, message, boundary, candidate)
