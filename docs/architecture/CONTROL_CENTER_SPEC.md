# Control Plane and Operations Console

## M3.5 architecture audit

Starting Distribution: `26256dd0cef1ca632625cf54a38e72157e676164`.
Kernel remains pinned to `87fd1b2ff28ef14ab1a515a58162592b452fda2e`.

| Existing mechanism | Classification | Required extension |
| --- | --- | --- |
| Runtime API, Control Plane routes and Desktop API bridge | EXTEND | Project authoritative runtime state and delegate mutations to existing Governance. |
| Governance Gate, ApprovalBroker, grants, credential leases and durable audit | REUSE | Preserve Operation bindings, authority checks and execution admission. |
| AgentSession, Workflow, Distributed Work, Node and Reality stores | REUSE | Read actual state and invoke existing lifecycle/recovery paths; never create a console-owned execution system. |
| RuntimeDashboard | EXTEND | Preserve compatibility while exposing distinct Nodes and Devices and evidence-backed health. |
| EventStream and RuntimeEventBus | EXTEND | Provide authenticated realtime transitions and reconnect semantics. |
| Local loopback ControlPlaneAuth | EXTEND | Retain local compatibility; service bearer credentials do not establish human approval authority. |
| MobileApprovalService prototype | REUSE only as compatibility | Default shared secret and in-memory replay tracking are insufficient for trusted remote human authority. |
| Authenticated remote human sessions with durable expiry/replay and audit binding | MISSING | Extend the existing identity/authentication boundary and the canonical Governance authority. |
| Unified responsive Operations Console | MISSING | Build on existing React/Desktop components, real API data and mobile Observe/Approve/Interrupt/Acknowledge flows. |

## Canonical state and controls

`control_plane.operations.OperationsPlane` projects the existing AgentSession,
Workflow, Distributed Work, controller/Node, Reality registry, ApprovalBroker,
GovernanceStore and Artifact CAS. It owns neither execution nor a second state
ledger. A missing controller identity produces UNKNOWN; reading status does
not provision an identity. Persisted Node observations are not proof of a live
connection. Devices are independently identified resources, never renamed Nodes.

The unified response is `apeir.operations/v1`. It contains Agents, Work,
Workflows, Nodes, Devices, Approvals, Grants, Credential leases, Artifacts,
Evidence, Activity, Incidents and Health. Collections are bounded to 500 records.
Grant and credential expiry is exposed as effective status; durable revocation
is preserved. Artifact integrity uses existing CAS verification. Missing or
corrupt components are UNKNOWN and degrade health rather than inventing success.

| Route | Contract |
| --- | --- |
| `GET /api/v1/control/operations` | Authenticated canonical state projection. |
| `GET /api/v1/control/events?since=N` | Durable monotonic transition backfill; `Accept: text/event-stream` provides SSE. |
| `POST /api/v1/control/operations/actions` | Explicit `kind`, `action`, `target_id`; delegates to existing Governance and lifecycle paths. |
| `POST /api/v1/control/human/challenge` | Public bounded PKCE challenge, selected by trusted host configuration. |
| `POST /api/v1/control/human/session` | Single-use code exchange, verified external identity; HttpOnly session cookie. |
| `GET /api/v1/control/human/session` | Restore the current authenticated human session metadata without renewing expiry or issuing authority; service identities are rejected. |
| `POST /api/v1/control/human/nonce` | Bind the authenticated session to one exact method, path and JSON body. |
| `POST /api/v1/control/human/logout` | Revoke the authenticated session; requires a bound nonce. |

Supported mutations are Approve Once, Deny, Interrupt, Reconcile, Revoke and
Acknowledge. Resume is available only when the controller supplies the original
Workflow handlers. Approval never replans; resumption retains the original Plan,
Workflow, Work and Operation. A service bearer, model, Node or provider cannot
establish human approval authority.

Interrupt revokes future admission for the exact Operation, then cancels the
existing Workflow/AgentSession. It does not promise to stop an effect already in
progress. Reconcile invokes existing receipt recovery and cannot execute a
Provider. Reality effect commit still requires an independently obtained fresh
Observation and MATCH. Acknowledging an incident is an audit fact, not resolution.
Acknowledgement is queried from the durable audit for current incident IDs,
independently of the bounded recent Activity window. UNKNOWN and failed Work
cannot be resumed blindly from this surface.

Realtime transitions use the existing durable EventStream, not another event
ledger. Facts are hashed to avoid unchanged-poll noise; event IDs deduplicate
concurrent projection delivery. SSE reauthenticates every batch, supports
Last-Event-ID backfill, and has 32 concurrent streams with bounded 25-second
connections, with a five-second socket write timeout. Clients reconnect; expired/revoked sessions lose access.

## Trusted remote human boundary

[Security Contract](SECURITY_CONTRACT.md#m35-remote-human-boundary) defines the
identity and permission rules. Authlib performs OAuth2 code exchange and PyJWT
verifies signatures from the explicitly configured issuer/JWKS. Human subjects
and permission rules are enrolled by the trusted host owner. Authentication is
not authorization: existing PermissionEngine rules and the Governance Gate
still deny by default. Proof of MFA, recent authentication, audience, issuer,
nonce and signature are required; arbitrary token claims cannot grant authority.
Token exchange rejects redirects: provision the actual canonical token endpoint,
so authorization codes and PKCE verifiers are not forwarded to another location.

On a POSIX controller, provision `.nous/human-identity.json` as an owner-controlled
file. No client secret is needed for this public PKCE client. Required fields:
`issuer`, `client_id`, `redirect_uri`, `authorization_endpoint`, `token_endpoint`,
`jwks_uri`, `subjects`. Endpoints use HTTPS; callback may also use loopback HTTP.
`required_methods` defaults to `["mfa"]`. `permissions` uses existing
Subject/Action/Resource/Context PermissionRule fields. Grant authority requires
explicit `governance.approve`; console actions additionally require
`control.approve_once`, `control.deny`, `control.interrupt`, `control.reconcile`,
`control.revoke`, `control.acknowledge` or `control.resume` for the target resource.
Explicit deny takes precedence. Do not enroll model/service identities as humans.

Use existing Runtime API remote transport protection (TLS or explicitly trusted
private transport). Set `NOUS_CONTROL_ORIGINS` to a JSON list of exact HTTPS
origins; wildcard, embedded credentials and origin paths are rejected. Deploy
console and API on the same site for Secure, HttpOnly, SameSite=Strict cookies.
`NOUS_CONTROLLER_STATE_DIR` and `NOUS_REALITY_STATE_DIR` select existing stores.
The runtime host configuration and its filesystem remain trusted boundaries.
File-based remote identity enrollment is fail-closed on Windows pending verified
configuration ACL support; a trusted embedded host adapter can supply the same
identity contract. Windows desktop can observe a configured remote controller.

## Desktop/Web and mobile

The shared React Operations Console is the default operations surface. It reads
real backend records only and displays unavailable state explicitly. Work,
Nodes, Devices, Approvals, Evidence and Incidents are prioritized; remaining
canonical collections are inspectable. Human actions request a one-use bound
nonce before dispatch and refresh from the server after completion. The console
never guesses mutation success or stores authority in UI state.

Web Crypto creates PKCE proof; verifier/state live only in temporary browser
session storage and are removed at callback. The backend issues a protected
cookie, never a JSON bearer credential. API origin is bound to the login attempt;
changing controllers clears the previous service token. Mobile layout prioritizes
Observe, Approve Once/Deny, Interrupt and Acknowledge with touch-sized controls.
Reload restores current cookie session metadata from the backend. Sign out uses
a request-bound nonce, durably revokes the same session and clears its cookie;
failure is shown rather than claiming confirmed revocation. Restoring a session
does not extend its original expiry. Denied/mismatched callbacks discard local
PKCE state and remove callback parameters from browser history.
Existing chat/developer surfaces remain compatible; the console does not add a
coding IDE. Native packaging is governed by existing Desktop component locks.

## Acceptance limits

Cloud acceptance uses signed deterministic fake identity proofs and stateful
simulated Reality. No production credentials or external IdP account is used.
Real IdP deployment, native binary release qualification and physical-device
acceptance are separate pending acceptance items; no physical success is claimed.

## M3.5-Q qualification preparation audit

Starting main: `d9c642d89930fcb8682aeab91fedf626610a765c`.
Kernel stays `87fd1b2ff28ef14ab1a515a58162592b452fda2e`.

| Existing mechanism | Classification | Qualification work |
| --- | --- | --- |
| Authlib/PyJWT OIDC/PKCE, HumanIdentity and host-enrolled subjects | REUSE | Exercise real library code over verified local TLS with fake IdP material; no password store or identity authority added. |
| GovernanceStore sessions/challenges/nonces, Gate/Broker and durable audit | REUSE | Keep approval, grant and exact Work/Operation owners; stale or duplicate approval remains rejected. |
| Context attestation, subject enrollment and PermissionEngine | EXTEND | Recheck current issuer, enrolled subject, required authentication methods, session expiry/revocation and current permission engine for retained Contexts, including within approval transactions. |
| CORS and canonical Operations routes | EXTEND | Reject an explicit untrusted browser Origin before identity exchange, nonce consumption or governed actions; use the existing origin configuration. Absence of Origin is not identity and cannot bypass authentication/nonce checks. |
| Responsive Console session lifecycle | EXTEND | Restore session metadata after reload and expose durable Sign out; never put cookie material in JSON or browser storage. |
| Real deployed IdP and authenticated human/browser/mobile acceptance | MISSING | Requires actual deployment and a human to perform the approval; fake TLS protocol tests do not satisfy this Gate. |

Four negative cases reproduced the old retained-Context gap before correction:
subject removal, issuer replacement, raised method requirements and permission
engine replacement could still approve. Those facts now fail closed, including
a change between the outer check and approval transaction. No new authority,
credential broker, execution path or verification system is introduced.

The [deployment procedure](../operations/deployment/DEPLOYMENT.md#remote-human-trust-qualification)
specifies the real acceptance evidence still required. Real deployed-human
acceptance remains PENDING until that flow is exercised; qualification preparation
is PARTIAL and does not upgrade that acceptance item.

### Qualification preparation validation

Local affected M3.1–M4 suites: **622 passed**, including the existing real OCI
reference with `python:3.11-slim`. Full repository: **3685 passed, 35 skipped,
9 recorded managed-Cloud baseline failures, 4 warnings**. Repository checks:
**244 passed**; Desktop: **51 tests across 25 files passed**, lint/typecheck/build
passed. Ruff, six changed Python formatting checks, compilation, documentation,
232 Markdown link targets, identity/comment/Git metadata and version checks pass.
Security scan: **0 findings**. Component-lock contract: **3 passed**; actual
native hash verification remains BLOCKED by missing locked Windows binaries.

An initial affected run had **619 passed, 1 skipped, 1 failed**: the unchanged
effect-then-response-lost restart test returned RUNNING at its bounded recovery
deadline instead of COMMITTED. The isolated unchanged main comparison had
**600 passed, 1 skipped**; it did not reproduce that failure. Later affected and
full runs passed that case. Five instrumented runs of the unchanged main's two
parameters produced **9 passed, 1 failed**: the lost-response/no-effect parameter
also returned RUNNING instead of FAILED. The trace recorded its signed FAILED
response at the Controller, with effect count zero. All five effect-then-response-
lost traces had exactly one mutation; no second effect was observed. Instrumentation
was temporary and recorded message types, times, Work IDs and effect counts only.
These observations do not establish the root cause or absence of a persistence
race: [issue #4](https://github.com/untrod/apeir/issues/4) remains open, and both
failures are retained. No timeout/assertion or Reality code was changed to hide
them. These counts are overlapping suites and must not be summed.
