# -*- coding: utf-8 -*-
"""
Capability Contract — formal specification for every capability.

Implements §9.2 of the master plan. Each capability registered in the
Runtime must declare its contract: name, schema, risk, timeout, retry
policy, idempotency, rollback behavior, verification method, and audit
requirements.

This contract is enforced by the Admission Pipeline before execution.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from nous_runtime.kernel.error_codes import ErrorCode, NousResult


class RetryStrategy(str, Enum):
    NONE = "none"              # Never retry
    LINEAR = "linear"          # Fixed interval
    EXPONENTIAL = "exponential"  # Exponential backoff
    ADAPTIVE = "adaptive"      # Based on error type


class Idempotency(str, Enum):
    """Whether a capability can be safely retried."""
    IDEMPOTENT = "idempotent"              # Safe to retry any number of times
    CONDITIONAL = "conditional"            # Safe only if same params
    NOT_IDEMPOTENT = "not_idempotent"      # Must not retry without user confirmation


class VerificationMethod(str, Enum):
    """How to verify the capability's output."""
    NONE = "none"                # No verification needed
    ASSERTION = "assertion"      # Check output against expected
    SCRIPT = "script"            # Run a verification script
    LLM_REVIEW = "llm_review"    # Have a reviewer model check
    TEST_RERUN = "test_rerun"    # Rerun tests and compare
    DIFF_CHECK = "diff_check"    # Check git diff
    MANUAL = "manual"            # Human must verify


@dataclass
class CapabilityContract:
    """Formal contract for a single capability.

    Every capability registered in the Runtime MUST declare this contract.
    The Admission Pipeline enforces it before allowing execution.
    """

    # Identity
    capability_id: str = ""              # e.g., "project.read_file"
    name: str = ""                       # Human-readable name
    description: str = ""                # What it does
    version: str = "1.0.0"

    # Input / Output schema
    input_schema: dict[str, Any] = field(default_factory=dict)   # JSON Schema
    output_schema: dict[str, Any] = field(default_factory=dict)  # JSON Schema

    # Risk & Security
    risk_level: str = "MEDIUM"           # READ_ONLY | LOW | MEDIUM | HIGH | CRITICAL
    required_permissions: list[str] = field(default_factory=list)

    # Execution constraints
    allowed_nodes: list[str] = field(default_factory=list)  # Empty = all nodes
    denied_nodes: list[str] = field(default_factory=list)   # Explicitly blocked
    timeout_seconds: int = 30
    max_output_bytes: int = 1_000_000    # 1MB default

    # Retry & Reliability
    retry_strategy: RetryStrategy = RetryStrategy.EXPONENTIAL
    max_retries: int = 3
    retry_delay_ms: int = 1000
    retryable_errors: list[str] = field(default_factory=lambda: [
        "TIMEOUT", "UNAVAILABLE", "OVERLOADED", "CIRCUIT_OPEN",
    ])

    # Idempotency
    idempotency: Idempotency = Idempotency.CONDITIONAL

    # Rollback
    rollback_capability_id: str = ""     # Capability to undo this operation
    rollback_timeout_seconds: int = 30

    # Verification
    verification_method: VerificationMethod = VerificationMethod.NONE
    verification_script: str = ""        # Script path or inline check
    verification_timeout_seconds: int = 60

    # Audit
    audit_level: str = "standard"        # none | standard | detailed
    audit_retention_days: int = 90

    # Metadata
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "capability_id": self.capability_id,
            "name": self.name,
            "description": self.description,
            "version": self.version,
            "input_schema": self.input_schema,
            "output_schema": self.output_schema,
            "risk_level": self.risk_level,
            "required_permissions": self.required_permissions,
            "allowed_nodes": self.allowed_nodes,
            "timeout_seconds": self.timeout_seconds,
            "retry_strategy": self.retry_strategy.value,
            "max_retries": self.max_retries,
            "idempotency": self.idempotency.value,
            "rollback_capability_id": self.rollback_capability_id,
            "verification_method": self.verification_method.value,
            "audit_level": self.audit_level,
        }

    def is_retryable_error(self, error_code: str) -> bool:
        return error_code in self.retryable_errors

    def is_allowed_node(self, node_id: str) -> bool:
        if self.denied_nodes and node_id in self.denied_nodes:
            return False
        if self.allowed_nodes:
            return node_id in self.allowed_nodes
        return True


# Contract registry

class CapabilityContractRegistry:
    """Registry of all capability contracts with validation."""

    def __init__(self):
        self._contracts: dict[str, CapabilityContract] = {}
        self._register_defaults()

    def register(self, contract: CapabilityContract) -> NousResult[CapabilityContract]:
        cid = contract.capability_id
        if not cid:
            return NousResult.err(ErrorCode.INVALID_ARGUMENT, message="capability_id required")
        self._contracts[cid] = contract
        return NousResult.ok(contract)

    def get(self, capability_id: str) -> NousResult[CapabilityContract]:
        contract = self._contracts.get(capability_id)
        if contract is None:
            return NousResult.err(ErrorCode.NOT_FOUND,
                                  message=f"No contract for '{capability_id}'")
        return NousResult.ok(contract)

    def list_all(self) -> list[CapabilityContract]:
        return list(self._contracts.values())

    def get_risk_level(self, capability_id: str) -> str:
        contract = self._contracts.get(capability_id)
        return contract.risk_level if contract else "MEDIUM"

    def _register_defaults(self) -> None:
        """Seed with standard capability contracts."""
        defaults = [
            CapabilityContract(
                capability_id="project.read_file",
                name="Read File",
                description="Read contents of a file in the workspace",
                risk_level="read_only",
                retry_strategy=RetryStrategy.NONE,
                idempotency=Idempotency.IDEMPOTENT,
                verification_method=VerificationMethod.NONE,
            ),
            CapabilityContract(
                capability_id="project.write_file",
                name="Write File",
                description="Write or overwrite a file in the workspace",
                risk_level="medium",
                timeout_seconds=60,
                rollback_capability_id="project.restore_file",
                idempotency=Idempotency.CONDITIONAL,
                verification_method=VerificationMethod.DIFF_CHECK,
            ),
            CapabilityContract(
                capability_id="project.run_tests",
                name="Run Tests",
                description="Execute the project test suite",
                risk_level="low",
                timeout_seconds=300,
                max_output_bytes=5_000_000,
                retry_strategy=RetryStrategy.EXPONENTIAL,
                max_retries=2,
                verification_method=VerificationMethod.TEST_RERUN,
            ),
            CapabilityContract(
                capability_id="network.fetch",
                name="Governed Network Fetch",
                description="Fetch a public HTTP resource through the Runtime Network Gateway",
                risk_level="high",
                required_permissions=["network"],
                timeout_seconds=120,
                max_output_bytes=5_242_880,
                retry_strategy=RetryStrategy.NONE,
                max_retries=0,
                idempotency=Idempotency.IDEMPOTENT,
                verification_method=VerificationMethod.ASSERTION,
                audit_level="detailed",
            ),
            CapabilityContract(
                capability_id="git.commit",
                name="Git Commit",
                description="Create a git commit with changes",
                risk_level="medium",
                rollback_capability_id="git.reset",
                verification_method=VerificationMethod.DIFF_CHECK,
            ),
            CapabilityContract(
                capability_id="git.push",
                name="Git Push",
                description="Push commits to remote",
                risk_level="high",
                required_permissions=["git.push"],
                rollback_capability_id="git.revert_push",
                verification_method=VerificationMethod.NONE,
                audit_level="detailed",
            ),
            CapabilityContract(
                capability_id="shell.execute_sandboxed",
                name="Sandboxed Shell",
                description="Execute command in a sandboxed environment",
                risk_level="medium",
                timeout_seconds=120,
                retry_strategy=RetryStrategy.EXPONENTIAL,
                max_retries=1,
                idempotency=Idempotency.NOT_IDEMPOTENT,
                verification_method=VerificationMethod.ASSERTION,
                required_permissions=["shell.sandboxed"],
            ),
            CapabilityContract(
                capability_id="model.run_inference",
                name="Model Inference",
                description="Run a model inference request",
                risk_level="low",
                timeout_seconds=300,
                retry_strategy=RetryStrategy.EXPONENTIAL,
                max_retries=3,
            ),
        ]
        for c in defaults:
            self.register(c)
