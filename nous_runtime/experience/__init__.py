# -*- coding: utf-8 -*-
"""Experience Runtime — Long-term learning and policy optimization.

Transforms Nous from a reliable executor into a system that improves
from every execution, discovering patterns, optimizing policies,
and recommending better approaches over time.

Lifecycle: NEW → VALIDATED → TRUSTED → DEPRECATED
"""

from nous_runtime.experience.exceptions import (
    ExperienceCollectionError,
    ExperienceError,
    ExperiencePatternError,
    ExperienceSecurityError,
    ExperienceStoreError,
    ExperienceValidationError,
)
from nous_runtime.experience.models import (
    ExperiencePattern,
    ExperienceRecord,
    PolicyProposal,
    Recommendation,
)
from nous_runtime.experience.schema import (
    EXPERIENCE_SCHEMA_VERSION,
    ExperienceSource,
    ExperienceStatus,
    PatternType,
    RecommendationType,
)
from nous_runtime.experience.store import ExperienceStore


def __getattr__(name: str):
    _deferred = {
        "ExperienceCollector": "nous_runtime.experience.collector",
        "PatternEngine": "nous_runtime.experience.pattern",
        "SimilarityEngine": "nous_runtime.experience.similarity",
        "ExperienceLearner": "nous_runtime.experience.learning",
        "PolicyOptimizer": "nous_runtime.experience.policy_optimizer",
        "RecommendationEngine": "nous_runtime.experience.recommendation",
        "ExperienceAnalyzer": "nous_runtime.experience.analyzer",
        "ExperienceGuard": "nous_runtime.experience.security",
        "ExperienceAccessRequest": "nous_runtime.experience.security",
        "ExperienceAccessDecision": "nous_runtime.experience.security",
    }
    if name in _deferred:
        import importlib
        mod = importlib.import_module(_deferred[name])
        return getattr(mod, name)
    raise AttributeError(f"module 'nous_runtime.experience' has no attribute {name!r}")


__all__ = [
    "ExperienceRecord", "ExperiencePattern", "PolicyProposal", "Recommendation",
    "EXPERIENCE_SCHEMA_VERSION", "ExperienceStatus", "ExperienceSource",
    "PatternType", "RecommendationType",
    "ExperienceStore", "ExperienceCollector", "PatternEngine", "SimilarityEngine",
    "ExperienceLearner", "PolicyOptimizer", "RecommendationEngine",
    "ExperienceAnalyzer", "ExperienceGuard",
    "ExperienceError", "ExperienceValidationError", "ExperienceStoreError",
    "ExperienceCollectionError", "ExperiencePatternError", "ExperienceSecurityError",
]
