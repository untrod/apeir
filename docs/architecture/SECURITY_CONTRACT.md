# Security Contract v1.0

## Authority and scope

The [project constitution](DISTRIBUTION.md) and [State Ownership](STATE_OWNERSHIP.md)
define the Kernel-managed and Distribution runtime-service domains. Model,
Planner, Scheduler, Node, Provider and Resource Graph never grant authority.
Discovery, trust, authorization, execution and effect are separate facts.
Current Operation admission is the four-decision contract below; unknown facts
fail closed. External policy, identity or secret providers cannot replace the
existing authority or approve their own requests.

Current Operation outcomes are exactly:

| Decision | Runtime obligation |
| --- | --- |
| ALLOW | Admit only while all current bound authorization facts remain valid |
| DENY | Block execution |
| REQUIRE_APPROVAL | Durably pause the original Workflow/Work for trusted human authority |
| UNKNOWN | Block execution; unresolved facts never become success |

Only explicit policy may auto-allow registered low-risk read-only Operations.
State mutation requires valid scoped authority; high risk normally requires
trusted human approval. Critical/destructive or unsafe unknown operations are
denied by default. An approval does not replace admission or effect verification.

The initial admission/risk examples below describe legacy generic Runtime modes,
not M3.4+ Operation policy. Operation policy is governed by the
[M3.4-A contract](#m34-a-operation-governance-audit), with current human identity
at the [M3.5 boundary](#m35-remote-human-boundary).

## Ordinary workspace data

Workbench, Chat tools and proposal snapshots reuse the canonical workspace path
guard with private-state protection enabled. Named `.nous`/`.git` paths and
regular files with multiple or unknown links are excluded from ordinary data.
Lists/searches omit refused entries; reads, previews and proposals reject them
before publishing original bytes or a proposal snapshot. Normal single-link
files, directories and not-yet-created write targets retain their contracts.
Trusted internal callers that explicitly omit private-state protection retain
their existing scope; that compatibility mode grants no model permission.

This shared guard admits a static path, not a defense against a malicious OS
owner changing the filesystem after validation. Selected model input additionally
checks descriptor identity/version and link count around its bounded read and
revalidates source and transfer authority at actual dispatch. Models still receive
only admitted ordinary data; neither a filename nor a link supplies permission.

The trusted host may explicitly select `NOUS_PERMISSION_POLICY` under its current
Governance private-state directory. This feeds the existing PermissionEngine;
file existence is not trust, and model/request data cannot select it. POSIX
owner-only, single-link and bounded JSON checks precede admission. Rules are
reloaded for checks; expiration, revocation or invalid state cannot reuse a cached
allow. Conditions require present, exact-typed facts. Inspection reports
configuration and UNKNOWN grants, not an authorization or new authority. Native
Operation approvals, credential leases and execution/effect evidence stay distinct.

## Signed Node identity and trust persistence

The product connectivity audit at Distribution `edb932c` classifies signed
Node Protocol, NodeRuntimeService identity, NodeRelayServer's durable
`trusted-nodes.json`, existing file locks and Work journals as REUSE.
Cross-process read/check/write and first-identity provisioning are EXTEND;
lost enrollment updates, silent key replacement and replacement of incomplete
identities are FIX. The old in-memory Connectivity PairingService remains a
compatibility mechanism; it is not an authority for signed Node enrollment.
One-time signed invitation software now extends this path as described below;
real human identity and multi-network qualification remain separate pending gates.

Trust updates now reload the existing authoritative map under its file lock.
Same-ID/same-key registration is idempotent; a changed key is rejected. Failed
persistence restores the previous in-memory trust, preventing admission of an
unpersisted enrollment. Node and Controller initialization share an identity
file lock and preserve the pinned identity. Partial Node identity or missing
Controller key alongside durable records fails closed before generating a new
key or changing original evidence. Node trust still grants no Capability or
Operation authority; Device lifecycle remains owned by Reality.

Eight controlled contracts fail against the original owners at `edb932c`; their
corrected cases pass. The focused suite has 11 passing cases, including actual
independent-process enrollment and concurrent identity initialization; affected
Node/Governance/Reality/Control Plane/Agent/Workflow regression has 669 passing
cases. Raw identity keys remain protected owner-only files and never enter audit
or ordinary evidence. This is local software durability, not signed remote-human
approval, complete one-time pairing, concurrent Node journal writers, Controller
HA, physical hardware or native Windows installation qualification.


Node first-key publication creates a unique empty temporary file, applies the
existing owner-only permission/ACL boundary before writing private material,
then flushes/fsyncs and atomically publishes it. Permission or write failure
cleans the temporary file without publishing the identity. Ordinary public Node
JSON writes retain their existing behavior. Loaded identities still undergo the
existing key and permission checks. This closes the Node pre-write permission
window; it does not establish remote human identity or authorize an Operation.

## Legacy admission pipeline

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

## Legacy admission decisions

| Decision | Meaning |
|----------|---------|
| `ALLOW` | Proceed normally |
| `DENY` | Reject immediately |
| `REQUIRE_APPROVAL` | Pause until human approves |
| `SANDBOX_ONLY` | Allow but with restricted capabilities |

## Legacy risk examples

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
3. Legacy environment credential configuration is not the governed Operation delivery API
4. Current Operations use opaque SecretHandle references and narrowly scoped Credential leases
5. Raw values are resolved only by the execution boundary with valid existing authorization; they never become ordinary context or durable evidence

## Audit

- Every admission decision is logged
- Every capability execution is logged
- Current governance audit is append-oriented and integrity chained; it does not claim immutable host storage
- Retention and external archival guarantees require their own configured and tested backend
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

## M3.4-B credential governance audit

This audit starts at Distribution `2fdea905729284abe0bc05d414656867b358d3b9`.
Kernel remains pinned to `87fd1b2ff28ef14ab1a515a58162592b452fda2e`.

| Existing authoritative mechanism | Classification | Milestone treatment |
| --- | --- | --- |
| Kernel `SecretRef`, NKI/provider credential references | REUSE | `SecretHandle` aliases the existing reference contract; Kernel and production model dispatch are unchanged. |
| `security/vault.py`, native AES-GCM and owner-only files | EXTEND | Protected backend adapter requires an explicit stable 256-bit master key and restricts the vault file to its owner. No key is persisted in Runtime evidence. |
| Provider environment/keyring/Credential Manager resolver; Desktop credential storage | REUSE | A protected reference backend maps opaque handles to existing configuration references. Legacy compatibility callers retain their contracts. |
| Connector credential scopes and token vaults | REUSE | Existing connector storage remains authoritative; environment deletion alone is not durable revocation. |
| Governance Gate, PermissionEngine, ApprovalBroker, scoped grants and local owner attestation | EXTEND | Operation admission binds the existing AuthorizationContext to the executing Node; the same authority owns handle registration and revocation. |
| GovernanceStore, revocation ledger and append-oriented audit | EXTEND | Handle scope/expiry and one-delivery CredentialLease records live in the existing database and audit chain. |
| Distributed Work, Node journal, Reality handler, Workflow/AgentSession and CAS | EXTEND | Credentials are delivered only inside admitted provider execution; existing recovery and independent verification remain authoritative. |
| Central recursive redaction, EventStream and API envelopes | EXTEND | Exact resolved-value matching also protects logs, exceptions, captured provider output, Node results, Events and durable records; CAS rejects known secret payloads. |
| Operation-scoped credential delivery and terminal delivery revocation | MISSING → implemented | CredentialBroker and transient CredentialContext adapt existing storage and admission; neither creates execution authority. |
| Pending approval list/detail and Once/Deny backend | MISSING → implemented | Existing ApprovalBroker supplies details and decisions; existing API routes delegate to it. |
| Trusted remote human attestation, remote secret transport/rotation, physical device qualification | MISSING / deferred | Service bearer authentication is not human approval. No authenticated remote-human acceptance is claimed. |

### Delivery and recovery contract

Plans, Work, Operation and mutation Artifact inputs may contain only opaque
`secret_handles` identifiers (`secret_` plus 32 hexadecimal characters). Empty
handle lists are omitted from existing canonical requests, preserving prior
authorization digests. Human-controlled registration binds a handle to the
subject, Capability, Node and target resource with an explicit expiry. A revoked
handle cannot be revived by registration, restart, rediscovery or reconnect.

Credential resolution requires the very same active Gate admission and the
Node-origin AuthorizationContext, bound to the original Work and Operation.
Constructed human/node claims, models, planners and providers cannot establish
that admission or issue their own authority. Missing, expired, revoked or
mismatched authorization/handles fail closed. Before resolving, the broker
durably records a unique authorization/handle delivery and its audit evidence;
audit failure prevents delivery. It reacquires the governance transaction and
revalidates authority after committing delivery evidence.

CredentialLease records identify authorization/context, handle, subject, Work,
Operation, Node, Capability, resource and expiry. Their default lifetime is 30
seconds, bounded by handle and grant expiry (maximum configured lifetime 300
seconds). A provider receives only a transient CredentialContext for declared
handles, never the backend or a general resolver. Access and the immediate
effect callback reload current authorization, revocation, lifecycle and lease
expiry. Contexts refuse serialization and close after the call; a unique delivery
binding prevents a second credential delivery for that authorization. Leases
are delivery evidence, never permission for another side effect.

Node journals still precede credential resolution. A completed cached receipt
is reconciled after reconnect without resolving credentials again, even if the
handle and lease have subsequently been revoked. A fresh read-only Observation
does not inherit the mutation's credentials. Only independent `MATCH` commits.
Missing terminal evidence remains `UNKNOWN`, without replay or a second
credential delivery, even while a broader grant remains valid. Disconnected
Nodes cannot resolve expired handles after reconnect; expiry during a provider
delay prevents the effect.

### Redaction and approval backend boundary

Resolved material exists only in protected storage/matcher memory and transient
execution buffers. The central redactor retains exact matchers for late logs
after context closure. Logging records, exception traces, provider errors,
captured stdout/stderr and captured subprocess results, Node outputs/receipts,
Events, audit/API/CLI records and durable Workflow/Work/AgentSession records are
scrubbed. Artifact metadata is scrubbed; byte and streamed file payloads containing
known resolved material are rejected, including a secret spanning read chunks.
Deterministic fake values are used in tests; persisted simulation files and
runtime evidence are scanned for those values, including encrypted backend files.

This is a trusted-host execution boundary, not isolation from arbitrary host
code, raw file-descriptor writes, uncooperative child processes or deliberate
secret encoding. Existing direct provider/environment compatibility paths are
not silently migrated into a second credential authority. Providers must use
captured subprocess output inside the scoped boundary. Production distributed
secret transport, managed key provisioning/rotation and external audit anchoring
require further acceptance; the current slice uses the shared local authority.

`GET /api/v1/approvals` and `GET /api/v1/approvals/{request_id}` expose pending
Operation approvals and their bindings through the existing authenticated API.
The existing `POST /api/v1/approvals/{request_id}/{approve|deny}` delegates to the
same broker. Bearer-authenticated services cannot exercise these human actions;
body identity claims are ignored. Trusted local `nous approval approve` (Once)
and `nous approval deny` remain the accepted human boundary. Approval preserves
the original Plan/Workflow/Work and requires explicit existing workflow resume.

### M3.4-B validation record

Local Python 3.12 validation: **746 passed, 3 skipped** in directly affected
M3.1/M3.2/M3.3/M3.4-A, provider and security regressions. The Governance Core,
credential contracts and Reality suites have **122 passed**, including 34 new
credential/backend tests and seven additional credentialed simulation cases.
The final full suite has **3538 passed, 35 skipped, 9 failed**. All nine failures
reproduce at the required starting Distribution `2fdea905729284abe0bc05d414656867b358d3b9`
(**135 passed, 9 failed** in the four containing modules): read-only default
home storage, managed Python layout and container orphan-process cleanup. These
failures are preserved; local full-suite PASS is not claimed.

Ruff, formatting of all 23 changed/new Python files, compilation, document/comment/
identity/Git-metadata audits and 245 Markdown link checks pass. Security scan has
zero findings. The existing component-lock contract tests have **3 passed**;
the actual native-binary verifier cannot run to completion in this checkout
because locked `desktop/src-tauri/binaries/nousd-x86_64-pc-windows-msvc.exe` is
not staged. The same missing artifact is confirmed at the starting baseline;
no binary, component lock or Kernel source was changed. Relevant existing
Desktop and Multi-Arch CI run after push; native packaging is not qualified by
these local simulation checks.

M3.4-B Credential Governance satisfies the local Distribution simulation gate.
M3.3-A PASS and M3.3-B PASS remain unchanged. M3.3-C physical acceptance,
authenticated remote-human approval and deployment of remote credential
transport/key management remain pending.


## M3.5 remote human boundary

The [Control Plane audit and specification](CONTROL_CENTER_SPEC.md) classifies
existing mechanisms as REUSE / EXTEND / MISSING. Human identity extends the
existing AuthorizationContext and GovernanceStore; no second approval authority
is introduced. External identity adapters establish identity only. The Gate
alone issues grants after explicitly enrolled existing permission policy allows
it. Models, planners, service bearers, Nodes and Providers cannot approve.

OIDC code exchange uses Authlib; configured JWKS signatures, issuer, audience,
nonce, enrolled subject, recent auth_time and MFA methods use PyJWT verification.
PKCE challenge and IdP nonce are durable and single-use; uncertainty during code
exchange cannot license reuse. Session tokens are random, hash-only persisted,
expiry bounded to 15 minutes, and delivered only by Secure HttpOnly SameSite
cookie. Session expiry/revocation is checked again inside approval/grant mutation
transactions. Context object attestation cannot be copied from a serialized claim.
Every retained Context rechecks the current trusted adapter's issuer, subject
enrollment, required methods and permission policy at admission, including the
approval transaction. Removing enrollment or replacing permissions cannot leave
old Context authority active. Re-enrollment on restart also rechecks subjects.
Host file configuration changes require a controller restart to load the new
configuration; use explicit session/grant revocation when immediate fencing is
required. Runtime host configuration
must be owner-controlled; Windows file enrollment fails closed pending verified
ACL support. Real external IdP deployment is not Cloud-qualified.

Every authenticated human mutation (except login/challenge/nonce issuance)
requires a durable, 60-second, one-use nonce bound to session, method, canonical
route and exact JSON body. Changed targets, bodies, paths, sessions and replay
fail closed. Approval audit evidence retains human subject, session and
AuthorizationContext IDs together with existing Operation/Work/resource binding.
Audit and nonce persistence failures do not produce grants. Logging and response
redaction cover OAuth-library token dictionaries before proof validation.

Explicit untrusted browser Origins are rejected on the canonical Operations and
human-session surface before exchange or nonce consumption. Origin allowlisting
reuses configured CORS policy and is an additional browser boundary, never proof
of human identity. No-Origin clients still require valid authentication and the
same bound nonce. OAuth token exchange does not follow redirects. Session lookup
returns current nonsecret metadata without renewing expiry; logout revocation
survives restart and expires the HttpOnly cookie.

Remote control actions also require explicit existing PermissionEngine rules.
Interrupt fences future Operation admission, not already occurring effects.
Reconciliation never grants execution authority; existing Reliability/Reality
journals, receipts and fresh independent Observation remain authoritative.
A valid grant cannot license replay of a possibly completed side effect.

### Legacy approval and Environment UI boundary

The legacy `POST /api/v1/approvals/{request_id}/{approve|deny}` path now uses
`ApprovalBroker.respond_legacy`, the existing Gate human attestation and
GovernanceStore transaction. Service tokens authenticate requests; they cannot
approve them. Body identity claims grant nothing. A valid decision requires the
original persisted ActionProposal, matching recomputed digest, current enrolled
human permissions, bounded request expiry and the existing exact-body one-use
nonce. ActionProposal serialization retains the canonical parameter hash needed
for independent digest reconstruction, without persisting raw parameters. Old
evidence missing that hash is not repaired or implicitly approved. Explicit
untrusted Origins are rejected here too. Human/session/context,
original request/proposal, run/task, Capability and resource identities are
appended to the existing governance audit inside the decision/lease transaction.
Original records, session and permission facts are checked again before commit;
audit failure cannot leave a grant. Trusted local Broker compatibility remains,
without exposing it as an API authority.

Environment UI mutations deliberately use the existing service-authenticated API
channel without human cookies. Human approval uses the separate attested session
and nonce; the original service then resumes exactly the reviewed body. Controller
changes fence that continuation. Deny performs no execution. A lost command
response is displayed as uncertain; the UI does not automatically repeat it.
This is Runtime-service execution, not Kernel evidence or a persistent PTY.

The Operations Workbench embeds the existing EnvironmentInspector; no second
state, provider or executor is introduced. Creation Artifacts now reference a
separate initial contract snapshot in the existing Environment output directory;
mutable lifecycle records remain in their existing state owner. Artifact metadata
`sha256` identifies exact file bytes, while `environment_contract_sha256` retains
the semantic contract digest. Existing run/task identities and byte size are bound
to that Artifact. Lifecycle transitions and restart do not overwrite the original
snapshot. Snapshot failure or an output symlink escape cannot publish an Artifact;
old mutable references remain historical evidence and are not retroactively
repaired. This changes neither environment IDs nor schema/compatibility versions.
The existing Artifact API lists persisted Registry metadata and rejects unknown
IDs instead of returning placeholder availability. Queries remain metadata-only:
registration is not file verification or effect verification. The Environment
view can inspect those scoped records explicitly; it does not fetch or execute
file contents. CAS Work/Receipt evidence remains in its existing scope. Actual sandboxed Chromium/Runtime HTTP
qualification exercised service request, human Approve Once, persisted contract,
start approval and a real fail-closed start error. The fake OIDC fixture does not
qualify a deployed IdP or installed APEIR.exe. The managed Linux host has Docker,
but default OCI engine control still requires the existing strict ProcessSandbox,
which is unavailable here. No fixture runner, host-process fallback, container,
command or scientific report was substituted. Local sandbox diagnostics now
report unavailable isolation without inventing a pending Windows reboot. OCI
static discovery is not engine/containment qualification; PID64 remains unchanged.

Audit classification: **REUSE** Gate/Broker/Store, HumanSessionAuth, PermissionEngine,
RuntimeCapabilityExecutor, EnvironmentRuntime, EventStream and ArtifactRegistry;
**EXTEND** legacy decision admission and the existing workbench entry; **FIX**
service/human channel binding, exact Controller continuation and platform diagnostic;
**DEFER** native Windows installation, deployed IdP, default OCI execution on this
host, interactive PTY and scientific strong-isolation acceptance. Focused evidence
is in `tests/control_plane/test_legacy_approval_identity.py` and existing Environment,
API and Desktop test suites. Product status remains PARTIAL in ROADMAP.

### M3.5 validation record

Local directly affected M3.1–M3.4 and Control Plane regressions: **556 passed,
3 skipped**. Full repository regression: **3582 passed, 35 skipped, 9 failed**.
The same nine failures reproduce at the required starting Distribution
`26256dd0cef1ca632625cf54a38e72157e676164`: **135 passed, 9 failed** in their four
containing modules. They concern read-only default HOME, managed Python paths
and container process cleanup. No unrelated failure is rewritten or hidden.
New identity, control and simulated firmware acceptance coverage contains 44
new Python cases; the Desktop suite has **47 passed in 25 files**.

Ruff, formatting of 15 changed/new Python files, compilation, Desktop lint,
typecheck/build, existing documentation/comment/identity/Git-metadata/security
checks and all 245 current Markdown local-link checks pass. Security scan:
zero findings. Component-lock contract tests: **3 passed**. Native component
verification remains blocked by the baseline missing locked Windows Kernel
binaries; no Kernel sources or component pin change. Relevant existing Desktop
and Multi-Arch CI are checked against the pushed commit, not an earlier SHA.

This qualifies the Distribution software/simulation boundary only. External
IdP deployment, Windows file-based identity enrollment, native binary release
qualification and M3.3-C physical hardware acceptance remain pending.

## M4 external-provider admission

External policy is a restrictive input to the same Operation Gate, never a grant
issuer. ALLOW cannot override Core denial or replace authority; exceptions and
unknown/malformed results fail closed. Providers receive detached facts and policy
is rechecked at the effect boundary. External-agent execution requires an attested
Node context, immutable approved CAS input, at-most-once journal and an explicitly
configured isolated Environment runner. Ordinary agent context receives neither
credentials nor authority objects. A provider-authored approval or completion
claim cannot authorize a device mutation or substitute for independent effect
verification. The [Provider contract and M4 audit](PROVIDER_CONTRACT.md#m4-interoperability-audit)
documents the real OCI reference scope and unexercised integrations.

The OPA Data API reference uses the same restrictive hook. Exact authorization
hash binding prevents acceptance of another request's decision; extra grant or
approval fields and undefined/malformed results fail closed. Only a trusted host
configures the service origin/path. URLs with credentials are rejected, HTTP is
loopback-only, HTTPS verification remains enabled, redirects are refused and
response bodies/socket waits are bounded. Ambient `.netrc` service credentials
are not resolved; platform proxy/CA settings are preserved. No service credential broker or remote
policy identity qualification is claimed. Raw responses/errors are not audit
content; existing audit records contain the verdict and canonical request facts.
Actual OPA process pause/disconnection stops admission/commitment. After an
effect with a lost response, restoring policy availability permits reconciliation
and a new read-only Observation, never a second mutation. A live OPA service and
simulated firmware effect do not qualify real hardware or a remote human IdP.


The OpenBao KV-v2 reference extends the existing protected SecretBackend only;
CredentialBroker retains execution-time authorization, scope, expiry and lease
revocation. Host-provisioned store tokens are explicitly read-only and cannot
issue APEIR authority. No implicit netrc identity or redirect is accepted. Fetched
material is registered centrally before delivery; protected transport diagnostics
are suppressed even before new material is known to the matcher. Backend health
is not permission. Static KV-v2 reads do not qualify dynamic server leases or
production deployment. Lost-response reconciliation consumes persisted evidence
and a fresh independent observation, never another mutation credential resolution.
See the [reference limitations](PROVIDER_CONTRACT.md#m44-openbao-kv-v2-software-reference).

### Skill/Extension acquisition before publication

Installation reuses `ExtensionRegistry`, `SkillRegistry` and the Artifact CAS;
package metadata is not permission and installing never executes package scripts.
The copied package digest must match the inspected source digest before publishing
normalized/supply-chain records, the registry index or the extension lock. A copy
failure or changed content removes the new object and leaves any prior valid
install/index/lock intact. Reuse of an existing object also checks its content
before publishing an install record. Admission and execution still require their
existing authority checks; acquisition does not issue a grant.

Skill catalog JSON files are bounded to 1 MiB, matching the existing HTTPS metadata
fetch limit, to 512 entries and 32 registered sources; nonregular local files are rejected. This bounds metadata reads;
it does not establish trust in a catalog or enable remote package installation.
Remote catalogs remain discovery metadata, not authority or executable content.
The source Operations Console now manages registered local catalogs through the
existing human session, exact-body nonce and Governance permission checks. Review
binds the exact skill ID, version, digest and declared capabilities; changed or
ambiguous entries fail closed. Package paths must remain under the registered
catalog directory. UI/API callers cannot register arbitrary catalogs or URLs.
Passive snapshots never fetch remote catalogs. Remote package acquisition remains
unqualified and is rejected, not delegated to an unrestricted downloader.

The Registry snapshots bounded content and writes CAS evidence before Extension
publication. The CAS reference is bound into the existing Extension index/lock;
legacy Skill artifact references remain readable. Publication revalidates current
human authority after content acquisition. An ordinary failed publication restores
the old index/lock; a hard crash between those files remains fail-closed rather than
being presented as a multi-file atomic transaction. Staged CAS objects may remain
pinned for failure inspection. Disabled state survives updates/restart, and revoked
installed Skills cannot be reenabled by Catalog installation. Invalid CAS evidence
prevents loading. Install/enable/load never executes scripts or issues execution
grants. Human identity, package digest and artifact references use the existing
Governance audit. Actual Operations still require existing Work authorization.

Local software qualification: **17 focused package/authority cases passed**, plus
**594 affected Skill/Extension/Control Plane/repository/public SDK cases passed,
17 skipped**; source Desktop lint/typecheck/build and **65 tests in 25 files passed**.
Sandboxed Chromium using real Runtime HTTP/CAS and a cryptographic fake IdP exercised
review/install/instruction-load/disable/enable/remove, along with live Node pairing
and revocation. These records qualify local source software, not installed Windows,
real remote identity, remote packages, device Operations or physical hardware.
See the [public Skill example](../../examples/hello_skill/README.md) for commands.

### Signed one-time Node enrollment

REUSE the Node/Controller Ed25519 identities, Protocol REGISTER/ACK signatures,
existing trust file/file lock and Governance human/session validation. EXTEND
that same trust document with bounded invitations, exact-key PENDING proofs,
atomic human decisions and persistent revocations. FIX malformed trust files
that previously became an empty registry. No second PairingService, Node trust
store, Work or authority is introduced; legacy in-memory pairing remains outside
canonical signed Node enrollment.

An invitation expires in five minutes, accepts at most five code attempts and
binds the Controller key, request ID and the submitting Node's possession proof.
Only an authenticated enrolled human or attested local OS owner can apply the
exact-key decision. Code possession alone never establishes trust or execution
permission. Consumed codes cannot be reused; a signed status query reconciles
the original request after response loss. Approval and revocation retain their
identity/audit bindings across reload. Revoked identities cannot be revived by
ordinary registration or reconnect. Original Work/effect evidence is preserved.

Public-key and proof metadata live in the existing owner-restricted trust file.
Human decision intents use the existing append-oriented Governance audit before
the atomic file update. An intent is not a persisted-success receipt. Raw codes
are excluded from ordinary API serialization, audit, events, artifacts, CLI
arguments and browser storage; the existing HTTP adapter delivers a typed,
short-lived invitation only after the human gate. General redaction is retained.
See [onboarding operations](../operations/compute-mesh/OPERATIONS.md#one-time-signed-node-onboarding)
for the exact commands, permission scopes, persistence-failure handling and limits.
This software scope does not qualify production remote identity, installed
Windows Desktop, physical hardware, concurrent Node journal writers or HA.

Scoped Cloud validation: 45 pairing/Control Plane tests passed, 714 affected
Node/Governance/Reality/Agent/SDK tests passed, and 8 Workflow/external-workflow
tests passed with 1 real-OCI skip. Repository checks have 262 passed, including
three lock-contract cases. Desktop lint/typecheck/build and 63 tests in 25 files
passed. The earlier full host run had 4,051 passed, 60 skipped and the two recorded
PID1 orphan-cleanup failures; it predates the final two boundary tests and is not
rewritten as a clean full Gate. Required source/main CI evaluates the final SHA.
Sandboxed Chromium also exercised actual Runtime HTTP, signed Node CLI processes,
explicit fake-OIDC human nonce decisions, ONLINE resources and live revocation,
with no mocked Runtime records, page errors or mobile horizontal overflow.
Those are source-browser/fake-identity records, not installed APEIR.exe or real IdP.

### Current Desktop intent during governed mutations

Generic Operations actions and Automation reuse the existing exact-body human
mutation helper. The client checks the captured Controller URL, token and
configuration epoch (including A-to-B-to-A changes), together with its current
human session, before dispatch and before publishing a response. Explicit
reconnect, expiry, logout and unmount invalidate pending client intent. Logout
remains available while an action waits, and clears private displayed content
immediately. Client invalidation does not prove server revocation; uncertain
responses remain explicit and never cause automatic resubmission. Server
Governance, nonce consumption and fresh authorization remain authoritative.


Automation intent publication reuses the same live human/permission check after
acquiring the Workflow writer transaction, before inserting a new original Run
and trigger relation. This complements creation/toggle publication and the
pre/post-transport checks; waiting on SQLite cannot extend a human session or
permission. A rejected check rolls back the new intent. Existing historical reads
remain reads, and the optional trusted-host callback creates no permission or
grant. Governance and Workflow are separate local transactions, not an atomic
cross-database authority; execution still revalidates its own bound authorization.
