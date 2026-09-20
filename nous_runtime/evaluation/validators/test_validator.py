# -*- coding: utf-8 -*-
"""Test Validator — runs pytest and reports results."""

from __future__ import annotations

import logging
import subprocess
import sys
from pathlib import Path
from typing import Any

from nous_runtime.evaluation.models import EvaluationEvidence
from nous_runtime.evaluation.schema import EvaluationDimension, EvidenceKind

_log = logging.getLogger("nous.evaluation.validators.test")


class TestValidator:
    """Runs pytest against a target path and produces evidence."""

    dimension: str = EvaluationDimension.CORRECTNESS.value
    source: str = "pytest"

    def validate(
        self,
        target: Any,
        context: dict[str, Any] | None = None,
    ) -> list[EvaluationEvidence]:
        """Run pytest and return evidence."""
        ctx = context or {}
        evidence: list[EvaluationEvidence] = []

        test_path = ctx.get("test_path", "tests/")
        cwd = ctx.get("cwd", str(Path.cwd()))

        try:
            result = subprocess.run(
                [sys.executable, "-m", "pytest", test_path, "-q", "--tb=line"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                cwd=cwd,
                timeout=ctx.get("timeout", 120),
            )
            passed = result.returncode == 0
            stdout = result.stdout
            stderr = result.stderr

            # Parse test count
            total = 0
            for line in stdout.splitlines():
                if "passed" in line:
                    import re
                    nums = re.findall(r'\d+', line)
                    if nums:
                        total = sum(int(n) for n in nums)

            score = 1.0 if passed else max(0.0, 0.5 if total > 0 else 0.0)
            summary = f"pytest: {'PASS' if passed else 'FAIL'} ({total} tests)"

            evidence.append(EvaluationEvidence(
                kind=EvidenceKind.TEST_RESULT.value,
                dimension=self.dimension,
                summary=summary,
                passed=passed,
                score=score,
                source=self.source,
                detail={
                    "returncode": result.returncode,
                    "stdout_tail": stdout[-500:] if stdout else "",
                    "stderr_tail": stderr[-200:] if stderr else "",
                },
            ))

        except subprocess.TimeoutExpired:
            evidence.append(EvaluationEvidence(
                kind=EvidenceKind.TEST_RESULT.value,
                dimension=self.dimension,
                summary="pytest: TIMEOUT",
                passed=False, score=0.0, source=self.source,
                detail={"error": "timeout"},
            ))
        except FileNotFoundError:
            evidence.append(EvaluationEvidence(
                kind=EvidenceKind.TEST_RESULT.value,
                dimension=self.dimension,
                summary="pytest: NOT FOUND (pytest not installed)",
                passed=False, score=0.0, source=self.source,
                detail={"error": "pytest not found"},
            ))
        except Exception as exc:
            evidence.append(EvaluationEvidence(
                kind=EvidenceKind.TEST_RESULT.value,
                dimension=self.dimension,
                summary=f"pytest: ERROR ({exc})",
                passed=False, score=0.0, source=self.source,
                detail={"error": str(exc)},
            ))

        return evidence
