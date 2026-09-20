# Candidate Model Spec

Nous is an Open Intelligence Runtime.

## Candidate Types

Supported candidate types:

- `model`
- `provider`
- `retrieval_strategy`
- `recovery_strategy`
- `capability`
- `execution_plan`

## Canonical Models

Scheduler models:

- `DecisionCandidate`
- `CandidateCapability`
- `CandidateEstimate`
- `CandidateConstraintResult`
- `CandidateEvaluation`
- `CandidateRanking`
- `CandidateSelection`
- `SelectionContext`
- `SchedulingRequest`
- `SchedulingResult`

All scheduler records include schema-ready fields, runtime version where applicable, stable IDs, deterministic serialization, and secret-redacted metadata.

## Feature Provenance

Scheduling features record:

- value
- unit
- source
- provenance type
- confidence
- observed timestamp
- expiration timestamp
- stale status

Supported provenance values:

- `declared`
- `observed`
- `estimated`
- `verified`
- `unknown`
- `stale`

Unknown and stale values are preserved and penalized. They are not silently converted to zero, maximum, or average.
