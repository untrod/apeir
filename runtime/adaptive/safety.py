"""
Safety Envelope — hard constraints that adaptive policies MUST NOT violate.

The safety envelope is the IMMUTABLE boundary within which all adaptive
optimization occurs. No learning system may expand this envelope.
Only governance-approved changes (human or governance module) may modify it.

Design principle: filter BEFORE scoring. If no candidate survives the
safety envelope, use Scheduler 1.0 deterministic baseline.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class EnforcementLevel(str, Enum):
    HARD = "hard"  # Violation = immediate rejection
    SOFT = "soft"  # Violation = warning, candidate still considered
    AUDIT = "audit"  # Violation = audit event only


class ConstraintOperator(str, Enum):
    EQUALS = "equals"
    NOT_EQUALS = "not_equals"
    GREATER_THAN = "greater_than"
    LESS_THAN = "less_than"
    GREATER_OR_EQUAL = "greater_or_equal"
    LESS_OR_EQUAL = "less_or_equal"
    IN = "in"
    NOT_IN = "not_in"
    CONTAINS = "contains"
    NOT_CONTAINS = "not_contains"
    MATCHES = "matches"
    EXISTS = "exists"
    NOT_EXISTS = "not_exists"


@dataclass(frozen=True)
class Constraint:
    """A single hard constraint in the safety envelope."""

    constraint_id: str
    name: str
    description: str
    field: str
    operator: ConstraintOperator
    value: Any
    enforcement: EnforcementLevel = EnforcementLevel.HARD
    message: str = ""


@dataclass
class SafetyViolation:
    """Record of a safety envelope violation."""

    constraint_id: str
    constraint_name: str
    enforcement: EnforcementLevel
    reason: str
    candidate_value: Any
    expected: str


@dataclass
class SafetyEnvelopeResult:
    """Result of applying the safety envelope to a candidate."""

    passed: bool = True
    total_constraints: int = 0
    passed_hard: int = 0
    failed_hard: int = 0
    passed_soft: int = 0
    failed_soft: int = 0
    violations: list[SafetyViolation] = field(default_factory=list)


class SafetyEnvelope:
    """Immutable set of hard constraints for adaptive optimization.

    Usage:
        envelope = SafetyEnvelope.standard()
        candidate = {"estimated_cost": 50.0, "estimated_quality": 0.9}
        result = envelope.apply(candidate)
        if result.passed:
            # Candidate is safe to consider
            ...
    """

    def __init__(self, constraints: list[Constraint] | None = None) -> None:
        self._constraints: list[Constraint] = list(constraints or [])

    @classmethod
    def standard(cls) -> "SafetyEnvelope":
        """Create the standard safety envelope for Nous RC10."""
        return cls(
            [
                Constraint(
                    constraint_id="SE-COST-001",
                    name="cost_budget",
                    description="Total estimated cost must not exceed budget",
                    field="estimated_cost",
                    operator=ConstraintOperator.LESS_OR_EQUAL,
                    value=100.0,
                    message="Cost exceeds workload budget",
                ),
                Constraint(
                    constraint_id="SE-QUALITY-001",
                    name="quality_floor",
                    description="Estimated quality must meet minimum threshold",
                    field="estimated_quality",
                    operator=ConstraintOperator.GREATER_OR_EQUAL,
                    value=0.5,
                    message="Quality below minimum threshold",
                ),
                Constraint(
                    constraint_id="SE-PRIVACY-001",
                    name="data_residency",
                    description="Data must not leave the local node if classified as sensitive",
                    field="data_classification",
                    operator=ConstraintOperator.NOT_EQUALS,
                    value="sensitive",
                    enforcement=EnforcementLevel.HARD,
                    message="Sensitive data must stay on local node",
                ),
                Constraint(
                    constraint_id="SE-LATENCY-001",
                    name="latency_bound",
                    description="P99 latency must not exceed SLA",
                    field="estimated_latency_p99_ms",
                    operator=ConstraintOperator.LESS_OR_EQUAL,
                    value=5000.0,
                    enforcement=EnforcementLevel.SOFT,
                    message="Latency SLA may be violated under exceptional circumstances",
                ),
                Constraint(
                    constraint_id="SE-HARDWARE-001",
                    name="hardware_available",
                    description="Target device must be healthy and available",
                    field="device_health",
                    operator=ConstraintOperator.IN,
                    value=["healthy", "degraded"],
                    message="Target device is quarantined or unavailable",
                ),
            ]
        )

    @property
    def constraints(self) -> list[Constraint]:
        return list(self._constraints)

    def add_constraint(self, constraint: Constraint) -> None:
        """Add a constraint to the envelope."""
        self._constraints.append(constraint)

    def apply(self, candidate_features: dict[str, Any]) -> SafetyEnvelopeResult:
        """Apply all constraints to a candidate.

        Returns a SafetyEnvelopeResult indicating whether the candidate
        is safe to consider. If any HARD constraint fails, the candidate
        is rejected.
        """
        result = SafetyEnvelopeResult(
            total_constraints=len(self._constraints),
        )

        for constraint in self._constraints:
            field_value = candidate_features.get(constraint.field)
            violation = self._evaluate_constraint(constraint, field_value)

            if violation:
                if constraint.enforcement == EnforcementLevel.HARD:
                    result.failed_hard += 1
                    result.passed = False
                elif constraint.enforcement == EnforcementLevel.SOFT:
                    result.failed_soft += 1
                result.violations.append(violation)
            else:
                if constraint.enforcement == EnforcementLevel.HARD:
                    result.passed_hard += 1
                elif constraint.enforcement == EnforcementLevel.SOFT:
                    result.passed_soft += 1

        return result

    def filter_candidates(
        self, candidates: list[dict[str, Any]]
    ) -> tuple[list[dict[str, Any]], list[SafetyEnvelopeResult]]:
        """Filter a list of candidates, returning only those that pass the safety envelope."""
        passed = []
        results = []
        for candidate in candidates:
            result = self.apply(candidate)
            results.append(result)
            if result.passed:
                passed.append(candidate)
        return passed, results

    @staticmethod
    def _evaluate_constraint(
        constraint: Constraint, field_value: Any
    ) -> SafetyViolation | None:
        """Evaluate a single constraint against a field value."""
        op = constraint.operator
        expected = constraint.value

        if field_value is None:
            if op == ConstraintOperator.NOT_EXISTS:
                return None  # Passes
            if op == ConstraintOperator.EXISTS:
                return SafetyViolation(
                    constraint_id=constraint.constraint_id,
                    constraint_name=constraint.name,
                    enforcement=constraint.enforcement,
                    reason=f"Field '{constraint.field}' does not exist",
                    candidate_value=None,
                    expected=constraint.message,
                )
            return SafetyViolation(
                constraint_id=constraint.constraint_id,
                constraint_name=constraint.name,
                enforcement=constraint.enforcement,
                reason=f"Field '{constraint.field}' not found",
                candidate_value=None,
                expected=constraint.message,
            )

        passes = SafetyEnvelope._check_operator(op, field_value, expected)

        if passes:
            return None

        return SafetyViolation(
            constraint_id=constraint.constraint_id,
            constraint_name=constraint.name,
            enforcement=constraint.enforcement,
            reason=f"Constraint '{constraint.name}' violated: {field_value} vs {expected}",
            candidate_value=field_value,
            expected=constraint.message,
        )

    @staticmethod
    def _check_operator(op: ConstraintOperator, actual: Any, expected: Any) -> bool:
        """Evaluate a comparison operator."""
        try:
            if op == ConstraintOperator.EQUALS:
                return actual == expected
            elif op == ConstraintOperator.NOT_EQUALS:
                return actual != expected
            elif op == ConstraintOperator.GREATER_THAN:
                return float(actual) > float(expected)
            elif op == ConstraintOperator.LESS_THAN:
                return float(actual) < float(expected)
            elif op == ConstraintOperator.GREATER_OR_EQUAL:
                return float(actual) >= float(expected)
            elif op == ConstraintOperator.LESS_OR_EQUAL:
                return float(actual) <= float(expected)
            elif op == ConstraintOperator.IN:
                return (
                    actual in expected
                    if isinstance(expected, (list, tuple, set))
                    else False
                )
            elif op == ConstraintOperator.NOT_IN:
                return (
                    actual not in expected
                    if isinstance(expected, (list, tuple, set))
                    else True
                )
            elif op == ConstraintOperator.CONTAINS:
                return expected in actual if hasattr(actual, "__contains__") else False
            elif op == ConstraintOperator.NOT_CONTAINS:
                return (
                    expected not in actual if hasattr(actual, "__contains__") else True
                )
            elif op == ConstraintOperator.MATCHES:
                return str(expected).lower() in str(actual).lower()
            elif op == ConstraintOperator.EXISTS:
                return actual is not None
            elif op == ConstraintOperator.NOT_EXISTS:
                return actual is None
        except (ValueError, TypeError):
            return False
        return False


@dataclass(frozen=True)
class ImmutableBoundaries:
    """Things adaptive systems MUST NOT change. Always all False."""

    kernel_abi: bool = False
    nki_protocol: bool = False
    resource_lease: bool = False
    capability_bounds: bool = False
    approval_rules: bool = False
    credential_policy: bool = False
    privacy_policy: bool = False
    device_control: bool = False
    public_compatibility: bool = False
    git_main_branch: bool = False
    release_process: bool = False
    self_source_code: bool = False

    def assert_no_violation(self, target: str) -> None:
        """Assert that a proposed change target is not immutable.

        Raises:
            SafetyBoundaryError: If the target is immutable.
        """
        immutable_targets = {
            "kernel_abi": self.kernel_abi is False,
            "nki_protocol": self.nki_protocol is False,
            "capability_bounds": self.capability_bounds is False,
            "approval_rules": self.approval_rules is False,
            "credential_policy": self.credential_policy is False,
            "self_source_code": self.self_source_code is False,
        }
        if target in immutable_targets:
            raise SafetyBoundaryError(
                f"Cannot modify '{target}' — it is an immutable boundary. "
                f"Only governance-approved changes may modify immutable boundaries."
            )


class SafetyBoundaryError(Exception):
    """Raised when an adaptive system attempts to modify an immutable boundary."""

    pass
