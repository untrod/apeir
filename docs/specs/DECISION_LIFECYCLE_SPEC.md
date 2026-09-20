# Decision Lifecycle Spec

Nous is an Open Intelligence Runtime.

## Schema

Decision lifecycle records use `schema_version` and `runtime_version`.

Current decision schema version: `1.0`.

Older records without a schema version are read as legacy records and can be migrated through `migrate_record`.

## Canonical States

Decision statuses:

- `proposed`
- `evaluated`
- `selected`
- `authorized`
- `dispatched`
- `running`
- `succeeded`
- `failed`
- `cancelled`
- `timed_out`
- `outcome_recorded`
- `assessed`
- `closed`
- `superseded`

`completed` is accepted as a legacy compatibility status and is normalized to success when recording execution outcomes.

## Transition Table

Valid transitions:

- `proposed` -> `evaluated`, `cancelled`, `superseded`
- `evaluated` -> `selected`, `cancelled`, `superseded`
- `selected` -> `authorized`, `dispatched`, `cancelled`, `superseded`, `succeeded`, `failed`, `completed`
- `authorized` -> `dispatched`, `cancelled`, `timed_out`
- `dispatched` -> `running`, `succeeded`, `failed`, `cancelled`, `timed_out`, `completed`
- `running` -> `succeeded`, `failed`, `cancelled`, `timed_out`, `completed`
- `succeeded` -> `outcome_recorded`, `assessed`, `closed`
- `failed` -> `outcome_recorded`, `assessed`, `closed`
- `timed_out` -> `outcome_recorded`, `assessed`, `closed`
- `completed` -> `outcome_recorded`, `assessed`, `closed`
- `cancelled` -> `outcome_recorded`, `closed`
- `superseded` -> `closed`
- `outcome_recorded` -> `assessed`, `closed`
- `assessed` -> `closed`
- `closed` has no outgoing transitions

Invalid transitions are rejected by `validate_status_transition`.

## Lifecycle Events

Each transition is recorded as a `LifecycleTransition` with:

- stable `event_id`
- `decision_id`
- `from_status`
- `to_status`
- reason
- actor
- source
- optional `execution_id`
- optional `outcome_id`
- UTC timestamp
- redacted metadata

Duplicate lifecycle events are ignored by the store rather than appended again.

## Outcome Closure

Execution completion records an `ExecutionOutcome` and then transitions the decision to `outcome_recorded`.

Assessment records transition `outcome_recorded` to `assessed`.

Closing a lifecycle transitions the current valid state to `closed`.

Correction semantics should be represented as additional events. Existing lifecycle events are not silently mutated.

## Immutable Snapshot

Each decision stores:

- input snapshot
- context snapshot
- candidate snapshot
- policy ids
- policy versions
- policy sources
- policy hashes
- score breakdown
- rejected candidates
- fallback plan

Outcome records store decision and policy snapshot hashes so later replay can compare the executed decision with the current policy state.

## Compatibility

The existing `RuntimeDecision` type remains the public selected-decision object.

`DecisionRecord` wraps a `RuntimeDecision` for persisted record handling.

Legacy `.nous/decisions` records remain readable. New canonical lifecycle records are written under `.nous/intelligence`.
