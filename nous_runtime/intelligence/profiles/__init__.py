"""Model and Provider Profile intelligence (P5.6).

Canonical, dynamic, provenance-aware, confidence-aware model and provider
information for the scheduler.
"""

from nous_runtime.intelligence.profiles.models import (
    PROFILE_SCHEMA_VERSION,
    CapabilityClaim,
    CapabilityObservation,
    CapabilityState,
    DiscoveryRecord,
    ModelLifecycle,
    ModelProfile,
    PerformanceAggregate,
    PerformanceObservation,
    PricingProfile,
    ProbeDefinition,
    ProbeResult,
    ProfileSnapshot,
    ProfileValue,
    ProviderProfile,
    RateLimitProfile,
    ValueProvenance,
    snapshot_hash,
)
from nous_runtime.intelligence.profiles.store import (
    InMemoryProfileStore,
    JsonlProfileStore,
    ProfileStore,
)
from nous_runtime.intelligence.profiles.discovery import (
    LocalManifestDiscovery,
    ModelDiscoveryOrchestrator,
    ProviderRegistryDiscovery,
    StaticConfigDiscovery,
    build_provisional_profile,
    build_provisional_provider_profile,
)
from nous_runtime.intelligence.profiles.probes import (
    BUILTIN_PROBES,
    ProbeFramework,
    ProbeExecutor,
)
from nous_runtime.intelligence.profiles.observations import (
    aggregate_observations,
    record_observation,
)
from nous_runtime.intelligence.profiles.freshness import (
    DEFAULT_TTLS,
    apply_staleness,
    compute_confidence_decay,
    profile_staleness_report,
)
from nous_runtime.intelligence.profiles.mapping import (
    MAPPING_VERSION,
    profiles_to_scheduler_metadata,
)

__all__ = [
    # models
    "PROFILE_SCHEMA_VERSION",
    "CapabilityClaim",
    "CapabilityObservation",
    "CapabilityState",
    "DiscoveryRecord",
    "ModelLifecycle",
    "ModelProfile",
    "PerformanceAggregate",
    "PerformanceObservation",
    "PricingProfile",
    "ProbeDefinition",
    "ProbeResult",
    "ProfileSnapshot",
    "ProfileValue",
    "ProviderProfile",
    "RateLimitProfile",
    "ValueProvenance",
    "snapshot_hash",
    # store
    "InMemoryProfileStore",
    "JsonlProfileStore",
    "ProfileStore",
    # discovery
    "LocalManifestDiscovery",
    "ModelDiscoveryOrchestrator",
    "ProviderRegistryDiscovery",
    "StaticConfigDiscovery",
    "build_provisional_profile",
    "build_provisional_provider_profile",
    # probes
    "BUILTIN_PROBES",
    "ProbeFramework",
    "ProbeExecutor",
    # observations
    "aggregate_observations",
    "record_observation",
    # freshness
    "DEFAULT_TTLS",
    "apply_staleness",
    "compute_confidence_decay",
    "profile_staleness_report",
    # mapping
    "MAPPING_VERSION",
    "profiles_to_scheduler_metadata",
]
