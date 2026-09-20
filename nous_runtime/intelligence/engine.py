"""Runtime Policy Engine."""

from __future__ import annotations

from nous_runtime.intelligence.decisions.capability import capability_decision
from nous_runtime.intelligence.decisions.provider import provider_decision
from nous_runtime.intelligence.decisions.recovery import recovery_decision
from nous_runtime.intelligence.decisions.retrieval import retrieval_decision
from nous_runtime.intelligence.models import (
    DecisionOutcome,
    DecisionReason,
    DecisionRequest,
    DecisionType,
    RuntimeDecision,
    decision_id_for,
)
from nous_runtime.intelligence.policies.rule import RulePolicy
from nous_runtime.intelligence.policies.static import StaticPolicy
from nous_runtime.intelligence.registry import PolicyRegistry


class RuntimePolicyEngine:
    def __init__(self, registry: PolicyRegistry | None = None, *, prefer_registry: bool = False):
        self.registry = registry or default_registry()
        self.prefer_registry = prefer_registry

    @classmethod
    def from_workspace(cls, workspace_path: str) -> "RuntimePolicyEngine":
        from nous_runtime.intelligence.policy_loader import load_workspace_policies

        loaded = load_workspace_policies(workspace_path)
        registry = loaded.registry
        for policy in default_registry().list():
            if not any(existing.policy_id == policy.policy_id for existing in registry.list()):
                registry.register(policy, metadata={"source": "system.default"})
        return cls(registry, prefer_registry=True)

    def decide(self, request: DecisionRequest, *, dry_run: bool = False) -> RuntimeDecision:
        override = _explicit_override(request)
        if override:
            return override
        matches = self.registry.resolve(request)
        if self.prefer_registry and matches:
            return _attach_policy_metadata(matches[0].decide(request), self.registry.metadata_for(matches[0].policy_id))
        if request.decision_type == DecisionType.RETRIEVAL:
            return retrieval_decision(request)
        if request.decision_type == DecisionType.PROVIDER:
            return provider_decision(request)
        if request.decision_type == DecisionType.CAPABILITY:
            return capability_decision(request)
        if request.decision_type in (DecisionType.RETRY, DecisionType.FALLBACK):
            return recovery_decision(request)
        if matches:
            return _attach_policy_metadata(matches[0].decide(request), self.registry.metadata_for(matches[0].policy_id))
        return _default_decision(request, dry_run=dry_run)

    def explain(self, decision: RuntimeDecision) -> str:
        reasons = "; ".join(f"{r.code}: {r.message}" for r in decision.reasons)
        return (
            f"{decision.decision_type.value} selected {decision.selected} "
            f"via {decision.policy_id} confidence={decision.confidence:.2f}. {reasons}"
        )


# Backward-compatible public name retained for v1 clients.
IntelligenceEngine = RuntimePolicyEngine

def default_registry() -> PolicyRegistry:
    reg = PolicyRegistry()
    reg.register(
        RulePolicy(
            policy_id="retrieval.question.default",
            version="1.0",
            decision_type=DecisionType.RETRIEVAL.value,
            priority=100,
            conditions=(
                {"field": "context.task_kind", "operator": "in", "value": ["question", "research", "code"]},
                {"field": "context.retrieval_available", "operator": "eq", "value": True},
            ),
            action={"selected": "enabled", "confidence": 0.75},
            reason_code="TASK_KIND_NEEDS_CONTEXT",
            reason_message="Task kind benefits from project retrieval.",
        )
    )
    for dtype in DecisionType:
        reg.register(StaticPolicy(f"{dtype.value}.default", "1.0", dtype.value, "default", priority=0, confidence=0.5))
    return reg


def default_engine() -> RuntimePolicyEngine:
    return RuntimePolicyEngine(default_registry())


def _explicit_override(request: DecisionRequest) -> RuntimeDecision | None:
    overrides = request.context.explicit_overrides
    key = request.decision_type.value
    if key not in overrides:
        return None
    selected = str(overrides[key])
    reason = DecisionReason(
        code="EXPLICIT_USER_OVERRIDE",
        message="Explicit override has highest policy priority.",
        weight=1.0,
    )
    return RuntimeDecision(
        decision_id=decision_id_for(request, "explicit.override", selected),
        task_id=request.task_id,
        decision_type=request.decision_type,
        outcome=DecisionOutcome(selected=selected, confidence=1.0),
        reasons=(reason,),
        policy_id="explicit.override",
        policy_version="1.0",
        inputs_snapshot=request.to_dict(),
    )


def _default_decision(request: DecisionRequest, *, dry_run: bool = False) -> RuntimeDecision:
    selected = "dry_run" if dry_run else "default"
    reason = DecisionReason(
        code="DEFAULT_POLICY",
        message="No higher priority policy matched.",
        weight=0.5,
    )
    return RuntimeDecision(
        decision_id=decision_id_for(request, "runtime.default", selected),
        task_id=request.task_id,
        decision_type=request.decision_type,
        outcome=DecisionOutcome(selected=selected, confidence=0.5),
        reasons=(reason,),
        policy_id="runtime.default",
        policy_version="1.0",
        inputs_snapshot=request.to_dict(),
    )


def _attach_policy_metadata(decision: RuntimeDecision, metadata: dict) -> RuntimeDecision:
    if not metadata:
        return decision
    policy_hash = str(metadata.get("policy_hash") or "")
    source = str(metadata.get("source") or "")
    hashes = dict(decision.policy_hashes)
    sources = dict(decision.policy_sources)
    if policy_hash:
        hashes[decision.policy_id] = policy_hash
    if source:
        sources[decision.policy_id] = source
    merged_metadata = {**dict(decision.metadata), "policy_metadata": dict(metadata)}
    return RuntimeDecision(
        decision_id=decision.decision_id,
        task_id=decision.task_id,
        decision_type=decision.decision_type,
        outcome=decision.outcome,
        reasons=decision.reasons,
        schema_version=decision.schema_version,
        runtime_version=decision.runtime_version,
        status=decision.status,
        plan_id=decision.plan_id,
        trace_id=decision.trace_id,
        parent_decision_id=decision.parent_decision_id,
        candidates=decision.candidates,
        constraints=decision.constraints,
        rejected_candidates=decision.rejected_candidates,
        score_breakdown=decision.score_breakdown,
        fallback_plan=decision.fallback_plan,
        policy_ids=decision.policy_ids,
        policy_versions=decision.policy_versions,
        policy_sources=sources,
        policy_hashes=hashes,
        policy_id=decision.policy_id,
        policy_version=decision.policy_version,
        inputs_snapshot=decision.inputs_snapshot,
        context_snapshot=decision.context_snapshot,
        candidate_snapshot=decision.candidate_snapshot,
        override_metadata=decision.override_metadata,
        explanation=decision.explanation,
        metadata=merged_metadata,
        created_at=decision.created_at,
    )
