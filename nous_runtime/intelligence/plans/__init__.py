# -*- coding: utf-8 -*-
"""Execution Plan — the object of decision-making in Nous Intelligence.

An Execution Plan is the complete specification of HOW a task will execute:
task_graph, agent_roles, model_assignments, node_assignments, tools,
context_strategy, verification_strategy, recovery_strategy, etc.

The Decision Fabric selects among Plans, not individual models.
"""

from .schema import ExecutionPlan, PlanNode, PlanEdge
from .generator import PlanGenerator, PlanCandidate

__all__ = [
    "ExecutionPlan",
    "PlanNode",
    "PlanEdge",
    "PlanGenerator",
    "PlanCandidate",
]
