# -*- coding: utf-8 -*-
"""Canonical hard constraint and soft preference definitions."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class ConstraintCategory(str, Enum):
    PRIVACY = "privacy"
    CAPABILITY = "capability"
    RESOURCE = "resource"
    BUDGET = "budget"
    TIME = "time"
    NETWORK = "network"
    PERMISSION = "permission"
    SAFETY = "safety"
    APPROVAL = "approval"


@dataclass
class HardConstraint:
    """A non-negotiable constraint. Violation → plan REJECTED."""
    name: str
    category: ConstraintCategory
    description: str
    policy_reference: str = ""
    check_fn: str = ""  # name of the check function


@dataclass
class SoftPreference:
    """A negotiable preference. Lower score → still feasible, just lower ranked."""
    name: str
    description: str
    default_weight: float = 1.0
    higher_is_better: bool = True


HARD_CONSTRAINTS = [
    HardConstraint("privacy_class", ConstraintCategory.PRIVACY,
                   "Model/node must satisfy required privacy class (public/internal/confidential/restricted)"),
    HardConstraint("data_residency", ConstraintCategory.PRIVACY,
                   "Data must stay within specified geographic/network boundary"),
    HardConstraint("model_capability", ConstraintCategory.CAPABILITY,
                   "Model must declare required capability level for task"),
    HardConstraint("model_license", ConstraintCategory.CAPABILITY,
                   "Model license must be compatible with task requirements"),
    HardConstraint("node_architecture", ConstraintCategory.RESOURCE,
                   "Node CPU architecture must match task requirements (x86_64/arm64)"),
    HardConstraint("available_memory", ConstraintCategory.RESOURCE,
                   "Node must have sufficient free memory (>= task requirement)"),
    HardConstraint("available_gpu", ConstraintCategory.RESOURCE,
                   "Node must have GPU if task requires GPU execution"),
    HardConstraint("budget_ceiling", ConstraintCategory.BUDGET,
                   "Total estimated cost must not exceed task budget"),
    HardConstraint("deadline", ConstraintCategory.TIME,
                   "Estimated completion time must be within task deadline"),
    HardConstraint("network_availability", ConstraintCategory.NETWORK,
                   "Required network endpoints must be reachable from node"),
    HardConstraint("tool_permission", ConstraintCategory.PERMISSION,
                   "All required tools must be permitted for this task"),
    HardConstraint("file_permission", ConstraintCategory.PERMISSION,
                   "Task must have write access only within allowed scope"),
    HardConstraint("safety_policy", ConstraintCategory.SAFETY,
                   "Execution plan must not violate safety policies"),
    HardConstraint("approval_requirement", ConstraintCategory.APPROVAL,
                   "High-risk operations must have approval mechanism available"),
]


SOFT_PREFERENCES = [
    SoftPreference("cost_efficiency", "Prefer lower cost per task", default_weight=1.0, higher_is_better=False),
    SoftPreference("latency_minimization", "Prefer lower latency", default_weight=0.8, higher_is_better=False),
    SoftPreference("quality_maximization", "Prefer higher output quality", default_weight=1.2, higher_is_better=True),
    SoftPreference("reliability", "Prefer higher reliability/success rate", default_weight=1.0, higher_is_better=True),
    SoftPreference("reproducibility", "Prefer deterministic/reproducible execution", default_weight=0.5, higher_is_better=True),
    SoftPreference("resource_efficiency", "Prefer lower resource consumption", default_weight=0.6, higher_is_better=False),
    SoftPreference("novelty", "Prefer novel approaches (emergence lab only)", default_weight=0.2, higher_is_better=True),
]
