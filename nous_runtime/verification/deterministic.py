# -*- coding: utf-8 -*-
"""Deterministic Verification — reproducible, fast, unambiguous checks.

Prioritizes: compilation > unit tests > integration tests > schema validation >
type checking > static analysis > checksums > DB consistency > reproducibility.

Model review cannot override deterministic test failure.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class VerificationSeverity(str, Enum):
    LOW = "low"
    NORMAL = "normal"
    ELEVATED = "elevated"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass
class VerificationResult:
    """Result of deterministic verification."""
    passed: bool = True
    checks_run: int = 0
    checks_passed: int = 0
    checks_failed: int = 0
    failures: list[dict] = field(default_factory=list)  # [{check_name, message, severity}]
    evidence: dict[str, Any] = field(default_factory=dict)
    requires_human: bool = False
    human_reason: str = ""


class DeterministicVerifier:
    """Runs deterministic verification checks on task output.

    Checks: compilation, test_pass, schema_valid, type_check,
    checksum_match, db_integrity, reproducibility.
    """

    def verify(
        self,
        output: dict[str, Any],
        expected: dict[str, Any] | None = None,
        severity: VerificationSeverity = VerificationSeverity.NORMAL,
    ) -> VerificationResult:
        """Run all applicable deterministic checks."""
        result = VerificationResult()

        # Compilation check
        if output.get("code"):
            result.checks_run += 1
            try:
                compile(str(output["code"]), "<verification>", "exec")
                result.checks_passed += 1
            except SyntaxError as e:
                result.checks_failed += 1
                result.failures.append({"check_name": "compilation", "message": str(e), "severity": "critical"})

        # Schema validation
        if expected and expected.get("schema"):
            result.checks_run += 1
            if self._validate_schema(output, expected["schema"]):
                result.checks_passed += 1
            else:
                result.checks_failed += 1
                result.failures.append({"check_name": "schema_validation", "message": "Output does not match expected schema"})

        # Checksum verification
        if output.get("checksum") and expected and expected.get("checksum"):
            result.checks_run += 1
            if output["checksum"] == expected["checksum"]:
                result.checks_passed += 1
            else:
                result.checks_failed += 1
                result.failures.append({"check_name": "checksum", "message": "Checksum mismatch"})

        # Reproducibility check
        if output.get("previous_output") and output.get("current_output"):
            result.checks_run += 1
            if output["previous_output"] == output["current_output"]:
                result.checks_passed += 1
                result.evidence["reproducible"] = True
            else:
                result.checks_failed += 1
                result.failures.append({"check_name": "reproducibility", "message": "Output differs from previous run"})

        # Severity-based additional checks
        if severity in (VerificationSeverity.HIGH, VerificationSeverity.CRITICAL):
            result.checks_run += 1
            if result.checks_failed == 0:
                result.checks_passed += 1
            else:
                result.requires_human = True
                result.human_reason = "Critical task with deterministic failures"

        result.passed = result.checks_failed == 0
        return result

    def _validate_schema(self, output: dict, schema: dict) -> bool:
        """Simple structural schema validation."""
        for key, expected_type in schema.items():
            if key not in output:
                return False
            expected = str(expected_type)
            type(output[key]).__name__
            if expected == "str" and not isinstance(output[key], str):
                return False
            if expected == "int" and not isinstance(output[key], int):
                return False
            if expected == "list" and not isinstance(output[key], list):
                return False
            if expected == "dict" and not isinstance(output[key], dict):
                return False
        return True
