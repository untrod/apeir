"""Public adaptive scoring API."""

from nous_runtime.intelligence.scoring.config import (
    DynamicWeightConfig,
    RoutingPolicy,
    RoutingWeights,
    StrategyThresholds,
)
from nous_runtime.intelligence.scoring.dimensions import (
    STANDARD_DIMENSIONS,
    CapabilityDimension,
)
from nous_runtime.intelligence.scoring.errors import (
    DuplicateFeedbackError,
    InvalidCapabilityDimensionError,
    InvalidFeedbackError,
    InvalidRoutingConfigurationError,
    NoEligibleModelError,
    RoutingComputationError,
)
from nous_runtime.intelligence.scoring.normalization import (
    clamp_01,
    finite_float,
    round_score,
)
from nous_runtime.intelligence.scoring.registry import (
    CapabilityDimensionRegistry,
    default_dimension_registry,
)
from nous_runtime.intelligence.scoring.vectors import (
    ModelCapabilityVector,
    TaskRequirementVector,
    build_model_vector,
    build_task_vector,
)
from nous_runtime.intelligence.scoring.confidence import (
    DecisionConfidenceBreakdown,
    estimate_decision_confidence,
    evidence_confidence,
)
from nous_runtime.intelligence.scoring.constraints import (
    ConstraintResult,
    RoutingConstraints,
    evaluate_constraints,
)
from nous_runtime.intelligence.scoring.pareto import (
    deterministic_sort,
    dominates,
    pareto_frontier,
)
from nous_runtime.intelligence.scoring.utility import (
    CandidateScore,
    ScoreBreakdown,
    capability_fit,
    score_candidate,
)

__all__ = [
    "CapabilityDimension",
    "CapabilityDimensionRegistry",
    "CandidateScore",
    "ConstraintResult",
    "DecisionConfidenceBreakdown",
    "DuplicateFeedbackError",
    "DynamicWeightConfig",
    "InvalidCapabilityDimensionError",
    "InvalidFeedbackError",
    "InvalidRoutingConfigurationError",
    "ModelCapabilityVector",
    "NoEligibleModelError",
    "RoutingComputationError",
    "RoutingConstraints",
    "RoutingPolicy",
    "RoutingWeights",
    "STANDARD_DIMENSIONS",
    "ScoreBreakdown",
    "StrategyThresholds",
    "TaskRequirementVector",
    "build_model_vector",
    "build_task_vector",
    "capability_fit",
    "clamp_01",
    "default_dimension_registry",
    "finite_float",
    "deterministic_sort",
    "dominates",
    "estimate_decision_confidence",
    "evaluate_constraints",
    "evidence_confidence",
    "pareto_frontier",
    "round_score",
    "score_candidate",
]
