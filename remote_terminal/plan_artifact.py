# -*- coding: utf-8 -*-
"""
PlanArtifact — Formal versioned, hash-bound execution plan.

Implements the missing PlanArtifact from the master plan gap analysis.
Each plan is a YAML-serializable, SHA-256 hashed artifact that bridges
the Planner → Approval → ExecutionTicket chain.

Design:
  - Immutable after creation (hash-bound)
  - YAML for human readability + deterministic serialization
  - SHA-256 for integrity verification
  - Links tasks via dependency graph
"""

from __future__ import annotations

import hashlib
import json as _json
import time
import uuid
from dataclasses import dataclass, field
from typing import Any



# PlannedTask — a single task within a plan


@dataclass
class PlannedTask:
    """A single task step in a PlanArtifact."""
    task_id: str = field(default_factory=lambda: f"pt-{uuid.uuid4().hex[:12]}")
    capability_id: str = ""
    params: dict[str, Any] = field(default_factory=dict)
    depends_on: list[str] = field(default_factory=list)
    expected_output_schema: dict[str, Any] = field(default_factory=dict)
    description: str = ""
    estimated_duration_ms: int = 30000
    priority: int = 50  # 0-100, higher = more important

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "capability_id": self.capability_id,
            "params": self.params,
            "depends_on": list(self.depends_on),
            "expected_output_schema": self.expected_output_schema,
            "description": self.description,
            "estimated_duration_ms": self.estimated_duration_ms,
            "priority": self.priority,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "PlannedTask":
        return cls(
            task_id=str(data.get("task_id", "")),
            capability_id=str(data.get("capability_id", "")),
            params=dict(data.get("params", {})),
            depends_on=list(data.get("depends_on", [])),
            expected_output_schema=dict(data.get("expected_output_schema", {})),
            description=str(data.get("description", "")),
            estimated_duration_ms=int(data.get("estimated_duration_ms", 30000)),
            priority=int(data.get("priority", 50)),
        )



# PlanArtifact — versioned, hash-bound execution plan


@dataclass
class PlanArtifact:
    """Formal execution plan with versioning and integrity hashing.

    Usage:
        plan = PlanArtifact(
            plan_id="plan-abc",
            tasks=[PlannedTask(capability_id="tool.read_file", ...)],
        )
        yaml_str = plan.to_yaml()
        verified = plan.verify_hash()
    """
    plan_id: str = field(default_factory=lambda: f"plan-{uuid.uuid4().hex[:12]}")
    version: str = "1.0.0"
    schema_version: str = "1.0"

    # Core content
    tasks: list[PlannedTask] = field(default_factory=list)
    dependencies: dict[str, list[str]] = field(default_factory=dict)
    # dependencies maps task_id → list of task_ids it blocks

    # Metadata
    estimated_cost: dict[str, Any] = field(default_factory=dict)
    # e.g., {"tokens": 8192, "cost_usd": 0.05, "duration_ms": 120000}
    created_at: str = field(default_factory=lambda: time.strftime(
        "%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
    created_by: str = "brain.run_turn"
    target_node_id: str = ""
    target_model_id: str = ""
    approval_status: str = "pending"  # pending | approved | denied | expired
    approved_by: str = ""
    approved_at: str = ""

    # Integrity
    signature: str = ""  # SHA-256 hash of canonical representation

    def __post_init__(self) -> None:
        if not self.signature:
            self.signature = self.compute_hash()

    def compute_hash(self) -> str:
        """Compute SHA-256 hash of the canonical (sorted) JSON representation."""
        canonical = _json.dumps(
            self._canonical_dict(),
            sort_keys=True,
            ensure_ascii=False,
            separators=(",", ":"),
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def verify_hash(self) -> bool:
        """Verify that the stored signature matches the computed hash."""
        return self.signature == self.compute_hash()

    def _canonical_dict(self) -> dict[str, Any]:
        """Return the canonical dictionary form (excludes signature for hashing)."""
        return {
            "plan_id": self.plan_id,
            "version": self.version,
            "schema_version": self.schema_version,
            "tasks": [t.to_dict() for t in self.tasks],
            "dependencies": {k: sorted(v) for k, v in sorted(self.dependencies.items())},
            "estimated_cost": self.estimated_cost,
            "created_at": self.created_at,
            "created_by": self.created_by,
            "target_node_id": self.target_node_id,
            "target_model_id": self.target_model_id,
            "approval_status": self.approval_status,
            "approved_by": self.approved_by,
            "approved_at": self.approved_at,
        }

    def to_dict(self) -> dict[str, Any]:
        """Full dictionary including signature."""
        result = self._canonical_dict()
        result["signature"] = self.signature
        return result

    def to_yaml(self) -> str:
        """Serialize to YAML string."""
        try:
            import yaml
            return yaml.dump(
                self.to_dict(),
                default_flow_style=False,
                allow_unicode=True,
                sort_keys=False,
            )
        except ImportError:
            # Fallback to JSON if PyYAML not available
            return _json.dumps(self.to_dict(), indent=2, ensure_ascii=False)

    def to_json(self) -> str:
        """Serialize to JSON string."""
        return _json.dumps(self.to_dict(), indent=2, ensure_ascii=False)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "PlanArtifact":
        """Deserialize from a dictionary."""
        tasks = [
            PlannedTask.from_dict(t) if isinstance(t, dict) else t
            for t in data.get("tasks", [])
        ]
        return cls(
            plan_id=str(data.get("plan_id", "")),
            version=str(data.get("version", "1.0.0")),
            schema_version=str(data.get("schema_version", "1.0")),
            tasks=tasks,
            dependencies={str(k): list(v) for k, v in data.get("dependencies", {}).items()},
            estimated_cost=dict(data.get("estimated_cost", {})),
            created_at=str(data.get("created_at", "")),
            created_by=str(data.get("created_by", "brain.run_turn")),
            target_node_id=str(data.get("target_node_id", "")),
            target_model_id=str(data.get("target_model_id", "")),
            approval_status=str(data.get("approval_status", "pending")),
            approved_by=str(data.get("approved_by", "")),
            approved_at=str(data.get("approved_at", "")),
            signature=str(data.get("signature", "")),
        )

    @classmethod
    def from_yaml(cls, yaml_str: str) -> "PlanArtifact":
        """Deserialize from a YAML string."""
        try:
            import yaml
            data = yaml.safe_load(yaml_str)
        except ImportError:
            data = _json.loads(yaml_str)
        if not isinstance(data, dict):
            raise ValueError(f"Expected dict, got {type(data).__name__}")
        return cls.from_dict(data)

    @classmethod
    def from_json(cls, json_str: str) -> "PlanArtifact":
        """Deserialize from a JSON string."""
        data = _json.loads(json_str)
        if not isinstance(data, dict):
            raise ValueError(f"Expected dict, got {type(data).__name__}")
        return cls.from_dict(data)

    def get_task_by_id(self, task_id: str) -> PlannedTask | None:
        """Look up a PlannedTask by ID."""
        for task in self.tasks:
            if task.task_id == task_id:
                return task
        return None

    def get_execution_order(self) -> list[str]:
        """Return task IDs in dependency-respecting execution order (topological sort)."""
        # Build adjacency
        in_degree: dict[str, int] = {t.task_id: 0 for t in self.tasks}
        for t in self.tasks:
            for dep in t.depends_on:
                if dep in in_degree:
                    in_degree[t.task_id] = in_degree.get(t.task_id, 0) + 1

        # Kahn's algorithm
        order: list[str] = []
        queue = [tid for tid, deg in in_degree.items() if deg == 0]
        while queue:
            current = queue.pop(0)
            order.append(current)
            # Find tasks that depend on current
            for blocked_id, blocked_by_list in self.dependencies.items():
                if current in blocked_by_list and blocked_id in in_degree:
                    in_degree[blocked_id] -= 1
                    if in_degree[blocked_id] == 0:
                        queue.append(blocked_id)

        # Add any remaining (cycles or missing deps)
        for tid in in_degree:
            if tid not in order:
                order.append(tid)

        return order
