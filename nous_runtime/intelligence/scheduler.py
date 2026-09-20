"""Deterministic candidate scheduling pipeline."""

from __future__ import annotations

import math
import time
from typing import Any

from nous_runtime.intelligence._compact import (
    DIM_ORDER,
    CompactCandidate,
    optimized_pareto_reduction,
    _normalize_raw,
    _bounded,
)

from nous_runtime.platform.constraints import platform_hard_filter
from nous_runtime.platform.models import Architecture, RuntimeTier

from nous_runtime.intelligence.models import (
    CandidateConstraintResult,
    CandidateEvaluation,
    CandidateRanking,
    CandidateRejection,
    CandidateSelection,
    CandidateType,
    DecisionCandidate,
    DecisionFeature,
    DecisionReason,
    DecisionScore,
    FeatureProvenance,
    PolicyEvaluationTrace,
    SchedulingRequest,
    SchedulingResult,
    SelectionContext,
    snapshot_hash,
)

SCHEDULER_VERSION = "2.0"

PRIORITY_CLASSES = {
    "P0": 0,
    "P1": 1,
    "P2": 2,
    "P3": 3,
    "P4": 4,
    "P5": 5,
}
_RESOURCE_KEYS = ("cpu", "gpu", "memory", "disk")

DEFAULT_WEIGHTS = {
    "expected_quality": 0.18,
    "reliability": 0.16,
    "capability_fit": 0.18,
    "privacy_fit": 0.10,
    "information_gain": 0.08,
    "reversibility": 0.06,
    "cost": 0.08,
    "latency": 0.08,
    "risk": 0.06,
    "uncertainty": 0.02,
    "resource_fit": 0.10,
    "queue_fit": 0.05,
}

POSITIVE_DIMS = {"expected_quality", "reliability", "capability_fit", "privacy_fit", "information_gain", "reversibility"}
NEGATIVE_DIMS = {"cost", "latency", "risk", "uncertainty"}


class DeterministicScheduler:
    def schedule(self, request: SchedulingRequest) -> SchedulingResult:
        started = time.perf_counter()
        context = request.context
        candidates = tuple(sorted(request.candidates, key=lambda item: item.candidate_id))
        discovered = [candidate.candidate_id for candidate in candidates]

        effective_priority = _effective_priority(context)

        # Phase: platform hard-constraint pre-filter (§multi-arch)
        candidates, platform_rejected = self._apply_platform_filter(candidates, context)

        # Phase: evaluate each candidate
        evaluations = [self._evaluate_candidate(candidate, context) for candidate in candidates]

        # Phase: policy evaluation
        evaluations = self._apply_policy(evaluations, context)

        # Phase: Pareto reduction (optimized path)
        dominance_records: list[tuple[int, int, int]] = []
        if context.pareto_enabled:
            evaluations, dominance_records = self._apply_pareto_optimized(evaluations, context)

        # Phase: ranking
        evaluations = self._rank(evaluations)

        # Phase: selection
        selected = self._select(evaluations, context)

        # Phase: build trace objects (deferred from hot path)
        rejected = self._build_rejections(evaluations, dominance_records, candidates)
        constraint_trace = tuple(result for item in evaluations for result in item.constraints)
        policy_trace = self._policy_trace(context)

        # Phase: hashing (optimized — use precomputed compact data)
        ranking = CandidateRanking(tuple(evaluations), pareto_enabled=context.pareto_enabled, scheduler_version=SCHEDULER_VERSION)

        # Optimized hashing: compute directly from compact data instead of full to_dict()
        sched_hash = _fast_scheduler_hash(candidates, evaluations, context)
        scoring_hash = _fast_scoring_hash(context)

        trace = {
            "phases": [
                "task",
                "hard_constraints",
                "capability_matching",
                "security_privacy_filtering",
                "node_provider_feasibility",
                "priority_class",
                "fairness_and_aging",
                "resource_fit",
                "normalized_soft_scoring",
                "stable_tie_breaking",
                "fallback_plan_and_explanation",
            ],
            "effective_priority": effective_priority,
            "explanation": _scheduling_explanation(evaluations, selected, effective_priority),
            "discovered": discovered,
            "duration_ms": round((time.perf_counter() - started) * 1000, 3),
        }
        return SchedulingResult(
            request_id=request.request_id,
            selected=selected,
            ranking=ranking,
            rejected_candidates=rejected,
            policy_trace=policy_trace,
            constraint_trace=constraint_trace,
            scheduler_snapshot_hash=sched_hash,
            scoring_config_hash=scoring_hash,
            trace=trace,
        )

    def _apply_platform_filter(
        self,
        candidates: tuple[DecisionCandidate, ...],
        context: SelectionContext,
    ) -> tuple[tuple[DecisionCandidate, ...], list[CandidateRejection]]:
        """
        Hard-constraint pre-filter: exclude candidates on incompatible architectures.

        This MUST run before evidence, cost, or latency evaluation.
        Lite nodes (ARMv7/ARMv6) are excluded from restricted capabilities.
        """
        capability_id = str(context.constraints.get("capability_id") or "")
        if not capability_id:
            return candidates, []

        filtered: list[DecisionCandidate] = []
        rejected: list[CandidateRejection] = []

        for candidate in candidates:
            metadata = getattr(candidate, "metadata", {}) or {}
            node_arch_raw = metadata.get("platform_arch", metadata.get("arch", "amd64"))
            node_tier_raw = metadata.get("runtime_tier", metadata.get("tier", "full"))

            try:
                arch = Architecture(node_arch_raw)
            except ValueError:
                arch = Architecture.AMD64
            try:
                tier = RuntimeTier(node_tier_raw)
            except ValueError:
                tier = RuntimeTier.FULL

            allowed = platform_hard_filter(arch, tier, [capability_id])
            if allowed:
                filtered.append(candidate)
            else:
                rejected.append(CandidateRejection(
                    candidate.candidate_id,
                    "platform_hard_filter",
                    f"Node {candidate.candidate_id} ({arch.value}/{tier.value}) excluded from {capability_id}",
                    metadata={"arch": arch.value, "tier": tier.value, "capability": capability_id},
                ))

        return tuple(filtered), rejected

    def _evaluate_candidate(self, candidate: DecisionCandidate, context: SelectionContext) -> CandidateEvaluation:
        constraints = tuple(_constraint_results(candidate, context))
        rejection = next(
            (
                CandidateRejection(candidate.candidate_id, item.constraint, item.reason, metadata=item.metadata)
                for item in constraints
                if item.hard and not item.passed
            ),
            None,
        )
        features = tuple(_features(candidate, context))
        scores, uncertainty_penalty = _score_breakdown(features, context)
        normalized_score = _bounded(sum(score.value * score.weight for score in scores) - uncertainty_penalty)
        if rejection is not None:
            normalized_score = 0.0
        return CandidateEvaluation(
            candidate=candidate,
            eligible=rejection is None,
            features=features,
            constraints=constraints,
            score_breakdown=tuple(scores),
            normalized_score=normalized_score,
            uncertainty_penalty=uncertainty_penalty,
            rejection=rejection,
        )

    def _apply_policy(self, evaluations: list[CandidateEvaluation], context: SelectionContext) -> list[CandidateEvaluation]:
        force = str(context.constraints.get("force_candidate") or "")
        prefer = set(_as_list(context.constraints.get("prefer_candidates")))
        avoid = set(_as_list(context.constraints.get("avoid_candidates")))
        deny = set(_as_list(context.constraints.get("deny_candidates")))
        updated: list[CandidateEvaluation] = []
        for item in evaluations:
            candidate_id = item.candidate.candidate_id
            rejection = item.rejection
            score = item.normalized_score
            if candidate_id in deny:
                rejection = CandidateRejection(candidate_id, "POLICY_DENY", "Candidate denied by policy.", metadata={"policy": "deny"})
                score = 0.0
            elif item.eligible and candidate_id in prefer:
                score = _bounded(score + 0.08)
            elif item.eligible and candidate_id in avoid:
                score = _bounded(score - 0.08)
            elif item.eligible and force and candidate_id == force:
                score = _bounded(score + 0.20)
            updated.append(
                CandidateEvaluation(
                    candidate=item.candidate,
                    eligible=rejection is None,
                    features=item.features,
                    constraints=item.constraints,
                    score_breakdown=item.score_breakdown,
                    normalized_score=score,
                    uncertainty_penalty=item.uncertainty_penalty,
                    dominated_by=item.dominated_by,
                    rejection=rejection,
                )
            )
        return updated

    # Optimized Pareto (replaces _apply_pareto)

    def _apply_pareto_optimized(
        self,
        evaluations: list[CandidateEvaluation],
        context: SelectionContext,
    ) -> tuple[list[CandidateEvaluation], list[tuple[int, int, int]]]:
        """Optimized Pareto using compact internal representation.

        Returns (updated_evaluations, dominance_records) where
        dominance_records are (dominated_eval_idx, dominator_eval_idx, dim_mask).
        """
        # Build compact candidates (precompute feature vectors once)
        compact_list = _build_compact_from_evaluations(evaluations, context)

        # Run optimized Pareto
        _survivors, dominance_records = optimized_pareto_reduction(
            compact_list,
            preserve_fallback=bool(context.preserve_fallback_candidates),
        )

        # Apply results back to evaluations (deferred trace construction)
        dominated_indices: set[int] = set()
        dominator_map: dict[int, list[int]] = {}  # dominated_idx -> [dominator_idx, ...]
        for dom_idx, domby_idx, _dim_mask in dominance_records:
            dominated_indices.add(dom_idx)
            dominator_map.setdefault(dom_idx, []).append(domby_idx)

        result: list[CandidateEvaluation] = []
        for idx, item in enumerate(evaluations):
            if idx in dominated_indices and item.eligible:
                dominator_ids: list[str] = []
                for domby_idx in dominator_map.get(idx, []):
                    if domby_idx < len(evaluations):
                        dominator_ids.append(evaluations[domby_idx].candidate.candidate_id)
                result.append(
                    CandidateEvaluation(
                        candidate=item.candidate,
                        eligible=False,
                        features=item.features,
                        constraints=item.constraints,
                        score_breakdown=item.score_breakdown,
                        normalized_score=0.0,
                        uncertainty_penalty=item.uncertainty_penalty,
                        dominated_by=tuple(sorted(set(dominator_ids))),
                        rejection=CandidateRejection(
                            item.candidate.candidate_id,
                            "PARETO_DOMINATED",
                            "Candidate dominated on configured dimensions.",
                        ),
                    )
                )
            else:
                result.append(item)

        return result, dominance_records

    # Original Pareto (kept for reference, not used in hot path)

    def _apply_pareto(self, evaluations: list[CandidateEvaluation], context: SelectionContext) -> list[CandidateEvaluation]:
        """Legacy Pareto reduction — kept for backward compatibility testing."""
        result: list[CandidateEvaluation] = []
        eligible = [item for item in evaluations if item.eligible]
        feature_values = {_candidate_key(item): _normalized_feature_map(item) for item in eligible}
        capabilities = {_candidate_key(item): set(str(value) for value in item.candidate.metadata.get("capabilities") or ()) for item in eligible}
        for item in evaluations:
            dominators = []
            if item.eligible:
                for other in eligible:
                    if other.candidate.candidate_id == item.candidate.candidate_id:
                        continue
                    if _preserve_unique_capability_sets(capabilities[_candidate_key(item)], capabilities[_candidate_key(other)]):
                        continue
                    if _dominates_values(feature_values[_candidate_key(other)], feature_values[_candidate_key(item)]):
                        dominators.append(other.candidate.candidate_id)
            if dominators and not (context.preserve_fallback_candidates and item.candidate.metadata.get("fallback_only")):
                result.append(
                    CandidateEvaluation(
                        candidate=item.candidate,
                        eligible=False,
                        features=item.features,
                        constraints=item.constraints,
                        score_breakdown=item.score_breakdown,
                        normalized_score=0.0,
                        uncertainty_penalty=item.uncertainty_penalty,
                        dominated_by=tuple(sorted(dominators)),
                        rejection=CandidateRejection(item.candidate.candidate_id, "PARETO_DOMINATED", "Candidate dominated on configured dimensions."),
                    )
                )
            else:
                result.append(item)
        return result

    def _rank(self, evaluations: list[CandidateEvaluation]) -> list[CandidateEvaluation]:
        return sorted(
            evaluations,
            key=lambda item: (
                not item.eligible,
                -item.normalized_score,
                item.uncertainty_penalty,
                item.candidate.candidate_id,
            ),
        )

    def _select(self, evaluations: list[CandidateEvaluation], context: SelectionContext) -> CandidateSelection:
        eligible = [item for item in evaluations if item.eligible]
        force = str(context.constraints.get("force_candidate") or "")
        forced = next((item for item in eligible if item.candidate.candidate_id == force), None) if force else None
        selected = forced or (eligible[0] if eligible else None)
        if selected is None:
            return CandidateSelection(
                selected_candidate_id="",
                confidence=0.0,
                approval_required=True,
                no_safe_option=True,
                explanation="No safe candidate satisfied hard constraints.",
            )
        fallback = tuple(item.candidate.candidate_id for item in eligible if item.candidate.candidate_id != selected.candidate.candidate_id)[:3]
        return CandidateSelection(
            selected_candidate_id=selected.candidate.candidate_id,
            confidence=selected.normalized_score,
            approval_required=bool(context.constraints.get("approval_required")),
            fallback_candidates=fallback,
            explanation=f"Selected {selected.candidate.candidate_id} for {_effective_priority(context)} work with deterministic score {selected.normalized_score:.3f}.",
        )

    def _build_rejections(
        self,
        evaluations: list[CandidateEvaluation],
        dominance_records: list[tuple[int, int, int]],
        candidates: tuple[DecisionCandidate, ...],
    ) -> tuple[CandidateRejection, ...]:
        """Build full rejection objects after selection (deferred from hot path)."""
        rejections: list[CandidateRejection] = []
        for item in evaluations:
            if item.rejection is not None:
                rejections.append(item.rejection)
        return tuple(rejections)

    def _policy_trace(self, context: SelectionContext) -> tuple[PolicyEvaluationTrace, ...]:
        traces: list[PolicyEvaluationTrace] = []
        for key in ("force_candidate", "deny_candidates", "prefer_candidates", "avoid_candidates"):
            if context.constraints.get(key):
                traces.append(
                    PolicyEvaluationTrace(
                        policy_id=f"scheduler.{key}",
                        policy_version=SCHEDULER_VERSION,
                        source="scheduler.context",
                        matched=True,
                        reason=str(context.constraints.get(key)),
                    )
                )
        return tuple(traces)


# Public API

def schedule_candidates(request: SchedulingRequest) -> SchedulingResult:
    return DeterministicScheduler().schedule(request)


def scheduling_request_from_dict(data: dict[str, Any]) -> SchedulingRequest:
    context_data = dict(data.get("context") or {})
    decision_type = context_data.get("decision_type") or data.get("decision_type") or "execution"
    from nous_runtime.intelligence.models import DecisionType

    context = SelectionContext(
        task_id=str(context_data.get("task_id") or data.get("task_id") or ""),
        decision_type=DecisionType(str(decision_type)),
        constraints=dict(context_data.get("constraints") or data.get("constraints") or {}),
        weights=dict(context_data.get("weights") or data.get("weights") or {}),
        preserve_fallback_candidates=bool(context_data.get("preserve_fallback_candidates", True)),
        pareto_enabled=bool(context_data.get("pareto_enabled", True)),
        missing_value_penalty=float(context_data.get("missing_value_penalty", data.get("missing_value_penalty", 0.08))),
        metadata=dict(context_data.get("metadata") or {}),
    )
    candidates = tuple(DecisionCandidate.from_dict(dict(item)) for item in data.get("candidates") or ())
    return SchedulingRequest(
        request_id=str(data.get("request_id") or snapshot_hash({"candidates": [c.to_dict() for c in candidates], "context": context_data})),
        candidates=candidates,
        context=context,
    )


# Fast hashing (avoids full to_dict() serialization)

def _fast_scheduler_hash(
    candidates: tuple[DecisionCandidate, ...],
    evaluations: list[CandidateEvaluation],
    context: SelectionContext,
) -> str:
    """Compute scheduler snapshot hash without full to_dict() round-trip.

    Uses precomputed evaluation data directly.
    """
    import hashlib
    import json as _json

    # Build a compact hash input from the data we already have
    eval_summary = [
        {
            "id": e.candidate.candidate_id,
            "eligible": e.eligible,
            "score": round(e.normalized_score, 6),
            "uncertainty": round(e.uncertainty_penalty, 6),
            "dominated_by": list(e.dominated_by),
        }
        for e in evaluations
    ]
    hash_input = {
        "candidates": [c.candidate_id for c in candidates],
        "context": {
            "task_id": context.task_id,
            "decision_type": context.decision_type.value,
            "pareto_enabled": context.pareto_enabled,
        },
        "evaluations": eval_summary,
    }
    raw = _json.dumps(hash_input, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def _fast_scoring_hash(context: SelectionContext) -> str:
    """Compute scoring config hash from weights."""
    import hashlib
    import json as _json

    weights = _validated_weights(context.weights)
    raw = _json.dumps({"weights": weights, "missing": context.missing_value_penalty}, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


# Compact candidate builder (precomputes feature vectors once)

def _build_compact_from_evaluations(
    evaluations: list[CandidateEvaluation],
    context: SelectionContext,
) -> list[CompactCandidate]:
    """Build compact candidates from already-evaluated candidates.

    Feature extraction happens once here, not inside Pareto loops.
    """
    result: list[CompactCandidate] = []
    for idx, eval_item in enumerate(evaluations):
        if not eval_item.eligible:
            # Ineligible candidates don't participate in Pareto
            metadata = eval_item.candidate.metadata
            cap_set = frozenset(str(c) for c in (metadata.get("capabilities") or ()))
            result.append(CompactCandidate(
                index=idx,
                candidate_id=eval_item.candidate.candidate_id,
                vector=tuple(0.5 for _ in DIM_ORDER),
                eligible=False,
                cap_set=cap_set,
                fallback_tier=bool(metadata.get("fallback_only")),
            ))
            continue

        # Precompute normalized feature vector from already-extracted features
        feature_map: dict[str, float] = {}
        for feat in eval_item.features:
            if feat.name in DIM_ORDER:
                feature_map[feat.name] = _normalize_feature(feat)

        vector_parts: list[float] = []
        for dim in DIM_ORDER:
            vector_parts.append(feature_map.get(dim, 0.5))

        vector = tuple(vector_parts)

        metadata = eval_item.candidate.metadata
        caps_raw = metadata.get("capabilities") or ()
        cap_set = frozenset(str(c) for c in caps_raw)

        result.append(CompactCandidate(
            index=idx,
            candidate_id=eval_item.candidate.candidate_id,
            vector=vector,
            eligible=True,
            cap_set=cap_set,
            fallback_tier=bool(metadata.get("fallback_only")),
        ))

    return result


# Constraint evaluation

def _constraint_results(candidate: DecisionCandidate, context: SelectionContext) -> list[CandidateConstraintResult]:
    metadata = candidate.metadata
    constraints = context.constraints
    results: list[CandidateConstraintResult] = []
    required = str(constraints.get("required_capability") or "")
    capabilities = set(str(item) for item in metadata.get("capabilities") or ())
    required_permission = str(constraints.get("workspace_permission") or constraints.get("required_workspace_permission") or "")
    if required_permission:
        permissions = set(_as_list(metadata.get("workspace_permissions")))
        results.append(
            CandidateConstraintResult(
                "workspace_permission",
                required_permission in permissions,
                "" if required_permission in permissions else f"Workspace permission {required_permission} is not granted.",
            )
        )
    if required:
        passed = required in capabilities or any(item.endswith("*") and required.startswith(item[:-1]) for item in capabilities)
        results.append(CandidateConstraintResult("required_capability", passed, "" if passed else f"Missing capability {required}"))
    for key, meta_key in (
        ("modality", "modality"),
        ("privacy", "privacy"),
        ("data_residency", "data_residency"),
        ("locality", "locality"),
    ):
        expected = str(constraints.get(key) or "")
        if expected:
            actual = str(metadata.get(meta_key) or "")
            results.append(CandidateConstraintResult(key, actual == expected, "" if actual == expected else f"Expected {expected}, got {actual or 'unknown'}"))
    allowed_models = set(_as_list(constraints.get("allowed_models")))
    denied_models = set(_as_list(constraints.get("denied_models")))
    model = str(metadata.get("model") or "")
    if allowed_models:
        results.append(
            CandidateConstraintResult(
                "allowed_models",
                bool(model) and model in allowed_models,
                f"Model {model or 'unknown'} is not allowed.",
            )
        )
    if denied_models and model:
        results.append(CandidateConstraintResult("denied_models", model not in denied_models, f"Model {model} is denied."))
    _max_constraint(results, "max_cost", metadata.get("cost"), constraints.get("max_cost"))
    _max_constraint(results, "max_latency", metadata.get("latency_ms", metadata.get("avg_latency_ms")), constraints.get("max_latency_ms"))
    if constraints.get("tool_calling_required"):
        results.append(CandidateConstraintResult("tool_calling_required", bool(metadata.get("tool_calling")), "Tool calling required."))
    if constraints.get("structured_output_required"):
        results.append(CandidateConstraintResult("structured_output_required", bool(metadata.get("structured_output")), "Structured output required."))
    if constraints.get("availability_required", True):
        status = str(metadata.get("health") or metadata.get("status") or "unknown")
        results.append(CandidateConstraintResult("availability", status not in {"down", "unavailable", "disabled"}, f"Availability is {status}."))
    allowed_providers = set(_as_list(constraints.get("allowed_providers")))
    denied_providers = set(_as_list(constraints.get("denied_providers")))
    provider = str(metadata.get("provider_id") or candidate.candidate_id)
    risk_ceiling = _risk_value(constraints.get("risk_ceiling"))
    risk = _risk_value(metadata.get("risk"))
    if risk_ceiling is not None:
        results.append(
            CandidateConstraintResult(
                "risk_ceiling",
                risk is not None and risk <= risk_ceiling,
                "Risk is unknown or exceeds ceiling.",
            )
        )
    node_online_required = bool(constraints.get("node_online_required")) or "node_online" in metadata
    if node_online_required:
        results.append(
            CandidateConstraintResult(
                "node_online",
                metadata.get("node_online") is True,
                "Node is offline or online state is unknown.",
            )
        )
    required_resources = dict(constraints.get("required_resources") or {})
    if required_resources:
        available = dict(metadata.get("available_resources") or metadata.get("resources_available") or {})
        for resource, required_value in sorted(required_resources.items()):
            _minimum_constraint(results, f"node_capacity.{resource}", available.get(resource), required_value)
    circuit_required = bool(constraints.get("provider_circuit_required_closed")) or "circuit_state" in metadata
    if circuit_required:
        circuit = str(metadata.get("circuit_state") or "unknown").lower()
        results.append(CandidateConstraintResult("provider_circuit", circuit in {"closed", "healthy"}, f"Provider circuit is {circuit}."))
    rate_required = bool(constraints.get("provider_rate_limit_required")) or "rate_limit_state" in metadata
    if rate_required:
        rate_state = str(metadata.get("rate_limit_state") or "unknown").lower()
        results.append(CandidateConstraintResult("provider_rate_limit", rate_state in {"ok", "available"}, f"Provider rate limit is {rate_state}."))
    resource_budget = dict(constraints.get("resource_budget") or {})
    if resource_budget:
        usage = dict(metadata.get("resource_usage") or metadata.get("resource_costs") or {})
        for resource, limit in sorted(resource_budget.items()):
            _max_constraint(results, f"resource_budget.{resource}", usage.get(resource), limit)
    required_approval = str(constraints.get("required_approval_state") or "")
    if required_approval:
        approval_state = str(context.metadata.get("approval_state") or metadata.get("approval_state") or "unknown")
        results.append(
            CandidateConstraintResult(
                "required_approval_state",
                approval_state == required_approval,
                f"Approval state is {approval_state}; {required_approval} is required.",
            )
        )
    user_limit = constraints.get("per_user_concurrency_limit")
    if user_limit is not None:
        _below_limit(results, "per_user_concurrency", context.metadata.get("active_user_runs"), user_limit)
    workspace_limit = constraints.get("per_workspace_concurrency_limit")
    if workspace_limit is not None:
        _below_limit(results, "per_workspace_concurrency", context.metadata.get("active_workspace_runs"), workspace_limit)
    workflow_limit = constraints.get("max_workers_per_workflow")
    if workflow_limit is not None:
        _below_limit(results, "workflow_worker_share", metadata.get("workflow_active_workers"), workflow_limit)
    if _effective_priority(context) in {"P3", "P4", "P5"}:
        reserved = constraints.get("interactive_capacity_reservation")
        if reserved is not None:
            _above_reservation(results, metadata.get("available_worker_slots"), reserved)
    if allowed_providers:
        results.append(CandidateConstraintResult("allowed_providers", provider in allowed_providers, f"Provider {provider} is not allowed."))
    if denied_providers:
        results.append(CandidateConstraintResult("denied_providers", provider not in denied_providers, f"Provider {provider} is denied."))
    return results


def _features(candidate: DecisionCandidate, context: SelectionContext) -> list[DecisionFeature]:
    metadata = candidate.metadata
    stale = set(_as_list(metadata.get("stale_features")))
    features = [
        _feature("expected_quality", metadata.get("quality", metadata.get("expected_quality")), default_source="candidate"),
        _feature("reliability", metadata.get("success_rate", metadata.get("reliability")), default_source="candidate"),
        _feature("capability_fit", _capability_fit(metadata, context), default_source="scheduler", confidence=1.0),
        _feature("privacy_fit", metadata.get("privacy_fit", 1.0 if metadata.get("local") else None), default_source="candidate"),
        _feature("information_gain", metadata.get("information_gain"), default_source="candidate"),
        _feature("reversibility", metadata.get("reversibility"), default_source="candidate"),
        _feature("cost", metadata.get("cost"), unit="currency", default_source="candidate"),
        _feature("resource_fit", _resource_fit(metadata, context), default_source="scheduler", confidence=1.0),
        _feature("queue_fit", _queue_fit(metadata), default_source="scheduler", confidence=0.8),
        _feature("latency", metadata.get("latency_ms", metadata.get("avg_latency_ms")), unit="ms", default_source="candidate"),
        _feature("risk", _risk_value(metadata.get("risk")), default_source="candidate"),
    ]
    features = [_mark_stale(feature) if feature.name in stale else feature for feature in features]
    unknown_count = sum(1 for item in features if item.provenance_type == FeatureProvenance.UNKNOWN)
    features.append(_feature("uncertainty", unknown_count / max(len(features), 1), default_source="scheduler", confidence=1.0))
    return features


def _mark_stale(feature: DecisionFeature) -> DecisionFeature:
    return DecisionFeature(
        name=feature.name,
        value=feature.value,
        normalized=feature.normalized,
        unit=feature.unit,
        source=feature.source,
        provenance_type=FeatureProvenance.STALE,
        confidence=feature.confidence,
        observed_at=feature.observed_at,
        expires_at=feature.expires_at,
        stale=True,
    )


def _score_breakdown(features: tuple[DecisionFeature, ...], context: SelectionContext) -> tuple[list[DecisionScore], float]:
    weights = _validated_weights(context.weights)
    scores: list[DecisionScore] = []
    uncertainty_penalty = 0.0
    for feature in features:
        weight = weights.get(feature.name, 0.0)
        if weight <= 0:
            continue
        normalized = _normalize_feature(feature)
        missing = feature.provenance_type in {FeatureProvenance.UNKNOWN, FeatureProvenance.STALE} or feature.value is None
        if missing:
            uncertainty_penalty += context.missing_value_penalty * weight
        scores.append(DecisionScore(feature.name, normalized, weight=weight, metadata={"source": feature.source, "provenance": feature.provenance_type.value}))
    return scores, _bounded(uncertainty_penalty)


def _normalize_feature(feature: DecisionFeature) -> float:
    return _normalize_raw(feature.name, feature.value)


# Legacy Pareto helpers (kept for backward compat / testing)

def _normalized_feature_map(evaluation: CandidateEvaluation) -> dict[str, float]:
    return {feature.name: _normalize_feature(feature) for feature in evaluation.features}


def _dominates_values(left_values: dict[str, float], right_values: dict[str, float]) -> bool:
    dims = sorted(POSITIVE_DIMS | NEGATIVE_DIMS)
    better_or_equal = all(left_values.get(dim, 0.5) >= right_values.get(dim, 0.5) for dim in dims)
    strictly_better = any(left_values.get(dim, 0.5) > right_values.get(dim, 0.5) for dim in dims)
    return better_or_equal and strictly_better


def _preserve_unique_capability_sets(own: set[str], competing: set[str]) -> bool:
    return bool(own - competing)


def _candidate_key(item: CandidateEvaluation) -> str:
    return item.candidate.candidate_id


def _feature(name: str, value: Any, *, unit: str = "", default_source: str, confidence: float = 0.6) -> DecisionFeature:
    provenance = FeatureProvenance.UNKNOWN if value is None else FeatureProvenance.OBSERVED
    return DecisionFeature(
        name=name,
        value=value,
        unit=unit,
        source=default_source,
        provenance_type=provenance,
        confidence=0.0 if value is None else confidence,
        stale=provenance == FeatureProvenance.STALE,
    )


def _capability_fit(metadata: dict[str, Any], context: SelectionContext) -> float | None:
    required = str(context.constraints.get("required_capability") or "")
    if not required:
        return 1.0
    capabilities = set(str(item) for item in metadata.get("capabilities") or ())
    return 1.0 if required in capabilities or any(item.endswith("*") and required.startswith(item[:-1]) for item in capabilities) else 0.0


def _max_constraint(results: list[CandidateConstraintResult], name: str, actual: Any, limit: Any) -> None:
    if limit is None or limit == "":
        return
    try:
        limit_value = float(limit)
        actual_value = float(actual)
    except (TypeError, ValueError):
        results.append(CandidateConstraintResult(name, False, f"{name} requires known numeric value."))
        return
    results.append(CandidateConstraintResult(name, actual_value <= limit_value, f"{actual_value} exceeds {limit_value}."))


def _risk_value(value: Any) -> float | None:
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return {"low": 0.2, "medium": 0.5, "high": 0.8, "critical": 1.0}.get(str(value).lower())


def _minimum_constraint(results: list[CandidateConstraintResult], name: str, actual: Any, required: Any) -> None:
    try:
        actual_value = float(actual)
        required_value = float(required)
    except (TypeError, ValueError):
        results.append(CandidateConstraintResult(name, False, f"{name} requires known numeric capacity."))
        return
    results.append(CandidateConstraintResult(name, actual_value >= required_value, f"{actual_value} is below required {required_value}."))


def _below_limit(results: list[CandidateConstraintResult], name: str, actual: Any, limit: Any) -> None:
    try:
        actual_value = int(actual)
        limit_value = int(limit)
    except (TypeError, ValueError):
        results.append(CandidateConstraintResult(name, False, f"{name} requires known concurrency state."))
        return
    results.append(CandidateConstraintResult(name, actual_value < limit_value, f"{name} limit {limit_value} is reached."))


def _above_reservation(results: list[CandidateConstraintResult], actual: Any, reserved: Any) -> None:
    try:
        actual_value = int(actual)
        reserved_value = int(reserved)
    except (TypeError, ValueError):
        results.append(CandidateConstraintResult("interactive_capacity_reservation", False, "Worker capacity is unknown."))
        return
    results.append(
        CandidateConstraintResult(
            "interactive_capacity_reservation",
            actual_value > reserved_value,
            f"{reserved_value} interactive worker slots must remain reserved.",
        )
    )


def _resource_fit(metadata: dict[str, Any], context: SelectionContext) -> float | None:
    required = dict(context.constraints.get("required_resources") or {})
    available = dict(metadata.get("available_resources") or metadata.get("resources_available") or {})
    if not required:
        return metadata.get("resource_fit")
    ratios: list[float] = []
    for resource in _RESOURCE_KEYS:
        if resource not in required:
            continue
        try:
            need = float(required[resource])
            capacity = float(available[resource])
        except (KeyError, TypeError, ValueError):
            return None
        ratios.append(1.0 if need <= 0 else min(capacity / need, 2.0) / 2.0)
    return sum(ratios) / len(ratios) if ratios else None


def _queue_fit(metadata: dict[str, Any]) -> float | None:
    values: list[float] = []
    for key, ceiling in (("network_rtt_ms", 2000.0), ("node_queue_depth", 100.0), ("provider_latency_ms", 5000.0)):
        if metadata.get(key) is None:
            continue
        try:
            values.append(1.0 - min(max(float(metadata[key]), 0.0), ceiling) / ceiling)
        except (TypeError, ValueError):
            continue
    if metadata.get("provider_failure_rate") is not None:
        try:
            values.append(1.0 - min(max(float(metadata["provider_failure_rate"]), 0.0), 1.0))
        except (TypeError, ValueError):
            pass
    return sum(values) / len(values) if values else None


def _effective_priority(context: SelectionContext) -> str:
    requested = str(context.metadata.get("priority_class") or context.constraints.get("priority_class") or "P3").upper()
    base = PRIORITY_CLASSES.get(requested, PRIORITY_CLASSES["P3"])
    try:
        queued_seconds = max(float(context.metadata.get("queued_seconds") or 0.0), 0.0)
        aging_seconds = max(float(context.constraints.get("aging_seconds_per_class") or 300.0), 1.0)
    except (TypeError, ValueError):
        queued_seconds, aging_seconds = 0.0, 300.0
    promoted = min(int(queued_seconds // aging_seconds), base)
    return f"P{base - promoted}"


def _scheduling_explanation(
    evaluations: list[CandidateEvaluation],
    selected: CandidateSelection,
    effective_priority: str,
) -> dict[str, Any]:
    return {
        "candidates_considered": [item.candidate.candidate_id for item in evaluations],
        "candidates_rejected": [item.candidate.candidate_id for item in evaluations if not item.eligible],
        "hard_rejection_reasons": {
            item.candidate.candidate_id: [constraint.reason for constraint in item.constraints if constraint.hard and not constraint.passed]
            for item in evaluations
            if not item.eligible
        },
        "normalized_score_components": {
            item.candidate.candidate_id: {score.name: score.value for score in item.score_breakdown}
            for item in evaluations
        },
        "missing_data": {
            item.candidate.candidate_id: [feature.name for feature in item.features if feature.value is None or feature.stale]
            for item in evaluations
        },
        "effective_priority": effective_priority,
        "selected_candidate": selected.selected_candidate_id,
        "fallback_order": list(selected.fallback_candidates),
    }




def _validated_weights(weights: dict[str, float]) -> dict[str, float]:
    merged = dict(DEFAULT_WEIGHTS)
    merged.update({str(key): float(value) for key, value in weights.items() if _finite_number(value)})
    total = sum(max(value, 0.0) for value in merged.values())
    if total <= 0:
        return dict(DEFAULT_WEIGHTS)
    return {key: max(value, 0.0) / total for key, value in merged.items()}


def _finite_number(value: Any) -> bool:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return False
    return math.isfinite(parsed)


def _as_list(value: Any) -> list[str]:
    if value is None or value == "":
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, (list, tuple, set)):
        return [str(item) for item in value]
    return [str(value)]


# Candidate factory helpers

def candidates_from_provider_context(items: tuple[dict[str, Any], ...]) -> tuple[DecisionCandidate, ...]:
    candidates = []
    for item in items:
        provider_id = str(item.get("provider_id") or item.get("id") or item.get("name") or "")
        if not provider_id:
            continue
        candidates.append(
            DecisionCandidate(
                candidate_id=provider_id,
                candidate_type=CandidateType.PROVIDER,
                metadata=dict(item),
                reasons=(DecisionReason("PROVIDER_CANDIDATE", "Provider candidate discovered from context."),),
            )
        )
    return tuple(candidates)


def retrieval_strategy_candidates(metadata: dict[str, Any] | None = None) -> tuple[DecisionCandidate, ...]:
    base = dict(metadata or {})
    return (
        DecisionCandidate(
            "enabled",
            candidate_type=CandidateType.RETRIEVAL_STRATEGY,
            metadata={**base, "information_gain": 0.8, "cost": 0.05, "latency_ms": 80, "risk": "low"},
        ),
        DecisionCandidate(
            "disabled",
            candidate_type=CandidateType.RETRIEVAL_STRATEGY,
            metadata={**base, "information_gain": 0.2, "cost": 0.0, "latency_ms": 0, "risk": "low"},
        ),
    )


def recovery_strategy_candidates(category: str) -> tuple[DecisionCandidate, ...]:
    strategies = {
        "fallback": {"reliability": 0.75, "latency_ms": 400, "risk": "medium"},
        "retry_once": {"reliability": 0.55, "latency_ms": 250, "risk": "low"},
        "retry": {"reliability": 0.50, "latency_ms": 500, "risk": "medium"},
        "stop": {"reliability": 1.0, "latency_ms": 0, "risk": "low", "approval_required": True},
    }
    return tuple(
        DecisionCandidate(
            candidate_id=name,
            candidate_type=CandidateType.RECOVERY_STRATEGY,
            metadata={**data, "error_category": category},
        )
        for name, data in strategies.items()
    )
