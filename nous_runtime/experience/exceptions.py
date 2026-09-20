# -*- coding: utf-8 -*-
"""Experience Runtime exceptions."""

from __future__ import annotations


class ExperienceError(Exception):
    """Base exception for Experience Runtime."""


class ExperienceValidationError(ExperienceError, ValueError):
    """Experience data validation failed."""


class ExperienceStoreError(ExperienceError):
    """Experience persistence operation failed."""


class ExperienceCollectionError(ExperienceError):
    """Experience collection from sources failed."""


class ExperiencePatternError(ExperienceError):
    """Pattern discovery failed."""


class ExperienceSecurityError(ExperienceError, PermissionError):
    """Unauthorized experience access or modification."""
