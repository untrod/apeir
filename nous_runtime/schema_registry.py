# -*- coding: utf-8 -*-
"""Central schema version registry for Nous Runtime.

All schema-aware modules MUST import their schema version constants from
this module. Do NOT define independent SCHEMA_VERSION constants in
individual modules — that creates version fragmentation and makes
schema migrations untrackable.

Canonical versions:
    CANONICAL_SCHEMA_VERSION        = "1.0.0"
    CANONICAL_SCHEMA_VERSION_SHORT  = "1.0"
    CANONICAL_PROTOCOL_VERSION      = "1.0"

All sub-schema versions are frozen at CANONICAL for the v1.0.0-rc1
release. After GA, individual schemas may diverge under a formal
schema evolution policy.

Import pattern:
    from nous_runtime.schema_registry import (
        DECISION_SCHEMA_VERSION,
        CONTEXT_SCHEMA_VERSION,
        ...
    )
"""

from __future__ import annotations

from nous_runtime._version import (
    CANONICAL_SCHEMA_VERSION,
    CANONICAL_SCHEMA_VERSION_SHORT,
    PROTOCOL_VERSION,
)

# Protocol
CANONICAL_PROTOCOL_VERSION = PROTOCOL_VERSION  # "1.0"

# Intelligence sub-schemas
DECISION_SCHEMA_VERSION = CANONICAL_SCHEMA_VERSION_SHORT  # "1.0"
OUTCOME_SCHEMA_VERSION = CANONICAL_SCHEMA_VERSION_SHORT  # "1.0"
SCHEDULING_SCHEMA_VERSION = CANONICAL_SCHEMA_VERSION_SHORT  # "1.0"
RELIABILITY_SCHEMA_VERSION = CANONICAL_SCHEMA_VERSION_SHORT  # "1.0"
PROFILE_SCHEMA_VERSION = CANONICAL_SCHEMA_VERSION_SHORT  # "1.0"
POLICY_SCHEMA_VERSION = CANONICAL_SCHEMA_VERSION_SHORT  # "1.0"

# Context sub-schemas
CONTEXT_SCHEMA_VERSION = CANONICAL_SCHEMA_VERSION  # "1.0.0"
STORE_SCHEMA_VERSION = CANONICAL_SCHEMA_VERSION  # "1.0.0"

# Events
EVENT_SCHEMA_VERSION = CANONICAL_SCHEMA_VERSION  # "1.0.0"

# Evaluation
EVALUATION_SCHEMA_VERSION = CANONICAL_SCHEMA_VERSION  # "1.0.0"
HISTORY_SCHEMA_VERSION = CANONICAL_SCHEMA_VERSION  # "1.0.0"

# Experience
EXPERIENCE_SCHEMA_VERSION = CANONICAL_SCHEMA_VERSION  # "1.0.0"

# Execution
EXECUTION_TRACE_SCHEMA_VERSION = CANONICAL_SCHEMA_VERSION  # "1.0.0"

# Governance
GOVERNANCE_SCHEMA_VERSION = CANONICAL_SCHEMA_VERSION  # "1.0.0"

# Agent
AGENT_SCHEMA_VERSION = CANONICAL_SCHEMA_VERSION  # "1.0.0"

# Capability
CAPABILITY_SCHEMA_VERSION = CANONICAL_SCHEMA_VERSION_SHORT  # "1.0"

# Planner / Observation
OBSERVATION_SCHEMA_VERSION = CANONICAL_SCHEMA_VERSION_SHORT  # "1.0"

# Project / Memory
MEMORY_RECORDS_SCHEMA_VERSION = CANONICAL_SCHEMA_VERSION_SHORT  # "1.0"

# Model Runtime (integer-typed for JSON compat)
MODEL_CONFIG_SCHEMA_VERSION = 1
MODEL_EVALUATION_SCHEMA_VERSION = 1
MODEL_OBSERVATION_SCHEMA_VERSION = CANONICAL_SCHEMA_VERSION  # "1.0.0"

# Connectivity / Project
CONNECTIVITY_PROJECT_SCHEMA_VERSION = CANONICAL_SCHEMA_VERSION_SHORT  # "1.0"

# Telemetry (new for RC1)
TELEMETRY_SCHEMA_VERSION = CANONICAL_SCHEMA_VERSION  # "1.0.0"

# Professional Document IR
DOCUMENT_SCHEMA_VERSION = "nous.document-ir/v1"

# Execution Environment contracts
ENVIRONMENT_SCHEMA_VERSION = "nous.environment/v1"
ENVIRONMENT_PROVIDER_SCHEMA_VERSION = "nous.environment-provider/v1"

# Reproducible Simulation contracts
SIMULATION_SCHEMA_VERSION = "nous.simulation/v1"
SIMULATION_RUN_SCHEMA_VERSION = "nous.simulation-run/v1"

# Scientific Capability Layer contracts
SCIENTIFIC_ANALYSIS_SCHEMA_VERSION = "nous.scientific-analysis/v1"
SCIENTIFIC_RESULT_SCHEMA_VERSION = "nous.scientific-result/v1"

# Desktop workspace manifest
WORKSPACE_SCHEMA_VERSION = "2.0.0"

# Vendor-neutral extension interchange contract
EXTENSION_SCHEMA_VERSION = "nous.extension/v1"


# Registry introspection


def all_schema_versions() -> dict[str, str | int]:
    """Return all registered schema version constants.

    Useful for CI validation: assert every value is either
    CANONICAL_SCHEMA_VERSION, CANONICAL_SCHEMA_VERSION_SHORT,
    or a known integer version.
    """
    result: dict[str, str | int] = {}
    for name, value in globals().items():
        if name.endswith("_SCHEMA_VERSION") and name != "CANONICAL_SCHEMA_VERSION":
            result[name] = value
    return result
