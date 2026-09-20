"""Decision lifecycle and outcome recording service."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from nous_runtime.intelligence.models import (
    DecisionStatus,
    ExecutionOutcome,
    LifecycleTransition,
    OutcomeAssessment,
    OutcomeError,
    OutcomeFeedback,
    RuntimeDecision,
    assessment_id_for,
    feedback_id_for,
    lifecycle_event_id_for,
    outcome_id_for,
    sanitize_mapping,
    snapshot_hash,
    validate_status_transition,
)
from nous_runtime.intelligence.store import DecisionStore, JsonlDecisionStore


class DecisionLifecycleService:
    def __init__(self, store: DecisionStore):
        self.store = store

    def record_decision_created(self, decision: RuntimeDecision, *, actor: str = "runtime", source: str = "engine") -> None:
        self.store.persist_decision_snapshot(decision)
        self._record_status_path(
            decision.decision_id,
            DecisionStatus.PROPOSED,
            decision.status,
            reason="decision created",
            actor=actor,
            source=source,
        )

    def record_authorized(
        self,
        decision: RuntimeDecision,
        *,
        authorization_decision_id: str = "",
        actor: str = "governance",
        source: str = "execution_authorization_gate",
    ) -> None:
        """Record that a decision has been authorized by the B1 Execution Authorization Gate.

        Transitions SELECTED → AUTHORIZED. The Gate is the exclusive owner of this transition.
        """
        self.store.persist_decision_snapshot(decision)
        current = self.current_status(decision.decision_id, default=decision.status)
        if current == DecisionStatus.SELECTED:
            self._append_transition(
                decision.decision_id,
                current,
                DecisionStatus.AUTHORIZED,
                reason=f"authorized by governance gate ({authorization_decision_id})",
                actor=actor,
                source=source,
                execution_id=authorization_decision_id,
            )
        elif current != DecisionStatus.AUTHORIZED:
            # Already past SELECTED; log but don't fail
            import logging
            _log = logging.getLogger("nous.intelligence.lifecycle")
            _log.debug(
                "record_authorized skipped: decision %s is in status %s (expected SELECTED or AUTHORIZED)",
                decision.decision_id, current.value if hasattr(current, 'value') else current,
            )

    def record_execution_start(
        self,
        decision: RuntimeDecision,
        *,
        execution_id: str,
        actor: str = "runtime",
        source: str = "executor",
    ) -> None:
        self.store.persist_decision_snapshot(decision)
        current = self.current_status(decision.decision_id, default=decision.status)
        if current in (DecisionStatus.SELECTED, DecisionStatus.AUTHORIZED):
            self._append_transition(decision.decision_id, current, DecisionStatus.DISPATCHED, reason="execution dispatched", actor=actor, source=source, execution_id=execution_id)
            current = DecisionStatus.DISPATCHED
        if current == DecisionStatus.DISPATCHED:
            self._append_transition(decision.decision_id, current, DecisionStatus.RUNNING, reason="execution started", actor=actor, source=source, execution_id=execution_id)

    def record_execution_completion(
        self,
        decision: RuntimeDecision,
        *,
        execution_id: str,
        status: DecisionStatus | str,
        metadata: dict[str, Any] | None = None,
        error: OutcomeError | None = None,
        actor: str = "runtime",
        source: str = "executor",
    ) -> ExecutionOutcome:
        target = _completion_status(status)
        outcome = build_execution_outcome(
            decision,
            execution_id=execution_id,
            status=target,
            metadata=metadata or {},
            error=error,
        )
        existing = self.store.read_outcome(outcome.outcome_id)
        if existing is not None:
            return existing
        self.store.persist_decision_snapshot(decision)
        current = self.current_status(decision.decision_id, default=decision.status)
        if current in {DecisionStatus.OUTCOME_RECORDED, DecisionStatus.ASSESSED, DecisionStatus.CLOSED}:
            return outcome
        if current == DecisionStatus.SELECTED:
            self.record_execution_start(decision, execution_id=execution_id, actor=actor, source=source)
            current = self.current_status(decision.decision_id, default=DecisionStatus.RUNNING)
        self._append_transition(decision.decision_id, current, target, reason="execution completed", actor=actor, source=source, execution_id=execution_id)
        self.record_outcome(outcome, actor=actor, source=source)
        return outcome

    def record_outcome(self, outcome: ExecutionOutcome, *, actor: str = "runtime", source: str = "outcome") -> bool:
        written = self.store.persist_outcome(outcome)
        current = self.current_status(outcome.decision_id, default=outcome.status)
        if current in {
            DecisionStatus.SUCCEEDED,
            DecisionStatus.FAILED,
            DecisionStatus.TIMED_OUT,
            DecisionStatus.COMPLETED,
            DecisionStatus.CANCELLED,
        }:
            self._append_transition(
                outcome.decision_id,
                current,
                DecisionStatus.OUTCOME_RECORDED,
                reason="outcome recorded",
                actor=actor,
                source=source,
                execution_id=outcome.execution_id,
                outcome_id=outcome.outcome_id,
            )
        return written

    def add_assessment(self, assessment: OutcomeAssessment, *, actor: str = "runtime", source: str = "assessment") -> bool:
        written = self.store.persist_assessment(assessment)
        current = self.current_status(assessment.decision_id, default=DecisionStatus.OUTCOME_RECORDED)
        if current == DecisionStatus.OUTCOME_RECORDED:
            self._append_transition(
                assessment.decision_id,
                current,
                DecisionStatus.ASSESSED,
                reason="assessment recorded",
                actor=actor,
                source=source,
                outcome_id=assessment.outcome_id,
            )
        return written

    def add_feedback(self, feedback: OutcomeFeedback) -> bool:
        return self.store.persist_feedback(feedback)

    def close_decision(self, decision_id: str, *, actor: str = "runtime", source: str = "lifecycle", reason: str = "closed") -> None:
        current = self.current_status(decision_id, default=DecisionStatus.OUTCOME_RECORDED)
        if current != DecisionStatus.CLOSED:
            self._append_transition(decision_id, current, DecisionStatus.CLOSED, reason=reason, actor=actor, source=source)

    def current_status(self, decision_id: str, *, default: DecisionStatus = DecisionStatus.PROPOSED) -> DecisionStatus:
        events = self.store.read_timeline(decision_id)
        if not events:
            return default
        return events[-1].to_status

    def incomplete_decisions(self) -> list[RuntimeDecision]:
        return self.store.find_incomplete_decisions()

    def timeline(self, decision_id: str) -> list[LifecycleTransition]:
        return self.store.read_timeline(decision_id)

    def _append_transition(
        self,
        decision_id: str,
        from_status: DecisionStatus,
        to_status: DecisionStatus,
        *,
        reason: str,
        actor: str,
        source: str,
        execution_id: str = "",
        outcome_id: str = "",
    ) -> None:
        if from_status == to_status:
            return
        validate_status_transition(from_status, to_status)
        event = LifecycleTransition(
            event_id=lifecycle_event_id_for(
                decision_id,
                to_status,
                reason=reason,
                actor=actor,
                source=source,
                execution_id=execution_id,
                outcome_id=outcome_id,
            ),
            decision_id=decision_id,
            from_status=from_status,
            to_status=to_status,
            reason=reason,
            actor=actor,
            source=source,
            execution_id=execution_id,
            outcome_id=outcome_id,
        )
        self.store.append_lifecycle_event(event)

    def _record_status_path(
        self,
        decision_id: str,
        from_status: DecisionStatus,
        to_status: DecisionStatus,
        *,
        reason: str,
        actor: str,
        source: str,
    ) -> None:
        if from_status == to_status:
            return
        if from_status == DecisionStatus.PROPOSED and to_status == DecisionStatus.SELECTED:
            self._append_transition(decision_id, from_status, DecisionStatus.EVALUATED, reason=reason, actor=actor, source=source)
            self._append_transition(decision_id, DecisionStatus.EVALUATED, to_status, reason=reason, actor=actor, source=source)
            return
        self._append_transition(decision_id, from_status, to_status, reason=reason, actor=actor, source=source)


def lifecycle_for_workspace(workspace_path: str) -> DecisionLifecycleService:
    return DecisionLifecycleService(JsonlDecisionStore(workspace_path))


def build_execution_outcome(
    decision: RuntimeDecision,
    *,
    execution_id: str = "",
    status: DecisionStatus = DecisionStatus.SUCCEEDED,
    metadata: dict[str, Any] | None = None,
    error: OutcomeError | None = None,
) -> ExecutionOutcome:
    clean_metadata = sanitize_mapping(metadata or {})
    selected = str(clean_metadata.get("selected_candidate") or decision.selected)
    outcome_id = str(clean_metadata.get("outcome_id") or outcome_id_for(decision.decision_id, execution_id, selected))
    started_at = _parse_or_now(clean_metadata.get("started_at"))
    completed_at = _parse_or_now(clean_metadata.get("completed_at"))
    return ExecutionOutcome(
        outcome_id=outcome_id,
        decision_id=decision.decision_id,
        execution_id=execution_id or str(clean_metadata.get("execution_id") or ""),
        task_id=decision.task_id,
        decision_type=decision.decision_type,
        selected_candidate=selected,
        status=status,
        trace_id=decision.trace_id,
        plan_id=decision.plan_id,
        started_at=started_at,
        completed_at=completed_at,
        latency_ms=_optional_number(clean_metadata.get("latency_ms")),
        queue_latency_ms=_optional_number(clean_metadata.get("queue_latency_ms")),
        execution_latency_ms=_optional_number(clean_metadata.get("execution_latency_ms")),
        cost=_optional_number(clean_metadata.get("cost")),
        token_usage=dict(clean_metadata.get("token_usage") or {}),
        result_quality=_optional_number(clean_metadata.get("result_quality")),
        error=error,
        retry_count=int(clean_metadata.get("retry_count") or 0),
        fallback_used=bool(clean_metadata.get("fallback_used", False)),
        fallback_depth=int(clean_metadata.get("fallback_depth") or 0),
        decision_snapshot_hash=snapshot_hash(decision.to_dict()),
        policy_snapshot_hash=snapshot_hash(decision.policy_hashes),
        metadata=clean_metadata,
    )


def build_assessment(
    outcome: ExecutionOutcome,
    *,
    execution_success: bool | None = None,
    task_success: bool | None = None,
    quality_success: bool | None = None,
    policy_compliant: bool | None = None,
    safety_compliant: bool | None = None,
    user_accepted: bool | None = None,
    metadata: dict[str, Any] | None = None,
) -> OutcomeAssessment:
    return OutcomeAssessment(
        assessment_id=assessment_id_for(outcome.outcome_id, outcome.decision_id),
        outcome_id=outcome.outcome_id,
        decision_id=outcome.decision_id,
        execution_success=execution_success,
        task_success=task_success,
        quality_success=quality_success,
        policy_compliant=policy_compliant,
        safety_compliant=safety_compliant,
        user_accepted=user_accepted,
        metadata=sanitize_mapping(metadata or {}),
    )


def build_feedback(outcome: ExecutionOutcome, *, accepted: bool | None = None, rating: float | None = None, comment: str = "") -> OutcomeFeedback:
    return OutcomeFeedback(
        feedback_id=feedback_id_for(outcome.outcome_id, comment=comment),
        outcome_id=outcome.outcome_id,
        decision_id=outcome.decision_id,
        accepted=accepted,
        rating=rating,
        comment=comment,
    )


def record_retrieval_outcome(
    service: DecisionLifecycleService,
    decision: RuntimeDecision,
    *,
    execution_id: str,
    ok: bool | None = None,
    result_count: int | None = None,
    candidate_count: int | None = None,
    latency_ms: float | None = None,
    context_packed: bool | None = None,
    fallback_used: bool = False,
    metadata: dict[str, Any] | None = None,
) -> ExecutionOutcome:
    data = {
        **(metadata or {}),
        "result_count": result_count,
        "candidate_count": candidate_count,
        "latency_ms": latency_ms,
        "context_packed": context_packed,
        "fallback_used": fallback_used,
    }
    status = DecisionStatus.SUCCEEDED if ok is not False and (result_count is None or result_count >= 0) else DecisionStatus.FAILED
    return service.record_execution_completion(decision, execution_id=execution_id, status=status, metadata=data, source="retrieval")


def record_provider_outcome(
    service: DecisionLifecycleService,
    decision: RuntimeDecision,
    *,
    execution_id: str,
    ok: bool,
    latency_ms: float | None = None,
    token_usage: dict[str, Any] | None = None,
    cost: float | None = None,
    retry_count: int = 0,
    fallback_used: bool = False,
    error: OutcomeError | None = None,
    metadata: dict[str, Any] | None = None,
) -> ExecutionOutcome:
    data = {
        **(metadata or {}),
        "latency_ms": latency_ms,
        "token_usage": token_usage or {},
        "cost": cost,
        "retry_count": retry_count,
        "fallback_used": fallback_used,
    }
    return service.record_execution_completion(
        decision,
        execution_id=execution_id,
        status=DecisionStatus.SUCCEEDED if ok else DecisionStatus.FAILED,
        metadata=data,
        error=error,
        source="provider",
    )


def record_recovery_outcome(
    service: DecisionLifecycleService,
    decision: RuntimeDecision,
    *,
    execution_id: str,
    recovered: bool,
    added_latency_ms: float | None = None,
    added_cost: float | None = None,
    escalation_required: bool | None = None,
    metadata: dict[str, Any] | None = None,
) -> ExecutionOutcome:
    data = {
        **(metadata or {}),
        "added_latency_ms": added_latency_ms,
        "added_cost": added_cost,
        "escalation_required": escalation_required,
    }
    return service.record_execution_completion(
        decision,
        execution_id=execution_id,
        status=DecisionStatus.SUCCEEDED if recovered else DecisionStatus.FAILED,
        metadata=data,
        source="recovery",
    )


def _completion_status(status: DecisionStatus | str) -> DecisionStatus:
    parsed = status if isinstance(status, DecisionStatus) else DecisionStatus(str(status))
    if parsed == DecisionStatus.COMPLETED:
        return DecisionStatus.SUCCEEDED
    return parsed


def _parse_or_now(value: Any) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str) and value:
        text = value[:-1] + "+00:00" if value.endswith("Z") else value
        parsed = datetime.fromisoformat(text)
    else:
        parsed = datetime.now(timezone.utc)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _optional_number(value: Any) -> float | None:
    if value is None or value == "":
        return None
    return float(value)
