# -*- coding: utf-8 -*-
"""Nous Orchestration Fabric — Dynamic task graph compilation, role assignment,
artifact contracts, concurrency control, replanning, arbitration, and credit assignment.

Converts user tasks into executable DAGs with dynamic role generation,
intelligent assignment, and rolling-horizon replanning.
"""

from .graph import TaskGraph, TaskNode, GraphCompiler, validate_dag
from .roles import RoleGenerator, AgentRole
from .assignment import AssignmentEngine, Assignment
from .contracts import ArtifactContract, ContractRegistry
from .synchronization import ConcurrencyController, WriteLease, ConflictDetector
from .replanning import Replanner, ReplanTrigger
from .arbitration import Arbiter, ArbitrationDecision
from .credit import CreditAssigner, CreditReport

__all__ = [
    "TaskGraph", "TaskNode", "GraphCompiler", "validate_dag",
    "RoleGenerator", "AgentRole",
    "AssignmentEngine", "Assignment",
    "ArtifactContract", "ContractRegistry",
    "ConcurrencyController", "WriteLease", "ConflictDetector",
    "Replanner", "ReplanTrigger",
    "Arbiter", "ArbitrationDecision",
    "CreditAssigner", "CreditReport",
]
