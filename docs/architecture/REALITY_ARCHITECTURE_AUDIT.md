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
| Delayed signed rejection after credential expiry | A bounded wait may leave Work RUNNING; await the original signed failure, then reconcile FAILED with zero credential resolutions and zero effects. |
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
If a cached Node connection closes during Artifact transfer or Work dispatch,
the existing provider spool retains the request and durable assignment rather
than terminating or rejecting an uncertain effect. Reconnect continues the
same operation identity under the existing at-most-once Node journal.

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

Local acceptance on Python 3.12: 402 directly affected regressions passed and
3 skipped, including all 26 new simulation tests. The full CI-style Python
suite produced 3455 passed, 35 skipped and 9 failed. All nine failures were
also reproduced at the required starting Distribution baseline
`701d053e1bfc97d1e4f77dbd1f1a3fdc89ba3a4e` (135 passed, 9 failed in the
baseline reproduction): read-only default home storage, the managed Python
installation layout, and container orphan-process cleanup. These are not
simulation failures; full-suite local acceptance is not claimed. Ruff,
changed-file formatting, compilation, documentation/link checks and the
existing repository hygiene/security checks passed.

M3.3-C remains PENDING: no USB, serial, ESP32, physical actuator, hardware
timing, power-loss durability, or field acceptance has been demonstrated.

## M3.4-A firmware governance acceptance

The existing [Security Contract](SECURITY_CONTRACT.md#m34-a-operation-governance-audit)
is authoritative for the governance audit and approval semantics. Reality uses
that Gate and Broker rather than a provider-specific authority. A deterministic
Agent Goal produces a Plan that reads the current simulated firmware through a
read-only Distributed Work, detects `1.0.0`, and proposes the high-risk
`device.firmware.update` Operation to `2.0.0`. The original mutation Work persists
at `CREATED` while its Workflow pauses for a durable human approval request.
Approve Once then explicit `resume_plan` continues the same Plan, Workflow and
Work through Node admission, the existing OperationReceipt, a new independent
read Work, EffectVerification `MATCH` and `COMMITTED`. Deny, including after
restart, leaves firmware at `1.0.0` and executes no mutation.

Tests also cover copying human identity claims, legacy approval bypass,
Workflow approval hints, Node-boundary revocation, scope/expiry, audit failure,
restart during approval, effect followed by lost response with subsequent grant
revocation, and missing terminal receipts while a broader grant remains valid.
Reconciliation observes the persisted effect without reexecuting it. Both
`MISMATCH` and `UNKNOWN` remain uncommitted. This firmware simulation changes only
a version field; it does not flash hardware or validate a physical firmware image.

M3.4-A local simulation gate: 687 directly affected tests passed, 3 skipped;
68 Governance/Reality tests passed, including all 42 new governance/firmware
tests. The full suite has 3497 passed, 35 skipped and the nine unchanged local
environment failures reproduced at the M3.4-A starting baseline. See the
[validation record](SECURITY_CONTRACT.md#m34-a-validation-record). M3.3-A PASS,
M3.3-B PASS and M3.3-C Real Hardware Acceptance PENDING remain unchanged.

## M3.4-B credentialed firmware acceptance

The [Security Contract](SECURITY_CONTRACT.md#m34-b-credential-governance-audit)
owns credential policy and the repository-wide credential audit. The existing
firmware Goal/Plan/Workflow acceptance now also runs with an opaque SecretHandle
in its original mutation input. After local Approve Once, the existing Node
admission resolves the credential into a transient provider context, obtains
the existing OperationReceipt, independently observes firmware without the
mutation credential, verifies `MATCH` and reaches Distribution `COMMITTED`.
Lease IDs preserve delivery provenance without exposing values in receipts.

Simulation tests cover provider logs/errors/stdout, captured subprocess output,
Events, Artifact metadata, durable records and scans for fake-secret leakage.
Credential expiry during delay or reconnect blocks mutation. Completed effects
with lost responses reconcile after handle/lease revocation without resolving
again. Missing terminal receipts remain `UNKNOWN` without replay despite a
valid broader grant. These are software simulations, not credentialed physical
firmware flashing or Rust Kernel StepCommit acceptance. Kernel remains unchanged;
M3.3-C Real Hardware Acceptance remains PENDING.

## M5 serial preparation audit

REUSE: DeviceProvider/DeviceTransport, stable Device identity, durable Registry
and lifecycle Events, Node admission, Governance, CredentialBroker, Artifact CAS,
OperationReceipt, independent Observation, EffectVerifier and Recovery remain
the authoritative paths. The legacy DeviceAdapter remains a compatibility
surface; it is not used as a new governed execution path.

EXTEND: `reality/serial.py` prepares SerialTransport and ESP32DeviceProvider,
exported through the public Provider SDK. The optional `reality` dependency uses
pyserial rather than introducing a second serial stack. Host configuration fixes
the local port, Node, transport and public peer key. Discovery does not probe or
grant trust. Signed identification derives Device identity from provider and chip
identity, excluding the transport locator. Registry rediscovery preserves trust
and persisted revocation.

MISSING: physical Jetson/ESP32 enrollment, matching on-device firmware,
power-loss-durable operation evidence, physical firmware mutation, hardware
credential handling, the complete physical acceptance fault matrix, and a second
materially different device family. No physical mutation capability is advertised.

### Prepared wire contract

The draft `apeir.esp32-state/v1` request is newline-terminated JSON containing
exactly `schema`, `kind` (`identify` or `observe`), a fresh `nonce`, and
`stable_identity` (empty only for identification). The reply contains exactly
those fields plus `state_revision` (nonnegative integer), `last_operation_id`
(empty or an identifier), `state` (object), and `signature` (hex Ed25519). The
signature covers the reply without `signature`, encoded as UTF-8 JSON with
sorted keys, compact separators and no nonfinite numbers. A signature proves
possession of the pinned peer key; it grants neither trust nor execution authority.

Frames are bounded to 65536 bytes, one response per request, with a host timeout
of at most ten seconds and no automatic retry. Missing, truncated, duplicate-key,
oversized, stale-challenge, wrong-resource, unsafe or invalid-signature replies
produce failed Observations. Read correlation IDs do not replace fresh wire
challenges. Device, Node and transport bindings are checked before opening the
port. Firmware mutation commands are rejected before I/O.

The default pyserial driver is constructed closed, with flow control disabled;
DTR/RTS are configured false before assigning and opening the fixed port. This
avoids automatically opening with driver defaults. Actual control-line glitches,
USB-bridge behavior and ESP32 reset behavior remain physical qualification items.

### Acceptance boundary

Cloud tests use generated fake signing keys and an in-memory serial fixture.
Passing these tests validates the host contract only. All prepared Devices carry
`hardware_acceptance: PENDING`; M3.3-C and M5 physical acceptance remain PENDING.
Before adding a mutating transport, the existing distributed execution path must
retain uncertain execution evidence and reconcile fresh, independently admitted
state after response loss. A missing receipt must never become permission to
replay an effect. Hardware acceptance must exercise WAN loss, Controller/Jetson
restart, reconnect and locator change, response loss after effect, stale and
tampered observations, and revocation, then repeat with a different device family.

The M5 host-contract preparation run has 27 focused tests and 737 directly
affected regressions passing, including the real OCI reference probe. Full
regression has 3653 passed, 35 skipped and the same nine managed-Cloud baseline
failures recorded at M3.5; none was hidden or rewritten. An initial affected
run concurrent with full regression had 736 passed and one existing missing-
receipt recovery test failure: it observed RUNNING rather than UNKNOWN at its
wait deadline, while effect count remained one. The full run and subsequent
sequential affected run both passed that case; the failed run is retained, not
classified as a confirmed baseline defect. No production recovery logic or
existing assertion was changed to accommodate it.

Ruff, changed-file formatting, compilation, documentation and 245 local link
checks, hygiene, security (zero findings), release-version consistency and the
three component-lock contract tests pass. Installed-wheel public SDK imports
also pass outside the repository under isolated optimized Python. Native
component verification retains the existing missing locked Windows binary
failure. Kernel and its lock remain unchanged. These results qualify software
contract preparation only; physical acceptance remains PENDING.

The first preparation CI runs failed on Windows in a new test's setup/teardown:
pytest's automatically generated ID for the oversized frame exceeded Windows'
32767-character environment-variable limit (`PYTEST_CURRENT_TEST`). Explicit
short case IDs reduce the longest collected test identifier from 65600 to 111
characters while retaining all 27 tests and the same oversized frame and
assertions. Linux/macOS suites and frontend passed in those runs. The original
[Desktop](https://github.com/untrod/apeir/actions/runs/37311108061) and
[Multi-Arch](https://github.com/untrod/apeir/actions/runs/37311108170) failures
remain visible. Corrective CI must pass before the host-contract Gate is reported.

After the ID correction and closed-driver configuration, 28 focused contract
tests and 738 directly affected regressions pass. Full regression has 3654
passed, 35 skipped and the same nine local baseline failures. The installed
public SDK also verifies canonical types and rejects mutation outside the
repository under isolated optimized Python. The initial Windows jobs recorded
3662 passed/29 skipped/two setup-teardown errors (Desktop) and 3374 passed/
29 skipped/272 deselected/two errors (Multi-Arch); these were not hidden by reruns.
