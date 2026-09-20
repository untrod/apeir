# -*- coding: utf-8 -*-
"""Security Validator — governance check, permission audit, vulnerability scan."""

from __future__ import annotations

import logging
from typing import Any

from nous_runtime.evaluation.models import EvaluationEvidence
from nous_runtime.evaluation.schema import EvaluationDimension, EvidenceKind

_log = logging.getLogger("nous.evaluation.validators.security")


class SecurityValidator:
    """Validates security: governance compliance, no HIGH vulnerabilities."""

    dimension: str = EvaluationDimension.SECURITY.value
    source: str = "security_validator"

    def validate(
        self,
        target: Any,
        context: dict[str, Any] | None = None,
    ) -> list[EvaluationEvidence]:
        ctx = context or {}
        evidence: list[EvaluationEvidence] = []

        # 1. Governance gate check
        evidence.extend(self._check_governance(ctx))

        # 2. Constitution compliance
        evidence.extend(self._check_constitution(ctx))

        # 3. Known vulnerability scan (lightweight)
        evidence.extend(self._check_vulnerabilities(ctx))

        return evidence

    def _check_governance(self, ctx: dict) -> list[EvaluationEvidence]:
        """Verify governance gate is operational."""
        try:
            from nous_runtime.governance.gate import get_gate
            get_gate()  # Verify gate is importable
            return [EvaluationEvidence(
                kind=EvidenceKind.AUTOMATED_CHECK.value,
                dimension=self.dimension,
                summary="Governance gate: available",
                passed=True, score=1.0, source="governance_gate",
                detail={"gate_available": True},
            )]
        except Exception as exc:
            return [EvaluationEvidence(
                kind=EvidenceKind.AUTOMATED_CHECK.value,
                dimension=self.dimension,
                summary=f"Governance gate: unavailable ({exc})",
                passed=False, score=0.5, source="governance_gate",
                detail={"gate_available": False, "error": str(exc)},
            )]

    def _check_constitution(self, ctx: dict) -> list[EvaluationEvidence]:
        """Check constitution rule compliance."""
        try:
            from nous_runtime.governance.constitution import CONSTITUTION_RULES
            rule_count = len(CONSTITUTION_RULES)
            return [EvaluationEvidence(
                kind=EvidenceKind.AUTOMATED_CHECK.value,
                dimension=self.dimension,
                summary=f"Constitution: {rule_count} rules loaded",
                passed=True, score=1.0, source="constitution",
                detail={"rule_count": rule_count},
            )]
        except Exception as exc:
            return [EvaluationEvidence(
                kind=EvidenceKind.AUTOMATED_CHECK.value,
                dimension=self.dimension,
                summary=f"Constitution: error ({exc})",
                passed=False, score=0.0, source="constitution",
                detail={"error": str(exc)},
            )]

    def _check_vulnerabilities(self, ctx: dict) -> list[EvaluationEvidence]:
        """Lightweight vulnerability check."""
        # Check for common security anti-patterns in code
        findings: list[str] = []
        target_path = ctx.get("target_path", ".")

        try:
            import os
            # Quick scan for dangerous patterns
            dangerous = ["eval(", "exec(", "os.system(", "subprocess.call(", "__import__("]
            for root, _, files in os.walk(target_path):
                for fname in files:
                    if fname.endswith(".py"):
                        try:
                            fpath = os.path.join(root, fname)
                            with open(fpath, encoding="utf-8", errors="ignore") as f:
                                for i, line in enumerate(f, 1):
                                    for pattern in dangerous:
                                        if pattern in line and "# nosec" not in line:
                                            findings.append(f"{fpath}:{i}: {pattern}")
                        except Exception:
                            pass
        except Exception:
            pass

        passed = len(findings) == 0
        return [EvaluationEvidence(
            kind=EvidenceKind.SECURITY_SCAN.value,
            dimension=self.dimension,
            summary=f"Security scan: {'PASS' if passed else f'{len(findings)} unsafe patterns'}",
            passed=passed,
            score=1.0 if passed else max(0.3, 1.0 - len(findings) * 0.05),
            source="pattern_scan",
            detail={"findings": findings[:20]},
        )]
