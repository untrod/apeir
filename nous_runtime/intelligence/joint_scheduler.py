# -*- coding: utf-8 -*-
"""
Evidence-Driven Joint Scheduler for Nous Runtime.

Implements §13 (Evidence-Driven Joint Scheduling) of the master plan.

The scheduler selects not just a model, but the complete execution path:
    Model + Node + Tools + Context + Permissions + Budget + Verification

Scheduling flow:
    Hard constraints → Node availability → Model compatibility →
    Historical evidence → Cost/latency estimation → Selection →
    Execution → Verification → Fallback/Review → Evidence update

Early phase: deterministic hard rules + user defaults + clear data-insufficient markers.
Later: Bayesian update, contextual bandit, Pareto multi-objective, drift detection.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from nous_runtime.kernel.error_codes import ErrorCode, NousResult
from nous_runtime.kernel.task import TaskFingerprint

log = logging.getLogger("nous.intelligence.scheduler")


# Execution Path

@dataclass
class ExecutionPath:
    """A candidate execution path for a task."""
    model_instance_key: str = ""         # provider/model/quant/runtime/hardware
    node_id: str = ""
    node_name: str = ""
    tool_ids: list[str] = field(default_factory=list)
    estimated_cost_cents: int = 0
    estimated_latency_ms: int = 0
    estimated_success_rate: float = 0.5
    evidence_level: int = 0              # How much evidence backs this estimate
    evidence_sample_count: int = 0
    score: float = 0.0                   # Composite score


@dataclass(frozen=True)
class ExecutionPlan:
    """A bounded set of independently schedulable execution lanes."""

    paths: tuple[ExecutionPath, ...]
    requested_lanes: int
    scheduled_lanes: int
    degraded: bool = False


# Scheduling constraints

@dataclass
class SchedulingConstraints:
    """Hard constraints that filter candidate execution paths."""
    required_capabilities: list[str] = field(default_factory=list)
    denied_models: list[str] = field(default_factory=list)
    preferred_models: list[str] = field(default_factory=list)
    preferred_nodes: list[str] = field(default_factory=list)
    allowed_nodes: list[str] = field(default_factory=list)
    required_node_capabilities: list[str] = field(default_factory=list)
    allowed_trust_zones: list[str] = field(default_factory=list)
    authorized_assets: list[str] = field(default_factory=list)
    max_parallel_lanes: int = 1
    max_cost_cents: int = 0              # 0 = unlimited
    max_latency_ms: int = 0              # 0 = unlimited
    privacy_required: bool = False       # Must use local model
    require_verification: bool = True


# Joint Scheduler

class JointScheduler:
    """Selects the best model + node + tool combination for a task.

    Combines hard constraint filtering with evidence-based scoring.
    Early phase uses deterministic rules; later phases will add
    Bayesian updates and contextual bandits.
    """

    def __init__(self):
        self._default_model = ""         # User's default model
        self._default_node = ""          # User's default node
        self._fallback_model = ""        # Fallback when primary fails
        self._prefer_local: bool = False  # Prefer local models when possible

    def schedule(self, fingerprint: TaskFingerprint,
                 available_nodes: list[dict[str, Any]],
                 available_models: list[dict[str, Any]],
                 constraints: SchedulingConstraints | None = None,
                 evidence: dict[str, dict] | None = None) -> NousResult[ExecutionPath]:
        """Select the best execution path for a task.

        Args:
            fingerprint: Task characteristics
            available_nodes: [{node_id, name, online, resources, ...}]
            available_models: [{instance_key, provider, model_id, capabilities, ...}]
            constraints: Hard constraints for filtering
            evidence: Historical performance data per instance_key
        """
        ranked = self._rank_candidates(
            fingerprint,
            available_nodes,
            available_models,
            constraints or SchedulingConstraints(),
            evidence or {},
        )
        if not ranked.ok:
            return NousResult.err(
                ranked.code,
                message=ranked.message,
                details=ranked.details,
            )
        candidates = ranked.value or []
        return NousResult.ok(candidates[0])

    def schedule_lanes(
        self,
        fingerprint: TaskFingerprint,
        available_nodes: list[dict[str, Any]],
        available_models: list[dict[str, Any]],
        constraints: SchedulingConstraints | None = None,
        evidence: dict[str, dict] | None = None,
    ) -> NousResult[ExecutionPlan]:
        """Select a bounded, deterministic set of distinct execution paths."""
        active = constraints or SchedulingConstraints()
        requested = max(1, min(int(active.max_parallel_lanes), 64))
        ranked = self._rank_candidates(
            fingerprint,
            available_nodes,
            available_models,
            active,
            evidence or {},
        )
        if not ranked.ok:
            return NousResult.err(
                ranked.code,
                message=ranked.message,
                details=ranked.details,
            )
        candidates = ranked.value or []
        selected = tuple(candidates[:requested])
        return NousResult.ok(
            ExecutionPlan(
                paths=selected,
                requested_lanes=requested,
                scheduled_lanes=len(selected),
                degraded=len(selected) < requested,
            )
        )

    def _rank_candidates(
        self,
        fingerprint: TaskFingerprint,
        available_nodes: list[dict[str, Any]],
        available_models: list[dict[str, Any]],
        constraints: SchedulingConstraints,
        evidence: dict[str, dict],
    ) -> NousResult[list[ExecutionPath]]:
        if (
            any(
                item.startswith("security.defensive.")
                for item in constraints.required_capabilities
            )
            and not constraints.authorized_assets
        ):
            return NousResult.err(
                ErrorCode.PERMISSION_DENIED,
                message="Defensive security scheduling requires authorized assets",
            )

        # Stage 1: Hard constraint filtering

        # Filter nodes: must be online
        online_nodes = [n for n in available_nodes if n.get("online", False)]

        if constraints.allowed_nodes:
            online_nodes = [
                node
                for node in online_nodes
                if node.get("node_id") in constraints.allowed_nodes
            ]
        if constraints.required_node_capabilities:
            online_nodes = [
                node
                for node in online_nodes
                if all(
                    capability in node.get("capabilities", [])
                    for capability in constraints.required_node_capabilities
                )
            ]
        if constraints.allowed_trust_zones:
            online_nodes = [
                node
                for node in online_nodes
                if node.get("trust_zone") in constraints.allowed_trust_zones
            ]

        # Apply preferred/denied filters
        if constraints.preferred_nodes:
            preferred = [n for n in online_nodes
                        if n["node_id"] in constraints.preferred_nodes]
            if preferred:
                online_nodes = preferred

        if not online_nodes:
            return NousResult.err(ErrorCode.NODE_OFFLINE,
                                  message="No online nodes available")

        # Filter models: must support required capabilities
        qualified_models = available_models
        if constraints.required_capabilities:
            qualified_models = [
                m for m in available_models
                if all(c in m.get("capabilities", []) for c in constraints.required_capabilities)
            ]

        # Privacy: only local models
        if constraints.privacy_required:
            qualified_models = [
                m for m in qualified_models
                if m.get("provider") in ("ollama", "llama.cpp", "vllm", "local")
            ]

        # Apply preferred/denied
        if constraints.denied_models:
            qualified_models = [
                m for m in qualified_models
                if m["instance_key"] not in constraints.denied_models
            ]
        if constraints.preferred_models:
            preferred = [m for m in qualified_models
                        if m["instance_key"] in constraints.preferred_models]
            if preferred:
                qualified_models = preferred

        if not qualified_models:
            return NousResult.err(ErrorCode.MODEL_UNAVAILABLE,
                                  message="No qualified models available")

        # Stage 2: Score candidates

        candidates: list[ExecutionPath] = []

        for node in online_nodes:
            for model in qualified_models:
                path = self._build_path(fingerprint, node, model, constraints, evidence)
                candidates.append(path)

        # Sort by composite score descending
        candidates.sort(key=lambda p: p.score, reverse=True)

        # Stage 3: Budget filtering

        if constraints.max_cost_cents > 0:
            candidates = [c for c in candidates
                         if c.estimated_cost_cents <= constraints.max_cost_cents]

        if constraints.max_latency_ms > 0:
            candidates = [c for c in candidates
                         if c.estimated_latency_ms <= constraints.max_latency_ms]

        if not candidates:
            return NousResult.err(ErrorCode.BUDGET_EXCEEDED,
                                  message="No candidates within budget constraints")

        best = candidates[0]

        if best.evidence_sample_count < 5:
            log.info("Scheduler: best path has low evidence (n=%d) — using user defaults",
                     best.evidence_sample_count)

        return NousResult.ok(candidates)

    def _build_path(self, fingerprint: TaskFingerprint,
                    node: dict, model: dict,
                    constraints: SchedulingConstraints,
                    evidence: dict[str, dict]) -> ExecutionPath:
        """Build and score a single execution path."""
        instance_key = model.get("instance_key", "")
        path = ExecutionPath(
            model_instance_key=instance_key,
            node_id=node.get("node_id", ""),
            node_name=node.get("name", ""),
        )

        # Estimate cost
        path.estimated_cost_cents = self._estimate_cost(fingerprint, model)

        # Estimate latency
        path.estimated_latency_ms = self._estimate_latency(fingerprint, model, node)

        # Look up evidence
        ev = evidence.get(instance_key, {})
        path.evidence_level = ev.get("evidence_level", 0)
        path.evidence_sample_count = ev.get("sample_count", 0)
        path.estimated_success_rate = ev.get("success_rate", 0.5)

        # Score: weighted combination
        succ_weight = 0.4
        cost_weight = 0.3
        latency_weight = 0.3

        succ_score = path.estimated_success_rate

        # Normalize cost: lower is better, clamp at 100 cents
        max_cost = 100
        norm_cost = max(0, 1.0 - (path.estimated_cost_cents / max_cost))
        cost_score = norm_cost

        # Normalize latency: lower is better, clamp at 10s
        max_lat = 10000
        norm_lat = max(0, 1.0 - (path.estimated_latency_ms / max_lat))
        latency_score = norm_lat

        # Evidence bonus: higher evidence → higher confidence
        evidence_bonus = min(0.2, path.evidence_sample_count * 0.01)

        path.score = (
            succ_weight * succ_score +
            cost_weight * cost_score +
            latency_weight * latency_score +
            evidence_bonus
        )

        return path

    def _estimate_cost(self, fingerprint: TaskFingerprint,
                       model: dict) -> int:
        """Estimate cost in cents for the task on this model."""
        # Use model's declared price if available
        price_per_1k_input = model.get("price_per_1k_input", 0.0)
        price_per_1k_output = model.get("price_per_1k_output", 0.0)

        if price_per_1k_input > 0:
            est_tokens = fingerprint.estimated_context_tokens or 4000
            est_output = est_tokens // 2
            cost = (est_tokens / 1000 * price_per_1k_input +
                    est_output / 1000 * price_per_1k_output)
            return int(cost * 100)  # Convert to cents
        else:
            # Local model — estimate VRAM time cost
            vram_gb = model.get("vram_gb", 0)
            if vram_gb > 0:
                est_seconds = (fingerprint.estimated_context_tokens or 4000) / 10
                return int(vram_gb * est_seconds * 0.001)  # Rough estimate
            return 1  # Minimal cost for local

    def _estimate_latency(self, fingerprint: TaskFingerprint,
                          model: dict, node: dict) -> int:
        """Estimate latency in milliseconds."""
        # Local: based on tokens / tps
        if model.get("provider") in ("ollama", "llama.cpp", "vllm", "local"):
            tps = model.get("tokens_per_second", 20)  # Default 20 tps
            est_tokens = fingerprint.estimated_context_tokens or 4000
            return int(est_tokens / tps * 1000)
        else:
            # Cloud: add network overhead
            base = model.get("avg_latency_ms", 2000)
            est_tokens = fingerprint.estimated_context_tokens or 4000
            return base + int(est_tokens / 50 * 1000)  # Assume 50 tps cloud

    def set_defaults(self, default_model: str, default_node: str = "",
                     fallback_model: str = "", prefer_local: bool = False) -> None:
        self._default_model = default_model
        self._default_node = default_node
        self._fallback_model = fallback_model
        self._prefer_local = prefer_local

    def explain(self, path: ExecutionPath) -> str:
        """Generate human-readable explanation for a scheduling decision."""
        lines = [
            f"Selected: {path.model_instance_key}",
            f"Node: {path.node_name} ({path.node_id})",
            f"Estimated cost: {path.estimated_cost_cents}¢",
            f"Estimated latency: {path.estimated_latency_ms}ms",
            f"Success rate: {path.estimated_success_rate:.0%}",
            f"Evidence: {path.evidence_sample_count} samples (L{path.evidence_level})",
            f"Score: {path.score:.3f}",
        ]
        if path.evidence_sample_count < 5:
            lines.append("⚠️  Low evidence — results may vary. Consider using default model.")
        return "\n".join(lines)
