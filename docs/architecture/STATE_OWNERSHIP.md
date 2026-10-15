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

CAS writers reload the current index under its existing shared file lock before
checking graph references or adding an object. Separate Workflow, Node and API
store instances must retain each other's evidence and original immutable
provenance; a corrupt persisted index blocks a write instead of being replaced by
an older in-memory snapshot. Pin, unpin and garbage collection also reload current
index and pin state under that same lock, preserving another instance's protected
objects and transitive evidence dependencies. Corrupt pin state blocks these
mutations. Object bytes still require digest verification.

Long-lived CAS readers also reload the existing atomically published index before
get/list/resolve/verify. Evidence published by another store instance is visible
without recreating the reader; corrupt current metadata raises an Artifact error
instead of letting an older cache certify integrity. Readers do not rewrite or
repair that evidence. This adds index reads, not a second cache or state owner.

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

Workflow recovery reads the original run's bound checkpoints. Definition/version,
inputs, dependencies, handler policy, attempt count and output digest are checked
before admitting another step. A completed-state label without matching checkpoint
evidence cannot unlock a dependent effect. Definitions and idempotency bindings
are immutable; cancellation and parallel completions use current store revisions.

Generic handlers have no implicit retry safety. Only a trusted host-supplied
Capability contract can establish bounded idempotent retries. Model parameters,
an approval or a requested retry count cannot establish that contract. A started
effect with no definite outcome becomes UNKNOWN and pauses Agent coordination;
it cannot enter automatic replanning. Existing journal-backed Work/Reality/agent
adapters may resume only to reconcile their original operation. Legacy unfinished
runs with incomplete evidence remain fenced instead of being silently certified.
Cancellation stops later admission; it does not prove an active effect stopped.

A bounded Workflow wait returning WAITING does not guarantee Controller Work is
terminal. Node journal state, signed terminal delivery and Controller projection
are separate points: Node can have persisted FAILED while Controller Work is
still RUNNING. Await the actual result and use the canonical reconciler to
project it; do not manufacture a terminal state or resubmit an Operation merely
because a wait deadline elapsed. Tests of denial must retain FAILED, zero-effect,
unchanged-resource and audit assertions after that real projection.

A fresh authenticated resource report also does not mean that an independent
read Work's signed terminal result has been delivered. Reality recovery may
verify the original mutation receipt, then pause while a separate observation
Work exceeds its bounded wait. The mutation remains VERIFIED, not COMMITTED;
no missing Observation implies MATCH. Acceptance continuation waits for that
exact read's terminal evidence and uses the canonical reconciler before resuming
the same Workflow once. The existing finalizer acquires a fresh independently
authorized read on continuation; it does not replay the mutation. Missing or
changed evidence remains fail-closed. Resource readiness, result delivery and
effect verification are distinct conditions with unchanged runtime deadlines.

An unavailable Node host probe cannot discard an already recorded Work result.
The existing authenticated Relay may reconcile the original journal and signed
assignment without a fresh host report. That mode rejects new execution and
changed Work/Node/Operation input bindings; uncertain execution stays
RECOVERY_REQUIRED. It publishes no replacement health or resource facts. A fresh
successful probe is still required before readiness can advance to ONLINE.
Controller placement also requires a signed resource report accepted after the
latest REGISTER, within the unchanged three-heartbeat freshness window. The
resource timestamp is Controller-observed and separate from generic liveness;
REGISTER, heartbeat and Device reports cannot renew old resource facts. A
resource timestamp ahead of the Controller clock is UNKNOWN for placement.
Absent resource inputs on existing connectivity calls fail closed. A
resumed session ID does not bind resources to its replacement connection.
Recent DEGRADED placement remains eligible only while both freshness windows
hold. Historical resource reports without their observed time remain visible
but cannot establish readiness. Original receipt reconciliation remains available
while placement is blocked, through the same trust and signed-result checks.

The legacy connectivity adapter's TCP `is_connected()` flag is distinct from
processing WELCOME and from readiness of the current send queue. A cached session
ID after reconnect is not a new handshake. Await the actual current session and
queue before a transport integration test proceeds, within the existing protocol
budget; fixed sleeps cannot establish these facts. A legacy WELCOME is not remote
human identity qualification or permission for a governed Operation. Canonical
Distributed Work still uses its signed Node admission and Governance boundaries.

Legacy delivery routes are published from an accepted HELLO/WELCOME session,
not a fixed timer. Cross-thread submission schedules a gateway-loop callback;
that callback rechecks the exact current route, session, writer, Node revocation,
capability, deadline and original QUEUED state before the existing assignment
and FIFO enqueue. Scheduling alone is not a persisted DELIVERED claim. If the route is
lost or replaced before admission, the original task stays QUEUED. A newly ready
route may deliver never-dispatched queued tasks; reconnect never republishes
DELIVERED, running or terminal tasks. EOF closes that connection, and its cleanup
cannot remove a successor's route. This repairs transport ordering only; it
creates no human identity, grant, Governance decision or physical-effect proof.

Local correction evidence: the missing-route contract reproduced **1 failed**
on the accepted prior implementation (it returned success and persisted
DELIVERED with no send queue). Final affected regressions have **609 passed**, repository contracts **244 passed**.
Final new contracts have **14 passed**; initial
combined connectivity tests had **29 passed**, and forced late HELLO, old-connection
cleanup and duplicate scheduling passed **60 cases across 20 rounds**. Full
configured init-container regression: **3812 passed, 47 skipped, 4 warnings**;
bare managed host: **3821 passed, 36 skipped, 2 unchanged orphan-process failures,
4 warnings**. Those failures and process identity assertions are preserved.
Ruff/format/compile/docs/link/hygiene/security and three component-lock contract
tests pass; actual locked native binaries remain missing/BLOCKED. Required
source/PR/main CI and checkpoint are separate prerequisites. Issue #4 and Windows
shutdown issue #8 remain open; this evidence does not prove all timing races absent.

Source `2992690040305441bdac34339411477d1d34c2e9` then exposed the previously
tracked Windows relay stop mechanism: Core `37552829192` recorded **1 failed,
3818 passed, 40 skipped, 4 warnings**. A keepalive close reached an uninterruptible
reconnect-backoff sleep, and the unchanged two-second stop assertion timed out.
The failed run is preserved in [issue #8 evidence](https://github.com/untrod/apeir/issues/8#issuecomment-6028532257).
Three deterministic pre-fix stop probes failed; the narrow correction waits on
stop with the unchanged jitter/exponential timeout instead of sleeping through it.
It grants no authority and changes neither session execution nor the Node journal.
Stop wakes the backoff, ordinary retry still waits, and cancellation propagates.
Six new cases plus the two observed integration tests passed **8 cases**;
**160 passed across 20 controlled rounds**, final affected **615 passed** and
repository **245 passed**. Complete supported init-container regression:
**3819 passed, 47 skipped, 4 warnings**, exit0; bare managed host: **3828 passed,
36 skipped, 2 unchanged orphan failures, 4 warnings**. Whole standard checks pass,
security **0 findings/1895 files**; lock contracts3 pass while actual native hash
verification remains BLOCKED. Keepalive origin and active-session close timing remain
unqualified; #8 stays open. Source/PR/main CI must qualify the final correction.


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
approved Operation. See [Compute Mesh recovery](../operations/compute-mesh/EXECUTION_RECOVERY.md)
and the [Reality fault matrix](../acceptance/REALITY_ARCHITECTURE_AUDIT.md#recovery-and-faults).

## Current deployment assumptions

The accepted Cloud slices use one local durable Governance authority and
Node-owned simulation state. Shared local file/SQLite transactions do not prove
cross-site consistency, distributed consensus or Controller high availability.
Remote secret transport, fleet/federation and physical faults require their
own later acceptance evidence. M3.3-C remains PENDING.
