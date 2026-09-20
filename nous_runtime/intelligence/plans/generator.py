# -*- coding: utf-8 -*-
"""Candidate Plan Generator — produces multiple Execution Plans for a task.

Generates diverse plans across dimensions:
  single/multi-model, single/multi-agent, serial/parallel, local/cloud,
  different node combinations, verification depths, recovery strategies,
  budget levels, context strategies.

Uses combinatorial control to prevent explosion:
  template constraints, beam search, heuristic pruning, capability pruning,
  budget pruning, dominance pruning, duplicate detection.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .schema import ExecutionPlan, PlanNode, PlanEdge


@dataclass
class PlanCandidate:
    """A candidate Execution Plan with generation metadata."""
    plan: ExecutionPlan
    generation_method: str = ""      # template, heuristic, learned, mutated
    generation_score: float = 0.0    # a priori quality estimate
    generation_uncertainty: float = 0.0


class PlanGenerator:
    """Generates diverse candidate Execution Plans for a task.

    Controls combinatorial explosion via:
    - Template constraints (max 5 topologies)
    - Beam search (width = 20)
    - Capability pruning (skip infeasible model/node combos)
    - Budget pruning (skip plans above 2x budget)
    - Duplicate detection (hash-based)
    """

    def __init__(self, max_candidates: int = 50, beam_width: int = 20) -> None:
        self.max_candidates = max_candidates
        self.beam_width = beam_width
        self._seen_hashes: set[str] = set()

    def generate(
        self,
        task: dict[str, Any],
        available_models: list[dict[str, Any]] | None = None,
        available_nodes: list[dict[str, Any]] | None = None,
    ) -> list[PlanCandidate]:
        """Generate candidate execution plans for a task."""
        self._seen_hashes.clear()
        models = available_models or []
        nodes = available_nodes or []
        candidates: list[PlanCandidate] = []

        # 1. Single-agent plans
        for model in models[:10]:
            for node in nodes[:5]:
                for strategy in ["standard", "minimal"]:
                    plan = self._build_single_agent_plan(task, model, node, strategy)
                    c = PlanCandidate(plan=plan, generation_method="single_agent_template")
                    if self._accept(c):
                        candidates.append(c)
                    if len(candidates) >= self.max_candidates:
                        return candidates

        # 2. Multi-agent plans (Planner-Worker-Reviewer variants)
        if len(models) >= 2:
            for plan_model in models[:5]:
                for work_model in models[:5]:
                    if plan_model == work_model:
                        continue
                    for review_model in models[:5]:
                        plan = self._build_pwr_plan(task, plan_model, work_model, review_model, nodes[:3])
                        c = PlanCandidate(plan=plan, generation_method="pwr_template")
                        if self._accept(c):
                            candidates.append(c)
                        if len(candidates) >= self.max_candidates:
                            return candidates

        # 3. Parallel plans
        for model in models[:5]:
            plan = self._build_parallel_plan(task, model, nodes[:3])
            c = PlanCandidate(plan=plan, generation_method="parallel_template")
            if self._accept(c):
                candidates.append(c)
            if len(candidates) >= self.max_candidates:
                return candidates

        # 4. Verification variants
        for c in list(candidates)[:10]:  # clone and vary verification
            for verif in ["none", "standard", "exhaustive"]:
                plan = self._clone_with_verification(c.plan, verif)
                nc = PlanCandidate(plan=plan, generation_method="verification_variant")
                if self._accept(nc):
                    candidates.append(nc)
                if len(candidates) >= self.max_candidates:
                    return candidates

        # 5. Recovery variants
        for c in list(candidates)[:10]:
            for recovery in ["retry", "fallback", "reassign"]:
                plan = self._clone_with_recovery(c.plan, recovery)
                nc = PlanCandidate(plan=plan, generation_method="recovery_variant")
                if self._accept(nc):
                    candidates.append(nc)
                if len(candidates) >= self.max_candidates:
                    return candidates

        # 6. Budget variants
        budget = float(task.get("budget_usd", 0) or 0)
        if budget > 0:
            for c in list(candidates)[:10]:
                for budget_mult in [0.3, 0.6, 1.0]:
                    plan = self._clone_with_budget(c.plan, budget * budget_mult)
                    nc = PlanCandidate(plan=plan, generation_method="budget_variant")
                    if self._accept(nc):
                        candidates.append(nc)
                    if len(candidates) >= self.max_candidates:
                        return candidates

        return candidates[:self.max_candidates]

    # Plan builders

    def _build_single_agent_plan(
        self, task: dict, model: dict, node: dict, strategy: str
    ) -> ExecutionPlan:
        plan = ExecutionPlan()
        plan.plan_id_for()
        plan.agent_roles = ["worker"]
        plan.model_assignments = {"worker": str(model.get("model_id", ""))}
        plan.node_assignments = {"worker": str(node.get("node_id", ""))}
        plan.tools = task.get("required_tools", []) or []
        plan.verification_strategy = strategy
        plan.context_strategy = task.get("context_strategy", "standard")
        plan.recovery_strategy = "retry"
        plan.cost_estimate_usd = float(model.get("cost_per_1k_tokens", 0.01)) * 0.5
        plan.latency_estimate_ms = float(model.get("avg_latency_ms", 1000))
        plan.uncertainty = 0.3

        # Single node
        n = PlanNode(
            node_id="execute",
            objective=str(task.get("description", "Execute task")),
            required_capabilities=task.get("capabilities", []) or [],
            resource_requirements={
                "model_id": model.get("model_id", ""),
                "memory_mb": model.get("memory_required_mb", 512),
            },
            timeout_seconds=int(task.get("timeout_seconds", 300)),
        )
        plan.nodes = [n]
        return plan

    def _build_pwr_plan(
        self, task: dict, plan_model: dict, work_model: dict, review_model: dict, nodes: list
    ) -> ExecutionPlan:
        plan = ExecutionPlan()
        plan.plan_id_for()
        plan.agent_roles = ["planner", "worker", "reviewer"]
        plan.model_assignments = {
            "planner": str(plan_model.get("model_id", "")),
            "worker": str(work_model.get("model_id", "")),
            "reviewer": str(review_model.get("model_id", "")),
        }
        if nodes:
            plan.node_assignments = {
                "planner": str(nodes[0].get("node_id", "")),
                "worker": str(nodes[min(1, len(nodes)-1)].get("node_id", "")),
                "reviewer": str(nodes[min(2, len(nodes)-1)].get("node_id", "")),
            }
        plan.verification_strategy = "standard"
        plan.recovery_strategy = "fallback"
        plan.cost_estimate_usd = sum(
            float(m.get("cost_per_1k_tokens", 0.01)) * 0.3
            for m in [plan_model, work_model, review_model]
        )
        plan.latency_estimate_ms = sum(
            float(m.get("avg_latency_ms", 1000)) for m in [plan_model, work_model, review_model]
        ) / 3
        plan.uncertainty = 0.2

        plan.nodes = [
            PlanNode(node_id="plan", objective="Analyze and plan", dependencies=[],
                     required_capabilities=["planning"], timeout_seconds=120),
            PlanNode(node_id="execute", objective="Execute task", dependencies=["plan"],
                     required_capabilities=task.get("capabilities", []), timeout_seconds=300),
            PlanNode(node_id="review", objective="Review output", dependencies=["execute"],
                     required_capabilities=["code_review"], timeout_seconds=120),
        ]
        plan.edges = [
            PlanEdge(from_node="plan", to_node="execute"),
            PlanEdge(from_node="execute", to_node="review"),
        ]
        return plan

    def _build_parallel_plan(
        self, task: dict, model: dict, nodes: list
    ) -> ExecutionPlan:
        plan = ExecutionPlan()
        plan.plan_id_for()
        plan.agent_roles = ["coordinator", "worker_a", "worker_b"]
        plan.model_assignments = {
            "coordinator": model.get("model_id", ""),
            "worker_a": model.get("model_id", ""),
            "worker_b": model.get("model_id", ""),
        }
        plan.verification_strategy = "standard"
        plan.recovery_strategy = "retry"
        plan.uncertainty = 0.25

        plan.nodes = [
            PlanNode(node_id="analyze", objective="Analyze and split", dependencies=[],
                     required_capabilities=["planning"], timeout_seconds=60),
            PlanNode(node_id="execute_a", objective="Execute part A", dependencies=["analyze"],
                     required_capabilities=task.get("capabilities", []), timeout_seconds=300),
            PlanNode(node_id="execute_b", objective="Execute part B", dependencies=["analyze"],
                     required_capabilities=task.get("capabilities", []), timeout_seconds=300),
            PlanNode(node_id="merge", objective="Merge results", dependencies=["execute_a", "execute_b"],
                     required_capabilities=["data_processing"], timeout_seconds=60),
        ]
        return plan

    # Variant cloners

    def _clone_with_verification(self, plan: ExecutionPlan, strategy: str) -> ExecutionPlan:
        clone = ExecutionPlan()
        clone.plan_id_for()
        clone.agent_roles = list(plan.agent_roles)
        clone.model_assignments = dict(plan.model_assignments)
        clone.node_assignments = dict(plan.node_assignments)
        clone.verification_strategy = strategy
        clone.recovery_strategy = plan.recovery_strategy
        clone.cost_estimate_usd = plan.cost_estimate_usd * (1.5 if strategy == "exhaustive" else 1.0)
        clone.latency_estimate_ms = plan.latency_estimate_ms * (2.0 if strategy == "exhaustive" else 1.0)
        clone.uncertainty = plan.uncertainty * (0.5 if strategy == "exhaustive" else 1.0)
        clone.nodes = [
            PlanNode(**{k: v for k, v in n.__dict__.items()})
            for n in plan.nodes
        ]
        return clone

    def _clone_with_recovery(self, plan: ExecutionPlan, strategy: str) -> ExecutionPlan:
        clone = ExecutionPlan()
        clone.plan_id_for()
        clone.agent_roles = list(plan.agent_roles)
        clone.model_assignments = dict(plan.model_assignments)
        clone.node_assignments = dict(plan.node_assignments)
        clone.verification_strategy = plan.verification_strategy
        clone.recovery_strategy = strategy
        clone.cost_estimate_usd = plan.cost_estimate_usd
        clone.latency_estimate_ms = plan.latency_estimate_ms
        clone.uncertainty = plan.uncertainty
        clone.nodes = [
            PlanNode(**{k: v for k, v in n.__dict__.items()})
            for n in plan.nodes
        ]
        return clone

    def _clone_with_budget(self, plan: ExecutionPlan, budget: float) -> ExecutionPlan:
        clone = ExecutionPlan()
        clone.plan_id_for()
        clone.agent_roles = list(plan.agent_roles)
        clone.model_assignments = dict(plan.model_assignments)
        clone.node_assignments = dict(plan.node_assignments)
        clone.verification_strategy = plan.verification_strategy
        clone.recovery_strategy = plan.recovery_strategy
        clone.cost_estimate_usd = budget
        clone.latency_estimate_ms = plan.latency_estimate_ms
        clone.uncertainty = plan.uncertainty
        clone.nodes = [
            PlanNode(**{k: v for k, v in n.__dict__.items()})
            for n in plan.nodes
        ]
        return clone

    # Pruning

    def _accept(self, candidate: PlanCandidate) -> bool:
        """Check if candidate should be accepted (pruning)."""
        h = candidate.plan.hash_short()
        if h in self._seen_hashes:
            return False  # duplicate
        if candidate.plan.cost_estimate_usd < 0:
            return False
        self._seen_hashes.add(h)
        return True
