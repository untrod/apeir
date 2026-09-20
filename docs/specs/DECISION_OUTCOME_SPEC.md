# Decision Outcome Spec

Nous is an Open Intelligence Runtime.

## Purpose

Decision outcomes describe what happened after a runtime decision was selected. They are append-only, JSON-serializable records used by CLI, Inspector, diagnostics, evaluation, and future policy learning.

## Models

Canonical outcome models:

- `ExecutionOutcome`
- `OutcomeAssessment`
- `OutcomeEvidence`
- `OutcomeMetric`
- `OutcomeAttribution`
- `OutcomeError`
- `OutcomeFeedback`

`DecisionOutcome` remains the selected-decision result embedded in `RuntimeDecision`.

## Required Fields

`ExecutionOutcome` includes:

- `schema_version`
- `runtime_version`
- stable `outcome_id`
- `decision_id`
- `execution_id`
- `task_id`
- `decision_type`
- selected candidate
- execution status
- trace and plan IDs when available
- UTC start and completion timestamps
- latency, cost, token usage, retry, and fallback fields when available
- optional error
- metrics, evidence, attribution, and delayed feedback
- decision snapshot hash
- policy snapshot hash
- redacted metadata

Unavailable metrics stay `null` or empty. The runtime does not fabricate values.

## Assessment Dimensions

Outcome assessment separates:

- execution success
- task success
- quality success
- policy compliance
- safety compliance
- user acceptance

These dimensions are independent and must not be collapsed into one Boolean.

## Secret Handling

Outcome serialization applies metadata redaction for sensitive keys such as API keys, authorization values, cookies, passwords, private keys, secrets, and credentials.

Usage fields such as `token_usage` are not secrets and remain available for observability.

## Integration Points

Outcome recording is available through:

- `record_retrieval_outcome`
- `record_provider_outcome`
- `record_recovery_outcome`
- `DecisionLifecycleService.record_execution_completion`

The planner pipeline records retrieval decision outcomes when a workspace exists. Provider and recovery outcome helpers are ready for execution surfaces that have provider call and recovery result data.
