# -*- coding: utf-8 -*-
"""Evaluation Runtime exceptions."""

from __future__ import annotations


class EvaluationError(Exception):
    """Base exception for Evaluation Runtime."""


class EvaluationValidationError(EvaluationError, ValueError):
    """Evaluation data validation failed."""


class EvaluationCriteriaError(EvaluationError):
    """Criteria definition or resolution failed."""


class EvaluationScoringError(EvaluationError):
    """Quality scoring failed."""


class EvaluationVerificationError(EvaluationError):
    """Execution verification failed."""


class EvaluationRegressionError(EvaluationError):
    """Regression evaluation failed."""


class EvaluationSecurityError(EvaluationError, PermissionError):
    """Unauthorized evaluation access or modification."""
