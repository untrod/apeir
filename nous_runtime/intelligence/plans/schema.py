# -*- coding: utf-8 -*-
"""Execution Plan Schema — complete specification of task execution."""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass, field
from typing import Any


@dataclass
class PlanNode:
    """A single node in the execution DAG."""
    node_id: str = ""
    objective: str = ""
    inputs: list[str] = field(default_factory=list)       # artifact IDs
    outputs: list[str] = field(default_factory=list)       # artifact IDs to produce
    dependencies: list[str] = field(default_factory=list)  # node_ids
    required_capabilities: list[str] = field(default_factory=list)
    resource_requirements: dict[str, Any] = field(default_factory=dict)
    write_scope: str = "workspace"
    acceptance_conditions: list[str] = field(default_factory=list)
    verification: list[str] = field(default_factory=list)
    failure_policy: str = "fail"  # fail, retry, skip, escalate
    timeout_seconds: int = 300
    retry_policy: str = "none"    # none, exponential_backoff, fixed_delay
    checkpoint_policy: str = "after_completion"


@dataclass
class PlanEdge:
    """An edge in the execution DAG."""
    from_node: str = ""
    to_node: str = ""
    edge_type: str = "dependency"  # dependency, data_flow, conditional, speculative
    condition: str = ""            # Python expression for conditional edges


@dataclass
class ExecutionPlan:
    """Complete specification of HOW a task will execute.

    This is the primary object of decision-making. The Decision Fabric
    generates candidate Plans, evaluates them against constraints, ranks
    them on the Pareto frontier, and selects one for execution.
    """
    plan_id: str = ""
    version: str = "1.0"

    # Graph structure
    task_graph: dict[str, Any] = field(default_factory=dict)  # DAG definition
    nodes: list[PlanNode] = field(default_factory=list)
    edges: list[PlanEdge] = field(default_factory=list)

    # Resource assignments
    agent_roles: list[str] = field(default_factory=list)
    model_assignments: dict[str, str] = field(default_factory=dict)  # role → model_id
    node_assignments: dict[str, str] = field(default_factory=dict)   # role → node_id
    tools: list[str] = field(default_factory=list)

    # Strategies
    context_strategy: str = "standard"         # standard, expanded, minimal, task_specific
    data_sources: list[str] = field(default_factory=list)
    verification_strategy: str = "standard"    # none, standard, exhaustive, critical_only
    recovery_strategy: str = "retry"           # retry, fallback, reassign, escalate
    approval_requirements: list[str] = field(default_factory=list)

    # Estimates
    resource_limits: dict[str, Any] = field(default_factory=dict)
    cost_estimate_usd: float = 0.0
    latency_estimate_ms: float = 0.0
    uncertainty: float = 0.0

    # Metadata
    policy_version: str = ""
    created_by: str = ""
    tags: list[str] = field(default_factory=list)

    # Methods

    def plan_id_for(self) -> str:
        if not self.plan_id:
            self.plan_id = f"plan_{uuid.uuid4().hex[:12]}"
        return self.plan_id

    def validate_dag(self) -> tuple[bool, str]:
        """Validate the DAG: no cycles, all dependencies exist."""
        node_ids = {n.node_id for n in self.nodes}

        # Check all dependency references exist
        for n in self.nodes:
            for dep in n.dependencies:
                if dep not in node_ids:
                    return False, f"Node {n.node_id} depends on unknown node {dep}"

        # Cycle detection via DFS
        WHITE, GRAY, BLACK = 0, 1, 2
        color = {nid: WHITE for nid in node_ids}

        def dfs(nid: str) -> bool:
            color[nid] = GRAY
            node = next((n for n in self.nodes if n.node_id == nid), None)
            if node:
                for dep in node.dependencies:
                    if color[dep] == GRAY:
                        return True  # cycle
                    if color[dep] == WHITE and dfs(dep):
                        return True
            color[nid] = BLACK
            return False

        for nid in node_ids:
            if color[nid] == WHITE and dfs(nid):
                return False, "Cycle detected in execution DAG"

        return True, "DAG valid"

    def critical_path(self) -> list[str]:
        """Return node IDs on the critical path (longest dependency chain)."""
        # Simple longest-path in DAG via topological sort
        node_ids = {n.node_id for n in self.nodes}
        dist = {nid: 0 for nid in node_ids}
        for n in self.nodes:
            for dep in n.dependencies:
                dist[n.node_id] = max(dist[n.node_id], dist.get(dep, 0) + 1)

        max_dist = max(dist.values()) if dist else 0
        return [nid for nid, d in dist.items() if d == max_dist]

    def to_dict(self) -> dict:
        return {
            "plan_id": self.plan_id,
            "version": self.version,
            "nodes": [n.__dict__ for n in self.nodes],
            "edges": [e.__dict__ for e in self.edges],
            "agent_roles": self.agent_roles,
            "model_assignments": self.model_assignments,
            "node_assignments": self.node_assignments,
            "tools": self.tools,
            "context_strategy": self.context_strategy,
            "verification_strategy": self.verification_strategy,
            "recovery_strategy": self.recovery_strategy,
            "cost_estimate_usd": self.cost_estimate_usd,
            "latency_estimate_ms": self.latency_estimate_ms,
            "uncertainty": self.uncertainty,
            "policy_version": self.policy_version,
        }

    def hash_short(self) -> str:
        d = self.to_dict()
        d.pop("plan_id", None)
        return hashlib.sha256(
            json.dumps(d, sort_keys=True, ensure_ascii=False).encode()
        ).hexdigest()[:12]
