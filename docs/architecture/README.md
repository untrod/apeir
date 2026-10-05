# Authoritative architecture

Read these five documents in order. Each has a distinct responsibility; product
pages, protocol details and milestone audits extend them rather than introducing
an alternative authority or execution model.

| Contract | Responsibility |
| --- | --- |
| [Project constitution and Distribution boundary](DISTRIBUTION.md) | Purpose, invariants, Kernel/runtime-service scope and replaceability |
| [Security Contract](SECURITY_CONTRACT.md) | Authority, Operation policy, human approval, grants, credentials and trusted identity |
| [Execution Path](EXECUTION_PATH.md) | Existing admitted execution routes; no Agent/Provider shortcuts |
| [State Ownership and failure semantics](STATE_OWNERSHIP.md) | Durable owners, receipt/observation distinction, UNKNOWN and reconciliation |
| [Provider model](PROVIDER_CONTRACT.md) | Replaceable roles, canonical SDK boundaries and exercised conformance |

Supporting contracts are [Runtime Coordination](RUNTIME_COORDINATION.md), the
[Reality audit](REALITY_ARCHITECTURE_AUDIT.md),
[Compute Mesh execution/recovery](../compute-mesh/EXECUTION_RECOVERY.md),
[public Developer Platform](../development/DEVELOPER_PLATFORM.md) and
[Control Plane specification](CONTROL_CENTER_SPEC.md).
Wire formats remain in [`docs/protocol`](../protocol/); specialized specifications
remain in [`docs/specs`](../specs/). The [Kernel Foundation reference](FOUNDATION_1_0.md)
is scoped to the independently released Kernel. Root/legacy architecture pages
are navigation or explicitly historical references, not competing specifications.

## Architecture Consolidation Gate audit

Starting Distribution: `6960175c2a554d813047ea7c462f0447bc204584`.
Kernel remains `87fd1b2ff28ef14ab1a515a58162592b452fda2e`.
The audit inspected the existing Kernel boundary, SDK/Provider interfaces,
AgentSession/Work Harness/Workflow/Distributed Work, Reality Device/Node,
Governance/approval/credentials, receipts, observations, verification, Artifact
CAS and recovery paths. No implementation system was replaced or duplicated.

| Concern | Classification | Consolidation |
| --- | --- | --- |
| Kernel NKI versus Distribution service authority | EXTEND | Correct broad Kernel-only ownership claims; explicitly name both existing scopes |
| Project constitution and invariant entrypoint | MISSING → supplied | Extend existing Distribution boundary; no redundant constitution document |
| Root/v1 architecture, Runtime Boundary and Execution Contract | EXTEND | Preserve URLs as navigation; remove obsolete diagrams/direct-invoke pseudocode from normative use |
| Kernel Foundation profiles | REUSE | Retain as scoped Kernel reference; not physical acceptance evidence |
| Agent definition, AgentSession, Work Harness and Project cursor | REUSE | Different existing coordination/data roles; handlers still use canonical Workflow/Work |
| Kernel compute Device versus Reality Device | REUSE | Different resources; public SDK preserves legacy Device and exposes ManagedDevice |
| Scheduler/graph versus Governance | REUSE | Placement/relationships remain advisory; no grant authority |
| Legacy approval/modes versus Operation Broker and trusted human boundary | EXTEND | Identify current four-decision Operation contract and legacy compatibility scope |
| Artifact metadata versus CAS bytes; Receipt versus Observation | REUSE | Name canonical owners and required evidence binding; no second artifact/verifier system |
| Local durable Work/Governance/Node recovery | EXTEND | Describe actual local lock/transaction and at-most-once evidence semantics, not imaginary distributed consistency |
| Physical acceptance, real external identity/provider deployment and scale | MISSING | Explicit pending qualification; never inferred from simulation or a declaration |

## Fresh-reader acceptance questions

- **Why does Scheduler placement not grant authority?** Placement selects an
  eligible executor; existing Governance must independently admit the bound
  Operation and revalidate current scope, expiry and revocation.
- **Why is a Device different from a Node?** A Node executes Work under a
  cryptographic identity; a Device is the managed resource observed/affected.
  Transport addresses are routes, not that resource's stable identity.
- **Why is a Receipt different from an Effect?** A Receipt is bound execution
  evidence. Independently acquired fresh state determines the expected effect;
  execution success alone cannot establish MATCH.
- **Why is UNKNOWN fail-closed?** Missing, stale, contradictory or unsupported
  evidence cannot establish the required authorization/effect fact. Neither a
  model assertion nor human approval supplies that missing fact.
- **Why reconcile an uncertain side effect?** Delivery may have succeeded before
  its response was lost. Read original persisted journals/evidence and acquire
  a fresh Observation; valid authority cannot justify executing it again.

These explanations follow existing production contracts and tested simulation;
they do not claim hardware, cross-site or native qualification. Documentation
validation uses the repository's existing link/hygiene/security checks and
architecture regressions. No new documentation or validation framework is added.

### Consolidation validation

Architecture/repository regressions: **245 passed**. Existing document/link,
comment, identity, release-version, Ruff, compile and security checks pass;
**245 Markdown files** have valid local links and security reports **0 findings**.
This is a documentation-only gate: the immediately preceding M3.6 source state
has **650 passed, 3 skipped** affected regressions and **3600 passed, 35 skipped,
9 unchanged local baseline failures** in the full repository, with successful
Desktop and Multi-Arch CI. No runtime implementation, Kernel or component lock
is changed by consolidation. The pushed documentation SHA and CI status are
reported after local/remote agreement and hygiene verification.
