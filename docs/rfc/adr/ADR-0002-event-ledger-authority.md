# ADR-0002: EventStream Is the Developer Event Ledger Authority

- Status: Accepted
- Date: 2026-08-29
- Scope: Runtime, Kernel adapters, Desktop Developer Platform

## Decision

Nous uses `nous_runtime.events.EventStream` as the single durable authority for
developer-operation events. The phrase **Event Ledger** names this contract; it
does not introduce a second database, broker, or sequence generator.

Every governed workbench mutation or execution creates a canonical `run_id` and
appends versioned `RunEvent` records. The stream owns per-run monotonic sequence
assignment, durable JSONL persistence, redaction, bounded replay, idempotent
event IDs, retention protection, indexes, and deterministic snapshots.

## Authority map

| Concern | Authority | Consumer |
| --- | --- | --- |
| Event schema version | `nous_runtime.schema_registry.EVENT_SCHEMA_VERSION` | Runtime, Desktop, SDK |
| Run state | `RunRecord` reconstructed from `RunEvent` | Runs page, recovery, diagnostics |
| Sequence allocation | `EventStream.emit` under process/file locks | Replay and reconnect clients |
| File-change evidence | `file.changed` payload with before/after SHA-256 | Workbench, audit, rollback tooling |
| Command output | bounded `command.output` chunks | Desktop output view, diagnostics |
| Test result | `test.started` / `test.completed` | Runs page, evaluation consumers |
| Replay cursor | per-run `sequence` | `/runtime/runs/{run_id}/events` |

ProjectStore may reference a Runtime run, but it does not duplicate run-event
truth. Desktop state is a cache and must be reconstructible from Runtime APIs.
Kernel execution adapters emit through the Runtime boundary; they do not write a
parallel ledger.

## Append contract

A workbench operation appends, in order:

1. `run.created`
2. `command.proposed`
3. `run.started`
4. operation evidence (`command.started`, `command.output`, `file.changed`,
   `test.started`, or `test.completed` as applicable)
5. exactly one terminal `run.completed` or `run.failed`

Persisted payloads contain workspace-relative paths only. Credentials, bearer
tokens, full environment blocks, and caller-supplied arbitrary shell commands
are forbidden. Output is bounded and redacted by EventStream before durable
persistence.

## Replay and compatibility

Consumers resume after the last acknowledged sequence. They must ignore unknown
event types and fields and use `schema_version` to select migrations. Additive
payload fields are backward compatible. Renaming an event type, changing the
meaning of a field, or resetting a per-run sequence requires a new schema
version and migration tests.

## Consequences

- Workbench write and run results always return a `run_id` that resolves to
  durable evidence.
- Status screens distinguish registered capabilities from actually available
  executors/providers.
- New IDE, document, simulation, and connector surfaces must append to this
  authority instead of creating their own histories.
- A failure to persist an event is an operation failure, not a best-effort log
  omission.