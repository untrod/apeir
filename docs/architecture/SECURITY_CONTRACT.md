# Security Contract v1.0

## Admission Pipeline

```
Request
  ↓
Identity          <- Who is making the request?
  ↓
Validation        <- Is the request well-formed?
  ↓
Authentication    <- Are they who they claim to be?
  ↓
Authorization     <- Do they have access to this resource?
  ↓
Permission        <- Does their role allow this action?
  ↓
Policy            <- Does any policy block this?
  ↓
Risk              <- What is the risk level?
  ↓
Admission         <- ALLOW | DENY | REQUIRE_APPROVAL | SANDBOX_ONLY
  ↓
Execution         <- Run with appropriate constraints
  ↓
Audit             <- Record the decision and outcome
```

## Admission Decisions

| Decision | Meaning |
|----------|---------|
| `ALLOW` | Proceed normally |
| `DENY` | Reject immediately |
| `REQUIRE_APPROVAL` | Pause until human approves |
| `SANDBOX_ONLY` | Allow but with restricted capabilities |

## Risk Levels

| Level | Auto-allow? | Requires | Example |
|-------|------------|----------|---------|
| `low` | Yes | None | `model.reason`, `rag.search` |
| `medium` | Yes | Audit log | `file.read`, `web.search` |
| `high` | No | User approval | `file.write`, `device.shell` |
| `critical` | No | Multi-party approval | `device.factory_reset`, `security.policy_change` |

## Permission Model

```yaml
permissions:
  - read:knowledge       # Read knowledge data
  - write:knowledge      # Write knowledge data
  - execute:shell        # Execute shell commands
  - execute:code         # Execute arbitrary code
  - manage:devices       # Register/modify devices
  - manage:providers     # Register/remove providers
  - manage:packs         # Install/remove packs
  - manage:security      # Modify security policies
  - access:secrets       # Read encrypted secrets
```

## Secret Handling

1. Secrets never stored in plaintext in the repository
2. Secrets never logged (auto-masked in audit)
3. Secrets loaded from environment or encrypted vault
4. Provider credentials scoped per-provider, not global

## Audit

- Every admission decision is logged
- Every capability execution is logged
- Logs are append-only, immutable
- Retention: configurable, default 90 days
- Sensitive fields auto-masked before storage

## M3.4-A Operation governance audit

The starting Distribution is `935dcb757ae0a6132fb47762a4a1febf5241fe2b`.
This audit distinguishes execution authority from planning preferences. The
following existing paths were inspected before choosing the extension boundary:

| Mechanism at the starting baseline | Classification | M3.4-A decision |
|---|---|---|
| `governance.gate`, Constitution, risk engine and strict runtime modes | EXTEND | Add deterministic Operation admission to the same `ExecutionAuthorizationGate`; retain legacy evaluation modes. |
| `governance.broker`, `approval`, CLI and durable approval tables | EXTEND | Add exact-Operation Approve Once / Deny; legacy broker/manager entry points cannot approve these records. |
| `governance.contracts.AuthorizationContext`, identity registry, enterprise RBAC and `permission` | REUSE | Establish identity at the trusted CLI boundary; apply configured permission deny rules, never accept model-supplied identity claims as human authority. |
| Authorization leases, consumption and revocation in `governance.store` / `lease` | EXTEND | `CapabilityGrant` extends `AuthorizationLease` in the existing table, with explicit scope, expiry, subject and Node binding. |
| Capability 2.0 registry, manifests, resolver, availability and sandbox checks | EXTEND | Register simulated state read/write and firmware update metadata; use the registry's current risk, side effects, idempotency and verification declarations. |
| Agent profile policy and sandbox bindings | REUSE | Agent capability selection does not issue grants; all nonhuman approval contexts fail closed. |
| Intelligence/workspace policies, shadow policy, optimizer and planner decisions | REUSE | Planning preferences and proposed policies remain advisory; they do not replace governance authority. |
| AgentSession coordinator, Plan bridge and durable Workflow pause/resume | EXTEND | Project a real durable approval ID and pause the original handler step; resume its unchanged Plan, run and Work. |
| Distributed Work, signed Node envelopes, receipt binding and M3.2 journals | REUSE | Schedule only after admission; Node rechecks authority before the effect; cached/incomplete journals precede handler execution. |
| Reality DeviceRegistry, lifecycle events, stable identity and simulator | EXTEND | Govern mutation and independent read Work; add a version-only simulated firmware mutation. Rediscovery never grants authority. |
| Artifact CAS, Observation, EffectVerification and Recovery Runtime | REUSE | Mutation and evidence provenance remains in the existing CAS; only an independent `MATCH` permits commit. |
| Kernel identity/grants/SecretRef, NKI gateways and Effect Gate | REUSE | Preserve the pinned Kernel boundary and all existing production routing; Distribution simulation does not claim Kernel traversal. |
| Governance audit chain and runtime execution-boundary/security audits | EXTEND | Append Operation policy, approval, grant, authorization, admission and verification evidence in the existing audit table. |
| Mobile approval signed-token prototype | REUSE | Retain its existing contracts; it is not a remote human attestation path for these Operation requests. |
| Network egress policy, workspace isolation, extension/pack/plugin admission, private-file security and API bearer authentication | REUSE | Keep their restrictions; bearer service authentication is not a human approval credential. |
| Operation-bound durable request, deterministic four-decision projection and typed lease scopes | MISSING | Add the smallest contracts in `governance.operation_contracts`; persist bindings alongside the existing store. |
| Remote human attestation, credential broker and physical firmware transport | MISSING | Outside M3.4-A; credential brokerage remains M3.4-B and physical-device qualification remains M3.3-C. |

### Operation decisions and policy

The Operation projection has exactly `ALLOW`, `DENY`, `REQUIRE_APPROVAL` and
`UNKNOWN`. Both `DENY` and `UNKNOWN` block execution. This narrower contract
coexists with the legacy admission modes above for backward compatibility.
`Policy` reuses the existing `ApprovalPolicy`; no second policy authority is
introduced. An explicit default `reality-read-only-v1` policy permits only
registered, low-risk, idempotent, read-only `device.state.read` Operations.
State writes require explicit scoped authority even when declared low risk.
High-risk `device.firmware.update` requires authority. Unknown capabilities,
critical risk and destructive/unknown side effects are denied. Changed trusted
metadata, missing mutation verification, unresolved required permissions or
unavailable governance persistence fail closed. Configured PermissionEngine
deny rules precede grants and automatic read policy.

A `GovernanceRequest` binds Work/Operation identity, AgentSession, Plan,
Workflow run, subject, Node, Capability, Device, expected effect and input CAS
references. Its canonical hash is the authorization ID. Reusing an Operation
ID with changed bindings is rejected. Capability metadata comes from the
trusted registry, never from a planner's risk claim.

### Persistent grants and minimal human control

| Scope | Matching authority |
|---|---|
| `ONCE` | One admission of the exact immutable authorization ID. |
| `WORK` | The named Work, subject, Capability, resource and bound Node. |
| `SESSION` | The named AgentSession, subject, Capability, resource and bound Node. |
| `RESOURCE` | The named resource, subject, Capability and bound Node. |
| `CAPABILITY` | The named Capability and subject, retaining any explicit Node restriction. |

All scopes have a bounded expiration and use limit. The runtime supports them
for trusted control-plane use; the milestone's human approval actions expose
only Approve Once and Deny through the existing `nous approval` CLI. Approval
expires after one hour. A pending request pauses Work before scheduling, at
`CREATED`, in the existing durable Workflow `WAITING_APPROVAL` state. The
AgentSession's existing `WAITING` state projects the real approval request ID.
Approving atomically records the response and issues a one-use lease. The
coordinator's existing `resume_plan` resumes the same workflow; approval does
not call the planner. Workflow `approved_steps` hints never grant Operation
authority. Deny remains durable and prevents any Device mutation.

The trusted local CLI establishes an ephemeral owner-context attestation that
is not serialized with AuthorizationContext. Constructed/copied claims,
remote contexts, bearer-authenticated services, models, planners, schedulers,
Nodes, providers, agents and Operations cannot issue grants or respond to
Operation approvals. The local host and trusted control-plane implementation
remain part of the security boundary; this is not isolation against arbitrary
code running as the host owner. No remote human approval UI is claimed.

### Admission, revocation and recovery

Immediately before a Node effect, admission reloads current policy metadata,
permissions, approval status, expiry, grant consumption and resource revocation,
and checks the Device's current lifecycle. The simulator invokes the same
transaction-bound revalidation immediately before changing state, including
after injected provider delay; expiration during that delay blocks the effect. Lease consumption and admission
audit evidence commit before the effect. A second immediate SQLite transaction
rechecks authorization and lifecycle, and serializes the effect with governance
revocation. Revocation records are permanent; replacing a legacy lease row,
restart, rediscovery or reconnect cannot clear them. Device lifecycle
revocation separately remains terminal in DeviceRegistry.

The existing Node journal records `EXECUTING` before handler admission. Recovery
reads that journal first. A cached terminal receipt is reconciled without a new
side effect or grant consumption, followed by a fresh independent observation.
An incomplete journal remains `UNKNOWN` without replay, even with another valid
grant. A revoked/consumed grant does not prevent reconciling an already completed
operation's receipt. Receipt loss without sufficient persisted evidence cannot
produce an automatic commit. Approval is authority to attempt the original
Operation, never evidence that its effect occurred.

The existing append-oriented SQLite audit records policy evaluation,
authorization verdicts, approval request/decision, grant issuance/revocation,
resource revocation, execution admission/denial and effect verification. Evidence
includes authorization, actor/context, AgentSession, Plan/run, Work/Operation,
Capability, Node, Device, input Artifact and receipt/observation references where
available. Audit append and lease consumption share a transaction; audit failure
blocks admission. The existing hash chain is serialized across store instances.
It is local evidence, not externally anchored or tamper-proof storage against a
host administrator.

The firmware payload contains only a semantic version. Existing recursive
redaction checks reject recognized plaintext credentials before Reality Plan,
CAS mutation input or GovernanceRequest persistence. No SecretHandle is needed
for this slice; the existing Kernel `SecretRef` remains unchanged. This does not
claim a complete credential broker or detection of arbitrary disguised secrets.

### M3.4-A validation record

The local Governance Core simulation gate passes on Python 3.12: **687 passed,
3 skipped** in directly affected M3.1/M3.2/M3.3 and security regressions. Within
that coverage, Governance/Reality has **68 passed**: 31 new governance tests and
37 Reality tests (26 retained M3.3-B tests plus 11 new approval/firmware boundary
tests). The final full suite reports **3497 passed, 35 skipped, 9 failed**.
Those same nine failures reproduce at the required starting Distribution
`935dcb757ae0a6132fb47762a4a1febf5241fe2b`: **135 passed, 9 failed** in the four
containing test modules. They concern read-only default home storage, the
managed Python installation layout and container orphan-process cleanup;
full-suite local PASS is not claimed and the failures were not hidden or rewritten.

Ruff, formatting of all 16 changed/new Python files, compilation, the existing
Markdown link/document/comment/repository-identity/Git-metadata audits, security
scan and component-lock tests pass. The link check covers 245 current Markdown
files; the security scan reports zero findings. Relevant existing Desktop and
Multi-Arch CI run against the milestone commit after push. Acceptance here is
Distribution simulation only; remote human attestation, credential brokerage
and physical firmware acceptance remain outside this gate.
