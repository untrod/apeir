"""Policy-driven Runtime Intelligence — v1.0 Intelligence & Discovery Program.

Batch 1 modules: trace, dataset, replay, baselines, metrics, shadow mode.
"""

from nous_runtime.intelligence.engine import RuntimePolicyEngine, default_engine
from nous_runtime.intelligence.history import DecisionHistory
from nous_runtime.intelligence.lifecycle import (
    DecisionLifecycleService,
    build_assessment,
    build_execution_outcome,
    build_feedback,
    lifecycle_for_workspace,
    record_provider_outcome,
    record_recovery_outcome,
    record_retrieval_outcome,
)
from nous_runtime.intelligence.models import (
    CandidateRejection,
    CandidateCapability,
    CandidateConstraintResult,
    CandidateEstimate,
    CandidateEvaluation,
    CandidateRanking,
    CandidateSelection,
    CandidateType,
    DECISION_SCHEMA_VERSION,
    DecisionCandidate,
    DecisionConstraint,
    DecisionContext,
    DecisionExplanation,
    DecisionFeature,
    DecisionOutcome,
    DecisionReason,
    DecisionRecommendation,
    DecisionRecord,
    DecisionRequest,
    DecisionScore,
    DecisionStatus,
    DecisionType,
    ExecutionOutcome,
    FallbackPlan,
    FeatureProvenance,
    LifecycleTransition,
    OUTCOME_SCHEMA_VERSION,
    OutcomeAssessment,
    OutcomeAttribution,
    OutcomeError,
    OutcomeEvidence,
    OutcomeFeedback,
    OutcomeMetric,
    PolicyEvaluationTrace,
    RuntimeDecision,
    SCHEDULING_SCHEMA_VERSION,
    SchedulingRequest,
    SchedulingResult,
    SelectionContext,
    VALID_DECISION_TRANSITIONS,
    assessment_id_for,
    feedback_id_for,
    lifecycle_event_id_for,
    migrate_record,
    outcome_id_for,
    sanitize_mapping,
    snapshot_hash,
    validate_status_transition,
)
from nous_runtime.intelligence.registry import PolicyRegistry
from nous_runtime.intelligence.scheduler import DeterministicScheduler, schedule_candidates, scheduling_request_from_dict
from nous_runtime.intelligence.store import InMemoryDecisionStore, JsonlDecisionStore
from nous_runtime.intelligence.task import TaskAnalysis, TaskAnalyzer, analyze_task
from nous_runtime.intelligence.adaptive import AdaptiveRoutingEngine

# Batch 1: Execution Intelligence Foundation
from nous_runtime.intelligence.trace import ExecutionTraceRecord, TraceCollector, TraceStore
from nous_runtime.intelligence.dataset import DatasetRecord, DatasetRegistry, DatasetBuilder
from nous_runtime.intelligence.replay import ReplayEngine, ReplayComparator
from nous_runtime.intelligence.baselines import BaselineRegistry, BaselinePolicy
from nous_runtime.intelligence.metrics import MetricsComputer, MetricsReport, METRIC_DEFINITIONS

__all__ = [
    # Existing
    "CandidateRejection", "CandidateCapability", "CandidateConstraintResult",
    "CandidateEstimate", "CandidateEvaluation", "CandidateRanking",
    "CandidateSelection", "CandidateType", "DECISION_SCHEMA_VERSION",
    "DecisionCandidate", "DecisionConstraint", "DecisionContext",
    "DecisionExplanation", "DecisionFeature", "DecisionHistory",
    "DecisionLifecycleService", "DecisionOutcome", "DecisionReason",
    "DecisionRecommendation", "DecisionRecord", "DecisionRequest",
    "DecisionScore", "DecisionStatus", "DecisionType", "ExecutionOutcome",
    "FallbackPlan", "FeatureProvenance", "InMemoryDecisionStore",
    "JsonlDecisionStore", "LifecycleTransition", "OUTCOME_SCHEMA_VERSION",
    "OutcomeAssessment", "OutcomeAttribution", "OutcomeError",
    "OutcomeEvidence", "OutcomeFeedback", "OutcomeMetric", "PolicyRegistry",
    "PolicyEvaluationTrace", "RuntimeDecision", "RuntimePolicyEngine",
    "SCHEDULING_SCHEMA_VERSION", "SchedulingRequest", "SchedulingResult",
    "SelectionContext", "VALID_DECISION_TRANSITIONS", "DeterministicScheduler",
    "assessment_id_for", "build_assessment", "build_execution_outcome",
    "build_feedback", "default_engine", "feedback_id_for",
    "lifecycle_event_id_for", "lifecycle_for_workspace", "migrate_record",
    "outcome_id_for", "record_provider_outcome", "record_recovery_outcome",
    "record_retrieval_outcome", "sanitize_mapping", "schedule_candidates",
    "scheduling_request_from_dict", "snapshot_hash", "validate_status_transition",
    "TaskAnalysis", "TaskAnalyzer", "AdaptiveRoutingEngine", "analyze_task",
    # Batch 1: Execution Intelligence Foundation
    "ExecutionTraceRecord", "TraceCollector", "TraceStore",
    "DatasetRecord", "DatasetRegistry", "DatasetBuilder",
    "ReplayEngine", "ReplayComparator",
    "BaselineRegistry", "BaselinePolicy",
    "MetricsComputer", "MetricsReport", "METRIC_DEFINITIONS",
]
