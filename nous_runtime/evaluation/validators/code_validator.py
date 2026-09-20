# -*- coding: utf-8 -*-
"""Code Validator — linting, compilation, type checking."""

from __future__ import annotations

import logging
import subprocess
import sys
from pathlib import Path
from typing import Any

from nous_runtime.evaluation.models import EvaluationEvidence
from nous_runtime.evaluation.schema import EvaluationDimension, EvidenceKind

_log = logging.getLogger("nous.evaluation.validators.code")


class CodeValidator:
    """Validates code quality: ruff lint, compileall, type checking."""

    dimension: str = EvaluationDimension.MAINTAINABILITY.value
    source: str = "code_validator"

    def validate(
        self,
        target: Any,
        context: dict[str, Any] | None = None,
    ) -> list[EvaluationEvidence]:
        ctx = context or {}
        evidence: list[EvaluationEvidence] = []
        cwd = ctx.get("cwd", str(Path.cwd()))
        target_path = ctx.get("target_path", ".")

        # -- ruff --
        evidence.extend(self._check_ruff(target_path, cwd, ctx))

        # -- compileall --
        evidence.extend(self._check_compile(target_path, cwd, ctx))

        return evidence

    def _check_ruff(self, target_path: str, cwd: str, ctx: dict) -> list[EvaluationEvidence]:
        try:
            result = subprocess.run(
                [sys.executable, "-m", "ruff", "check", target_path, "--output-format=concise"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                cwd=cwd,
                timeout=ctx.get("timeout", 60),
            )
            passed = result.returncode == 0
            issues = [line for line in result.stdout.splitlines() if line.strip()]
            score = 1.0 if passed else max(0.0, 1.0 - len(issues) * 0.1)
            return [EvaluationEvidence(
                kind=EvidenceKind.LINT_RESULT.value,
                dimension=self.dimension,
                summary=f"ruff: {'PASS' if passed else f'{len(issues)} issues'}",
                passed=passed, score=score, source="ruff",
                detail={"returncode": result.returncode, "issue_count": len(issues)},
            )]
        except Exception as exc:
            return [EvaluationEvidence(
                kind=EvidenceKind.LINT_RESULT.value,
                dimension=self.dimension,
                summary=f"ruff: ERROR ({exc})",
                passed=False, score=0.0, source="ruff",
                detail={"error": str(exc)},
            )]

    def _check_compile(self, target_path: str, cwd: str, ctx: dict) -> list[EvaluationEvidence]:
        try:
            result = subprocess.run(
                [sys.executable, "-m", "compileall", "-q", target_path],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                cwd=cwd,
                timeout=ctx.get("timeout", 60),
            )
            passed = result.returncode == 0
            return [EvaluationEvidence(
                kind=EvidenceKind.COMPILE_CHECK.value,
                dimension=EvaluationDimension.CORRECTNESS.value,
                summary=f"compileall: {'PASS' if passed else 'FAIL'}",
                passed=passed,
                score=1.0 if passed else 0.0,
                source="compileall",
                detail={"returncode": result.returncode},
            )]
        except Exception as exc:
            return [EvaluationEvidence(
                kind=EvidenceKind.COMPILE_CHECK.value,
                dimension=EvaluationDimension.CORRECTNESS.value,
                summary=f"compileall: ERROR ({exc})",
                passed=False, score=0.0, source="compileall",
                detail={"error": str(exc)},
            )]
