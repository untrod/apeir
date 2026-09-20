"""Retrieval policy decision."""

from __future__ import annotations

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
from nous_runtime.intelligence.scheduler import retrieval_strategy_candidates, schedule_candidates


def retrieval_decision(request: DecisionRequest) -> RuntimeDecision:
    ctx = request.context
    prompt = ctx.prompt.lower()
    reasons: list[DecisionReason] = []
    enabled = False
    metadata = {
        "mode": "policy",
        "backend": "local",
        "generation_id": ctx.active_generation_id,
        "top_k": 8,
        "context_budget": min(ctx.token_budget or 6000, 6000),
    }

    if ctx.explicit_overrides.get("retrieval") in ("enabled", True):
        enabled = True
        reasons.append(DecisionReason("EXPLICIT_RETRIEVAL_REQUEST", "Task explicitly requested retrieval.", 1.0))
    elif not ctx.retrieval_available or not ctx.active_generation_id:
        enabled = False
        reasons.append(DecisionReason("NO_ACTIVE_GENERATION", "No active retrieval generation is available.", 0.9))
    elif any(word in prompt for word in ("memory", "project", "code", "research", "docs", "document", "repo")):
        enabled = True
        reasons.append(
            DecisionReason(
                "TASK_NEEDS_PROJECT_CONTEXT",
                "Prompt indicates project or document context is useful.",
                0.85,
            )
        )
    elif ctx.task_kind in ("question", "research", "code", "document"):
        enabled = True
        reasons.append(DecisionReason("TASK_KIND_NEEDS_CONTEXT", "Task kind benefits from retrieval.", 0.75))
    else:
        enabled = False
        reasons.append(DecisionReason("TASK_CONTEXT_SUFFICIENT", "No retrieval signal was detected.", 0.55))

    selected = "enabled" if enabled else "disabled"
    if enabled:
        metadata["query"] = ctx.prompt[:240]
    metadata["reason_codes"] = [reason.code for reason in reasons]
    scheduler_result = schedule_candidates(
        SchedulingRequest(
            request_id=snapshot_hash(request.to_dict()),
            candidates=retrieval_strategy_candidates(metadata),
            context=SelectionContext(
                task_id=request.task_id,
                decision_type=DecisionType.RETRIEVAL,
                constraints={"force_candidate": selected},
                weights={"information_gain": 0.35, "latency": 0.20, "cost": 0.15, "risk": 0.10, "uncertainty": 0.20},
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
    metadata["scheduler_snapshot_hash"] = scheduler_result.scheduler_snapshot_hash
    metadata["scheduler_selected"] = scheduler_result.selected.selected_candidate_id
    return RuntimeDecision(
        decision_id=decision_id_for(request, "retrieval.policy", selected),
        task_id=request.task_id,
        decision_type=request.decision_type,
        outcome=DecisionOutcome(
            selected=selected,
            alternatives=("disabled",) if enabled else ("enabled",),
            confidence=max((reason.weight for reason in reasons), default=0.5),
            metadata=metadata,
        ),
        reasons=tuple(reasons),
        candidates=ranked_candidates,
        rejected_candidates=scheduler_result.rejected_candidates,
        score_breakdown=tuple(scheduler_result.ranking.evaluations[0].score_breakdown) if scheduler_result.ranking.evaluations else (),
        policy_id="retrieval.policy",
        policy_version="1.0",
        inputs_snapshot=request.to_dict(),
    )
