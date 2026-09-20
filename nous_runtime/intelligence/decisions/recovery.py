"""Retry, fallback, and recovery decisions."""

from __future__ import annotations

from enum import Enum

from nous_runtime.intelligence.models import (
    DecisionCandidate,
    DecisionOutcome,
    DecisionReason,
    DecisionRequest,
    DecisionType,
    RuntimeDecision,
    SelectionContext,
    SchedulingRequest,
    decision_id_for,
    snapshot_hash,
)
from nous_runtime.intelligence.scheduler import recovery_strategy_candidates, schedule_candidates


class ErrorCategory(str, Enum):
    TRANSIENT = "TRANSIENT"
    PERMANENT = "PERMANENT"
    POLICY = "POLICY"
    AUTH = "AUTH"
    RATE_LIMIT = "RATE_LIMIT"
    TIMEOUT = "TIMEOUT"
    BACKEND = "BACKEND"
    VALIDATION = "VALIDATION"
    SECURITY = "SECURITY"
    USER_CANCELLED = "USER_CANCELLED"


def recovery_decision(request: DecisionRequest) -> RuntimeDecision:
    category = ErrorCategory(str(request.context.metadata.get("error_category") or ErrorCategory.TRANSIENT.value))
    if category in {ErrorCategory.RATE_LIMIT, ErrorCategory.BACKEND}:
        selected = "fallback"
        reason = DecisionReason(category.value, "Switch provider or backend.", 0.85)
    elif category == ErrorCategory.TIMEOUT:
        selected = "retry_once"
        reason = DecisionReason("TIMEOUT", "Retry once or use a smaller model.", 0.75)
    elif category in {ErrorCategory.AUTH, ErrorCategory.VALIDATION, ErrorCategory.SECURITY, ErrorCategory.USER_CANCELLED}:
        selected = "stop"
        reason = DecisionReason(category.value, "Do not retry this error category.", 0.95)
    else:
        selected = "retry"
        reason = DecisionReason(category.value, "Transient error can be retried.", 0.65)
    scheduler_result = schedule_candidates(
        SchedulingRequest(
            request_id=snapshot_hash(request.to_dict()),
            candidates=recovery_strategy_candidates(category.value),
            context=SelectionContext(
                task_id=request.task_id,
                decision_type=DecisionType.FALLBACK,
                constraints={"force_candidate": selected, "approval_required": selected == "stop"},
                weights={"reliability": 0.30, "latency": 0.20, "risk": 0.25, "reversibility": 0.10, "uncertainty": 0.15},
            ),
        )
    )
    ranked_candidates = tuple(
        DecisionCandidate(
            candidate_id=item.candidate.candidate_id,
            score=item.normalized_score,
            candidate_type=item.candidate.candidate_type,
            metadata=item.candidate.metadata,
            reasons=item.candidate.reasons,
        )
        for item in scheduler_result.ranking.evaluations
    )
    return RuntimeDecision(
        decision_id=decision_id_for(request, "recovery.policy", selected),
        task_id=request.task_id,
        decision_type=request.decision_type,
        outcome=DecisionOutcome(selected=selected, confidence=reason.weight, metadata={"error_category": category.value}),
        reasons=(reason,),
        candidates=ranked_candidates,
        rejected_candidates=scheduler_result.rejected_candidates,
        score_breakdown=tuple(scheduler_result.ranking.evaluations[0].score_breakdown) if scheduler_result.ranking.evaluations else (),
        policy_id="recovery.policy",
        policy_version="1.0",
        inputs_snapshot=request.to_dict(),
        metadata={"scheduler_snapshot_hash": scheduler_result.scheduler_snapshot_hash},
    )
