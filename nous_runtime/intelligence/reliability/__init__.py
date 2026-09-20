"""Provider Reliability and Circuit Control (P5.7).

Resilient, observable, bounded, and safe provider execution under failure.
"""

from nous_runtime.intelligence.reliability.models import (
    RELIABILITY_SCHEMA_VERSION,
    NON_RETRYABLE_CATEGORIES,
    VALID_CIRCUIT_TRANSITIONS,
    DEFAULT_CIRCUIT_CONFIG,
    DEFAULT_RETRY_POLICY,
    CircuitConfig,
    CircuitState,
    CircuitStateRecord,
    FailureCategory,
    FailureSignal,
    FallbackExecution,
    ProviderExecutionResult,
    ProviderHealthSnapshot,
    ReliabilityWindow,
    RetryAttempt,
    RetryPolicy,
    snapshot_hash,
)
from nous_runtime.intelligence.reliability.classifier import classify_failure
from nous_runtime.intelligence.reliability.circuit_breaker import CircuitBreaker
from nous_runtime.intelligence.reliability.retry import RetryBudget, RetryController
from nous_runtime.intelligence.reliability.fallback import (
    FallbackBoundary,
    FallbackCompatibility,
    FallbackExecutionPolicy,
    FallbackSafetyAssessment,
    assess_fallback_safety,
)
from nous_runtime.intelligence.reliability.store import (
    InMemoryReliabilityStore,
    JsonlReliabilityStore,
    ReliabilityStore,
)
from nous_runtime.intelligence.reliability.fault_injection import FaultConfig, FaultInjector, FAULT_TYPES
from nous_runtime.intelligence.reliability.executor import execute_provider, execute_provider_observation, observation_from_provider_result

__all__ = [
    # models
    "RELIABILITY_SCHEMA_VERSION",
    "NON_RETRYABLE_CATEGORIES",
    "VALID_CIRCUIT_TRANSITIONS",
    "DEFAULT_CIRCUIT_CONFIG",
    "DEFAULT_RETRY_POLICY",
    "CircuitConfig",
    "CircuitState",
    "CircuitStateRecord",
    "FailureCategory",
    "FailureSignal",
    "FallbackExecution",
    "ProviderExecutionResult",
    "ProviderHealthSnapshot",
    "ReliabilityWindow",
    "RetryAttempt",
    "RetryPolicy",
    "snapshot_hash",
    # classifier
    "classify_failure",
    # circuit breaker
    "CircuitBreaker",
    # retry
    "RetryBudget",
    "RetryController",
    # fallback safety
    "FallbackBoundary",
    "FallbackCompatibility",
    "FallbackExecutionPolicy",
    "FallbackSafetyAssessment",
    "assess_fallback_safety",
    # store
    "InMemoryReliabilityStore",
    "JsonlReliabilityStore",
    "ReliabilityStore",
    # fault injection
    "FaultConfig",
    "FaultInjector",
    "FAULT_TYPES",
    # executor
    "execute_provider",
    "execute_provider_observation",
    "observation_from_provider_result",
]
