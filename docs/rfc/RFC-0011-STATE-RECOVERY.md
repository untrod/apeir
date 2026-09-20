# RFC-0011: State Journal & Crash Recovery

- **Status:** Draft | **Depends on:** RFC-0001, RFC-0002

## Append-Only Journal

All state transitions recorded in SQLite journal. Entries never modified or deleted. Ordered by monotonic sequence number.

## Execution Path

Command → Validate → Append Intent → CAS State Transition → Perform Side Effect → Append Observation → Commit / Compensate.

## 17-State Workload Lifecycle

CREATED→VALIDATING→VALIDATED→REJECTED|ADMITTED→PLACED→PREPARING→RUNNING→QUIESCING→CHECKPOINTING→CHECKPOINTED→RECOVERING→SUCCEEDED|FAILED|CANCELLED|LOST|QUARANTINED.

## Crash Recovery

On restart: open journal → replay all entries → reconstruct workload states → re-acquire leases → mark lost workloads → resume interrupted workloads.

## Guarantees

- CAS with Generation + Fencing Token on every transition
- Idempotent replay (same journal → same state)
- At-least-once delivery with idempotency dedup
- NOT exactly-once (cannot guarantee across external side effects)

## Fault Injection Tests

Kernel crash, engine crash, driver crash, SQLite/WAL interrupt, node disconnect, network partition, lease expiry, cancel+complete race.

See `kernel/crates/nous-state/src/` for implementation.
