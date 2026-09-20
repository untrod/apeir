"""Provider and model routing decisions."""

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
from nous_runtime.intelligence.scheduler import candidates_from_provider_context, schedule_candidates


def provider_decision(request: DecisionRequest) -> RuntimeDecision:
    scheduler_result = schedule_candidates(
        SchedulingRequest(
            request_id=snapshot_hash(request.to_dict()),
            candidates=candidates_from_provider_context(request.context.provider_candidates),
            context=SelectionContext(
                task_id=request.task_id,
                decision_type=DecisionType.PROVIDER,
                pareto_enabled=False,
                constraints={
                    "required_capability": request.context.metadata.get("required_capability")
                    or next((item.get("required_capability") for item in request.context.provider_candidates if item.get("required_capability")), ""),
                    "max_cost": request.context.max_cost if request.context.max_cost else None,
                    "max_latency_ms": request.context.max_latency_ms if request.context.max_latency_ms else None,
                    "allowed_providers": request.context.explicit_overrides.get("allowed_providers", ()),
                    "denied_providers": request.context.explicit_overrides.get("denied_providers", ()),
                },
            ),
        )
    )
    candidates = [
        DecisionCandidate(
            candidate_id=item.candidate.candidate_id,
            score=item.normalized_score,
            candidate_type=item.candidate.candidate_type,
            metadata=item.candidate.metadata,
            reasons=item.candidate.reasons,
        )
        for item in scheduler_result.ranking.evaluations
        if item.eligible
    ]
    if not candidates:
        reason = DecisionReason("NO_PROVIDER_CANDIDATES", "No usable provider candidates were supplied.", 1.0)
        selected = ""
        alternatives: tuple[str, ...] = ()
        confidence = 0.0
    else:
        selected = candidates[0].candidate_id
        alternatives = tuple(c.candidate_id for c in candidates[1:])
        confidence = candidates[0].score
        reason = DecisionReason("BEST_PROVIDER_SCORE", "Selected provider has the best explainable score.", confidence)
    return RuntimeDecision(
        decision_id=decision_id_for(request, "provider.routing", selected),
        task_id=request.task_id,
        decision_type=request.decision_type,
        outcome=DecisionOutcome(
            selected=selected,
            alternatives=alternatives,
            confidence=confidence,
            metadata={"fallback_chain": list(alternatives)},
        ),
        reasons=(reason,),
        candidates=tuple(candidates),
        rejected_candidates=scheduler_result.rejected_candidates,
        score_breakdown=tuple(scheduler_result.ranking.evaluations[0].score_breakdown) if scheduler_result.ranking.evaluations else (),
        policy_id="provider.routing",
        policy_version="1.0",
        inputs_snapshot=request.to_dict(),
        metadata={"scheduler_snapshot_hash": scheduler_result.scheduler_snapshot_hash},
    )


def _score_candidate(item: dict) -> DecisionCandidate:
    provider_id = str(item.get("provider_id") or item.get("id") or item.get("name") or "")
    reasons: list[DecisionReason] = []
    score = 0.0
    capabilities = set(item.get("capabilities") or ())
    required = str(item.get("required_capability") or "")
    if not required or required in capabilities or any(required.startswith(str(c).rstrip("*")) for c in capabilities):
        score += 0.35
        reasons.append(DecisionReason("CAPABILITY_MATCH", "Provider can satisfy the capability.", 0.35))
    health = str(item.get("health") or item.get("status") or "unknown")
    if health in ("ok", "healthy"):
        score += 0.25
        reasons.append(DecisionReason("PROVIDER_HEALTHY", "Provider health is good.", 0.25))
    elif health == "degraded":
        score += 0.10
        reasons.append(DecisionReason("PROVIDER_DEGRADED", "Provider is degraded but usable.", 0.10))
    success = float(item.get("success_rate", 0.5))
    score += min(max(success, 0.0), 1.0) * 0.20
    reasons.append(DecisionReason("HISTORICAL_SUCCESS", "Historical success contributes to score.", success * 0.20))
    if item.get("local") or "local" in provider_id.lower() or "ollama" in provider_id.lower():
        score += 0.10
        reasons.append(DecisionReason("PRIVACY_LOCAL", "Local provider gets privacy preference.", 0.10))
    latency = float(item.get("latency_ms", item.get("avg_latency_ms", 0)) or 0)
    if latency and latency < 1500:
        score += 0.10
        reasons.append(DecisionReason("LOW_LATENCY", "Provider latency is within target.", 0.10))
    return DecisionCandidate(candidate_id=provider_id, score=min(score, 1.0), metadata=dict(item), reasons=tuple(reasons))
