# Claim-Evidence Contract v1

Status: implemented and native-validated  
Stage: P14  
Evidence level: integrated-host  
Updated: 2026-08-30

## Authority

`nous_runtime.evidence.claims.ClaimEvidenceGraph` is the workspace-scoped
authority for current Claim/Evidence graph state. It persists an atomic
materialized state at `.nous/evidence/claims.json`.

The existing `EventStream` remains the only lifecycle ledger. There is no
Claim-specific event store.

## Claim contract

A Claim contains:

- `claim_id`, `statement`;
- `task_id`, `run_id`, `trace_id`;
- `evidence_refs`, `source_refs`, `snapshot_refs`;
- bounded `confidence`;
- `created_by`, `created_at`;
- `verification_state`;
- structured `provenance`.

Canonical verification states are `unverified`, `supported`,
`partially_supported`, `conflicted`, and `rejected`.

The old `text`, `source_id`, and weighted `status` accessors remain
compatibility views. New code must use `statement`, `source_refs`, and
`verification_state`.

## Evidence association

Each Evidence association records a Claim, Source, optional immutable Snapshot,
optional Artifact, relation, strength, description, timestamp, and provenance.

The first matcher is deliberately deterministic:

1. accept explicit Source references;
2. validate every Source;
3. select the latest Snapshot for each Source;
4. bind its Artifact when available;
5. create a supporting association;
6. calculate verification state from evidence relations and strengths.

It is not a semantic theorem prover. It never invents Sources, Snapshots, or
Artifacts.

## Traceability

The Runtime supports both directions:

~~~text
Claim -> Evidence -> Snapshot -> Source
Source -> Evidence -> Claims
~~~

Claim detail also resolves Artifact and structured Citation data. Broken or
cross-source Snapshot references fail closed.

## Verification

A supporting-only set is `supported` when its strongest association is at
least 0.5, otherwise `partially_supported`. Mixed evidence is
`partially_supported` when supporting strength wins and `conflicted` when
contradicting strength is equal or greater. Contradicting-only evidence is
`rejected`.

The governed verification API refuses a requested state that does not match the
associated evidence. In particular, a Claim cannot be marked supported without
supporting evidence.

## Events

The canonical EventStream records:

- `claim.created`;
- `claim.evidence_attached`;
- `claim.verified`;
- `claim.conflicted`;
- `claim.rejected`.

The `claim.` prefix is protected by EventStream retention rules.

## Governed API

Read routes:

- `GET /api/v1/research/claims`;
- `GET /api/v1/research/claims/{claim_id}`;
- `GET /api/v1/research/sources/{source_id}/claims`.

Local mutation routes:

- `POST /api/v1/research/claims`;
- `POST /api/v1/research/claims/{claim_id}/evidence`;
- `POST /api/v1/research/claims/{claim_id}/verify`.

Mutations use the registered `research.claim.manage` capability and the
existing ExecutionAuthorizationGate/one-use Approval Lease. They are classified
as reversible local writes.

## Desktop

The existing Research workbench now loads persisted Claims, lets the user choose
a persisted Source, proposes a statement, displays the explicit approval card,
retries the identical reviewed request, and shows verification state, evidence
count, Claim ID, and Trace ID.

## Boundaries

- The v1 matcher is reference-based, not semantic entailment.
- Document IR/DOCX/PDF production remains P17.
- The NSIS package is rebuilt but its install/upgrade/uninstall/reinstall
  lifecycle remains uncertified.
- Global network boundary closure remains P15 work.
