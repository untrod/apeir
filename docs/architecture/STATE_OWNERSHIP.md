# State ownership and failure semantics

Each mutable domain has one authoritative owner within its explicitly selected
execution scope. A view, graph, Provider response, UI status or model statement
cannot override that owner. See the [project constitution](DISTRIBUTION.md).

## Kernel-managed scope

For NKI workloads, the independently released Kernel owns Workload lifecycle,
compute claims/resource leases, scheduling decisions, semantic state, knowledge
assertions and durable effect admission/verification/commit in its journal.
Distribution uses NKI and public ABI clients. Kernel receipt/effect facts cannot
be synthesized by Python compatibility objects or a Controller projection.
The Kernel's Python data models are not an independent production executor.

## Distribution runtime-service scope

These existing stores own Distribution state; they are not copies of a Kernel
journal and do not imply Kernel traversal.

| State | Canonical owner | Durable record |
| --- | --- | --- |
| AgentSession coordination | `AgentSessionCoordinator` / session store | `.nous/agent_sessions.db` |
| Plan execution, run, pause/resume | existing Workflow Runtime / WorkflowStore | `.nous/workflows.db` and its checkpoints |
| Distributed Work lifecycle, placement and dispatch | `DistributedWorkStore` / `NodeRelayServer` | Controller `distributed-works.json` and relay spool |
| Node identity, delivery and terminal execution evidence | Node Runtime | Node identity and workload journals |
| Device lifecycle and stable identity | Reality `DeviceRegistry` | existing Reality device store |
| Resource relationships | `ResourceGraph` | persisted projection of canonical IDs, not authority |
| Operation policy, grants, approval and revocation | existing Governance Gate, Broker and Store | governance database and append-oriented audit chain |
| Human sessions and bound mutation nonces | trusted Control Plane human boundary | existing GovernanceStore tables |
| Credential handle references and leases | existing CredentialBroker | GovernanceStore lifecycle records; raw values stay in protected SecretBackend |
| Artifact and evidence bytes | `ContentAddressedArtifactStore` | SHA-256-addressed immutable objects and provenance metadata |
| OperationReceipt candidate | existing producer/validator | signed Node result, Node journal and Work evidence references |
| Observation and EffectVerification | existing read Work and `EffectVerifier` | independently acquired Observation and bound verification evidence |
| Events/activity | existing EventStream | durable per-run records; live bus/SSE are projections |
| Work Harness deliberation/recovery | existing Work Harness / checkpoint store | workspace checkpoints and AgentExecutionRuntime records |
| Project/conversation cursor | existing Project Coordinator/Execution Service | project, work-item, attempt and checkpoint tables |

An SDK Agent definition, an AgentSession and a Work Harness checkpoint describe
different existing concerns. They do not permit a new agent executor. Legacy
Artifact metadata and CAS content also have distinct concerns; metadata alone
is not evidence integrity. The Control Plane and Console read these stores and
route supported mutations through existing Governance, never their own ledger.

## Admission, durability and commitment

1. Bind the current authenticated actor, Work, Operation, Node, Capability,
   resource and Artifact IDs at the established boundary. Placement cannot
   grant authority; discovery cannot establish trust.
2. Revalidate grants, expiry, revocation, resource facts and credential scope
   immediately before execution. Missing authority or UNKNOWN blocks admission.
3. Use the existing store's transaction/lock and expected-state checks. Local
   Work reads and mutations share its file lock; atomic replacement is not a
   substitute for read/write exclusion. Kernel CAS/fencing remains Kernel-owned.
4. Persist Node execution admission before an effect. Repeated original delivery
   identities resolve to their recorded outcome; changed bindings are rejected.
5. Validate signed result/receipt bindings and CAS digests. A receipt describes
   execution evidence, not the independently observed state of a Device.
6. Effectful Reality Work commits only on independent fresh MATCH. A successful
   execution result cannot substitute for an Observation. MISMATCH and UNKNOWN
   are uncommitted, including after a valid human approval.
7. Raw credentials never enter ordinary state, audit, events or artifacts.
   Audit is append-oriented with integrity checks, not a claim of resistance
   to a privileged host administrator or immutable external storage.

Read-only Work can verify its execution result and artifacts without claiming a
physical effect. A `COMMITTED` label must be interpreted with its selected scope,
Work policy and bound evidence; it cannot manufacture a different scope's proof.

## Failure and recovery

| Evidence condition | Required response |
| --- | --- |
| Missing/expired/revoked authority or credentials | Deny current execution; do not reuse after reconnect |
| Explicit negative or contradictory independent state | MISMATCH; no effect commit |
| Stale, missing, conflicting or unsupported state/evidence | UNKNOWN; fail closed |
| Node disconnect or delayed response | Preserve original Work and delivery state; await/reconcile evidence |
| Duplicate original receipt/result | Validate identical bindings and deduplicate; no new effect |
| Effect occurred, acknowledgement lost | Reconcile persisted Node/Work evidence and acquire a fresh Observation |
| Executing journal exists but terminal receipt is missing | RECOVERY_REQUIRED/UNKNOWN; no blind replay or fabricated receipt |
| Approval remains valid during uncertain recovery | Authority still does not prove delivery safety; reconcile first |
| Interrupted commit with durable MATCH evidence | Revalidate persisted bindings/evidence; commit the original verified outcome |
| Device rediscovery/reconnect or locator change | Preserve stable identity/trust and terminal revocation |

Do not interpret cancellation, interruption, failed execution or a missing
response as proof that a physical effect stopped or never happened. An
acknowledgement records operator attention; it does not resolve UNKNOWN. A new
plan is explicit deliberation and must not silently replace the originally
approved Operation. See [Compute Mesh recovery](../compute-mesh/EXECUTION_RECOVERY.md)
and the [Reality fault matrix](REALITY_ARCHITECTURE_AUDIT.md#recovery-and-faults).

## Current deployment assumptions

The accepted Cloud slices use one local durable Governance authority and
Node-owned simulation state. Shared local file/SQLite transactions do not prove
cross-site consistency, distributed consensus or Controller high availability.
Remote secret transport, fleet/federation and physical faults require their
own later acceptance evidence. M3.3-C remains PENDING.
