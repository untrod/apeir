# Reality Architecture Audit

Status: M3.3-A foundation PASS; M3.3-B simulation acceptance PASS;
M3.3-C Real Hardware Acceptance PENDING.

## Decision

APEIR already has the authoritative Work, Capability, receipt, Observation,
Verification, Artifact and Node execution paths. The Reality layer therefore
adds a durable resource projection and device-management boundary; it does not
introduce a second execution system.

| Concern | Existing authority | Decision | Foundation work |
|---|---|---|---|
| Work | `node_runtime.distributed_work`, Work Runtime | EXTEND | An `Operation` references an existing `work_id`; effectful simulation Work requires independent verification before commit. |
| Resource | `kernel.resource_model` compute vectors and leases | EXTEND | Add a generic graph projection without changing leases. |
| Node | `connectivity.protocol.NodeIdentity`, Node Runtime | REUSE | Graph nodes reference the existing cryptographic identity. |
| Device | Kernel compute-device model; device manifests; legacy adapters | EXTEND | Add managed-device identity and lifecycle; do not replace compute discovery. |
| Capability | `capability.CapabilityContract` | EXTEND | Add side-effect and observation declarations; retain scheduling fields. |
| Effect | Effect Gate and at-most-once effect bindings | REUSE | Operation records the expected effect; admission remains unchanged. |
| OperationReceipt | Existing `nous.operation-receipt/v1` producers and validators | REUSE | Verification consumes the existing receipt mapping. |
| Observation | `planner.observation.Observation` | REUSE | Device providers return the same authoritative Observation type. |
| Verification | Verification Runtime and deterministic verifiers | EXTEND | Add the narrow `MATCH / MISMATCH / UNKNOWN` effect comparator. |
| Provider | Provider SDK plus device adapters | EXTEND | Add a minimal device-specific discovery/identity/state interface. |
| Transport | Node protocol and specialized transports | MISSING | Add a device transport boundary; a locator is explicitly not identity. |
| Resource relationships | No unified persisted projection | MISSING | Add typed JSON-backed relationships, not a graph database. |

## Resource graph

The first graph contains `Resource` projections of existing or managed objects:

```text
Node --HOSTS--> Device
Node/Device --EXPOSES--> Capability
Node/Device --CONNECTED_TO--> Transport
Capability/Operation --REQUIRES--> Transport/Capability
Device/Operation --OBSERVED_BY--> Observation
```

The store uses the Runtime's established atomic JSON replacement pattern. It is
an index for discovery and reasoning, not a new source of execution authority.

## Node and Device boundary

- A Node is an execution host with the existing cryptographic `NodeIdentity`.
- A Device is a managed real-world resource that may be hosted by a Node.
- A transport locator describes how to reach a Device at this moment.
- USB port numbers, serial paths, network addresses and simulator locators must
  not be used as permanent Device identity.
- Device identity is derived from provider-scoped stable evidence such as a
  manufacturer serial, hardware key or other durable fingerprint.

## Lifecycle and safety

The Device Registry persists these states:

```text
DISCOVERED -> IDENTIFIED -> TRUSTED -> AVAILABLE
                     \-> DEGRADED / OFFLINE / REVOKED
```

`REVOKED` is terminal. Device availability does not grant permission to act;
Capability admission, approval, Kernel routing and receipts remain mandatory.

An effect may auto-commit only when an existing OperationReceipt is bound to
the Operation and an independently acquired Observation yields `MATCH`.
`MISMATCH` and `UNKNOWN` are fail-closed and cannot auto-commit. Receipt and
Artifact verification alone leaves effectful simulation Work at `VERIFIED`.
The store enforces the MATCH requirement at the `COMMITTED` transition.

Transient disconnection preserves the previous lifecycle. Explicit reconnect
restores that lifecycle, including its trust level; it cannot promote an
untrusted Device or revive a `REVOKED` Device. Rediscovery only updates routes
and metadata. Lifecycle transitions publish `reality.device.lifecycle.changed`
and `reality.device.<state>` through the existing `RuntimeEventBus` after
persistence. An AgentSession can subscribe to `reality.device.available` and
set `context.device_id` to ignore events for other Devices. Its durable
subscription wakes `WAITING` to `OBSERVING`; `resume_plan` then continues the
same Workflow run.

## M3.3-B simulated vertical slice

The existing execution chain now covers a hardware-independent mutable device:

```text
AgentSession objective -> deterministic TaskPlan proposal
  -> PlanWorkflowBridge -> WorkflowRuntime
  -> RealityOperationWorkflowHandler -> DistributedWorkflowAdapter
  -> DistributedWork / WorkAssignment -> provider spool -> Node Protocol
  -> NodeRuntimeService -> registered device.state.set handler
  -> verified mutation Artifact CAS input -> SimulatedDeviceProvider
  -> durable Node OperationReceipt -> signed WORKLOAD_STATUS
  -> receipt + Artifact verification -> VERIFIED
  -> separate device.state.read Distributed Work on the assigned Node
  -> fresh authoritative Observation -> EffectVerifier
  -> MATCH: COMMITTED / MISMATCH or UNKNOWN: remain uncommitted
```

`SimulatedDeviceOperationHandler` is a bounded Node handler registered at Node
construction. A Node declares both `device.state.set` and `device.state.read`
in its existing identity. A Device must be `AVAILABLE`, expose the requested
Capability, and match its provider and hosting Node. The Node validates the
Operation/Work and Artifact target bindings before mutation. Mutation inputs
are immutable `artifact://sha256/<digest>` references transferred and verified
through the existing Controller and Node CAS path.

The simulator supports controlled state updates, durable operation identity,
state revision and last-operation evidence, and queued deterministic faults.
`state_dir` persists state, results, mutation counts and remaining fault entries
across restarts. Reusing an operation identity with changed mutation or target
is rejected. Its persistence assumes one Node-owned simulator writer.

The independent observation is a second read-only Work, with its own Node
receipt and signed result. It must name the target, latest mutation identity,
positive state revision and newly requested acquisition identity. An explicitly
stale sample, a repeated sample from an earlier acquisition, conflicting sample
identity, missing receipt or unsuccessful latest observation cannot commit.
Observation identifiers are deduplicated, not counted as extra evidence.

## Recovery and faults

| Injected condition | Required behavior |
| --- | --- |
| Device disconnect/reconnect | Persist lifecycle and publish events; restore previous trust without reviving revocation. |
| Operation failure | Signed failed result; no commit and no automatic mutation retry. |
| Delayed result | Bounded wait; resume consumes the existing persisted result. |
| Duplicate observation | Repeated identity does not establish a fresh acquisition. |
| Stale observation | `UNKNOWN`; a later fresh read can reconcile without repeating mutation. |
| Duplicate receipt | Existing Node-protocol duplicate handling accepts identical facts idempotently. |
| Response lost before effect | Persisted failed outcome; effect count remains zero. |
| Effect occurred, response lost | Node terminal receipt and simulator state survive restart; reconnect returns the recorded result and verification acquires a fresh observation. Effect count remains one. |
| Node terminal journal missing after effect | Existing `EXECUTING` journal returns `RECOVERY_REQUIRED`; Work stays `UNKNOWN`, without mutation replay or a fabricated receipt. |
| Commit interrupted after MATCH | Reverify persisted signed result and CAS evidence, then commit the existing MATCH. |

`SimulationFault` entries are explicitly queued with `inject_fault`. Disconnect
and reconnect are also explicit provider lifecycle controls. Response loss is
injected after terminal Node persistence via `WorkloadResponseLost`, which
closes the connection before `WORKLOAD_STATUS` reaches the Controller. The
tests also interrupt terminal journal persistence to cover the harder missing
receipt window. Recovery reuses existing Node journal, Controller
reconciliation and Workflow checkpoints; it does not issue a new mutation.
The cross-platform fault tests wait for actual Node connection termination
before inspecting the durable receipt or incomplete journal. Relay timeouts
allow filesystem persistence to finish; elapsed milliseconds alone do not
establish that an injected effect or response loss occurred.

Previous non-MATCH verification and Observation Artifacts remain in the CAS
provenance graph when a fresh acquisition produces a new verdict. Binding or
CAS corruption fails closed. No receipt means no automatic commit even if
the observed state happens to match.

## Provenance and acceptance boundary

Operation and Work records bind AgentSession, Plan, Workflow/run/step, Node,
Device, Capability and mutation input Artifact. The mutation Artifact retains
the proposal provenance. Output/evidence CAS records bind the signed receipt;
Observation evidence depends on its independent read Work evidence;
EffectVerification depends on Observation and receipt evidence. Work retains
all evidence references and the current verification. AgentSession receives the
receipt, structured observations and verdict through its existing Workflow
result and observation projection. The resource graph projects Node-hosted
Device, exposed Capability, Operation and Observation relations.

This is Distribution simulation acceptance. Node-local receipts remain
`nous.operation-receipt/v1` and their existing remote projections. Outputs
report `execution_scope=distributed-simulation` and `kernel_traversed=false`.
Distribution `COMMITTED` is not a Rust Kernel `StepCommit`. Kernel revision
`87fd1b2ff28ef14ab1a515a58162592b452fda2e` remains pinned and unchanged.

The simulation gates are the existing pytest contracts and integrations in
`tests/reality`, `tests/node_runtime`, `tests/agent_execution`, Artifact/Event/
Workflow/Verification/Recovery regressions, and the repository's Ruff,
formatting, compile, link, hygiene and security checks. See the existing
[distributed execution](../compute-mesh/DISTRIBUTED_EXECUTION.md) and
[recovery](../compute-mesh/EXECUTION_RECOVERY.md) documentation for the reused
execution contracts.

Local acceptance on Python 3.12: 401 directly affected regressions passed and
3 skipped, including all 25 new simulation tests. The full CI-style Python
suite produced 3454 passed, 35 skipped and 9 failed. All nine failures were
also reproduced at the required starting Distribution baseline
`701d053e1bfc97d1e4f77dbd1f1a3fdc89ba3a4e` (135 passed, 9 failed in the
baseline reproduction): read-only default home storage, the managed Python
installation layout, and container orphan-process cleanup. These are not
simulation failures; full-suite local acceptance is not claimed. Ruff,
changed-file formatting, compilation, documentation/link checks and the
existing repository hygiene/security checks passed.

M3.3-C remains PENDING: no USB, serial, ESP32, physical actuator, hardware
timing, power-loss durability, or field acceptance has been demonstrated.
