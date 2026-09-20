"""Capability routing decisions — dispatches to executor type."""

from __future__ import annotations

from nous_runtime.intelligence.models import (
    CandidateType,
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
from nous_runtime.intelligence.scheduler import schedule_candidates


def capability_decision(request: DecisionRequest) -> RuntimeDecision:
    """Select the best executor for a universal capability.

    v0.2.0: This handler replaces the model-only routing in
    :func:`route_model`.  It evaluates all candidates (providers,
    connectors, agents, nodes) and selects based on capability fit,
    health, privacy, and cost.
    """
    candidates_raw = request.context.provider_candidates or ()
    metadata = request.context.metadata or {}

    # Build scheduler candidates from capability context
    scheduler_candidates = tuple(
        DecisionCandidate(
            candidate_id=str(item.get("provider_id") or item.get("name") or item.get("id") or ""),
            candidate_type=CandidateType.CAPABILITY,
            metadata=dict(item),
        )
        for item in candidates_raw
        if item.get("provider_id") or item.get("name") or item.get("id")
    )

    required_capability = str(
        metadata.get("required_capability")
        or request.context.explicit_overrides.get("required_capability")
        or ""
    )

    constraints: dict = {
        "required_capability": required_capability,
    }
    if request.context.max_cost is not None:
        constraints["max_cost"] = request.context.max_cost
    if request.context.max_latency_ms is not None:
        constraints["max_latency_ms"] = request.context.max_latency_ms
    allowed = request.context.explicit_overrides.get("allowed_providers", ())
    if allowed:
        constraints["allowed_providers"] = allowed
    denied = request.context.explicit_overrides.get("denied_providers", ())
    if denied:
        constraints["denied_providers"] = denied

    scheduler_result = schedule_candidates(
        SchedulingRequest(
            request_id=snapshot_hash(request.to_dict()),
            candidates=scheduler_candidates or _fallback_candidates(required_capability),
            context=SelectionContext(
                task_id=request.task_id,
                decision_type=DecisionType.CAPABILITY,
                constraints=constraints,
                pareto_enabled=True,
                preserve_fallback_candidates=True,
            ),
        )
    )

    evaluations = scheduler_result.ranking.evaluations
    candidates = [
        DecisionCandidate(
            candidate_id=item.candidate.candidate_id,
            score=item.normalized_score,
            candidate_type=item.candidate.candidate_type,
            metadata=item.candidate.metadata,
            reasons=item.candidate.reasons,
        )
        for item in evaluations
        if item.eligible
    ]

    if not candidates:
        reason = DecisionReason(
            "NO_ELIGIBLE_EXECUTOR",
            f"No executor can satisfy {required_capability or 'the request'}.",
            1.0,
        )
        return RuntimeDecision(
            decision_id=decision_id_for(request, "capability.routing", ""),
            task_id=request.task_id,
            decision_type=request.decision_type,
            outcome=DecisionOutcome(selected="", confidence=0.0),
            reasons=(reason,),
            policy_id="capability.routing",
            policy_version="2.0",
            inputs_snapshot=request.to_dict(),
        )

    selected = candidates[0]
    alternatives = tuple(c.candidate_id for c in candidates[1:])
    reason = DecisionReason(
        "BEST_EXECUTOR",
        f"Selected {selected.candidate_id} (type={selected.metadata.get('executor_type', 'provider')}) "
        f"for {required_capability or 'the task'}.",
        selected.score,
    )
    return RuntimeDecision(
        decision_id=decision_id_for(request, "capability.routing", selected.candidate_id),
        task_id=request.task_id,
        decision_type=request.decision_type,
        outcome=DecisionOutcome(
            selected=selected.candidate_id,
            alternatives=alternatives,
            confidence=selected.score,
            metadata={
                "executor_type": selected.metadata.get("executor_type", "provider"),
                "capability": required_capability,
            },
        ),
        reasons=(reason,),
        candidates=tuple(candidates),
        rejected_candidates=scheduler_result.rejected_candidates,
        score_breakdown=tuple(evaluations[0].score_breakdown) if evaluations else (),
        policy_id="capability.routing",
        policy_version="2.0",
        inputs_snapshot=request.to_dict(),
        metadata={"scheduler_snapshot_hash": scheduler_result.scheduler_snapshot_hash},
    )


def _fallback_candidates(required_capability: str) -> tuple[DecisionCandidate, ...]:
    """Return candidates from the capability registry when none are provided."""
    try:
        from nous_runtime.compat.capability import list_capabilities

        caps = list_capabilities()
        result = []
        for cap in caps:
            if isinstance(cap, dict):
                cid = str(cap.get("name", cap.get("capability_id", "")))
                if required_capability and cid != required_capability:
                    continue
                meta = dict(cap.get("metadata", {}) if isinstance(cap.get("metadata"), dict) else {})
                provider = str(cap.get("provider", ""))
                result.append(
                    DecisionCandidate(
                        candidate_id=provider or cid,
                        candidate_type=CandidateType.CAPABILITY,
                        metadata={
                            "provider_id": provider,
                            "name": provider or cid,
                            "capabilities": [cid],
                            "executor_type": meta.get("executor_type", "provider"),
                            "risk": cap.get("risk", "low"),
                        },
                    )
                )
        return tuple(result)
    except Exception:
        return ()
