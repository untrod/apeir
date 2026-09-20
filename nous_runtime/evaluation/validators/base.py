# -*- coding: utf-8 -*-
"""Base validator protocol."""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from nous_runtime.evaluation.models import EvaluationEvidence


@runtime_checkable
class Validator(Protocol):
    """Interface for execution validators."""

    dimension: str
    source: str

    def validate(self, target: Any, context: dict[str, Any] | None = None) -> list[EvaluationEvidence]:
        """Run validation and return evidence."""
        ...
