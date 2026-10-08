# APEIR roadmap and milestone status

This is the authoritative current status source. **PASS** means the named Gate
was exercised within its stated scope; **PARTIAL** means implemented portions
remain short of the complete Gate; **PENDING** means acceptance/implementation
has not been performed; **BLOCKED** identifies a concrete unavailable prerequisite.
Dated acceptance records describe historical evidence, not current blanket claims.

Master execution baseline: `d95589908f7686210126b75f8033e6bf494f9fb7` on `main`.
The implementation closure audit began at `ff4d7b4f47b5821f05b3c1a6ef2429847a64cf6d`;
the consolidation merge preserved that accepted history. Its 15 published
`milestone/*` checkpoints remain historical evidence, never moving pointers.
Kernel: `87fd1b2ff28ef14ab1a515a58162592b452fda2e` (frozen).

APEIR is an open execution, governance and verification runtime for heterogeneous
intelligence and real-world resources. APEIR 是面向异构智能与现实资源的开放执行、治理与验证运行时。
Codex, Claude, OpenHands, local models, algorithms and humans can supply
intelligence. APEIR owns authority, execution, recovery, observation, verification
and evidence; it does not compete with those agent harnesses. Read the canonical
[constitution and invariants](docs/architecture/DISTRIBUTION.md) before this plan.
Future targets below are requirements, not claims of implemented integrations.

## Closure matrix

| Milestone / acceptance item | Status | Actual evidence and limits |
| --- | --- | --- |
| M3.1 autonomous coordination | PASS | `1e26d5e`: durable AgentSession, TaskPlan→existing Workflow, event wake/resume and Distributed Work; regression suites `tests/agent_collaboration`, `tests/agent_execution`, `tests/node_runtime`. |
| M3.2 reliability | PASS | `c95029d`: durable delivery/journals, restart/disconnect reconciliation, at-most-once effects; `tests/node_runtime` and recovery/reliability suites. Local durable ownership, not HA. |
| M3.3-A Reality foundation | PASS | `701d053`: stable managed Device identity, registry/graph projection, existing Capability/Observation/EffectVerifier; `tests/reality`. |
| M3.3-B simulated Reality | PASS | `935dcb7`: stateful simulated mutation through Work/Node, independent MATCH, deterministic faults/lost response; [Reality evidence](docs/acceptance/REALITY_ARCHITECTURE_AUDIT.md). |
| M3.3-C real hardware acceptance | PENDING | No complete Jetson→ESP32 physical-effect/observation/commit and physical fault evidence. Historical ARM64 host qualification is not this Gate. |
| M3.4-A Governance Core | PASS | `2fdea90`: four deterministic decisions, durable approval of original Work/Operation, scoped grants, revoke/expire/revalidate/audit; `tests/governance`. |
| M3.4-B Credential Governance | PASS | `26256dd`: execution-bound leases and redaction/leakage negatives; existing approval backend; fake Cloud secrets, not a production secret-store qualification. |
| M3.5 Control Plane software | PASS | `242acf8`: canonical-state API, nonce/session/identity-bound governance, realtime transitions, real-data responsive Operations Console; `tests/control_plane` and Desktop tests. [Contract](docs/architecture/CONTROL_CENTER_SPEC.md). |
| M3.5 real IdP / deployed remote-human qualification | PENDING | Signed fake identity proofs exercise the contract. No live production IdP or Windows enrollment ACL qualification is claimed. |
| M3.5-Q remote-human qualification preparation | PARTIAL | Current enrollment/method/permission revalidation, browser Origin admission, cookie session restore/logout and verified fake local TLS protocol tests extend the existing boundary. Real IdP + actual human browser/mobile approval/audit remains PENDING; see [qualification audit](docs/architecture/CONTROL_CENTER_SPEC.md#m35-q-qualification-preparation-audit). |
| M3.6 Developer Platform software | PASS | `6960175`: public canonical SDK, seven conformance suites, protocol/version checks and isolated installed-wheel consumer; [SDK evidence](docs/development/DEVELOPER_PLATFORM.md), `tests/developer_platform`. SDK remains beta, not a production stability promise. |
| Architecture Consolidation Gate | PASS | `070640b`: five canonical documents cover constitution, authority, execution, ownership/failure and Provider model. This consolidation reduces redundant navigation and stale status. |
| M4 Interoperability (complete target) | PARTIAL | Six Provider seams and exercised generic external-agent reference exist; industrial/reference integrations below remain unimplemented/unqualified. |
| M4 generic external-agent / restrictive policy reference | PASS | `05cfbc8`: actual isolated OCI subprocess plus canonical approval/Work/evidence/recovery and simulated downstream Reality; `tests/interoperability`. An external proposal never grants authority. |
| M4.3 OPA Data API software reference | PASS | Real OPA 1.21.1 evaluation through existing restrictive PolicyProvider/Governance, exact-request binding, ambient credential denial, health/errors, approval/credential/Work/Node/evidence and paused-service/lost-response recovery; [reference scope](docs/architecture/PROVIDER_CONTRACT.md#m43-opa-data-api-software-reference). Fake credentials and simulated device effects; authenticated production remote-policy deployment remains PENDING. |
| M4.4 OpenBao KV-v2 software reference | PASS | Real OpenBao 2.7.1 read-only scoped resolution through existing CredentialBroker, expiration/revocation, original firmware approval/denial and response-loss/restart without another credential fetch or effect; [scoped evidence](docs/architecture/PROVIDER_CONTRACT.md#m44-openbao-kv-v2-software-reference). Source/PR and repaired main CI passed; `milestone/m4.4-openbao-kv2-reference` freezes main `c3eeeaca`. Production deployment, rotation and dynamic server leases remain PENDING. |
| M4.6 bounded Ray diagnostic | PARTIAL | Explicit local PID64..256 exception measured actual Ray2.49.2 startup/task/resource/cleanup; existing Governance/Node recovery tests use a bound diagnostic profile. Normal OCI PID64 is unchanged. [Diagnostic scope](docs/architecture/PROVIDER_CONTRACT.md#m46-bounded-ray-qualification-diagnostic); production Ray Provider admission, complete effect verification, remote cluster/GPU/platform qualification remain PENDING. |
| Provider dispatch-admission boundary | PARTIAL | Admission-aware host runner preparation extends the existing supervisor/SDK to revalidate Governance after setup and before task dispatch; [contract and limits](docs/architecture/PROVIDER_CONTRACT.md#dispatch-admission-after-provider-setup). Focused fake-runner tests are not actual Ray integration or production acceptance. |
| M4 authenticated Codex / remaining industrial Providers | PENDING | Codex CLI discovery currently requires authentication; no authenticated service integration is qualified. Ray/Kubernetes, SPIFFE/SPIRE and Viam/ROS/KubeEdge remain unexercised. OPA reference does not complete M4 or authenticate remote human approval. |
| M5 Reality & Hardware (complete target) | PARTIAL | Read-only signed SerialTransport/ESP32 host contracts exist. Physical mutation, firmware persistence and a second device family remain missing. |
| M5 serial/ESP32 host-contract preparation | PASS | `ff4d7b4`: 28 focused tests, bounded signed frames/fresh nonce/stable identity/trust preservation; `tests/reality/test_serial_contract.py`. No firmware-write capability advertised. |
| M5 physical ESP32 write / power-loss acceptance | PENDING | Requires real Jetson/ESP32, firmware/NVS behavior and physical fault-injection evidence. |
| M5 second real hardware family | PENDING | No materially different real device family accepted. |
| M6 Scale & Federation | PENDING | Local locking and federation drafts are not Controller HA, multi-site authority, fleet lifecycle, rolling upgrades, quotas or tenant isolation. Implementation must wait for stable M3–M5 contracts. |
| M7 Open Specification & Verified Reality Benchmark | PENDING | Existing RFCs/CTK and generic evaluation machinery are reusable foundations; no evidence-backed Verified Reality Execution Benchmark or complete open-spec Gate exists. |
| M8 Governed Evolution | PENDING | Long-term reserved target; no autonomous maintenance/deployment acceptance is claimed. |
| Component-lock contract validation | PASS | Existing `tests/repository/test_kernel_component_lock.py`: 3 tests. This checks the lock contract, not native bytes. |
| Native component-lock binary hash validation | BLOCKED | Locked `nousd` and provider-worker Windows x64 binaries are absent. Actual verifier must run before any verified binary release; source CI cannot certify integrity. |

## Execution protocol and immediate governance prerequisite

`main` is the only permanent development branch. Keep one or two active branches
at most; each branch completes one coherent Gate. Start from clean current main:

```text
main → short-lived branch → audit → implementation → tests → semantic commit
     → push → PR → CI → merge commit → scoped checkpoint → delete branch → clean main
```

Every Gate begins with REUSE / EXTEND / MISSING classification of existing
implementation, contracts and evidence. Define invariants, implement the smallest
vertical slice, exercise positive/negative tests and fault injection, then run
affected regressions and full regression where practical. Use existing lint,
format, compile, documentation/link, security, hygiene and component-lock checks.
Report exact results, skips, baseline failures and unavailable prerequisites.
Preserve historical SHAs, verify local/remote HEAD equality and clean worktree.
Only exercised acceptance can be PASS; incomplete work is PARTIAL, PENDING or
BLOCKED. Preparation must never silently upgrade a milestone.

The consolidation environment received administration API 403 responses.
Existing main protection is present, but new rules were not applied. The
maintainer must configure and verify these settings through GitHub:

- Require PRs, required CI and resolved conversations on main; block force push
  and branch deletion. Require zero reviewer approvals for the single maintainer.
- Retain normal merge commits; disable squash/rebase for acceptance history.
  Do not require signed commits until automation signing is proven reliable.
- Protect `milestone/*` and `v*` against update/deletion while permitting creation.
- Require `Core gate`, `Repository checks` and `Frontend Build Validation` with
  current-base validation; change existing contexts only after verifying the
  replacement checks run. See the [settings audit](docs/acceptance/REPOSITORY_CONSOLIDATION.md).

Do not report this administration prerequisite complete without checking the
actual settings. Do not use personal-token workarounds for missing permissions.

## Ordered software qualification and interoperability Gates

Proceed in the order below. External credentials or deployed infrastructure may
block one qualification; retain its explicit status and continue independent
software work where architecture permits. Never substitute fake Cloud tests for
the real acceptance item. All adapters extend the existing
[Provider model](docs/architecture/PROVIDER_CONTRACT.md) and Governance paths.

### M3.5-Q — Remote Human Trust

Branch: `feature/m3.5-remote-human-trust`. Extend the accepted Control Plane,
not a second approval system or password database. Prefer OIDC for the first
real IdentityProvider. Stabilize HumanIdentity, authenticated sessions, session
lifecycle and approval/audit identity binding through existing contracts.

The chain is remote human → authentication → identity → authenticated session →
approval API → Governance → AuthorizationContext → execution. Test unauthenticated,
expired/revoked sessions, wrong user, identity mismatch, replay/CSRF, duplicate or
stale approval and approval after Operation expiry; each must fail closed.
Gate PASS requires a real deployed browser/mobile flow, a genuinely authenticated
human approving the original Operation once, and audit evidence identifying that
human correctly. Fake signed identity proofs validate software only. Qualify
deployment ACLs where relevant; never place production credentials in evidence.

### M4.1 — Authenticated Codex Provider

Branch: `feature/m4-codex-provider`. Map an existing Goal/Work to a supported,
authenticated task interface supplied by Codex. First audit available public APIs and account
capabilities; do not invent a Codex Cloud endpoint or infer integration from CLI
help. Missing credentials or an unavailable task API block that acceptance item.

The Provider returns task ID, status, repository, branch, commit SHA, changed
files, test results, artifacts and execution metadata, bound to canonical Work,
Artifact CAS, evidence and independent verification. Codex may reason, edit,
test and produce artifacts; it cannot approve itself, issue grants or establish
verification authority. Exercise discovery, health/error mapping, provenance,
cancel/recovery and lost-response semantics. PASS requires an actual authenticated
task and verified result through existing Governance; an external success claim
alone cannot commit Work.

### M4.2–M4.7 — Stable Provider roles and exercised reference services

Prefer coherent modules with narrow contracts over one subsystem per adapter.
Keep IntelligenceProvider, ExecutionProvider, PolicyProvider, SecretProvider,
IdentityProvider and DeviceProvider replaceable. Each exercised integration needs
capability discovery, health, error mapping, evidence binding, recovery and public
conformance tests. Provider discovery is not trust or permission.

| Gate | First target and retained APEIR ownership | Acceptance requirement |
| --- | --- | --- |
| M4.2 Provider framework | Extend six existing seams and public SDK; third-party developers should not import internal Runtime modules. | Compatibility and conformance across exercised adapters; contract declarations alone do not qualify services. |
| M4.3 Policy | OPA supplies evaluation input; native Governance retains decisions, approvals, grants and execution admission. | Real service evaluation, unavailable/unknown/malformed fail-closed results and immediate pre-execution revalidation; no policy-to-execution bypass. |
| M4.4 Secret | OpenBao/Vault-compatible backend extends SecretHandle, Broker and Lease semantics. | Real backend storage/resolution/revoke/expiry at the authorized execution boundary; no plaintext in ordinary context, artifacts, receipts or audit, and no replay after an uncertain effect. |
| M4.5 Identity | SPIFFE/SPIRE supplies short-lived workload identity, not Operation authorization. | Real identity issuance/rotation/revocation and reconnect tests while preserving Node identity, trust and Governance semantics. |
| M4.6 Execution | Choose Ray **or** Kubernetes first; reuse Native/OCI and canonical Work. | Real dispatch, evidence, cancellation and fault/recovery flow; external placement cannot grant authority or blindly repeat effects. |
| M4.7 Device ecosystem | Choose one Viam, ROS or KubeEdge reference adapter. | Real ecosystem interaction through existing Device/Operation/Observation contracts, stable identity and revoke-preserving rediscovery; simulated interaction remains simulation. |

Use separate coherent Gates even when related work uses
`feature/m4-policy-secret-identity`; do not merge unrelated adapters as one
uncontrolled diff. `feature/m4-execution-provider` covers one execution backend.

## Engineering blockers before scale and verified releases

Use `fix/baseline-environment-cleanup` (the current branch validator supports
`fix/`, not `chore/`) for supported-development-environment qualification. Address
the nine recorded managed-Cloud failures: MCP interpreter path, read-only HOME,
API/daemon persistence and container orphan cleanup. Reproduce and distinguish
environment requirements from product defects; avoid incidental Runtime refactors.
Gate: zero unexplained failures in documented supported environments, with
unsupported conditions stated explicitly. Existing baseline failures remain
visible until resolved, not permanently accepted or skipped away.
Local qualification now passes the complete initialized-container regression
with **3799 passed, 47 skipped, 4 warnings**; the managed host records **3808
passed, 36 skipped, 2 failed, 4 warnings**. Seven original failures are repaired;
the two orphan assertions require a supported init/reaper, which is independently
verified without Kernel or assertion changes. See the
[configuration and preserved failed probes](docs/development/DEVELOPER_PLATFORM.md#supported-development-environment).
Source/PR and resulting-main Core, Desktop, Multi-Arch and Security all passed;
`milestone/development-environment-qualification` freezes normal merge
`9fe47490dd2bb7c670d7762bdf5de54b4e3f9a1b`. Issue #9 is closed for that scoped
qualification. A bare managed PID 1 is not a qualified process lifecycle environment.

[Recovery timing issue #4](https://github.com/untrod/apeir/issues/4) remains open
for continued cross-platform timing qualification after [PR #7](https://github.com/untrod/apeir/pull/7)
repaired two deterministically reproduced ordering faults. Baseline timing traces and deterministic ACK
interleaving reproduced a real ASSIGNED-snapshot/RUNNING-admission race in both
response-loss cases. The focused repair validates an existing dispatch without
republishing started Work and persists initial dispatch evidence before spool
publication; see [execution recovery](docs/operations/compute-mesh/EXECUTION_RECOVERY.md).
A subsequent main Multi-Arch Windows run exposed a revoked firmware test
expecting terminal projection before signed delivery. Controlled hold/release
coverage distinguishes persisted Node denial, bounded Workflow waiting and
canonical Controller reconciliation; [evidence](https://github.com/untrod/apeir/issues/4#issuecomment-6011144748)
remains open for latency qualification. Reruns passing cannot establish absence
of other races. Preserve original
persisted evidence and no-blind-replay behavior.
Further Windows/controlled legacy-connectivity evidence distinguishes TCP,
WELCOME, cached reconnect session and actual send-queue readiness. Test
synchronization does not repair the legacy early-assignment gap; it remains
[actionable OPEN evidence](https://github.com/untrod/apeir/issues/4#issuecomment-6012448219)
outside the nine original environment failures. The subsequent routing repair
binds a route to actual accepted WELCOME, revalidates before assignment and
preserves successor routes on old-connection EOF; [state semantics](docs/architecture/STATE_OWNERSHIP.md)
remain transport-only. Its source/PR/main CI passed and immutable checkpoint
`milestone/m3.2-delivery-and-stop-recovery` freezes main `583387ea`; #4 remains open
for broader timing qualification.

The separate [Windows relay shutdown timeout #8](https://github.com/untrod/apeir/issues/8)
remains OPEN. Source Core `37552829192` preserved another Windows keepalive-close /
stop timeout (**1 failed, 3818 passed, 40 skipped**). A deterministic reconnect
backoff stop defect is now isolated and narrowly repaired without increasing the
existing stop timeout; [evidence](docs/architecture/STATE_OWNERSHIP.md) and required
final CI (all source/PR and merged-main workflows passed) remain separate from
proving the keepalive timing origin.
[Environment cleanup #9](https://github.com/untrod/apeir/issues/9)
tracks the qualification above and closes only after its checkpoint prerequisites.
The original nine unconfigured Cloud failures remain historical evidence; current configured qualification and its remaining unsupported host
conditions are recorded above, rather than retaining nine failures as permanent
current status.

[Native component-lock issue #2](https://github.com/untrod/apeir/issues/2) requires
the actual pinned binaries, a documented build/download origin and comparison
of their bytes with locked hashes. Contract tests cannot supply this evidence.
Do not change the lock merely to make unavailable binaries pass. A verified
release is false whenever required native hash verification is absent or fails.

## M5 — Physical Reality acceptance

Branch: `hardware/m5-real-acceptance`, only when Jetson Orin Nano and ESP32-S3
are available. Do not expand simulation to imply physical completion. Exercise:

```text
Cloud Controller → Agent → Governance → Credential → Distributed Work → Jetson
                 → ESP32 → physical effect → fresh Observation → MATCH → COMMIT
```

Record real faults: Controller restart, WAN loss, Jetson restart/hard kill,
ESP32 unplug/reboot, USB locator changes, serial response/flash ACK loss, partial
operation, power loss, stale observation, tampered receipt and tampered artifact.
An effect followed by lost ACK must reconcile persisted evidence, observe and
verify; it must never blindly repeat firmware flashing. Receipt alone is not
physical-effect proof. Stable Device identity survives locator changes and
rediscovery never revives revoked resources.

After ESP32 acceptance choose one materially different family, such as a camera,
actuator, PLC or scientific instrument. Gate requires the same canonical
Device/Capability/Operation/Observation/Verification chain and physical fault
evidence. Extensive core changes for that second family indicate the abstraction
still needs stabilization. Hardware blockers are tracked in
[issue #1](https://github.com/untrod/apeir/issues/1); both physical Gates remain PENDING.

## M6 — Scale and Federation

Branch: `feature/m6-federation`, split further if needed for coherent Gates.
Begin implementation only after stable M4 Provider boundaries and accepted M5
real-effect/recovery semantics. Specify consistency requirements before choosing
consensus infrastructure; do not introduce Raft without a concrete requirement.

- **M6.1 Controller HA:** identify single-writer state, immutable evidence and
  eventually consistent projections; prove durable ownership, failover and
  idempotent reconciliation under Controller loss.
- **M6.2 Federation:** preserve local authority, operation, recovery and evidence
  during partition; reconcile state/evidence across sites on reconnect without
  granting authority through synchronization.
- **M6.3 Fleet:** enroll, provision, activate, drain, upgrade, rollback, revoke
  and retire Nodes/Devices with durable lifecycle and safe rolling upgrades.
- **M6.4 Protocol:** negotiate protocol/capability versions and publish a tested
  Controller/Node/Provider compatibility matrix, including mixed-version recovery.
- **M6.5 Isolation:** add justified tenant/resource ownership, policy boundaries,
  quotas and backpressure. Defer speculative enterprise IAM.

## M7 — Specification, conformance and research

Branch: `research/m7-spec-benchmark`. Extend the existing RFC process under
[`docs/rfc`](docs/rfc/README.md), rather than creating another governance hierarchy.
Major contracts require problem, motivation, invariants, proposed contract,
alternatives, failure semantics, security, compatibility, migration and acceptance.
Formalize Work, Operation, Capability, Node, Device, Governance, Authorization,
Evidence, Provider and Recovery specifications from exercised implementations.

Build public provider/node/device conformance entry points with machine-readable
PASS/FAIL/Unsupported reports and reference implementations. A command sketch is
a target, not an available CLI. APEIR-compatible must mean tested contracts.

The Verified Reality Execution Benchmark measures runtime safety and truthful
outcomes under variable intelligence, not model cleverness. Each reproducible
scenario records fault injection, expected invariant, actual evidence and result:
wrong resource, revoked authorization before dispatch, effect with lost ACK,
receipt without effect, stale/tampered observation, Node loss, Controller restart,
expired credentials, duplicate delivery, rediscovery after revocation and a model
claiming success without evidence. Separate simulated and physical results.
Generic evaluation scaffolding alone cannot qualify this Gate.

## M8 — Governed Evolution (reserved)

Do not implement now. The eventual chain is incident → engineering Work →
CodexProvider → patch/tests → Governance → human approval → canary → independent
observation/verification → commit or rollback. Maintenance agents never authorize
their own changes, deployment or success. This is a future Gate, not self-approval.

## Product and developer direction

The real-data Operations Console remains an execution control surface: health,
Agents, Work, Nodes, Devices, Providers, approvals, credentials, artifacts,
evidence, incidents, activity and eventually federation. Show the Work chain
from Goal/Plan through Governance, authorization, placement, execution, receipt,
independent observation, verification and COMMITTED. Mobile focuses on Observe,
Approve Once/Deny, Interrupt and Acknowledge with target, risk, expected effect
and required evidence visible. Do not turn it into a coding IDE or chat clone.

Continue public Work/Node/Device/Provider/conformance SDKs without exposing
internal Runtime dependencies. Providers identify/discover resources, declare
capabilities, execute admitted operations, observe and report health; the Runtime
retains governance, scheduling, recovery, verification and evidence. Keep the five
stable documentation domains and one authoritative status source; historical
tags and Git history replace archive directories and permanent feature branches.

## Release discipline

Distribution remains `0.1.0-rc1`; SDK remains `1.0.0b2` and NKI wrapper `0.1.1`.
There are no published GitHub releases at the audit baseline. Checkpoint tags
preserve evidence and do not create production versions. Do not invent v1.0.
Formal SemVer releases require a sufficiently stable SDK/packaging/compatibility
boundary and [release acceptance](docs/acceptance/RELEASE_RUNBOOK.md), including
actual component hashes, reproducible build metadata, checksums, SBOM and
provenance/attestation where supported. No signing capability is assumed.

Before a formal v0.x release, stabilize exercised M4 Provider/public SDK
compatibility, packaging and physically validated Reality contracts. Future
release Gates include full tests, multi-arch and native Desktop builds, security,
SBOM, checksums, actual native hashes, reproducible provenance, release notes and
a compatibility matrix. Simulated software and hardware evidence remain separate.

**APEIR 1.0 readiness** requires exercised core coordination/reliability,
Governance and Credential Governance; Control Plane and real remote-human trust;
public Developer Platform; authenticated Codex/agent and Policy/Secret/Identity
Providers; real Execution Provider; physical Reality and a second hardware family;
fault recovery, federation, public conformance/specifications, reproducible
Verified Reality Benchmark and verified release/supply chain. Stable upgrade and
security boundaries must be documented. Until those Gates pass, do not claim 1.0
readiness. This roadmap reserves no production version and claims no new Gate PASS.
