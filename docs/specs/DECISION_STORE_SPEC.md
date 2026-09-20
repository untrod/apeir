# Decision Store Spec

Nous is an Open Intelligence Runtime.

## Purpose

The decision store is the canonical persistence layer for Runtime Intelligence lifecycle data.

It is intentionally file-first and does not require a database dependency.

## Protocol

`DecisionStore` supports:

- append lifecycle event
- persist decision snapshot
- persist outcome
- persist assessment
- persist feedback
- read decision
- read outcome
- read complete timeline
- list decisions
- list outcomes
- find incomplete decisions
- verify integrity
- rebuild indexes
- compact storage
- report stats

## Implementations

Current implementations:

- `InMemoryDecisionStore`
- `JsonlDecisionStore`

`JsonlDecisionStore` writes under `.nous/intelligence/`:

- `events.jsonl`
- `snapshots.jsonl`
- `outcomes.jsonl`
- `assessments.jsonl`
- `feedback.jsonl`
- `metrics.jsonl`
- `indexes/`
- `manifests/`

## File Behavior

Writes are append-only and protected by a process-local reentrant lock.

Duplicate event, decision, outcome, assessment, and feedback IDs are ignored.

Invalid or truncated JSONL lines are skipped during reads and counted by integrity verification.

Index rebuild writes deterministic decision and outcome ID lists under `indexes/`.

Compaction is exposed as an explicit operation. CLI compaction defaults to dry-run and requires `--force` for execution.

## Compatibility

Legacy `.nous/decisions` history remains readable.

`DecisionHistory.append()` writes legacy history and records the canonical lifecycle snapshot.

`DecisionHistory.append_outcome()` writes legacy outcome rows and bridges them into canonical execution outcomes.
