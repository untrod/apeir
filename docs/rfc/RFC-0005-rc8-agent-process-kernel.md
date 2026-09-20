# RFC-0005: RC8 — Durable Agent Process & Virtual Context Memory

- **Status:** Draft
- **Date:** 2026-08-05
- **Author:** Nous Architecture
- **Requires:** RC7 (Open Ecosystem & Platform Freeze)
- **Target:** RC8

## Abstract

RC7 established Nous as an open platform with stable external ABIs, Provider SDK,
OCI-based registry, and third-party extensibility. RC8 moves beyond platform
openness to establish Nous as an **AI operating system kernel** — managing
long-running Agent programs, virtualizing semantic context, scheduling across
the full program critical path, and producing independently verifiable execution
proofs.

This RFC defines four new kernel primitives and two new system services:

| Primitive | Analogy | Purpose |
|-----------|---------|---------|
| AgentProcess | OS Process | Durable, pausable, migratable AI program with lifecycle |
| Virtual Context Memory | Virtual Memory | Logical address space for semantic/KV/artifact state |
| Execution Hypergraph | Beyond DAG | Multi-node, multi-relation program structure |
| Proof-Carrying Action | Capability + Audit | Independently verifiable execution evidence |

## Motivation

Current AI runtimes (including Nous RC7) treat work as **requests** — single
inference calls, tool executions, or workflow steps. Real AI applications are
**programs** — long-running Agent loops with complex state, tool interactions,
approval gates, and failure modes that span minutes to hours.

The gap is visible in what Nous currently lacks compared to an OS:

| OS Concept | Nous RC7 | RC8 Target |
|-----------|----------|------------|
| Process | Workload/DAG (stateless, linear) | AgentProcess (stateful, branching, signal-aware) |
| Virtual Memory | Memory Fabric (physical tiers only) | Virtual Context Memory (logical → physical mapping) |
| Scheduler | Resource/placement scheduler | Program-aware critical-path scheduler |
| Signals | Cancel/Pause only | 11 AI-native signals (REPLAN, ESCALATE, MIGRATE, VERIFY...) |
| File System | Artifact store | Versioned, permissioned semantic state |
| Audit | Journal + governance | Proof-carrying actions with independent verification |

## Design

### 1. AgentProcess

```
AgentProcess {
    process_id: UUIDv7,
    parent_process_id: Option<UUIDv7>,
    process_group_id: UUIDv7,
    namespace: String,
    principal: PrincipalRef,
    program: ProgramRef,
    program_counter: u64,
    continuation: Continuation,
    mailbox: Vec<ProcessSignal>,
    context_address_space: ContextAddressSpace,
    capability_set: CapabilitySet,
    resource_domain: ResourceDomain,
    budgets: { quality, latency, cost, energy },
    checkpoint: Option<CheckpointRef>,
    effect_log: Vec<EffectReceipt>,
    status: AgentProcessStatus,
}
```

State machine: CREATED → READY → RUNNING → WAITING_* → SUSPENDED → CHECKPOINTING
→ MIGRATING → RECOVERING → COMPLETED/FAILED/CANCELLED/QUARANTINED (14 states).

Signals: PAUSE, RESUME, CANCEL, CHECKPOINT, REPLAN, ESCALATE_MODEL, REDUCE_BUDGET,
MIGRATE, VERIFY, QUARANTINE, TERMINATE.

### 2. Virtual Context Memory

Logical address space with 10 page types: TokenPage, SemanticPage, KVPage,
PrefixPage, RetrievalPage, ToolResultPage, ArtifactPage, SummaryPage,
EvidencePage, CheckpointPage.

Each page has: content hash, schema, model compatibility, namespace, data
classification, permissions, provenance, version, invalidation conditions,
reuse probability, recompute cost, load cost, quality risk, current physical
location.

Page fault handler: permission check → local copy → semantic equivalent →
remote load → recompute → summary fallback → model conversion → failure.

Consistency: STRONG | VERSIONED | EVENTUAL | IMMUTABLE | DERIVED | EPHEMERAL.

### 3. Execution Hypergraph

Extends the existing DAG-based ExecutionGraph with hyperedges:

- SharedContext (multiple nodes share same KV/page)
- SharedBudget (cost pool across nodes)
- AtomicCommit (all-or-nothing group)
- CompensateGroup (rollback if any fails)
- ConsistencyConstraint (ordering/invalidation dependency)
- ResourceContention (mutual exclusion on device)
- SecurityBoundary (trust domain edge)
- FaultDomain (shared failure scope)

### 4. Proof-Carrying Execution

Every side-effect action carries:

```
ProofCarryingAction {
    canonical_action,    // What was intended
    principal,           // Who authorized
    capability,          // Under what grant
    policy_decision,     // Governance outcome
    approval_receipt,    // Human/system approval
    input_digest,        // SHA-256 of inputs
    execution_environment, // Sandbox/engine identity
    effect_intent,       // Declared side effects
    effect_receipt,      // Actual observed effects
    output_digest,       // SHA-256 of outputs
    causal_parent,       // Previous action in chain
    replay_descriptor,   // How to replay for verification
    attestation,         // Cryptographic signature
}
```

WorkloadCertificate: aggregate proof of the entire program execution.

### 5. Durable Speculative Execution

PURE phases (no side effects) can be speculated:
- Model inference (read-only)
- Retrieval (read-only)
- Static analysis, compilation checks, test plans

SIDE-EFFECT phases default to NO speculation:
- Send, commit, delete, pay, control devices

Flow: Speculate → Produce Candidate → Validate Preconditions → Governance → Commit/Discard.

### 6. System Digital Twin

Profiles: DeviceProfile, EngineProfile, ModelProfile, NetworkProfile,
StorageProfile, WorkloadProfile, FailureProfile, QualityProfile, EnergyProfile.

Updated continuously from execution telemetry. Used by scheduler for
distribution-aware placement (P50/P95/P99 predictions, not point estimates).

## Compatibility

- NKI v1beta1: EXTENDED (new methods for ProcessSignal, ContextPage, Proof), not BROKEN
- Engine ABI v1beta1: UNCHANGED
- Device ABI v1beta1: UNCHANGED
- Workload IR v1beta1: EXTENDED (ExecutionHypergraph), not BROKEN
- Resource Model v1beta1: UNCHANGED
- Scheduler 1.0: Preserved as safe fallback; Scheduler 2.0 is additive

## Out of Scope (for RC8)

- Training cluster management
- Full RLHF platform
- Custom GPU kernels
- Custom tensor compilers
- Custom container runtime
- Blockchain / decentralized compute markets
- Auto-modifying kernel code
- Industrial bus protocol adaptation

## References

- Agentix (NSDI '26): Agent programs as scheduling units
- SYMPHONY (NSDI '26): Compute-memory disaggregation for LLM serving
- Strata (OSDI '26): Tiered context caching
- Prism (NSDI '26): GPU memory elasticity across models
- Cortex (NSDI '26): Semantic knowledge caching
- libDSE (OSDI '26): Distributed speculative execution
- DynaRL (OSDI '26): Dynamic hypergraph scheduling
- CAVA (arXiv 2607.13716): Canonical action verification
- ServeGen (NSDI '26): Production LLM workload characterization
