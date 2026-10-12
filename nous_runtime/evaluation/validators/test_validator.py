# -*- coding: utf-8 -*-
"""Test Validator — runs pytest and reports results."""

from __future__ import annotations

import logging
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

from nous_runtime.evaluation.models import EvaluationEvidence
from nous_runtime.evaluation.schema import EvaluationDimension, EvidenceKind
from nous_runtime.core.redaction import redact_sensitive_data

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
            stdout = result.stdout
            stderr = result.stderr

            counts = None
            for line in stdout.splitlines():
                fields = re.findall(
                    r"(\d+)\s+(passed|failed|skipped|errors?|xfailed|xpassed|deselected|warnings?)\b",
                    line,
                )
                if fields:
                    counts = {
                        key.rstrip("s") if key in {"errors", "warnings"} else key: int(
                            value
                        )
                        for value, key in fields
                    }
            total = sum(
                (counts or {}).get(key, 0)
                for key in (
                    "passed",
                    "failed",
                    "skipped",
                    "error",
                    "xfailed",
                    "xpassed",
                )
            )
            executed_passes = (counts or {}).get("passed", 0)
            passed = (
                result.returncode == 0
                and executed_passes > 0
                and not any((counts or {}).get(key, 0) for key in ("failed", "error"))
            )
            outcome = "PASS" if passed else "FAIL" if result.returncode else "UNKNOWN"
            score = (
                1.0 if passed else 0.5 if result.returncode and executed_passes else 0.0
            )
            summary = f"pytest: {outcome} ({total if counts is not None else 'UNKNOWN'} tests)"

            evidence.append(
                EvaluationEvidence(
                    kind=EvidenceKind.TEST_RESULT.value,
                    dimension=self.dimension,
                    summary=summary,
                    passed=passed,
                    score=score,
                    source=self.source,
                    detail=redact_sensitive_data(
                        {
                            "returncode": result.returncode,
                            "test_counts": counts,
                            "test_count": total if counts is not None else None,
                            "stdout_tail": stdout[-500:] if stdout else "",
                            "stderr_tail": stderr[-200:] if stderr else "",
                        }
                    ),
                )
            )

        except subprocess.TimeoutExpired:
            evidence.append(
                EvaluationEvidence(
                    kind=EvidenceKind.TEST_RESULT.value,
                    dimension=self.dimension,
                    summary="pytest: TIMEOUT",
                    passed=False,
                    score=0.0,
                    source=self.source,
                    detail={"error": "timeout"},
                )
            )
        except FileNotFoundError:
            evidence.append(
                EvaluationEvidence(
                    kind=EvidenceKind.TEST_RESULT.value,
                    dimension=self.dimension,
                    summary="pytest: NOT FOUND (pytest not installed)",
                    passed=False,
                    score=0.0,
                    source=self.source,
                    detail={"error": "pytest not found"},
                )
            )
        except Exception as exc:
            evidence.append(
                EvaluationEvidence(
                    kind=EvidenceKind.TEST_RESULT.value,
                    dimension=self.dimension,
                    summary=f"pytest: ERROR ({exc})",
                    passed=False,
                    score=0.0,
                    source=self.source,
                    detail={"error": str(exc)},
                )
            )

        return evidence
