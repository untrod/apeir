# -*- coding: utf-8 -*-
"""Schema Validator — output format and data integrity checks."""

from __future__ import annotations

import json
import logging
from typing import Any

from nous_runtime.evaluation.models import EvaluationEvidence
from nous_runtime.evaluation.schema import EvaluationDimension, EvidenceKind

_log = logging.getLogger("nous.evaluation.validators.schema")


class SchemaValidator:
    """Validates output schema: expected fields, types, data integrity."""

    dimension: str = EvaluationDimension.CORRECTNESS.value
    source: str = "schema_validator"

    def validate(
        self,
        target: Any,
        context: dict[str, Any] | None = None,
    ) -> list[EvaluationEvidence]:
        ctx = context or {}
        evidence: list[EvaluationEvidence] = []

        # Check if target has expected schema
        expected_schema = ctx.get("expected_schema")
        if expected_schema:
            evidence.extend(self._validate_schema(target, expected_schema))
        else:
            # Basic structural check
            evidence.extend(self._check_structure(target))

        return evidence

    def _validate_schema(self, target: Any, expected: dict) -> list[EvaluationEvidence]:
        """Validate target against an expected schema definition."""
        checks_passed = 0
        checks_total = 0
        detail_checks: list[dict] = []

        for field, expected_type in expected.items():
            checks_total += 1
            actual = None

            if isinstance(target, dict):
                actual = target.get(field)
            elif hasattr(target, field):
                actual = getattr(target, field)
            else:
                detail_checks.append({"field": field, "status": "missing", "expected": expected_type})
                continue

            # Type check
            type_ok = self._check_type(actual, expected_type)
            if type_ok:
                checks_passed += 1
                detail_checks.append({"field": field, "status": "ok", "expected": expected_type})
            else:
                detail_checks.append({
                    "field": field, "status": "type_mismatch",
                    "expected": expected_type, "actual": type(actual).__name__,
                })

        score = checks_passed / max(checks_total, 1)
        passed = score >= 0.8

        return [EvaluationEvidence(
            kind=EvidenceKind.AUTOMATED_CHECK.value,
            dimension=self.dimension,
            summary=f"Schema: {checks_passed}/{checks_total} checks passed",
            passed=passed, score=score, source=self.source,
            detail={"checks": detail_checks},
        )]

    def _check_structure(self, target: Any) -> list[EvaluationEvidence]:
        """Basic structural validation without a schema."""
        checks: list[str] = []

        # Check if target is serializable
        try:
            json.dumps(target if isinstance(target, dict) else {"value": str(target)})
            checks.append("serializable")
        except Exception:
            pass

        # Check if target has expected common fields
        if isinstance(target, dict):
            for field in ("id", "status", "result"):
                if field in target:
                    checks.append(f"has_{field}")

        passed = len(checks) > 0
        return [EvaluationEvidence(
            kind=EvidenceKind.AUTOMATED_CHECK.value,
            dimension=self.dimension,
            summary=f"Structure: {len(checks)} basic checks passed",
            passed=passed, score=0.7 if passed else 0.0, source=self.source,
            detail={"checks": checks},
        )]

    @staticmethod
    def _check_type(value: Any, expected: str) -> bool:
        """Check if value matches expected type string."""
        type_map = {
            "str": str, "string": str,
            "int": int, "integer": int,
            "float": float, "number": (int, float),
            "bool": bool, "boolean": bool,
            "list": list, "array": list,
            "dict": dict, "object": dict,
            "null": type(None), "none": type(None),
        }
        expected_types = type_map.get(expected.lower(), str)
        if not isinstance(expected_types, tuple):
            expected_types = (expected_types,)
        return isinstance(value, expected_types)
