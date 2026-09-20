# -*- coding: utf-8 -*-
"""Constraint Engine — evaluates Execution Plans against hard/soft constraints."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .definitions import HARD_CONSTRAINTS, SOFT_PREFERENCES, HardConstraint, SoftPreference


@dataclass
class ConstraintResult:
    """Result of evaluating a plan against all constraints."""
    feasible: bool = True
    hard_constraints_passed: int = 0
    hard_constraints_failed: int = 0
    violated_constraints: list[dict] = field(default_factory=list)  # [{name, reason, evidence}]
    soft_scores: dict[str, float] = field(default_factory=dict)  # preference_name → score
    rejection_reason: str = ""
    policy_references: list[str] = field(default_factory=list)


class ConstraintEngine:
    """Evaluates Execution Plans against hard constraints and soft preferences.

    Hard constraints are binary (pass/fail). Any failure → plan INFEASIBLE.
    Soft preferences produce scores used in Pareto ranking.
    """

    def evaluate(self, plan: dict[str, Any], context: dict[str, Any]) -> ConstraintResult:
        """Evaluate a plan against all constraints."""
        result = ConstraintResult()

        # Hard constraints
        for hc in HARD_CONSTRAINTS:
            ok, reason, evidence = self._check_hard(hc, plan, context)
            if ok:
                result.hard_constraints_passed += 1
            else:
                result.feasible = False
                result.hard_constraints_failed += 1
                result.violated_constraints.append({
                    "name": hc.name,
                    "reason": reason,
                    "evidence": evidence,
                    "policy_reference": hc.policy_reference,
                })
                result.policy_references.append(hc.policy_reference)

        # Soft preferences
        for sp in SOFT_PREFERENCES:
            score = self._score_soft(sp, plan, context)
            result.soft_scores[sp.name] = score

        # Rejection summary
        if not result.feasible:
            violations = [v["name"] for v in result.violated_constraints]
            result.rejection_reason = f"Hard constraints violated: {', '.join(violations)}"

        return result

    # Hard constraint checkers

    def _check_hard(self, hc: HardConstraint, plan: dict, ctx: dict) -> tuple[bool, str, str]:
        """Dispatch to specific constraint checker."""
        checker = getattr(self, f"_check_{hc.name}", None)
        if checker is None:
            return True, "", ""
        return checker(plan, ctx)

    def _check_privacy_class(self, plan: dict, ctx: dict) -> tuple[bool, str, str]:
        required = str(ctx.get("privacy_class", "") or "internal").lower()
        model_privacy = str(plan.get("model_privacy_class", "") or "").lower()
        node_trust = str(plan.get("node_trust_zone", "") or "").lower()

        if required == "restricted":
            if model_privacy != "restricted":
                return False, f"Model privacy class {model_privacy} insufficient for restricted data", f"required=restricted, got={model_privacy}"
            if node_trust != "restricted":
                return False, f"Node trust zone {node_trust} insufficient for restricted data", f"required=restricted, got={node_trust}"
        elif required == "confidential":
            if model_privacy not in ("confidential", "restricted"):
                return False, f"Model privacy class {model_privacy} insufficient", f"required=confidential, got={model_privacy}"
        return True, "", ""

    def _check_data_residency(self, plan: dict, ctx: dict) -> tuple[bool, str, str]:
        required_region = str(ctx.get("data_residency", "") or "")
        plan_locality = str(plan.get("execution_locality", "") or "")
        if required_region and plan_locality:
            if required_region.lower() != plan_locality.lower() and plan_locality != "any":
                return False, f"Data residency {required_region} not satisfied by {plan_locality}", ""
        return True, "", ""

    def _check_model_capability(self, plan: dict, ctx: dict) -> tuple[bool, str, str]:
        required = str(ctx.get("min_capability_level", "") or "").lower()
        model_cap = str(plan.get("model_capability_level", "") or "").lower()
        levels = {"expert": 5, "advanced": 4, "competent": 3, "basic": 2, "novice": 1}
        req_level = levels.get(required, 0)
        model_level = levels.get(model_cap, 0)
        if req_level > 0 and model_level < req_level:
            return False, f"Model capability {model_cap} below required {required}", f"required={req_level}, got={model_level}"
        return True, "", ""

    def _check_model_license(self, plan: dict, ctx: dict) -> tuple[bool, str, str]:
        required = str(ctx.get("license_requirement", "") or "")
        model_license = str(plan.get("model_license", "") or "")
        if required == "open_source" and model_license not in ("apache-2.0", "mit", "bsd", "gpl", "open-source"):
            return False, f"Model license {model_license} does not satisfy open-source requirement", ""
        if required == "commercial" and model_license in ("non-commercial", "research-only"):
            return False, f"Model license {model_license} not compatible with commercial use", ""
        return True, "", ""

    def _check_node_architecture(self, plan: dict, ctx: dict) -> tuple[bool, str, str]:
        required = str(ctx.get("required_arch", "") or "")
        node_arch = str(plan.get("node_architecture", "") or "")
        if required and node_arch and required != node_arch:
            return False, f"Architecture mismatch: required {required}, got {node_arch}", ""
        return True, "", ""

    def _check_available_memory(self, plan: dict, ctx: dict) -> tuple[bool, str, str]:
        required_mb = int(ctx.get("min_memory_mb", 0) or 0)
        available_mb = int(plan.get("available_memory_mb", 0) or 0)
        if required_mb > 0 and available_mb < required_mb:
            return False, f"Insufficient memory: need {required_mb}MB, have {available_mb}MB", ""
        return True, "", ""

    def _check_available_gpu(self, plan: dict, ctx: dict) -> tuple[bool, str, str]:
        requires_gpu = bool(ctx.get("requires_gpu", False))
        has_gpu = bool(plan.get("has_gpu", False))
        if requires_gpu and not has_gpu:
            return False, "GPU required but not available on node", ""
        return True, "", ""

    def _check_budget_ceiling(self, plan: dict, ctx: dict) -> tuple[bool, str, str]:
        budget = float(ctx.get("budget_usd", 0) or 0)
        estimated_cost = float(plan.get("estimated_cost_usd", 0) or 0)
        if budget > 0 and estimated_cost > budget:
            return False, f"Estimated cost ${estimated_cost:.4f} exceeds budget ${budget:.2f}", ""
        return True, "", ""

    def _check_deadline(self, plan: dict, ctx: dict) -> tuple[bool, str, str]:
        deadline_s = int(ctx.get("deadline_seconds", 0) or 0)
        estimated_ms = float(plan.get("estimated_latency_ms", 0) or 0)
        if deadline_s > 0 and estimated_ms > deadline_s * 1000:
            return False, f"Estimated latency {estimated_ms:.0f}ms exceeds deadline {deadline_s}s", ""
        return True, "", ""

    def _check_network_availability(self, plan: dict, ctx: dict) -> tuple[bool, str, str]:
        required_endpoints = ctx.get("required_endpoints", []) or []
        node_network = str(plan.get("node_network_type", "") or "local")
        if required_endpoints and node_network == "isolated":
            return False, f"Node is isolated but {len(required_endpoints)} endpoints required", ""
        return True, "", ""

    def _check_tool_permission(self, plan: dict, ctx: dict) -> tuple[bool, str, str]:
        required_tools = ctx.get("required_tools", []) or []
        permitted_tools = plan.get("permitted_tools", []) or []
        forbidden = [t for t in required_tools if t not in permitted_tools]
        if forbidden:
            return False, f"Tools not permitted: {forbidden}", ""
        return True, "", ""

    def _check_file_permission(self, plan: dict, ctx: dict) -> tuple[bool, str, str]:
        write_scope = str(plan.get("write_scope", "") or "readonly")
        if write_scope == "external":
            return False, "Plan requires external write scope which exceeds file permissions", ""
        return True, "", ""

    def _check_safety_policy(self, plan: dict, ctx: dict) -> tuple[bool, str, str]:
        risk_class = str(ctx.get("risk_class", "") or "low")
        plan_safety = str(plan.get("safety_checks", "") or "")
        if risk_class in ("high", "critical") and "safety_review" not in plan_safety:
            return False, f"High-risk task ({risk_class}) requires safety review in plan", ""
        return True, "", ""

    def _check_approval_requirement(self, plan: dict, ctx: dict) -> tuple[bool, str, str]:
        requires_approval = bool(ctx.get("requires_approval", False))
        plan_has_approval = bool(plan.get("approval_mechanism", False))
        if requires_approval and not plan_has_approval:
            return False, "Task requires approval but plan has no approval mechanism", ""
        return True, "", ""

    # Soft preference scorers

    def _score_soft(self, sp: SoftPreference, plan: dict, ctx: dict) -> float:
        """Score a plan against a soft preference (0-1, higher = better unless higher_is_better=False)."""
        scorer = getattr(self, f"_score_{sp.name}", None)
        if scorer is None:
            return 0.5  # neutral
        raw = scorer(plan, ctx)
        return raw if sp.higher_is_better else 1.0 - raw

    def _score_cost_efficiency(self, plan: dict, ctx: dict) -> float:
        cost = float(plan.get("estimated_cost_usd", 0.01) or 0.01)
        max_cost = float(ctx.get("budget_usd", cost * 10) or cost * 10)
        return max(0.0, min(1.0, 1.0 - (cost / max(max_cost, 0.001))))

    def _score_latency_minimization(self, plan: dict, ctx: dict) -> float:
        lat = float(plan.get("estimated_latency_ms", 1000) or 1000)
        deadline = float(ctx.get("deadline_seconds", 300) or 300) * 1000
        return max(0.0, min(1.0, 1.0 - (lat / max(deadline, 1))))

    def _score_quality_maximization(self, plan: dict, ctx: dict) -> float:
        levels = {"expert": 1.0, "advanced": 0.8, "competent": 0.6, "basic": 0.4, "novice": 0.2}
        return levels.get(str(plan.get("model_capability_level", "basic")).lower(), 0.4)

    def _score_reliability(self, plan: dict, ctx: dict) -> float:
        return float(plan.get("model_success_rate", 0.8) or 0.8)

    def _score_reproducibility(self, plan: dict, ctx: dict) -> float:
        temp = float(plan.get("model_temperature", 0.0) or 0.0)
        return 1.0 - min(1.0, temp)  # lower temperature = more reproducible

    def _score_resource_efficiency(self, plan: dict, ctx: dict) -> float:
        mem = float(plan.get("estimated_memory_mb", 1000) or 1000)
        return max(0.0, min(1.0, 1.0 - (mem / 32000)))  # normalize against 32GB

    def _score_novelty(self, plan: dict, ctx: dict) -> float:
        return float(plan.get("novelty_score", 0.0) or 0.0)
