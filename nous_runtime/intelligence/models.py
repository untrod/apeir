"""Serializable Runtime Intelligence contracts."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from nous_runtime.core.errors import RuntimeStateError
from nous_runtime.version import __version__


from nous_runtime.schema_registry import (
    DECISION_SCHEMA_VERSION,
    OUTCOME_SCHEMA_VERSION,
    SCHEDULING_SCHEMA_VERSION,
)

class DecisionType(str, Enum):
    RETRIEVAL = "retrieval"
    MEMORY = "memory"
    PROVIDER = "provider"
    MODEL = "model"
    CAPABILITY = "capability"
    EXECUTION = "execution"
    RETRY = "retry"
    FALLBACK = "fallback"
    APPROVAL = "approval"


class CandidateType(str, Enum):
    MODEL = "model"
    PROVIDER = "provider"
    RETRIEVAL_STRATEGY = "retrieval_strategy"
    RECOVERY_STRATEGY = "recovery_strategy"
    CAPABILITY = "capability"
    EXECUTION_PLAN = "execution_plan"


class FeatureProvenance(str, Enum):
    DECLARED = "declared"
    OBSERVED = "observed"
    ESTIMATED = "estimated"
    VERIFIED = "verified"
    UNKNOWN = "unknown"
    STALE = "stale"


class DecisionStatus(str, Enum):
    PROPOSED = "proposed"
    EVALUATED = "evaluated"
    SELECTED = "selected"
    AUTHORIZED = "authorized"
    DISPATCHED = "dispatched"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    TIMED_OUT = "timed_out"
    OUTCOME_RECORDED = "outcome_recorded"
    ASSESSED = "assessed"
    CLOSED = "closed"
    SUPERSEDED = "superseded"
    COMPLETED = "completed"


VALID_DECISION_TRANSITIONS: dict[DecisionStatus, set[DecisionStatus]] = {
    DecisionStatus.PROPOSED: {DecisionStatus.EVALUATED, DecisionStatus.CANCELLED, DecisionStatus.SUPERSEDED},
    DecisionStatus.EVALUATED: {DecisionStatus.SELECTED, DecisionStatus.CANCELLED, DecisionStatus.SUPERSEDED},
    DecisionStatus.SELECTED: {
        DecisionStatus.AUTHORIZED,
        DecisionStatus.DISPATCHED,
        DecisionStatus.CANCELLED,
        DecisionStatus.SUPERSEDED,
        DecisionStatus.SUCCEEDED,
        DecisionStatus.FAILED,
        DecisionStatus.COMPLETED,
    },
    DecisionStatus.AUTHORIZED: {DecisionStatus.DISPATCHED, DecisionStatus.CANCELLED, DecisionStatus.TIMED_OUT},
    DecisionStatus.DISPATCHED: {
        DecisionStatus.RUNNING,
        DecisionStatus.SUCCEEDED,
        DecisionStatus.FAILED,
        DecisionStatus.CANCELLED,
        DecisionStatus.TIMED_OUT,
        DecisionStatus.COMPLETED,
    },
    DecisionStatus.RUNNING: {
        DecisionStatus.SUCCEEDED,
        DecisionStatus.FAILED,
        DecisionStatus.CANCELLED,
        DecisionStatus.TIMED_OUT,
        DecisionStatus.COMPLETED,
    },
    DecisionStatus.SUCCEEDED: {DecisionStatus.OUTCOME_RECORDED, DecisionStatus.ASSESSED, DecisionStatus.CLOSED},
    DecisionStatus.FAILED: {DecisionStatus.OUTCOME_RECORDED, DecisionStatus.ASSESSED, DecisionStatus.CLOSED},
    DecisionStatus.TIMED_OUT: {DecisionStatus.OUTCOME_RECORDED, DecisionStatus.ASSESSED, DecisionStatus.CLOSED},
    DecisionStatus.COMPLETED: {DecisionStatus.OUTCOME_RECORDED, DecisionStatus.ASSESSED, DecisionStatus.CLOSED},
    DecisionStatus.CANCELLED: {DecisionStatus.OUTCOME_RECORDED, DecisionStatus.CLOSED},
    DecisionStatus.SUPERSEDED: {DecisionStatus.CLOSED},
    DecisionStatus.OUTCOME_RECORDED: {DecisionStatus.ASSESSED, DecisionStatus.CLOSED},
    DecisionStatus.ASSESSED: {DecisionStatus.CLOSED},
    DecisionStatus.CLOSED: set(),
}


def validate_status_transition(current: DecisionStatus | str, next_status: DecisionStatus | str) -> None:
    current_status = _decision_status(current)
    target_status = _decision_status(next_status)
    if target_status not in VALID_DECISION_TRANSITIONS[current_status]:
        raise RuntimeStateError(
            f"invalid decision status transition: {current_status.value} -> {target_status.value}"
        )


def _decision_status(value: DecisionStatus | str) -> DecisionStatus:
    if isinstance(value, DecisionStatus):
        return value
    return DecisionStatus(str(value))


@dataclass(frozen=True)
class DecisionReason:
    code: str
    message: str
    weight: float = 0.0
    evidence: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class DecisionConstraint:
    name: str
    value: Any
    source: str = "runtime"


@dataclass(frozen=True)
class DecisionFeature:
    name: str
    value: Any
    normalized: float | None = None
    unit: str = ""
    source: str = "runtime"
    provenance_type: FeatureProvenance = FeatureProvenance.UNKNOWN
    confidence: float = 1.0
    observed_at: datetime | None = None
    expires_at: datetime | None = None
    stale: bool = False


@dataclass(frozen=True)
class DecisionScore:
    name: str
    value: float
    weight: float = 1.0
    direction: str = "positive"
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class CandidateRejection:
    candidate_id: str
    reason_code: str
    message: str
    constraint: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class FallbackPlan:
    candidates: tuple[str, ...] = ()
    reasons: tuple[str, ...] = ()
    conditions: tuple[str, ...] = ()
    max_depth: int = 0


@dataclass(frozen=True)
class DecisionCandidate:
    candidate_id: str
    score: float = 0.0
    candidate_type: CandidateType = CandidateType.PROVIDER
    schema_version: str = SCHEDULING_SCHEMA_VERSION
    runtime_version: str = __version__
    metadata: dict[str, Any] = field(default_factory=dict)
    reasons: tuple[DecisionReason, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "runtime_version": self.runtime_version,
            "candidate_id": self.candidate_id,
            "candidate_type": self.candidate_type.value,
            "score": self.score,
            "metadata": sanitize_mapping(self.metadata),
            "reasons": [asdict(reason) for reason in self.reasons],
            "candidate_hash": snapshot_hash(
                {
                    "candidate_id": self.candidate_id,
                    "candidate_type": self.candidate_type.value,
                    "metadata": sanitize_mapping(self.metadata),
                }
            ),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "DecisionCandidate":
        return cls(
            candidate_id=str(data.get("candidate_id") or ""),
            score=float(data.get("score") or 0.0),
            candidate_type=CandidateType(str(data.get("candidate_type") or CandidateType.PROVIDER.value)),
            schema_version=str(data.get("schema_version") or SCHEDULING_SCHEMA_VERSION),
            runtime_version=str(data.get("runtime_version") or ""),
            metadata=dict(data.get("metadata") or {}),
            reasons=tuple(
                DecisionReason(
                    code=str(item.get("code") or ""),
                    message=str(item.get("message") or ""),
                    weight=float(item.get("weight") or 0.0),
                    evidence=dict(item.get("evidence") or {}),
                )
                for item in data.get("reasons") or ()
            ),
        )


@dataclass(frozen=True)
class CandidateCapability:
    name: str
    modality: str = ""
    required: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class CandidateEstimate:
    name: str
    value: float | None = None
    unit: str = ""
    source: str = "runtime"
    provenance_type: FeatureProvenance = FeatureProvenance.UNKNOWN
    confidence: float = 0.0
    observed_at: datetime | None = None
    expires_at: datetime | None = None
    stale: bool = False

    def to_feature(self) -> DecisionFeature:
        return DecisionFeature(
            name=self.name,
            value=self.value,
            unit=self.unit,
            source=self.source,
            provenance_type=self.provenance_type,
            confidence=self.confidence,
            observed_at=self.observed_at,
            expires_at=self.expires_at,
            stale=self.stale,
        )


@dataclass(frozen=True)
class CandidateConstraintResult:
    constraint: str
    passed: bool
    reason: str = ""
    hard: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class CandidateEvaluation:
    candidate: DecisionCandidate
    eligible: bool
    features: tuple[DecisionFeature, ...] = ()
    constraints: tuple[CandidateConstraintResult, ...] = ()
    score_breakdown: tuple[DecisionScore, ...] = ()
    normalized_score: float = 0.0
    uncertainty_penalty: float = 0.0
    dominated_by: tuple[str, ...] = ()
    rejection: CandidateRejection | None = None

    def to_dict(self) -> dict[str, Any]:
        return sanitize_mapping(
            {
                "candidate": self.candidate.to_dict(),
                "eligible": self.eligible,
                "features": [_feature_to_dict(item) for item in self.features],
                "constraints": [asdict(item) for item in self.constraints],
                "score_breakdown": [asdict(item) for item in self.score_breakdown],
                "normalized_score": self.normalized_score,
                "uncertainty_penalty": self.uncertainty_penalty,
                "dominated_by": list(self.dominated_by),
                "rejection": asdict(self.rejection) if self.rejection else None,
            }
        )


@dataclass(frozen=True)
class CandidateRanking:
    evaluations: tuple[CandidateEvaluation, ...]
    pareto_enabled: bool = True
    scheduler_version: str = SCHEDULING_SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "scheduler_version": self.scheduler_version,
            "pareto_enabled": self.pareto_enabled,
            "evaluations": [item.to_dict() for item in self.evaluations],
        }


@dataclass(frozen=True)
class CandidateSelection:
    selected_candidate_id: str
    confidence: float = 0.0
    approval_required: bool = False
    fallback_candidates: tuple[str, ...] = ()
    no_safe_option: bool = False
    explanation: str = ""


@dataclass(frozen=True)
class SelectionContext:
    task_id: str = ""
    decision_type: DecisionType = DecisionType.EXECUTION
    constraints: dict[str, Any] = field(default_factory=dict)
    weights: dict[str, float] = field(default_factory=dict)
    preserve_fallback_candidates: bool = True
    pareto_enabled: bool = True
    missing_value_penalty: float = 0.08
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class SchedulingRequest:
    request_id: str
    candidates: tuple[DecisionCandidate, ...]
    context: SelectionContext
    schema_version: str = SCHEDULING_SCHEMA_VERSION
    runtime_version: str = __version__

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "runtime_version": self.runtime_version,
            "request_id": self.request_id,
            "candidates": [candidate.to_dict() for candidate in self.candidates],
            "context": _selection_context_to_dict(self.context),
        }


@dataclass(frozen=True)
class SchedulingResult:
    request_id: str
    selected: CandidateSelection
    ranking: CandidateRanking
    rejected_candidates: tuple[CandidateRejection, ...] = ()
    policy_trace: tuple[PolicyEvaluationTrace, ...] = ()
    constraint_trace: tuple[CandidateConstraintResult, ...] = ()
    scheduler_snapshot_hash: str = ""
    scoring_config_hash: str = ""
    trace: dict[str, Any] = field(default_factory=dict)
    schema_version: str = SCHEDULING_SCHEMA_VERSION
    runtime_version: str = __version__

    def to_dict(self) -> dict[str, Any]:
        return sanitize_mapping(
            {
                "schema_version": self.schema_version,
                "runtime_version": self.runtime_version,
                "request_id": self.request_id,
                "selected": asdict(self.selected),
                "ranking": self.ranking.to_dict(),
                "rejected_candidates": [asdict(item) for item in self.rejected_candidates],
                "policy_trace": [asdict(item) for item in self.policy_trace],
                "constraint_trace": [asdict(item) for item in self.constraint_trace],
                "scheduler_snapshot_hash": self.scheduler_snapshot_hash,
                "scoring_config_hash": self.scoring_config_hash,
                "trace": self.trace,
            }
        )


@dataclass(frozen=True)
class DecisionOutcome:
    selected: str
    alternatives: tuple[str, ...] = ()
    confidence: float = 1.0
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class LifecycleTransition:
    event_id: str
    decision_id: str
    from_status: DecisionStatus
    to_status: DecisionStatus
    reason: str = ""
    actor: str = "runtime"
    source: str = "runtime"
    execution_id: str = ""
    outcome_id: str = ""
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": DECISION_SCHEMA_VERSION,
            "event_id": self.event_id,
            "decision_id": self.decision_id,
            "from_status": self.from_status.value,
            "to_status": self.to_status.value,
            "reason": self.reason,
            "actor": self.actor,
            "source": self.source,
            "execution_id": self.execution_id,
            "outcome_id": self.outcome_id,
            "timestamp": _format_datetime(self.timestamp),
            "metadata": sanitize_mapping(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "LifecycleTransition":
        return cls(
            event_id=str(data.get("event_id") or ""),
            decision_id=str(data.get("decision_id") or ""),
            from_status=_decision_status(data.get("from_status") or DecisionStatus.PROPOSED.value),
            to_status=_decision_status(data.get("to_status") or DecisionStatus.SELECTED.value),
            reason=str(data.get("reason") or ""),
            actor=str(data.get("actor") or "runtime"),
            source=str(data.get("source") or "runtime"),
            execution_id=str(data.get("execution_id") or ""),
            outcome_id=str(data.get("outcome_id") or ""),
            timestamp=_parse_datetime(data.get("timestamp")),
            metadata=dict(data.get("metadata") or {}),
        )


@dataclass(frozen=True)
class OutcomeMetric:
    name: str
    value: float | int | str | None = None
    unit: str = ""
    unknown: bool = False
    source: str = "runtime"
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class OutcomeEvidence:
    evidence_id: str
    kind: str
    summary: str = ""
    value: Any = None
    confidence: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class OutcomeAttribution:
    component: str
    identifier: str
    role: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class OutcomeError:
    error_type: str
    error_code: str = ""
    message: str = ""
    retryable: bool | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return sanitize_mapping(asdict(self))

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "OutcomeError":
        return cls(
            error_type=str(data.get("error_type") or ""),
            error_code=str(data.get("error_code") or ""),
            message=str(data.get("message") or ""),
            retryable=data.get("retryable") if isinstance(data.get("retryable"), bool) else None,
            metadata=dict(data.get("metadata") or {}),
        )


@dataclass(frozen=True)
class OutcomeFeedback:
    feedback_id: str
    outcome_id: str
    decision_id: str
    accepted: bool | None = None
    rating: float | None = None
    comment: str = ""
    actor: str = "user"
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["created_at"] = _format_datetime(self.created_at)
        return sanitize_mapping(data)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "OutcomeFeedback":
        return cls(
            feedback_id=str(data.get("feedback_id") or ""),
            outcome_id=str(data.get("outcome_id") or ""),
            decision_id=str(data.get("decision_id") or ""),
            accepted=data.get("accepted") if isinstance(data.get("accepted"), bool) else None,
            rating=float(data["rating"]) if data.get("rating") is not None else None,
            comment=str(data.get("comment") or ""),
            actor=str(data.get("actor") or "user"),
            created_at=_parse_datetime(data.get("created_at")),
            metadata=dict(data.get("metadata") or {}),
        )


@dataclass(frozen=True)
class OutcomeAssessment:
    assessment_id: str
    outcome_id: str
    decision_id: str
    execution_success: bool | None = None
    task_success: bool | None = None
    quality_success: bool | None = None
    policy_compliant: bool | None = None
    safety_compliant: bool | None = None
    user_accepted: bool | None = None
    metrics: tuple[OutcomeMetric, ...] = ()
    evidence: tuple[OutcomeEvidence, ...] = ()
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["schema_version"] = OUTCOME_SCHEMA_VERSION
        data["runtime_version"] = __version__
        data["created_at"] = _format_datetime(self.created_at)
        return sanitize_mapping(data)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "OutcomeAssessment":
        return cls(
            assessment_id=str(data.get("assessment_id") or ""),
            outcome_id=str(data.get("outcome_id") or ""),
            decision_id=str(data.get("decision_id") or ""),
            execution_success=_optional_bool(data.get("execution_success")),
            task_success=_optional_bool(data.get("task_success")),
            quality_success=_optional_bool(data.get("quality_success")),
            policy_compliant=_optional_bool(data.get("policy_compliant")),
            safety_compliant=_optional_bool(data.get("safety_compliant")),
            user_accepted=_optional_bool(data.get("user_accepted")),
            metrics=tuple(OutcomeMetric(**dict(item)) for item in data.get("metrics") or ()),
            evidence=tuple(OutcomeEvidence(**dict(item)) for item in data.get("evidence") or ()),
            created_at=_parse_datetime(data.get("created_at")),
            metadata=dict(data.get("metadata") or {}),
        )


@dataclass(frozen=True)
class ExecutionOutcome:
    outcome_id: str
    decision_id: str
    execution_id: str
    task_id: str
    decision_type: DecisionType
    selected_candidate: str = ""
    status: DecisionStatus = DecisionStatus.SUCCEEDED
    trace_id: str = ""
    plan_id: str = ""
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    completed_at: datetime | None = None
    queue_latency_ms: float | None = None
    execution_latency_ms: float | None = None
    latency_ms: float | None = None
    cost: float | None = None
    token_usage: dict[str, Any] = field(default_factory=dict)
    result_quality: float | None = None
    error: OutcomeError | None = None
    retry_count: int = 0
    fallback_used: bool = False
    fallback_depth: int = 0
    metrics: tuple[OutcomeMetric, ...] = ()
    evidence: tuple[OutcomeEvidence, ...] = ()
    attribution: tuple[OutcomeAttribution, ...] = ()
    feedback: tuple[OutcomeFeedback, ...] = ()
    decision_snapshot_hash: str = ""
    policy_snapshot_hash: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    schema_version: str = OUTCOME_SCHEMA_VERSION
    runtime_version: str = __version__

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["decision_type"] = self.decision_type.value
        data["status"] = self.status.value
        data["started_at"] = _format_datetime(self.started_at)
        data["completed_at"] = _format_datetime(self.completed_at) if self.completed_at else ""
        data["error"] = self.error.to_dict() if self.error else None
        return sanitize_mapping(data)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ExecutionOutcome":
        return cls(
            outcome_id=str(data.get("outcome_id") or ""),
            decision_id=str(data.get("decision_id") or ""),
            execution_id=str(data.get("execution_id") or ""),
            task_id=str(data.get("task_id") or ""),
            decision_type=DecisionType(str(data.get("decision_type") or DecisionType.EXECUTION.value)),
            selected_candidate=str(data.get("selected_candidate") or ""),
            status=_decision_status(data.get("status") or DecisionStatus.SUCCEEDED.value),
            trace_id=str(data.get("trace_id") or ""),
            plan_id=str(data.get("plan_id") or ""),
            started_at=_parse_datetime(data.get("started_at")),
            completed_at=_parse_datetime(data.get("completed_at")) if data.get("completed_at") else None,
            queue_latency_ms=_optional_float(data.get("queue_latency_ms")),
            execution_latency_ms=_optional_float(data.get("execution_latency_ms")),
            latency_ms=_optional_float(data.get("latency_ms")),
            cost=_optional_float(data.get("cost")),
            token_usage=dict(data.get("token_usage") or {}),
            result_quality=_optional_float(data.get("result_quality")),
            error=OutcomeError.from_dict(data["error"]) if isinstance(data.get("error"), dict) else None,
            retry_count=int(data.get("retry_count") or 0),
            fallback_used=bool(data.get("fallback_used", False)),
            fallback_depth=int(data.get("fallback_depth") or 0),
            metrics=tuple(OutcomeMetric(**dict(item)) for item in data.get("metrics") or ()),
            evidence=tuple(OutcomeEvidence(**dict(item)) for item in data.get("evidence") or ()),
            attribution=tuple(OutcomeAttribution(**dict(item)) for item in data.get("attribution") or ()),
            feedback=tuple(OutcomeFeedback.from_dict(dict(item)) for item in data.get("feedback") or ()),
            decision_snapshot_hash=str(data.get("decision_snapshot_hash") or ""),
            policy_snapshot_hash=str(data.get("policy_snapshot_hash") or ""),
            metadata=dict(data.get("metadata") or {}),
            schema_version=str(data.get("schema_version") or "0.1"),
            runtime_version=str(data.get("runtime_version") or ""),
        )


@dataclass(frozen=True)
class DecisionExplanation:
    summary: str = ""
    policy_chain: tuple[str, ...] = ()
    score_breakdown: dict[str, Any] = field(default_factory=dict)
    missing_data: tuple[str, ...] = ()
    fallback_summary: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class PolicyEvaluationTrace:
    policy_id: str
    policy_version: str = "1.0"
    policy_hash: str = ""
    source: str = "runtime.default"
    matched: bool = False
    overridden_by: str = ""
    reason: str = ""


@dataclass(frozen=True)
class DecisionRecommendation:
    recommendation_id: str
    recommendation_type: str
    decision_type: DecisionType
    target_policy: str
    summary: str
    evidence: dict[str, Any] = field(default_factory=dict)
    sample_size: int = 0
    confidence: float = 0.0
    expected_effect: str = ""
    risk: str = ""
    affected_scope: str = ""
    suggested_patch: str = ""
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    expires_at: datetime | None = None
    status: str = "proposed"

    def to_dict(self) -> dict[str, Any]:
        return {
            "recommendation_id": self.recommendation_id,
            "recommendation_type": self.recommendation_type,
            "decision_type": self.decision_type.value,
            "target_policy": self.target_policy,
            "summary": self.summary,
            "evidence": dict(self.evidence),
            "sample_size": self.sample_size,
            "confidence": self.confidence,
            "expected_effect": self.expected_effect,
            "risk": self.risk,
            "affected_scope": self.affected_scope,
            "suggested_patch": self.suggested_patch,
            "created_at": _format_datetime(self.created_at),
            "expires_at": _format_datetime(self.expires_at) if self.expires_at else "",
            "status": self.status,
        }


@dataclass(frozen=True)
class DecisionContext:
    workspace_id: str = "default"
    project_id: str = "default"
    task_kind: str = ""
    prompt: str = ""
    available_context_chars: int = 0
    token_budget: int = 0
    latency_budget_ms: int = 0
    max_cost: float = 0.0
    max_latency_ms: int = 0
    deadline: str = ""
    quality_floor: float = 0.0
    risk_ceiling: str = ""
    retry_budget: int = 0
    fallback_budget: int = 0
    retrieval_available: bool = False
    active_generation_id: str = ""
    provider_candidates: tuple[dict[str, Any], ...] = ()
    explicit_overrides: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["provider_candidates"] = list(self.provider_candidates)
        return data


@dataclass(frozen=True)
class DecisionRequest:
    task_id: str
    decision_type: DecisionType
    context: DecisionContext
    requested_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    request_id: str = ""

    def __post_init__(self) -> None:
        if not self.task_id:
            raise ValueError("task_id is required")
        if not self.request_id:
            object.__setattr__(self, "request_id", _stable_id("request", self.task_id, self.decision_type.value, self.context.to_dict()))

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "decision_type": self.decision_type.value,
            "context": self.context.to_dict(),
            "requested_at": _format_datetime(self.requested_at),
            "request_id": self.request_id,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "DecisionRequest":
        context_data = dict(data.get("context") or {})
        allowed_context = DecisionContext.__dataclass_fields__
        return cls(
            task_id=str(data.get("task_id") or ""),
            decision_type=DecisionType(str(data.get("decision_type") or DecisionType.EXECUTION.value)),
            context=DecisionContext(**{k: v for k, v in context_data.items() if k in allowed_context}),
            requested_at=_parse_datetime(data.get("requested_at")),
            request_id=str(data.get("request_id") or ""),
        )


@dataclass(frozen=True)
class RuntimeDecision:
    decision_id: str
    task_id: str
    decision_type: DecisionType
    outcome: DecisionOutcome
    reasons: tuple[DecisionReason, ...]
    schema_version: str = DECISION_SCHEMA_VERSION
    runtime_version: str = __version__
    status: DecisionStatus = DecisionStatus.SELECTED
    plan_id: str = ""
    trace_id: str = ""
    parent_decision_id: str = ""
    candidates: tuple[DecisionCandidate, ...] = ()
    constraints: tuple[DecisionConstraint, ...] = ()
    rejected_candidates: tuple[CandidateRejection, ...] = ()
    score_breakdown: tuple[DecisionScore, ...] = ()
    fallback_plan: FallbackPlan = field(default_factory=FallbackPlan)
    policy_ids: tuple[str, ...] = ()
    policy_versions: dict[str, str] = field(default_factory=dict)
    policy_sources: dict[str, str] = field(default_factory=dict)
    policy_hashes: dict[str, str] = field(default_factory=dict)
    policy_id: str = "runtime.default"
    policy_version: str = "1.0"
    inputs_snapshot: dict[str, Any] = field(default_factory=dict)
    context_snapshot: dict[str, Any] = field(default_factory=dict)
    candidate_snapshot: tuple[dict[str, Any], ...] = ()
    override_metadata: dict[str, Any] = field(default_factory=dict)
    explanation: DecisionExplanation = field(default_factory=DecisionExplanation)
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def __post_init__(self) -> None:
        if not self.policy_ids:
            object.__setattr__(self, "policy_ids", (self.policy_id,))
        if not self.policy_versions:
            object.__setattr__(self, "policy_versions", {self.policy_id: self.policy_version})
        if not self.context_snapshot and self.inputs_snapshot.get("context"):
            object.__setattr__(self, "context_snapshot", dict(self.inputs_snapshot.get("context") or {}))
        if not self.candidate_snapshot and self.candidates:
            object.__setattr__(self, "candidate_snapshot", tuple(c.metadata for c in self.candidates))

    @property
    def selected(self) -> str:
        return self.outcome.selected

    @property
    def confidence(self) -> float:
        return self.outcome.confidence

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "runtime_version": self.runtime_version,
            "decision_id": self.decision_id,
            "task_id": self.task_id,
            "plan_id": self.plan_id,
            "trace_id": self.trace_id,
            "parent_decision_id": self.parent_decision_id,
            "decision_type": self.decision_type.value,
            "decision_status": self.status.value,
            "selected": self.selected,
            "alternatives": list(self.outcome.alternatives),
            "confidence": self.confidence,
            "outcome": asdict(self.outcome),
            "reasons": [asdict(reason) for reason in self.reasons],
            "candidates": [c.to_dict() for c in self.candidates],
            "constraints": [asdict(constraint) for constraint in self.constraints],
            "rejected_candidates": [asdict(rejection) for rejection in self.rejected_candidates],
            "score_breakdown": [asdict(score) for score in self.score_breakdown],
            "fallback_plan": asdict(self.fallback_plan),
            "policy_ids": list(self.policy_ids),
            "policy_versions": dict(self.policy_versions),
            "policy_sources": dict(self.policy_sources),
            "policy_hashes": dict(self.policy_hashes),
            "policy_id": self.policy_id,
            "policy_version": self.policy_version,
            "inputs_snapshot": dict(self.inputs_snapshot),
            "context_snapshot": dict(self.context_snapshot),
            "candidate_snapshot": [dict(item) for item in self.candidate_snapshot],
            "override_metadata": dict(self.override_metadata),
            "explanation": asdict(self.explanation),
            "metadata": dict(self.metadata),
            "created_at": _format_datetime(self.created_at),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "RuntimeDecision":
        outcome_data = dict(data.get("outcome") or {})
        if not outcome_data:
            outcome_data = {
                "selected": data.get("selected", ""),
                "alternatives": tuple(data.get("alternatives") or ()),
                "confidence": data.get("confidence", 1.0),
            }
        return cls(
            decision_id=str(data.get("decision_id") or ""),
            task_id=str(data.get("task_id") or ""),
            decision_type=DecisionType(str(data.get("decision_type") or DecisionType.EXECUTION.value)),
            outcome=DecisionOutcome(
                selected=str(outcome_data.get("selected") or ""),
                alternatives=tuple(str(v) for v in outcome_data.get("alternatives") or ()),
                confidence=float(outcome_data.get("confidence", 1.0)),
                metadata=dict(outcome_data.get("metadata") or {}),
            ),
            reasons=tuple(
                DecisionReason(
                    code=str(item.get("code") or ""),
                    message=str(item.get("message") or ""),
                    weight=float(item.get("weight") or 0.0),
                    evidence=dict(item.get("evidence") or {}),
                )
                for item in data.get("reasons") or ()
            ),
            schema_version=str(data.get("schema_version") or "0.1"),
            runtime_version=str(data.get("runtime_version") or ""),
            status=DecisionStatus(str(data.get("decision_status") or data.get("status") or DecisionStatus.SELECTED.value)),
            plan_id=str(data.get("plan_id") or ""),
            trace_id=str(data.get("trace_id") or ""),
            parent_decision_id=str(data.get("parent_decision_id") or ""),
            candidates=tuple(
                DecisionCandidate(
                    candidate_id=str(item.get("candidate_id") or ""),
                    score=float(item.get("score") or 0.0),
                    metadata=dict(item.get("metadata") or {}),
                    reasons=tuple(
                        DecisionReason(
                            code=str(reason.get("code") or ""),
                            message=str(reason.get("message") or ""),
                            weight=float(reason.get("weight") or 0.0),
                            evidence=dict(reason.get("evidence") or {}),
                        )
                        for reason in item.get("reasons") or ()
                    ),
                )
                for item in data.get("candidates") or ()
            ),
            constraints=tuple(
                DecisionConstraint(
                    name=str(item.get("name") or ""),
                    value=item.get("value"),
                    source=str(item.get("source") or "runtime"),
                )
                for item in data.get("constraints") or ()
            ),
            rejected_candidates=tuple(
                CandidateRejection(
                    candidate_id=str(item.get("candidate_id") or ""),
                    reason_code=str(item.get("reason_code") or ""),
                    message=str(item.get("message") or ""),
                    constraint=str(item.get("constraint") or ""),
                    metadata=dict(item.get("metadata") or {}),
                )
                for item in data.get("rejected_candidates") or ()
            ),
            score_breakdown=tuple(
                DecisionScore(
                    name=str(item.get("name") or ""),
                    value=float(item.get("value") or 0.0),
                    weight=float(item.get("weight") or 1.0),
                    direction=str(item.get("direction") or "positive"),
                    metadata=dict(item.get("metadata") or {}),
                )
                for item in data.get("score_breakdown") or ()
            ),
            fallback_plan=FallbackPlan(
                candidates=tuple(str(v) for v in (data.get("fallback_plan") or {}).get("candidates") or ()),
                reasons=tuple(str(v) for v in (data.get("fallback_plan") or {}).get("reasons") or ()),
                conditions=tuple(str(v) for v in (data.get("fallback_plan") or {}).get("conditions") or ()),
                max_depth=int((data.get("fallback_plan") or {}).get("max_depth") or 0),
            ),
            policy_ids=tuple(str(v) for v in data.get("policy_ids") or (data.get("policy_id") or "runtime.default",)),
            policy_versions=dict(data.get("policy_versions") or {}),
            policy_sources=dict(data.get("policy_sources") or {}),
            policy_hashes=dict(data.get("policy_hashes") or {}),
            policy_id=str(data.get("policy_id") or "runtime.default"),
            policy_version=str(data.get("policy_version") or "1.0"),
            inputs_snapshot=dict(data.get("inputs_snapshot") or {}),
            context_snapshot=dict(data.get("context_snapshot") or {}),
            candidate_snapshot=tuple(dict(item) for item in data.get("candidate_snapshot") or ()),
            override_metadata=dict(data.get("override_metadata") or {}),
            explanation=DecisionExplanation(
                summary=str((data.get("explanation") or {}).get("summary") or ""),
                policy_chain=tuple(str(v) for v in (data.get("explanation") or {}).get("policy_chain") or ()),
                score_breakdown=dict((data.get("explanation") or {}).get("score_breakdown") or {}),
                missing_data=tuple(str(v) for v in (data.get("explanation") or {}).get("missing_data") or ()),
                fallback_summary=str((data.get("explanation") or {}).get("fallback_summary") or ""),
                metadata=dict((data.get("explanation") or {}).get("metadata") or {}),
            ),
            metadata=dict(data.get("metadata") or {}),
            created_at=_parse_datetime(data.get("created_at")),
        )

    def transition(self, next_status: DecisionStatus | str) -> "RuntimeDecision":
        validate_status_transition(self.status, next_status)
        return RuntimeDecision(
            decision_id=self.decision_id,
            task_id=self.task_id,
            decision_type=self.decision_type,
            outcome=self.outcome,
            reasons=self.reasons,
            schema_version=self.schema_version,
            runtime_version=self.runtime_version,
            status=_decision_status(next_status),
            plan_id=self.plan_id,
            trace_id=self.trace_id,
            parent_decision_id=self.parent_decision_id,
            candidates=self.candidates,
            constraints=self.constraints,
            rejected_candidates=self.rejected_candidates,
            score_breakdown=self.score_breakdown,
            fallback_plan=self.fallback_plan,
            policy_ids=self.policy_ids,
            policy_versions=self.policy_versions,
            policy_sources=self.policy_sources,
            policy_hashes=self.policy_hashes,
            policy_id=self.policy_id,
            policy_version=self.policy_version,
            inputs_snapshot=self.inputs_snapshot,
            context_snapshot=self.context_snapshot,
            candidate_snapshot=self.candidate_snapshot,
            override_metadata=self.override_metadata,
            explanation=self.explanation,
            metadata=self.metadata,
            created_at=self.created_at,
        )


@dataclass(frozen=True)
class DecisionRecord:
    decision: RuntimeDecision
    record_id: str = ""

    def __post_init__(self) -> None:
        if not self.record_id:
            object.__setattr__(self, "record_id", self.decision.decision_id)

    def to_dict(self) -> dict[str, Any]:
        data = self.decision.to_dict()
        data["record_id"] = self.record_id
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "DecisionRecord":
        return cls(RuntimeDecision.from_dict(data), record_id=str(data.get("record_id") or data.get("decision_id") or ""))


def migrate_record(record: dict[str, Any], from_version: str, to_version: str = DECISION_SCHEMA_VERSION) -> dict[str, Any]:
    migrated = dict(record)
    if from_version in ("", "0.1") and to_version == DECISION_SCHEMA_VERSION:
        migrated.setdefault("schema_version", DECISION_SCHEMA_VERSION)
        migrated.setdefault("runtime_version", "")
        migrated.setdefault("decision_status", DecisionStatus.SELECTED.value)
        migrated.setdefault("policy_ids", [migrated.get("policy_id", "runtime.default")])
        migrated.setdefault("policy_versions", {migrated.get("policy_id", "runtime.default"): migrated.get("policy_version", "1.0")})
        return migrated
    if from_version == to_version:
        return migrated
    raise ValueError(f"unsupported decision record migration: {from_version} -> {to_version}")


def decision_id_for(request: DecisionRequest, policy_id: str, selected: str) -> str:
    return _stable_id("decision", request.to_dict(), policy_id, selected)


def lifecycle_event_id_for(
    decision_id: str,
    to_status: DecisionStatus | str,
    *,
    reason: str = "",
    actor: str = "runtime",
    source: str = "runtime",
    execution_id: str = "",
    outcome_id: str = "",
) -> str:
    return _stable_id("lifecycle", decision_id, _decision_status(to_status).value, reason, actor, source, execution_id, outcome_id)


def outcome_id_for(decision_id: str, execution_id: str = "", selected_candidate: str = "") -> str:
    return _stable_id("outcome", decision_id, execution_id, selected_candidate)


def feedback_id_for(outcome_id: str, actor: str = "user", comment: str = "") -> str:
    return _stable_id("feedback", outcome_id, actor, comment)


def assessment_id_for(outcome_id: str, decision_id: str = "") -> str:
    return _stable_id("assessment", outcome_id, decision_id)


def snapshot_hash(data: dict[str, Any]) -> str:
    return _stable_id("snapshot", sanitize_mapping(data))


SENSITIVE_KEYS = {
    "api_key",
    "authorization",
    "cookie",
    "password",
    "private_key",
    "secret",
    "token",
}

NON_SECRET_KEYS = {
    "token_count",
    "token_usage",
    "tokens",
}


def sanitize_mapping(value: Any) -> Any:
    if isinstance(value, dict):
        cleaned: dict[str, Any] = {}
        for key, item in value.items():
            text_key = str(key)
            if _is_sensitive_key(text_key):
                cleaned[text_key] = "[redacted]"
            else:
                cleaned[text_key] = sanitize_mapping(item)
        return cleaned
    if isinstance(value, list):
        return [sanitize_mapping(item) for item in value]
    if isinstance(value, tuple):
        return tuple(sanitize_mapping(item) for item in value)
    if isinstance(value, str) and len(value) > 1000:
        return f"{value[:1000]}...[truncated:{len(value)}]"
    return value


def _feature_to_dict(feature: DecisionFeature) -> dict[str, Any]:
    return sanitize_mapping(
        {
            "name": feature.name,
            "value": feature.value,
            "normalized": feature.normalized,
            "unit": feature.unit,
            "source": feature.source,
            "provenance_type": feature.provenance_type.value,
            "confidence": feature.confidence,
            "observed_at": _format_datetime(feature.observed_at) if feature.observed_at else "",
            "expires_at": _format_datetime(feature.expires_at) if feature.expires_at else "",
            "stale": feature.stale,
        }
    )


def _selection_context_to_dict(context: SelectionContext) -> dict[str, Any]:
    return sanitize_mapping(
        {
            "task_id": context.task_id,
            "decision_type": context.decision_type.value,
            "constraints": context.constraints,
            "weights": context.weights,
            "preserve_fallback_candidates": context.preserve_fallback_candidates,
            "pareto_enabled": context.pareto_enabled,
            "missing_value_penalty": context.missing_value_penalty,
            "metadata": context.metadata,
        }
    )


def _is_sensitive_key(key: str) -> bool:
    lowered = key.lower()
    if lowered in NON_SECRET_KEYS:
        return False
    return any(part in lowered for part in SENSITIVE_KEYS)


def _optional_bool(value: Any) -> bool | None:
    return value if isinstance(value, bool) else None


def _optional_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    return float(value)


def _stable_id(*parts: Any) -> str:
    raw = json.dumps(parts, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def _format_datetime(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _parse_datetime(value: Any) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    else:
        text = str(value or "")
        if text.endswith("Z"):
            text = f"{text[:-1]}+00:00"
        try:
            parsed = datetime.fromisoformat(text) if text else datetime.now(timezone.utc)
        except ValueError:
            parsed = datetime.now(timezone.utc)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)
