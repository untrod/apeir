# -*- coding: utf-8 -*-
"""Experience Runtime schema — enums, constants."""

from __future__ import annotations

from enum import Enum

from nous_runtime.schema_registry import EXPERIENCE_SCHEMA_VERSION  # noqa: F401 - public re-export



class ExperienceStatus(str, Enum):
    """Lifecycle status of an experience record."""
    NEW = "new"              # Freshly collected
    VALIDATED = "validated"  # Confirmed by multiple occurrences
    TRUSTED = "trusted"      # High confidence, actively used
    DEPRECATED = "deprecated"  # No longer relevant


class ExperienceSource(str, Enum):
    """Where the experience came from."""
    DECISION = "decision"
    AGENT = "agent"
    EVALUATION = "evaluation"
    PROVIDER = "provider"
    USER = "user"
    SYSTEM = "system"


class PatternType(str, Enum):
    """Types of discoverable patterns."""
    SUCCESS = "success"          # "This approach works well"
    FAILURE = "failure"          # "This approach consistently fails"
    FIX = "fix"                  # "This fixes a known problem"
    CONFIGURATION = "configuration"  # "These settings work well together"
    DEPENDENCY = "dependency"    # "These dependencies conflict/resolve"
    WORKFLOW = "workflow"        # "This sequence of steps works"


class RecommendationType(str, Enum):
    """Types of recommendations."""
    AGENT = "agent"
    PROVIDER = "provider"
    APPROACH = "approach"
    CONFIG = "config"
    DEVICE = "device"
    DEPENDENCY = "dependency"
